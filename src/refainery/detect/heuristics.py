"""Heuristic-based failure detection — no LLM required.

Five heuristics that identify different failure patterns in tool invocations:
1. Retry chains — same tool called repeatedly with similar arguments
2. Error outputs — tool results containing error indicators
3. Struggle signals — agent text expressing difficulty after tool use
4. Command mutations — same base command with progressively different flags
5. Abandoned tools — agent gives up on a tool after failures
"""

from __future__ import annotations

from difflib import SequenceMatcher
from itertools import groupby

from refainery.models import FailureCluster, ToolInvocation


def detect_retry_chains(invocations: list[ToolInvocation]) -> list[FailureCluster]:
    """Detect consecutive calls to the same tool with similar arguments.

    A retry chain is N>1 consecutive calls to the same tool within a conversation
    where the arguments are similar (SequenceMatcher ratio > 0.5).
    """
    clusters: list[FailureCluster] = []
    if len(invocations) < 2:
        return clusters

    # Group consecutive invocations by tool_name
    chain: list[ToolInvocation] = [invocations[0]]

    for inv in invocations[1:]:
        if inv.tool_name == chain[-1].tool_name:
            # Check similarity of arguments/command
            prev_sig = chain[-1].command or str(chain[-1].arguments)
            curr_sig = inv.command or str(inv.arguments)
            ratio = SequenceMatcher(None, prev_sig, curr_sig).ratio()
            if ratio > 0.5:
                chain.append(inv)
                continue

        # End of chain — emit if N > 1
        if len(chain) > 1:
            clusters.append(_chain_to_cluster(chain, "retry_chain"))
        chain = [inv]

    # Don't forget the last chain
    if len(chain) > 1:
        clusters.append(_chain_to_cluster(chain, "retry_chain"))

    return clusters


def detect_error_outputs(invocations: list[ToolInvocation]) -> list[FailureCluster]:
    """Detect tool invocations that produced error output."""
    clusters: list[FailureCluster] = []

    failed = [inv for inv in invocations if not inv.success]
    if not failed:
        return clusters

    # Group by (skill, tool)
    failed.sort(key=lambda i: (i.skill_context or "", i.tool_name))
    for key, group in groupby(failed, key=lambda i: (i.skill_context or "", i.tool_name)):
        occurrences = list(group)
        skill, tool = key
        clusters.append(
            FailureCluster(
                skill=skill or "unknown",
                tool=tool,
                failure_type="error_output",
                occurrences=occurrences,
                providers=frozenset(i.provider for i in occurrences),
                frequency=len(occurrences),
            )
        )

    return clusters


def detect_struggle_signals(invocations: list[ToolInvocation]) -> list[FailureCluster]:
    """Detect tool invocations followed by agent struggle language."""
    clusters: list[FailureCluster] = []

    struggled = [inv for inv in invocations if inv.next_action == "struggle"]
    if not struggled:
        return clusters

    struggled.sort(key=lambda i: (i.skill_context or "", i.tool_name))
    for key, group in groupby(struggled, key=lambda i: (i.skill_context or "", i.tool_name)):
        occurrences = list(group)
        skill, tool = key
        clusters.append(
            FailureCluster(
                skill=skill or "unknown",
                tool=tool,
                failure_type="struggle_signal",
                occurrences=occurrences,
                providers=frozenset(i.provider for i in occurrences),
                frequency=len(occurrences),
            )
        )

    return clusters


def detect_command_mutations(invocations: list[ToolInvocation]) -> list[FailureCluster]:
    """Detect the same base command called with progressively different flags.

    Focuses on Bash tool invocations where the first word of the command is
    the same but arguments vary across 3+ calls in a conversation.
    """
    clusters: list[FailureCluster] = []

    bash_invocations = [inv for inv in invocations if inv.tool_name == "Bash" and inv.command]
    if len(bash_invocations) < 3:
        return clusters

    # Group by base command (first token)
    by_base: dict[str, list[ToolInvocation]] = {}
    for inv in bash_invocations:
        assert inv.command is not None
        base = inv.command.split()[0] if inv.command.strip() else ""
        if base:
            by_base.setdefault(base, []).append(inv)

    for base_cmd, group in by_base.items():
        if len(group) < 3:
            continue

        # Check for progressive mutation: consecutive commands with increasing edit distance
        mutations: list[ToolInvocation] = [group[0]]
        for inv in group[1:]:
            assert inv.command is not None and mutations[-1].command is not None
            ratio = SequenceMatcher(None, mutations[-1].command, inv.command).ratio()
            if 0.3 < ratio < 0.95:  # Different enough to be a mutation, similar enough to be related
                mutations.append(inv)
            else:
                if len(mutations) >= 3:
                    break
                mutations = [inv]

        if len(mutations) >= 3:
            skill = mutations[0].skill_context or "unknown"
            clusters.append(
                FailureCluster(
                    skill=skill,
                    tool=f"Bash:{base_cmd}",
                    failure_type="command_mutation",
                    occurrences=mutations,
                    providers=frozenset(i.provider for i in mutations),
                    frequency=len(mutations),
                )
            )

    return clusters


def detect_abandoned_tools(invocations: list[ToolInvocation]) -> list[FailureCluster]:
    """Detect when an agent switches away from a tool after failures.

    Pattern: tool A fails -> agent uses different tool B -> tool A never used again
    in the remaining conversation.
    """
    clusters: list[FailureCluster] = []
    if len(invocations) < 2:
        return clusters

    for i, inv in enumerate(invocations):
        if inv.success:
            continue

        # Failed invocation — check if this tool is never used again
        tool = inv.tool_name
        remaining = invocations[i + 1 :]
        if not remaining:
            continue

        # Check: next invocation uses a different tool
        next_inv = remaining[0]
        if next_inv.tool_name == tool:
            continue

        # Check: tool never appears again in this conversation
        tool_used_again = any(r.tool_name == tool for r in remaining)
        if tool_used_again:
            continue

        clusters.append(
            FailureCluster(
                skill=inv.skill_context or "unknown",
                tool=tool,
                failure_type="abandoned_tool",
                occurrences=[inv],
                providers=frozenset([inv.provider]),
                frequency=1,
            )
        )

    return clusters


def _chain_to_cluster(chain: list[ToolInvocation], failure_type: str) -> FailureCluster:
    skill = chain[0].skill_context or "unknown"
    tool = chain[0].tool_name
    return FailureCluster(
        skill=skill,
        tool=tool,
        failure_type=failure_type,
        occurrences=chain,
        providers=frozenset(i.provider for i in chain),
        frequency=len(chain),
    )
