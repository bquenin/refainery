---
name: refainery
description: Analyze AI coding agent session history to find where models struggle with tool calls, scripts, rules, hooks, skills, CLIs, or workflows. Use when asked to review recent Claude/Codex/Cursor sessions, diagnose repeated tool failures, identify missing skill instructions, or propose improvements to SKILL.md files or automation.
---

# refainery

Use this skill for retrospective session analysis. The goal is to identify concrete, evidence-backed improvements to skills, scripts, hooks, rules, CLIs, or session extraction itself.

Prefer `mnemonai` as the session source. Do not parse provider-specific session stores directly unless `mnemonai` is unavailable or missing data needed for the task.

## Workflow

1. Verify `mnemonai` headless support.
   - Resolve the binary once with `MNEMONAI_BIN="${MNEMONAI_BIN:-mnemonai}"` and use `"$MNEMONAI_BIN"` for every `mnemonai` command. Shell variables may not persist between commands in every agent, so keep each `mnemonai` call in the same shell as that assignment, or substitute the resolved absolute path (the installed `mnemonai`, or a checkout's `target/debug/mnemonai`) directly into later commands.
   - Run `"$MNEMONAI_BIN" list --json --since 7d --cwd . --limit 1` before starting analysis. Exit 0 with a JSON array confirms the binary supports JSON output plus the `--since` and `--cwd` scope flags this skill relies on.
   - Load one session with `"$MNEMONAI_BIN" show <id-or-path> --json` and confirm `messages[]` is ordered and carries the always-present trace fields `index`, `entry_index`, `tool_call_id`, and `tool_name`. The `tool_result_status`, `tool_result_exit_code`, and `tool_result_error` fields are best-effort: they appear only when the provider exposes them, so their absence is normal and is not a sign of an old binary.
   - Rebuild only on a real version signal — the binary rejects `--json`, `--since`, or `--cwd`, or `"$MNEMONAI_BIN" --version` is older than `0.12.3` by semantic version (compare numerically, so `0.12.10` is newer than `0.12.3`, not older). Then build an updated `mnemonai` from source in a temporary directory and set `MNEMONAI_BIN` to that checkout's `target/debug/mnemonai`. See `references/mnemonai-json.md` for the exact commands.
   - If a checkout cannot be built (no network, no toolchain), stop and report that the skill needs `mnemonai` headless JSON support.

2. Define the scope from the user's request.
   - If no scope is provided, inspect the past 7 days with `"$MNEMONAI_BIN" list --json --since 7d --limit 50`.
   - For current-repo analysis, start with `"$MNEMONAI_BIN" list --json --cwd . --since 30d --limit 50`.
   - For cross-agent or global analysis, start with `"$MNEMONAI_BIN" list --json --since 7d --limit 50`.
   - For a named skill or tool, prefer `--since 30d --limit 200`, then filter summaries, previews, tool names, and nearby text for that skill/tool.
   - Filter by provider, cwd, summary, preview, explicit time window, or explicit session path when the user gives one.

3. Load candidate sessions.
   - Use `"$MNEMONAI_BIN" show <id-or-path> --json` for each selected session.
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
   - The agent claims success while the tool output shows failure (a silent wrong answer); treat this as a high-signal struggle.
   - Treat generic words such as `error`, `failed`, `invalid`, or `usage:` as weak signals when structured fields are absent. Do not count them as failures when `tool_result_error` is false, `tool_result_status` is successful, or the output reports exit code 0; those words often appear in help text, source code, filenames, or documentation.
   - The agent retries the same tool or command with small argument changes.
   - The agent abandons a tool path and switches to a different approach after failure.
   - The agent repeatedly searches or reads files without narrowing the problem.
   - Patch, edit, formatter, test, or lint loops repeat before converging.
   - The user corrects the agent after a tool sequence.
   - Tool output is too noisy, truncated, unstructured, or missing an identifier needed for the next step.
   - The agent says it is trying again, confused, unable to find something, or that the previous attempt did not work.
   - Avoid counting a missing result from the currently active/latest session as a finding unless nearby messages show the tool was abandoned or cancelled.
   - The `cursor-agent` provider records tool calls but not tool results, so its traces are call-only by design. Never treat a `cursor-agent` tool call's absent result as a struggle, abandonment, or cancellation.

6. Triage detected signals before writing findings.
   - For final findings, build evidence with the bundled `evidence.sh` (the full rows) instead of manually joining tool calls and results. Invoke it by the skill's absolute path: `<refainery-skill-dir>/scripts/evidence.sh <id-or-path>`. If step 1 built an updated binary, prefix `MNEMONAI_BIN=<that binary>` or pass the binary path as the second argument. It emits JSONL, one row per flagged tool result, including session metadata, signal/confidence/reasons, paired tool call input, result status/text, and nearby user/assistant context.
   - For a quick compact scan of which results are flagged, run `triage.sh` (a thin projection over `evidence.sh`) instead of retyping the jq. Invoke it by the skill's absolute path (your shell cwd is the project under analysis, so a bare `scripts/...` will not resolve): `<refainery-skill-dir>/scripts/triage.sh <id-or-path>` — typically `~/.codex/skills/refainery/scripts/triage.sh` or `~/.claude/skills/refainery/scripts/triage.sh`. If step 1 built an updated binary, prefix `MNEMONAI_BIN=<that binary>` so triage uses it too. See `references/mnemonai-json.md`.
   - Confirmed failures: structured errors, non-zero exit codes, failing statuses, or text-only failures confirmed by surrounding intent and recovery behavior.
   - Review candidates: strong text-only signals such as tracebacks, shell errors, compiler errors, permission failures, missing files, or invalid usage when structured fields are missing or inconclusive.
   - Benign/noise: successful help output, expected negative tests, docs/source text containing failure words, exploratory misses that immediately recover, and missing results from the currently active/latest session.
   - Only promote a review candidate into the main findings when nearby messages show retry, abandonment, user correction, wrong success claim, or a repeated pattern across sessions.

7. Classify likely causes.
   - Skill instruction gap: `SKILL.md` omitted a necessary command, flag, ordering rule, safety rule, or interpretation detail.
   - CLI/tool UX gap: the tool accepted ambiguous input, emitted hard-to-parse output, hid required identifiers, or lacked a headless mode.
   - Hook/rule gap: a repeated mistake could be prevented by a repo rule, preflight check, shell helper, or validation hook.
   - Environment/access gap: credentials, network, PATH, workspace state, or permissions blocked progress.
   - Model workflow issue: the agent had the data but planned poorly, over-searched, skipped verification, or failed to use an obvious existing pattern.
   - Provider/extraction gap: session JSON lacks IDs, statuses, outputs, timestamps, or context needed for reliable analysis.
   - Benign exploration: the behavior was reasonable discovery rather than actual struggle.
   - When a failure fits more than one category, prefer the cheapest durable fix: documentation (skill) before automation (hook/rule) before tool changes (CLI/UX). Pick the category that matches the recommended fix.

8. Recommend improvements.
   - Prefer small, testable changes with direct evidence from sessions.
   - Separate skill edits, CLI/tool changes, rules/hooks, and extraction improvements.
   - For repeated shell-portability mistakes, prefer a documented baseline rule (a cheap docs/setup fix, not an enforcement hook); for repeated tool-ordering or interpretation mistakes, prefer skill edits; prefer `mnemonai` changes only when evidence is missing, ambiguous, or too hard to reconstruct from JSON. This refines the step 7 precedence (documentation before automation before tool changes) for common cases.
   - Do not recommend an enforcement hook until the same issue repeats across sessions or causes a high-severity failure; a documented rule is fine sooner.
   - Do not apply edits unless the user asks.
   - If recommending a skill change, inspect the relevant `SKILL.md` first.
   - If recommending a code or CLI change, inspect the owning repo before proposing exact implementation details.

## Output

Lead with findings ranked by severity, highest first. For each finding include:

- Symptom: what the agent struggled with.
- Evidence: provider/session identifier plus message indices or tool call IDs.
- Likely cause: one category from the taxonomy.
- Improvement: the smallest concrete change likely to reduce recurrence.
- Severity: high, medium, or low — the impact if the finding is real (see `references/failure-taxonomy.md`).
- Confidence: high, medium, or low — the strength of evidence that the finding is real (see `references/failure-taxonomy.md`).

Then include:

- Scope: time window, cwd/project filter, provider filter, and max sessions.
- Sessions inspected and tool calls analyzed.
- Patterns across sessions or providers.
- Review candidates that were not promoted, if they materially affected confidence or would be useful to inspect next.
- Benign/noise categories suppressed from findings, when that explains why failure-looking text was ignored.
- Suggested next experiments or validation steps.
- `mnemonai` data gaps, if any, that blocked stronger analysis.

## References

- Read `references/mnemonai-json.md` when using or explaining the `mnemonai` headless JSON schema.
- Read `references/failure-taxonomy.md` when classifying ambiguous struggle patterns or comparing multiple findings.
