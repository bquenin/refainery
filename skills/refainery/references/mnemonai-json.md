# Mnemonai JSON Reference

Use `mnemonai` as the normalized session source.

## Commands

Set the binary once, then use the same value for every command. Shell variables may not persist between separate commands in every agent — keep each `mnemonai` call in the same shell as this assignment, or substitute the resolved absolute path directly:

```bash
MNEMONAI_BIN="${MNEMONAI_BIN:-mnemonai}"
```

Verify the installed binary supports the required headless contract:

```bash
"$MNEMONAI_BIN" list --json --since 7d --cwd . --limit 1
```

If that command fails with an unexpected `--json`, `--since`, or `--cwd` argument, or `"$MNEMONAI_BIN" --version` reports a version older than `0.12.3` by semantic version (compare numerically, so `0.12.10` is newer than `0.12.3`), the installed `mnemonai` is too old. Build an updated binary from source in a temporary checkout and use it for the session:

```bash
workdir="$(mktemp -d "${TMPDIR:-/tmp}/mnemonai.XXXXXX")"
git clone --depth 1 https://github.com/bquenin/mnemonai "$workdir/mnemonai"
cargo build --manifest-path "$workdir/mnemonai/Cargo.toml"
MNEMONAI_BIN="$workdir/mnemonai/target/debug/mnemonai"
"$MNEMONAI_BIN" list --json --since 7d --cwd . --limit 1
```

List sessions:

```bash
"$MNEMONAI_BIN" list --json --limit 50
"$MNEMONAI_BIN" list --json --since 7d --limit 50
"$MNEMONAI_BIN" list --json --cwd . --since 30d --limit 50
"$MNEMONAI_BIN" list --jsonl --provider codex --limit 100
```

Scope flags:

- `--since <duration>`: relative window such as `7d`, `24h`, or `2w`.
- `--after <timestamp>`: inclusive lower bound, accepting RFC 3339 or `YYYY-MM-DD`.
- `--before <timestamp>`: exclusive upper bound, accepting RFC 3339 or `YYYY-MM-DD`.
- `--cwd <path>`: include conversations whose recorded `cwd` or `project_path` is at or under this path.
- `--local`: current directory shortcut; prefer `--cwd <path>` for repeatable reports.

Show one session:

```bash
"$MNEMONAI_BIN" show <id-or-path> --json
```

`show --json` returns:

- `conversation`: the same summary shape used by `list --json`.
- `messages`: ordered normalized messages.

When candidate sessions exist, load one before deep analysis and verify that `messages[]` is ordered and carries the always-present fields `index`, `entry_index`, `tool_call_id`, and `tool_name`. The `tool_result_status`, `tool_result_exit_code`, and `tool_result_error` fields are best-effort and absent for many providers/sessions, so do not treat their absence as a failure. Decide the build fallback from the binary itself — argument rejection of `--json`/`--since`/`--cwd`, or a semantic version older than `0.12.3` — not from which optional fields a given session happens to include. Only when the up-to-date binary cannot expose the ordering/pairing fields (`index`, `tool_call_id`) for a session is that a provider/extraction gap to report in the findings.

## Conversation Summary Fields

Useful fields from `list --json`:

- `provider`: stable provider key such as `claude`, `codex`, `cursor`, or `cursor-agent`.
- `id`: provider/session identifier.
- `path`: raw transcript path. Prefer passing this to `show` when IDs are ambiguous.
- `timestamp`: conversation timestamp.
- `cwd` or `project_path`: workspace context.
- `summary`, `preview`, `model`, `message_count`, `total_tokens`, `duration_minutes`.
- `parse_errors`: extraction issues that may affect confidence.

## Message Fields

Useful fields from `show --json` under `messages[]`:

- `index`: zero-based normalized message index.
- `entry_index`: zero-based source log entry index.
- `block_index`: content block index inside the source entry when applicable.
- `role`: `summary`, `user`, `assistant`, `tool_call`, `tool_result`, `thinking`, `image`, `system`, or `agent_<type>`.
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
