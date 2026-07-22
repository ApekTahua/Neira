# V3 Findings Log

Read this first if you're picking up this project cold. It's the log of
what's been tried, what worked, what didn't, and the bugs that made early
numbers look better than they were. Full plan/spec context:
`docs/superpowers/plans/2026-07-15-v2-hmm-screener.md` and
`docs/superpowers/specs/2026-07-15-v2-hmm-screener-design.md` (that's the
V2 HMM-gate plan — superseded, see below).

## TL;DR status

- **V1** (`src/screener.py`, `src/backtest.py`) — live production, Telegram bot. Never touch.
- **V2** (HMM regime gate + ADTV liquidity filter) — built, works, but its
  headline backtest numbers (+668% etc.) turned out to be 99%+ concentrated
  in 5 microcap "gorengan" trades. Not a real distributed edge. Superseded.
- **V3** (current work) — replaced the entry signal entirely after
  statistically proving the old one (MA squeeze + BB squeeze + volume
  spike) has **no edge on liquid stocks in any regime**. New entry rule:
  `BULLISH regime AND weekly-trend-alignment top quintile AND sector-RRG
  relative-strength top quintile`, on liquid stocks (ADTV≥1B), thresholds
  learned on train data only. Portfolio backtest (`src/backtest_v3.py`),
  out-of-sample 2024-07 to 2026-06 (window 1): **net profit +216.94%**
  (after fixing three real bugs that originally inflated it to +486.74%
  — see below), win rate 55.4%, profit factor 1.84, max drawdown -24.33%.
  **A second OOS window (2023-07 to 2024-12, train 2021-2023) came back
  much weaker: +16.29% net profit, win rate exactly 50.0%, profit factor
  1.14, max drawdown -33.12%.** The edge is real but NOT stable across
  market conditions — window 1 covered a period where the bullish-regime
  gate got to sit safely in cash through an actual IHSG crash; window 2
  was a choppier, more range-bound period where the same gate produced
  more whipsaws (stop-loss exits rose from 42.5% to 47.2% of all exits).
  **Treat the realistic expectation as closer to window 2's numbers
  (coin-flip win rate, thin profit factor, 30%+ drawdown possible) than
  window 1's, until more OOS windows are tested.** Not deployed to
  production.

## The core finding: squeeze signal is dead

`docs/superpowers/plans/...v2-hmm-screener.md`'s entry signal (MA squeeze
+ BB squeeze + volume spike, `strategy.get_signals()`) was never
statistically validated in isolation before V2 was built on top of it.
Phase 0 (`src/phase0_signal_validation.py`) tested it directly: **win rate
never clears 50% on liquid stocks, in any regime.** The pattern is a
lottery-ticket detector (rewards low volatility = literally what a
dead-money stock looks like), not a signal.

Real example that exposed this live: 2026-07-22 Telegram signals for
REAL and HDIT scored 70-73% confidence despite both being flat at
Rp50-51 for two months. Root cause: `SLEEPING_PRICE` filter in
`strategy.get_signals()` requires *exact* equality
(`rolling_min_close == 50 AND rolling_max_close == 50`) — one tick to 51
anywhere in the 10-day window breaks the filter. Never fixed in V1 (out
of scope, V1 is frozen); worth fixing if V1 ever gets touched again.

## What was tested, what survived

