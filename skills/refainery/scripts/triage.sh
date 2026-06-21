#!/usr/bin/env bash
# refainery triage helper.
# Loads a session via mnemonai and classifies its tool_results into
# `confirmed_failure` (high confidence) and `review_candidate` (low confidence,
# needs human confirmation). Run this instead of retyping the jq by hand.
#
# Usage:
#   triage.sh <session-id-or-path> [mnemonai-binary]
#   MNEMONAI_BIN=/path/to/mnemonai triage.sh <session-id-or-path>
set -euo pipefail

session="${1:?usage: triage.sh <session-id-or-path> [mnemonai-binary]}"
bin="${2:-${MNEMONAI_BIN:-mnemonai}}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$here/evidence.sh" "$session" "$bin" |
  jq -c '{
    index: .result.index,
    tool_call_id: .result.tool_call_id,
    signal,
    confidence,
    exit_code: .result.exit_code,
    tool_result_status: .result.tool_result_status,
    tool_result_error: .result.tool_result_error,
    text: (.result.text | .[0:500])
  }'
