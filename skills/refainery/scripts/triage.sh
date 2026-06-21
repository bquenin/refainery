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

"$bin" show "$session" --json | jq -f "$here/triage.jq"