| Feature | File | Verdict |
|---|---|---|
| Squeeze + vol spike (core signal) | `phase0_signal_validation.py` | **No edge**, any regime, any liquidity tier |
| Foreign net-flow | `phase0b_foreign_flow_validation.py` | **Lagging indicator**, not predictive — correlates with *past* return 15-30x stronger than forward return |
| Sector RRG relative strength | `phase0c_rrg_validation.py` | Weak real signal, monotonic, **bullish-regime-only** (inverts in bearish) |
| Weekly-trend alignment | `phase0d_multitimeframe_validation.py` | **Strongest single feature** — clean monotonic win rate/return, bullish-regime-conditional, inverts bearish |
| Combined ML model (8-12 features, HistGradientBoosting) | `phase0e_ml_combined_model.py`, `phase0h_leaner_interaction_model.py` | **Failed twice** — AUC ~0.50 (random) in most folds even after pruning to just the validated features + explicit regime-interaction terms. The two real univariate signals got *negative* permutation importance in the combined model. |
| Explicit rule intersection (bullish + weekly-trend Q5 + sector-RRG Q5, no ML) | `phase0g_rule_intersection_test.py` | **This is the one that worked.** OOS mean 20d return +7.48% vs +1.18% baseline, concentration check clean (12.6% from top-5 tickers vs V1/V2's 90%+). |
| Adaptive hold-time (`expected_hold_days = |TP-entry|/ATR`, checkpoint exit) | `phase0f_holdtime_exit_backtest.py` | **Mixed** — only helps trades with expected_hold_days≥5d (rare, ~1% of triggers); hurts the majority of fast-resolving trades. Not folded into backtest_v3 yet; needs its own OOS validation before inclusion. |

**Lesson: a simple, explicit, hand-built rule beat every ML attempt on
the same features, twice.** Don't default to throwing a gradient-boosted
model at this kind of data — validate the rule-based hypothesis directly
first. Trees didn't cleanly isolate the sharp joint-percentile region a
manual AND-rule finds trivially.

## Bugs found and fixed in backtest_v3.py (all confirmed real, not hypothetical)

1. **Survivorship bias** — `data_fetch.py` built the tradeable stock
   universe from whichever stocks were trading on the *last day* of the
   fetch window. Any stock delisted mid-backtest vanished entirely,
   including its pre-delisting losses. Confirmed via MFIN (~Rp2.4B/day
   ADTV, collapsed ~85% before delisting Oct 2025) — completely invisible
   before the fix. **Fix**: universe is now the union of stock codes seen
   at monthly checkpoints across the whole range.
   Impact when fixed: net profit +486.74% → +183.48%, max drawdown
   -20.25% → -27.77%. This is a big deal — always check for this pattern
   in any historical-universe query that snapshots a single date.

2. **Delisted position handling** — a position in a stock whose data
   stops (delisting/suspension) would sit forever frozen at its last
   mark-to-market price, never reflecting a real loss. **Fix**: force-exit
   after `DELISTING_GAP_DAYS` (10) consecutive no-data trading days, at
   last known price, tagged `DELISTED_GAP`.

3. **Zero-volume stale prints** — suspended stocks carry a stale close
   forward with `volume=0` on some days (observed directly in MFIN/PIPA
   data). Filling an order against zero real trading is unrealistic.
   **Fix**: entries now check that day's own volume, not just the 20-day
   average.

4. **ADTV (Rupiah-value) liquidity filter doesn't catch hypervolatile
   penny stocks** — a stock with a tiny per-share price but huge share
   count (e.g. PIPA: sub-Rp700, single-day ranges of 10-37%) clears the
   Rupiah ADTV bar easily despite behaving nothing like a real liquid
   large-cap. This is the *mirror image* of the REAL/HDIT dead-money bug
   — same root cause (the liquidity filter measures the wrong thing),
   opposite failure mode. Confirmed via trade audit: 102/177 trades
   (57.6%) had entry price <Rp500, contributing 82.8% of total profit —
   some legitimate (GOTO/BUKA: low price but ~4% avg daily range, huge
   genuine share volume) and some genuinely erratic (PIPA/FUTR/ISAP:
   7-10%+ avg daily range). **Fix**: `ATR_14/close_price <= 10%` cap on
   entry day — price-agnostic, so it excludes the erratic names while
   keeping calm low-price large-caps eligible. Result: took window 1 from
   +183.48% to the final +216.94%, and improved both profit factor
   (1.65→1.84) and max drawdown (-27.77%→-24.33%).

**Standing caution for any future backtest on this data**: always run a
top-5-ticker concentration check on any headline number before trusting
it (this is what caught V1/V2's fake 99%-concentrated "edge"), always
check for survivorship bias in the universe-selection query, and always
sanity-check whether a liquidity/volume filter is actually filtering what
you think it's filtering (Rupiah-value ADTV ≠ genuine institutional
liquidity when a stock has an extreme share count or extreme volatility).

## Known open items / next steps

- **Run more OOS windows.** Two is enough to prove the edge is unstable
  across regimes, not enough to characterize *how* unstable — a third or
  fourth window (ideally spanning a genuinely choppy/sideways multi-year
  stretch, not just two different 1.5-2yr slices) would help quantify a
  realistic worst case rather than anchoring on window 2's single data
  point.
- **Investigate a "don't trade this regime" filter** — something that
  detects choppy/range-bound conditions (not just BULLISH/BEARISH/NEUTRAL
  via price-vs-MA50) and sits out, since window 2's underperformance
  traces directly to more whipsaws (SL exits 42.5%→47.2%) in a period
  IHSG itself was flat. The current regime detector is binary trend
  direction, not trend *quality*/choppiness.
- Adaptive hold-time exit (`phase0f`) needs its own proper OOS validation
  before folding into `backtest_v3.py` — the "helps slow movers, hurts
  fast movers" finding came from looking at bucketed results after the
  fact, not a clean train/test split.
- Not yet tried: shorter forward-return horizons (5/10d instead of 20d)
  for the final entry rule specifically (only tested in the ML attempts,
  not the winning explicit rule); Phase 1-3 items from the original V3
  pitch (regime-conditional playbooks beyond the bullish gate, multi-
  timeframe confirmation beyond weekly) haven't been built since the
  bullish-regime-gate + weekly-trend + sector-RRG rule already covers
  much of that ground.
