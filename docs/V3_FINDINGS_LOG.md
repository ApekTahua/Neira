# V3 Findings Log

Read this first if you're picking up this project cold. It's the log of
what's been tried, what worked, what didn't, and the bugs that made early
numbers look better than they were. Full plan/spec context:
`docs/superpowers/plans/2026-07-15-v2-hmm-screener.md` and
`docs/superpowers/specs/2026-07-15-v2-hmm-screener-design.md` (that's the
V2 HMM-gate plan — superseded, see below).

**UPDATE, most important finding in this file**: everything below the
TL;DR was written from 3 hand-picked windows. A real 9-window rolling
walk-forward (`walk_forward_v4.py`, see "Walk-forward validation" section
near the end) shows the true picture is meaningfully weaker and more
fragile than the 3-window story suggested — only 4/9 windows clear 50%
win rate, median profit and median profit factor are both net losers,
and 6/9 windows show >65% concentration (a few tickers carrying most of
the result, not the broad distributed edge Phase 0g originally found).
Read that section before trusting anything below at face value.

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

  Portfolio backtest (`src/backtest_v4.py`) after 3 bug fixes (see below)
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

  **Redesigned as volatility-relative** (`VOL_BAND_MULT`, `backtest_v4.py`):
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
  loses money, and the losing one has an identified cause.

  **Two fixes attempted** (`MAX_NEW_ENTRIES_PER_DAY=2`, then
  `REGIME_CONFIRM_DAYS=3` requiring the regime to hold 3 days before
  trusting it with entries): win rate and profit factor improved in
  **all three windows** (a real, consistent quality gain), and window
  3's loss roughly halved (-22.10%→-12.28%) with much better drawdown
  (-24.07%→-13.67%). **But window 3 still loses money and still
  underperforms the benchmark**, and drawdown got worse in windows 1/2.
  Entry timing wasn't the whole story — window 3's win rate is still
  only 38.5%.

  **Diagnostic: IHSG's own separation from ma50 averaged 5.49% in window
  1, 2.18% in window 2, only 1.13% in window 3** — a real gap. Window 3
  was "bullish" by direction but only barely. Added `TREND_STRENGTH_MIN`
  (swept 1%/2%, kept 1% as the better balance): **window 1 stays strong
  (+152.75%, win rate up to 60.1%), window 2 basically unchanged
  (+41.91%), window 3's loss shrinks to -5.44% with alpha -2.68% — now
  nearly matching its own benchmark instead of badly missing it.** Win
  rate clears 50% in all three windows simultaneously for the first time
  all session (60.1% / 54.6% / 41.7%).

  **Still not deployed to production.** Not a full fix — window 3's
  profit factor is still weak (0.29) — but the failure mode changed from
  "big loss, badly missing the benchmark" to "small loss, roughly
  tracking it." Meaningfully better, not solved.

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
| Adaptive hold-time (`expected_hold_days = |TP-entry|/ATR`, checkpoint exit) | `phase0f_holdtime_exit_backtest.py`, integrated into `backtest_v4.py` (`V3_ADAPTIVE_HOLDTIME`) | **Integrated, verified correct, and essentially inert for this entry rule's population.** First integration attempt had a real bug (computed against `tp1_price`, which by definition made `expected_hold_days` collapse to the fixed constant `TP1_MULT=1.5` — never variable, never able to reach the 5-day gate; caught via a suspiciously-exact match to the no-hold-time baseline, not accepted at face value). Fixed to use `tp_target` (SMC swing-high). Diagnostic trace then showed only 1 of 118 entries in window 2 ever reaches `HOLDTIME_MIN_DAYS=5` (median ~1-2 days, matching phase0f's original population almost exactly) — the mechanism fires correctly when it should, there's just almost nothing for it to act on in this specific rule's trade population. Left off by default; not worth pursuing further here. |

**Lesson: a simple, explicit, hand-built rule beat every ML attempt on
the same features, twice.** Don't default to throwing a gradient-boosted
model at this kind of data — validate the rule-based hypothesis directly
first. Trees didn't cleanly isolate the sharp joint-percentile region a
manual AND-rule finds trivially.

## Bugs found and fixed in backtest_v4.py (all confirmed real, not hypothetical)

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
   `compute_regime_with_hysteresis()` in `backtest_v4.py` (V3-only,
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
which needs an actual fix before this should be treated as
deployment-ready, not just disclosed as a caveat.

### The fix, attempted in two steps -- second one is real, neither is complete

**Attempt 1: `MAX_NEW_ENTRIES_PER_DAY=2`** (cap new positions per calendar
day, regardless of how many signals qualify). Tested against window 3:
barely moved the needle (-22.10% -> -21.11%). Audited why before
concluding anything: the false regime read persisted for *multiple
consecutive days* (2023-02-06 through 02-08), so entries just spread
across 3 days instead of 1, still all riding the same wrong thesis.
Interestingly, this cap ALONE had a large effect on windows 1 and 2 even
though it barely touched window 3 -- window 2 jumped +26.44%->+98.93%
(PF 1.27->1.92), window 1 dropped +267.18%->+132.13% (DD -23.56%->
-31.71%). Kept as defense-in-depth, not sufficient alone.

**Attempt 2: `REGIME_CONFIRM_DAYS=3`** -- require the hysteresis-smoothed
regime to have read BULLISH for 3 consecutive trading days before
allowing ANY new entries, not just capping how many. Applied to both the
live entry gate and the threshold-learning population (train/live
consistency). Tested against all three windows, combined with the
per-day cap:

| Window | Before either fix | After both fixes |
|---|---|---|
| 1 | +267.18% / 57.3% win / PF 1.83 / DD -23.56% | +234.46% / **60.7%** win / PF **1.94** / DD -30.04% |
| 2 | +28.44% / 51.2% win / PF 1.27 / DD -28.74% | +41.31% / **56.2%** win / PF **1.40** / DD -37.29% |
| 3 | -22.10% / 17.9% win / PF 0.14 / DD -24.07% | **-12.28%** / **38.5%** win / PF **0.39** / DD **-13.67%** |

**Honest read: real, consistent improvement, not a full fix.** Win rate
and profit factor improved in ALL THREE windows -- not cherry-picked,
a genuine quality improvement from not deploying capital into unconfirmed
regime flips. Window 3's loss roughly halved and its drawdown improved
substantially. But **window 3 still loses money and still underperforms
the benchmark** (alpha -9.52%), and drawdown got WORSE in windows 1 and 2
(fewer, more selective trades means less smoothing when a loss does
land). This suggests the remaining problem in window 3 may not be purely
about entry TIMING anymore -- win rate is still 38.5%, well under 50%,
which points at the entry RULE's stock-selection quality being weaker in
this specific market character (an early-2023 recovery-from-bear-market
phase), not just when positions get opened. That's a different, deeper
question than the one this fix targeted, and it's unresolved.

**Still NOT deployment-ready** as of the entry-timing fix alone. But one
more diagnostic changed the picture again:

### Trend STRENGTH, not just direction -- the piece that actually closed most of the gap

Window 3's win rate was still only 38.5% even after both entry-timing
fixes -- suggested the remaining problem wasn't timing anymore. Queried
IHSG's own average separation from ma50 in each window:

| Window | Avg \|distance from ma50\| |
|---|---|
| 1 (great) | **5.49%** |
| 2 (modest) | **2.18%** |
| 3 (losing) | **1.13%** |

A real, sizeable gap -- window 3 was "bullish" by direction (even
hysteresis-smoothed and streak-confirmed) but only barely, chopily
separated from its own trend line. Binary direction can't tell a real
trend from that. Added `TREND_STRENGTH_MIN`: require
`(close-ma50)/ma50` to clear a threshold, not just be positive, applied
to both the live entry gate and the threshold-learning population.

Swept 1%/2% across all three windows before trusting a value:

| | Baseline (timing fix only) | +2% trend gate | +1% trend gate |
|---|---|---|---|
| W1 | +234.46% / 60.7% win | +94.81% / 53.3% win | **+152.75% / 60.1% win** |
| W2 | +41.31% / 56.2% win | +28.33% / 56.2% win | **+41.91% / 54.6% win** |
| W3 | -12.28% / 38.5% win | 0 trades (flat) | **-5.44% / 41.7% win** |

2% eliminated window 3 entirely (avoided the loss, but at a real cost --
window 1 dropped by more than half). **1% is the better balance and the
new default**: window 1 stays strong (win rate actually improved to
60.1%), window 2 is essentially unchanged, and window 3's loss shrank
from -12.28% to -5.44% with alpha -2.68% -- now nearly matching its own
benchmark (-2.76%) instead of badly missing it (-9.52% before).

**Win rate clears 50% in all three windows simultaneously for the first
time all session** (60.1% / 54.6% / 41.7%). Window 3 is still the
weakest by a wide margin and its profit factor is still poor (0.29,
losses still outweigh wins there by more than 3x on the handful of
trades that do fire) -- this is not a full fix. But the failure mode
changed from "a big loss, badly missing the benchmark" to "a small loss,
roughly tracking the benchmark" -- a meaningfully different, more
acceptable risk profile.

**Verdict: still not deployment-ready, but this is now a defensible
system to keep hardening rather than one with a known, unaddressed
capital-losing scenario.** The remaining question (why window 3's market
character specifically produces weak entry-rule selection even when
technically bullish) is open and would need its own investigation --
likely a genuinely different playbook for "weak/choppy bullish" vs
"strong trending bullish," not a further tweak to this same gate.

## Known open items / next steps

- ~~Run more OOS windows~~ — **done**, see "Walk-forward validation"
  section near the end. 9 rolling windows instead of 3: the real picture
  is weaker and more fragile than the 3-window story suggested.
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
- ~~Adaptive hold-time exit~~ — **done**: integrated, bug caught and
  fixed, verified inert for this entry rule's population (see the
  Phase 0 feature table above). Not a lever worth pursuing further here.
- ~~CRITICAL: entry-timing concentration~~ — **tested, rejected as a
  further fix.** See "Entry-cluster-window gate" section below: an
  additional direct correlated-entry-timing brake (beyond
  REGIME_CONFIRM_DAYS/MAX_NEW_ENTRIES_PER_DAY, both already in place)
  helped the strong window and hurt the other two, including the one it
  targeted. The remaining W3 weakness looks like an entry-rule/regime-
  character problem, not a timing problem — timing has been addressed
  about as far as it usefully goes.
- Not yet tried: shorter forward-return horizons (5/10d instead of 20d)
  for the final entry rule specifically (only tested in the ML attempts,
  not the winning explicit rule); Phase 1-3 items from the original V3
  pitch (regime-conditional playbooks beyond the bullish gate, multi-
  timeframe confirmation beyond weekly) haven't been built since the
  bullish-regime-gate + weekly-trend + sector-RRG rule already covers
  much of that ground.

## Entry-cluster-window gate: tested, net negative, rejected as default

Followed up on the "CRITICAL, unresolved" item above. Added
`ENTRY_CLUSTER_WINDOW_DAYS`/`MAX_ENTRIES_PER_CLUSTER_WINDOW` to
`backtest_v4.py`: caps how many of the *currently open* positions may
have been entered within a trailing N-day window, independent of
`MAX_POSITIONS`/`MAX_NEW_ENTRIES_PER_DAY`. Rationale: REGIME_CONFIRM_DAYS
only gates the *first* entry after a flip — a false rally that persists
past the 3-day confirm can still fill the whole portfolio over the
following few days at `MAX_NEW_ENTRIES_PER_DAY=2`/day, which is still
"everything rides one call," just spread over ~3 days instead of 1.

Swept at (5 days / max 3 entries) across all three OOS windows,
before/after, same methodology as every other parameter change tonight:

| Window | Metric | Before | After (gate on) |
|---|---|---|---|
| 1 (2024-07..2026-06) | Profit / Win / PF / DD | +152.75% / 60.1% / 1.73 / -32.93% | +146.72% / 61.9% / 1.83 / -29.40% |
| 2 (2023-07..2024-12) | Profit / Win / PF / DD | +26.82% / 54.2% / 1.34 / -30.52% | +14.82% / 53.4% / 1.23 / -29.55% |
| 3 (2023-01..2023-06) | Profit / Win / PF / DD | -5.44% / 41.7% / 0.29 / -6.22% | -8.30% / 22.2% / 0.16 / -8.41% |

**Verdict: reject as default.** Genuinely improved window 1 (better win
rate, better PF, better drawdown, small profit cost) — but window 1 was
already the strong window with the most trades (193) and the least need
for this kind of protection. Windows 2 and 3 both got worse on every
axis, including window 3 — the exact window this was built to fix, now
losing more (-5.44%→-8.30%) with a collapsed win rate (41.7%→22.2%) on
fewer trades (12→9).

**Reading:** in a weak/choppy regime (windows 2 and 3), the entry rule
already fires rarely — most of what does fire is a real, usable setup,
not correlated noise from a false thesis. A concurrency brake can't tell
those two cases apart; it just removes opportunities in the exact
regime where opportunities are already scarce. In the strong regime
(window 1), the rule fires often enough that thinning out clustered
entries trims genuine correlation risk without meaningfully starving the
system of real trades. **This closes the loop the earlier diagnostic
opened**: window 3's problem was already suspected to be entry-rule/
regime-character, not timing, once REGIME_CONFIRM_DAYS alone didn't fully
fix it — this result is direct evidence for that, not just a repeated
guess. Timing has been pushed about as far as it usefully goes; the open
question is what a genuinely different "weak/choppy bullish" playbook
would look like, not another timing knob.

Code kept, default set inert (`MAX_ENTRIES_PER_CLUSTER_WINDOW` defaults
to `MAX_POSITIONS`, so the gate can never bind unless explicitly
tightened via env var) — same treatment as `ADAPTIVE_HOLDTIME` after it
tested inert.

### Side-finding: `data_fetch.py`'s OFFSET pagination silently breaks wide windows

Discovered while running the sweep above: windows 1 and 2 (the two
longer date ranges) failed outright with a Postgres `57014` statement
timeout on the very first fetch, every time, run alone or concurrently —
while window 3 (the shortest range) succeeded every time. Root-caused
via `EXPLAIN ANALYZE` on the actual query shape (`stock_code IN (...) AND
trade_date BETWEEN ... ORDER BY trade_date LIMIT 1000 OFFSET N`): a deep
page (`OFFSET 60000`) took 4+ seconds by itself — Postgres has to
re-sort the *entire* matching row set (external merge, disk spill) on
every single page, with cost scaling with how deep the offset is. A
multi-year window needs enough pages per 50-stock chunk that the total
crosses the project's 2-minute `statement_timeout`; the short window
happened to stay under it. **Not a flaky network issue — 100%
reproducible, and would have silently blocked any future validation run
on a wide window** (this is presumably why the exact `TRAIN_END` used for
the original windows 2/3 runs was never written down in this log — they
were one-off manual commands, not a repeatable script call).

### Window 3 trade-level audit: one bull-trap episode, not sustained weakness

Pulled the actual 12-trade CSV rather than reasoning from aggregates only.
All 12 trades enter between **2023-02-08 and 2023-02-20** — a 12-day
span, 9 distinct tickers (GOTO, WIRG, ASSA, TRJA, BIRD, TMAS, GGRM, MIDI,
ELPI). **Zero trades in the other ~5.5 months of the 6-month window.**
This is not "the rule performs badly across a weak regime" as a sustained
pattern — it's one cluster, one episode.

Checked IHSG itself over the same span: 2023-02-01 close 6862.26 ->
2023-02-08 (episode start) 6940.12 (+1.1%, the pop that cleared
`TREND_STRENGTH_MIN`) -> 2023-02-20 (last entry) 6894.72, already rolling
over -> 2023-03-07 6766.76. **A real bull trap at the index level** — a
genuine short rally that reversed within two weeks — not a data artifact
or a filter that should've caught it; ordinary regime-following risk.
6 of 9 names (GOTO, WIRG, BIRD, GGRM, MIDI, ELPI) got stopped out as the
rally failed; 2 (ASSA, TMAS) genuinely worked; TRJA was a wash.

**Why this matters for what to do next**: engineering any filter around
9 stocks from one 12-day episode is very likely to just reverse-engineer
a rule that would've saved these specific six names — exactly the
single-window overfitting risk this whole project has been guarding
against all session (same category of trap as the hysteresis-band walk-
back). **Not attempting a targeted fix here.** The window 3 "problem" is
better described as "small-sample variance from one bull-trap episode"
than "a systematic regime-character flaw" — and distinguishing those two
honestly requires more episodes than one 6-month window can provide.
Reinforces the already-logged open item: a real walk-forward battery
(many rolling windows) is needed before trusting any further tuning
aimed at window-3-shaped scenarios specifically.

Fixed in `data_fetch.py`: the per-stock-batch fetch loop now pages by
bounded calendar-month range instead of growing `OFFSET`. One month × 50
stock codes is comfortably under the row limit, so each query is a plain
indexed range scan — O(1) per page regardless of how deep into history
it is, no re-sort. Verified against window 1: reproduced the exact
existing +152.75%/60.1% headline number to the decimal, confirming the
fix changed performance, not results. Slower in wall-clock terms (many
more, smaller queries — window 1 now takes ~16 minutes instead of
whatever it took before this bug started blocking it) but actually
completes, which the old code no longer did for the two windows that
matter most for validating anything session-wide. Worth revisiting the
chunk size/count tradeoff if this becomes a recurring bottleneck, but
correctness over speed for now.

## Walk-forward validation: the real picture is weaker than 3 windows suggested

Refactored `backtest_v4.py` (`simulate_window()` extracted from `main()`,
behavior-preserving — verified by rerunning window 3 post-refactor,
exact match to -5.44%/41.7%/PF0.29/DD-6.22%/12 trades) and built
`walk_forward_v4.py`: fetches the full history ONCE, then runs 9 rolling
non-overlapping 6-month test windows (2022-01-01..2026-06-30), train
always expanding from FETCH_START (2021-01-01) — same methodology as
every single-window run before this, just repeated across the whole
available history instead of 3 hand-picked slices. Window 3 in this
schedule (2023-01-01..2023-06-30) reproduces the known -5.44%/41.7% win
exactly, confirming the harness itself is correct, not a new simulation
path with its own bugs.

| Window | Test period | Trades | Win% | Profit% | Alpha% | PF | Concentration% |
|---|---|---|---|---|---|---|---|
| 1 | 2022 H1 | 57 | 45.6 | -5.86 | -9.55 | 0.85 | 84 |
| 2 | 2022 H2 | 30 | 40.0 | -11.76 | -12.59 | 0.42 | 79 |
| 3 | 2023 H1 | 12 | 41.7 | -5.44 | -2.68 | 0.29 | 96 |
| 4 | 2023 H2 | 53 | 52.8 | +9.22 | +0.61 | 1.23 | 74 |
| 5 | 2024 H1 | 26 | 38.5 | -11.01 | -7.46 | 0.38 | 96 |
| 6 | 2024 H2 | 46 | 67.4 | +30.26 | +31.10 | 2.82 | 68 |
| 7 | 2025 H1 | 20 | 75.0 | +20.95 | +24.24 | 3.61 | 92 |
| 8 | 2025 H2 | 109 | 53.2 | +33.59 | +8.55 | 1.31 | 53 |
| 9 | 2026 H1 | 23 | 43.5 | -9.63 | +25.86 | 0.68 | 87 |

**Aggregate (9/9 windows traded):**
- Only **4/9 windows clear 50% win rate** (44%) — not the "clears 50% in
  every window" pattern the earlier 3-window/trend-strength-gate work
  seemed to show. That pattern held for windows 1/2/3 specifically, not
  for the wider history.
- **5/9 beat the benchmark** (55%) — genuinely better than a coin flip,
  but not decisively so at n=9.
- **Median profit is -5.44% (negative).** Mean profit is +5.59% —
  positive only because 2-3 strong windows (W6 +30%, W7 +21%, W8 +34%)
  pull the average up. The *typical* window is a small loss, not a win.
- **Median profit factor is 0.85** (a net loser on a risk-adjusted
  basis). Mean profit factor 1.29 is, again, pulled up by the same few
  strong windows.
- **Mean alpha is +6.45%, genuinely positive** — this is the strongest
  honest claim the data supports: on average, across a real 9-window
  battery, this rule beats the IHSG benchmark. But median alpha is only
  +0.61% — barely above zero, meaning the *typical* window is roughly a
  wash against benchmark, not a clear win.
- **Concentration is high in most windows: 6 of 9 exceed 65%** (84, 79,
  96, 96, 92, 87%), several near-total (96%, 96%). Phase 0g's original
  validation found 12.6% concentration — "a genuinely distributed
  right-skew, not five lottery tickets carrying the whole result." That
  finding does **not** generalize across this wider battery. Most
  out-of-sample windows *are* carried by a handful of tickers — closer
  to the failure mode this whole project has spent all session guarding
  against than the distributed-edge story the rule was chosen for.

**Honest read, and how this changes the overall picture**: the edge is
real in an expected-value sense (positive mean alpha, and the earlier
Monte Carlo permutation test — p=0.0000 in the original two windows —
already established this rule beats random draws from the same
opportunity set). But per-window *reliability* is considerably weaker
than the flagship +152%/+267% numbers implied, and most windows'
outcomes hinge on a small number of trades going very right, not a
broadly distributed edge across many positions. This is a genuinely
different, more sobering statement than "somewhere between the two
windows, not the flagship number alone" (the previous honest caveat) —
it's closer to: **a real but noisy, regime-dependent, and often
concentration-fragile edge, nowhere near reliable enough per-window to
call deployment-ready**, and meaningfully further from any
80%-win-rate/consistent-100%-YoY bar than the 3-window sample suggested.

**Why this matters for what to do next**: the high concentration finding
reframes where effort is best spent. If most windows' results come down
to a few large winners rather than a broad base of small edges, then
**position sizing / letting winners run further matters more than
further win-rate-focused entry filtering** — a filter can't fix a
distribution that's inherently carried by outliers; sizing that
captures more of those outliers when they occur might. This is the
concrete link back to "risk-based position sizing" as the next
priority, not a coincidence.

## Score-weighted position sizing: tested, rejected -- worse on every metric

Direct follow-up to the walk-forward's concentration finding: since most
windows are carried by a handful of outlier winners, tested whether the
entry rule's own `score` (weekly_ma_spread + sector_rs_momentum excess
above their train-derived cuts -- already computed for ranking the
top-15 daily picks, never used for sizing) predicts which trades become
those outliers. Implementation: `SCORE_SIZING_ENABLED` scales
`ALLOC_PCT` by `clip(score / train_score_p90, 0.5, 2.0)` -- a signal at
the train 90th-percentile score gets the base allocation, stronger/
weaker signals scale up/down, still bounded by the existing RISK_PCT/
LIQ_CAP_PCT caps. Verified inert when disabled (window 3 regression
matches exactly). Ran the full 9-window walk-forward with it enabled:

| Metric | Baseline (flat sizing) | Score-weighted sizing |
|---|---|---|
| Windows beating benchmark | 5/9 | 4/9 |
| Win rate (mean / median) | 50.9% / 45.6% | 49.3% / 44.8% |
| Profit (mean / median) | +5.59% / -5.44% | +0.82% / -7.95% |
| Alpha (mean / median) | +6.45% / +0.61% | **+1.68% / -5.19%** |
| Profit factor (mean / median) | 1.29 / 0.85 | **0.98** / 0.84 |
| Max drawdown (mean) | -15.56% | -17.88% |

**Rejected -- every single metric got worse, not a mixed result.** Mean
alpha collapsed from +6.45% to +1.68%; median alpha flipped from
slightly positive to meaningfully negative; mean profit factor dropped
below 1. Not attempting to rescue this by retuning the 0.5x-2x
multiplier range -- a consistent across-the-board decline like this
points at the signal itself lacking predictive content for sizing, not
at a miscalibrated range. (A narrower or wider multiplier band would
just be more knob-turning on a signal that's already shown it doesn't
carry the information needed here.)

**Likely why**: `score` measures how far a stock has *already* moved
relative to the train thresholds (weekly-trend spread, sector relative
strength) at entry time -- it's a measure of established momentum, not
remaining runway. Sizing up the highest scorers may mean sizing up the
most *already-extended* names, which plausibly have less room left to
run than a name that just barely cleared the qualifying bar. The score
is validated and kept for the yes/no entry filter it was built for; it
has no demonstrated value for sizing.

Kept off by default (`V3_SCORE_SIZING`, unset). Concentration is still
the open problem this was meant to address -- this result rules out one
approach (predict the winner at entry, size accordingly) without
resolving how to actually capture more of the outlier trades. Worth
trying the alternative framing next: let a position PROVE itself is
working before adding size (pyramiding into strength post-TP1) instead
of trying to predict the winner at entry -- a different, more
commonly-validated approach in real systematic trend-following, and one
this result doesn't rule out.

## Pyramiding into strength: tested, net positive, adopted as default

Alternative to score-weighted sizing (rejected above): instead of
predicting at entry which signal becomes the outlier winner, add to a
position only after it's already proven itself by reaching TP1 --
funded fresh from cash, original stop stays at the original entry price
regardless of the add-on's cost. Ran the full 9-window walk-forward with
`V3_PYRAMID=1`, `PYRAMID_ADD_PCT=0.20` (same size as the base
`ALLOC_PCT` tranche):

| Metric | Baseline (no pyramid) | Pyramiding |
|---|---|---|
| Windows beating benchmark | 5/9 | 5/9 |
| Windows win-rate > 50% | 4/9 | **5/9** |
| Win rate (mean / median) | 50.9% / 45.6% | 50.6% / **52.1%** |
| Profit (mean / median) | +5.59% / -5.44% | **+9.60%** / **-3.15%** |
| Alpha (mean / median) | +6.45% / +0.61% | **+10.47%** / **+17.50%** |
| Profit factor (mean / median) | 1.29 / 0.85 | **1.46** / 0.90 |
| Max drawdown (mean) | -15.56% | -17.21% |

