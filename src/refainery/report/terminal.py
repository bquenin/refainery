"""Rich-based terminal report output."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from refainery.models import AnalysisResult

SEVERITY_COLORS = {"high": "red", "medium": "yellow", "low": "green"}


def render_terminal(results: list[AnalysisResult]) -> None:
    """Render analysis results directly to the terminal."""
    console = Console()

    if not results:
        console.print("[dim]No failure clusters found.[/dim]")
        return

    # Summary stats
    total_freq = sum(r.cluster.frequency for r in results)
    by_severity: dict[str, int] = {}
    for r in results:
        by_severity.setdefault(r.severity, 0)
        by_severity[r.severity] += 1

    console.print()
    console.print("[bold]Refainery Analysis Report[/bold]")
    console.print(f"  Clusters analyzed: {len(results)}")
    console.print(f"  Total failure occurrences: {total_freq}")
    for sev in ("high", "medium", "low"):
        count = by_severity.get(sev, 0)
        if count:
            color = SEVERITY_COLORS[sev]
            console.print(f"  [{color}]{sev.upper()}[/{color}]: {count}")
    console.print()

    # Results table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Severity", width=8)
    table.add_column("Skill", max_width=15)
    table.add_column("Tool", max_width=25)
    table.add_column("Type", max_width=18)
    table.add_column("Freq", justify="right")
    table.add_column("Timespan", max_width=25)
    table.add_column("Root Cause", max_width=22)
    table.add_column("Providers", max_width=14)

    for r in results:
        color = SEVERITY_COLORS.get(r.severity, "white")
        table.add_row(
            Text(r.severity.upper(), style=color),
            r.cluster.skill,
            r.cluster.tool,
            r.cluster.failure_type,
            str(r.cluster.frequency),
            r.cluster.timespan or "[dim]—[/dim]",
            r.root_cause,
            ", ".join(sorted(r.cluster.providers)),
        )

    console.print(table)

    # Detailed suggestions
    actionable = [r for r in results if r.skill_md_suggestion or r.cli_tool_suggestion]
    if actionable:
        console.print()
        console.print(f"[bold]Actionable Suggestions ({len(actionable)})[/bold]")
        console.print()

        for i, r in enumerate(actionable, 1):
            color = SEVERITY_COLORS.get(r.severity, "white")
            ts = f", {r.cluster.timespan}" if r.cluster.timespan else ""
            console.print(f"[bold]{i}. [{color}]{r.severity.upper()}[/{color}] {r.cluster.skill}/{r.cluster.tool}[/bold] ({r.cluster.failure_type}, freq={r.cluster.frequency}{ts})")
            console.print(f"   [dim]Root cause:[/dim] {r.root_cause}")
            console.print(f"   {r.explanation}")

            if r.skill_md_suggestion:
                console.print("   [bold]SKILL.md suggestion:[/bold]")
                for line in r.skill_md_suggestion.split("\n"):
                    console.print(f"     {line}")

            if r.cli_tool_suggestion:
                console.print("   [bold]CLI tool suggestion:[/bold]")
                for line in r.cli_tool_suggestion.split("\n"):
                    console.print(f"     {line}")

            console.print()

    # Cross-provider correlation
    _render_correlation(console, results)


def _render_correlation(console: Console, results: list[AnalysisResult]) -> None:
    """Render the cross-provider correlation table."""
    correlations: dict[tuple[str, str], dict[str, bool]] = {}
    for r in results:
        key = (r.cluster.skill, r.cluster.tool)
        if key not in correlations:
            correlations[key] = {}
        for p in r.cluster.providers:
            correlations[key][p] = True

    multi_provider = {k: v for k, v in correlations.items() if len(v) > 1}
    if not multi_provider:
        return

    console.print("[bold]Cross-Provider Correlation[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Skill/Tool")
    table.add_column("Claude", justify="center")
    table.add_column("Cursor", justify="center")
    table.add_column("Likely Cause")

    for (skill, tool), providers in sorted(multi_provider.items()):
        claude = "claude" in providers
        cursor = "cursor" in providers
        if claude and cursor:
            cause = "Skill/CLI tool itself"
        elif claude:
            cause = "Claude-specific"
        else:
            cause = "Cursor-specific"

        table.add_row(
            f"{skill}/{tool}",
            "[green]Y[/green]" if claude else "[dim]N[/dim]",
            "[green]Y[/green]" if cursor else "[dim]N[/dim]",
            cause,
        )

    console.print(table)
    console.print()
