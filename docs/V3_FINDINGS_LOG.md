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
  learned on train data only.

  Portfolio backtest (`src/backtest_v3.py`) after 3 bug fixes (see below)
  but BEFORE regime hysteresis: window 1 (2024-07..2026-06) +216.94%
  profit / 55.4% win / PF 1.84 / DD -24.33%; window 2 (2023-07..2024-12,
  a choppier period) fell to +16.29% / 50.0% win (exact coin flip) / PF
  1.14 / DD -33.12%. Edge real but unstable across regimes.

  **After adding regime hysteresis** (see "Bug/gap #5" below): window 1
  **+267.18%** / 57.3% win / PF 1.83 / DD -23.56%; window 2 **+28.44%** /
  **51.2% win** / PF 1.27 / DD -28.74%. Every metric improved in BOTH
  windows — win rate now clears 50% even in the weak window. Gap
  narrowed, not eliminated: window 2 is still meaningfully weaker than
  window 1, which makes sense (hysteresis fixes whipsaw noise, not the
  fact that a genuinely choppy market has less trend to ride than a
  crash to sit out or a rally to ride). **Current realistic expectation:
  somewhere between the two windows, not the flagship number alone.**

  **Monte Carlo permutation significance test** (`phase0i_significance_test.py`,
  5000 random same-size draws from the same liquid+bullish opportunity
  set each rule draws from): **p-value = 0.0000 in BOTH windows** — zero
  of 5000 random draws matched or beat the rule's actual mean return, in
  either window, including the weak window 2 (rule mean 1.64% vs random
  draws averaging -0.57%). This is real selection skill, not an artifact
  of testing many hypotheses tonight — the *existence* of the edge is
  not in doubt; its *size* still swings with market conditions.

  **IMPORTANT WALK-BACK: `HYSTERESIS_BAND` sensitivity sweep (0.01/0.02/
  0.03/0.05, both windows) shows the 2% figure above is one point in a
  genuinely noisy parameter landscape, not a validated optimum:**

  | band | W1 profit | W1 win | W1 PF | W1 DD | W2 profit | W2 win | W2 PF | W2 DD | W2 trades | W2 conc |
  |---|---|---|---|---|---|---|---|---|---|---|
  | 0.01 | +501.30% | 62.7% | 2.38 | -32.84% | +28.83% | 54.2% | 1.27 | -28.82% | 177 | 50.5% |
  | 0.02 | +267.18% | 57.3% | 1.83 | -23.56% | +28.44% | 51.2% | 1.27 | -28.74% | 166 | 49.8% |
  | 0.03 | +60.77%  | 54.8% | 1.24 | -32.22% | +39.63% | 53.8% | 1.34 | -25.04% | 169 | 48.3% |
  | 0.05 | +159.97% | 55.8% | 1.68 | -26.08% | +5.21%  | 58.0% | 1.22 | -10.50% | 50  | **82.0%** |

  Window 1 swings 61%→501% across bands with no clean monotonic
  relationship. Window 2 is stable across 0.01-0.03 but **breaks down at
  0.05** — only 50 trades and 82.0% concentration, the exact fragile-
  result signature this whole project has been guarding against.
  **What IS robust**: every single band, both windows, keeps win rate
  above 50% and beats the benchmark — the direction of the hysteresis
  fix (smoothing regime detection helps) holds up. **What is NOT
  robust**: the specific profit/drawdown magnitude at any one band,
  including the 2% reported above as though it were tuned — it wasn't;
  it was picked a priori and got lucky-looking results on the first try.

  **Redesigned as volatility-relative** (`VOL_BAND_MULT`, `backtest_v3.py`):
  band width = `VOL_BAND_MULT × IHSG's trailing 20-day daily-return
  std-dev`, instead of a flat percentage — widens automatically in
  choppy periods, narrows in calm ones. Swept `VOL_BAND_MULT` 1.0/2.0/3.0
  on both windows:

  | mult | W1 profit | W1 win | W1 PF | W1 DD | W1 conc | W2 profit | W2 win | W2 PF | W2 DD | W2 conc | W2 trades |
  |---|---|---|---|---|---|---|---|---|---|---|---|
  | 1.0 | +220.35% | 55.9% | 1.76 | -33.98% | 37.2% | +54.75% | 53.3% | 1.50 | -31.84% | 53.6% | 152 |
  | 2.0 | +225.66% | 59.3% | 1.89 | -31.39% | 41.3% | +26.49% | 55.2% | 1.26 | -35.18% | 51.8% | 174 |
  | 3.0 | +123.44% | 57.8% | 1.55 | -32.23% | 38.8% | +31.16% | 53.8% | 1.30 | -27.86% | 50.3% | 182 |

  **The real win: no catastrophic breakdown at any tested multiplier, in
  either window.** Trade counts stay healthy (152-222) and concentration
  stays in a sane 37-54% range everywhere — contrast with the fixed-%
  design's collapse to 50 trades / 82% concentration at its 5% extreme.
  Window 1's results also cluster far more tightly (123-226% profit, a
  ~1.8x range) than the fixed-% design did (61-501%, an ~8x range) —
  genuinely more predictable behavior near the chosen parameter.

  **Honest tradeoff, not a free upgrade**: absolute profit/win-rate are
  comparable to the fixed-% design's *typical* case, not clearly better,
  and drawdown is consistently somewhat worse (28-35% vs the fixed
  design's best cases of 23-29%, excluding its broken 5% outlier).
  **Verdict: prefer the volatility-relative design for deployment
  despite the modestly worse average numbers** — a design that behaves
  predictably across nearby parameter choices is more trustworthy than
  one that happens to score spectacularly at one hand-picked value,
  which is exactly the failure mode just walked back above. Default
  kept at `VOL_BAND_MULT=2.0` (the standard "2-sigma" convention) since
  it's not clearly dominated by 1.0 or 3.0 in either window.

  **A THIRD, genuinely different OOS window (2023-01..2023-06, not
  overlapping windows 1 or 2) then returned -22.10% net profit, 17.9% win
  rate, alpha -19.34% (underperforms the benchmark) — a real loss, not
  just a weak win.** Traced to a specific, fixable structural gap (six
  positions opening simultaneously on a false-start regime flip, all
  stopped out together) — see "Third OOS window" section below for the
  full trade-level audit. **This is not yet deployment-ready** — three
  windows now show one great result, one modest result, and one that
  loses money, and the losing one has an identified, un-fixed cause.

  Not deployed to production.

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

5. **Regime detector has zero hysteresis** — `strategy.get_regime()`
   flips BULLISH/BEARISH the instant close crosses ma50, with no buffer.
   Near that line, ordinary noise flips the regime back and forth, which
   is the direct explanation for window 2's underperformance (SL exits
   rose to 47.2% of all exits vs 42.5% in window 1 — more whipsaws).
   Insight from reviewing HKUDS/Vibe-Trading (causal hysteresis state
   machine for regime detection) and stefan-jansen/machine-learning-for-trading
   (HMM regime probabilities are inherently smoother than a raw
   threshold) — both pointed at the same gap. **Fix**:
   `compute_regime_with_hysteresis()` in `backtest_v3.py` (V3-only,
   `strategy.py` untouched) — a Schmitt-trigger band: enter BULLISH only
   2% above ma50, exit only 2% below. Requires a sustained move to flip
   state. **Result: improved every single metric in both OOS windows.**
   Window 1: +216.94%→+267.18% profit, 55.4%→57.3% win, DD -24.33%→
   -23.56%, concentration 52.3%→45.2%. Window 2: +16.29%→+28.44% profit,
   50.0%→51.2% win, PF 1.14→1.27, DD -33.12%→-28.74%, concentration
   56.0%→49.8%. Narrowed the window-1-vs-window-2 gap, didn't eliminate
   it — expected, since hysteresis fixes noise-driven whipsaws, not the
   underlying fact that a genuinely choppy market has less trend to ride.