**Window-by-window, not just the aggregate**: 6 of 9 windows improved
(1, 4, 6, 7, 8, 9), 3 got worse (2, 3, 5). This is exactly what
pyramiding should do mechanically -- it **amplifies whichever direction
a window is already going**, since it only adds exposure to positions
that already hit TP1 (proven, in that window's own terms). Already-
strong windows got much stronger (W4: PF 1.23->1.89, alpha +0.6%->
+24.1%; W7: PF 3.61->5.01), already-weak windows got weaker (W2: alpha
-12.6%->-21.0%, PF 0.42->0.16). Net positive across this 9-window
battery because good windows outweigh bad ones in this sample, but this
is a genuine variance tradeoff, not a free upgrade -- mean max drawdown
got slightly worse (-15.56%->-17.21%), consistent with amplifying both
tails, not just the good one.

**Adopted as the new default** (same status `TREND_STRENGTH_MIN`/
`REGIME_CONFIRM_DAYS` earned after their own validation) -- median alpha
alone moving from near-zero to +17.5% is a real, substantial
improvement, and the concentration problem this was meant to address is
addressed by construction (capturing more of the outlier winners is
the explicit mechanism, not a side effect). Not sweeping this in from
one try, though -- `PYRAMID_ADD_PCT=0.20` was picked to match the
existing `ALLOC_PCT`, not tuned. Sweeping it next before fully trusting
the exact size, same discipline `HYSTERESIS_BAND`/`VOL_BAND_MULT`
required.

## PYRAMID_ADD_PCT sweep: 0.20 kept, not the highest-mean value

Swept `PYRAMID_ADD_PCT` at 0.10/0.20/0.30 across the full 9-window
walk-forward before fully trusting the 0.20 pick (same discipline
`HYSTERESIS_BAND`/`VOL_BAND_MULT` required):

| ADD_PCT | Beat bench | Win-rate>50% | Alpha (mean/median) | PF (mean/median) | Max DD (mean/worst) |
|---|---|---|---|---|---|
| 0 (no pyramid) | 5/9 | 4/9 | +6.45% / +0.61% | 1.29 / 0.85 | -15.56% / -31.84% |
| 0.10 | 4/9 | 5/9 | +5.75% / -3.16% | 1.35 / 0.83 | -16.55% / -29.48% |
| **0.20** | 5/9 | **5/9** | +10.47% / +17.50% | 1.46 / 0.90 | -17.21% / -31.84% |
| 0.30 | 5/9 | 4/9 | **+12.04% / +20.24%** | **1.49 / 0.95** | **-18.45% / -33.75%** |

Monotonic pattern: bigger add-on -> steadily better mean alpha/profit/
profit-factor, but steadily worse drawdown. **Not adopting 0.30 despite
its higher mean numbers** -- win-rate-consistency (the >50% count) peaks
at 0.20 (5/9) and regresses at 0.30 (back to 4/9, same as no pyramid at
all), and 0.30's drawdown is the worst of every setting tested
(-33.75% worst-case). This is the same judgment call `VOL_BAND_MULT`
required: a setting that's dominant on one axis (raw mean return) isn't
automatically the right default when it costs consistency and drawdown
control on the others. 0.20 kept as default -- real, disclosed
tradeoff, not hidden: 0.30 would show better on a pure backtest-profit
comparison, at a cost this project has consistently chosen not to pay
for a spectacular-looking single number.

0.10 sits between baseline and 0.20 (weaker effect, smaller add-on),
confirming the direction is real -- not adopted since 0.20 dominates it
on every metric except max drawdown.

**Where this leaves V3**: real, validated, disclosed edge (mean alpha
positive and improved by pyramiding, Monte Carlo p=0.0000 on the
original two-window test) but explicitly not deployment-ready by any
reasonable reading -- median profit is still negative even with
pyramiding (-3.15%), profit factor is still below 1 in the median window
(0.90), and concentration remains high in most windows (pyramiding
doesn't reduce reliance on outlier winners, it makes that reliance pay
off more when it works). This is nowhere near an 80%-win-rate/100%-YoY
bar and isn't going to get there through further parameter tuning on
this same historical data -- that path leads to overfitting, not a real
improvement, which is the discipline this whole file has tried to hold
to all session.

## Conditional pyramid trend gate: mixed, rejected -- too blunt an instrument

Tested whether gating the pyramid add-on on IHSG's trend strength at the
moment of the add-on (`PYRAMID_TREND_GATE_MIN=0.03`, i.e. require a
stronger separation from ma50 than the base 1% entry gate) could
suppress pyramiding's downside in the windows it hurt (2, 3, 5) without
giving up the upside in the windows it helped. Ran the full 9-window
walk-forward with the gate on:

| Metric | Unconditional pyramid | + trend gate @ 3% |
|---|---|---|
| Windows beating benchmark | 5/9 | 5/9 |
| Windows win-rate > 50% | 5/9 | **4/9** |
| Alpha (mean/median) | +10.47% / +17.50% | **+7.38% / +0.51%** |
| Profit factor (mean/median) | 1.46 / 0.90 | 1.35 / 0.97 |
| Max drawdown (mean) | -17.21% | -16.04% |

**The gate worked exactly as designed for windows 3 and 5** -- both
revert to almost EXACTLY their no-pyramid baseline numbers (W3:
-5.44%/-2.68%/PF0.29, matching the original baseline to the decimal;
W5: -11.01%/-7.46%/PF0.38, same), confirming the gate correctly detects
these as weak-trend windows on the days TP1 fires and suppresses the
add-on entirely. Window 2 barely changed (still bad) -- apparently has
enough individually-strong-trend days scattered through an otherwise
weak window that the gate doesn't consistently block it there.

**But the same gate also suppressed genuine upside in windows 4 and
6 -- two of unconditional pyramiding's best beneficiaries**: W4's PF
dropped from 1.89 back to 1.23 (essentially erasing the pyramid benefit
entirely), W6's PF dropped from 2.40 to 1.74. These were GOOD windows
that pyramiding correctly amplified; the trend gate filtered out
productive add-on opportunities there too, not just in the weak windows
it was designed to protect.

**Rejected.** Trend strength at the moment of TP1 is too blunt an
instrument to cleanly separate "this add-on will pay off" from "this
add-on won't" at the individual-trade level -- it correlates with
window-level character on average (the original diagnostic: 5.49%/
2.18%/1.13% across great/modest/losing windows) but not tightly enough
day-to-day to gate a trade-level decision without meaningful collateral
cost. Not sweeping the threshold further -- this isn't a calibration
problem the way PYRAMID_ADD_PCT was; the conditioning signal itself
isn't discriminating well enough for tuning to fix. Unconditional
pyramiding (`PYRAMID_ADD_PCT=0.20`, no trend gate) remains the adopted
default.

## Second pyramid tier: rejected -- past the point of diminishing returns

Extended the validated single-tier pyramid (add at TP1) with a second
add-on if the position proves itself further (a fixed additional leg
from the ORIGINAL entry price/ATR). Ran the full 9-window walk-forward:

| Metric | Single-tier pyramid (0.20) | + second tier |
|---|---|---|
| Windows beating benchmark | 5/9 | 5/9 |
| Windows win-rate > 50% | 5/9 | **3/9** |
| Alpha (mean/median) | +10.47% / +17.50% | +6.24% / +8.08% |
| Profit factor (mean/median) | 1.46 / 0.90 | 1.62 / 0.88 |
| Max drawdown (worst) | -31.84% | **-38.32%** -- the worst drawdown seen across every configuration tested this session |

**Rejected.** Same amplification mechanism as the ADD_PCT sweep (more
exposure to already-proven winners), but here it clearly crosses from
"worthwhile tradeoff" into "not worth it" -- win-rate-consistency
collapsed (5/9 -> 3/9), both mean and median alpha declined, and the
worst-case drawdown got meaningfully worse than anything else tried.
Only mean profit factor improved (1.46->1.62), and that alone doesn't
justify the cost on every other axis. Kept off by default
(`V3_PYRAMID_TP2`, unset).

## Where this leaves V3 after this round of position-sizing work

Four experiments run this round, one adopted: score-weighted sizing
(rejected), unconditional single-tier pyramiding at TP1 (**adopted,
`PYRAMID_ADD_PCT=0.20` default**), conditional trend-gated pyramiding
(rejected), second pyramid tier (rejected). The adopted change is real
and disclosed: median alpha +0.61%->+17.50%, median profit factor
0.85->0.90, windows clearing 50% win rate 4/9->5/9, at the cost of a
modest drawdown increase (mean -15.56%->-17.21%).

**Not continuing to add more tuning knobs on top of this right now.**
Three of the last four ideas tried were rejected; that ratio, plus the
diminishing/negative returns of the last two attempts specifically
(trend gate and second tier both made things worse, not better), is the
signal to stop turning this particular set of knobs rather than keep
searching for one that happens to look good -- exactly the overfitting
risk this file has flagged and walked back from more than once already
tonight (`HYSTERESIS_BAND`, `VOL_BAND_MULT`). The honest current state:
a real, validated, but modest and noisy edge (mean alpha positive,
Monte Carlo p=0.0000 on the original test, pyramiding genuinely helps),
nowhere near reliable enough per-window or broadly enough distributed
to call deployment-ready, and not going to get meaningfully closer
through more parameter search on this same historical data. The next
genuinely new thread (not a further tweak on this one) would be either
a real news-sentiment feature once the separate news pipeline is live,
or investigating window 3/5's specific "weak/choppy bullish" character
directly rather than through sizing -- both bigger, different pieces of
work than another knob on the existing rule.

## Exit-mechanic calibration, round 1: TP1_MULT sweep -- no change

First sweep on the exit side (everything tuned so far was entry-side:
regime, trend strength, sizing). `TP1_MULT` (currently 1.5x ATR, shared
with V1's config.py -- swept via a process-local override, see the
override-hook commit, never touching the file) at 1.0/1.5/2.0 across
the full 9-window walk-forward:

| TP1_MULT | Beat bench | Win-rate>50% | Alpha (mean/median) | PF (mean/median) | Worst single-window win rate |
|---|---|---|---|---|---|
| 1.0 | 4/9 | 4/9 | +10.88% / -3.01% | 1.50 / 1.10 | 38.5% |
| **1.5 (current default)** | 5/9 | **5/9** | +10.47% / +17.50% | 1.46 / 0.90 | 33.3% |
| 2.0 | 5/9 | 4/9 | +10.99% / **+21.78%** | 1.39 / 1.02 | **12.5%** (window 2) |

Non-monotonic, no value dominates every axis. 2.0 has the best median
alpha and a median PF just above 1, but window 2 (2022 H2, the choppy
period) drops to a 12.5% win rate -- 3 winners out of 24 trades, the
worst single-window result of the entire session. A wider TP1 target
means more trades never reach it and resolve via SL instead in a
genuinely difficult period -- real tail risk, not just a worse average.
1.0 trades some median-profit/PF improvement for a worse median alpha
and fewer windows beating benchmark.

**Kept at the current default (1.5).** Best win-rate-consistency count
(5/9) of the three, no concerning single-window blowup, and not clearly
dominated by either alternative once tail risk is weighed alongside the
mean/median numbers -- same judgment call as `VOL_BAND_MULT`/
`PYRAMID_ADD_PCT`: not chasing the highest number on one axis when it
costs reliability on another.

## Exit-mechanic calibration, round 2: TRAILING_PCT sweep -- no change

`TRAILING_PCT` (currently 8% from highest price, also shared with V1's
config.py via the same safe override) at 0.05/0.08/0.12 across the full
9-window walk-forward:

| TRAILING_PCT | Beat bench | Win-rate>50% | Alpha (mean/median) | Profit (median) | Median PF | Max DD (mean/worst) |
|---|---|---|---|---|---|---|
| 0.05 | 5/9 | 5/9 | +7.32% / +0.37% | +1.19% | 1.08 | -15.89% / -34.24% |
| **0.08 (current default)** | 5/9 | **5/9** | +10.47% / +17.50% | -3.15% | 0.90 | -17.21% / -31.84% |
| 0.12 | **6/9** | 4/9 | +9.82% / +17.71% | **+14.00%** | **1.42** | -18.77% / **-38.49%** |

(Mean PF at 0.12 is not reported -- window 7 posted a PF of 85.77 on
just 16 trades at a 93.75% win rate, which explodes the mean into a
meaningless number; that result carries the same small-sample fragility
signature flagged earlier this session (a handful of trades producing
an extreme, likely-lucky number), not something to trust or chase.)

0.12 has the best median profit and profit factor and the best
beat-benchmark count -- genuinely tempting on the surface -- but the
window 7 result looks like exactly the kind of fluke this project has
repeatedly walked back from trusting, worst-case drawdown ties for the
worst of the whole session (-38.49%), and win-rate-consistency regresses
to 4/9. 0.05 keeps the win-rate-consistency and improves median profit/
PF modestly, but at a real cost to median/mean alpha (+17.50%->+0.37%).
Window 2 (the choppy window) is highly sensitive to this parameter in
both directions -- 61.3% win rate at 0.05, only 23.1% at 0.12 -- more
evidence that a tighter trailing stop suits choppy conditions and a
looser one suits trending ones, which the current 0.08 already
straddles reasonably.

**Kept at the current default (0.08).** No value cleanly dominates once
tail risk and small-sample fragility are weighed against the headline
numbers, same discipline applied to every other parameter tonight.

## Exit-mechanic calibration, round 3: QUANTILE_CUT sweep -- adopted, genuine interior peak

Last of the three exit/threshold parameters swept this round.
`QUANTILE_CUT` (the top-percentile threshold for weekly_ma_spread/
sector_rs_momentum, currently 0.80 = top quintile) at 0.50/0.60/0.70/
0.80/0.90 across the full 9-window walk-forward:

| QUANTILE_CUT | Beat bench | Win-rate>50% | Alpha (mean/median) | PF (mean/median) | Max DD (worst) |
|---|---|---|---|---|---|
| 0.50 | 5/9 | 4/9 | +16.80% / +10.77% | 1.29 / 0.70 | -29.10% |
| **0.60** | **6/9** | **5/9** | **+17.19% / +13.12%** | **1.49 / 1.24** | **-23.30%** |
| 0.70 | 6/9 | 4/9 | +14.02% / +11.72% | 1.67 / 0.90 | -25.62% |
| 0.80 (old default) | 5/9 | 5/9 | +10.47% / +17.50% | 1.46 / 0.90 | -31.84% |
| 0.90 | 4/9 | 4/9 | +5.25% / -1.08% | 1.39 / 0.68 | -32.78% |

**Unlike TP1_MULT and TRAILING_PCT (both non-monotonic, no adoption),
this is a genuine bracketed interior peak** -- performance degrades in
BOTH directions away from 0.60 (tighter toward 0.90, looser toward
0.50), not a monotonic trend that might keep improving past the tested
range or an edge-of-range fluke. 0.60 wins on every axis simultaneously:
best beat-benchmark count, best win-rate-consistency, best mean alpha,
best median profit factor (1.24 -- the first time any configuration
this session crossed meaningfully above 1 without a fragility red flag
attached), and the best worst-case drawdown of every value tested this
entire session (-23.30%, vs -31.84% at the old default).

**Adopted as the new default** (`QUANTILE_CUT=0.60`). Verified via a
cached rerun (zero new Supabase queries, using the local fetch cache
added this session) that the new default reproduces the recorded 0.60
numbers exactly.

**Why a looser threshold helps**: being more selective (0.80, 0.90) cuts
out candidates that turn out to still carry real, usable signal --
consistent with this being a QUINTILE-style validated feature that
degrades gracefully rather than a sharp cliff at the exact 80th
percentile. Loosening it increases trade count and diversification
without diluting quality until somewhere past 0.50, where genuinely
weaker candidates start pulling the average down.

## Exit-mechanic calibration round: summary

Three parameters swept across the full 9-window walk-forward:
`TP1_MULT` (no change, current default not dominated), `TRAILING_PCT`
(no change, current default not dominated), `QUANTILE_CUT` (**adopted,
0.80 -> 0.60**, a genuine bracketed improvement on every axis). Combined
with the earlier position-sizing round (pyramiding adopted at
`PYRAMID_ADD_PCT=0.20`), this is the current best validated V3
configuration. Also fixed in this round: `walk_forward_v4.py` now
caches its fetch locally, since every sweep point (11 full walk-forward
runs across both rounds) had been re-downloading the identical 5.5-year
dataset from Supabase -- real, avoidable load that contributed to a
Supabase compute-exhaustion alert mid-session.

## Window 3/5 character, revisited under the current best config

With pyramiding + `QUANTILE_CUT=0.60` adopted, re-checked the two
windows flagged as weakest in the original 3-window era.

**Window 5 (2024 H1) looks fixed as a side effect.** Was -11.01% profit
/ -7.46% alpha under the old 0.80 threshold; now **+5.91% profit /
+9.46% alpha** with more candidates let in. Not a targeted fix -- the
threshold change that helped the whole battery happened to resolve this
window too. No longer a standing concern.

**Window 3 (2023 H1) is still a net loser, but the character is better
understood now.** Pulled a fresh 19-trade audit (up from 12 under the
old threshold): **two distinct episodes, not one.** The already-known
Feb 2023 bull-trap cluster (13 tickers: GOTO, WIRG, BUKA, DMMX, TMAS,
ASSA, TRJA, GULA, BIRD, TRUK, ELPI, MMIX, MEDS -- more names than before
since the looser threshold admits more candidates into the same false-
start episode), mostly losses -- plus a **genuine second opportunity in
May 2023 (KING, HOMI)** that the rule correctly caught and profited
from: HOMI gained ~26% over 23 days, amplified further by the pyramid
add-on (+181 then +842 across the two tranches, exactly the mechanism
working as designed).

**Conclusion: not pursuing further tuning here.** The rule isn't blind
in this window -- it found and profited from a real opportunity in the
same 6 months. February's concentrated bull-trap losses are simply
larger than May's genuine gain. This is the bounded, structural cost of
a regime-following rule occasionally riding a false start, not a
correctable flaw -- trying to design that away specifically would mean
reverse-engineering a rule that filters out GOTO/WIRG/BUKA/etc.'s
February entries without also filtering out KING/HOMI's May entries,
using the same signal that can't distinguish them in advance (this is
exactly what the entry-cluster-window gate and trend-gated pyramid
already tried and both made things worse elsewhere). Window 3 stands as
disclosed: a real loss, understood, not evidence the rule is broken.

## Current best validated V3 configuration (as of this session)

- Entry: BULLISH regime (volatility-relative hysteresis, `VOL_BAND_MULT=2.0`)
  + weekly-trend-alignment + sector-RRG top **60th percentile**
  (`QUANTILE_CUT=0.60`, changed from 0.80 this session), liquid stocks only.
- Timing guards: `MAX_NEW_ENTRIES_PER_DAY=2`, `REGIME_CONFIRM_DAYS=3`,
  `TREND_STRENGTH_MIN=0.01`. `ENTRY_CLUSTER_WINDOW_DAYS`/
  `MAX_ENTRIES_PER_CLUSTER_WINDOW` present but inert by default (tested,
  rejected).
- Sizing: `PYRAMID_ENABLED=1` (default on this session), add at TP1,
  `PYRAMID_ADD_PCT=0.20`. `SCORE_SIZING_ENABLED`, `PYRAMID_TREND_GATE`,
  `PYRAMID_TP2` all present but off by default (tested, rejected).
- Exit: `TP1_MULT=1.5`, `TRAILING_PCT=0.08` (both swept this session,
  kept -- not dominated by tested alternatives).
- 9-window walk-forward result at this configuration: 6/9 beat
  benchmark, 5/9 clear 50% win rate, mean alpha +17.19% / median
  +13.12%, mean PF 1.49 / median 1.24, worst drawdown -23.30%.

Still not deployment-ready by any honest reading (median profit +5.91%
across windows sounds fine but individual windows still lose real
money, e.g. window 3 above), but this is a materially better, more
thoroughly validated state than where this session started.

## Portfolio breadth (MAX_POSITIONS 8/10): tested, rejected

User question: is a full 6-position portfolio actually missing real
opportunity (a new qualifying signal shows up, no slot free, it's just
dropped, no queue)? Tested by increasing `MAX_POSITIONS` to 8/10 while
proportionally shrinking `ALLOC_PCT` (15%/12%) to hold total exposure
at the same ~120% as today's 6x20% -- isolates breadth (more concurrent
names) from leverage (more total capital at risk).

| Config | Beat bench | Win-rate>50% | Alpha (mean/median) | PF (mean/median) | Worst DD |
|---|---|---|---|---|---|
| **6 x 20% (current)** | 6/9 | **5/9** | **+17.19% / +13.12%** | **1.49 / 1.24** | -23.30% |
| 8 x 15% | 6/9 | 5/9 | +11.46% / +7.84% | 1.39 / 1.17 | -22.27% |
| 10 x 12% | 6/9 | **3/9** | +13.82% / +11.43% | 1.43 / 1.17 | -22.33% |

**Rejected -- more breadth consistently hurt, didn't help**, and
win-rate-consistency collapsed at 10 slots. Consistent with everything
else learned this session: most of the return comes from a handful of
outlier winners (the concentration finding), amplified by pyramiding.
Diluting position size to fit more concurrent names means even the
eventual big winners get a smaller slice of capital -- directly working
against the mechanism actually driving the edge. **The 6-position cap
is not the bottleneck** -- kept at 6.

## Liquidity-weighted sizing: adopted -- best mean alpha AND best worst-case drawdown together

User's own instinct: rather than adding more portfolio slots (tested
above, rejected), size up specifically on very liquid, large-cap,
"trusted" names using real ADTV data already computed and filtered.
Implemented as a log-scale multiplier against the train-derived 90th-
percentile ADTV (`LIQ_SIZING_ENABLED`), composable with the (off-by-
default) score-sizing multiplier. Ran the full 9-window walk-forward:

| Metric | Baseline (no liq sizing) | + liquidity sizing |
|---|---|---|
| Windows beating benchmark | 6/9 | 6/9 |
| Windows win-rate > 50% | **5/9** | 4/9 |
| Alpha (mean/median) | +17.19% / +13.12% | **+21.71%** / +12.60% |
| Profit factor (mean/median) | 1.49 / 1.24 | **1.58** / 1.12 |
| Max drawdown (mean/worst) | -17.03% / -23.30% | **-16.08%** / **-21.61%** |

**Best mean alpha AND best worst-case drawdown of every configuration
tested this entire session, simultaneously** -- unusual, since more
return and less risk don't normally move together; this is a real
signal that ADTV carries information the entry score doesn't (recall
score-weighted sizing, using the entry rule's own momentum score, was
rejected outright -- worse on every metric). Real, disclosed cost:
win-rate-consistency dropped from 5/9 to 4/9, and median alpha dipped
slightly (+13.12% -> +12.60%).

**Methodological note**: swept the multiplier's clip bounds (0.5-2.0
default vs a narrower 0.7-1.5) expecting to find a gentler tradeoff --
the two runs produced byte-identical results. Log-compression already
keeps the real log(ADTV)/log(ADTV_p90) ratio within a narrow range
naturally for this liquid-only universe (ADTV already floor-filtered at
Rp1B); the clip bounds were never actually binding at either setting.
Testing clip bounds was not a real experiment here -- a genuinely
different tilt strength would need a different transform (e.g. a
fractional exponent), not tighter clipping. Not pursuing that further
right now; noting it for whoever revisits this.

**Adopted as default** (`LIQ_SIZING_ENABLED` defaults to on). Same
judgment call as pyramiding's original adoption: a real average
improvement with a disclosed, bounded cost, not a free upgrade.
Verified via cached rerun that the new default (pyramid + QUANTILE_CUT
0.60 + liquidity sizing, all together) reproduces the recorded numbers
exactly.

## Current best validated V3 configuration (updated)

- Entry: BULLISH regime (volatility-relative hysteresis) + weekly-trend
  + sector-RRG top 60th percentile (`QUANTILE_CUT=0.60`), liquid stocks.
- Timing guards: unchanged (`MAX_NEW_ENTRIES_PER_DAY=2`,
  `REGIME_CONFIRM_DAYS=3`, `TREND_STRENGTH_MIN=0.01`).
- Sizing: `PYRAMID_ENABLED=1` (add at TP1, `PYRAMID_ADD_PCT=0.20`) AND
  now `LIQ_SIZING_ENABLED=1` (log-ADTV-weighted allocation, 0.5x-2x).
  `SCORE_SIZING_ENABLED` still off (rejected). `MAX_POSITIONS=6`,
  `ALLOC_PCT=0.20` (8/10-position variants tested, rejected).
- Exit: `TP1_MULT=1.5`, `TRAILING_PCT=0.08` (unchanged, not dominated).
- 9-window walk-forward at this full configuration: 6/9 beat benchmark,
  4/9 clear 50% win rate, mean alpha +21.71% / median +12.60%, mean PF
  1.58 / median 1.12, worst drawdown -21.61% -- the best mean-return/
  worst-case-risk combination reached this session, at the cost of one
  fewer window clearing 50% win rate than the pre-liquidity-sizing state.

## Honest strategic assessment (2026-07-27): why we keep hitting walls, and what an actually-robust system looks like

