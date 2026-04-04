from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import click

from refainery import __version__


def parse_since(value: str) -> datetime:
    """Parse a duration string like '7d', '24h', '2w' into a datetime cutoff."""
    match = re.fullmatch(r"(\d+)([hdwm])", value.strip())
    if not match:
        raise click.BadParameter(f"Invalid duration: {value!r}. Use e.g. '7d', '24h', '2w'.")
    amount, unit = int(match.group(1)), match.group(2)
    deltas = {"h": timedelta(hours=amount), "d": timedelta(days=amount), "w": timedelta(weeks=amount), "m": timedelta(days=amount * 30)}
    return datetime.now(timezone.utc) - deltas[unit]


class SinceType(click.ParamType):
    name = "duration"

    def convert(self, value: str, param: click.Parameter | None, ctx: click.Context | None) -> datetime:
        try:
            return parse_since(value)
        except click.BadParameter as e:
            self.fail(str(e), param, ctx)


SINCE = SinceType()


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Automated skill refinement through retrospective analysis of AI coding agent conversations."""


@main.command()
@click.option("--provider", default=None, type=click.Choice(["claude", "cursor"]), help="Filter by provider.")
@click.option("--since", default=None, type=SINCE, help="Time window, e.g. '7d', '24h', '2w'.")
def index(provider: str | None, since: datetime | None) -> None:
    """Index conversations into the local store (incremental)."""
    from refainery.pipeline import run_index

    run_index(since=since, provider=provider)


@main.command()
def stats() -> None:
    """Show store statistics."""
    from refainery.pipeline import run_stats

    run_stats()


@main.command()
@click.option("--skill", default=None, help="Focus on a specific skill.")
@click.option("--provider", default=None, type=click.Choice(["claude", "cursor"]), help="Filter by provider.")
@click.option("--since", default=None, type=SINCE, help="Time window, e.g. '7d', '24h', '2w'.")
@click.option("--dry-run", is_flag=True, help="Show prompts that would be sent to Claude without calling the API.")
def analyze(skill: str | None, provider: str | None, since: datetime | None, dry_run: bool) -> None:
    """Analyze recent conversations for skill failures."""
    from refainery.pipeline import run_analysis

    run_analysis(skill=skill, provider=provider, since=since, dry_run=dry_run)


@main.command()
@click.option("--format", "fmt", default="terminal", type=click.Choice(["terminal", "markdown"]), help="Output format.")
@click.option("--skill", default=None, help="Focus on a specific skill.")
@click.option("--provider", default=None, type=click.Choice(["claude", "cursor"]), help="Filter by provider.")
@click.option("--since", default=None, type=SINCE, help="Time window, e.g. '7d', '24h', '2w'.")
def report(fmt: str, skill: str | None, provider: str | None, since: datetime | None) -> None:
    """Generate a summary report of skill failures."""
    from refainery.pipeline import run_report

    run_report(fmt=fmt, skill=skill, provider=provider, since=since)


@main.command()
@click.option("--skill", default=None, help="Filter sessions by skill.")
@click.option("--resume", "resume_id", default=None, help="Resume a session by ID (or prefix).")
def sessions(skill: str | None, resume_id: str | None) -> None:
    """List and resume analysis sessions in Claude Code."""
    from refainery.pipeline import run_sessions

    run_sessions(skill=skill, resume_id=resume_id)


@main.command()
@click.option("--dry-run", is_flag=True, help="Show what would change without applying.")
def apply(dry_run: bool) -> None:
    """Interactively apply suggested fixes to SKILL.md files."""
    from refainery.pipeline import run_apply

    run_apply(dry_run=dry_run)
