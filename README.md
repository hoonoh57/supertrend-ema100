# Supertrend‑EMA100 backtest

A runnable, dependency-light implementation of the strategy and indicator
specification. It uses real Kiwoom REST market data
(daily + 1-minute charts), builds every indicator/feature from the plan, runs a
per-symbol entry/exit state machine with a portfolio layer, and writes
trade/signal/counterfactual reports.

No pandas/numpy: the engine is plain Python (`requests` is the only runtime
dependency), so it runs on the local Python 3.13 install without DLL issues.

---

## 1. Setup

```powershell
python -m pip install -r requirements.txt
```

Credentials are discovered in this order (first file wins per key):

1. `$SUPERTREND_ENV_FILE`
2. `<project>/.env`

Required keys (mock server shown; real keys are also supported):

```dotenv
KIWOOM_MOCK_APP_KEY=...
KIWOOM_MOCK_SECRET_KEY=...
KIWOOM_USE_MOCK=true
```

`KIWOOM_USE_MOCK=false` uses `https://api.kiwoom.com` with
`KIWOOM_REAL_APP_KEY` / `KIWOOM_REAL_SECRET_KEY`.  Secrets are never printed or
written to reports.

## 2. Quick start

```powershell
# Resolve Korean names or 6-digit codes
python run_backtest.py resolve --symbols 삼성전자,SK하이닉스

# Download and cache the bars (optional; backtest does it automatically)
python run_backtest.py fetch --symbols 005930,000660 --days 30 --end 2026-10-28

# Stage 1: trigger + confirmation only (score logged, not enforced)
python run_backtest.py backtest --symbols 005930,000660 --days 30 `
    --end 2026-10-28 --out runs/latest --plot

# Stage 2: enable the composite score gate and grade-based sizing
python run_backtest.py backtest --symbols 005930,000660 --days 30 `
    --end 2026-10-28 --out runs/stage2 --score
```

The defaults are deliberately strict (`min_rti=2.0`, `buy_ratio>=0.55`,
`D<=1.5 ATR`, 3-bar confirmation window).  On a quiet 2-symbol/30-day window
this can legitimately produce zero entries.  Two independent reasons:

* **`EXT` is structural at T1.**  Supertrend uses `st_mult=2.0`, so a fresh
  up-flip puts the close roughly 2.0–2.5 ATR above the line.  `F_EXT` therefore
  defers almost every T1; entries must wait for a pullback re-arm that comes
  back within `d_max` (1.5 ATR) of the line.
* **`K_RTI` is strict in `bar` mode.**  The REST feed has no tick counts, so
  RTI is a volume ratio.  Its median is near 1.0 and readings ≥ 2.0 are rare
  (about 6 % of signal bars in the sample), so most re-arms fail confirmation.

This is the plan's intended "do not chase" behaviour, not a missing trade.  To
exercise the full pipeline on such a window, relax the confirmation thresholds:

```powershell
python run_backtest.py backtest --symbols 005930,000660 --days 30 `
    --end 2026-10-28 --out runs/demo `
    --set confirm.min_rti=1.2 --set confirm.min_buy_ratio=0.5 --set confirm.window=5
```

Add `--score` to apply the grade gate on the same window; grade C entries are
then rejected and B positions are sized at ×0.6.

The package can also be installed (`pip install -e .`) and run as
`python -m supertrend_ema100 ...` or `supertrend-ema100 ...`.

## 3. CLI

```
python run_backtest.py [resolve|fetch|backtest|all] [options]
```

If the first argument is not a subcommand, `backtest` is assumed.

| Option | Meaning |
| --- | --- |
| `--symbols 005930,삼성전자` | Codes or Korean names, comma-separated; repeatable |
| `--start YYYY-MM-DD` | Backtest start (overrides `--days`) |
| `--end YYYY-MM-DD` | Last requested trading day (default: latest) |
| `--days N` | Number of trading days when `--start` is absent |
| `--config file.json` | Load a full/partial config |
| `--set section.key=value` | Override one parameter, repeatable |
| `--feature-mode auto\|bar\|tick` | Tick-feature source mode |
| `--selection score\|time\|random` | Which candidate fills a free slot first |
| `--no-score` | Disable score computation entirely (trigger + confirmation only) |
| `--score` | Stage 2: grade gate + grade multipliers + score ordering |
| `--mock` / `--real` | Force the Kiwoom server |
| `--cache-dir DIR` | CSV cache location (default `.cache`) |
| `--force-refresh` | Ignore the cache and refetch |
| `--out DIR` | Report directory (default `runs/latest`) |
| `--plot` | Write `equity.svg` |
| `--verbose` | Progress log, env sources, pagination |

