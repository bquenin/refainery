"""Report generation."""

from __future__ import annotations

from refainery.models import AnalysisResult


def generate_report(results: list[AnalysisResult], fmt: str = "terminal") -> None:
    if fmt == "markdown":
        from refainery.report.markdown import render_markdown

        from rich.console import Console

        Console().print(render_markdown(results), highlight=False)
    else:
        from refainery.report.terminal import render_terminal

        render_terminal(results)
