"""Analyzer — uses Claude to classify root causes and suggest fixes."""

from __future__ import annotations

from rich.progress import Progress, SpinnerColumn, TextColumn

from refainery.analyze.client import AnalyzerClient
from refainery.models import AnalysisResult, FailureCluster


def analyze_clusters(
    clusters: list[FailureCluster],
    max_clusters: int = 20,
) -> list[AnalysisResult]:
    """Analyze the top failure clusters using Claude.

    Processes clusters sequentially to avoid rate limiting.
    Limits to top N clusters by frequency to control cost.
    """
    client = AnalyzerClient()
    results: list[AnalysisResult] = []

    to_analyze = clusters[:max_clusters]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("Analyzing failure clusters...", total=len(to_analyze))

        for cluster in to_analyze:
            progress.update(task, description=f"Analyzing {cluster.skill}/{cluster.tool} ({cluster.failure_type})...")
            try:
                result = client.analyze_cluster(cluster)
                results.append(result)
            except Exception as e:
                # Don't let a single cluster failure stop the whole analysis
                results.append(
                    AnalysisResult(
                        cluster=cluster,
                        root_cause="analysis_error",
                        severity="low",
                        explanation=f"Analysis failed: {e}",
                    )
                )
            progress.advance(task)

    # Sort by severity (high > medium > low), then frequency
    severity_rank = {"high": 3, "medium": 2, "low": 1}
    results.sort(key=lambda r: (severity_rank.get(r.severity, 0), r.cluster.frequency), reverse=True)

    return results
