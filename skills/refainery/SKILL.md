---
name: refainery
description: Analyze AI coding agent session history to find where models struggle with tool calls, scripts, rules, hooks, skills, CLIs, or workflows. Use when asked to review recent Claude/Codex/Cursor sessions, diagnose repeated tool failures, identify missing skill instructions, propose improvements to SKILL.md files or automation, or evaluate whether mnemonai/refainery needs better extraction data.
---

# refainery

Use this skill for retrospective session analysis. The goal is to identify concrete, evidence-backed improvements to skills, scripts, hooks, rules, CLIs, or session extraction itself.

Prefer `mnemonai` as the session source. Do not parse provider-specific session stores directly unless `mnemonai` is unavailable or missing data needed for the task.

## Workflow

1. Verify `mnemonai` headless support.
   - Run `mnemonai list --json --limit 1` before starting analysis.
   - If the installed binary rejects `--json`, locate an updated `mnemonai` checkout, build it, and use its `target/debug/mnemonai` binary for the session.
   - If no updated binary is available, stop and report that the skill needs `mnemonai` headless JSON support.

2. Define the scope from the user's request.
   - If no scope is provided, inspect the past 7 days with `mnemonai list --json --since 7d --limit 50`.
   - For current-repo analysis, start with `mnemonai list --json --cwd . --since 30d --limit 50`.
   - For cross-agent or global analysis, start with `mnemonai list --json --since 7d --limit 50`.
   - For a named skill or tool, prefer `--since 30d --limit 200`, then filter summaries, previews, tool names, and nearby text for that skill/tool.
   - Filter by provider, cwd, summary, preview, explicit time window, or explicit session path when the user gives one.

3. Load candidate sessions.
   - Use `mnemonai show <id-or-path> --json` for each selected session.
   - Keep raw transcripts out of the final response unless the user asks for exact excerpts.
   - If a session appears relevant but the JSON lacks tool trace fields, note that as a `mnemonai` extraction gap.

4. Reconstruct the tool trace.
   - Pair `tool_call` and `tool_result` messages by `tool_call_id`.
   - Use `index`, `entry_index`, and `block_index` to preserve chronological order.
   - Record nearby assistant/user text before and after each call so the diagnosis includes intent and recovery behavior.
   - Treat `tool_input`, `tool_result`, and image `source` as opaque provider data; inspect only the fields required for the analysis.

5. Detect struggle signals.
   - Tool result has `tool_result_error: true`, a non-zero `tool_result_exit_code`, or a failing `tool_result_status`.
   - Command-like tool output reports a non-zero exit status, traceback, permission failure, missing command, missing file, invalid usage, or another explicit failure.
   - Treat generic words such as `error`, `failed`, or `invalid` as weak signals when the same output also reports exit code 0; those words often appear in source code, filenames, or documentation.
   - The agent retries the same tool or command with small argument changes.
   - The agent abandons a tool path and switches to a different approach after failure.
   - The agent repeatedly searches or reads files without narrowing the problem.
   - Patch, edit, formatter, test, or lint loops repeat before converging.
   - The user corrects the agent after a tool sequence.
   - Tool output is too noisy, truncated, unstructured, or missing an identifier needed for the next step.
   - The agent says it is trying again, confused, unable to find something, or that the previous attempt did not work.
   - Avoid counting a missing result from the currently active/latest session as a finding unless nearby messages show the tool was abandoned or cancelled.

6. Classify likely causes.
   - Skill instruction gap: `SKILL.md` omitted a necessary command, flag, ordering rule, safety rule, or interpretation detail.
   - CLI/tool UX gap: the tool accepted ambiguous input, emitted hard-to-parse output, hid required identifiers, or lacked a headless mode.
   - Hook/rule gap: a repeated mistake could be prevented by a repo rule, preflight check, shell helper, or validation hook.
   - Environment/access gap: credentials, network, PATH, workspace state, or permissions blocked progress.
   - Model workflow issue: the agent had the data but planned poorly, over-searched, skipped verification, or failed to use an obvious existing pattern.
   - Provider/extraction gap: session JSON lacks IDs, statuses, outputs, timestamps, or context needed for reliable analysis.
   - Benign exploration: the behavior was reasonable discovery rather than actual struggle.

7. Recommend improvements.
   - Prefer small, testable changes with direct evidence from sessions.
   - Separate skill edits, CLI/tool changes, rules/hooks, and extraction improvements.
   - Do not apply edits unless the user asks.
   - If recommending a skill change, inspect the relevant `SKILL.md` first.
   - If recommending a code or CLI change, inspect the owning repo before proposing exact implementation details.

## Output

Lead with ranked findings. For each finding include:

- Symptom: what the agent struggled with.
- Evidence: provider/session identifier plus message indices or tool call IDs.
- Likely cause: one category from the taxonomy.
- Improvement: the smallest concrete change likely to reduce recurrence.
- Confidence: high, medium, or low.

Then include:

- Scope: time window, cwd/project filter, provider filter, and max sessions.
- Sessions inspected and tool calls analyzed.
- Patterns across sessions or providers.
- Suggested next experiments or validation steps.
- `mnemonai` data gaps, if any, that blocked stronger analysis.

## References

- Read `references/mnemonai-json.md` when using or explaining the `mnemonai` headless JSON schema.
- Read `references/failure-taxonomy.md` when classifying ambiguous struggle patterns or comparing multiple findings.
