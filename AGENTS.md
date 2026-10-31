# Agent operating contract — Supertrend-EMA100

## Mandatory session restart
1. Read `AGENTS.md` (this file), `README.md`, `docs/CURRENT_WORK_STATE.json`, `docs/SESSION_HANDOFF.md`, and `docs/TODO.md` **from the current remote HEAD**.
2. Read the concrete files and tests for the single tranche being worked on.
3. State in Korean: project purpose, current work location, next narrow task, and prohibitions **before code changes**. Never infer that local and remote Git trees are identical.
4. In the local Windows working tree, inspect `git status --short --branch`, `git remote -v`, `git rev-parse HEAD` **before pull/reset/edit**. Do not overwrite uncommitted work.

## Repository identity and scope
- Project repository: `hoonoh57/supertrend-ema100` (Python REST-data backtester). User-reported VS Code working folder: `E:\deepseek\projects\Supertrend‑EMA100`. The exact local `.git` remote, HEAD, and dirty state have NOT been verified by this remote document.
- Distinct repository: `hoonoh57/leader-selection`, whose active D1-A task and artifacts are **not** this backtester's current state.
- Historical `Leader_Lab` is an unrelated read-only research reference. Do not merge SQL/code/state/test results between repos.
- No live brokerage order engine or profitable strategy claim is established in this repository.

## Permanent engineering constraints
- GitHub-first editing: change remote source when requested; local machine only pulls and executes tests. Do not direct blind PowerShell rewrites or overwrite Windows files.
- One micro-tranche at a time: code/test change in one responsibility boundary → automated verification → evidence/WYSIWYG if applicable → docs checkpoint/commit → next.
- Never weaken tests, mask structural failure with allowlists, or silently reinterpret an input contract to obtain green.
- Label each issue: test defect / product defect / authority drift / environment issue / unknown. Differentiate changed-file tests, repository-wide boundary audit, and overall compliance.
- Prevent future leakage: decisions only use features available at decision time; fill must not use signal-close as a realizable fill, except explicitly documented exceptional execution models.
- Keep genuine tick signals distinct from approximated bar-based signals. Do not treat REST mock prices as real tradable performance.
- Do not commit keys, `.env`, account data, proprietary KWD/HOGA archives, output caches or execution logs.
- For any later integration into the wider four-axis trading platform: Chart generic drawing SSOT, Bridge/Runtime feature-blind, Add-on private calculations/semantics, JSON persistence-only. Do not retrofit feature-specific chart or runtime logic.
- Windows PowerShell 5.1 and UTF-8 safety are mandatory for any scripts; ordinary PASS logs should be concise and evidence-backed.

## Current status
See `docs/CURRENT_WORK_STATE.json`, not prior chat. As of the 2026-10-31 handoff, the *remote* Python source has capture-universe/watch-start gating; runtime tests and local uncommitted changes have not been inspected from this environment.
