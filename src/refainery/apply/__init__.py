"""Apply suggested fixes to SKILL.md files."""

from __future__ import annotations

from rich.console import Console

from refainery.models import AnalysisResult


def apply_suggestions(results: list[AnalysisResult], dry_run: bool = False) -> None:
    """Display and optionally apply suggested fixes."""
    console = Console()

    actionable = [r for r in results if r.skill_md_suggestion or r.cli_tool_suggestion]
    if not actionable:
        console.print("[dim]No actionable suggestions to apply.[/dim]")
        return

    for i, r in enumerate(actionable, 1):
        console.print(f"\n[bold]{i}/{len(actionable)}. {r.cluster.skill}/{r.cluster.tool}[/bold] ({r.severity})")
        console.print(f"  Root cause: {r.root_cause}")
        console.print(f"  {r.explanation}")

        if r.skill_md_suggestion:
            console.print("\n  [bold]Suggested SKILL.md addition:[/bold]")
            for line in r.skill_md_suggestion.split("\n"):
                console.print(f"    {line}")

        if r.cli_tool_suggestion:
            console.print("\n  [bold]Suggested CLI tool change:[/bold]")
            for line in r.cli_tool_suggestion.split("\n"):
                console.print(f"    {line}")

        if dry_run:
            console.print("  [dim](dry-run, not applying)[/dim]")
        else:
            console.print("\n  [dim]Manual application required — review and apply the suggestions above.[/dim]")
