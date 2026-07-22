# refainery

refainery is an agent skill for retrospective analysis of AI coding agent sessions. The same `skills/refainery/` package works in both Codex and Claude Code: both load and trigger the skill from `SKILL.md` alone.

It uses `mnemonai` as the session extraction layer and focuses the agent on answering one question:

> Where did the model struggle with tools, scripts, rules, hooks, skills, CLIs, or workflow patterns, and what should we improve?

## Current Shape

```text
refainery/
  DESIGN.md
  skills/
    refainery/
      SKILL.md
      references/
        mnemonai-json.md
        failure-taxonomy.md
      scripts/
        evidence.jq
        evidence.sh
        triage.sh
```

The previous Python CLI implementation has been retired on this branch. The first implementation should stay skill-first and depend on `mnemonai` headless JSON output instead of duplicating provider parsers.

## Responsibilities

### mnemonai

- Discover agent sessions across providers.
- Search full session content and rank candidate conversations.
- Normalize conversation summaries.
- Export full session JSON with ordered messages.
- Return focused message windows around content matches while preserving original indices.
- Preserve tool-call IDs, result status/error fields, and raw provider payloads.

### refainery skill

- Preflight the `mnemonai` binary for headless list, search, and focused show support, building it from source into a temporary checkout when the installed binary is too old.
- Use `mnemonai list --json` for unbiased time-window audits and `mnemonai search` for named topics.
- Review candidates with `mnemonai show --grep`, then load unfiltered sessions for final evidence.
- Reconstruct tool traces by pairing `tool_call` and `tool_result` messages.
- Detect struggle patterns such as retries, failed statuses, parse failures, abandoned approaches, noisy outputs, and user corrections.
- Triage detected signals into confirmed failures, review candidates, and benign/noise before writing findings.
- Classify likely root causes.
- Recommend improvements to skills, scripts, hooks, rules, CLIs, or `mnemonai` extraction.

## Non-Goals

- Do not reimplement provider transcript parsing in this repo.
- Do not automatically apply suggested fixes.
- Do not store full raw transcripts in reports by default.
- Do not build a standalone analyzer until real skill usage shows that deterministic code is needed.

## Iteration Path

1. Use the skill manually on recent sessions.
2. Capture recurring analysis steps that are too tedious or error-prone.
3. Improve `mnemonai` when session JSON lacks required evidence.
4. Add small scripts to the skill only after repeated real usage proves they are worth automating.
