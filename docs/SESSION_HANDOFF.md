# Session handoff — Supertrend-EMA100 — 2026-10-31

> **Repository being worked on:** `hoonoh57/supertrend-ema100`, `main`.
> **User-reported local VS Code folder:** `E:\deepseek\projects\Supertrend‑EMA100` (nonstandard hyphen may appear in display; prefer copying the actual filesystem path).
> **Last inspected remote HEAD before this documentation-only checkpoint:** `d42761a38d192f0b2eccbf4b7ff9153a0ce05ab6`.
> This document does **not** certify the local Windows folder is clean or identical to GitHub; only GitHub-connected remote source was inspected.

## 1. New session — nonnegotiable first actions
1. Read `AGENTS.md`, `README.md`, `docs/CURRENT_WORK_STATE.json`, `docs/SESSION_HANDOFF.md`, and `docs/TODO.md` from current remote `main`; inspect current GitHub HEAD rather than relying on the recorded SHA.
2. Recover the goal: **Kiwoom REST daily+1m data based Supertrend(14,2)/EMA100/JMA state-machine strategy backtest**, including candidate capture/watch gating, post-signal entry/exit and portfolio performance. Do **not** replace the objective with `leader-selection`'s D1-A source-audit objective.
3. Distinguish **remote committed code** from **uncommitted local VS Code files**. The local directory cannot be read from the GitHub connector. Before Git pull/test, inspect local status. Do not overwrite or reset users' uncommitted work.
4. Summarize in Korean the project purpose, current position, next isolated task, prohibitions. Do not start by coding a new score.

## 2. GitHub repo verified facts
- Remote `main` SHA before handoff was `d42761a38d192f0b2eccbf4b7ff9153a0ce05ab6` (commit message: `Add capture universe and watch-start gating`). No project-specific AGENTS, CURRENT_WORK_STATE, SESSION_HANDOFF, TODO previously existed in the remote root.
- Runtime Python >=3.10; `requests>=2.31.0` is the only listed direct runtime dependency. CLI entrypoint `run_backtest.py`, package under `src/supertrend_ema100/`.
- Kiwoom REST `ka10081` daily, `ka10080` minute data; optional `ka10079` recent ticks. Historical tick coverage is not proven for multiple days; bar-based tick-strength proxies are used unless true tick data is present.
- Implemented modules: indicator cores (`basic.py` ATR/EMA/Supertrend/JMA/VWAP/RSI), tick-strength, U/M/P score, delay/re-arm/confirmation state machine, portfolio, event-driven backtest, CSV/JSON/SVG reports, captured universe loader.
- Recent capture CSV schema in this repo: `date,code,time[,name]`. First capture per date/code. `watch_start` and prewatch policy `defer/carry/ignore` are configurable.
- The documented timing model is signal on bar close, entry on a **later bar open**; no direct signal-close fill. Actual local runtime parity was **not** executed at this checkpoint.
- Existing tests under `tests/` include `test_universe.py`, `test_engine.py`, `test_indicators.py`, `test_ticks.py` etc. README mentions 42 tests, but current exact count and local PASS were **not verified**.

## 3. Three important issues requiring explicit verification
**A. Universe symbol drop (confirmed code-path observation; runtime failing test pending).** `data/universe.py::load_universe` strips a leading A then requires `raw_code.isdigit()` before storing a candidate. Korean stock identifiers like `0011A0` can be silently dropped. `kiwoom/client.py::normalize_code` supports alphanumerics differently. Add one focused test on input normalization in the next micro-tranche; do not patch broad modules at once.

**B. MFE label inconsistency (confirmed code-path observation, not a backtest failure).** `tools/capture_mfe.py` sets `reference = bars[0].close` then computes MFE from minute high. This is **not** the 2026-10-30 research policy of buying on the first actual 09:11 trade. Label each metric differently and do not claim their results are comparable without true tick history.

**C. Pre-capture prewatch state (audit hypothesis).** `watch_phase` identifies a `pre` phase before the effective watch start; `SymbolStateMachine.on_bar` may store a prewatch T1. Determine if that T1 is pre-capture or merely pre-watch-start, and whether replay of future-selected symbols uses ineligible historical triggers. Preserve intended watch-start behavior but do not let candidate inclusion after time t leak into t decisions.

Other review: default regular session `09:01–15:20`; REST tick feed only limited recent data; VI/limit/proxy assumptions; simulated fills, cost/risk settings. Do not interpret a simulated profit as a live result.

## 4. Current verification position
- **Source/README inspection:** remote code and commit metadata read successfully.
- **Local Git status / local HEAD / uncommitted files:** UNKNOWN; no direct access to `E:\deepseek\projects\Supertrend‑EMA100` from this assistant environment.
- **Python unittest on actual checkout:** NOT_RUN in this handoff. An attempted public clone in isolated environment failed due to DNS/network access; it did not inspect the Windows folder.
- **Backtest return or PF/MDD:** NOT_EVALUATED here.
- **Feature causal/PIT audit:** NOT_RUN.
- **Changed file scope:** documentation-only checkpoint. No strategy/indicator/backtester source edits were made.
- **Full repository architectural/compliance PASS:** NOT_AUDITED.

## 5. Exact safe next task — baseline reconciliation before any source edits
On Windows PowerShell 5.1, **in the real local workspace** (do not use the `leader-selection` directory):

```powershell
Set-Location -LiteralPath 'E:\deepseek\projects\Supertrend‑EMA100'
git status --short --branch
git remote -v
git rev-parse HEAD
python --version
python -m unittest discover -s tests -t . -v
```

First verify that the local directory exists and is the intended repository. If local changes are present, **preserve and review them before any pull**. If the tree is clean and remote tracking matches, then optionally run `git pull --ff-only origin main`. If `requests` is missing, handle that as an environment issue; installing packages may require a permitted local environment.

Return the **non-secret** local git status/HEAD and test summary (test count, errors, failures). Only after this checkpoint begin the smallest focused alphanumeric symbol parsing test, then fix the parser if the failing test demonstrates the issue. Do not modify unrelated files or invent live order integrations.

## 6. Session continuity and prohibitions
- GitHub remote file edits and commits first; local pull/test only, unless user explicitly overrides.
- Separate this project's Python backtest tests/results from `hoonoh57/leader-selection` and legacy SQL repos.
- User secrets, real order data, `.env`, minute caches, run folders and proprietary KWD/HOGA files are never committed.
- Failed assertion, repository-wide structure, and project compliance are separate statuses; never call an unexecuted test PASS.
- Every follow-up writes the new tested HEAD, root cause classification, changed files, test evidence and next isolated tranche into `docs/CURRENT_WORK_STATE.json` and this handoff.