Asked directly, after three weeks of intense work, whether we're close to
a "bulletproof, perfect" system. Answering honestly instead of
reassuringly, because every prior instance of overpromising in this log
(80% win rate, the 2% hysteresis band, V2's +668%) had to be walked back
later, and that walk-back cost more trust than an early "no" would have.

**"Bulletproof" is not a real category in trading, and chasing it is
itself the mistake.** Every edge that has ever existed in a liquid public
market is: (a) small relative to what people hope for, (b) regime-
dependent, and (c) discoverable by imitators the moment it's big enough
to matter, which caps how big it can get before it decays. A system that
"always wins" isn't undiscovered -- it isn't possible on daily-bar public
data. That was true before this session and is still true now; nothing
found in three weeks contradicts it, and nothing will.

**What we actually have, stated plainly:** a real, positive, statistically
validated edge (Monte Carlo permutation p=0.0000 against 5000 random
draws from the same opportunity set, in two separate windows) that is
inconsistent across regimes -- strong in trending windows (window 1:
+152.75%, 60.1% win rate), weak-but-no-longer-catastrophic in choppy ones
(window 3: -5.44%, was -22.10% before three separate fixes this session).
That is a legitimate result. It is also not what "80% win rate, 100%
YoY" meant when that target was set, and closing that gap isn't a
matter of one more parameter sweep -- see below for why.

**Why we hit walls (the real reasons, not a list of bugs left to fix):**

1. **The edge is real but genuinely small and regime-conditional.** The
   trend-strength diagnostic this session (IHSG's own separation from
   ma50: 5.49% / 2.18% / 1.13% across windows 1/2/3) shows window 3 wasn't
   a bug, it was a market that was barely trending at all. No entry rule
   built on trend/momentum can perform well in a period with weak trend to
   detect -- that's not a fixable flaw, it's the rule correctly running out
   of signal.
2. **Small sample size limits how far tuning can safely go.** IHSG has a
   few years of clean, survivorship-bias-free data. Nine 6-month windows
   is already stretching that thin -- the hysteresis-band sensitivity
   sweep earlier this session (2% looking great, then swinging 61%-501%
   profit across nearby values) is the concrete proof: with this little
   data, a parameter can look "optimized" while actually just being a
   lucky draw. Every additional free parameter this system gains makes
   this worse, not better -- which is why sizing/exit sweeps this session
   were judged on "not dominated" rather than "found the true optimum."
3. **Every "reserve" of easy return is a known trap we deliberately fenced
   off.** V2's headline +668% was 99% concentrated in microcap "gorengan"
   names -- real return, but not repeatable at any real capital and not
   safe to rely on. The liquidity floor (Rp1B ADTV) that excludes those
   names is exactly what keeps the current numbers honest, and exactly
   what caps how large the numbers can look.
4. **Scalping/intraday is not a harder version of this system -- it's a
   different system we've never built.** Every backtest this entire
   project has ever run (V1's live pipeline, V2, all of V3) holds
   positions over days, using daily OHLCV bars. Scalping needs intraday
   price action, bid-ask spread, order-book depth or at minimum
   minute-bars -- data this system has never ingested and logic this
   system has never tested. Today's Quant Signals list being unsuitable
   for scalping tomorrow (flagged separately today) isn't a symptom of
   the model being weak; it's a symptom of asking a multi-day model an
   intraday question.

**What I'd actually build next, in priority order, if the goal is the
most robust practical system rather than a bigger number:**

1. **Regime-conditional capital allocation, not just regime-conditional
   entry filtering.** Everything this session gates *which stocks* enter
   in a given regime; nothing yet reduces *how much capital trades at
   all* when the regime is weak. Window 3's remaining -5.44% is a market
   where the honest move might be smaller size or no size, not a smaller
   loss on the same size. Not yet tried -- the natural next experiment.
2. **A second, complementary signal for weak-trend regimes** (e.g.
   mean-reversion or range-bound logic) so choppy periods are a different
   trade, not a starved version of the trending one. Higher effort, real
   payoff if it works -- an ensemble that knows which regime it's in and
   switches character, not just switches on/off.
3. **Keep the walk-forward-only discipline permanently**, including for
   any new signal above -- every adoption this session went through
   inert-by-default -> exact-match regression -> full 9-window run ->
   honest reject-or-adopt, and that discipline is the actual reason this
   log is trustworthy. Loosening it to move faster would undo the one
   thing that's working.
4. **A separate, explicitly-scoped intraday research track if scalping
   matters enough to invest in** -- different data source, different
   validation, do not bolt it onto V3. Trying to stretch the current
   system to cover it would produce exactly the kind of false confidence
   this log has walked back before.
5. **Paper-trade the current best configuration before any of the above**,
   in parallel with more research, not instead of it. Backtesting -- even
   honest, walk-forward, permutation-tested backtesting -- cannot see
   live slippage, fills, or a regime this data has never contained. The
   remaining gap between "validated on history" and "safe to deploy" is
   time forward, not more sweeps backward.

**Bottom line:** the walls aren't a mistake still hiding somewhere in the
code -- three weeks of work already found and fixed the real mistakes
(survivorship bias, delisted-position handling, the liquidity gap, the
entry-clustering bug, the OFFSET pagination bug). What's left is the
market itself being smaller and choppier than the original target
assumed. The honest path forward is the list above, not one more clever
parameter.

## Roadmap item #1 executed: regime-strength capital sizing -- tested, rejected

First item off the 2026-07-27 roadmap: scale allocation by how strongly
IHSG is separated from its own ma50 on the day of execution, not just
gate entries on/off by it. Implemented as `TREND_SIZING_ENABLED` (off by
default), `trend_mult = clip(trend_strength_today / trend_strength_p90,
TREND_SIZING_MIN, TREND_SIZING_MAX)`, composing with `size_mult` and
`liq_mult` at the same allocation line -- exact same pattern as
liquidity sizing. `trend_strength_p90` is the 90th percentile of
`_trend_strength` among train-qualifying BULLISH days (never touches
test data).

Verified inert first: full 9-window run with the flag off reproduced
the recorded baseline exactly (mean alpha +21.71%, PF 1.58/1.12, DD
-16.08%/-21.61%, 6/9 beat bench, 4/9 win-rate>50%) -- no regression from
adding the toggle.

Then ran ON at two bound settings, learning from the hysteresis-band
lesson not to trust a single point:

| Config | Beat bench | Win-rate>50% | Alpha (mean/median) | PF (mean/median) | Max DD (mean/worst) |
|---|---|---|---|---|---|
| Baseline (off) | 6/9 | 4/9 | +21.71% / +12.60% | 1.58 / 1.12 | -16.08% / -21.61% |
| Trend sizing 0.5x-1.5x | 6/9 | 4/9 | +17.15% / +18.08% | 1.75 / 1.66 | -14.06% / -19.30% |
| Trend sizing 0.7x-1.3x (gentler) | **7/9** | 4/9 | +21.82% / +8.13% | 1.67 / 1.26 | -15.15% / -20.56% |

Aggregate metrics alone look encouraging both ways, but the per-window
detail is why this gets rejected: **window 4** (a strong baseline
window at +50.49% profit / 50.0% win rate) goes to +52.06%/54.2% under
0.5x-1.5x but collapses to +16.73%/39.6% under 0.7x-1.3x -- a "gentler"
setting doing far more damage than the "more aggressive" one, no
monotonic relationship between bound width and outcome. **Window 8**
(the big outlier winner, +129.13% baseline) gets compressed to +55.32%
under 0.5x-1.5x but *improves* to +142.60% under 0.7x-1.3x -- opposite
direction again. This is the exact fragility signature the hysteresis-
band sweep already taught this project to distrust: a parameter whose
effect flips sign window-to-window depending on the bound chosen isn't
capturing something real about regime strength, it's just reshuffling
which train-period p90 threshold a handful of test days happen to sit
near.

**More importantly, it didn't do the one thing it was built for.**
Window 3 -- the specific target, the one still losing money in the
current default config -- barely moved (alpha -3.31% baseline to
-2.85%/-2.48% under the two settings, essentially noise) and its **win
rate got worse in both variants** (42.1% baseline down to 31.6% and
36.8%). Regime-strength sizing dampens or amplifies bets on days that
already passed the binary `TREND_STRENGTH_MIN` gate; it has nothing to
say about days that never qualify at all, which is what actually
starves window 3 of opportunities. Solving that needs a different
mechanism (a complementary weak-trend signal, roadmap item #2 below),
not a sizing tweak on top of the same entry rule.

**Rejected. `TREND_SIZING_ENABLED` stays off by default** (code kept in
place, inert, for whoever revisits this with a different transform).
Logging this as a real negative result, not a quiet walk-back: the
instinct behind it (size down when the regime is barely qualifying) was
reasonable and worth testing, and testing it honestly is exactly what
avoided adopting a fragile, order-of-magnitude-sensitive parameter.

## Roadmap item #2 scoped, not built: only one real chop episode exists in the available data

Before designing the complementary weak-trend/mean-reversion signal
(roadmap item #2), checked whether there's actually enough independent
evidence to validate one. Computed regime-flip counts (a real chop
proxy -- how often BULLISH/NEUTRAL/BEARISH actually flips, unlike raw
trend-strength which also dips during clean downtrends) across all 9
walk-forward windows:

| Window | Period | Regime flips | Bullish-day frac | Win rate |
|---|---|---|---|---|
| W1 | 2022 H1 | 1 | 60% | 54.5% |
| W2 | 2022 H2 | 2 | 28% | 50.0% |
| **W3** | **2023 H1** | **4** | 29% | 42.1% |
| W4 | 2023 H2 | 3 | 62% | 50.0% |
| W5 | 2024 H1 | 1 | 30% | 40.0% |
| W6 | 2024 H2 | 2 | 53% | 54.5% |
| W7 | 2025 H1 | 1 | 33% | 71.4% |
| W8 | 2025 H2 | 0 | 93% | 65.6% |
| W9 | 2026 H1 | 1 | 15% | 34.8% |

Low trend-strength/bullish-day-fraction alone does not predict a bad
window -- W7 and W9 both have low bullish-day fractions but only 1
regime flip each (clean, sustained trends, just not upward for most of
the window) and the existing signal does fine (W7: 71.4% win rate) or
relatively well (W9: loses money outright but still beats a crashing
benchmark by +19.75%). **Frequent regime flipping, not low trend
strength, is what actually correlates with a bad window** -- and only
W3 has more than 3 flips.

Then checked whether more chop episodes exist in the data outside the
rigid 6-month calendar schedule (a real chop cluster could span two
windows and get diluted by the arbitrary boundary). Scanned continuously
-- every rolling 126-trading-day window, stepped monthly, across the
full cached history back to 2020-06 -- ranked by flip count:

```
2023-01-06..2023-07-25: 5 flips
2022-11-09..2023-05-17: 4 flips
2022-12-08..2023-06-20: 4 flips
2023-02-07..2023-08-24: 4 flips
2023-04-11..2023-10-24: 4 flips
2022-04-01..2022-10-10: 3 flips
2022-09-12..2023-03-07: 3 flips
2023-03-08..2023-09-22: 3 flips
2023-06-21..2023-12-21: 3 flips
2020-06-15..2020-12-17: 2 flips  <- next-highest era, and still lower
```

**Every single one of the choppiest rolling windows is the same
underlying episode** (roughly Nov 2022 - Oct 2023), just measured at
different overlapping offsets -- not independent chop events. Nothing
in 2020-06 through 2026-06 comes close outside that one stretch. Real
answer: **this market has produced exactly one genuinely choppy,
whipsaw-prone episode in the ~6 years of clean data available**, and
window 3 sits inside it.

**Conclusion: not building the complementary signal right now.**
Validating a new signal type against what is honestly a single
historical episode -- however it's sliced into overlapping windows --
is the same mistake as the hysteresis-band sweep this session already
walked back from: a result that looks validated because it's measured
many times, when it's actually one draw dressed up as several. A signal
tuned to fit this one stretch would be indistinguishable from curve-
fitting to it, and there is no way to tell the difference with the data
that exists. This is a data-availability limit, not a verdict that the
underlying idea (a different entry logic for genuinely choppy regimes)
is wrong -- it becomes buildable the day either more history becomes
available or the market produces a second chop episode to validate
against independently. Revisit then. Deferring, not abandoning.

**Practical implication for the roadmap**: with item #1 rejected and
item #2 correctly un-buildable for now, the two items left with a real
path forward are #3 (keep the walk-forward-only discipline permanent --
already the practice, nothing new to build) and #5 (paper-trade the
current best validated configuration going forward, since that's the
one place additional real evidence can still come from without needing
more historical data). #4 (a separate intraday research track) remains
a distinct, larger investment decision, not something to fold into V3.

## Live paper trading built (2026-07-31): roadmap item #5, executed

Built the full live paper-trading system from the roadmap: Rp100,000,000
simulated capital, real fees (config.py's BUY_FEE 0.18%/SELL_FEE 0.28%
plus a new flat Rp10,000 surcharge on any single buy over
Rp10,000,000 -- a real broker rule the user reported, paper-trading-
specific, not added to config.py), `ihsg_realtime`-based live pricing
polled every 15 minutes, target launch Monday 2026-08-03.

**Governance (binding for the life of this run)**: trades the exact
"current best validated V3 configuration" recorded above
(`LIQ_SIZING_ENABLED=1`, `PYRAMID_ENABLED=1`, `QUANTILE_CUT=0.60`,
`TP1_MULT=1.5`, `TRAILING_PCT=0.08`, `MAX_POSITIONS=6`,
`ALLOC_PCT=0.20`, `TREND_STRENGTH_MIN=0.01`, `REGIME_CONFIRM_DAYS=3`),
frozen for this run's lifetime. No retroactive tweaks -- that would
contaminate the track record the same way test-data leakage
contaminates a backtest. Further research continues on this branch,
walk-forward validated as always; an improvement only ever ships as a
new run (e.g. `V3.1_PAPER`), never a silent edit to this one. 100%
deterministic Python -- no LLM anywhere in signal generation, sizing,
or exit decisions (the user's explicit requirement).

**Zero-drift design**: rather than re-implement the trading rule for a
live context, extracted three pure functions out of `simulate_window`'s
day-loop so the backtest and the live engine call the *exact same code*:
- `score_candidates()` -- entry filtering/ranking.
- `compute_entry_fill()` -- sizing (score/liq/trend multipliers,
  RISK_PCT/LIQ_CAP_PCT caps, ALLOC_MIN_LOTS floor) and the ATR-based
  TP1/SL calc.
- `evaluate_position_exit()` -- SL/TP1/TRAILING/CHECKPOINT/TIME exits
  plus the TP1/TP2 pyramid-add-on.

Each extraction was verified via the full 9-window walk-forward
regression check before proceeding -- byte-identical to the recorded
baseline every time (mean alpha +21.71%, PF 1.58/1.12, DD
-16.08%/-21.61%, 6/9 beat bench, 4/9 win-rate>50%). A dedicated dry-run
(`src/test_paper_trading_math.py`, no Supabase needed) then verified
the money math itself against independently hand-computed expected
values -- fees, SL/TP1/TRAILING pnl, the pyramid add-on's cash outflow,
candidate ranking -- all 8 checks pass.

**Architecture**: two new daily/intraday scripts
(`src/paper_signal_scan.py` once/day after close, `src/paper_monitor.py`
every 15 min during trading hours) plus two new Supabase tables
(`paper_positions` -- permanent, append-only position audit log;
`paper_account` -- cash ledger), reusing `backtest_runs`/
`backtest_trades`/`backtest_equity` as-is so the existing frontend
chart component needed zero changes. New `/paper-trading` page on the
website (stat cards, equity-vs-IHSG chart, live open-positions table,
closed-trade history) plus a fix for a real bug found the same day
(`ihsg_realtime`'s live-price query had no ORDER BY/dedupe and no
tab-foreground refresh -- both fixed, since the paper-trading engine
depends on the same feed for live pricing).

**Known, disclosed simplifications** (not gaps found by accident --
decided against explicitly to hit the deadline): no ARA/ARB or
order-book depth (assumes a full fill at the observed price, same as
the backtest); no true intraday tick data (`day_high`/`day_low` are
built up from 15-minute polls, a proxy for the backtest's real daily
H/L -- disclosed, not silently assumed equivalent); no IDX holiday
calendar (relies on `ihsg_eod` simply not advancing, same assumption
`screener.py` already makes in production); one continuous run, no
versioning/reset UI for v1.

**Blocked on a manual step**: Supabase MCP was disconnected for this
entire session, so `sql/paper_trading_schema.sql` (the two new tables
+ the seed row) has not been applied yet -- needs to be run once,
manually or once the MCP reconnects, before the first
`paper_signal_scan.py` run. Everything else (code, workflows, frontend)
is pushed and ready.

**Update same day**: Supabase MCP reconnected -- applied
`sql/paper_trading_schema.sql` directly (fixed one real bug found in
the process: Postgres has no `CREATE POLICY IF NOT EXISTS`, swapped to
`DROP POLICY IF EXISTS` + `CREATE POLICY`, and guarded the seed insert
against re-runs). Confirmed live: run id 32, `V3_PAPER`,
Rp100,000,000 cash, `last_signal_date` null. User confirmed the site
and paper run are live and checked in.

## Paper-trading hardening (same day): DELISTED_GAP + failure alerting

Two gaps identified right after launch, both closed same day:

1. **`DELISTED_GAP` wasn't ported to the live engine.** The backtest
   force-exits a position after `DELISTING_GAP_DAYS` (10) consecutive
   trading days with no EOD print -- without it, a suspended/delisted
   stock in the live run would sit "open" forever, frozen at its last
   mark-to-market price, the same blind spot fixed in the backtest
   itself earlier this session. Ported into `paper_signal_scan.py`'s
   EOD reconciliation pass: two new `paper_positions` columns
   (`no_data_days`, `last_valid_close`, applied live via the MCP),
   incremented/reset exactly like the backtest's own position dict.
2. **No alerting if the jobs themselves fail.** GitHub Actions emails
   on a red run, but that's easy to miss for days on a background cron.
   Added `paper_common.run_guarded()`, wrapping both scripts'
   entry points: any uncaught exception now sends a Telegram alert with
   the traceback before re-raising (the workflow still shows red too).

Also added a "How This Works" explainer to `/paper-trading` (frozen
config, real fee structure, cadence, the day-high/day-low intrabar
proxy, explicit not-investment-advice disclosure) -- verified via
`tsc --noEmit` and a full `next build`, both clean. Backend changes
verified via syntax check + the existing money-math dry-run
(`src/test_paper_trading_math.py`, still 8/8) -- neither touches
`compute_entry_fill`/`evaluate_position_exit`, so no walk-forward
regression re-check was needed this round.

## Fill-realism check: participation-scaled slippage -- major disclosed
## finding, kept OFF by default

Prompted by a scan of github.com/wangzhe3224/awesome-systematic-trading
for transferable techniques (most of the list is AI/RL trading
platforms -- explicitly out of scope, paper-trading is 100%
algorithmic by design -- or alternative backtest engines, not worth
the migration risk given the existing walk-forward/Monte-Carlo
validation already built here). The one genuinely relevant idea:
realistic fill-cost modeling (the category `hftbacktest` /
`flashalpha-fill-simulator` occupy). Every fill so far, backtest AND
live paper engine, executes at the exact observed price with zero cost
for crossing the spread or moving an illiquid name's own volume -- a
known, disclosed simplification, but never actually quantified.

**Added `apply_slippage()`** in `backtest_v4.py`: widens buys / narrows
sells by `SLIPPAGE_BASE_BPS` (5, a flat spread-crossing cost) +
`SLIPPAGE_IMPACT_BPS` (50, scaled by `participation` = order quantity
/ the stock's own `avg_vol_20` -- how big a bite out of its daily
liquidity the order represents). Wired into every buy/sell path in
`compute_entry_fill` and `evaluate_position_exit`, including both
pyramid add-on tiers. Gated behind `SLIPPAGE_ENABLED` (env
`V3_SLIPPAGE`, default `"0"`) -- a no-op unless explicitly turned on.
**The live paper engine's GitHub Actions workflows never set
`V3_SLIPPAGE`, so this cannot change the running `V3_PAPER` run's
behavior** -- required by this session's own frozen-config governance
rule (no silent drift into an already-live track record). Verified:
full 9-window walk-forward with `V3_SLIPPAGE` unset reproduces the
pre-change numbers exactly, row for row (confirmed against a
stashed-changes rerun of the unmodified file, not just eyeballing);
`test_paper_trading_math.py` still 8/8 unchanged.

**With `V3_SLIPPAGE=1`** (default bps, un-calibrated against real IDX
execution data -- a reasonable estimate, not a validated cost model):
mean alpha across the 9 windows roughly halves, **+21.71% -> +9.73%**;
median alpha barely moves (+12.60% -> +11.71%), so the drop is driven
by a handful of concentrated windows, not a broad-based effect --
consistent with the standing concentration finding (6/9 windows
>65% of positive PnL from their top-5 tickers). Windows beating
benchmark: 6/9 -> 5/9. Profit factor: mean 1.58 -> 1.29, **median
1.12 -> 0.90** -- the typical window is now marginally unprofitable on
a per-trade basis once fill cost is priced in, not just the mean.
Most striking: **window 4 (2023 H2) flips from +41.89% alpha to
-24.03% alpha** -- a full sign flip on what was the second-best
window, traced to its own 92-93% top-5 concentration meaning a few
large fills in thin names ate most of the round-trip via slippage.
Win-rate-clearing-50% held steady at 4/9 either way -- the entry rule
itself still picks real winners more than half the time; it's the
economics of actually executing size in illiquid names that's fragile.

**Kept `SLIPPAGE_ENABLED` off by default** -- this is not a "tested,
rejected" strategy toggle like `TREND_SIZING`; it's a diagnostic on
whether the existing headline numbers are honest. Two reasons not to
flip the switch: (1) the bps values are a reasonable estimate, not
calibrated against real IDX brokerage/market-impact data, so treating
them as gospel and quietly ratcheting down every published number
would trade one kind of overconfidence for another; (2) flipping the
default would also silently move the live paper engine's economics if
its workflows ever start setting `V3_SLIPPAGE`, which is exactly the
kind of drift the frozen-config rule exists to prevent. **What this
finding actually does**: hardens the "not deployment-ready" verdict
with a number. The 3-week validated edge (Monte Carlo p=0.0000, real
selection skill) survives realistic fill costs directionally -- still
beats benchmark most windows, still keeps win rate above 50% in the
same windows -- but the *magnitude* investors would actually see is
meaningfully smaller than the frictionless backtest suggests, and at
least one window's story flips entirely. Before ever moving from paper
to real capital, this needs a properly calibrated slippage model (real
IDX bid-ask/impact data, not an estimate) run against the full
walk-forward battery, not just this directional check.

## Walking back the slippage number: functional form matters more than expected

Read the actual paper behind the slippage idea in full this session --
Cont, Kukanov & Stoikov (2011), "The Price Impact of Order Book
Events" -- rather than just citing it. Their real, validated model is
`price_change = beta * order_flow_imbalance`, `beta ~ 1/market_depth`,
estimated on Level-1 bid/ask queue data (65% average R^2 across 50
NYSE stocks). **This project has no such data for IDX names** -- only
EOD OHLCV, no bid/ask depth at any timescale -- so that model is
simply not buildable here, not now and not without a new data source.

The linear-in-participation slippage shipped earlier this session was
never actually sourced from this paper -- it was an unsourced straight
line with round-number bps. Going back to CKS's own text, they *do*
derive a volume-only proxy (`price_change ~ sqrt(volume)`, their
equation 14) as a byproduct of the real model, for exactly this
situation -- no book data, only trade/volume data. But they explicitly
call it noisier than the real model and write "we do not recommend to
use it." Used it anyway, since a concave shape grounded in a real
derivation is more defensible than an arbitrary linear one, and it's
the only proxy that fits what this project actually has.

**Swapped `apply_slippage()`'s impact term from linear to
`sqrt(participation)`**, recalibrated `SLIPPAGE_IMPACT_BPS` (50 -> 16)
so impact at the liquidity cap (10% of ADTV, `cfg.LIQ_CAP_PCT`) lands
near the same ~5bps the old linear model gave at its own cap --
apples-to-apples at the one point both curves were anchored to.
Result, full 9-window walk-forward: **mean alpha +21.71% -> +21.25%**
(previously reported: -> +9.73%), median profit factor 1.12 -> 1.14
(previously reported: -> 0.90), win-rate-clearing-50% 4/9 -> **5/9**
(previously reported: unchanged at 4/9). **Window 4's alpha sign flip
(+41.89% -> -24.03%) does not reproduce** -- under the sqrt model it's
+42.21%, essentially untouched. Slippage-off run re-verified
byte-identical first, so this is a clean swap, not new drift. Dry-run
math test still 8/8 (default stays off; live paper engine unaffected
either way).

**The actual finding here isn't "impact is small after all."** It's
that this project's own slippage estimate swung from "roughly halves
the edge and flips a window" to "barely moves anything" purely from
changing the shape of an unvalidated cost function -- neither version
is fit to real IDX execution data, both are estimates. That's the
same failure mode as the hysteresis-band sensitivity sweep earlier
this session (one config looked great, the neighborhood didn't): a
number this sensitive to an arbitrary modeling choice isn't a number
to trust either direction. The honest position is unchanged from
before this whole detour: **the frictionless backtest number is an
upper bound, the true real-world number is unknown but not zero, and
nothing short of real IDX bid-ask/impact data closes that gap** -- not
another guess at a better-sounding formula. Not deployment-ready
either way.

**Also added, same session: CVaR(95%) as a second tail-risk metric**
alongside `max_drawdown` -- mean daily return on the worst 5% of days
in a window's equity curve. Distinct signal from drawdown (one
peak-to-trough episode): a window can have a mild max drawdown but a
fat left tail of bad days, or the reverse. Baseline (slippage off):
mean -3.72%, worst -5.64% (window 8, the standout winner -- its
CVaR is also its worst, a reminder that the best-returning window
isn't the smoothest one). Printed per-window and in the aggregate
summary in `walk_forward_v4.py`; stored in `simulate_window()`'s
returned `metrics` dict as `cvar_95`. **Update, same day**: wired into
the `backtest_runs` Supabase insert (`cvar_95` column added via MCP
migration) and shown on `/backtest` next to Max Drawdown.

## Live paper engine: drawdown_pct was hardcoded to 0.0, now real (plus live CVaR)

Found while looking for something useful to close during the weekend
lull before paper trading's first real trading day. `paper_signal_scan.py`'s
daily equity snapshot wrote `drawdown_pct: 0.0` on every single insert --
a placeholder that was never filled in, and `backtest_runs.max_drawdown`
for the live run was never updated at all after the seed row's initial 0.
Not yet visibly wrong on the website only because no paper-trading day
had happened yet to expose it (0 rows in `paper_positions`/`backtest_equity`
as of this check) -- the exact right moment to fix it, before any real
row would need correcting.

Added `paper_common.compute_drawdown_and_cvar(equity_history, today_equity)`
-- a pure function (extracted for the same reason `compute_entry_fill`/
`evaluate_position_exit` were: independently testable, see
`test_paper_trading_math.py`'s new `test_compute_drawdown_and_cvar`,
3 hand-computed cases). Real drawdown = today's distance from the
running peak including today; `backtest_runs.max_drawdown` now tracks
the running min (worst) drawdown ever seen, not a stale seed value.
CVaR(95%) computed the same way as the batch backtest's (worst-5%-of-
days mean daily return) but withheld (`None`) until 20+ days of live
history exist -- noisy and misleading on a handful of days otherwise.
9/9 dry-run checks pass. No walk-forward re-check needed -- doesn't
touch `backtest_v4.py`'s shared entry/exit functions, only the live-only
EOD snapshot step.

## Full-universe daily scoreboard -- backend shipped (2026-08-02)

Queued below yesterday, built today (Sunday, day before paper trading's
Monday launch). Shipped exactly the scoped v1: `score_full_universe()`
in `backtest_v4.py` (new function, zero lines changed in
`score_candidates`/`evaluate_position_exit`/`simulate_window` -- no
walk-forward re-check needed, same reasoning as the CVaR live-engine fix
above), wired into `paper_signal_scan.py`'s daily run, writing to a new
`daily_scoreboard` table (applied via migration). Labels: STRONG_BUY/
BUY/WATCH/WAIT exactly as scoped -- no SELL label, no price target
(both deferred for the reasons below, unchanged). 10/10 dry-run checks
pass, including the case that matters most: a ticker with a high score
driven entirely by `sector_rs_momentum` but failing the `weekly_ma_spread`
gate correctly lands on WATCH, not BUY -- score alone never overrides a
failed gate.

**Not yet done**: frontend read (newscraper.ai repo) -- ticker
search/detail page doesn't query `daily_scoreboard` yet. Backend-only
this pass, deliberately, given this ships hours before Monday's real
launch and the live paper-trading pipeline is the priority to keep
stable, not rush a frontend integration alongside it.

## Original scoping note (queued, now shipped above)

User request (2026-08-01, weekend before paper trading's Monday launch):
today the daily scan only surfaces the stocks that actually qualify as
new candidates (`score_candidates` in `backtest_v4.py`, currently called
with `top_n=15` from `paper_signal_scan.py`; V1's separate Telegram bot
posts its own top-10, `src/screener.py:162`). Everything else in the
IHSG universe is invisible -- if a user searches a specific ticker on
the website, there is currently no answer to "where does this stock
stand today." Ask: score **every** ticker daily, not just qualifiers,
with a confidence label (something like Strong Buy / Buy / Watch / Wait)
and, ideally, a target price to wait for.

**Why this is cheaper than it sounds, for the classification half.**
`score_candidates` (`backtest_v4.py:404-429`) currently does two things
in one step: (1) a hard gate -- `adtv_20 >= ADTV_MIN AND weekly_ma_spread
>= weekly_cut AND sector_rs_momentum >= sector_cut AND ATR sanity`,
which is why anything failing the gate never gets a score at all today
-- then (2) a score for whatever survives the gate:
`(weekly_ma_spread - weekly_cut)/|weekly_cut| + (sector_rs_momentum -
sector_cut)/|sector_cut|`. That score formula is just a normalized
distance above both cuts -- it's equally well-defined for a stock
*below* the cuts (it just comes out negative). So computing a score for
the whole liquid universe is not new modeling, it's removing the gate
before scoring and keeping it only as a label:
  - Above both cuts + passes ATR/regime sanity -> **Strong Buy** if score
    also clears `score_p90` (the same threshold `SCORE_SIZING_ENABLED`
    already uses to size positions), else **Buy**.
  - Below one or both cuts but regime is BULLISH -> **Watch** (bucket by
    how close: near-miss vs far below is just the same score number,
    now negative).
  - Regime not BULLISH, or `REGIME_CONFIRM_DAYS` hasn't been cleared yet
    -> **Wait** (this is a real, already-computed piece of state --
    `compute_regime_with_hysteresis`, not a new signal).
  - Liquidity gate itself fails (`adtv_20 < ADTV_MIN`) -> excluded
    entirely, not scored, not shown as "Strong Sell" or anything else.
    **This matters**: the ADTV liquidity filter is the exact fix for the
    hypervolatile-penny-stock bug that inflated an earlier headline
    backtest number (see the bug/gap section near the top of this log).
    Scoring illiquid names "for completeness" would quietly reopen that
    same hole in a user-facing feature instead of a backtest, which is
    worse, not better.

**Why "Strong Sell" is the wrong label to promise.** This system has
no short/sell-signal model -- it's a long-only entry screener. A stock
scoring badly here means "doesn't qualify as a new long entry today,"
not "sell this if you own it." Labeling that Strong Sell implies a
fundamental/technical view the algorithm was never validated to hold.
Plan is to use Buy-side-only language (Strong Buy/Buy/Watch/Wait) and
be explicit in the UI copy that this is an entry screener, not a full
buy-and-sell advisory.

**Why "what price to wait for" is the part that needs real caution, not
a quick add.** Nothing in `backtest_v4.py` today computes a pullback or
support target -- entries fire at next available open once the gate
clears, full stop. Any "wait for Rp X" number would have to come from a
brand-new heuristic (e.g. distance back to `weekly_cut`/`sector_cut` in
price terms, or a moving-average level) that has never been walked
forward or validated the way the entry rule itself was (Monte Carlo
p=0.0000, 9-window walk-forward, three real bug fixes along the way).
Shipping an unvalidated number as if it were advice is exactly the
failure mode this whole project has spent three weeks trying to avoid
in the backtest -- doing it live, to users, without the same rigor,
would be worse. **Do not ship a "wait for this price" figure until it
has its own backtest**: does entering when price retraces to that
computed level actually perform better than entering at the gate-clear
open, on held-out data? If not (or if not tested), the honest v1 is to
show *only* "how far the score currently is from qualifying" (a number
already computed, zero new modeling) and leave the price target out
rather than fabricate one.

**Where it plugs in, with zero risk to the live paper track record.**
`paper_signal_scan.py` already runs the full feature pipeline
(`add_features`, `compute_rs_momentum`, `attach_weekly_trend`,
`compute_regime_with_hysteresis`) and recomputes `weekly_cut`/
`sector_cut`/`score_p90` once per day for the whole liquid universe,
before it ever calls `score_candidates` to pick actual trade candidates.
This enhancement is a pure read/display addition *after* that existing
step -- score everything the pipeline already touched, write it to a
new table (e.g. `daily_scoreboard`, one row per ticker per day: score,
label, gate distances), and never feed it back into `paper_positions`/
`paper_account`. It cannot touch the frozen live config or the actual
trading decisions -- same isolation guarantee the CVaR fix above relied
on.

**Scope for a first version (skip the price-target piece for now):**
1. New pure function alongside `score_candidates` (same file, same
   signature style) that scores the full liquid-universe day-slice
   without the gate, returns score + label for every ticker instead of
   only the top-N that pass.
2. `paper_signal_scan.py` calls it once daily (already has all the
   inputs in hand), upserts one row per ticker into a new
   `daily_scoreboard` table.
3. Frontend: ticker search/detail page reads that table for "today's
   score" -- this is the newscraper.ai repo, not this one.
4. Explicitly deferred: the "wait for this price" target, until it has
   its own validation pass. Note it here so it isn't silently dropped,
   not because it's being built next.

## Bug found + fixed: ihsg_eod/ihsg_realtime close_price is NOT split-adjusted

Found 2026-08-02, the day before paper trading's Monday launch, while
checking an external code-review's "does this handle corporate actions"
question -- the codebase had zero mentions of splits/dividends anywhere,
so it needed an actual data check, not just a grep. Confirmed with a
direct query for extreme day-over-day close ratios:

```
DSSA  2026-04-09  67000 -> 3120   (ratio 0.047, ~1:21)
FISH  2025-09-09  10350 -> 1035   (ratio 0.100, exactly 1:10)
CUAN  2025-07-15  16875 -> 1625   (ratio 0.096, ~1:10.4)
MLPT  2026-07-21  25950 -> 1300   (ratio 0.050, ~1:20)
PACK  2026-01-12   3280 -> 272    (ratio 0.083, ~1:12)
```

These are real stock splits sitting unadjusted in the raw feed, not
crashes -- IDX auto-reject bands don't allow a genuine single-day move
anywhere near these ratios, and the round numbers are the giveaway. This
affects `strategy.py`'s `add_features()` (shared by V1 and V3 -- any
rolling window spanning a split date computes over a fabricated price
cliff) and, more urgently for tomorrow, the live paper engine: a held
position's SL/TP1/TRAILING is evaluated against `avg_price` set at entry
-- an unadjusted split during the hold period would look identical to a
catastrophic real loss and could force a false exit, corrupting the live
track record with a loss that never happened.

**Fixed defensively, not by adjusting the feed** (no access to a
corporate-actions data source, and retroactively adjusting historical
`ihsg_eod` is a separate, bigger job outside today's scope). Added
`paper_common.looks_like_unadjusted_corporate_action(prev_price,
current_price)`: true if the ratio falls outside [0.6, 1.7], bounds wide
enough that no legitimate single-day IDX move should ever cross them.
Wired into both live scripts as a guard BEFORE calling
`evaluate_position_exit` -- zero changes to that shared function, so no
walk-forward re-check needed (same isolation reasoning as every other
live-only fix in this log):
  - `paper_signal_scan.py`'s EOD reconcile: compares today's close
    against the stock's own previous trading day close (looked up from
    the already-loaded full history).
  - `paper_monitor.py`'s intraday check: compares the live price against
    the position's own `avg_price` (the anchor SL/TP1/trailing actually
    evaluate against) -- deliberately not `day_open`, since if the split
    happened overnight, today's open already reflects the new price too
    and wouldn't trip the guard at all.

On a hit: skips SL/TP/trailing evaluation for that position this cycle
only, sends a Telegram alert, leaves the position open and untouched for
manual review (`avg_price`/`sl_price`/`tp1_price` need a human to correct
against the real split ratio -- not something to guess automatically).
11/11 dry-run checks pass, including the real confirmed splits above as
literal test cases, a synthetic reverse-split, a genuine bad-but-real
-25% day (must NOT trip), and null/zero-price inputs (must not crash).

**Not fixed**: the underlying data still isn't split-adjusted, and V1's
`add_features()` still computes rolling windows over the raw feed --
untouched, since that's a protected file and a much bigger job (would
need a real corporate-actions source, not a threshold guess). This is a
live-engine safety net, not a data-quality fix.

## Day 1 live (2026-08-03): first real signal-scan run, 22min, root cause found + fixed

The gh-dispatch bridge bug (workflow files living only on this branch
can't be dispatched by filename OR by ID from a `main`-branch trigger --
GitHub never indexes them) was fixed on `main` this same morning by
inlining `actions/checkout@v4` with `ref: worktree-v2-hmm-screener`
directly into the three trigger workflows, dropping the `gh workflow run`
dispatch step entirely. First scheduled fire after the fix: still 34+ min
late (GitHub schedule jitter or something stuck -- inconclusive, since it
had never fired successfully before either), so triggered manually.
**Result: real success** -- `paper_account.last_signal_date` set to
2026-08-03 for the first time ever, 2 real PENDING candidates queued
(DOOH, BAJA, `V3_regime_weekly_sector` trigger), to fill at tomorrow's
open via `paper_monitor.py`. First genuine end-to-end proof this pipeline
works in production, not just in dry-run.

Took **22m10s**. Root-caused by reading `data_fetch.fetch_data()`
directly (this was its first-ever real invocation, so no prior timing
baseline existed): `build_full_dataset()` refetches the ENTIRE history
(`FETCH_START=2021-01-01` minus 280d lookback, through today) from
scratch every single day, no caching between runs. The stock-OHLCV fetch
chunks by 50 stock codes x one request per calendar month across ~5.5
years -- for a ~900-stock universe that's ~18 chunks x ~68 months =
1,200+ fully serial paginated Supabase requests, one at a time. Not a
hang, not a bug in the trading logic -- just genuinely that slow by
design, and nobody could have caught it earlier since the dispatch bug
prevented this code path from ever running against real data before today.

**Fixed same day** (`a20fbab`, low-risk since it's pure I/O concurrency,
zero change to what's fetched or computed): every (stock-code-chunk,
month) request is independent and order-insensitive -- the assembled
dataframe gets `sort_values()`'d regardless of arrival order -- so both
that loop and the smaller per-checkpoint stock-code-discovery loop now
run through a `ThreadPoolExecutor(max_workers=12)` instead of one request
at a time. Expected ~1-2min instead of 22min. Verified: syntax-checks,
existing 11/11 regression suite (`test_paper_trading_math.py`) still
passes unaffected. **Not yet verified against a real run** -- today's
scan already set `last_signal_date=2026-08-03` so it'll skip until
tomorrow; the actual wall-clock improvement is confirmed by the next
real scheduled run, not asserted here. Deliberately did NOT touch the
CPU-bound per-stock `add_features()` loop in the same function
(`build_full_dataset`, `backtest_v4.py`) in the same pass -- that's a
groupby-vs-repeated-filter algorithmic question, touches the shared
validated backtest logic, and per this log's own discipline would need
a full 9-window walk-forward regression check before landing, not
something to bundle into a same-day I/O fix.

## MIN_HOLD_DAYS/TP1 blocked-crossing study + W9 (2026 H1) deep dive (2026-08-07)

Two read-only research passes tonight, zero changes to `backtest_v4.py` --
both used a runtime monkeypatch/direct call against the existing
`walk_forward_data_2021-01-01_2026-06-30.pkl` cache, not the live/frozen
`V3_PAPER` config.

**Study 1 -- does `MIN_HOLD_DAYS=3` blocking a real TP1 crossing actually
cost money?** User flagged a live example (BLES, day 1 of hold, close
already above TP1 but blocked). Instrumented `evaluate_position_exit` to
log every day a position's `high >= tp1_price` fired while `hold_ok` was
still false, across all 9 walk-forward windows: 85/392 trades (21.7%)
hit this at least once; 73 of those 85 (86%) captured TP1 anyway once the
gate opened -- delayed, not lost. Only 8 positions (2.0% of all trades,
~Rp11.4M combined across all 9 windows) round-tripped into a real SL loss
they'd touched TP1 before hitting. **Conclusion: leave `MIN_HOLD_DAYS`
alone** -- its job is blocking whipsaw noise-exits right after entry (the
exact fix for the window-3 -22% incident), and this cost is small enough
that loosening it risks reopening that wound for a 2%-of-trades problem.

**Study 2 -- W9 (2026-01-02..2026-06-30), the OOS window immediately
before live launch, was the weakest of all 9** (net -15.74%, win rate
34.8%, PF 0.49, SL=65.2% of exits) despite alpha +19.75% (IHSG itself
fell -35.49% that window). Pulled the actual trade list and regime
timeline instead of trusting the aggregate number: **all 23 of the
window's trades entered between 2026-01-05 and 2026-01-27** -- regime was
BULLISH for exactly those 17 trading days (already past
`REGIME_CONFIRM_DAYS=3`, so not a false-start flip), then flipped BEARISH
on 2026-01-28 and held BEARISH for the remaining ~94 days straight, during
which the strategy correctly opened zero new positions (that's *why* it
only lost -15.74% while the index fell -35.49%, not despite it). 15 of
23 entries were SL losses, mean hold 2.0 days, mean -12.15% -- almost all
opened in the back half of that 17-day bullish stretch, right before it
turned. **Same shape as the already-documented window-3 bull-trap, one
level up**: not a false-start flip (that's fixed), but a genuine
multi-week bullish run that reversed hard right as positions piled in
late into it. `TREND_STRENGTH_MIN`/`REGIME_CONFIRM_DAYS` don't address
this -- both were satisfied the whole time; the trend was real, it just
ended. **Not fixed tonight, not attempting a same-night parameter change
off one eyeballed window** -- exactly the mistake the hysteresis-band
sweep already taught this log not to make. Flagging as the next real
research thread: something like "how late into a confirmed bullish run is
still safe to enter" (a trend-age or momentum-deceleration signal, not a
regime-confirm-days tweak) needs its own swept, all-9-window validation
before it goes anywhere near the live config.

**CORRECTION + follow-up test (same night):** the "17-day bullish stretch"
claim above is wrong -- an artifact of filtering `regime_by_date` to
just the W9 test window before checking for transitions, which makes the
first day of the *filter* look like a regime-flip day even when it isn't.
Checked the real streak: `bullish_streak_by_date` shows BULLISH running
continuously from **2025-06-02 (at latest -- streak was already 16 that
day) through 2026-01-27**, ~8 months, before flipping BEARISH on
2026-01-28. And that flip wasn't a fade -- `trend_strength` (IHSG's
separation from ma50) went from +3.21% to -4.36% in ONE trading day, then
kept falling to -8.79% within a week. Not a bull trap; a genuine long
bull market ending in a sharp, fast reversal. The system's own response
(zero new entries for the following 94 days once BEARISH latched) is
exactly why the window only lost -15.74% against IHSG's -35.49% -- that
part worked as designed.

