"""Anthropic SDK client for failure cluster analysis."""

from __future__ import annotations

import json

import anthropic

from refainery.analyze.prompts import build_cluster_analysis_prompt
from refainery.models import AnalysisResult, FailureCluster


class AnalyzerClient:
    """Wraps the Anthropic SDK to analyze failure clusters."""

    def __init__(self, model: str = "claude-sonnet-4-20250514") -> None:
        self.client = anthropic.Anthropic()
        self.model = model

    def analyze_cluster(self, cluster: FailureCluster) -> AnalysisResult:
        prompt = build_cluster_analysis_prompt(cluster)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract text response
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text

        # Parse JSON response
        try:
            # Strip markdown fences if present
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                if cleaned.endswith("```"):
                    cleaned = cleaned[: cleaned.rfind("```")]
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return AnalysisResult(
                cluster=cluster,
                root_cause="parse_error",
                severity="low",
                explanation=f"Could not parse LLM response: {text[:200]}",
            )

        return AnalysisResult(
            cluster=cluster,
            root_cause=data.get("root_cause", "unknown"),
            severity=data.get("severity", "low"),
            skill_md_suggestion=data.get("skill_md_suggestion"),
            cli_tool_suggestion=data.get("cli_tool_suggestion"),
            explanation=data.get("explanation", ""),
        )
