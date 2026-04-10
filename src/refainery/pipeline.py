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


def _interactive_session_picker(sessions: list[dict], console: Console, store: Store | None = None) -> None:
    """Show an interactive menu of sessions.

    Enter resumes in Claude Code. 'd' toggles resolved status (requires store).
    """
    from simple_term_menu import TerminalMenu

    def _format_timespan(s: dict) -> str:
        first = s.get("first_seen", "")
        last = s.get("last_seen", "")
        if not first or not last:
            return ""
        first_date = first[:10]
        last_date = last[:10]
        if first_date == last_date:
            return first_date
        return f"{first_date} → {last_date}"

    def _build_entries() -> tuple[list[str], dict[str, int]]:
        entries = []
        lookup: dict[str, int] = {}
        for i, s in enumerate(sessions):
            resolved = "✓ " if s.get("resolved") else "  "
            timespan = _format_timespan(s)
            ts_suffix = f"  [{timespan}]" if timespan else ""
            label = f"{resolved}{s['skill']}/{s['tool']} ({s['failure_type']}, {s['frequency']}×){ts_suffix}"
            entries.append(label)
            lookup[label] = i
        return entries, lookup

    entries, entry_to_idx = _build_entries()

    def _preview(entry: str) -> str:
        idx = entry_to_idx.get(entry)
        if idx is None:
            return ""
        s = sessions[idx]
        status = "RESOLVED" if s.get("resolved") else "OPEN"
        timespan = _format_timespan(s)
        header = (
            f"Status: {status}\n"
            f"Skill: {s['skill']}  Tool: {s['tool']}  Type: {s['failure_type']}\n"
            f"Frequency: {s['frequency']}  Providers: {', '.join(s['providers'])}\n"
            f"Timespan: {timespan or 'unknown'}\n"
            f"Session: {s['session_id']}\n"
            f"{'─' * 60}\n\n"
        )
        return header + s["analysis"]

    while True:
        title = "Enter: resume in Claude · d: toggle resolved · q: quit"
        menu = TerminalMenu(
            entries,
            title=title,
            preview_command=_preview,
            preview_size=0.7,
            preview_title="Analysis",
            accept_keys=("enter", "d"),
            shortcut_key_highlight_style="",
        )

        choice = menu.show()
        if choice is None:
            break

        chosen_key = menu.chosen_accept_key
        if chosen_key == "d" and store is not None:
            s = sessions[choice]
            new_resolved = not s.get("resolved", False)
            store.resolve_session(s["session_id"], new_resolved)
            s["resolved"] = new_resolved
            entries, entry_to_idx = _build_entries()
            continue

        # Enter — resume
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


def _interactive_cluster_picker(
    clusters: list,
    console: Console,
    store: Store,
) -> list:
    """Show an interactive multi-select menu of failure clusters.

    Returns the selected clusters.
    """
    from simple_term_menu import TerminalMenu

    entries = []
    for c in clusters:
        has_session = store.has_session(c.skill, c.tool, c.failure_type)
        analyzed = "✓ " if has_session else "  "
        ts = f"  [{c.timespan}]" if c.timespan else ""
        providers = ", ".join(sorted(c.providers))
        label = f"{analyzed}{c.skill}/{c.tool} ({c.failure_type}, {c.frequency}×, {providers}){ts}"
        entries.append(label)

    def _preview(entry: str) -> str:
        idx = entries.index(entry)
        c = clusters[idx]
        has_session = store.has_session(c.skill, c.tool, c.failure_type)
        status = "ANALYZED" if has_session else "NOT ANALYZED"
        lines = [
            f"Status: {status}",
            f"Skill: {c.skill}  Tool: {c.tool}  Type: {c.failure_type}",
            f"Frequency: {c.frequency}  Providers: {', '.join(sorted(c.providers))}",
            f"Timespan: {c.timespan or 'unknown'}",
            f"{'─' * 60}",
            "",
            f"Sample occurrences ({min(5, len(c.occurrences))} of {len(c.occurrences)}):",
            "",
        ]
        for occ in c.occurrences[:5]:
            cmd = occ.command or occ.tool_name
            output_preview = (occ.output or "")[:200].replace("\n", " ")
            lines.append(f"  [{occ.timestamp:%Y-%m-%d %H:%M}] {cmd}")
            if output_preview:
                lines.append(f"    → {output_preview}")
            lines.append("")
        return "\n".join(lines)

    menu = TerminalMenu(
        entries,
        title="Space: select · Enter: analyze selected · q: quit",
        multi_select=True,
        show_multi_select_hint=True,
        preview_command=_preview,
        preview_size=0.5,
        preview_title="Cluster Details",
        multi_select_select_on_accept=False,
        shortcut_key_highlight_style="",
    )

    selection = menu.show()
    if selection is None:
        return []

    if isinstance(selection, int):
        return [clusters[selection]]
    return [clusters[i] for i in selection]


