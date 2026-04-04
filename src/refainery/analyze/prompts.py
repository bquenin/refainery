"""Prompt templates for Claude analysis of failure clusters."""

from __future__ import annotations

from refainery.models import FailureCluster


def build_cluster_analysis_prompt(cluster: FailureCluster) -> str:
    """Build the analysis prompt for a single failure cluster."""

    # Select representative examples (up to 5)
    examples = cluster.occurrences[:5]

    examples_text = ""
    for i, inv in enumerate(examples, 1):
        output_preview = inv.output[:500] if inv.output else "(no output)"
        examples_text += f"""
### Example {i}
- Provider: {inv.provider}
- Tool: {inv.tool_name}
- Command: {inv.command or '(not a shell command)'}
- Arguments: {_truncate_dict(inv.arguments)}
- Output (first 500 chars): {output_preview}
- Success: {inv.success}
- Next action: {inv.next_action or 'unknown'}
"""

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

## Representative Examples
{examples_text}
## Instructions

Analyze these failures and provide:

1. **What's going wrong** — describe the pattern you see in the examples. What is the agent doing, and why is it failing or being inefficient?

2. **Root cause** — why does this keep happening? Is it a gap in the skill instructions, wrong tool usage, a limitation of the CLI tool, or something else?

3. **Suggested fix** — provide specific, concrete changes. If the fix is a SKILL.md update, write the exact text to add. If it's a workflow change, describe the steps.

Be concise and actionable. Focus on what would prevent these failures from recurring."""


def _truncate_dict(d: dict, max_len: int = 300) -> str:
    s = str(d)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
