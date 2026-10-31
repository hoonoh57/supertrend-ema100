# Supertrend-EMA100 — pending work by validation gate

**Only the remote repository was inspected for the 2026-10-31 checkpoint. The user's local Windows working tree is not accessible from this environment. The boxes below are NOT assertions of success.**

## Gate 0: preserve and reconcile local work first
- [ ] In `E:\deepseek\projects\Supertrend‑EMA100`, record `git status --short --branch`, `git remote -v`, and `git rev-parse HEAD` without editing or resetting.
- [ ] Compare exact local remote/branch/HEAD and uncommitted files against `hoonoh57/supertrend-ema100` GitHub `main`; avoid pulling until the local working tree is safe. Any local-only changes must be reviewed/preserved before further GitHub writes.
- [ ] Run `python --version` and confirm `requests` is importable, without printing credential values.

## Gate 1: execute unchanged baseline
- [ ] Run `python -m unittest discover -s tests -t . -v` locally on the actual checkout.
- [ ] Record run date, Python version, local SHA, exact test counts, errors/warnings, and environment-sensitive failures; classify before modifying assertions.
- [ ] Run CLI help/safe off-market smoke if appropriate: `python run_backtest.py --help`. No live trading or credential-dependent fetch is required for initial tests.

## Gate 2: assess one causal/data defect at a time
- [ ] **Alphanumeric ticker coverage:** `src/supertrend_ema100/data/universe.py::load_universe` requires `raw_code.isdigit()`, so a code such as `0011A0` is silently skipped. Add a failing focused test; preserve legitimate code format and reject malformed ones; modify only the universe loader boundary; rerun all tests.
- [ ] **MFE reference definition:** `tools/capture_mfe.py` uses first qualifying minute bar's **close**. Prior 2026-10-30 research defined first **actual trade at 09:11** as entry. These are different metrics. Document label policy explicitly and use full historical tick data when exact trade entry is required. Never silently substitute minute close.
- [ ] **Capture/watch causal guard:** inspect how prewatch T1/DEFERRED state is accumulated for a stock that was not captured yet. Verify that no pre-capture candidate alert or prewatch carry creates an invalid post-capture recommendation. Write one targeted test before any adjustment.
- [ ] **Bar-mode proxies:** quantify the impact of proxy `buy_ratio`, `n_ticks`, `er_tick`, `RTI` versus real tick mode. Do not present bar-mode metrics as true orderflow.
- [ ] **Boundary audit:** validate t-close signal → next-bar open fill, prior-day warm-up, trading session times (`09:01–15:20` defaults), VI assumptions, no lookahead, tax/commission/slippage.

## Gate 3: confirm strategy performance only after data semantics pass
- [ ] Fix a historically captured full universe and immutable as-of decision windows; compare Stage 1 (score logged only) vs Stage 2 (score gate + sizing) on the exact same candidate universe.
- [ ] Preserve complete config, symbol-day counts, source provenance, signal logs, trades, virtual trades, MFE/MAE, PF/MDD and failure cases; run chronological out-of-sample validation.
- [ ] Separate mock/rest-bar/tick results; do not claim actual profit or readiness to trade without reproducible costs and forward paper fills.
- [ ] Update README and current-state/handoff docs only after verified local or CI evidence; never mark a task PASS solely because a source function exists.

## Scope boundary
This is a **standalone Supertrend-EMA100 historical backtester** task list, not the six-category `leader-selection` plan. Do not import the other repo's current D1-A status.