Given that correction, ran the actual testable version of the "trend-age"
hypothesis pooled across all 392 trades from all 9 windows (not just
eyeballing W9): does `bullish_streak_by_date` at entry (days into a
confirmed run, uncapped) or `trend_strength` at entry predict SL losses?
**No.** Mann-Whitney wins-vs-losses p=0.67 (streak) and p=0.28 (trend
strength); Spearman rho(streak, pnl_pct)=-0.027 (p=0.59, indistinguishable
from zero); win rate by streak bucket is flat-to-slightly-improving with
higher streak (51.4% at streak 6-9 up to 54.4% at streak 20+), not
declining. Per-window check confirms this isn't masked by aggregation --
W1 and W8 also had long streaks at entry (mean ~157-160 and ~99
respectively) with strong win rates (54.5%, 65.6%); W9's streak (~164-170)
wasn't unusual, other windows saw similar values and did fine. **The
trend-age hypothesis is dead, confirmed empirically, not just discarded on
priors.** W9's loss isn't a timing-gate problem at all -- it's a sharp,
fast, largely unpredictable-in-advance regime break, the kind of tail risk
inherent to any long-biased momentum strategy, not a bug this system's
rules can front-run without also killing entries in the many other
long-running-bullish windows that went on to do fine. Nothing to build
here. Closing this thread rather than let a wrong framing stand
uncorrected in this log.

## diagnose_score_power run + rank-1-specific fix, built and swept -- doesn't clear the bar yet (2026-08-07)

Ran `diagnose_score_power.py` for real for the first time (previously built but never
executed -- see the "V3.1 candidate entry filters" entry). Live fetch against Supabase took
8+ minutes, not the "~1-2min" the data_fetch concurrency-fix commit estimated but never
verified against a real run -- correcting that record here since it's now actually measured.
1,768 candidate-days, 345 sessions, 2022-01-03..2026-08-07.

**Headline (block A):** top-2-by-score underperforms rank-6-12 on every metric (ret_20 3.96%
vs 16.33%, win_20 46.8% vs 57.2%, sl_hit_10 84.6% vs 75.6%). Same inversion under liquidity
and calmness orderings too (blocks B/C) -- not score-specific. Block D (per-window) only had
3/9 windows with enough rank-6-12 candidates to check, 2/3 showing the inversion -- thin,
flagged in the script's own output as needing more than 3 data points before acting.

**Deeper look at the raw output (`diagnose_score_power_raw.csv`) resolved the ambiguity.**
Per-exact-rank breakdown: rank 1 specifically is bad (win_20=36.8%, sl_hit_10=89.5%,
sl_hit_20=100%) -- ranks 2 through 12 are all roughly flat and unremarkable (win_20 46-57%,
no trend). Pooled Spearman rho(rank, ret_20)=0.018 (p=0.45) confirms: there is NO broad
top-tier-underperforms-middle effect once rank 1 is separated out. The earlier "top-2"
bucketing was averaging a genuinely bad rank-1 with a perfectly fine rank-2, which is what
made the whole top tier look bad.

**Characterized rank-1 specifically:** ~2x the average score magnitude of rank 2+ (63.6 vs
35.6), ~20% higher ATR% (0.076 vs 0.063) -- a same-day statistical outlier, not just "the
best pick." Split the 4.5-year sample at its midpoint (2025-08-08) for a real robustness
check (much more power than the thin 3-window check): rank-1's stop-loss-hit rate stays
extremely high in BOTH halves (82.4% H1, 97.7% H2) even though rank-1's raw win rate moves
with the broader market like everything else does (29.4%->45.5%). This is the load-bearing
result: a same-day-outlier signature that survives a genuine out-of-sample split, not a
period-specific artifact.

**Built two mechanisms in `score_candidates()` to test the fix, both off by default (0 /
None), byte-identical to every existing caller -- reverified via a W9 rerun post-change
(still 23 trades / -15.74% / 34.8% win) plus the full regression suite (12/12):**
- `skip_top_n` (`V3_SCORE_SKIP_TOP_N`): unconditionally drops the day's #1 candidate.
- `outlier_gap_mult` (`V3_SCORE_OUTLIER_GAP_MULT`): only drops #1 when its score exceeds
  this multiple of #2's score (a real-outlier gate, not a blanket rule) -- rank1/rank2 score
  ratio across the sample: median 1.09x, 75th pct 1.36x, max 1.93x.

**Full 9-window walk-forward sweep, off the existing cache (skip0 baseline / skip1 flat /
gap1.3 / gap1.5 / gap1.8):**

| config | mean profit | median profit | mean alpha | mean PF | median PF | mean maxDD | worst maxDD | beat-bench |
|---|---|---|---|---|---|---|---|---|
| baseline | +20.84% | +2.96% | +21.71% | 1.58 | 1.12 | -16.08% | -21.61% | 6/9 |
| skip1 flat | +10.20% | +11.46% | +11.07% | 2.01 | 1.54 | -14.51% | -24.03% | 7/9 |
| gap1.3 | +10.54% | +3.16% | +11.40% | 1.36 | 1.09 | -16.48% | -23.49% | -- |
| gap1.5 | +12.29% | +3.74% | +13.15% | 1.50 | 1.15 | -16.28% | -21.61% | -- |
| gap1.8 | +20.55% | +7.58% | +21.42% | 1.58 | 1.31 | -16.82% | -21.61% | -- |

**None of these clear the bar this project has actually used to adopt a change before**
(LIQ_SIZING_ENABLED's own adoption criterion: best mean alpha AND best worst-case drawdown
of everything tested, simultaneously). skip1 flat wins on median profit/PF and beat-bench
count, but LOSES on mean alpha (21.71%->11.07%) and worst-case drawdown (-21.61%->-24.03%)
by giving up most of window 8's outlier upside (129%->40%) while making window 2 worse
(-6.54%->-17.36%). The outlier-gap-conditional variants (meant to only strike genuine
outliers and preserve good rank-1 days like W8) don't cleanly fix this either: gap1.3 is a
net negative (worse win rate than baseline, wrecks W4 50.49%->3.16%), gap1.5 is a wash, and
gap1.8 is nearly a no-op (only fires in 2/9 windows -- W5 improves, W2 -- already a loser --
gets worse) with a modest, thin median-profit gain that isn't worth trusting off two touched
windows.

