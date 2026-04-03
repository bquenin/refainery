"""Markdown report generation."""

from __future__ import annotations

from refainery.models import AnalysisResult


def render_markdown(results: list[AnalysisResult]) -> str:
    """Render analysis results as a Markdown report."""
    lines: list[str] = []

    total_freq = sum(r.cluster.frequency for r in results)
    by_severity: dict[str, int] = {}
    for r in results:
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1

    lines.append("# Refainery Analysis Report\n")
    lines.append(f"- **Clusters analyzed**: {len(results)}")
    lines.append(f"- **Total failure occurrences**: {total_freq}")
    for sev in ("high", "medium", "low"):
        count = by_severity.get(sev, 0)
        if count:
            lines.append(f"- **{sev.upper()}**: {count}")
    lines.append("")

    # Summary table
    lines.append("## Failure Clusters\n")
    lines.append("| Severity | Skill | Tool | Type | Freq | Root Cause | Providers |")
    lines.append("|----------|-------|------|------|------|------------|-----------|")

    for r in results:
        providers = ", ".join(sorted(r.cluster.providers))
        lines.append(
            f"| {r.severity.upper()} | {r.cluster.skill} | {r.cluster.tool} | "
            f"{r.cluster.failure_type} | {r.cluster.frequency} | {r.root_cause} | {providers} |"
        )
    lines.append("")

    # Suggestions
    actionable = [r for r in results if r.skill_md_suggestion or r.cli_tool_suggestion]
    if actionable:
        lines.append("## Actionable Suggestions\n")
        for i, r in enumerate(actionable, 1):
            lines.append(f"### {i}. [{r.severity.upper()}] {r.cluster.skill}/{r.cluster.tool}\n")
            lines.append(f"**Failure type**: {r.cluster.failure_type} (freq={r.cluster.frequency})")
            lines.append(f"**Root cause**: {r.root_cause}\n")
            lines.append(f"{r.explanation}\n")

            if r.skill_md_suggestion:
                lines.append("**SKILL.md suggestion:**\n")
                lines.append(f"```\n{r.skill_md_suggestion}\n```\n")

            if r.cli_tool_suggestion:
                lines.append("**CLI tool suggestion:**\n")
                lines.append(f"{r.cli_tool_suggestion}\n")

    # Cross-provider correlation
    correlations: dict[tuple[str, str], dict[str, bool]] = {}
    for r in results:
        key = (r.cluster.skill, r.cluster.tool)
        if key not in correlations:
            correlations[key] = {}
        for p in r.cluster.providers:
            correlations[key][p] = True

    multi_provider = {k: v for k, v in correlations.items() if len(v) > 1}
    if multi_provider:
        lines.append("## Cross-Provider Correlation\n")
        lines.append("| Skill/Tool | Claude | Cursor | Likely Cause |")
        lines.append("|------------|--------|--------|--------------|")
        for (skill, tool), providers in sorted(multi_provider.items()):
            claude = "Y" if "claude" in providers else "N"
            cursor = "Y" if "cursor" in providers else "N"
            if "claude" in providers and "cursor" in providers:
                cause = "Skill/CLI tool itself"
            elif "claude" in providers:
                cause = "Claude-specific"
            else:
                cause = "Cursor-specific"
            lines.append(f"| {skill}/{tool} | {claude} | {cursor} | {cause} |")
        lines.append("")

    return "\n".join(lines)