def run_analysis(
    skill: str | None = None,
    provider: str | None = None,
    since: datetime | None = None,
    dry_run: bool = False,
    interactive: bool = False,
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
            from refainery.analyze.prompts import build_cluster_analysis_prompt, write_occurrences_csv

            target = clusters if interactive else clusters[:20]
            if interactive:
                target = _interactive_cluster_picker(target, console, store)
                if not target:
                    return

            for i, cluster in enumerate(target, 1):
                ts = f" | {cluster.timespan}" if cluster.timespan else ""
                csv_path = write_occurrences_csv(cluster)
                console.rule(f"[bold]Cluster {i}/{len(target)}: {cluster.skill}/{cluster.tool} ({cluster.failure_type})[/bold]")
                console.print(f"[dim]Frequency: {cluster.frequency} | Providers: {', '.join(sorted(cluster.providers))}{ts}[/dim]")
                console.print(f"[dim]CSV: {csv_path}[/dim]")
                console.print()
                console.print(build_cluster_analysis_prompt(cluster, csv_path), highlight=False, markup=False)
                console.print()
            return

        # 5. Select clusters to analyze
        if interactive:
            selected = _interactive_cluster_picker(clusters, console, store)
            if not selected:
                return
            new_clusters = [
                c for c in selected
                if not store.has_session(c.skill, c.tool, c.failure_type)
            ]
            already = len(selected) - len(new_clusters)
            if already:
                console.print(f"  Skipping {already} clusters that already have sessions")
        else:
            all_clusters = clusters[:20]
            new_clusters = [
                c for c in all_clusters
                if not store.has_session(c.skill, c.tool, c.failure_type)
            ]
            existing = len(all_clusters) - len(new_clusters)
            if existing:
                console.print(f"  Skipping {existing} clusters with existing sessions")

        if not new_clusters:
            console.print("  All selected clusters already have sessions")
            console.print(f"[dim]  Use 'refainery sessions --skill {skill or '...'}' to review them.[/dim]")
        else:
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
                    ts = f"  {cluster.timespan}" if cluster.timespan else ""
                    label = f"{cluster.skill}/{cluster.tool} [dim]({cluster.failure_type}, {cluster.frequency}×){ts}[/dim]"
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
                        first_seen=s.cluster.first_seen,
                        last_seen=s.cluster.last_seen,
                    )
            console.print(f"  [green]{len(sessions)} new sessions created and stored[/green]")

        console.print()

        # 7. Interactive session picker
        store.backfill_session_timespans()
        all_sessions = store.list_sessions(skill=skill)
        if all_sessions:
            _interactive_session_picker(all_sessions, console, store=store)


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


def run_sessions(skill: str | None = None, resume_id: str | None = None, include_resolved: bool = False) -> None:
    """List stored analysis sessions, or resume one."""
    console = Console()

    with Store() as store:
        store.backfill_session_timespans()

        if resume_id:
            # Direct resume by session ID (or prefix match)
            sessions = store.list_sessions(skill=skill, include_resolved=True)
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

        sessions = store.list_sessions(skill=skill, include_resolved=include_resolved)
        if not sessions:
            console.print("[dim]No analysis sessions found. Run 'refainery analyze' first.[/dim]")
            return

        _interactive_session_picker(sessions, console, store=store)


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