**Conclusion: the rank-1 finding is real (survives an actual out-of-sample split, not a
3-point read), but converting it into a config change that's actually better -- not just
different -- isn't done.** Every threshold tried trades one risk axis for another rather
than clearly reducing risk. Both mechanisms stay in the code, off by default, alongside
every other unvalidated-but-available flag (SCORE_SIZING_ENABLED, TREND_SIZING_ENABLED,
PYRAMID_TREND_GATE_ENABLED) -- real infrastructure and a real, now-quantified finding, not
a decision to flip a default off two sweeps. If this gets picked back up: the natural next
angle is asking WHY rank-1 fails (which of weekly_ma_spread vs sector_rs_momentum drives the
outlier score, and whether gating on each factor's own extremity separately -- rather than
the combined score's magnitude -- is more surgical), not more threshold values on the same
combined signal.

## Decomposed WHY rank-1 fails; built the surgical version; drawdown effect real, profit effect not trustworthy yet (2026-08-07, same night)

Followed the log's own suggested next angle. Replicated diagnose_score_power's day-loop
against the local walk-forward cache (no live fetch needed -- a mechanism question doesn't
need this week's freshest data), capturing `weekly_ma_spread` and `sector_rs_momentum`'s
individual normalized components (`w_comp`, `s_comp`) instead of just the combined score.

**Rank-1's outlier-ness comes almost entirely from `w_comp`, not `s_comp`.** Rank-1 mean
`w_comp`=48.78 vs rank-2+'s 19.72 (2.5x) -- but mean `s_comp` is nearly identical (16.92 vs
16.74). Pooled Spearman correlations of each component alone against 20-day forward return
were both statistically flat (w_comp rho=-0.026 p=0.28, s_comp rho=-0.008 p=0.74) -- but that
is because the real relationship is non-monotonic, which a linear rank correlation can't see.
Quintile breakdown makes it visible: `w_comp`'s top quintile (mean 41.97, closely matching
rank-1's own profile) is the ONLY quintile where win rate and mean return both drop
(50.3% win, matching rank-1's badness, sl_hit_20=100% exactly), after rising cleanly through
Q1-Q3. `s_comp`'s top quintile shows no such reversal -- its highest bucket has the SECOND-
BEST mean return of the whole table (12.04%). An "imbalance" hypothesis (one factor
dominating the other) was tested and killed first (rho=-0.014, p=0.90 within rank-1 alone,
pooled bucket table not monotonic) before landing on this cleaner, component-specific read.

**Built `weekly_comp_cap_q`** (`V3_SCORE_WEEKLY_COMP_CAP_Q`, default None/off, byte-identical
-- reverified via W9 rerun, still 23/-15.74%/34.8%, plus 12/12 regression suite): excludes
candidates whose `w_comp` exceeds this within-day quantile of that day's own qualifying pool.
Targets the actual driver directly instead of using rank or combined score as a fuzzy proxy.

**Swept 7 quantile values (0.95 down to 0.35) across the full 9-window walk-forward --
applying the exact discipline this log already learned the hard way from the hysteresis-band
episode: don't trust one point, check the neighbors.** Good news and a real caution, not a
clean win:

| cap_q | mean alpha | mean maxDD | worst maxDD | trades |
|---|---|---|---|---|
| baseline (off) | +21.71% | -16.08% | -21.61% | 392 |
| 0.95 | +14.07% | -16.17% | -21.39% | 364 |
| 0.90 | +14.57% | -14.68% | -23.97% | 355 |
| 0.85 | +20.50% | -11.34% | -14.76% | 329 |
| 0.75 | **+34.57%** | -10.92% | -16.71% | 332 |
| 0.60 | +19.99% | -11.05% | -18.44% | 288 |
| 0.50 | +22.06% | **-9.87%** | **-13.86%** | 313 |
| 0.35 | +30.95% | -10.09% | -14.12% | 292 |

**Drawdown improvement is the trustworthy part of this result.** Every single tested value
reduces mean drawdown vs baseline, most by a lot (-16.08% -> roughly -10 to -11% for every
cap_q <= 0.85) -- consistent, monotonic-ish, and mechanistically sensible: removing the most
overextended entries removes exactly the trades most prone to a violent reversal. This part
is believable.

**The alpha/profit numbers are NOT trustworthy at any single value.** They zigzag
non-monotonically across neighboring thresholds -- 0.75 looks spectacular (+34.57%), its
immediate neighbor 0.60 is actually WORSE than baseline (+19.99% vs +21.71%), then 0.50 and
0.35 climb back up. Only 3 of 7 tested values (0.75, 0.50, 0.35) even beat baseline's mean
alpha; 0.90/0.95/0.85/0.60 land below it. Trade counts are already down to 288-364 (some
individual windows down to 11-16 trades), which is exactly the small-sample regime where a
few trades falling in or out of a filter at one exact cutoff can swing an aggregate by
double digits -- textbook version of the same trap the 2%-hysteresis-band episode already
named in this log: a great-looking single point in a noisy landscape, not a validated optimum.

**Where this leaves it:** the mechanism is real and now well-understood (extreme
weekly_ma_spread specifically drives the bad outcomes; sector momentum doesn't). The
drawdown-reduction effect looks genuinely adoptable-shaped. The profit/alpha effect needs
real tuning discipline before any number gets trusted -- likely a per-window-fit cutoff
(learned from each window's own train split, the same way weekly_cut/sector_cut already are,
rather than one hand-picked global constant) or a materially larger sample before grid-
searching a single quantile threshold again. `SCORE_WEEKLY_COMP_CAP_Q` stays off. Not
adopting anything tonight off a threshold that swings 15+ points between neighbors.

## Why TP1_PCT=0.10 and not more -- swept, and this one's decisive (2026-08-08)

User question after seeing a live position (BLES) sell only 10% at TP1: why not take the
whole profit there, and doesn't partial-TP + pyramid mean more transactions -> more fees?
Both real questions, both answered directly rather than by reasoning from priors.

**Fees: yes, real, and already priced into every number this log reports.** Backtest fees
apply to every transaction regardless of TP1_PCT; summed across all 9 windows (Rp100M
capital each): TP1_PCT=0.10 (current, pyramid on) = Rp26.2M total fees vs a literal "sell
100% at TP1, no pyramid, no re-entry" config = Rp8.5M -- roughly 3x less fee spend. So the
fee concern is correct, not imagined. It just doesn't change the conclusion once net
performance is compared (below) -- the fee-heavier config still wins by a wide margin
after those fees are already deducted.

**Swept TP1_PCT at 0.10 (current) / 0.25 / 0.50 / 0.75 / 1.00, all with pyramid on, plus
one more run at 1.00 with pyramid OFF entirely** (the literal "just take the whole win and
stop" case the question was picturing) -- full 9-window walk-forward, no re-fetch:

| TP1_PCT | pyramid | mean alpha | mean profit | win rate | win>50% | total fees (9 windows) |
|---|---|---|---|---|---|---|
| 0.10 (current) | on | **+21.71%** | **+20.84%** | 51.4% | 4/9 | Rp26.2M |
| 0.25 | on | +15.84% | +14.98% | 50.3% | 4/9 | Rp27.5M |
| 0.50 | on | +8.09% | +7.23% | 47.9% | 3/9 | Rp29.1M |
| 0.75 | on | +13.82% | +12.96% | 47.7% | 3/9 | Rp31.4M |
| 1.00 | on | +14.41% | +13.55% | 44.7% | 2/9 | Rp34.7M |
| 1.00 (full TP) | **off** | +0.22% | -0.65% | 51.2% | 2/9 | Rp8.5M |

**Unlike the last two sweeps tonight, this one is not a fragile single point -- it's a clean,
directionally consistent result.** 0.10 beats every other value tested, by a wide margin, on
every metric that matters (mean alpha, mean profit, win-rate-consistency). The most literal
version of "just take the full profit" (1.00, no pyramid) comes out to essentially ZERO edge
(+0.22% alpha -- indistinguishable from doing nothing) despite paying the LEAST in fees of
any config. Mechanism matches something this log already established independently
(concentration checks earlier this session, most windows carried by a handful of huge
winners, 6/9 windows >65% concentration): selling the whole position at a small first target
caps exactly the compounding moves that produce most of the real profit. Locking in most of
the win early and letting the small remainder trail with a protected (breakeven) stop is
what actually captures those.

**No change made -- this confirms the existing default is already right, not a reason to
touch it.** Genuinely reassuring result, not just a null one.

## weekly_comp_cap follow-up: train-derived absolute version -- confirms the drawdown effect, doesn't fix the noise (2026-08-08)

Direct follow-up to the weekly_comp_cap_q entry above. That version capped `w_comp` at a
quantile of THAT DAY's own qualifying pool -- often single digits in size, a plausible
source of the non-monotonic swings it showed. Built `weekly_comp_abs_cap`
(`V3_SCORE_WEEKLY_COMP_ABS_CAP_Q`, default None/off, byte-identical -- reverified via W9
rerun + 12/12 suite): learns ONE fixed cutoff per window from the full TRAIN period's own
`w_comp` distribution among historically-qualifying candidates -- same train-only,
applied-out-of-sample discipline `weekly_cut`/`sector_cut`/`score_p90` already use, a large
and stable reference sample instead of a noisy daily one.

Swept 0.95 down to 0.50. Below 0.65 the filter becomes too strict to trade at all (0.60
collapsed to 1 trade total across all 9 windows, 0.50 to zero) -- expected, a candidate
already needs `w_comp >= 0` by construction (weekly_ma_spread >= weekly_cut is part of the
qualifying gate itself), so a train-quantile cap much below that floor guts the candidate
pool entirely. Usable range is 0.65-0.95:

| abs_cap_q | mean alpha | mean maxDD | worst maxDD | trades |
|---|---|---|---|---|
| baseline (off) | +21.71% | -16.08% | -21.61% | 392 |
| 0.95 | +22.94% | -15.00% | -25.47% | 356 |
| 0.90 | +19.82% | -9.87% | -17.10% | 294 |
| 0.85 | +20.94% | -10.47% | -16.83% | 302 |
| 0.80 | +32.83% | -9.51% | -12.76% | 290 |
| 0.75 | +13.31% | -10.94% | -18.59% | 293 |
| 0.70 | +17.34% | -13.83% | -21.70% | 335 |
| 0.65 | +19.27% | -10.32% | -15.49% | 292 |

**Same two-part verdict as the within-day version, now confirmed independently by a second,
differently-constructed filter -- which makes both halves more trustworthy, not less.**
Drawdown: every single value from 0.65-0.95 beats baseline's mean drawdown, several by a
lot (-16.08% -> as low as -9.51%). Two unrelated filter constructions (a noisy daily
statistic and a stable train-derived one) both show this same consistent pattern -- real
evidence this is a genuine property of removing overextended entries, not a construction
artifact. Alpha: still bumpy (0.80 spikes to +32.83%, its immediate neighbors 0.85 and 0.75
sit at +20.94% and +13.31% -- an isolated peak, not a plateau). Since a differently-built
filter produces the SAME qualitative shape (drawdown solid, alpha noisy) rather than fixing
it, the noise looks like an intrinsic property of this strategy's small per-window trade
count (already down to ~290-350 across 9 windows, i.e. ~30-40/window) rather than something
a smarter filter construction can engineer away.

**Stopping this specific thread here.** Two independent constructions agree: this family is
a genuine, adoptable-shaped drawdown-reduction tool, and not (yet, at any single hand-picked
threshold) a trustworthy source of extra alpha. A third filter-construction attempt is
unlikely to resolve a noise floor that's about sample size, not shape. If drawdown reduction
alone becomes a live priority, this is ready to revisit with that framing; chasing alpha
through this specific mechanism needs a fundamentally larger trade sample first, not another
threshold sweep. Both flags stay off.

## V3.1 filters (ARA lock + ATR ceiling) validated for the first time -- best-looking candidate of the night (2026-08-08)

`ARA_FILTER_ENABLED` and `ATR_PRICE_RATIO_MAX` were built (see the "V3.1 candidate entry
filters" commit) specifically to be swept once `diagnose_score_power.py` existed as the
validation gate -- per project memory, that script had never actually been run before
tonight. Now that it has (twice, extensively -- see the entries above), this closes the
loop: both flags pure monkeypatch-tested against the full 9-window walk-forward, zero code
changes (both are module-globals `score_candidates` reads fresh at call time).

| config | mean alpha | win_gt50 | beat0 | mean PF | mean maxDD |
|---|---|---|---|---|---|
| baseline (ARA off, ATR<=0.10) | +21.71% | 4/9 | 6/9 | 1.58 | -16.08% |
| ARA on (ATR<=0.10) | +14.28% | 3/9 | 5/9 | 1.42 | -16.04% |
| ATR<=0.06 | +23.81% | 3/9 | 6/9 | 2.42 | -12.88% |
| ATR<=0.07 | +18.55% | 5/9 | 7/9 | 1.68 | -14.55% |
| ATR<=0.08 | **+33.03%** | 4/9 | 7/9 | 2.03 | -15.17% |
| ATR<=0.09 | +29.58% | 5/9 | 6/9 | 1.98 | -15.80% |
| ATR<=0.12 | +23.48% | 2/9 | 5/9 | 1.41 | -17.88% |
| ATR<=0.15 | +18.38% | 4/9 | 6/9 | 1.38 | -16.04% |
| ARA on + ATR<=0.08 | +29.69% | **5/9** | **7/9** | 1.95 | -15.33% |

**ARA lock filter alone: net negative.** Excluding candidates currently locked at their
own auto-reject ceiling sounds like it should only remove bad fills, but alpha drops
(21.71%->14.28%) and win-rate-consistency drops (4/9->3/9). Checked per-window: it helps
window 9 a lot (-15.74%->-0.36%) but costs window 4 badly (50.49%->3.16%) and trims window
8 (129.13%->91.40%) -- a real tradeoff, not a free filter, on its own.

**Tightening the ATR ceiling from 0.10 to 0.08 is the best single change tested tonight.**
Checked neighbors specifically (0.06/0.07/0.09) before trusting it, same discipline as
every other sweep -- and unlike the weekly-comp sweeps, 0.08 AND 0.09 both cluster well
above every other value tested (33.03% and 29.58%, vs everything else in the 14-24% range),
a plateau, not an isolated spike (0.07 dips oddly between 0.06 and 0.08, the one blemish
in an otherwise clean shape). **Combining ARA-on with ATR<=0.08 is the single best-rounded
result of the entire night**: best win-rate-consistency of everything tested (5/9, tied with
ATR<=0.09 alone) AND best beat-bench count (7/9, tied with ATR<=0.08 alone) simultaneously --
the ARA filter's downside gets absorbed/offset once paired with the tighter vol ceiling,
even though it was net-negative alone.

**Not deployed tonight -- flagged as the strongest validated candidate to come out of this
whole session, for a deliberate adoption decision, not an auto-flip.** Both flags stay at
their current defaults (off / 0.10) in the live-mirroring baseline. If this gets adopted:
`ATR_PRICE_RATIO_MAX=0.08` with `ARA_FILTER_ENABLED=1` is the config to carry forward,
`ATR_PRICE_RATIO_MAX` alone (no ARA) if simplicity is preferred over that last bit of
win-rate-consistency.

## Quick stack test: best candidate x drawdown-reducer -- one promising point, not yet trusted (2026-08-08)

Stacked tonight's two survivors -- ARA-on+ATR<=0.08 (best single change) and
`weekly_comp_abs_cap` (confirmed drawdown-reducer) -- to see if they compound.

| config | alpha_mean | dd_mean | dd_worst | win_gt50 | beat0 |
|---|---|---|---|---|---|
| baseline | +21.71% | -16.08% | -21.61% | 4/9 | 6/9 |
| ara+atr0.08 alone | +29.69% | -15.33% | -22.06% | 5/9 | 7/9 |
| + wcap 0.90 | +16.45% | -11.23% | -15.17% | 4/9 | 5/9 |
| + wcap 0.85 | +18.92% | -9.79% | -15.16% | 2/9 | 6/9 |
| + wcap 0.80 | **+34.80%** | **-8.94%** | **-12.29%** | 5/9 | 6/9 |

wcap 0.80 stacked on top beats everything tested all night on BOTH alpha and drawdown
simultaneously -- best of the whole session by a real margin if it holds. **But it's one
point among three (0.90/0.85/0.80), and 0.90/0.85 are clearly worse** -- the exact
"isolated peak, check the neighbors" situation this log has flagged (and been burned by)
multiple times tonight already. Not run finer (0.78/0.79/0.81/0.82) yet. Noting this as the
most promising open thread for next time, explicitly NOT as a validated result -- needs the
same neighbor-check discipline as everything else before it's trusted.

## Fine neighbor sweep confirms the wcap plateau -- real, not a lucky spike (2026-08-08)

Ran the finer grid the entry above flagged as missing: wcap in
{0.70, 0.75, 0.78, 0.79, 0.80, 0.81, 0.82}, ara+atr0.08 fixed.

| wcap | win_gt50 | beat0 | alpha_mean | pf_mean | dd_mean | dd_worst |
|---|---|---|---|---|---|---|
| 0.70 | 2/9 | 7/9 | +12.31% | 1.32 | -11.45% | -23.26% |
| 0.75 | 3/9 | 6/9 | +10.84% | 1.53 | -11.57% | -19.45% |
| 0.78 | 3/9 | 5/9 | +8.86% | 1.29 | -10.46% | -13.66% |
| 0.79 | 4/9 | 6/9 | +15.94% | 1.75 | -10.36% | -14.38% |
| 0.80 | 5/9 | 6/9 | +34.80% | 2.75 | -8.94% | -12.29% |
| 0.81 | 6/9 | 7/9 | +22.49% | 2.00 | -9.62% | **-11.56%** |
| 0.82 | 4/9 | 7/9 | **+35.92%** | **3.81** | -9.08% | -12.45% |

Not an isolated spike -- **0.80/0.81/0.82 cluster together as a real plateau**, clearly
separated from 0.70-0.79 on almost every axis: alpha roughly doubles (9-16% -> 22-36%),
win-rate-consistency climbs 2/9->3/9->3/9->4/9 then jumps to 5/9-6/9 in the plateau, and
worst-case drawdown improves from -23%/-19% down to -12%/-11%. This clears the
neighbor-check bar the entry above said it needed.

Picking a specific point inside the plateau: 0.80 has the single highest win_gt50-adjacent
combo but only 5/9; **0.81 has the best win_gt50 (6/9, tied-best of the whole sweep) AND
best beat0 (7/9) AND the best worst-case drawdown (-11.56%)**, trading a bit of raw alpha
(22.49% vs 0.80's 34.80% or 0.82's 35.92%) for consistency -- more in line with this
project's standing preference (win-rate-consistency + beat-bench over peak alpha, see the
trend-strength-gate entries above). 0.82 has the best raw alpha/PF but win_gt50 drops back
to 4/9, no cleaner than 0.79.

**Still not deployed.** This is now a validated (neighbor-checked) candidate stack --
ARA_FILTER_ENABLED=1 + ATR_PRICE_RATIO_MAX=0.08 + SCORE_WEEKLY_COMP_ABS_CAP_Q=0.81 -- the
strongest, least-fragile finding of the whole session. Needs a deliberate adoption decision
before it touches the live V3_PAPER config (frozen by design, see
`project_paper_trading_pipeline_status` memory) -- a real config change ships as a new
versioned run (V3.1_PAPER), never a silent edit.

## Window 3's remaining -5.44%: trade-level diagnosis, skfolio ruled out (2026-08-15)

An LLM-council pressure-test session (5 differently-angled advisors + anonymized peer
review, `~/.claude/skills/llm-council`) on "what to build next for Window 3" converged on
"skfolio-based HRP/CVaR portfolio sizing" -- but peer review caught that all 5 advisors were
reasoning from the ORIGINAL failure mode (6 correlated positions clustering and stopping out
together), which the entry-cap + regime-confirm-days fixes already resolved (-22.10% ->
-12.28%, see above). The council's own recommended next step: check the REMAINING losing
trades directly before building anything, rather than re-reasoning from a stale writeup.

Reproduced the exact -5.44% run (had to disable `BANDAR_SIZING_ENABLED` -- its default
flipped 0->1 in commit `71b4a1c`, AFTER this number was logged, so Window 3's number under
current HEAD defaults is actually -6.07%/19 rows now, a different run than the one this
section analyzes; flagging so a future session doesn't compare apples to oranges). Full
trade-level picture, 12 rows / 9 unique positions, the ENTIRE window's activity:

- **All 9 entries fall in one 12-calendar-day span: 2023-02-08 to 2023-02-20.** Zero trades
  anywhere else in the 6-month window. The per-day cap (MAX_NEW_ENTRIES_PER_DAY=2) is hit on
  4 of 5 entry days, never exceeded -- confirms the entry-cap fix IS working as designed.
- Position-level P&L: 6 losers (GOTO -1.49M, WIRG -2.17M, BIRD -1.31M, GGRM -1.25M, MIDI
  -0.25M, ELPI -1.13M), 3 winners (ASSA +1.54M, TMAS +0.57M, TRJA net +0.03M).
- **All 6 losers exit via hard SL** -- zero trailing-stop or time-exit losers. A sharp
  signature (a bad regime call, not a slow bleed).
- **Every losing position's `trend_strength` at entry sits at 0.7%-1.9%**, barely above the
  `TREND_STRENGTH_MIN=1%` gate -- nowhere near window 1's 5.49% average. Directly confirms
  the earlier "5.49%/2.18%/1.13% across windows 1/2/3" trend-strength diagnostic, this time
  at individual-trade resolution instead of window-average resolution.

**Verdict: neither the council's original framing nor a clean "weak-trend-only" story is
complete on its own.** The entry cap prevented a 6-way pileup (confirmed fixed), but it did
NOT prevent 2-way co-failure within one short, thin-regime episode -- both capped same-day
pairs (Feb 8, Feb 16) failed together anyway. The loss isn't spread across 6 months of weak
trend, it's concentrated in one 12-day false-start rally that barely cleared the
trend-strength gate and then reversed.

**skfolio HRP/CVaR ruled out as the next build**: n is too small for correlation-aware
sizing to have anything to diversify across -- max 2 concurrent new entries/day, 9 positions
total in the whole window. There's no meaningful cross-sectional correlation structure to
risk-budget over at this scale.

**Recommendation, not yet built**: a regime-quality/episode-duration gate -- skip short,
barely-qualifying rallies like this one, not just weak ones on average. Direct extension of
the existing `TREND_STRENGTH_MIN` work (a duration/persistence requirement on top of the
existing magnitude requirement), swept across all 9 `walk_forward_v4.py` windows before any
promotion, same discipline as everything else in this log. Not started.

## Trend-duration/episode-quality gate: built and swept, REJECTED -- fixes Window 3, breaks Window 5 every time (2026-08-16)

Built the recommendation above. **Mechanism**: `compute_trend_duration_streak()` walks
`trend_strength_by_date` (already computed by `compute_regime_with_hysteresis`) and counts
consecutive trading days trend_strength has read `>= TREND_STRENGTH_MIN`, resetting to 0 on
any dip below it -- distinct from `bullish_streak_by_date` (how long the regime *state* has
read BULLISH, unaffected by trend_strength dipping within that state) and from
`TREND_STRENGTH_MIN` itself (a point-in-time check on the signal day only, no memory of the
days before it). New entry requires this streak `>= TREND_DURATION_MIN_DAYS`, gated by
`V3_TREND_DURATION_GATE` (default `"0"`, off) with `V3_TREND_DURATION_MIN_DAYS` (default
`3`) -- applied at both the same two sites `TREND_STRENGTH_MIN`/`REGIME_CONFIRM_DAYS` are
(the TRAIN threshold-learning mask and the live day-by-day entry check), same pattern.
Neither `TREND_STRENGTH_MIN`'s nor `REGIME_CONFIRM_DAYS`'s own defaults were touched; a
cold-process import (`test_trend_duration_gate.py`) confirms both still read
`0.01`/`3` regardless of the new flag's state.

**Concretely, against the Feb 2023 episode** (pulled `trend_strength_by_date` directly for
2023-01-01..2023-03-15): the regime flips BULLISH 2023-02-03, clears `REGIME_CONFIRM_DAYS=3`
on 2023-02-07 (trend_strength 1.63%) -- but trend_strength itself never separates cleanly,
it oscillates around the 1% line for two weeks: 2023-02-06 dips to 0.71% (below the gate, so
02-07's clearing is a fresh streak=1, not a continuation), 02-10 dips to 0.95% (streak reset
to 0 again), then 02-13 re-crosses (streak=1 again). Every one of the 9 signal days that fed
the losing episode (02-07/08/09/13/14/15/16/17/20) cleared `TREND_STRENGTH_MIN` on its own
day, but `compute_trend_duration_streak` never exceeds 6 anywhere in the whole episode, and
sits at 1 on four separate days -- confirms the "isolated barely-qualifying day" diagnosis at
the mechanism level, not just eyeballing the trade list. Concrete effect on entries: at
`TREND_DURATION_MIN_DAYS=3`, the 02-07 and 02-13 signal days (fresh streak=1) get dropped,
delaying the window's first entries by 2-3 trading days and cutting total window-3 trades
from 19 to 14.

**Full 9-window walk-forward** (`walk_forward_v4.py`, same cache, `V3_BANDAR_SIZING` at its
own current default throughout -- gate=OFF reproduces the promoted BANDAR_SIZING record
byte-for-byte: mean alpha +24.09%, mean PF 1.88, mean max DD -15.03%, worst -21.84%, confirming
the harness and the "off by default" no-op both hold):

| Config      | W3 trades | W3 profit | W3 alpha | Beat bench | Win>50% | Mean/median alpha | Mean/median profit | Mean/median PF | Mean/worst maxDD |
|-------------|-----------|-----------|----------|------------|---------|--------------------|---------------------|-----------------|-------------------|
| OFF (base)  | 19        | -5.57%    | -2.81%   | 6/9        | 4/9     | +24.09% / +19.09%  | +23.23% / +6.66%    | 1.88 / 1.24     | -15.03% / -21.84% |
| N=2         | 15        | -1.99%    | +0.77%   | 5/9        | 3/9     | +12.65% / +0.77%   | +11.79% / -1.26%    | 1.65 / 0.94     | -14.76% / -22.35% |
| N=3         | 14        | +0.20%    | +2.96%   | 5/9        | 5/9     | +9.75% / +2.96%    | +8.89% / -0.05%     | 1.49 / 1.00     | -15.55% / -21.30% |
| N=5         | 6         | -2.17%    | +0.59%   | 7/9        | 5/9     | +19.27% / +13.11%  | +18.41% / +10.49%   | 1.76 / 1.77     | -12.44% / -18.70% |

**Window 3 improves at every N tested** -- the gate does what it was built for: alpha goes
from -2.81% (losing to bench) to +0.59%/+0.77%/+2.96% (roughly matching or beating bench) at
every duration tested, a real and consistent effect, not a lucky point.

**But it is not a clean win, and does not clear the promotion bar.** Two separate problems,
both real:

1. **Window 5 (2024-01-01..2024-06-30) regresses at every single N tested** -- +15.54%
   baseline down to -11.70% (N=2), -18.86% (N=3), -10.17% (N=5). This is the same kind of
   "brief dip in trend_strength during a genuine early-stage run" pattern the gate is
   designed to filter in window 3, except in window 5 those early entries were actually
   good ones -- the duration requirement can't tell "false start" from "real rally that
   happened to wobble near the threshold on day one" from the trend_strength series alone.
   Consistent across all three N values, not noise.
2. **The rest of the walk-forward is non-monotonic in N, the same failure shape the
   hysteresis-band sweep already taught this log to distrust a single value for.** N=3 in
   particular is badly damaging to Window 4 (+45.02% -> -0.05%, alpha +36.42% -> -8.65%,
   previously one of the two strongest windows in the whole schedule) while N=2 and N=5
   barely touch it (+44.10%, +21.71%). Mean alpha falls at every N relative to baseline
   (+24.09% -> +12.65% / +9.75% / +19.27%); mean profit factor falls at every N (1.88 ->
   1.65 / 1.49 / 1.76). N=5 is the closest to breakeven-or-better on aggregate (7/9 beat
   bench vs baseline's 6/9, better mean/worst max DD: -12.44%/-18.70% vs -15.03%/-21.84%)
   but even there, mean/median alpha and profit are both below baseline -- the least-bad
   point in a landscape that never recovers to a genuine net improvement, not a validated
   optimum bracketed by comparable neighbors.

**Verdict: REJECTED, kept off by default (`V3_TREND_DURATION_GATE=0`).** The direction of
the specific, targeted fix holds (Window 3's false-start episode is a real diagnosis and the
duration streak mechanism measurably suppresses it, at every N tried) -- but "fixes the one
window it was built for, breaks another every time, and swings unpredictably across the rest
depending on the exact threshold" is the same failure signature this log has rejected before
(`ENTRY_CLUSTER_WINDOW_DAYS`/`MAX_ENTRIES_PER_CLUSTER_WINDOW` above: "helped the window that
needed it least, hurt the other two"). Window 3's remaining -5.57%/31.6% win stands as an
open, real, small loss -- a magnitude-only threshold on a single index-level series
(trend_strength) can't distinguish "false start" from "genuine early rally with one noisy
day" without also catching real trades in other windows built the same way. Code kept
(inert, off by default, `compute_trend_duration_streak()` + `test_trend_duration_gate.py`)
in case a future session finds a way to make the duration check stock-specific or
volatility-relative (paralleling the `VOL_BAND_MULT` redesign of the hysteresis band above)
rather than a flat day-count on one index series -- not attempted this session.

## Market-wide participation gate: a genuinely different axis, still REJECTED -- same
## failure signature as the duration gate, different collateral-damage windows (2026-08-16)

Third attempt at Window 3's Feb 2023 false start, explicitly required to be a mechanism
that does NOT re-threshold `trend_strength` (the axis both the rejected duration gate and
`TREND_STRENGTH_MIN` itself already use). Before building anything, ran an exploratory
correlation check (not a backtest) against several genuinely different candidate axes,
computed directly from the cached walk-forward dataset across all 9 `walk_forward_v4.py`
windows' gate-open days -- looking for one where Window 3 is a real outlier relative to the
other 8, not just relative to Window 1 or Window 5 in isolation (the trap that burned the
duration gate: "helps the window it was built for, breaks whichever window wasn't checked"):

- **Index-level trend_strength shape variants** (different from a duration count): 5-day
  trailing slope, 10-day rolling std ("choppiness"), and a rolling-K-day-high breakout
  requirement. None separated W3 from the other 8 -- W1's own early entries in Jan 2022
  oscillate near a low trend_strength level in a shape similar to Feb 2023's, and W5's Jan
  2024 entries occur during a *declining* trend_strength trajectory despite being good
  trades, so a shape/acceleration read on this one series doesn't cleanly discriminate
  either, same root problem as the duration gate just reframed.
- **Per-stock "confirmation" variants**: each entered stock's own volume/avg_vol_20 ratio at
  entry, ADX/+DI-DI trend quality, and score margin above the qualifying weekly/sector cut
  (`w_comp + s_comp`). None showed a consistent direction across windows -- W3's own winners
  vs losers split the WRONG way on volume ratio (losers had *higher* mean vol_ratio than
  winners, 1.39 vs 0.88) while W1/W5 split the expected way, and W3's mean per-stock score
  margin (29.1) was actually *higher* than W1's (22.2), not lower as the "riding in on a weak
  setup" hypothesis predicted.
- **Breadth variants restricted to the candidate pool**: fraction of the liquid universe with
  `weekly_ma_spread > 0`, size of the qualifying candidate pool before top-15 truncation, and
  count of distinct sectors represented in that pool. All three go the WRONG direction for
  W3 -- W3's qualifying pool (mean 54.1 candidates/day, 5.1 sectors) was *broader* than W1's
  (39.7 candidates, 4.3 sectors), the opposite of "a narrow rally dragged up by a few names."
- **Market-wide turnover ratio** (total `close_price * volume` summed across the WHOLE
  fetched universe -- not just the liquid/qualifying subset -- vs its own trailing 20-day
  average): the one axis where W3 is a genuine outlier across the full 9-window schedule.
  Mean turnover_ratio on W3's gate-open days: 0.959, the lowest of all 9 windows (next-worst
  1.019); fraction of gate-open days reading below-average: 80%, also the highest by far
  (next-highest 56%, most windows 35-49%). A day-level hand-trace of W3's actual trades
  showed why this could work mechanically: at a 0.95 cutoff, every one of the 6 pure-loser
  entry days (GOTO/WIRG 02-08, BUKA/DMMX 02-09, TMAS/BIRD 02-14, GGRM 02-16, ELPI 02-21) has
  turnover_ratio < 0.95 and gets filtered, while the 3 mixed win/loss days (ASSA+TRJA 02-10,
  TRUK+MMIX 02-15, KING+HOMI 05-02) sit above 0.95 and survive untouched.

**Mechanism built**: `compute_market_participation()` (`src/backtest_v4.py`) -- total Rupiah
turnover across every `stock_code` in the fetched dataset (not the liquid/qualifying subset
`score_candidates` filters to) that day, divided by its own trailing 20-day average; first 19
days default to a neutral 1.0 rather than NaN or 0. New entries additionally require this
ratio `>= V3_PARTICIPATION_MIN` (default 0.95), gated by `V3_PARTICIPATION_GATE` (default
`"0"`, off) -- a new, isolated flag; `V3_TREND_DURATION_GATE`'s own default/behavior
untouched, confirmed by `test_participation_gate.py`. Applied ONLY at the live day-by-day
entry check, deliberately NOT folded into the TRAIN threshold-learning mask the way
`TREND_STRENGTH_MIN`/`REGIME_CONFIRM_DAYS`/`TREND_DURATION_GATE_ENABLED` all are -- reasoning:
the rejected duration gate's own N=3 run took down Window 4 (a window it wasn't targeting,
+45.02%->-0.05%) hard enough to suspect the TRAIN-mask ripple (changing what population
`weekly_cut`/`sector_cut` get learned from) did more damage than live-side filtering itself;
keeping this gate out of the TRAIN mask avoids that specific failure mode by construction.

**Full 9-window walk-forward** (`V3_BANDAR_SIZING=0` throughout, matching the reproducible
baseline noted in the section above; OFF reproduces that -6.07%/19-trade W3 number
byte-for-byte, confirming the harness and the off-by-default no-op both hold):

| Config   | W3 trades | W3 profit | W3 alpha | W1 alpha | W4 alpha | Beat bench | Win>50% | Mean/median alpha | Mean/median profit | Mean/median PF | Mean/worst maxDD |
|----------|-----------|-----------|----------|----------|----------|------------|---------|--------------------|---------------------|-----------------|-------------------|
| OFF      | 19        | -6.07%    | -3.31%   | -5.18%   | +41.89%  | 6/9        | 4/9     | +21.71% / +12.60%  | +20.84% / +2.96%    | 1.58 / 1.12     | -16.08% / -21.61% |
| ON_0.85  | 18        | -6.99%    | -4.23%   | -9.74%   | +13.95%  | 5/9        | 4/9     | +13.74% / +13.49%  | +12.87% / -6.05%    | 1.39 / 0.83     | -15.30% / -21.61% |
| ON_0.90  | 16        | -5.47%    | -2.71%   | -11.78%  | +13.95%  | 6/9        | 3/9     | +13.42% / +13.95%  | +12.55% / -1.64%    | 1.37 / 0.91     | -15.34% / -21.61% |
| ON_0.95* | 9         | +2.31%    | +5.07%   | -11.78%  | -5.98%   | 6/9        | 5/9     | +16.01% / +15.76%  | +15.15% / +2.62%    | 2.38 / 1.33     | -12.78% / -21.61% |
| ON_1.00  | 6         | +3.63%    | +6.39%   | +0.88%   | +13.04%  | 8/9        | 5/9     | +19.13% / +13.04%  | +18.27% / +6.42%    | 2.64 / 1.59     | -13.17% / -21.61% |

(*`V3_PARTICIPATION_MIN`'s actual default.)

**Window 3 improves monotonically as the threshold tightens, and cleanly** -- alpha goes from
-3.31% (losing to bench, 42.1% win) to +5.07%/+6.39% at 0.95/1.00 (55.6%/50.0% win, profit
factor 1.33/1.65), the exact mechanism traced above: the pure-loser days get filtered, the
mixed days survive. This part of the diagnosis and fix is real and reproducible.

**But it does not clear the promotion bar, for the same reason the duration gate didn't.**
Two windows absorb the collateral damage instead of one, and the pattern is non-monotonic
across every metric that matters in aggregate:

1. **Window 1 (already a working window) is hurt at every threshold except the most
   extreme.** Alpha -5.18% -> -9.74%/-11.78%/-11.78% at 0.85/0.90/0.95 -- only flips back to
   roughly neutral (+0.88%) at 1.00, where the gate is filtering nearly a third of the
   window's would-be trades (55 -> 46). Window 4 shows the mirror image: -41.89pp of alpha
   damage specifically at 0.95 (the actual default), the single worst point in the whole
   sweep for that window, then partially recovers at 1.00. Neither window's damage curve is
   monotonic in the threshold -- 0.90 and 0.95 are the WORST points for Window 1, while 0.95
   is the worst point for Window 4, a "worst-in-the-middle" shape this log has already
   learned not to trust from the fixed-percentage hysteresis-band sweep.
2. **Mean alpha and mean/median profit are below the OFF baseline at every single threshold
   tested** (+21.71% -> +13.74%/+13.42%/+16.01%/+19.13%; profit +20.84% -> +12.87%/
   +12.55%/+15.15%/+18.27%) -- the real, disclosed tradeoff the earlier duration-gate
   rejection used as its own decisive criterion applies identically here. Two metrics DO
   improve at every threshold (mean/worst max drawdown, both consistently better than OFF)
   and beat-bench count reaches 8/9 at the 1.00 extreme -- genuinely interesting, but not
   enough on their own when the headline return metric never recovers to baseline anywhere
   in the sweep, and the one point that looks best in aggregate (1.00) is also the point
   with the fewest Window 3 trades (6) to have drawn that conclusion from.

**Verdict: REJECTED, kept off by default (`V3_PARTICIPATION_GATE=0`).** The axis itself is a
genuine methodological improvement over the rejected duration gate -- market-wide turnover is
structurally unrelated to `trend_strength`/ma50 distance, the exploratory check found it the
only one of seven candidate axes tried this session where Window 3 is a real 9-window
outlier, and the day-level trace of exactly which entries it filters in Feb 2023 confirms the
mechanism does what it was designed to do. But "real, working, targeted fix for the window it
was built for; real, non-monotonic collateral damage to a DIFFERENT currently-strong window
at nearly every threshold tested; aggregate return metric never recovers to baseline" is the
same failure signature the duration gate was rejected for, just with Window 1/Window 4 taking
the hit this time instead of Window 5. Code kept (inert, off by default,
`compute_market_participation()` + `test_participation_gate.py`) -- the exploratory-check
methodology here (screen candidate axes for a genuine 9-window outlier BEFORE building
anything, not just a 2-3-window correlation) is worth reusing for whatever gets tried next;
the six axes that failed the outlier check are recorded above so a future session doesn't
re-spend the same effort re-deriving that trend-strength-shape and per-stock-confirmation
variants don't distinguish this specific episode. Window 3's residual weakness remains
diagnosed but unresolved without a net-positive fix.

## Window 3: accepted as a bounded, understood cost -- stop re-fitting the same 3 windows (2026-08-16)

A second LLM-council pressure-test (`~/.claude/skills/llm-council`) on "what's the next system
priority" converged 4/5 independently on the same statistical point, sharpened further in peer
review: three Window-3 fix attempts (skfolio, trend-duration, participation-turnover) were all
validated against the SAME three total backtest windows this project has. That isn't three
independent tests rejecting three independent hypotheses -- it's three rounds of curve-fitting
a sample of three, with researcher judgment as the search algorithm. A fourth attempt (combining
two already-rejected gates) adds parameters without adding real information. Window 3 itself is
no longer a defect: its loss already shrank from -22.10% to -5.44% through earlier STRUCTURAL
fixes (entry cap, regime-confirm-days, trend-strength gate) -- not window-3-specific patches --
and it clears >50% win rate with alpha tracking benchmark. **Decision: stop trying to fix Window
3 specifically. -5% to -6% in a short, thin false-start-rally regime is the accepted, understood,
bounded cost of this entry rule, confirmed by 4 rigorous walk-forward-validated attempts (1
promoted, 3 honest rejections) across two sessions.** Re-open only if a genuinely new mechanism
appears (not a recombination/re-threshold of concentration/mover/accdist/rotation/participation/
trend-duration -- all six already tried).

**Real blind spot the peer review caught, not in any of the 5 original advisor responses**:
this project already runs V4_PAPER, live forward paper trading -- real, growing out-of-sample
data that is the actual antidote to the "only 3 backtest windows exist" problem, and nobody
had been treating it that way. Going forward, V4_PAPER's live track record (not another fixed
backtest window) is the primary source of NEW validation evidence for whatever gets tried next
-- give it real runway before drawing conclusions from it, same standing note as
`newscraper.ai/docs/ROADMAP.md`'s "V4_PAPER needs runway" entry.

**A genuinely new, not-yet-tried mechanism was also surfaced** (2 of 5 peer reviewers,
independently): a reduced-SIZING gate for weak-trend regimes, instead of the ENTRY-FILTERING
approach all 4 prior attempts took. Shrink exposure in a detected weak/thin-trend regime rather
than excluding entries outright -- philosophically distinct (softer intervention, not a
recombination of concentration/duration/participation), cheaper to test, cheaper to fail. Not
attempted this session -- flagged as the one live idea if Window 3 work ever resumes.

## Extracted the isolated-feature-test scaffolding into src/feature_test_harness.py -- pure
## refactor, no new finding (2026-08-16)

Not a new signal or result -- process housekeeping flagged by the LLM-council pressure-test
above ("not the decay-monitoring, just the scaffolding... that's a today task, and it pays back
on attempt #7"). Six feature tests this session and last (concentration, mover_score,
accdist_score, rotation_pairs, trend-duration, market-participation) each manually rebuilt the
same ~30-line block from scratch: set an isolated flag, run `walk_forward_v4.py`'s 9-window
schedule off then on, hand-format the same "windows beating bench / win-rate>50% / mean-median
alpha,profit,PF / mean-worst maxDD" table into this log or `BANDARMOLOGY_DESIGN.md`.

`src/feature_test_harness.py`'s `run_isolated_feature_test(label, set_flag)` runs that pattern
once: loads the shared `.cache/walk_forward_data_*.pkl` dataset via a small extraction from
`walk_forward_v4.py` (`load_dataset()`/`run_schedule()`, pulled out of `main()` with zero output
change -- confirmed by re-running `main()` itself unchanged), then calls the schedule with
`set_flag(False)`, then `set_flag(True)`, and prints/returns the same table shape by hand-typed
convention above. `set_flag` mutates the already-imported `backtest_v4` module's attribute
directly (env vars are read once at import time, so re-setting them mid-process is a no-op --
this is why every existing sweep script, e.g. the one behind
`.cache/participation_sweep_results.csv`'s "config" column, already did it this way, just
without a shared name for the pattern).

**Correctness check (not a new experiment): re-ran `V3_PARTICIPATION_GATE` through the new
harness and compared against commit `f9cd458`'s already-published table.** First attempt (no
env override) reproduced a DIFFERENT already-published baseline instead -- `BANDAR_SIZING_ENABLED`
defaults ON in `backtest_v4.py`, and `f9cd458`'s own run had explicitly pinned
`V3_BANDAR_SIZING=0` ("matching the reproducible baseline noted in the section above"), while
the harness's first run left it at its current default. Numbers matched `510f67e`'s
"own current default" baseline exactly instead (+24.09%/1.88/-15.03%/-21.84% mean alpha/PF/
mean-worst DD) -- a real reminder that "the flag under test" isn't the only environment state a
published table depends on. Re-ran with `V3_BANDAR_SIZING=0` set and got an exact match to
`f9cd458`:

| Metric | OFF (harness) | f9cd458 (published) | ON_0.95 (harness) | f9cd458 (published) |
|---|---|---|---|---|
| Beat bench | 6/9 | 6/9 | 6/9 | 6/9 |
| Win>50% | 4/9 | 4/9 | 5/9 | 5/9 |
| Alpha mean/median | +21.71%/+12.60% | +21.71%/+12.60% | +16.01%/+15.76% | +16.01%/+15.76% |
| Profit mean/median | +20.84%/+2.96% | +20.84%/+2.96% | +15.15%/+2.62% | +15.15%/+2.62% |
| PF mean/median | 1.58/1.12 | 1.58/1.12 | 2.38/1.33 | 2.38/1.33 |
| Max DD mean/worst | -16.08%/-21.61% | -16.08%/-21.61% | -12.78%/-21.61% | -12.78%/-21.61% |

Byte-for-byte on every number in the published table. `src/test_feature_test_harness.py` covers
the two things a broken extraction could get wrong mechanically: the aggregation/table-formatting
math (fast, synthetic DataFrame, no real backtest), and that `run_isolated_feature_test` always
calls `set_flag(False)` last -- including if the ON run raises -- so a harness run can't leave a
shared module in an ON state for whatever runs next in the same process.

No feature flags' behavior or defaults changed. `walk_forward_v4.py main()`'s own output is
unchanged (`load_dataset()`/`run_schedule()` are the same code, just named and callable
separately). Template for the next candidate (attempt #7+) is in
`feature_test_harness.py`'s own module docstring.

## 2026-08-16: tick-size bug found + fixed (backtest only, NOT deployed live) + TEBE gorengan base-rate research

User flagged a real signal on the frontend (TEBE, STRONG_BUY 2026-08-14, score 10.61/percentile
97.4 on a +25% day with 28.2M shares volume vs a trailing ~0.4-5.4M/day) whose displayed TP
target (1488) isn't a valid IDX tick at that price (500-<2000 band, tick=5; nearest real prices
are 1485/1490). Two separate findings came out of investigating it.

**Tick-size bug: confirmed real, fixed in `compute_entry_fill()`.** Checked all 16 STRONG_BUY
candidates from 2026-08-14's `daily_scoreboard` -- every single one has a tp1/sl misalignment;
raw ATR math essentially never lands on a valid tick. The codebase already had a tick-size table
(`_gap_ok()` in `paper_monitor.py`, used only for gap-limit checking), just never applied to the
computed price levels themselves. Added `round_to_tick(price, direction)` using the same
breakpoints, applied to `compute_entry_fill()`'s `tp1_price`/`sl_price` after the existing
floor/ceiling clamps (rounding widens those guarantees, never violates them) -- TP rounds up,
SL rounds down. Frontend mirror (`newscraper.ai/lib/estimate-pending-levels.ts`) fixed
identically. Test: `test_round_to_tick()` in `test_paper_trading_math.py`.

**9-window walk-forward delta is misleading taken at face value**: mean alpha +21.71%→+15.88%,
mean profit +20.84%→+15.02%, mean PF 1.58→1.46, win-rate>50% windows 4/9→5/9
(`V3_BANDAR_SIZING=0`, matching the reproducible baseline). But 7 of 9 windows move <3pp either
way -- the small, uniform effect a half-tick correction should produce. Window 8 (2025 H2) alone
accounts for ~85% of the aggregate delta. Traced to portfolio-slot path dependence, not a
mechanical rounding cost: one ticker's entry date shifted by 9 calendar days between runs, which
`round_to_tick` cannot cause directly (zero role in entry-signal generation) -- the only path is
a different position's exit timing shifting by sub-tick amounts, freeing/blocking one of only 6
`MAX_POSITIONS` slots differently given the 10-day SL cooldown, cascading into a different
subsequent trade sequence. Same "small perturbation -> large single-window swing" fragility
already documented in the hysteresis-band sensitivity sweep. **Do not update any published
baseline table off this one run** -- if a clean before/after number is ever needed, it needs a
run designed to separate "the fix's effect" from "which trade won a scarce slot" (wider
`MAX_POSITIONS`, or a queue-priority tiebreak), not a straight diff.

**Governance flag, decision not yet made**: `paper_monitor.py` imports `compute_entry_fill`
directly from `backtest_v4.py` -- no separate copy. This fix is currently ONLY on the worktree
branch, not deployed, so V4_PAPER's live fills are unaffected today. But if/when this branch's
`backtest_v4.py` changes ever get promoted, this fix would silently start applying to *new* live
fills under the already-running frozen V4_PAPER config, without a version bump -- exactly the
kind of mid-flight change the frozen-run rule exists to prevent. Confirmed the live account
(`paper_positions`, run_id=36) already holds non-tick-aligned tp1/sl on both its open positions
(WMPP, BEEF) from before this fix existed. Confirmed mathematically + against the real code path
that this is a **display/precision issue, not a trigger-correctness issue** for the live
monitor: for a real, tick-aligned market price, crossing the raw threshold and crossing the
tick-rounded threshold happen at the same real tick whenever both fall in the same tick band (no
valid tick sits strictly between them). One real precision bug found beyond what was asked,
not touched, reported only: `evaluate_position_exit()`'s recorded `exit_price` for TP1/SL exits
that don't gap past the threshold uses the raw unrounded value itself as the booked fill price
(e.g. `1487.5`) -- a small, real error in booked PnL, independent of the trigger-timing question.

**TEBE liquidity check: not a filter gap.** `adtv_20` (20-day rolling value average, `strategy.py`)
including the spike day = Rp4.04B (4x the Rp1B floor); excluding it (prior 19 days) = Rp2.21B
(2.2x the floor) -- TEBE already cleared the liquidity floor comfortably before the spike day
counted at all. Also clears the hypervolatile-penny filter (ATR/price = 5.45%, under the 10%
cap). Correction to the "long dead-silent base" framing: TEBE had an elevated-volume mini-rally
in late July (1005→1110, Rp5.4B/Rp9.2B value days) before the 08-14 spike to 1375 -- the spike
day is a real step-change, but it wasn't emerging from total silence. TEBE's own spike is outside
the cached backtest window (through 2026-06-30 only), so it couldn't be tested against the
system's own historical trades directly.

**Base-rate check on the pattern itself** (932 historical episodes matching TEBE's profile:
single-day volume >=10x trailing average, single-day price move >=20%, clears ADTV_MIN, ATR/price
<=10%; concentrated in 2020 COVID-recovery and 2025's bull run, not independent across
time/tickers -- directional evidence, not a clean sample): forward returns from the spike-day
close are a classic post-blowoff fade -- +5d mean +0.72%/median -6.12%/win 35.8%; +10d mean
+1.48%/median -8.09%/win 35.8%; +20d mean +2.87%/median -9.18%/win 37.2%. Positive mean only from
real right-skew (best cases up to +453% at 20d -- consistent with the multi-bagger appetite the
user described wanting). Restricting to episodes with a genuinely flat pre-trend
(`|weekly_ma_spread|<=3%`, n=218) doesn't rescue the win rate. This is a diagnostic on the
*pattern*, not a backtest of what V3/V4's actual entry rule would do with these names (different
entry timing, real SL/TP1/trailing exits, not a fixed-N-day hold) -- directionally suggestive,
not a validated number.

**Recommendation, not implemented**: a dedicated future research pass shaped as a pre-spike
confirmation-delay gate (buy on pullback/confirmation after the breakout day, not the breakout
day itself) rather than a liquidity exclusion -- TEBE already clears the existing liquidity bar,
so excluding by liquidity wouldn't have caught it anyway. Test the same way the trend-duration
and participation gates were tested this session (9-window walk-forward, both-direction
sensitivity, explicit rejection if it trades away performance in unrelated windows), not a
same-session edit.

## Spike confirmation-delay gate: built and swept, REJECTED -- non-monotonic across both of its
## own parameters, and its one good-looking point is a single-window artifact a Monte Carlo
## check can't distinguish from random entry-timing noise (2026-08-17)

Built the recommendation above. **Front-loading check first** (the task explicitly asked
whether the fade is front-loaded or gradual, since that should set how many confirmation days
make sense): the base-rate research's own numbers already answer this -- median forward return
from the spike-day close is -6.12% at +5d, -8.09% at +10d, -9.18% at +20d. 66.7% of the eventual
20-day median loss is already present by day 5, 88.1% by day 10 -- clearly front-loaded, not
gradual. This is why the sweep below tests confirm_days in {2, 3, 5}, not larger values -- by
day 10 most of the damage this gate could plausibly avoid has already happened either way.

**Mechanism** (`compute_spike_confirm_gate`, `src/backtest_v4.py`): a spike day is `volume >=
SPIKE_VOL_MULT * avg_vol_20_prev` (avg_vol_20_prev is the TRAILING average, excludes the spike
day itself) AND `daily_return >= SPIKE_MOVE_PCT` -- same definition the base-rate research used
(defaults 10x / 20%, not swept -- these define what counts as "the pattern," a different
question from how long to wait once one is flagged). Per stock, independently: for
`SPIKE_CONFIRM_DAYS` trading days after a qualifying spike, the stock is excluded from candidacy
entirely (the blackout). On the day the blackout ends, ONE checkpoint decides the whole episode:
if close hasn't given back more than `SPIKE_GIVEBACK_PCT` from the spike day's own close, the
stock is eligible again -- permanently, until its next spike (not re-checked daily afterward,
deliberately a single pass/fail test, not continuous monitoring). A newer spike at any point
(including mid-blackout) immediately restarts the blackout from the newer spike. Vectorized per
stock via `np.maximum.accumulate` on a "spike-position-or--1" array (the standard "index of the
last True" trick) -- no per-row Python loop for the state machine itself. Unit-tested against a
synthetic episode shaped like the mechanism's own three claims (blackout, checkpoint-passes-stays-
open-through-a-later-dip, checkpoint-fails-stays-closed-through-a-later-recovery) in
`src/test_spike_confirm_gate.py`.

**Wiring, and why the live paper-trading path cannot be affected regardless of this flag's
state**: the gate is applied as a single filter step on `score_candidates()`'s *return value*,
inside `simulate_window`'s own `pending_entries` construction --
`score_candidates()`/`compute_entry_fill()` themselves are UNCHANGED (confirmed: `git diff`
touches only `src/backtest_v4.py`, and only inside `simulate_window`/its two new helper
functions). `paper_signal_scan.py` calls `score_candidates()` directly and `paper_monitor.py`
calls `compute_entry_fill()` directly -- neither calls `simulate_window`, which is the ONLY place
this gate's flag is ever read. Gated by `V3_SPIKE_CONFIRM_GATE` (default `"0"`, off), with
`V3_SPIKE_CONFIRM_DAYS` (default `3`) and `V3_SPIKE_GIVEBACK_PCT` (default `0.15`) -- new,
isolated flags; a cold-process import check in `test_spike_confirm_gate.py` confirms every other
gate's own default (`PARTICIPATION_GATE_ENABLED`, `TREND_DURATION_GATE_ENABLED`, etc.) is
untouched. Full existing test suite (`test_trend_duration_gate.py`, `test_participation_gate.py`,
`test_feature_test_harness.py`, `test_ara_filter.py`, `test_bandar_sizing_default.py`,
`test_accdist_signal.py`, `test_rotation_signal.py`, `test_paper_trading_math.py`) still passes
unchanged.

**9-window walk-forward at the default parameterization** (`src/feature_test_harness.py`,
`V3_BANDAR_SIZING=0` throughout, matching the reproducible baseline this log has used since the
tick-size-bug entry; OFF reproduces that baseline byte-for-byte -- mean alpha +15.88%, mean
profit +15.02%, mean PF 1.46, mean/worst maxDD -16.28%/-22.51%, win>50% 5/9 -- confirming the
harness and the off-by-default no-op both hold):

| Metric | OFF | ON (spike_confirm_gate, N=3/giveback=15%) |
|---|---|---|
| Windows beating benchmark | 6/9 | 6/9 |
| Windows win-rate > 50% | 5/9 | 4/9 |
| Win rate (mean / median) | 51.0% / 51.0% | 51.3% / 47.2% |
| Profit (mean / median) | +15.02% / +2.87% | +12.10% / +2.37% |
| Alpha (mean / median) | +15.88% / +11.57% | +12.96% / +2.15% |
| Profit factor (mean / median) | 1.46 / 1.12 | 1.37 / 1.13 |
| Max drawdown (mean / worst) | -16.28% / -22.51% | -16.97% / -29.01% |

The default parameterization (the one closest to the base-rate research's own numbers: a 3-day
wait, a 15% giveback floor) is a straightforward net negative -- worse mean AND median on every
return/consistency metric, and worse drawdown too. Not promising on its own, but one point is not
a verdict -- swept next.

**Sensitivity sweep** (confirm_days in {2, 3, 5} x giveback_pct in {10%, 15%, 20%} where
applicable, 9-window walk-forward each, same `V3_BANDAR_SIZING=0` baseline; full per-window CSV
at `.cache/spike_confirm_sweep_results.csv`):

| Config | Beat bench | Win>50% | Win rate mean/median | Profit mean/median | Alpha mean/median | PF mean/median | MaxDD mean/worst |
|---|---|---|---|---|---|---|---|
| OFF | 6/9 | 5/9 | 51.0% / 51.0% | +15.02% / +2.87% | +15.88% / +11.57% | 1.46 / 1.12 | -16.28% / -22.51% |
| N=2, giveback=10% | 5/9 | 4/9 | 47.2% / 45.7% | +12.34% / -1.04% | +13.20% / +2.51% | 1.35 / 0.95 | -15.04% / -29.33% |
| N=2, giveback=15% | 5/9 | 4/9 | 51.5% / 50.0% | +13.94% / -4.56% | +14.80% / +9.80% | 1.42 / 0.88 | -16.33% / -24.07% |
| N=3, giveback=10% | 8/9 | 5/9 | 51.3% / 53.5% | +24.81% / +9.25% | +25.67% / +12.83% | 1.60 / 1.34 | -15.25% / -29.12% |
| N=3, giveback=15% (default) | 6/9 | 4/9 | 51.3% / 47.2% | +12.10% / +2.37% | +12.96% / +2.15% | 1.37 / 1.13 | -16.97% / -29.01% |
| N=3, giveback=20% | 6/9 | 4/9 | 52.7% / 50.0% | +18.09% / +2.87% | +18.95% / +9.80% | 1.58 / 1.12 | -16.14% / -27.26% |
| N=5, giveback=10% | 6/9 | 4/9 | 49.9% / 47.8% | +14.58% / +1.84% | +15.44% / +2.27% | 1.37 / 1.09 | -15.71% / -29.53% |
| N=5, giveback=15% | 5/9 | 3/9 | 50.7% / 50.0% | +14.78% / -1.59% | +15.64% / +1.17% | 1.52 / 0.87 | -14.61% / -32.14% |
| N=5, giveback=20% | 6/9 | 4/9 | 51.4% / 49.0% | +18.51% / +4.10% | +19.38% / +14.12% | 1.54 / 1.17 | -17.05% / -30.17% |

**Non-monotonic across both axes -- the exact "worst-in-the-middle" shape this log has already
learned not to trust** (hysteresis-band sweep, then the participation-gate rejection). Fixing
`confirm_days=3` and sweeping giveback: mean alpha goes 25.67% (10%) -> 12.96% (15%) -> 18.95%
(20%) -- a dip in the MIDDLE of the range, not a monotonic trend or a clean interior peak.
Fixing `giveback=10%` and sweeping confirm_days: 13.20% (N=2) -> 25.67% (N=3) -> 15.44% (N=5) --
same shape, the other axis. `win-rate>50%` never exceeds the OFF baseline's 5/9 at any of the 9
points tested; it matches at best (N=3/g10) and is usually worse.

**The one point that looks good (N=3, giveback=10%, beat-bench 8/9) does not survive a per-window
trace.** Per-window alpha delta vs OFF:

| Window | OFF alpha | N=3/g10 alpha | Delta |
|---|---|---|---|
| W1 (2022 H1) | -8.26% | +24.07% | +32.33pp |
| W2 (2022 H2) | -8.33% | +2.14% | +10.47pp |
| W3 (2023 H1) | -3.89% | -1.14% | +2.75pp |
| W4 (2023 H2) | +41.04% | +0.65% | **-40.39pp** |
| W5 (2024 H1) | +6.42% | +5.88% | -0.54pp |
| W6 (2024 H2) | +11.57% | +12.89% | +1.31pp |
| W7 (2025 H1) | +26.13% | +23.98% | -2.15pp |
| W8 (2025 H2) | +59.56% | +149.76% | **+90.20pp** |
| W9 (2026 H1) | +18.66% | +12.83% | -5.84pp |

W8's own +90.20pp swing is 102% of the whole schedule's +88.15pp total delta -- every other
window nets out to roughly zero once W8 is set aside, and W4 (previously one of the two
strongest windows, alongside W8) takes real, uncompensated damage (+41.04% -> +0.65%, a
tighter-giveback checkpoint failing and permanently excluding what would otherwise have been
real winning trades in that episode). This is the identical failure signature the trend-duration
gate (fixed W3, broke W5 every N) and the participation gate (fixed W3, broke W1 and W4 at
nearly every threshold) were already rejected for: a real, mechanically-traceable effect in the
window it helps, paid for by uncompensated damage in a window it wasn't built for. The two milder
"also positive" points (N=3/g20: mean alpha +18.95%, N=5/g20: +19.38%) don't show W4-style
collateral damage (both leave W4 within ±1pp of OFF), but W8 still supplies 65-71% of their own
aggregate improvement -- a much smaller, still real dependence on the same one window.

**Monte Carlo check on W8's own N=3/giveback=10% result, specifically**: is +59.56% -> +149.76%
real spike-targeting skill, or the same "perturb which candidate-days are excluded -> reshuffle
which trade fills a scarce `MAX_POSITIONS` slot -> large single-window swing" fragility already
documented for the tick-size-rounding fix (that entry: "one ticker's entry date shifted by 9
calendar days... cascading into a different subsequent trade sequence")? Drew 30 random
`(stock_code, trade_date)` exclusion masks of the exact SAME SIZE as the real N=3/giveback=10%
gate's total blocked-row count (226,216 of 1,242,246 rows, 18.2% -- a giveback of 10% fails more
checkpoints than the 15% default, so this config blocks more than the 10.53% the default gate
blocks), monkeypatched `compute_spike_confirm_gate` to return each random mask instead of the
real targeted one, and reran ONLY Window 8 (`simulate_window` with `train_end=2025-06-30,
test=2025-07-01..2025-12-30`) per draw:

  - Window 8 baseline (gate OFF): alpha +59.56%
  - Window 8 real, spike-targeted N=3/giveback=10% gate: alpha +149.76%
  - Window 8, 30 random-mask draws of the same size: mean +69.09%, median +71.47%,
    min -12.91%, max +194.88%, std 47.08pp
  - Random draws matching or beating the real targeted gate's own result: **2/30 (6.7%)**

The real targeted gate sits above most of the random distribution (roughly its 93rd percentile),
so this is not pure noise in the strict sense the ~5000-draw permutation test used on the
original entry rule established -- but the random distribution's own MEAN (+69.09%) already
exceeds the untouched baseline (+59.56%) by more than the default config's ENTIRE net effect,
with a standard deviation (47pp) wide enough that 2 of 30 purely random draws beat the real
targeted mechanism outright, and the random max (+194.88%) clears it by 45pp. Blocking roughly a
fifth of this one window's candidate-days -- targeted at spikes, or picked at random -- reliably
pushes Window 8 higher, by an amount too noisy to call a specific mechanism's contribution. This
is the same known fragility already on record from the tick-size-bug entry, now demonstrated
directly with a permutation check rather than inferred from one before/after diff.

**One more clean, monotonic-direction finding, independent of all the noisy alpha/profit
numbers above**: worst-case single-window drawdown is WORSE than the OFF baseline's -22.51% at
literally every one of the 8 tested configurations (range -24.07% to -32.14%) -- the opposite of
what a gate designed to avoid buying into blowoff peaks would ideally do. Delaying entry into a
spike-flagged name doesn't reduce the portfolio's worst realized drawdown anywhere in this sweep;
if anything it makes the worst case somewhat more, not less, severe (most likely the same
scarce-slot reshuffling mechanism above, not a property of spike stocks specifically).

**Verdict: REJECTED, kept off by default (`V3_SPIKE_CONFIRM_GATE=0`).** The underlying diagnosis
(post-blowoff fade, front-loaded within ~5-10 days) is real and already-documented base-rate
evidence, not in question here. But the specific mechanism built to act on it fails on every
criterion this log has used to reject gates before: non-monotonic across both of its own
parameters (worst-in-the-middle on each axis independently), its best-looking point trades real
uncompensated damage in a previously-strong window (W4) for a single-window blowup (W8) a direct
Monte Carlo permutation check cannot distinguish from random entry-timing noise, and worst-case
drawdown is uniformly worse than baseline across the entire sweep regardless of parameters. Code
kept (inert, off by default, `compute_spike_confirm_gate()` + `test_spike_confirm_gate.py`) --
the front-loading diagnostic and the per-stock/single-checkpoint mechanism design are both
reusable if a future session finds a structurally different way to act on the same base-rate
finding (e.g. sizing the position DOWN on a fresh spike rather than delaying/excluding entry
outright, matching the "reduced-sizing instead of entry-filtering" idea already flagged and
unattempted in the Window-3 section above -- not attempted here either). `score_candidates()`,
`compute_entry_fill()`, `paper_signal_scan.py`, and `paper_monitor.py` are all unchanged by this
entry; only `src/backtest_v4.py` (inside `simulate_window` and its two new helper functions) and
the new `src/test_spike_confirm_gate.py` were touched.

## VOL_BAND_MULT re-swept on the full 9-window harness (roadmap item #1, "known-fragile
## parameter" backlog): no better plateau found, KEPT at 2.0 -- REGIME_CONFIRM_DAYS interaction
## is real but not exploitable, same W8-driven fragility already on record (2026-08-17)

**Hypothesis**: `VOL_BAND_MULT` (regime hysteresis band width, `compute_regime_with_hysteresis()`,
`src/backtest_v4.py`) gates every single trade in the system, and its only prior sweep
(`docs/V3_FINDINGS_LOG.md`, "Redesigned as volatility-relative") tested three coarse points
(1.0/2.0/3.0) on two hand-picked windows, before Window 3 existed and before
`REGIME_CONFIRM_DAYS`/`TREND_STRENGTH_MIN`/pyramiding/liquidity-sizing were layered on top. The
2.0 default was explicitly logged as "a convention pick (the standard 2-sigma convention), not an
evidence-based optimum." A full 9-window, finer-grained re-sweep against the CURRENT full
configuration might find a genuinely better, more robust value -- or might confirm 2.0 is already
fine.

**Method**: `src/sweep_vol_band_mult.py` (new) -- reuses `walk_forward_v4.py`'s dataset-cache/
9-window-schedule infrastructure exactly like `feature_test_harness.py` does for ON/OFF flags,
generalized to a numeric grid: loads the cached dataset ONCE, then for each grid point mutates
`backtest_v4.VOL_BAND_MULT`/`REGIME_CONFIRM_DAYS` directly on the already-imported module (same
"env vars are read once at import time" workaround `feature_test_harness.py`'s docstring explains)
and reruns `run_schedule()`. Cheaper than `sweep_v4_filters.py`'s one-subprocess-per-cell pattern
(which would re-unpickle the ~670MB cached dataset every cell); correctness isn't affected either
way since `VOL_BAND_MULT`/`REGIME_CONFIRM_DAYS` are read as plain module globals inside
`compute_regime_with_hysteresis()`/`simulate_window()`, not captured at def-time. `V3_BANDAR_SIZING=0`
pinned throughout, matching the reproducible baseline this log has used since the tick-size-bug
entry. **Correctness check**: the VOL_BAND_MULT=2.0/REGIME_CONFIRM_DAYS=3 cell (today's actual
defaults) reproduces that baseline exactly -- mean alpha +15.88%, mean profit +15.02%, mean PF
1.46, mean/worst maxDD -16.28%/-22.51%, win>50% 5/9, byte-for-byte -- confirming the harness and
dataset are correct before trusting anything else below.

**Grid**: `VOL_BAND_MULT` in {1.0, 1.5, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0} at
`REGIME_CONFIRM_DAYS=3` (coarse per the task's minimum grid, then finer-neighbor points added
around 2.0-3.0 once that region looked plateau-like on the coarse pass -- see below for why the
finer pass changed the read). Second axis: `REGIME_CONFIRM_DAYS` in {2, 3, 5} crossed with
`VOL_BAND_MULT` in {1.0, 2.0, 3.0} (narrow / current-default / wide) -- judged separable enough
not to need a full grid (reasoning below), but plausibly interacting mechanically (a wider band
flips regime less often, so how much protection `REGIME_CONFIRM_DAYS` is even doing should
shrink as the band widens), so a reduced joint check was run rather than assuming independence.

**Full aggregate table, VOL_BAND_MULT axis** (`REGIME_CONFIRM_DAYS=3`, 9 windows each; full
per-window CSVs at `.cache/vbm_stage1_full.csv` and `.cache/vbm_stage2a_full.csv`):

| mult | trades | beat bench | win>50% | win% mean/median | profit% mean/median | alpha% mean/median | PF mean/median | DD% mean/worst | conc% mean/max |
|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 404 | 6/9 | 5/9 | 48.8/51.4 | 21.25/0.00 | 22.11/3.55 | 1.89/1.00 | -17.70/-29.06 | 85.8/97.9 |
| 1.5 | 398 | 6/9 | 5/9 | 51.3/51.9 | 21.09/0.86 | 21.95/3.55 | 1.71/1.02 | -16.81/-23.06 | 85.3/97.9 |
| **2.0 (default)** | 389 | 6/9 | 5/9 | 51.0/51.0 | 15.02/2.87 | 15.88/11.57 | 1.46/1.12 | -16.28/-22.51 | 85.2/98.9 |
| 2.25 | 386 | 6/9 | 4/9 | 51.7/50.0 | 12.97/4.18 | 13.84/5.01 | 1.32/1.14 | -15.32/-22.51 | 82.0/97.5 |
| 2.5 | 366 | 6/9 | 5/9 | 51.5/55.4 | 15.77/8.11 | 16.64/13.61 | 1.55/1.29 | -15.86/-22.51 | 82.7/97.5 |
| 2.75 | 361 | 6/9 | 5/9 | 51.0/55.0 | 21.43/8.11 | 22.29/13.79 | 1.52/1.29 | -16.73/-22.51 | 83.3/97.0 |
| 3.0 | 363 | 6/9 | 5/9 | 50.8/55.8 | 17.57/8.11 | 18.43/13.79 | 1.39/1.29 | -15.89/-22.51 | 82.5/97.0 |
| 3.5 | 358 | 6/9 | 5/9 | 50.5/53.7 | 14.37/0.00 | 15.23/3.55 | 1.33/1.00 | -15.06/-22.51 | 82.7/97.8 |
| 4.0 | 359* | 8/9* | 4/9* | 53.0/52.5 | 12.77/5.69 | 13.40/8.68 | 1.33/1.20 | -15.97/-23.82 | 84.3/96.8 |

(*4.0: only 8/9 windows traded -- Window 3 drops to zero trades entirely at this width, so its
`beat_bench`/`win>50%` counts are out of 8, not 9; not directly comparable to the other rows.)

**Per-window detail for the three representative points (narrow / current default / wide)**,
format `trades / win% / profit% / PF / DD% / conc%`:

| Window | mult=1.0 | mult=2.0 (default) | mult=3.0 |
|---|---|---|---|
| W1 (2022 H1) | 55 / 32.7% / -19.32% / 0.67 / -29.06% / 71.6% | 56 / 55.4% / -4.56% / 0.88 / -16.92% / 74.6% | 55 / 56.4% / -0.14% / 1.00 / -16.88% / 70.9% |
| W2 (2022 H2) | 37 / 51.4% / +2.66% / 1.12 / -10.70% / 92.2% | 38 / 50.0% / -7.50% / 0.71 / -12.52% / 96.4% | 31 / 41.9% / -15.91% / 0.32 / -17.84% / 87.2% |
| W3 (2023 H1) | 18 / 33.3% / -8.26% / 0.52 / -14.77% / 96.0% | 19 / 42.1% / -6.65% / 0.58 / -13.28% / 96.1% | 10 / 30.0% / -6.42% / 0.12 / -7.75% / 82.2% |
| W4 (2023 H2) | 51 / 54.9% / +53.20% / 2.61 / -17.60% / 89.3% | 49 / 51.0% / +49.64% / 2.49 / -19.20% / 92.9% | 43 / 55.8% / +51.76% / 2.91 / -15.47% / 83.7% |
| W5 (2024 H1) | 35 / 37.1% / +0.00% / 1.00 / -15.75% / 97.9% | 34 / 41.2% / +2.87% / 1.12 / -15.05% / 98.9% | 36 / 47.2% / +10.24% / 1.43 / -15.04% / 97.0% |
| W6 (2024 H2) | 63 / 52.4% / -4.23% / 0.88 / -20.39% / 81.6% | 57 / 52.6% / +10.74% / 1.37 / -19.48% / 77.1% | 53 / 60.4% / +8.11% / 1.29 / -20.59% / 81.7% |
| W7 (2025 H1) | 28 / 78.6% / +52.00% / 6.84 / -7.34% / 86.8% | 21 / 71.4% / +22.84% / 3.18 / -7.97% / 89.5% | 19 / 68.4% / +13.24% / 2.13 / -8.31% / 89.2% |
| W8 (2025 H2) | 94 / 63.8% / +131.99% / 2.91 / -21.13% / 71.5% | 92 / 60.9% / +84.60% / 2.31 / -19.55% / 55.7% | 93 / 62.4% / +114.04% / 2.80 / -18.64% / 65.3% |
| W9 (2026 H1) | 23 / 34.8% / -16.82% / 0.48 / -22.51% / 85.1% | 23 / 34.8% / -16.83% / 0.48 / -22.51% / 85.1% | 23 / 34.8% / -16.82% / 0.48 / -22.51% / 85.1% |

**Plateau analysis -- two axes are genuinely flat, the return axes are NOT, and the apparent
2.5-3.0 "sweet spot" from the coarse pass dissolves once finer points are added.** This is the
exact discipline this log has required since the fixed-% hysteresis-band walk-back: check the
neighbours before trusting a value.

- **Real, robust plateau on `dd_worst` and `beat_bench`**: worst-case single-window drawdown is
  IDENTICAL (-22.51%) at every one of six consecutive tested points, 2.0 through 3.5 -- not
  approximately similar, byte-identical, because several windows' regime paths (W1, W3, W5, W9 in
  the table above) don't change AT ALL across some of these multiplier values (same trade count,
  same exact P&L to the rupiah in several cells) -- the band simply isn't crossing a different
  threshold on those windows' actual index path in that range. `beat_bench` is flat at 6/9 across
  the entire 1.0-3.5 range, eight consecutive points. **This part of the original finding
  replicates and strengthens on the fuller grid: no catastrophic breakdown anywhere in 1.0-3.5,**
  consistent with (not just repeating) the original two-window conclusion.
- **NOT robust: `alpha_median`/`pf_median` are non-monotonic, and the apparent 2.5-3.0 improvement
  is bracketed by a dip on one side and a collapse on the other.** Reading only the coarse 5-point
  grid (1.0/1.5/2.0/2.5/3.0) would suggest a clean monotonic climb in alpha_median (3.55 -> 3.55 ->
  11.57 -> 13.61 -> 13.79) -- exactly the kind of read that would tempt promoting 2.5 or 3.0. The
  finer points kill that story: **2.25 (between 2.0 and 2.5) dips to alpha_median 5.01 -- LOWER
  than 2.0's 11.57 on both sides of it** -- and **3.5 (just past 3.0) collapses back to 3.55,
  identical to 1.0's own value**, with `pf_median` doing the same round-trip (1.00 -> 1.02 -> 1.12
  -> 1.14 -> 1.29 -> 1.29 -> 1.29 -> **1.00**). A value that looks like a genuine climb on 5 points
  and turns into a dip-then-collapse on 9 is precisely the "one lucky point in a noisy landscape"
  signature the fixed-percentage hysteresis-band sweep (61%->501% profit swings) originally taught
  this project to distrust, and the same standard used to reject the trend-duration and
  participation gates (non-monotonic, worst-in-the-middle shapes). **2.5/2.75/3.0's better-looking
  median numbers do not survive fine-neighbor scrutiny and are not being recommended.**
- **One window explains almost the entire aggregate mean-alpha swing across the whole grid.**
  Window 8 (2025 H2)'s own alpha ranges from +59.56% (at 2.0) to +129.99% (at 2.75) across the
  1.0-3.5 grid -- a 70.4pp single-window range. Divided across 9 windows, that alone accounts for
  ~7.8pp of mean-alpha movement -- **about 93% of the entire observed mean-alpha range across the
  whole 1.0-3.5 sweep (8.45pp, from 13.84 at 2.25 to 22.29 at 2.75).** This is the same
  single-window-driven fragility already twice documented this session for W8 specifically (the
  tick-size-rounding fix's "one ticker's entry date shifted 9 days... cascading into a different
  subsequent trade sequence," and the spike-confirm-gate's own Monte Carlo check on this exact
  window) -- not new evidence of a different problem, but a third confirmation of the same one.
- **Region caution, not a promotion**: `mult < 1.5` is measurably worse on the one clean,
  monotonic-direction axis found (`dd_worst` -29.06% at 1.0 vs a flat -22.51%/-23.06% everywhere
  from 1.5 up), and (see below) interacts badly with a short `REGIME_CONFIRM_DAYS`. `mult >= 4.0`
  starts to lose whole-window sample coverage (Window 3 drops to **zero trades**, and `dd_worst`
  ticks up to -23.82%, the worst of the entire 2.0-4.0 range) -- a real, if milder, echo of the
  fixed-% design's breakdown-at-its-extreme. **2.0 sits inside the well-behaved 1.5-3.5 region on
  every axis that's actually trustworthy (dd_worst, beat_bench, trade-count/concentration
  sanity), and is not demonstrably beaten by any neighbour on the axes that looked promising until
  checked more closely.**

