# refainery — Design Document

Automated skill refinement through retrospective analysis of AI coding agent conversations.

## Problem

AI coding agents (Claude Code, Cursor, Codex, Gemini, etc.) use skills — packaged instructions (SKILL.md) paired with CLI tools — to perform specialized tasks (JIRA, GitHub, Splunk, etc.). These skills are hand-authored and iteratively refined, but agents frequently struggle with them:

- **Wrong parameters**: agent forgets required flags or passes incorrect values
- **Output parsing failures**: agent can't extract the needed information from CLI output
- **Missing context**: SKILL.md doesn't describe edge cases the agent encounters
- **Retry spirals**: agent calls the same tool 3-5 times with slight variations before succeeding (or giving up)

Today, refinement is manual: review conversations, spot failures, ask the agent what went wrong, update the skill. This is **incomplete** (only a fraction of conversations get reviewed) and **infrequent** (only when time permits or a major issue is noticed).

## Solution

A Python CLI tool that:

1. **Extracts** tool invocations from agent conversation history across all providers
2. **Detects** failure patterns using heuristics (no LLM needed for this stage)
3. **Analyzes** failure clusters with Claude to identify root causes and suggest fixes
4. **Reports** actionable improvements to SKILL.md files and CLI tools

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      Providers                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │  Claude   │  │  Cursor  │  │  Codex   │  │ Gemini │  │
│  │  (JSONL)  │  │ (SQLite) │  │  (TBD)   │  │ (TBD)  │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───┬────┘  │
│       └──────┬───────┴──────┬──────┘            │       │
│              ▼              ▼                    ▼       │
│       ┌─────────────────────────────────┐               │
│       │   Normalized ToolInvocation     │               │
│       │   (command, args, output,       │               │
│       │    next_action, context)        │               │
│       └──────────────┬──────────────────┘               │
└──────────────────────┼──────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────┐
│                  Failure Detector                         │
│  Heuristic-based, no LLM. Flags:                         │
│  - Retry chains (same tool, N>1 attempts)                │
│  - Error keywords in output (error, not found, usage:)   │
│  - Agent struggle language ("let me try", "that didn't") │
│  - Command mutations (same base command, different args)  │
│                                                          │
│  Output: FailureCluster[]                                │
│  (grouped by skill/tool, with full invocation context)   │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────┐
│                  Analyzer (Claude)                        │
│  Receives filtered failure clusters, not full convos.    │
│  For each cluster:                                       │
│  - Reads the relevant SKILL.md                           │
│  - Classifies root cause                                 │
│  - Suggests concrete edits to SKILL.md or CLI tool       │
│                                                          │
│  Uses: Anthropic SDK with OAuth (subscription-based)     │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────┐
│                     Reporter                             │
│  - Per-skill failure summary with frequency counts       │
│  - Cross-provider correlation (both fail = skill issue,  │
│    one fails = provider-specific issue)                   │
│  - Ranked list of suggested SKILL.md edits               │
│  - Optional: interactive apply mode                      │
└──────────────────────────────────────────────────────────┘
```

## Data Model

### ToolInvocation

The normalized unit extracted from any provider:

```python
@dataclass
class ToolInvocation:
    conversation_id: str
    provider: str                  # "claude", "cursor", "codex", ...
    timestamp: datetime
    tool_name: str                 # "Bash", "Read", "Write", etc.
    command: str | None            # shell command (for Bash tool calls)
    arguments: dict                # full tool input
    output: str                    # tool result / stdout+stderr
    success: bool                  # heuristic: did it produce an error?
    next_action: str | None        # what the agent did next (retry, apologize, succeed)
    skill_context: str | None      # which skill was active, if detectable
    conversation_summary: str | None
```

### FailureCluster

A group of related failures, ready for LLM analysis:

```python
@dataclass
class FailureCluster:
    skill: str                     # e.g., "jira", "gh", "splunk"
    tool: str                      # e.g., "jira issue list"
    failure_type: str              # "retry_chain", "error_output", "parse_failure"
    occurrences: list[ToolInvocation]
    providers: set[str]            # which providers hit this
    frequency: int                 # total occurrences across all convos
```

### AnalysisResult

Output from Claude analysis of a failure cluster:

```python
@dataclass
class AnalysisResult:
    cluster: FailureCluster
    root_cause: str                # classification
    severity: str                  # "high", "medium", "low"
    skill_md_suggestion: str | None  # proposed edit to SKILL.md
    cli_tool_suggestion: str | None  # proposed change to the CLI tool
    explanation: str               # why this fix would help
```

## Provider Extraction

### Claude Code

Conversation history lives in `~/.claude/projects/*/`. Each conversation is a JSONL file where tool invocations appear as `ContentBlock::ToolUse` inside assistant messages, with results as `ContentBlock::ToolResult` in the subsequent user message.

Key fields:
- `type: "assistant"` → `message.content[]` → blocks with `type: "tool_use"` (name, input)
- `type: "user"` → `message.content[]` → blocks with `type: "tool_result"` (tool_use_id, content)

### Cursor

Conversation history is in SQLite databases under Cursor's workspace storage. Tool invocations are stored as structured entries within composer conversations.

### Future providers

Adding a provider means implementing a `ConversationReader` that yields `ToolInvocation` objects. The detection and analysis layers are provider-agnostic.

## Failure Detection Heuristics

These run locally with no LLM cost:

1. **Retry chain**: same base command executed N>1 times within a conversation turn, with argument variations
2. **Error output**: tool output contains error indicators (`error`, `Error`, `not found`, `No such`, `usage:`, `invalid`, `failed`, non-zero exit code)
3. **Agent struggle signals**: assistant text following a tool call contains phrases like "let me try", "that didn't work", "I apologize", "seems like", "try a different approach"
4. **Command mutation**: same CLI tool called multiple times with progressively different flags/arguments (edit distance on args)
5. **Abandoned tool**: agent starts using a tool, encounters issues, then switches to a completely different approach

## Cross-Provider Correlation

One of the highest-value signals:

| Claude fails | Cursor fails | Likely cause |
|:---:|:---:|---|
| Yes | Yes | Skill/CLI tool itself needs fixing |
| Yes | No | Claude-specific SKILL.md gap or prompt issue |
| No | Yes | Cursor-specific integration issue |
| No | No | No issue (or both handle the edge case gracefully) |

## CLI Interface

```
refainery analyze                        # analyze all recent conversations
refainery analyze --skill jira           # focus on a specific skill
refainery analyze --provider claude      # filter by provider
refainery analyze --since 7d             # time window
refainery analyze --min-severity medium  # filter output

refainery report                         # generate a summary report
refainery report --format markdown       # output format

refainery apply                          # interactively apply suggested fixes
refainery apply --dry-run                # show what would change
```

## Authentication

Uses the Anthropic SDK with OAuth for Claude analysis — subscription-based, no API key required. This means the tool works with an existing Claude subscription.

## Non-Goals (v1)

- Real-time monitoring (this is retrospective analysis)
- Automatic application of fixes without review
- Training or fine-tuning models
- Replacing manual skill authoring — this augments it

## Future Directions

- **Watch mode**: continuously analyze new conversations as they appear
- **Confidence scoring**: track whether applied fixes actually reduce failure rates over time
- **Skill testing**: generate synthetic tool invocations to test skill instructions before deploying
- **Dashboard**: web UI for browsing failure patterns and trends
