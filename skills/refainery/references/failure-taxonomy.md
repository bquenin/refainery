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

Low-signal:

- One exploratory failed command that the agent immediately recovers from.
- Expected negative lookup, such as checking whether a file exists.
- Provider transcript lacks enough output to judge success.
- Words like `error`, `failed`, or `invalid` appear inside successful command output, source code, filenames, or documentation.

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

### Provider/Extraction Gap

Use when `mnemonai` cannot expose enough evidence:

- Missing tool call/result IDs.
- Missing status/error markers.
- Missing result text.
- Missing provider/model/session metadata.
- Raw provider data is present but not normalized.

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
