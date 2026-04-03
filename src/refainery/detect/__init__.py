"""Failure detection — heuristic-based, no LLM."""

from __future__ import annotations

from collections import defaultdict

from refainery.detect.heuristics import (
    detect_abandoned_tools,
    detect_command_mutations,
    detect_error_outputs,
    detect_retry_chains,
    detect_struggle_signals,
)
from refainery.models import FailureCluster, ToolInvocation


def detect_failures(invocations: list[ToolInvocation]) -> list[FailureCluster]:
    """Run all heuristics and merge results into deduplicated failure clusters."""
    # Group invocations by conversation for context-aware heuristics
    by_conversation: dict[str, list[ToolInvocation]] = defaultdict(list)
    for inv in invocations:
        by_conversation[inv.conversation_id].append(inv)

    # Sort each conversation's invocations by timestamp
    for conv_invs in by_conversation.values():
        conv_invs.sort(key=lambda i: i.timestamp)

    raw_clusters: list[FailureCluster] = []

    for conv_invs in by_conversation.values():
        raw_clusters.extend(detect_retry_chains(conv_invs))
        raw_clusters.extend(detect_error_outputs(conv_invs))
        raw_clusters.extend(detect_struggle_signals(conv_invs))
        raw_clusters.extend(detect_command_mutations(conv_invs))
        raw_clusters.extend(detect_abandoned_tools(conv_invs))

    return _merge_clusters(raw_clusters)


def _merge_clusters(clusters: list[FailureCluster]) -> list[FailureCluster]:
    """Merge clusters with the same (skill, tool, failure_type) key."""
    merged: dict[tuple[str, str, str], FailureCluster] = {}

    for cluster in clusters:
        key = cluster.key
        if key in merged:
            existing = merged[key]
            existing.occurrences.extend(cluster.occurrences)
            existing.providers = existing.providers | cluster.providers
            existing.frequency += cluster.frequency
        else:
            merged[key] = FailureCluster(
                skill=cluster.skill,
                tool=cluster.tool,
                failure_type=cluster.failure_type,
                occurrences=list(cluster.occurrences),
                providers=cluster.providers,
                frequency=cluster.frequency,
            )

    # Sort by frequency descending
    return sorted(merged.values(), key=lambda c: c.frequency, reverse=True)
