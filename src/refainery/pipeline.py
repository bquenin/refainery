"""Pipeline orchestrator — wires extract -> detect -> analyze -> report."""

from __future__ import annotations

import os
from datetime import datetime

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from refainery.detect import detect_failures
from refainery.models import AnalysisResult
from refainery.providers import ProviderRegistry
from refainery.store import Store


def _resume_session(session_id: str) -> None:
    """Resume a Claude Code session by replacing the current process."""
    os.execvp("claude", ["claude", "--resume", session_id])


def _interactive_session_picker(sessions: list[dict], console: Console) -> None:
    """Show an interactive menu of sessions. Enter resumes in Claude Code."""
    from simple_term_menu import TerminalMenu

    # Build a lookup from entry string -> index
    entries = []
    entry_to_idx: dict[str, int] = {}
    for i, s in enumerate(sessions):
        label = f"{s['skill']}/{s['tool']} ({s['failure_type']}, {s['frequency']}×)"
        entries.append(label)
        entry_to_idx[label] = i

    def _preview(entry: str) -> str:
        idx = entry_to_idx.get(entry)
        if idx is None:
            return ""
        s = sessions[idx]
        header = (
            f"Skill: {s['skill']}  Tool: {s['tool']}  Type: {s['failure_type']}\n"
            f"Frequency: {s['frequency']}  Providers: {', '.join(s['providers'])}\n"
            f"Session: {s['session_id']}\n"
            f"Created: {s['created_at'][:19]}\n"
            f"{'─' * 60}\n\n"
        )
        return header + s["analysis"]

    menu = TerminalMenu(
        entries,
        title="Analysis sessions — Enter to resume in Claude Code, q to quit",
        preview_command=_preview,
        preview_size=0.7,
        preview_title="Analysis",
    )

    choice = menu.show()
    if choice is not None:
        _resume_session(sessions[choice]["session_id"])



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
    dry_run: bool = False,
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

        # 4. Dry run — show prompts without calling the API
        if dry_run:
            from refainery.analyze.prompts import build_cluster_analysis_prompt

            for i, cluster in enumerate(clusters[:20], 1):
                console.rule(f"[bold]Cluster {i}/{min(len(clusters), 20)}: {cluster.skill}/{cluster.tool} ({cluster.failure_type})[/bold]")
                console.print(f"[dim]Frequency: {cluster.frequency} | Providers: {', '.join(sorted(cluster.providers))}[/dim]")
                console.print()
                console.print(build_cluster_analysis_prompt(cluster), highlight=False, markup=False)
                console.print()
            return

        # 5. Skip clusters that already have sessions
        all_clusters = clusters[:20]
        new_clusters = [
            c for c in all_clusters
            if not store.has_session(c.skill, c.tool, c.failure_type)
        ]
        existing = len(all_clusters) - len(new_clusters)

        if not new_clusters:
            console.print(f"  All {len(all_clusters)} clusters already have sessions")
            console.print(f"[dim]  Use 'refainery sessions --skill {skill or '...'}' to review them.[/dim]")
        else:
            if existing:
                console.print(f"  Skipping {existing} clusters with existing sessions")
            console.print(f"[bold]Analyzing {len(new_clusters)} clusters with Claude...[/bold]")
            console.print()

            from rich.live import Live
            from rich.spinner import Spinner
            from rich.table import Table
            from rich.text import Text
            from refainery.analyze.client import analyze_clusters_parallel

            # Track state per cluster: "pending", "running", "done"
            states = ["pending"] * len(new_clusters)
            spinners = [Spinner("dots", style="yellow") for _ in new_clusters]

            def _build_table() -> Table:
                table = Table(show_header=False, box=None, padding=(0, 1))
                table.add_column(width=3)
                table.add_column()
                for i, cluster in enumerate(new_clusters):
                    if states[i] == "done":
                        icon: Text | Spinner = Text("✓", style="green")
                    elif states[i] == "running":
                        icon = spinners[i]
                    else:
                        icon = Text("·", style="dim")
                    label = f"{cluster.skill}/{cluster.tool} [dim]({cluster.failure_type}, {cluster.frequency}×)[/dim]"
                    table.add_row(icon, label)
                return table

            live = Live(_build_table(), console=console, refresh_per_second=10, transient=True)

            def on_start(idx: int) -> None:
                states[idx] = "running"
                live.update(_build_table())

            def on_done(idx: int) -> None:
                states[idx] = "done"
                live.update(_build_table())

            try:
                with live:
                    sessions = analyze_clusters_parallel(
                        new_clusters, on_start=on_start, on_done=on_done,
                    )
            except Exception as e:
                console.print(f"[red]Analysis failed:[/red] {type(e).__name__}: {e}")
                return

            # Show final state (all checkmarks)
            console.print(_build_table())
            console.print()

            # Store sessions in DB
            for s in sessions:
                if s.session_id:
                    store.save_session(
                        session_id=s.session_id,
                        skill=s.cluster.skill,
                        tool=s.cluster.tool,
                        failure_type=s.cluster.failure_type,
                        frequency=s.cluster.frequency,
                        providers=s.cluster.providers,
                        analysis=s.text,
                    )
            console.print(f"  [green]{len(sessions)} new sessions created and stored[/green]")

        console.print()

        # 7. Interactive session picker
        all_sessions = store.list_sessions(skill=skill)
        if all_sessions:
            _interactive_session_picker(all_sessions, console)


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


def run_sessions(skill: str | None = None, resume_id: str | None = None) -> None:
    """List stored analysis sessions, or resume one."""
    console = Console()

    with Store() as store:
        if resume_id:
            # Direct resume by session ID (or prefix match)
            sessions = store.list_sessions(skill=skill)
            match = None
            for s in sessions:
                if s["session_id"] == resume_id or s["session_id"].startswith(resume_id):
                    match = s
                    break
            if not match:
                console.print(f"[red]No session found matching '{resume_id}'[/red]")
                return
            console.print(f"[dim]Resuming session {match['session_id']}...[/dim]")
            _resume_session(match["session_id"])
            return

        sessions = store.list_sessions(skill=skill)
        if not sessions:
            console.print("[dim]No analysis sessions found. Run 'refainery analyze' first.[/dim]")
            return

        _interactive_session_picker(sessions, console)


def run_apply(dry_run: bool = False) -> None:
    """Show stored analysis sessions and their suggestions."""
    console = Console()

    with Store() as store:
        sessions = store.list_sessions()
        if not sessions:
            console.print("[dim]No analysis sessions found. Run 'refainery analyze' first.[/dim]")
            return

        from refainery.apply import apply_suggestions

        apply_suggestions(sessions, dry_run=dry_run)