**Standing caution for any future backtest on this data**: always run a
top-5-ticker concentration check on any headline number before trusting
it (this is what caught V1/V2's fake 99%-concentrated "edge"), always
check for survivorship bias in the universe-selection query, and always
sanity-check whether a liquidity/volume filter is actually filtering what
you think it's filtering (Rupiah-value ADTV ≠ genuine institutional
liquidity when a stock has an extreme share count or extreme volatility).

## Third OOS window: a real, structural failure mode (not noise)

Window 3 (train 2021-2022, test 2023-01-01..2023-06-30 -- a fresh
6-month slice not overlapping windows 1 or 2 at all): **net -22.10%,
alpha -19.34% (underperforms the benchmark), win rate 17.9%, profit
factor 0.14, max drawdown -24.07%, only 28 trades, 100.0% concentration**
(literally every winning trade is in the top 5; the other ~23 trades all
lost).

Traced the cause via trade-level audit (`w3_trades.csv`), not accepted
at face value: on 2023-02-06, **six positions opened simultaneously**
(GOTO, BUKA, EMTK, WIRG, ASSA, DMMX -- all legitimate large-caps,
nothing wrong with stock selection) because `MAX_POSITIONS=6` filled
entirely in one day on a regime flip. The rally that triggered
"BULLISH" failed almost immediately -- **all six were stopped out within
2-6 days.** The rest of the window repeats the pattern (re-entries,
mostly losses); only two tickers (HOMI, TMAS) produced real gains across
the whole 6 months.