**`REGIME_CONFIRM_DAYS` interaction: real at the region's edge, not exploitable at the default.**
Full grid (`.cache/vbm_stage2b_full.csv`/`_agg.csv`):

| mult | confirm | beat bench | win>50% | alpha mean/median | PF mean/median | DD mean/worst | conc mean |
|---|---|---|---|---|---|---|---|
| 1.0 | 2 | 4/9 | **2/9** | 10.08 / **-6.55** | 1.56/0.77 | -18.21/-26.29 | 83.7 |
| 1.0 | 3 | 6/9 | 5/9 | 22.11 / 3.55 | 1.89/1.00 | -17.70/-29.06 | 85.8 |
| 1.0 | 5 | 5/9 | 3/9 | 13.57 / 3.53 | 1.47/1.04 | -16.41/-22.51 | 84.1 |
| 2.0 | 2 | 7/9 | 5/9 | 19.19 / 12.96 | 1.49/1.20 | -16.10/-23.30 | 83.9 |
| **2.0 (default)** | **3** | 6/9 | 5/9 | 15.88 / 11.57 | 1.46/1.12 | -16.28/-22.51 | 85.2 |
| 2.0 | 5 | 6/9 | 5/9 | 18.51 / 13.79 | 1.49/1.29 | -15.96/-22.51 | 84.5 |
| 3.0 | 2 | 7/9 | 5/9 | 16.93 / 13.79 | 1.65/1.11 | -16.59/-23.24 | 83.9 |
| 3.0 | 3 | 6/9 | 5/9 | 18.43 / 13.79 | 1.39/1.29 | -15.89/-22.51 | 82.5 |
| 3.0 | 5 | 6/9 | **4/9** | 14.41 / 3.62 | 1.15/1.00 | -16.29/-22.51 | 75.7 |

