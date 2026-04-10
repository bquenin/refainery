"""Prompt templates for Claude analysis of failure clusters."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from refainery.models import FailureCluster

# Module-level temp dir so CSV files persist for the duration of the process.
_TEMP_DIR: Path | None = None


def _get_temp_dir() -> Path:
    global _TEMP_DIR
    if _TEMP_DIR is None:
        _TEMP_DIR = Path(tempfile.mkdtemp(prefix="refainery-"))
    return _TEMP_DIR


def write_occurrences_csv(cluster: FailureCluster) -> Path:
    """Write all occurrences to a CSV file and return the path."""
    safe_name = f"{cluster.skill}__{cluster.tool}__{cluster.failure_type}.csv".replace("/", "-").replace(":", "-")
    path = _get_temp_dir() / safe_name
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "provider", "tool", "command", "arguments",
            "output", "success", "next_action",
        ])
        for inv in cluster.occurrences:
            writer.writerow([
                inv.timestamp.strftime("%Y-%m-%d %H:%M"),
                inv.provider,
                inv.tool_name,
                inv.command or "",
                _truncate_dict(inv.arguments),
                inv.output or "",
                inv.success,
                inv.next_action or "",
            ])
    return path


def build_cluster_analysis_prompt(cluster: FailureCluster, csv_path: Path) -> str:
    """Build the analysis prompt for a single failure cluster."""

    first = cluster.first_seen
    last = cluster.last_seen
    if first and last:
        span_days = (last - first).days
        if span_days == 0:
            lifespan = "same day"
        elif span_days == 1:
            lifespan = "1 day"
        else:
            lifespan = f"{span_days} days"
        timespan_line = f"- **First seen**: {first.strftime('%Y-%m-%d')}\n- **Last seen**: {last.strftime('%Y-%m-%d')} ({lifespan} span)"
    else:
        timespan_line = "- **Timespan**: unknown"

    return f"""You are analyzing a failure cluster from AI coding agent conversations. Your goal is to provide a clear, actionable analysis that helps improve the skill instructions.

## Failure Cluster

- **Skill**: {cluster.skill}
- **Tool**: {cluster.tool}
- **Failure type**: {cluster.failure_type}
- **Frequency**: {cluster.frequency} occurrences
- **Providers affected**: {', '.join(sorted(cluster.providers))}
{timespan_line}

## Data

All {cluster.frequency} failure occurrences are in: `{csv_path}`

The CSV has these columns:
- `timestamp` — when the failure occurred (YYYY-MM-DD HH:MM)
- `provider` — which AI agent (claude, cursor)
- `tool` — the tool that was invoked
- `command` — shell command if applicable
- `arguments` — tool arguments (may be truncated)
- `output` — tool output / error message
- `success` — True/False
- `next_action` — what the agent did next

Use your tools to read and analyze the CSV. You can use Bash to run data analysis commands (csvtool, awk, grep, sort, uniq, wc, python one-liners, etc.) to slice the data however you need.

## Instructions

Analyze the full set of failures and provide:

1. **What's going wrong** — describe the pattern you see across all occurrences. What is the agent doing, and why is it failing or being inefficient? Group by common error patterns if there are distinct sub-categories.

2. **Root cause** — why does this keep happening? Is it a gap in the skill instructions, wrong tool usage, a limitation of the CLI tool, or something else?

3. **Trend analysis** — is this getting better or worse over time? Are there time periods with spikes? Any correlation with specific providers?

4. **Suggested fix** — provide specific, concrete changes. If the fix is a SKILL.md update, write the exact text to add. If it's a workflow change, describe the steps.

Be concise and actionable. Focus on what would prevent these failures from recurring."""


def _truncate_dict(d: dict, max_len: int = 300) -> str:
    s = str(d)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
