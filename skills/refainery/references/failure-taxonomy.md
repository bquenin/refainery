# Failure Taxonomy

Use this taxonomy to make findings consistent across sessions.

## Struggle Signals

High-signal:

- Explicit failed status or `tool_result_error: true`.
- Non-zero `tool_result_exit_code`, stack traces, parse errors, permission failures, missing binary, missing credential, or missing file.
- Same command/tool retried repeatedly with minor argument changes.
- User correction after the tool sequence.
- Agent claims success while the tool output shows failure.

Medium-signal:

- Broad search/read loops with little narrowing.
- Tool output is too noisy or unstructured for the agent to identify the next action.
- Agent switches approach immediately after a failed tool without explaining why.
- Multiple formatter/linter/test loops converge only after trial and error.
- Generic failure words appear in output with no structured status or exit code.
- Shell portability mistakes recur, such as zsh special variables, unguarded globs, or GNU-only flags on macOS.

Low-signal:

- One exploratory failed command that the agent immediately recovers from.
- Expected negative lookup, such as checking whether a file exists.
- Provider transcript lacks enough output to judge success.
- Words like `error`, `failed`, or `invalid` appear inside successful command output, source code, filenames, or documentation.
- Help text contains words like `usage:` after a successful command.

## Triage Buckets

Use these buckets before writing findings:

- Confirmed failure: high-signal evidence from structured fields, non-zero exit codes, failing statuses, or text-only failure confirmed by retries, abandonment, user correction, or a wrong success claim.
- Review candidate: strong text-only evidence such as tracebacks, shell errors, compiler errors, permission failures, missing files, or invalid usage without enough surrounding evidence to confirm impact.
- Benign/noise: successful help output, expected negative tests, source/docs text containing failure words, exploratory checks that immediately recover, and incomplete traces from the currently active/latest session.

Main findings should use confirmed failures. Mention review candidates separately when they affect confidence or suggest a useful next inspection.

## Root Cause Categories

### Skill Instruction Gap

Use when a skill would likely prevent the failure by documenting:

- Required command order.
- Required flags or argument formats.
- How to interpret common outputs.
- Provider-specific constraints.
- Safety or approval rules.

### CLI/Tool UX Gap

Use when the underlying tool should change:

- Add JSON/headless output.
- Emit stable IDs or status fields.
- Make errors actionable.
- Validate arguments earlier.
- Add dry-run, limit, provider, local, or filter flags.
- Reduce noisy output or add a concise mode.

### Hook/Rule Gap

Use when a local rule or hook could prevent repetition:

- Preflight command availability checks.
- Repo-specific validation before editing.
- Commit/PR description policy enforcement.
- Standard test/lint command discovery.
- Shell portability rules for common agent mistakes, such as avoiding `path` in zsh, guarding globs, and preferring macOS-compatible flags.
- When shell portability recurs, recommend a baseline rule: avoid GNU-only flags on macOS, quote globs, do not use `path` as a variable name in zsh, use `mktemp` for temp files, and prefer `rg` or portable POSIX commands.

### Environment/Access Gap

Use when the model was blocked by external state:

- Missing credentials.
- Network/service outage.
- Sandbox or permission issue.
- Missing dependency or PATH entry.
- Dirty workspace conflict.

### Model Workflow Issue

Use when the data and tools were adequate but the agent:

- Did not inspect existing patterns.
- Over-searched instead of narrowing.
- Failed to verify after editing.
- Ignored an error.
- Chose a brittle manual approach over an available structured API.
- Used an edit/write tool before reading the target file when the provider requires a prior read.

### Provider/Extraction Gap

Use when `mnemonai` cannot expose enough evidence:

- Missing tool call/result IDs.
- Missing status/error markers.
- Missing result text.
- Missing provider/model/session metadata.
- Raw provider data is present but not normalized.

Known limitation, not a per-session finding: the `cursor-agent` provider does not record tool results in its transcripts (only tool calls), so its traces are call-only. Note it once as a provider limitation if relevant; do not flag each cursor-agent tool call as a missing/cancelled result.

### Benign Exploration

Use when the behavior was reasonable and no improvement is warranted.

Severity and confidence are independent axes. Severity is the impact if the finding is real. Confidence is the strength of evidence that the finding is real. Rank findings by severity; use confidence to convey how sure you are.

## Severity

High:

- Repeated across sessions or providers.
- Causes wrong final answers, unsafe changes, or user intervention.
- Blocks task completion.

Medium:

- Wastes noticeable time or tokens.
- Causes retries but the agent recovers.
- A small instruction or CLI change would likely help.

Low:

- Isolated friction.
- Minor, recoverable impact confined to a single session.

## Confidence

High:

- Explicit failure status, non-zero exit code, or the same pattern reproduced across sessions.

Medium:

- Strong circumstantial signals (retries, approach switches, user correction) without an explicit failure marker.

Low:

- Weak or ambiguous evidence.
- The improvement is speculative.