Without either score flag, the score is computed and logged but not enforced
(the stage-1 default).  `--score` additionally sets `risk.enforce_grade=true`
and defaults `selection` to `score`.

`--set` examples:

```powershell
--set delay.d_max=1.2 --set confirm.min_rti=1.5 --set risk.tax=0.0015
--set risk.enforce_grade=true --set score.grade_b=55
```

`--set` is applied after `--score` / `--no-score`, so it can be used to tune a
stage without changing the command line.

Unknown keys and invalid values are rejected, so a typo cannot silently change
a run.

## 4. Strategy mapping

| Plan section | Implementation |
| --- | --- |
| 1.4 tick size | `indicators/basic.py:tick_size`, `round_to_tick` |
| 2.1 Wilder ATR (SMA seed) | `atr_wilder` |
| 2.2 EMA100 | `ema` |
| 2.3 Supertrend (14, 2) | `supertrend` |
| 2.4 JMA approximation | `jma` |
| 2.5 session VWAP + weighted σ | `session_vwap`, σ floor `max(σ, 0.003·VWAP, 2·tick)` |
| 2.6 RSI(14) | `rsi` (`wilder` or `sma`) |
| 3.1 prior-day baselines | `BaselineBuilder` (median of smoothed prior days, market-profile fallback, floor) |
| 3.2 RTI / accel / buy ratio / ER / ATV / TOV | `compute_tick_features` |
| 4.1 T1 trigger | `filters.is_trigger` |
| 4.2 delay filters | `filters.delay_reasons` (EXT, VI, LIMIT, VICOOL, GAP, BAR, hard day block) |
| 4.3 re-arm | `filters.rearm_event` (ST / JMA / EITHER, pullback depth) |
| 4.4 confirmation | `filters.confirm_checks` (K_VAL, K_VWAP, K_RTI, K_BUY, K_RSI, K_SCORE) |
| 4.5 state machine | `strategy/state_machine.py` |
| 4.6 sizing | `Portfolio.open` |
| 4.7 exits | `BacktestEngine._process_position` (X_STOP, X_TRAIL, X_TP, X_EXH, X_TIME/EOD) |
| 6.2 portfolio | `Portfolio`, `max_positions`, score/time/random selection |
| 6.3 counterfactual | virtual trades for every deferred T1 + per-filter table |
| 6.4 metrics | `backtest/metrics.py` |
| 7 U/M/P score | `indicators/score.py` |
| 7.6 held-position warning | `SCORE_DROP` signal when score falls by `score_drop_warn` and `p_div > 0` |
| 8.1 score validation | Spearman IC and decile table on entry signals |

### Timing contract

