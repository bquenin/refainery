# Mnemonai JSON Reference

Use `mnemonai` as the normalized session source.

## Contents

- [Compatibility and commands](#compatibility-and-commands)
- [Conversation summary fields](#conversation-summary-fields)
- [Search result fields](#search-result-fields)
- [Message fields](#message-fields)
- [Trace reconstruction](#trace-reconstruction)
- [JQ helpers](#jq-helpers)

## Compatibility and Commands

Set the binary once, then use the same value for every command. Shell variables may not persist between separate commands in every agent — keep each `mnemonai` call in the same shell as this assignment, or substitute the resolved absolute path directly:

```bash
MNEMONAI_BIN="${MNEMONAI_BIN:-mnemonai}"
```

Verify the installed binary supports the required headless contract:

```bash
"$MNEMONAI_BIN" --version
"$MNEMONAI_BIN" list --json --since 7d --cwd . --limit 1
"$MNEMONAI_BIN" search --help >/dev/null
"$MNEMONAI_BIN" show --help | rg -q -- '--grep'
```

If a command rejects the required subcommand or flags, or `"$MNEMONAI_BIN" --version` reports a version older than `0.15.0` by semantic version (compare numerically, so `0.15.10` is newer than `0.15.0`), the installed `mnemonai` is too old. Build an updated binary from source in a temporary checkout and use it for the session:

```bash
workdir="$(mktemp -d "${TMPDIR:-/tmp}/mnemonai.XXXXXX")"
git clone --depth 1 https://github.com/bquenin/mnemonai "$workdir/mnemonai"
cargo build --manifest-path "$workdir/mnemonai/Cargo.toml"
MNEMONAI_BIN="$workdir/mnemonai/target/debug/mnemonai"
"$MNEMONAI_BIN" list --json --since 7d --cwd . --limit 1
"$MNEMONAI_BIN" search --help >/dev/null
"$MNEMONAI_BIN" show --help | rg -q -- '--grep'
```

List sessions:

```bash
"$MNEMONAI_BIN" list --json --limit 50
"$MNEMONAI_BIN" list --json --since 7d --limit 50
"$MNEMONAI_BIN" list --json --cwd . --since 30d --limit 50
"$MNEMONAI_BIN" list --jsonl --provider codex --limit 100
```

Use `list` for unbiased time-window audits. A list preview does not search full conversation content, so use `search` when the request names a skill, tool, command, error, or problem pattern.

Search session content:

```bash
# Concrete artifact vocabulary
"$MNEMONAI_BIN" search refainery evidence.sh --since 30d --limit 20 --snippets 2 --json

# Abstract problem vocabulary; vary terms when results are weak
"$MNEMONAI_BIN" search retry permission --since 30d --limit 20 --snippets 2 --json

# Restrict only when the topic is known to be repo-local
"$MNEMONAI_BIN" search evidence tool_result --cwd . --since 30d --limit 20 --json
```

Every search word is a case-insensitive substring match and all words must match. Results are ranked by relevance and recency. Prefer distinctive terms because generic words over-match. Use `--exclude-session <id>` when the live session ID is known, and try both concrete artifact vocabulary and abstract problem-class vocabulary before concluding there are no relevant sessions.

Scope and search flags:

- `--since <duration>`: relative window such as `7d`, `24h`, or `2w`.
- `--after <timestamp>`: inclusive lower bound, accepting RFC 3339 or `YYYY-MM-DD`.
- `--before <timestamp>`: exclusive upper bound, accepting RFC 3339 or `YYYY-MM-DD`.
- `--cwd <path>`: include conversations whose recorded `cwd` or `project_path` is at or under this path.
- `--local`: current directory shortcut; prefer `--cwd <path>` for repeatable reports.
- `--provider <provider>`: restrict to `claude`, `codex`, `cursor`, or `cursor-agent`.
- `--limit <n>`: cap list or search results.
- `--snippets <0..5>`: control lowercased search context windows; search only.
- `--exclude-session <id>`: remove a session ID from search results; repeatable.

Headless scope is flag-driven and does not inherit interactive config filters. `list` and `search` default to global scope unless `--local` or `--cwd` is passed.

Show one session:

```bash
"$MNEMONAI_BIN" show <id-or-path> --json

# Focused review: repeated --grep patterns are ORed
"$MNEMONAI_BIN" show <id-or-path> \
  --grep evidence.sh \
  --grep 'permission denied' \
  --context 2 \
  --json
```

`show --json` returns:

- `conversation`: the same summary shape used by `list --json`.
- `messages`: ordered normalized messages.
- `total_messages`: the pre-filter message count, present only with `--grep`.

`show --grep` matches case-insensitive substrings in message text, thinking, and stringified tool input/result. It keeps matching messages plus the requested neighboring messages, preserves original indices, and marks direct matches with `matched: true`. Repeated patterns are ORed, unlike the AND semantics of `search` words.

When candidate sessions exist, load one before deep analysis and verify that `messages[]` is ordered, every message carries `index` and `entry_index`, tool calls carry `tool_call_id` and `tool_name`, and results expose a matching `tool_call_id` when the provider records one. The `tool_result_status`, `tool_result_exit_code`, and `tool_result_error` fields are best-effort and absent for many providers/sessions, so do not treat their absence as a failure. Decide the build fallback from the binary itself — argument rejection of required commands/flags or a semantic version older than `0.15.0` — not from which optional fields a given session happens to include. Only when the up-to-date binary cannot expose ordering or linkable pairing fields for a session is that a provider/extraction gap to report in the findings.

## Conversation Summary Fields

Useful fields from `list --json`:

- `provider`: stable provider key such as `claude`, `codex`, `cursor`, or `cursor-agent`.
- `id`: provider/session identifier.
- `path`: raw transcript path. Prefer passing this to `show` when IDs are ambiguous.
- `timestamp`: conversation timestamp.
- `cwd` or `project_path`: workspace context.
- `summary`, `preview`, `model`, `message_count`, `total_tokens`, `duration_minutes`.
- `parse_errors`: extraction issues that may affect confidence.

## Search Result Fields

Useful fields from `search --json`:

- `provider`, `id`, `path`, `timestamp`, `project_name`, `cwd`, and `summary`: candidate identity and scope.
- `score`: relevance score used for result ordering.
- `match_count`: total query-term occurrences in the searchable conversation text.
- `snippets`: up to `--snippets` lowercased context windows around early matches.

Search results deliberately omit `preview`, `message_count`, `model`, and `parse_errors`. Use `show` on selected candidates before assessing evidence quality.

## Message Fields

Useful fields from `show --json` under `messages[]`:

- `index`: zero-based normalized message index.
- `entry_index`: zero-based source log entry index.
- `block_index`: content block index inside the source entry when applicable.
- `role`: `summary`, `user`, `assistant`, `tool_call`, `tool_result`, `thinking`, `image`, `system`, or `agent_<type>`.
- `matched`: `true` on direct `show --grep` matches; absent on context-only neighbors and unfiltered output.
- `timestamp`: message timestamp when available.
- `text`: normalized readable text for text messages and many tool results.
- `tool_call_id`: stable pairing key for `tool_call` and `tool_result`.
- `tool_name`: tool name for `tool_call`.
- `tool_input`: raw provider-specific input for `tool_call`.
- `tool_result`: raw provider-specific result for `tool_result`.
- `tool_result_status`: provider status when available.
- `tool_result_exit_code`: command exit code when command-style output exposes one.
- `tool_result_error`: explicit or recognized success/error marker when available.
- `model`, `agent_id`, `subtype`, `level`, `duration_ms`, `source`.

## Trace Reconstruction

Pair tool calls and results by `tool_call_id`.

If a result is missing, classify it as an incomplete trace unless nearby system messages explain cancellation.

Use `show --grep` only to shortlist evidence. A filtered window can omit a distant paired call/result or later recovery message, so use full `show --json` or the bundled `evidence.sh` before reconstructing a complete trace or writing a finding.

The `cursor-agent` provider is a known exception: its transcripts store `tool_call` messages but no `tool_result` messages (results are not recorded in a linkable form), so every `cursor-agent` tool call legitimately has no result. Treat `cursor-agent` traces as call-only and do not report the absent results as missing, cancelled, or a struggle. The `cursor` (IDE) provider, by contrast, does expose tool results.

Use adjacent assistant text to infer intent:

- Previous assistant text: what the model was trying to do.
- Tool call input: how it attempted the action.
- Tool result text/status: what happened.
- Next assistant text/tool call: whether it recovered, retried, abandoned, or misread the output.

## JQ Helpers

Summarize tool events without printing full outputs:

```bash
"$MNEMONAI_BIN" show "$session" --json |
  jq '.messages[]
    | select(.role == "tool_call" or .role == "tool_result")
    | {
        index,
        role,
        tool_call_id,
        tool_name,
        tool_result_status,
        tool_result_error,
        text: (.text | tostring | .[0:300])
      }'
```

Build evidence rows for findings:

Use the bundled evidence helper instead of manually joining `tool_call` and `tool_result` messages. Invoke it by the refainery skill's absolute path — a bare `scripts/...` will not resolve, because your shell cwd is the project under analysis, not the skill directory:

```bash
# point at wherever this skill is installed (it is the dir containing SKILL.md):
skill=~/.codex/skills/refainery   # or ~/.claude/skills/refainery

# emits compact JSONL, one row per flagged tool_result
"$skill/scripts/evidence.sh" <id-or-path>

# if step 1 built an updated binary, pass it explicitly
MNEMONAI_BIN=/path/to/checkout/target/debug/mnemonai "$skill/scripts/evidence.sh" <id-or-path>
```

Each evidence row includes:

- `session`: provider, id, path, cwd, timestamp, model, and parse errors.
- `signal`, `confidence`, and `reasons`: classification details.
- `call`: paired tool call metadata and truncated `tool_input`.
- `result`: result index, status/error/exit code, and truncated text.
- `context`: nearby previous user, previous assistant, and next assistant text.
- `pairing.has_call`: whether a matching tool call was found.

Use `evidence.sh` for final findings. It avoids brittle ad hoc jq joins and preserves the command/input needed to explain what the agent was trying to do.

Find tool results that need quick triage:

Run the bundled helper instead of retyping the jq (avoids copy/escape mistakes). Invoke it by the refainery skill's absolute path — a bare `scripts/...` will not resolve, because your shell cwd is the project under analysis, not the skill directory:

```bash
# point at wherever this skill is installed (it is the dir containing SKILL.md):
skill=~/.codex/skills/refainery   # or ~/.claude/skills/refainery

# uses the installed mnemonai (or $MNEMONAI_BIN) by default
"$skill/scripts/triage.sh" <id-or-path>

# if step 1 built an updated binary, pass it explicitly so triage uses it too
# (a fresh shell will not have inherited MNEMONAI_BIN from step 1)
MNEMONAI_BIN=/path/to/checkout/target/debug/mnemonai "$skill/scripts/triage.sh" <id-or-path>
```

It runs `evidence.sh` and emits one object per flagged tool_result with `index`, `tool_call_id`, `signal`, `confidence`, `exit_code`, `tool_result_status`, `tool_result_error`, and a truncated `text`. The classification logic lives in `scripts/evidence.jq` — read or edit that file rather than re-deriving the query.

`confirmed_failure` is driven by structured `tool_result_error`, `tool_result_status`, and `tool_result_exit_code` fields. `review_candidate` captures strong text-only signals such as tracebacks, line-leading `error:`/`fatal:` diagnostics, compiler errors, shell errors, sandbox denials, uppercase log-level `ERROR`/`FATAL`/`PANIC` lines, permission failures, missing files, and argument/usage errors. To reduce noise it gates `usage:` behind a co-occurring argument-error phrase, line-anchors the diagnostic signals, skips git-style diff output, and suppresses successful source/doc/session-inspection output unless the next assistant message indicates the output caused a real retry or recovery. Inspection suppression only applies when *every* stage of the command reads/inspects (e.g. `cat`/`sed`/`grep`/`git show`/`mnemonai show`); a pipe or chain into another program (for example `cat data.json | python analyze.py` or `ls && cargo build`) is never suppressed, so a failing non-inspection stage is preserved. Treat `signal: "review_candidate"` as low-confidence until surrounding messages confirm impact, and prefer surfacing a borderline result over silently dropping a real failure.

Find repeated tool names:

```bash
"$MNEMONAI_BIN" show "$session" --json |
  jq '[.messages[] | select(.role == "tool_call") | .tool_name]
    | group_by(.)
    | map({tool: .[0], count: length})
    | sort_by(-.count)'
```
