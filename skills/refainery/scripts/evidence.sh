#!/usr/bin/env bash
# refainery evidence helper.
# Loads a session via mnemonai, classifies struggling tool_results, pairs each
# result with its tool_call, and emits compact JSONL evidence rows.
#
# Usage:
#   evidence.sh <session-id-or-path> [mnemonai-binary]
#   MNEMONAI_BIN=/path/to/mnemonai evidence.sh <session-id-or-path>
set -euo pipefail

session="${1:?usage: evidence.sh <session-id-or-path> [mnemonai-binary]}"
bin="${2:-${MNEMONAI_BIN:-mnemonai}}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
json_file="$(mktemp "${TMPDIR:-/tmp}/refainery-evidence.XXXXXX")"

cleanup() {
  rm -f "$json_file"
}
trap cleanup EXIT

"$bin" show "$session" --json >"$json_file"

provider="$(jq -r '.conversation.provider // "unknown"' "$json_file")"
if [ "$provider" = "cursor-agent" ]; then
  tool_calls="$(jq '[.messages[] | select(.role == "tool_call")] | length' "$json_file")"
  tool_results="$(jq '[.messages[] | select(.role == "tool_result")] | length' "$json_file")"
  if [ "$tool_calls" != "0" ] && [ "$tool_results" = "0" ]; then
    printf 'refainery evidence: cursor-agent session has %s tool calls and no tool results; treating it as call-only by design\n' "$tool_calls" >&2
  fi
fi

jq -c -f "$here/evidence.jq" "$json_file"
