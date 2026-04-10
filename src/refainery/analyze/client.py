"""Claude Agent SDK client for failure cluster analysis."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import ResultMessage

from refainery.analyze.prompts import build_cluster_analysis_prompt, write_occurrences_csv
from refainery.models import FailureCluster


SYSTEM_PROMPT = """\
You are an expert at analyzing AI coding agent failure patterns. \
You have access to tools to read and analyze CSV data files containing failure occurrences. \
Use your tools to thoroughly explore the data before drawing conclusions. \
Use markdown formatting for readability.\
"""


@dataclass
class AnalysisSession:
    """Result of analyzing a single cluster, with session ID for resumption."""

    cluster: FailureCluster
    text: str
    session_id: str


async def _query_agent(prompt: str, csv_path: Path) -> tuple[str, str]:
    """Send a prompt to Claude via the Agent SDK.

    Returns (response_text, session_id).
    """
    options = ClaudeAgentOptions(
        model="sonnet",
        allowed_tools=["Read", "Bash", "Grep", "Glob"],
        permission_mode="bypassPermissions",
        system_prompt=SYSTEM_PROMPT,
        add_dirs=[str(csv_path.parent)],
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)

        parts: list[str] = []
        session_id = ""
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                session_id = message.session_id
            elif hasattr(message, "content") and isinstance(message.content, list):
                for block in message.content:
                    if hasattr(block, "text") and block.text:
                        parts.append(block.text)

        return "".join(parts), session_id


async def _analyze_one(
    index: int,
    cluster: FailureCluster,
    semaphore: asyncio.Semaphore,
    on_start: Callable[[int], None] | None = None,
    on_done: Callable[[int], None] | None = None,
) -> AnalysisSession:
    """Analyze a single cluster and return the session."""
    async with semaphore:
        if on_start:
            on_start(index)
        csv_path = write_occurrences_csv(cluster)
        prompt = build_cluster_analysis_prompt(cluster, csv_path)
        text, session_id = await _query_agent(prompt, csv_path)
        if on_done:
            on_done(index)
        return AnalysisSession(cluster=cluster, text=text, session_id=session_id)


def analyze_clusters_parallel(
    clusters: list[FailureCluster],
    max_clusters: int = 20,
    concurrency: int = 3,
    on_start: Callable[[int], None] | None = None,
    on_done: Callable[[int], None] | None = None,
) -> list[AnalysisSession]:
    """Analyze clusters in parallel (bounded concurrency), returning sessions with IDs for resumption."""
    to_analyze = clusters[:max_clusters]

    async def _run() -> list[AnalysisSession]:
        sem = asyncio.Semaphore(concurrency)
        return await asyncio.gather(
            *[_analyze_one(i, c, sem, on_start, on_done) for i, c in enumerate(to_analyze)]
        )

    return asyncio.run(_run())
