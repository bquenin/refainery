"""Prompt templates for Claude analysis of failure clusters."""

from __future__ import annotations

from refainery.models import FailureCluster


def build_cluster_analysis_prompt(cluster: FailureCluster, skill_md_content: str | None = None) -> str:
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

    skill_section = ""
    if skill_md_content:
        skill_section = f"""
## Current SKILL.md content

```markdown
{skill_md_content[:3000]}
```
"""

    return f"""You are analyzing a failure cluster from AI coding agent conversations to identify root causes and suggest improvements to skill instructions.

## Failure Cluster

- **Skill**: {cluster.skill}
- **Tool**: {cluster.tool}
- **Failure type**: {cluster.failure_type}
- **Frequency**: {cluster.frequency} occurrences
- **Providers affected**: {', '.join(sorted(cluster.providers))}

## Representative Examples
{examples_text}
{skill_section}
## Instructions

Analyze these failures and respond with a JSON object (no markdown fences) containing:

1. **root_cause**: A brief classification of the root cause. Examples:
   - "missing_instructions" — SKILL.md doesn't cover this scenario
   - "wrong_parameters" — agent uses wrong flags or arguments
   - "output_parsing" — agent can't parse the tool's output format
   - "tool_limitation" — the CLI tool itself has a bug or limitation
   - "context_gap" — agent lacks necessary context about the environment
   - "retry_without_learning" — agent retries the same approach without adapting

2. **severity**: "high" (blocks task completion), "medium" (causes delays), or "low" (minor inefficiency)

3. **skill_md_suggestion**: If the root cause is addressable by updating SKILL.md, provide the specific text to add or change. null if not applicable.

4. **cli_tool_suggestion**: If the root cause is in the CLI tool itself, describe the change needed. null if not applicable.

5. **explanation**: 2-3 sentences explaining WHY this failure happens and how the suggested fix would prevent it.

Respond with ONLY the JSON object."""


def _truncate_dict(d: dict, max_len: int = 300) -> str:
    s = str(d)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
