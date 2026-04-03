"""Pipeline orchestrator — wires extract -> detect -> analyze -> report."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from refainery.detect import detect_failures
from refainery.models import AnalysisResult
from refainery.providers import ProviderRegistry
from refainery.store import Store

SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


def index_invocations(
    store: Store,
    console: Console,
    since: datetime | None = None,
    provider_filter: str | None = None,
) -> tuple[int, int]:
    """Incrementally index invocations into the store.

    Returns (new_conversations, new_invocations) counts.
    """
    registry = ProviderRegistry()
    new_convs = 0
    new_invs = 0

    for provider in registry.providers:
        if provider_filter and provider.provider_name != provider_filter:
            continue

        conversations = provider.discover_conversations(since=since)
        stale = [c for c in conversations if store.needs_reindex(c)]

        if not stale:
            continue

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task(
                f"Indexing {provider.provider_name}...", total=len(stale)
            )

            for conv in stale:
                store.delete_invocations(conv.conversation_id, conv.provider)
                invocations = provider.extract_invocations(conv)
                store.insert_invocations(invocations)
                store.mark_indexed(conv)
                new_convs += 1
                new_invs += len(invocations)
                progress.advance(task)

        store.commit()

    return new_convs, new_invs


def run_index(
    since: datetime | None = None,
    provider: str | None = None,
) -> None:
    """Index conversations into the store."""
    console = Console()

    with Store() as store:
        console.print("[bold]Indexing conversations...[/bold]")
        new_convs, new_invs = index_invocations(store, console, since=since, provider_filter=provider)

        if new_convs:
            console.print(f"  Indexed {new_convs} new/updated conversations ({new_invs} invocations)")
        else:
            console.print("  Everything up to date")

        stats = store.stats()
        console.print(f"  Store: {stats['conversations']} conversations, {stats['invocations']} invocations")


def run_stats() -> None:
    """Show store statistics."""
    console = Console()

    with Store() as store:
        stats = store.stats()

    console.print()
    console.print("[bold]Refainery Store[/bold]")
    console.print(f"  Database: {stats['db_path']}")
    console.print(f"  Conversations: {stats['conversations']}")
    console.print(f"  Invocations: {stats['invocations']}")
    console.print(f"  Failed: {stats['failed']}")
    console.print(f"  Cached analysis results: {stats['analysis_results_cached']}")
    console.print()

    if stats["by_provider"]:
        console.print("[bold]By provider:[/bold]")
        for prov, count in sorted(stats["by_provider"].items()):
            console.print(f"  {prov}: {count}")
        console.print()

    if stats["top_tools"]:
        console.print("[bold]Top tools:[/bold]")
        for tool, count in stats["top_tools"].items():
            console.print(f"  {tool}: {count}")
        console.print()

    if stats["top_skills"]:
        console.print("[bold]Top skills:[/bold]")
        for skill, count in stats["top_skills"].items():
            console.print(f"  {skill}: {count}")
        console.print()


def _ensure_indexed(
    store: Store,
    console: Console,
    since: datetime | None = None,
    provider: str | None = None,
) -> None:
    """Auto-index if the store is empty or has stale conversations."""
    new_convs, new_invs = index_invocations(store, console, since=since, provider_filter=provider)
    if new_convs:
        console.print(f"  Indexed {new_convs} new/updated conversations ({new_invs} invocations)")


def run_analysis(
    skill: str | None = None,
    provider: str | None = None,
    since: datetime | None = None,
    min_severity: str | None = None,
) -> None:
    """Full pipeline: extract -> detect -> analyze -> report to terminal."""
    console = Console()

    with Store() as store:
        # 1. Ensure indexed
        console.print("[bold]Updating index...[/bold]")
        _ensure_indexed(store, console, since=since, provider=provider)

        # 2. Query from store
        invocations = store.query_invocations(since=since, provider=provider, skill=skill)
        console.print(f"  {len(invocations)} invocations loaded from store")

        if not invocations:
            console.print("[dim]No invocations found. Try adjusting --since or --provider.[/dim]")
            return

        # 3. Detect
        console.print("[bold]Detecting failure patterns...[/bold]")
        clusters = detect_failures(invocations)
        console.print(f"  Found {len(clusters)} failure clusters")

        if not clusters:
            console.print("[green]No failure patterns detected.[/green]")
            return

        # 4. Analyze
        console.print("[bold]Analyzing clusters with Claude...[/bold]")
        from refainery.analyze import analyze_clusters

        results = analyze_clusters(clusters)

        # 5. Cache analysis results
        store.save_analysis_results(results)

        # 6. Filter by severity
        if min_severity:
            min_rank = SEVERITY_RANK.get(min_severity, 0)
            results = [r for r in results if SEVERITY_RANK.get(r.severity, 0) >= min_rank]

        # 7. Report
        from refainery.report import generate_report

        generate_report(results, fmt="terminal")


def run_report(
    fmt: str = "terminal",
    skill: str | None = None,
    provider: str | None = None,
    since: datetime | None = None,
) -> None:
    """Extract + detect only (no LLM), then report clusters without analysis."""
    console = Console()

    with Store() as store:
        # 1. Ensure indexed
        console.print("[bold]Updating index...[/bold]")
        _ensure_indexed(store, console, since=since, provider=provider)

        # 2. Query from store
        invocations = store.query_invocations(since=since, provider=provider, skill=skill)
        console.print(f"  {len(invocations)} invocations loaded from store")

        if not invocations:
            console.print("[dim]No invocations found.[/dim]")
            return

        # 3. Detect
        console.print("[bold]Detecting failure patterns...[/bold]")
        clusters = detect_failures(invocations)
        console.print(f"  Found {len(clusters)} failure clusters")

        if not clusters:
            console.print("[green]No failure patterns detected.[/green]")
            return

        # Report without LLM analysis — create stub AnalysisResults
        results = [
            AnalysisResult(
                cluster=c,
                root_cause="(not analyzed)",
                severity="medium",
                explanation="Run 'refainery analyze' to get Claude-powered analysis.",
            )
            for c in clusters
        ]

        from refainery.report import generate_report

        generate_report(results, fmt=fmt)


def run_apply(dry_run: bool = False) -> None:
    """Full pipeline with interactive apply."""
    console = Console()

    with Store() as store:
        console.print("[bold]Updating index...[/bold]")
        _ensure_indexed(store, console)

        invocations = store.query_invocations()
        if not invocations:
            console.print("[dim]No invocations found.[/dim]")
            return

        clusters = detect_failures(invocations)
        if not clusters:
            console.print("[green]No failure patterns detected.[/green]")
            return

        from refainery.analyze import analyze_clusters

        results = analyze_clusters(clusters)
        store.save_analysis_results(results)

        from refainery.apply import apply_suggestions

        apply_suggestions(results, dry_run=dry_run)
