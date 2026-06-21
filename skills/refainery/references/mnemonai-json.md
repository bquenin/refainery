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

Find likely failing tool results:

```bash
"$MNEMONAI_BIN" show "$session" --json |
  jq '.messages[]
    | select(.role == "tool_result")
    | (.text // "") as $text
    | (($text | capture("(?m)^(?:Process exited with code|Exit code) (?<code>[0-9]+)$")? | .code | tonumber) // null) as $exit_code
    | (.tool_result_exit_code // $exit_code) as $normalized_exit_code
    | (
        .tool_result_error == true
        or ((.tool_result_status // "") | test("(?i)^(error|errored|failed|failure|cancelled|canceled)$"))
        or ($normalized_exit_code != null and $normalized_exit_code != 0)
      ) as $structured_failure
    | (
        $structured_failure == false
        and ($text | test("(?im)(^|\\n)(traceback|fatal:|error:|usage:|permission denied|command not found|no such file)"))
      ) as $text_candidate
    | select($structured_failure or $text_candidate)
    | {
        index,
        tool_call_id,
        signal: (if $structured_failure then "structured_failure" else "text_candidate" end),
        confidence: (if $structured_failure then "high" else "low" end),
        exit_code: $normalized_exit_code,
        tool_result_status,
        tool_result_error,
        text: ($text | .[0:500])
      }'
```

`$structured_failure` (high confidence) is driven by the structured `tool_result_error`, `tool_result_status`, and `tool_result_exit_code` fields. The `$text` regex produces a low-confidence `text_candidate` only when the structured fields do not already indicate a failure — so a result whose structured fields say success (for example `tool_result_error: false`) but whose text shows a traceback or `command not found` is still surfaced for review rather than dropped. The exit-code regex is anchored to a full line (`^...$`) so quoted text inside a file read or diff does not register as a command failure. Treat `signal: "text_candidate"` as low-confidence until surrounding messages confirm it; help output commonly contains `Usage:` despite succeeding.

Find repeated tool names:

```bash
"$MNEMONAI_BIN" show "$session" --json |
  jq '[.messages[] | select(.role == "tool_call") | .tool_name]
    | group_by(.)
    | map({tool: .[0], count: length})
    | sort_by(-.count)'
```