A signal is evaluated on bar `t`'s close.  Confirmation is evaluated on the
following bars (as in the plan's pseudocode), and an order is always filled on
the **next** bar's open + `slip_ticks × tick_size`.  No fill ever uses the
signal bar's close.  `X_EOD` decides at the `eod_exit` close and also fills on
the next bar's open; only the session's final bar (or an explicit
`allow_overnight=false` safety exit) liquidates at that bar's close.  Baselines,
VWAP percentiles and gap references use prior days only.  Unit tests assert the
t+1 fill, the EOD next-open fill, the stop-on-next-bar behaviour and the
no-overnight rule.

### Stage 1 vs stage 2

* **Stage 1 (default)** — score is computed and logged for IC analysis, but
  `risk.enforce_grade=false`, so it neither gates nor sizes entries.  Selection
  defaults to `time`.
* **Stage 2** (`--score`) — `risk.enforce_grade=true`: grade C cannot enter,
  grade B uses ×0.6, grade A ×1.0, and selection defaults to `score`.

## 5. Outputs

Every run writes to `--out`:

| File | Contents |
| --- | --- |
| `trades.csv` | Filled trades with entry/exit, R (net and gross), MAE/MFE, hold time, grade, deferred id/reasons |
| `signals.csv` | T1, REARM, REDELAY, CONFIRM_FAIL, ENTRY, FILL, EXIT, REJECT, SCORE_DROP, INVALIDATE with feature snapshot and checks |
| `counterfactual.csv` | Plan 6.3 per-filter table: deferred count, immediate-entry virtual R, re-arm rate, contribution |
| `virtual_trades.csv` | Raw immediate-entry virtual trades |
| `equity.csv` | Per-bar equity, cash, exposure, drawdown |
| `metrics.json` | All metrics plus the effective config and data summary |
| `config.json` | Effective configuration |
| `summary.txt` | Human-readable report |
| `equity.svg` | Daily equity curve (`--plot`) |

The counterfactual table is the key diagnostic: a delay filter is useful only
if `rearm_rate × rearmed_avg_r > immediate_avg_r`.  A `SCORE_DROP` signal is a
monitoring alert only (plan 7.6); it never closes a position by itself.

## 6. Data: what is real and what is a proxy

* **Daily / minute bars are real Kiwoom REST data** (`ka10081`, `ka10080`),
  paginated and cached as CSV under `.cache/bars/`.
* **Regular session only** by default: `09:01–15:20`, NXT after-hours excluded
  (`feature_mode`/`session_*` configurable).  The 09:00 opening auction bar is
  excluded on purpose.
* **Tick fields:** the REST minute chart has no per-tick counts, signed volume
  or path length.  In `bar` mode (the automatic mode for REST data):
  * `n_ticks` ← volume ÷ `assumed_trade_size` (default 1.0; the scale cancels
    in RTI because baselines use the same proxy),
  * `buy_ratio` ← close-location value,
  * `er_tick` ← bar range,
  * `ATV_ratio` is **unavailable (`None`)** and the score uses a neutral 0.5
    for it; reports mark `feature_mode=bar`.
* **True `tick` mode** is supported by the feature/bar code
  (`n_ticks`, `buy_vol`, `sell_vol`, `path_len`, `p_first/p_last`, `vi_flag`)
  and by `KiwoomClient.fetch_ticks`, but the REST tick endpoint only returns
  the most recent ~900 ticks.  A multi-day backtest needs a tick collector
  writing those fields into the bar cache; nothing is fabricated.
* **VI:** the REST chart feed does not provide VI intervals or the exact VI
  reference price.  The engine uses a static ±10 % line from the session open,
  no VI-release timestamp (VICOOL disabled unless configured), and the previous
  close as the limit reference.  These are documented approximations.
* **Mock server:** `KIWOOM_USE_MOCK=true` gives real-shaped but simulated
  prices, useful for plumbing and UI work.  Switch to real keys for research.
* **Survivorship:** the universe is the symbols you pass.  Delisted names are
  not reconstructed automatically.

REST rate limit is ~1 request/second per TR; the client throttles and retries.
A 30-day run over 2 symbols needs roughly 30–40 pages of minute data per symbol.

## 7. Project layout

```
src/supertrend_ema100/
  config.py              dataclass config + JSON/--set overrides
  cli.py                 resolve / fetch / backtest commands
  kiwoom/
    env.py               .env discovery (no secret logging)
    auth.py              token + throttled HTTP + retry
    client.py            ka10081/ka10080/ka10079/ka10099 parsing
    models.py            Bar, DailyBar, StockInfo, Tick
  data/
    cache.py             CSV cache (minute + daily)
    loader.py            trading-day window, session filter, resample, baselines
    series.py            per-symbol indicator/feature/score assembly
  indicators/
    basic.py             ATR, EMA, Supertrend, JMA, RSI, VWAP, tick size
    tick_strength.py     baselines + RTI/accel/buy/ER/ATV/TOV
    score.py             U/M/P score, grades, multipliers
  strategy/
    filters.py           delay, re-arm, confirmation
    state_machine.py     IDLE/PENDING/DEFERRED/IN_POS
    portfolio.py         sizing, cash, trade accounting
    engine.py            event loop, t+1 fills, exits, counterfactuals
  backtest/
    metrics.py           performance, buckets, IC, counterfactual table
    report.py            CSV/JSON/TXT/SVG writers
tests/                   stdlib unittest suite
```

## 8. Tests

```powershell
python -m unittest discover -s tests -t . -v
```

42 tests cover tick-size brackets, ATR/EMA/Supertrend/JMA/RSI/VWAP, baseline
causality (current day never leaks), score normalization/grades, config
validation, REST row parsing, next-bar fills, stop/EOD exits, the no-overnight
rule, deferred counterfactuals, metrics and report writing.

## 9. Extending

* **New indicator** — add a pure function in `indicators/basic.py` returning one
  value per bar, then wire it into `data/series.py` and `SymbolSeries`.
* **New delay/confirm rule** — add the code to `strategy/filters.py`; the
  signal log records the reason/check names automatically.
* **New exit** — add it to `_process_position` and keep the rule “decide on
  close, fill next open” (or explicitly at the stop price, as X_STOP does).
* **New universe rule** — filter `StockInfo` before `load_backtest_data`
  (`market`, `kind`, `shares`, state/audit fields are already parsed).
* **Optimization** — run `--set` grids over delay thresholds only (plan 6.5);
  keep Supertrend/EMA lengths fixed and require ≥100 trades per cell.

## 10. Disclaimer

This is research software for backtesting, not investment advice.  Mock-server
results are simulated; real results depend on data quality, costs, slippage and
market impact.  Verify tax rates and KRX rules for the period you test.