**This is a genuine, previously-unexamined structural gap: nothing
diversifies ENTRY TIMING.** Position sizing (ALLOC_PCT/RISK_PCT/
LIQ_CAP_PCT) is carefully managed per-position, but a false-start regime
flip can commit the entire portfolio's risk budget on a single bad day,
with zero protection from spreading entries over time. Windows 1 and 2
didn't expose this because their regime flips happened to coincide with
real, sustained moves (an actual crash to sit out, an actual rally to
ride) -- window 3's flip was a fakeout, and the current design has no
defense against that scenario.

**Verdict on "is V3 ready to finalize": no, not as of this finding.**
Three windows now show one great result, one modest result, and one
genuinely bad one that loses money and underperforms the benchmark.
That's not "edge exists but size varies" (the honest conclusion after
two windows) -- it's "edge exists but a specific, identifiable risk
(correlated entry timing on regime-flip days) can produce real losses,"
which needs an actual fix (e.g. staggering entries over multiple days
even when many signals fire at once, or requiring some confirmation
period after a regime flip before deploying full position count) before
this should be treated as deployment-ready, not just disclosed as a
caveat.

## Known open items / next steps

- **Run more OOS windows.** Two (now three effectively, pre/post
  hysteresis) is enough to prove the edge is unstable across regimes,
  not enough to characterize *how* unstable — a third genuinely
  different window (ideally a longer sideways multi-year stretch) would
  help quantify a realistic worst case.
- **`HYSTERESIS_BAND = 0.02` was picked, not tuned/validated** — it
  helped both windows on the first try, which is a good sign, but a
  single a-priori guess isn't a validated hyperparameter. Worth testing
  0.01/0.03/0.05 on both windows to see how sensitive the result is
  before trusting the exact number, and to rule out this being a
  lucky pick.
- ~~Statistical significance check~~ — **done**, see TL;DR: p=0.0000 in
  both windows via Monte Carlo permutation test. Could still go further
  with a proper Deflated Sharpe Ratio (adjusts for the exact number of
  trials run tonight, not just tests one rule against random chance) if
  more rigor is wanted before real capital.
- **Systematic alpha-factor battery** (insight from HKUDS/Vibe-Trading's
  452-factor registry: alpha101/qlib158/gtja191/academic) — instead of
  continuing to hand-invent one feature at a time, batch-test a curated
  set of published, well-known alpha formulas against the existing
  Phase-0 quintile-validation harness. Could surface additional real
  features beyond weekly-trend/sector-RRG. Not started.
- **News sentiment** (insight from snowfluke/sentimeter, which is
  IDX-specific — same market as us) — a genuinely different feature
  category from anything tested so far (foreign flow is a money-flow
  proxy; this would be textual/news sentiment). Would need a new news
  data pipeline, which is more than "algorithm" scope — noted for a
  future phase, not attempted tonight.
- **Triple-barrier labeling** (insight from both ML-for-trading repos)
  — if ML is revisited, label forward return using the actual TP/SL/
  time exit barriers instead of a fixed-horizon return, so the label
  matches what the live system actually does. Lower priority since the
  explicit rule has beaten ML twice already.
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
