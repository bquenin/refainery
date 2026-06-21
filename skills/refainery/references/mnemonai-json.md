# Mnemonai JSON Reference

Use `mnemonai` as the normalized session source.

## Commands

Verify the installed binary supports headless JSON:

```bash
mnemonai list --json --limit 1
```

If that command fails with an unexpected `--json` argument, the installed `mnemonai` is too old. Build an updated binary from source and use it for the session:

```bash
git clone https://github.com/bquenin/mnemonai
cd mnemonai
cargo build
target/debug/mnemonai list --json --limit 1
```

List sessions:

```bash
mnemonai list --json --limit 50
mnemonai list --json --since 7d --limit 50
mnemonai list --json --cwd . --since 30d --limit 50
mnemonai list --jsonl --provider codex --limit 100
```

Scope flags:

- `--since <duration>`: relative window such as `7d`, `24h`, or `2w`.
- `--after <timestamp>`: inclusive lower bound, accepting RFC 3339 or `YYYY-MM-DD`.
- `--before <timestamp>`: exclusive upper bound, accepting RFC 3339 or `YYYY-MM-DD`.
- `--cwd <path>`: include conversations whose recorded `cwd` or `project_path` is at or under this path.
- `--local`: current directory shortcut; prefer `--cwd <path>` for repeatable reports.

Show one session:

```bash
mnemonai show <id-or-path> --json
```

`show --json` returns:

- `conversation`: the same summary shape used by `list --json`.
- `messages`: ordered normalized messages.

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
mnemonai show "$session" --json |
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
mnemonai show "$session" --json |
  jq '.messages[]
    | select(.role == "tool_result")
    | (.text // "") as $text
    | (($text | capture("(?m)^Process exited with code (?<code>[0-9]+)$")? | .code | tonumber) // null) as $exit_code
    | (.tool_result_exit_code // $exit_code) as $normalized_exit_code
    | select(
        .tool_result_error == true
        or ((.tool_result_status // "") | test("(?i)^(error|errored|failed|failure|cancelled|canceled)$"))
        or ($normalized_exit_code != null and $normalized_exit_code != 0)
        or ($normalized_exit_code == null and ($text | test("(?im)(^|\\n)(traceback|fatal:|error:|usage:|permission denied|command not found|no such file)")))
      )
    | {index, tool_call_id, exit_code: $normalized_exit_code, tool_result_status, tool_result_error, text: ($text | .[0:500])}'
```

Prefer the structured `tool_result_error`, `tool_result_status`, and `tool_result_exit_code` fields; the regex on `$text` is only a fallback for command output that exposes no structured exit code. It is anchored to a full line (`^...$`) so that the phrase quoted inside a file read or diff does not register as a command failure. Always confirm a flagged result against its surrounding messages before treating it as a real struggle.

Find repeated tool names:

```bash
mnemonai show "$session" --json |
  jq '[.messages[] | select(.role == "tool_call") | .tool_name]
    | group_by(.)
    | map({tool: .[0], count: length})
    | sort_by(-.count)'
```