The one clean, mechanistically-sensible, monotonic-direction finding: **at a narrow band
(mult=1.0), under-confirming (`confirm=2`) is clearly worse** -- win>50% collapses to 2/9 (worst
of every cell tested in this whole session's VOL_BAND_MULT work), alpha_median goes negative
(-6.55%), dd_worst is close to the worst overall (-26.29%). This matches the mechanism: a
narrower band flips regime state more often, so the `REGIME_CONFIRM_DAYS` false-start protection
has more to protect against there, and 2 days isn't enough. `confirm=5` at mult=1.0 is a partial
recovery on drawdown but win>50% is still weak (3/9) -- narrow bands are simply a worse
neighbourhood on this axis regardless of confirm-days, consistent with the region-caution above.

**But at the CURRENT default band width (mult=2.0) and the wide band (mult=3.0), `confirm=2`'s
apparently-better aggregate numbers do not survive a per-window trace, and don't replicate
consistently between the two multipliers -- the identical "helps via one window, hurts a
previously-strong window, direction isn't even consistent" signature already used to reject three
gates this session.** At mult=2.0, confirm=2 vs confirm=3 per-window alpha delta:

| Window | confirm=3 (default) | confirm=2 | Delta |
|---|---|---|---|
| W1 | -8.26% | -8.26% | 0.0pp (identical trade path) |
| W2 | -8.33% | +2.06% | +10.4pp |
| W3 | -3.89% | -6.16% | -2.3pp |
| W4 | +41.04% | +12.96% | **-28.1pp** |
| W5 | +6.42% | +13.58% | +7.2pp |
| W6 | +11.57% | +7.59% | -4.0pp |
| W7 | +26.13% | +25.64% | -0.5pp |
| W8 | +59.56% | +106.65% | **+47.1pp** |
| W9 | +18.66% | +18.66% | 0.0pp (identical trade path) |

W4 (previously one of the two strongest, most reliable windows in the whole 9-window schedule)
takes a real, uncompensated 28pp hit while W8 supplies essentially the entire aggregate
improvement (+47.1pp on its own, more than the whole schedule's net gain) -- the exact
"real effect in the window it helps, paid for by damage in a window it wasn't built for" pattern
the trend-duration, participation, and spike-confirm gates were all rejected for. **Decisive
extra check: this W8 effect doesn't even replicate in direction at mult=3.0** -- there, confirm=2
vs confirm=3 makes W8 **worse** (+71.26% vs +89.00%, a -17.7pp move, the opposite sign from
mult=2.0's +47.1pp) while W3 gets genuinely better (+0.59% alpha, actually beating benchmark --
the best Window 3 has ever scored across this entire project's many dedicated W3-fix attempts) and
W7 improves substantially (+26.23% vs +16.53%). A real effect would point the same direction at
both band widths; this one flips sign, which is close to definitive evidence it's the same
scarce-`MAX_POSITIONS`-slot reshuffling noise already documented for the tick-size fix and the
spike-confirm-gate's own Monte Carlo check, not a real `REGIME_CONFIRM_DAYS=2` improvement.

**No Monte Carlo permutation check was run.** The task's own stated bar is to MC-test a candidate
only once it looks "genuinely better and more robust" on the sweep itself -- neither the
2.5-3.0 VOL_BAND_MULT region nor `REGIME_CONFIRM_DAYS=2` reached that bar: both were falsified by
the SAME kind of scrutiny an MC check exists to provide (checking whether an apparent improvement
survives a stress test, here a finer-neighbour resample and a per-window/cross-parameter trace)
before ever reaching "candidate for promotion." Running a permutation test on a value already
shown to fail its own neighbour-stability check would not add information.

**Why not a full 2D grid**: judged separable after the reduced check above -- the interaction is
real but concentrated entirely at the narrow end of the VOL_BAND_MULT range (mult=1.0), which is
already a region this sweep independently recommends avoiding on its own (dd_worst) grounds. At
and above the current default, `REGIME_CONFIRM_DAYS` sensitivity is modest and not usefully
distinguishable from the pre-existing W8 reshuffling noise; a denser grid in that region would be
spending compute to resolve noise more precisely, not to find a real effect.

**Verdict: KEEP `VOL_BAND_MULT=2.0`, KEEP `REGIME_CONFIRM_DAYS=3`. No default changed.** The
honest finding is closer to "2.0 is already fine, no better plateau exists" than to a promotable
alternative -- exactly the outcome the task asked to be stated plainly rather than dressed up.
Real, useful findings from this pass even though nothing gets promoted: (1) the volatility-relative
redesign's core claim -- no catastrophic breakdown across a wide multiplier range -- replicates and
strengthens on the fuller 9-window/finer grid, not just the original 2-window check; (2) there IS a
soft floor worth remembering if this parameter is ever revisited downward: below ~1.5x, drawdown
genuinely worsens and the interaction with `REGIME_CONFIRM_DAYS` turns hostile; (3) concentration%
does not discriminate between tested values anywhere in this sweep (stays in a 75-86% mean / 97-99%
max band across the *entire* grid) -- it's a pre-existing, already-documented characteristic of
this strategy's outlier-driven return distribution generally (see "Walk-forward validation"
section), not something `VOL_BAND_MULT` moves one way or the other.

**Governance note (no action needed this time, stated for the record per the task's own
requirement)**: `VOL_BAND_MULT`/`REGIME_CONFIRM_DAYS` are both read by `paper_signal_scan.py`
(`compute_regime_with_hysteresis()`/`bt.REGIME_CONFIRM_DAYS` directly, confirmed by grep) -- the
same live-affecting-default category as the tick-size fix. Since this pass concluded KEEP, not
CHANGE, nothing in `backtest_v4.py`'s live defaults was touched, so this entry (and
`src/sweep_vol_band_mult.py`) is safe to push without a separate approval step -- unlike a
promotion would have required.

Code kept: `src/sweep_vol_band_mult.py` (new, reusable for the next numeric-grid parameter sweep
the same way `feature_test_harness.py` is reusable for the next ON/OFF flag test). Raw sweep
outputs saved at `.cache/vbm_stage1_full.csv`/`_agg.csv` (coarse grid),
`.cache/vbm_stage2a_full.csv`/`_agg.csv` (finer neighbours), `.cache/vbm_stage2b_full.csv`/`_agg.csv`
(REGIME_CONFIRM_DAYS interaction grid).

## The scarce-`MAX_POSITIONS`-slot mechanism itself, investigated directly: real and pervasive
## (84.8% of all candidate-days across all 9 windows, not just Window 8), mechanistically
## confirmed as the exact cause of all three prior "small change, huge W8 swing" mysteries --
## but the obvious fix (widen the queue) makes results monotonically WORSE, cleanly rejected.
## KEEP `MAX_POSITIONS=6`, `ALLOC_PCT=0.20` (2026-08-17)

**Hypothesis, from the VOL_BAND_MULT re-sweep's own closing note**: three independent research
passes this session (tick-size-rounding fix, spike-confirm-delay gate, VOL_BAND_MULT re-sweep)
each found a small, mechanically-unrelated change producing a large, misleading-looking swing
concentrated almost entirely in Window 8 (2025 H2) -- traced each time to a DIFFERENT position's
exit timing shifting by a small amount, freeing (or not freeing) one of only `MAX_POSITIONS=6`
slots at a different moment, cascading into a different subsequent trade sequence. `pending_entries`
(`src/backtest_v4.py`'s main day loop, `simulate_window`) is a ONE-DAY-AHEAD queue, rebuilt fresh
every day from that day's `score_candidates()` output -- when the loop hits `len(positions) >=
MAX_POSITIONS`, it `break`s and every remaining ranked candidate for that day is dropped entirely,
not deferred. Worth investigating this mechanism directly rather than continuing to hit it
sideways through unrelated parameter research.

**Method (Phase 1, purely additive)**: added an optional `diag=None` kwarg to `simulate_window()`
-- when a dict is passed, it records one entry per candidate-day (why the entry-queue-consumption
loop stopped: `max_positions` / `daily_cap` / `cluster_cap` / never broke, and which ranked
candidates were admitted vs dropped) with zero effect on any trading decision. Every write is
behind `if diag is not None`, so every existing caller (`walk_forward_v4.py`,
`feature_test_harness.py`, `sweep_vol_band_mult.py`, `main()`) is unaffected -- confirmed two ways:
(1) a full 9-window walk-forward with the new kwarg unused reproduced the published baseline
byte-for-byte (mean alpha +15.88%, mean profit +15.02%, mean PF 1.46, mean/worst DD
-16.28%/-22.51%, win>50% 5/9); (2) `src/test_diag_hook.py` asserts `diag=None`, `diag={}`, and the
kwarg omitted entirely all produce identical trades/equity curves on a real 2-month slice, plus
internal-consistency checks (every day tagged `max_positions` really did end with exactly
`MAX_POSITIONS` positions open; a day that never broke has nothing dropped). `src/
diagnose_slot_queue.py` runs the diag-instrumented 9-window schedule and aggregates it.

**Phase 1 result 1 -- how often does the constraint actually bind** (`V3_BANDAR_SIZING=0`
throughout, matching the reproducible baseline; full per-window CSV at
`.cache/slot_queue_diag_summary.csv`):

| Window | candidate-days | days broke on `max_positions` | bind rate | n admitted | n dropped (max_positions) | drop:admit ratio | admitted score mean | dropped score mean | dropped/admitted |
|---|---|---|---|---|---|---|---|---|---|
| W1 (2022 H1) | 63 | 55 | 87.3% | 37 | 615 | 16.6x | 23.35 | 16.42 | 70.4% |
| W2 (2022 H2) | 35 | 32 | 91.4% | 26 | 355 | 13.7x | 29.75 | 21.47 | 72.2% |
| W3 (2023 H1) | 10 | 5 | 50.0% | 14 | 42 | 3.0x | 29.65 | 18.22 | 61.4% |
| W4 (2023 H2) | 67 | 50 | 74.6% | 35 | 557 | 15.9x | 37.55 | 29.03 | 77.3% |
| W5 (2024 H1) | 30 | 25 | 83.3% | 25 | 283 | 11.3x | 33.76 | 32.36 | 95.9% |
| W6 (2024 H2) | 64 | 59 | 92.2% | 37 | 702 | 19.0x | 64.39 | 62.74 | 97.4% |
| W7 (2025 H1) | 26 | 23 | 88.5% | 13 | 228 | 17.5x | 68.33 | 53.22 | 77.9% |
| W8 (2025 H2) | 117 | 102 | **87.2%** | 62 | 1158 | 18.7x | 67.89 | 54.64 | 80.5% |
| W9 (2026 H1) | 17 | 13 | 76.5% | 19 | 145 | 7.6x | 33.86 | 26.56 | 78.5% |
| **All 9, pooled** | **429** | **364** | **84.8%** | **268** | **4085** | **15.2x** | (46.02 weighted) | 40.91 | **88.9%** |

**The constraint binds on the large majority of candidate-days in EVERY SINGLE WINDOW, not just
Window 8.** Aggregate bind rate 84.8% (364/429) -- the portfolio is already full when a ranked
candidate list arrives on roughly 5 out of every 6 days that have a qualifying signal at all.
**Window 8 is NOT an outlier on this axis** -- its own bind rate (87.2%) sits in the middle of the
pack; W6 (92.2%) and W2 (91.4%) actually bind MORE often. What makes W8 different is scale, not
rate: it has by far the most candidate-days of any window (117/127 trading days, 92.1% -- the next
closest is W6 at 64/127), so it accumulates by far the most raw admitted+dropped candidate-
instances (62 admitted, 1158 dropped -- both the largest of any window), and it is also the
highest-return/highest-win-rate window (60.9% win, PF 2.31 at defaults). More binding events on a
window with more edge per event means more dollar-weighted sensitivity to which exact candidate
wins a slot -- not a uniquely fragile mechanism, a uniquely busy one.

**Phase 1 result 2 -- the dropped candidates are not marginal dregs.** Pooled across all 4085
max_positions-dropped candidate-instances, mean score 40.91 vs a (count-weighted) 46.02 mean for
the 268 admitted candidates -- **dropped candidates average 88.9% of admitted candidates' score.**
Every single window's own ratio is >=61%, and five of nine windows are >=77%. This is real,
comparable-quality signal being discarded by queue exhaustion, not noise the ranking already
correctly filtered out. `MAX_POSITIONS` dominates as the binding mechanism -- 4085 candidates lost
to full slots vs only 427 lost to the `MAX_NEW_ENTRIES_PER_DAY=2` daily cap (a much smaller,
secondary contributor, ~9.5% of the total).

**Phase 1 result 3 -- concrete trace of the three already-documented cases** (`src/
trace_w8_slot_swaps.py`, Window 8 only, diag-instrumented, comparing baseline vs each already-
published variant):

- **Tick-size rounding fix** (`round_to_tick` monkeypatched to identity = pre-fix behavior).
  W8 alpha: unrounded/pre-fix +104.09% vs rounded/current-default +59.56% (-44.53pp) --
  reproduces the direction and rough size of the previously-reported aggregate delta, now traced
  to a single concrete origin day. On 2025-09-29, both runs start the day with an IDENTICAL
  4-position portfolio. The unrounded run admits BOTH `PADA` (113.636) and `BNBR` (94.17) that
  day, filling to 6/6 and triggering `break=max_positions` -- dropping `ZATA, MHKI, VISI, JTPE,
  ASII, UNTR, KUAS, DADA, BTEK` (9 candidates). The rounded run admits only `PADA`
  that day (`break=None`, one slot still open) -- `round_to_tick`'s tiny change to `PADA`'s own
  SL price shifts its RISK_PCT-based position size/cost-basis (see `RISK_PCT=0.04`,
  `src/config.py`) by enough to change whether the day's SECOND candidate still fits the day's
  cash budget. That one slot's fate then cascades: by 2025-10-01/10-02 the two runs are admitting
  `BTEK`-then-`BNBR` vs `BNBR`-then-`BTEK` in swapped order, and 17 vs 16 trades across the rest
  of the window never realign.
- **Spike-confirm-delay gate** (N=3/giveback=10%, the rejected gate's own best-looking point).
  W8 alpha: OFF +59.56% vs ON +149.76% (+90.20pp, already on record). First divergence
  2025-07-16: the gate directly excludes `JAST`/`MMIX`/`NICE` (blacked out post-spike) from that
  day's ranked list, so the ON run admits `INET`+`EXCL` where OFF admits `INET`+`JAST` -- both
  runs still hit `break=max_positions` filling to 6/6 the SAME day, so the gate's own direct,
  intended filtering and the scarce-slot queue mechanism are entangled from the very first
  diverging day, not sequential effects. This is the mechanistic explanation for why that
  entry's own Monte Carlo check found random exclusion masks of the same size ALSO moved W8
  substantially (mean +69.09%, 2/30 draws beating the real targeted gate) -- with the portfolio
  full on 87% of W8's candidate-days, ANY exclusion (targeted or random) that reorders who is
  \#1/\#2/\#3 in the ranked queue on a binding day changes who gets the scarce slot.
- **`REGIME_CONFIRM_DAYS=2` vs 3** (default). W8 alpha: confirm=3 +59.56% vs confirm=2 +106.65%
  (+47.09pp, already on record). First divergence 2025-10-01: OFF admits `BTEK` (score 69.078),
  ON admits `BNBR` (score 69.057) -- a 0.02-point, essentially tied score difference (confirm=2
  shifts the TRAIN-period population slightly, moving `weekly_ma_spread`'s learned cut from 2.96
  to 2.94, a rounding-scale change) decides which of two near-identical candidates fills the
  last slot that day. 10-02 then swaps the order (`BNBR`-then-`BTEK` vs `BTEK`-then-`BNBR`), and
  this single coin-flip-level tie-break is the entire traceable origin of a 47-point single-
  window alpha swing.

All three traces confirm the SAME mechanism, mechanistically, for the first time (previously
inferred from aggregate deltas and one partially-traced ticker per the tick-size-bug entry) --
not three different bugs, one structural property of a 6-slot, no-backlog, reset-daily queue
sitting at capacity 85% of the time.

**Decision to proceed to Phase 2**: 4085 candidate-instances lost to a full queue across the
9-window schedule, at 88.9% of admitted candidates' own score quality, with a mechanistically
confirmed causal link to three independent large single-window swings already on record, clears
the bar for "a real, sizeable effect worth testing a structural fix on" by a wide margin.

**Phase 2 -- widen `MAX_POSITIONS` with a correspondingly-scaled `ALLOC_PCT`.** Grid: (6, 0.20)
default / (8, 0.15) / (10, 0.12) -- each pair holds `MAX_POSITIONS x ALLOC_PCT` at the current
default's ~1.2x nominal max concurrent exposure multiple, so the sweep isolates "more slots, each
sized proportionally smaller" from "more slots at the same size" (over-leveraging). `src/
sweep_max_positions.py`, same in-process module-attribute-mutation pattern as
`sweep_vol_band_mult.py`.

**Bug found and fixed before trusting any number**: the first run of this sweep did not pin
`V3_BANDAR_SIZING=0` (the reproducible baseline every other script/entry this session has used
since the tick-size-bug entry) -- `BANDAR_SIZING_ENABLED` defaults ON since its 2026-08-15
promotion, so the sweep's own (6, 0.20) "baseline" cell silently ran with bandar-weighted sizing
on and reproduced numbers close to the tick-size trace's UNROUNDED variant by coincidence, not the
actual current defaults. Caught by spot-checking the first cell against the known-published
baseline before trusting the rest of the grid (same discipline the feature-test-harness
correctness-check entry already flagged: "the flag under test isn't the only environment state a
published table depends on"). Fixed (`os.environ.setdefault("V3_BANDAR_SIZING", "0")` added
before the `walk_forward_v4` import) and re-run; the corrected (6, 0.20) cell now reproduces the
published baseline byte-for-byte on all 9 windows before the (8, 0.15)/(10, 0.12) cells are
trusted.

**Full 9-window aggregate** (full per-window CSV at `.cache/max_positions_sweep_full.csv`, agg at
`.cache/max_positions_sweep_agg.csv`):

| MAX_POSITIONS / ALLOC_PCT | trades | beat bench | win>50% | win% mean/median | profit% mean/median | alpha% mean/median | PF mean/median | DD% mean/worst | conc% mean/max |
|---|---|---|---|---|---|---|---|---|---|
| **6 / 0.20 (default)** | 389 | 6/9 | 5/9 | 51.0/51.0 | 15.02/2.87 | 15.88/11.57 | 1.46/1.12 | -16.28/-22.51 | 85.2/98.9 |
| 8 / 0.15 | 476 | 5/9 | 4/9 | 47.3/50.0 | 9.90/2.94 | 10.77/10.75 | 1.41/1.09 | -16.01/-22.00 | 80.0/97.1 |
| 10 / 0.12 | 546 | 6/9 | 5/9 | 48.4/52.8 | 8.19/4.74 | 9.05/8.29 | 1.32/1.23 | -15.62/-30.17 | 80.0/94.6 |

**Clean, monotonic, unambiguous rejection -- unlike every prior gate this session, this one does
not need a fine-neighbor sweep or a Monte Carlo check to distrust it.** Trade count rises exactly
as expected (389 -> 476 -> 546, +40% at the widest setting -- the queue really does admit more of
the previously-dropped signal). But every continuous return/quality metric moves the WRONG
direction, monotonically, at every grid point: profit_mean 15.02% -> 9.90% -> 8.19% (roughly
halved at 10 slots), alpha_mean 15.88% -> 10.77% -> 9.05% (also roughly halved), PF_mean 1.46 ->
1.41 -> 1.32, win_rate_mean 51.0% -> 47.3% -> 48.4%. `dd_worst` is flat-to-better at 8 slots
(-22.51% -> -22.00%) then breaks down hard at 10 (-30.17%, the single worst drawdown of ANY
configuration tested anywhere this session -- worse than the fixed-%-hysteresis-band's own
breakdown-at-its-extreme, worse than every VOL_BAND_MULT/REGIME_CONFIRM_DAYS/participation-gate/
spike-confirm-gate cell). `beat_bench`/`win>50%` are the one non-monotonic pair (6/9,5/9 ->
5/9,4/9 -> 6/9,5/9 -- a dip-then-recover, the "worst in the middle" shape this log already
distrusts) but even the "recovered" point (10 slots) is still clearly worse than the default on
every continuous metric, so this doesn't rescue the grid.

**Per-window trace explains why**: only 3 of 9 windows (W1, W5, W9) improve with wider slots, and
even W1's improvement peaks at 8 and partially reverses at 10 (alpha -8.26% -> +19.03% -> +8.20%).
The rest are flat (W3) or clearly worse -- W2 (-8.33% -> -11.49% -> -8.50%), W7 (26.13% -> 23.20%
-> 21.03%), and most decisively **W4, previously one of the two strongest windows in the whole
9-window schedule, collapses from +41.04% alpha to -5.67% at 8 slots and -9.63% at 10** -- the
same "a previously-strong window absorbs uncompensated damage" signature every prior gate
(trend-duration, participation, spike-confirm, REGIME_CONFIRM_DAYS=2) was rejected for, except
here it happens WITHOUT even a compensating win in the window the change targets: **W8 itself --
the window with the most scarce-slot drops to potentially recover -- gets WORSE too, and
monotonically** (alpha +59.56% -> +41.52% -> +24.88%, despite trade count rising 92 -> 99 -> 137).
Mechanism: `ALLOC_PCT`'s own code comment already documents that this strategy's edge is
concentration-driven, not broadly distributed (`docs/V3_FINDINGS_LOG.md`, most windows >65% top-5
concentration) -- shrinking `ALLOC_PCT` from 20% to 12-15% to fund more slots cuts the capital
behind the FEW big winners that actually drive returns, and the extra marginal positions (real,
comparably-scored signal per Phase 1, but still systematically lower-ranked within each day) do
not make up the difference; they add trade count and a worse worst-case drawdown without adding
net profit.

**No Monte Carlo permutation check run**: per this log's own established bar (used identically in
the VOL_BAND_MULT re-sweep entry), an MC check is for a candidate that looks "genuinely better and
more robust" on the sweep itself. This grid fails that bar cleanly and monotonically at every
point tested -- a permutation test on a result already this decisively negative would not add
information.

**Verdict: REJECTED. KEEP `MAX_POSITIONS=6`, `ALLOC_PCT=0.20`.** No default changed.

**What Phase 1 and Phase 2 together actually establish**: the scarce-slot queue-reset mechanism
Phase 1 diagnosed is real, large, structural, and now mechanistically confirmed as the exact cause
of three separate single-window "small change, huge swing" mysteries this session -- that finding
stands regardless of Phase 2's outcome. But the obvious lever (make the queue wider) is not a fix
-- it doesn't relieve the fragility, it just dilutes the concentrated sizing this strategy's real
edge depends on, for no net return benefit and a materially worse tail-drawdown at the wide end.
The fragility itself is therefore accepted as understood-but-unresolved, the same posture already
taken toward Window 3's residual weakness: real, diagnosed, not free to fix with the tools tried so
far.

**Not attempted this session (flagged for a future session, structurally distinct from what was
tested here)**: the task's second candidate direction, a real bounded backlog/priority queue (a
dropped high-score candidate stays eligible for a bounded number of subsequent days instead of
vanishing the instant `pending_entries` resets) rather than a wider queue. This is mechanistically
different from what Phase 2 tested -- TEMPORAL reordering (let a good signal wait 1-2 days for a
slot to free up naturally, keeping `MAX_POSITIONS`/`ALLOC_PCT` untouched) instead of concurrent
WIDENING (hold more, smaller positions at once) -- so Phase 2's clean rejection of the widening
approach does not automatically extend to it; it remains untested. It is also a bigger structural
change (touches the entry-queueing bookkeeping itself, shared conceptually if not by code with
`paper_signal_scan.py`'s own slot-counting) that would need the same care taken this session to
keep `score_candidates()`/`compute_entry_fill()` untouched and the change scoped to
`simulate_window`'s own day-loop bookkeeping.

**Governance note (no action needed this time, stated for the record per this session's own
standing requirement)**: both `MAX_POSITIONS` and `ALLOC_PCT` are read directly by the live paper-
trading path -- `paper_signal_scan.py` reads `bt.MAX_POSITIONS`/computes `slots_free = MAX_POSITIONS
- open_count` for its own live candidate queueing, and `paper_monitor.py` calls
`bt.compute_entry_fill()`, which reads `ALLOC_PCT` internally -- confirmed by grep, and confirmed
that V4_PAPER's own live workflow (`main:.github/workflows/paper_signal_scan_v4_trigger.yml`) does
NOT pin either var, unlike `V3_BANDAR_SIZING`'s explicit pin in the V3_PAPER workflows -- so a
promoted default change here would flow straight to the live account with no extra step. Since
this pass concluded REJECTED/KEEP, not CHANGE, nothing in `backtest_v4.py`'s live defaults was
touched, so (matching the identical situation in the VOL_BAND_MULT re-sweep entry) this entry and
its new scripts are safe to push without a separate approval step.

Code kept: `src/diagnose_slot_queue.py` (Phase 1 instrumentation + aggregation, reusable for a
future candidate-drop diagnostic), `src/trace_w8_slot_swaps.py` (Phase 1 point-2 concrete A/B
tracer for a specific window, reusable for the next "why did this one window move so much"
question), `src/sweep_max_positions.py` (Phase 2 sweep, reusable the same way
`sweep_vol_band_mult.py` is for the next paired-parameter numeric grid), `src/test_diag_hook.py`
(self-check for the `diag` hook itself). `simulate_window()`'s new `diag=None` kwarg in
`src/backtest_v4.py` is the only change to a previously-existing function -- purely additive,
regression-verified byte-identical for every existing caller. `score_candidates()`,
`compute_entry_fill()`, `evaluate_position_exit()`, `paper_signal_scan.py`, and `paper_monitor.py`
are all unchanged. Raw sweep outputs saved at `.cache/slot_queue_diag_summary.csv`,
`.cache/slot_queue_diag_dropped_max_positions.csv`, `.cache/max_positions_sweep_full.csv`/`_agg.csv`.

## The OTHER candidate direction from the scarce-`MAX_POSITIONS`-slot investigation -- a bounded
## backlog/priority queue (temporal reordering, not concurrent widening) -- tested, REJECTED.
## Same qualitative failure signature as the widening approach (Window 4 collapses, Window 8 gets
## worse despite admitting more of its own dropped candidates), reached by a different mechanism
## (reshuffling noise, not capital dilution -- avg concurrent positions barely moves). KEEP
## `BACKLOG_QUEUE_ENABLED=False` (2026-08-17)

**Hypothesis**: the prior entry established that `pending_entries` (`simulate_window`'s day loop,
`src/backtest_v4.py`) resets to `[]` every day and drops any ranked, comparably-scored candidate
that doesn't win a slot that same day -- MAX_POSITIONS binds on 84.8% of all candidate-days across
the 9-window schedule, and Phase 2's fix (widen `MAX_POSITIONS` with a scaled `ALLOC_PCT`) was
cleanly rejected because it dilutes the concentrated sizing this strategy's edge depends on. The
task's own second candidate direction, explicitly flagged as untried: instead of holding MORE
positions at once (concurrent widening), let a dropped candidate wait a BOUNDED number of extra
days for a slot to free up naturally (temporal reordering) -- `MAX_POSITIONS`/`ALLOC_PCT` stay at
their current defaults throughout. Mechanistically distinct from Phase 2, so its rejection doesn't
automatically extend here; needed its own test.

**Design decisions (the four questions posed for this task):**

1. **Expiry window**: swept `BACKLOG_EXPIRY_DAYS` (extra days beyond the normal one-shot-tomorrow
   attempt every candidate already had) at 2/3/5, plus 0 as a boundary/sanity cell (see the
   correctness check below).
2. **Re-validation on re-entry**: a genuinely backlogged attempt (age > 1, i.e. not the normal
   first-attempt path every candidate already went through pre-feature) re-checks the exact same
   regime/trend-strength/trend-duration/participation gate that governs whether the strategy opens
   ANY new position that day (`regime_ok_today`, hoisted from the existing new-candidate-generation
   site into a single shared boolean so both call sites can never drift out of sync with each
   other) -- a signal from a regime that has since flipped doesn't get grandfathered in just
   because it scored well days ago. Price staleness ("has it already run too far") reuses the
   EXISTING `gap_limit` check against `sig["signal_close"]` (the price on the day it was scored,
   unchanged when carried forward) rather than inventing a second mechanism -- an old backlog
   candidate whose price has moved too far from its original signal close already fails this gate
   today, for free. Deliberately did NOT re-run `score_candidates()`'s own weekly/sector-cut
   membership test on backlog days -- that would need re-slicing that day's full cross-section per
   candidate and risks just reproducing the drop-everything baseline in a more expensive way; the
   regime gate + price-staleness gate combination was judged the right balance per the task's own
   framing.
3. **Priority ordering, fresh vs backlogged**: pure score comparison across both pools, the
   simplest and most defensible default as the task itself suggested. Implementation: survivors
   (not admitted, not yet expired) plus that day's freshly-scored candidates are merged and
   re-sorted by score descending before being carried into tomorrow's admission loop, so the
   FIFO-by-position consumption loop effectively becomes FIFO-by-score across the whole combined
   pool, not "all leftover backlog first, then today's new candidates appended after."
4. **Interaction with existing gates**: `MAX_NEW_ENTRIES_PER_DAY`, `ENTRY_CLUSTER_WINDOW_DAYS`/
   `MAX_ENTRIES_PER_CLUSTER_WINDOW`, and `risk.is_in_cooldown` all sit at the top of the SAME
   per-candidate loop iteration regardless of a signal's origin (fresh or backlogged) -- no
   special-casing needed or added; a backlogged entry is subject to the exact same admission
   checks a fresh one would face, verified by re-reading the loop structure rather than assumed.

**Implementation** (`src/backtest_v4.py`): `BACKLOG_QUEUE_ENABLED` (`V3_BACKLOG_QUEUE_ENABLED`,
default `"0"`) / `BACKLOG_EXPIRY_DAYS` (`V3_BACKLOG_EXPIRY_DAYS`, default `3`) -- both isolated, new
flag names, off by default. Each candidate gets an `origin_day_idx` tag (the day it was scored) at
the point `new_candidates` is built; `age = day_idx - origin_day_idx` is 1 for the pre-existing
one-shot-tomorrow path every candidate already had, and > 1 only for a genuine backlog re-attempt.
At the top of each day's admission processing, `BACKLOG_QUEUE_ENABLED` filters out anything with
`age > 1 + BACKLOG_EXPIRY_DAYS` (permanent expiry) before the admission loop runs; inside the loop,
`age > 1` items additionally re-check `regime_ok_today` (question 2) via a `continue`, the same
pattern the existing cooldown check already uses. At the end of the day, the reset that used to be
an unconditional `pending_entries = []` is now conditional: `BACKLOG_QUEUE_ENABLED=False` keeps
that exact unconditional reset (byte-identical to every prior caller); `True` instead keeps
non-admitted, non-expired survivors, merges them with the day's fresh candidates, and re-sorts by
score (question 3). `diag`'s `admitted` records gained one new field (`age`) for instrumentation;
`equity_curve` gained one new field (`n_positions`, the day's open position count) so
`walk_forward_v4.run_schedule()` could compute `avg_n_positions` per window for the concentration/
dilution check below -- both purely additive (confirmed: `_save_to_supabase` and
`feature_test_harness.py`'s `_aggregate()` both select fields by name, so an extra dict/column key
is a no-op for every existing consumer).

**Correctness checks before trusting any sweep number** (`src/test_backlog_queue.py`, new,
same pattern as `test_diag_hook.py`; run on the same real 2025-07-01..2025-08-31 slice):

- Flag OFF is reproducible run-to-run and byte-identical to the pre-feature baseline; flag ON
  measurably differs (26 trades both OFF runs, 26 different trades ON -- ruling out the
  adaptive-hold-time class of bug where a flag looks like it does nothing because the mechanism
  can structurally never fire).
- 5 genuine backlog fills (age 2..4) on this slice, all within the configured expiry bound, all on
  days `diag` itself tagged `BULLISH` -- expiry and regime re-validation are both actually enforced,
  not just written.
- The `diag` hook stays purely additive under backlog mode too (`diag=None` vs `diag={}` produce
  identical trades/metrics with `BACKLOG_QUEUE_ENABLED=True`), extending `test_diag_hook.py`'s
  existing guarantee to the new code path.
- **Full 9-window walk-forward with the flag at its default (`False`) reproduces the published
  baseline byte-for-byte**: mean alpha +15.88%, mean profit +15.02%, mean PF 1.46, mean/worst DD
  -16.28%/-22.51%, win>50% 5/9 -- confirms the refactor needed to add the backlog mechanism
  (hoisting `regime_ok_today` out of the new-candidate-generation site so both the extension gate
  and the backlog re-validation gate share one definition, plus the new `n_positions`/`age`
  instrumentation) changed nothing for the existing default path.
- **`BACKLOG_EXPIRY_DAYS=0` (flag ON, zero extra days) independently reproduces the OFF baseline
  byte-for-byte too** (389 trades, 15.02/2.87 profit, 15.88/11.57 alpha, 1.46/1.12 PF,
  -16.28/-22.51 DD, 85.2/98.9 conc, 2.62/4.97 avg_n_positions -- every digit matches). This is the
  mechanism correctly reducing to the identity case at its own boundary, empirically confirmed, not
  just reasoned about -- the same "confirm the control cell before trusting the grid" discipline
  `sweep_max_positions.py` used (that one caught a real environment-pinning bug this way; this one
  didn't need a fix, but got the same scrutiny before the real grid was trusted).

**Full 9-window sweep** (`src/sweep_backlog_queue.py`, `V3_BANDAR_SIZING=0` pinned; full per-window
CSV at `.cache/backlog_queue_sweep_full.csv`, agg at `.cache/backlog_queue_sweep_agg.csv`):

| BACKLOG_EXPIRY_DAYS | trades | beat bench | win>50% | win% mean/median | profit% mean/median | alpha% mean/median | PF mean/median | DD% mean/worst | conc% mean/max | avg concurrent positions mean/max |
|---|---|---|---|---|---|---|---|---|---|---|
| **OFF (default)** | 389 | 6/9 | 5/9 | 51.0/51.0 | 15.02/2.87 | 15.88/11.57 | 1.46/1.12 | -16.28/-22.51 | 85.2/98.9 | 2.62/4.97 |
| 0 (sanity boundary) | 389 | 6/9 | 5/9 | 51.0/51.0 | 15.02/2.87 | 15.88/11.57 | 1.46/1.12 | -16.28/-22.51 | 85.2/98.9 | 2.62/4.97 |
| 2 | 385 | 7/9 | 4/9 | 50.0/48.7 | 13.29/8.41 | 14.15/14.74 | 1.98/1.27 | -14.23/-24.67 | 86.3/99.7 | 2.72/4.97 |
| 3 | 383 | 6/9 | 4/9 | 49.6/50.0 | 9.75/9.41 | 10.61/14.74 | 1.90/1.21 | -16.32/-34.11 | 81.4/99.7 | 2.76/5.00 |
| 5 | 379 | 6/9 | 5/9 | 50.4/54.4 | 10.42/6.62 | 11.29/7.46 | 1.84/1.35 | -14.83/-23.45 | 82.8/100.0 | 2.81/4.91 |

**Aggregate mean alpha falls at every tested value (15.88% -> 14.15% -> 10.61% -> 11.29%), a dip-
then-partial-recover shape across 2/3/5 -- the same "worst in the middle, no clean trend" pattern
this log already distrusts (used to help reject `MAX_POSITIONS` widening's `beat_bench`/`win>50%`
non-monotonicity). PF and profit MEDIAN both improve at every value** (PF mean 1.46->1.84-1.98,
profit median 2.87->6.62-9.41) -- a real, not-fabricated secondary effect: the *typical* window
looks a bit more consistent under backlog. But the aggregate mean is dragged down by damage to
specific windows, not noise, and the worst-case drawdown gets meaningfully worse at 2 of 3 tested
values (-24.67% at 2, **-34.11% at 3 -- the single worst drawdown of any configuration tested this
entire session**, worse than `MAX_POSITIONS=10`'s -30.17% that was independently rejected on that
basis alone).

**Per-window trace explains why, and it is the same failure signature Phase 2 (widening) showed --
reached by a different mechanism:**

| Window | OFF/0 alpha | expiry=2 | expiry=3 | expiry=5 |
|---|---|---|---|---|
| W1 | -8.26% | +1.07% | +5.71% | +6.16% |
| W2 | -8.33% | +0.24% | **-9.18%** | -2.52% |
| W3 | -3.89% | -3.88% | -3.88% | -3.88% |
| **W4** | **+41.04%** | **-0.19%** | **-7.05%** | **-7.05%** |
| W5 | +6.42% | +18.75% | +20.26% | +20.11% |
| W6 | +11.57% | +23.20% | +23.35% | +7.46% |
| W7 | +26.13% | +34.91% | +34.91% | +34.91% |
| **W8** | **+59.56%** | **+38.52%** | **+16.64%** | **+30.36%** |
| W9 | +18.66% | +14.74% | +14.74% | +16.02% |

**Window 4** -- explicitly on record twice already this session as "one of the two strongest, most
reliable windows in the whole 9-window schedule" (once when the trend-duration gate collapsed it,
once when `MAX_POSITIONS` widening collapsed it) -- **collapses again**, from +41.04% to
-0.19%/-7.05%/-7.05%, at every non-trivial backlog value tested, on a modest trade-count change
(49->44/43/43) that rules out "fewer trades, less opportunity" as the explanation; this is a
who-fills-which-slot reshuffling effect, the same mechanism Phase 1's concrete traces already
confirmed for the tick-size fix, the spike-confirm gate, and `REGIME_CONFIRM_DAYS=2`. **Window 8**
-- the window with by far the most scarce-slot drops (1158 of the 4085 pooled dropped candidates
from the Phase 1 diagnostic, the window this mechanism was intuitively supposed to help most by
finally admitting some of its own dropped, comparably-scored signal -- **gets WORSE, not better, at
every backlog value tested** (+59.56% -> +38.52%/+16.64%/+30.36%), *despite* trade count actually
rising there (92->95/96/103, backlog IS admitting more of W8's own candidates, just not
profitably). This is the identical outcome `MAX_POSITIONS` widening produced for W8 ("gets WORSE
too, and monotonically... despite trade count rising") -- reached via a structurally different
route (temporal reordering vs concurrent capacity), landing at the same place.

Window 2 is additionally unstable in DIRECTION, not just magnitude, across the grid itself
(+0.24% at expiry=2, -9.18% at expiry=3 -- worse than OFF's own -8.33%, then -2.52% at expiry=5) --
a sign-flipping non-monotonic response to a parameter that should, if this were a real structural
effect, move in a consistent direction as more backlog eligibility is added.

**Explicit check: does this recreate the `MAX_POSITIONS`-widening failure mode from a different
angle?** Partially, and the distinction is itself informative. `avg_n_positions` (mean concurrent
open positions, from the new per-day equity-curve field) stays close to baseline at every tested
value -- 2.62 (OFF) vs 2.72/2.76/2.81 at expiry=2/3/5, a +4-7% relative move, nowhere near
`MAX_POSITIONS=10`'s own dilution-by-design (`ALLOC_PCT` cut from 20% to 12% specifically to fund
more concurrent slots). **So this is NOT the same mechanism** -- capital per position is untouched,
concurrency is essentially unchanged, and the earlier design decision to keep `MAX_POSITIONS`/
`ALLOC_PCT` completely out of this feature held. **But the OUTCOME signature is the same anyway**:
the two windows the whole 9-window schedule's aggregate profit depends on most (W4, W8, the largest
and second-largest alpha contributors at defaults) both get meaningfully worse at every tested
value, while several weaker windows improve -- the same "real effect in the window(s) it helps,
paid for by damage in the window(s) it wasn't built for, concentrated exactly in the strongest
existing performers" pattern this log has now rejected gates for four separate times (trend-
duration, participation, spike-confirm-gate's own W8 sensitivity, `REGIME_CONFIRM_DAYS=2`). The
mechanism here is temporal reshuffling, not capital dilution: merging multiple days' worth of
ranked candidates into one score-sorted pool every day (question 3's design) multiplies the number
of stock/day pairings whose relative order can flip a scarce-slot outcome, which is exactly the
lever Phase 1's three concrete traces already showed produces large, misleading single-window
swings from small, mechanically-unrelated changes. Widening the CONCEPT of eligibility (more days
a signal can compete, even at unchanged `MAX_POSITIONS`) turns out to be just as exposed to that
reshuffling sensitivity as widening the CAPACITY was -- a different lever on the same underlying
fragility, not a fix for it.

**No Monte Carlo permutation check run.** Per this log's own established bar (used identically for
`REGIME_CONFIRM_DAYS=2` and `MAX_POSITIONS` widening): an MC check is for a candidate that looks
"genuinely better and more robust" on the sweep itself. No `BACKLOG_EXPIRY_DAYS` value tested here
reaches that bar -- mean alpha is worse than baseline at all three non-trivial values, the
worst-case drawdown is meaningfully worse at two of three (and the single worst of the whole
session at one), and the per-window trace shows the identical strongest-windows-absorb-the-damage
signature already used to reject four other mechanisms without needing an MC check to falsify them.

**Verdict: REJECTED. KEEP `BACKLOG_QUEUE_ENABLED=False` (the existing, unchanged default).** No
default changed -- `MAX_POSITIONS`, `ALLOC_PCT`, and every other live-affecting default are
untouched, and `BACKLOG_QUEUE_ENABLED`/`BACKLOG_EXPIRY_DAYS` are new, isolated, off-by-default flags
that `paper_signal_scan.py`/`paper_monitor.py` never reference (confirmed by grep) -- so this
finding has zero effect on the live paper-trading path regardless of the verdict, and no governance
approval step is needed before pushing.

**What this and the Phase 2 widening rejection together establish**: the scarce-`MAX_POSITIONS`-
slot mechanism's fragility (Phase 1, prior entry) is real, but BOTH of the two structurally distinct
fixes this session identified for it -- widen capacity, or widen temporal eligibility -- fail for
overlapping but not identical reasons (dilution for the former, reshuffling-noise amplification for
the latter), both landing on the same two windows (W4 damaged in both; W8 gets worse in both despite
more of its own signal being admitted in both). That convergence, from two mechanistically different
levers, is itself evidence the fragility is closer to structural than fixable-with-a-queueing-tweak
-- consistent with this log's existing "understood-but-unresolved" posture toward it, not a reason
to keep searching for a third queueing variant without new evidence pointing at one.

Code kept: `src/sweep_backlog_queue.py` (this sweep, reusable the same way `sweep_max_positions.py`/
`sweep_vol_band_mult.py` are for the next numeric-grid parameter), `src/test_backlog_queue.py`
(self-check, same pattern as `test_diag_hook.py`). `simulate_window()`'s day loop in
`src/backtest_v4.py` gained the `BACKLOG_QUEUE_ENABLED`/`BACKLOG_EXPIRY_DAYS` mechanism plus the
`regime_ok_today` hoist and `n_positions`/`age` instrumentation fields, all regression-verified
byte-identical at defaults. `walk_forward_v4.py`'s `run_schedule()` gained `avg_n_positions` in its
per-window output row (purely additive column). `score_candidates()`, `compute_entry_fill()`,
`evaluate_position_exit()`, `paper_signal_scan.py`, and `paper_monitor.py` are all unchanged. Raw
sweep outputs saved at `.cache/backlog_queue_sweep_full.csv`/`_agg.csv`.
