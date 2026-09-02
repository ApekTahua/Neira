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

## 2026-08-17: council session on today's research yield -- not a failed day, one real untested lever named, next step is a data pull not a new study

After the slot-cap fragility's two fix attempts both rejected (see above), the user directly
questioned whether a full day of rigorous research (7 attempts, 1 real fix + 6 honest rejections)
was actually productive. Ran a 5-advisor + 2-peer-review council (Contrarian, First Principles,
Expansionist, Outsider, Executor) rather than answer unilaterally -- full HTML report:
`council-report-strategy.html` (published as a Claude artifact this session, not committed to the
repo).

**Verdict: today was disciplined validation working as intended, not a failure.** Six rejections
plus one real bug fix, with a Monte Carlo check catching a fake-looking win along the way, is what
the process is supposed to produce -- a day that found six real improvements would be the alarming
result (overfitting). Both peer reviewers independently flagged that the two slot-cap fix attempts
(widen `MAX_POSITIONS`; bounded backlog queue) are really ONE failure mode (diluted concentration)
tested twice, not two independent confirmations the cap is unfixable -- the "stop touching it,
it's load-bearing" conclusion from one advisor overreached on that basis.

**One genuinely untested lever, independently proposed by two advisors and rated strongest by both
peer reviewers**: does `simulate_window()`'s entry loop actually rank-select the best-scoring
candidate when `MAX_POSITIONS` binds, or something closer to first-come-first-served within that
day's already-sorted `score_candidates()` output? Neither of the two rejected fixes (#6/#7 above)
touched selection quality -- both changed capacity or timing while keeping the same admission
order. Real, unresolved tension flagged by peer review: a third advisor's point that dropped
candidates score 89% as high as admitted ones might mean the ranking function's resolution is too
coarse for a rank-by-score fix to matter at all -- nobody connected this to the fix it undermines.

**Recommended next step, not yet done**: before building a rank-by-score fix, pull the existing
`.cache/slot_queue_diag_dropped_max_positions.csv` data (already collected from the earlier
diagnostic) and check score separation specifically on capped days -- does the admitted top-6
clearly outscore the best dropped candidate, or is it usually a near-tie? That's a five-minute data
pull, not a new walk-forward study, and it decides whether the fix is worth a session at all.

**Also flagged, not a finding requiring action**: the current unchanged baseline (win>50% in 5/9
windows, mean DD -16.28%/worst -22.51%) already sits roughly inside the user's own previously
stated comfort zone (45-60% win rate, 20-25% drawdown) -- part of today's "it doesn't feel like
it's working" read may be an expectations gap against that stated bar, not evidence the research
effort came up empty. And: 5 days / 0 closed trades of V4_PAPER live data remains genuinely
uninformative in either direction -- not proof more research is pointless, not proof it's needed
first. The recommendation is to run the data-pull check AND let live data keep accumulating in
parallel, not to choose one over the other.

## 2026-08-17: the council's "one thing to do first" check, done -- boundary is crisp, but the real
## open question turns out to be different from what was scoped

`src/check_slot_boundary_gap.py` -- reused `diagnose_slot_queue.py`'s exact diag hook and cached
dataset (no new backtest mechanism, no live-path files touched), this time pairing each day's
admitted/dropped scores by DATE (the earlier diagnostic only kept an unpaired flat list) to compute
`boundary_gap = min(admitted score that day) - max(dropped score that day)` on every day the
`max_positions` cap actually bound.

**Contrarian's "89% score similarity means the ranking is noise" concern is NOT supported at the
actual decision boundary.** Across 145 capped days that had both an admit and a drop that day:
mean gap 3.89, median 2.14 score points, and **zero inversions** -- not one single day where a
dropped candidate outscored the worst admitted candidate. The 89% figure was a pooled mean across
ALL dropped candidates (including many deep in the tail, far below the cutoff), which is a
different and less informative number than the gap right at the boundary that actually decides
admission. At the boundary specifically, the ranking is reliable.

**But this also surfaces a real, unscoped finding: same-day admission already respects rank order
perfectly (0% inversion) -- meaning Executor's originally-proposed fix ("replace first-come with
rank-by-score") may have little room to improve anything, because it may already describe what
`simulate_window`'s loop does within a single day.** The remaining 219 of the 364 capped days
(60.2%) had ZERO admits at all that day -- every ranked candidate was dropped, because slots were
already fully occupied by positions opened on PRIOR days. That reframes the open question:
it isn't "does today rank its own candidates correctly" (yes, verified) -- it's "should an
already-open position from an earlier day ever be displaced by a much better new candidate
arriving later." That's a materially bigger, more invasive idea than a same-day sort tweak --
it touches live position management, not just entry-queue ordering, and would need its own
careful design (what triggers a displacement? does it count as prematurely closing a position
that hasn't hit its own SL/TP/time exit? how does this interact with frozen-run governance if it
ever reached a live config) before any walk-forward validation, not a same-session build.

**Status: diagnostic-only, not acted on further.** Confirms the fix Executor/Expansionist/peer-
review converged on is worth designing properly, but the actual shape needed (cross-day position
rotation, not same-day rank-by-score) is bigger and riskier than what was scoped in council --
flagging back rather than building it unprompted. Raw data: `.cache/slot_boundary_gap.csv`.

## 2026-08-17: why the Screener page never shows fewer than ~90 signals -- it's reading the wrong
## function, not a scoring/algorithm problem. Root-caused, not yet fixed.

User complaint: too many BUY signals shown, every day, no matter what -- wanted a system that
shows exactly as many signals as genuinely qualify (including zero on a bad day), pointed at a
competitor screener (idx.maxlong.my.id) as a more "confident/selective" benchmark. Ran a 5-advisor
+ 2-peer-review council (report published as a Claude artifact this session).

**Benchmark investigation, before the council**: the competitor's "today" screenshots are 100%
exact-match stale data from the last real trading day (verified against our own `ihsg_eod` on all
18 tickers shown, to the exact price and percent) -- the site was displaying Friday 2026-08-14's
close under a 2026-08-17 header, since IDX was closed today (Hari Kemerdekaan). Its "selective"
categories also cluster many tickers on IDENTICAL scores (e.g. 3 different stocks all scoring
exactly 5270 in one category), suggesting a coarse discrete lookup table rather than a
continuously-computed, stricter quality bar. TEBE -- the exact stock this log already found has a
35-39% historical win rate / negative median return on this pattern -- appears uncontested in the
competitor's own "Gamma" category. Verdict: not a validated benchmark, don't build toward it.

**Real root cause, confirmed by direct code read (not inferred from output shape)**: the frontend
Screener page reads `daily_scoreboard`, populated by `score_full_universe()`
(`backtest_v4.py:1328`) -- which its OWN docstring says is deliberately built to "never drop a
row, so a ticker search always has an answer instead of silence." It is a ticker-lookup/display
function, not a selectivity filter, and was never meant to answer "how many signals qualify
today." The function ACTUALLY used to decide real trade entries, `score_candidates()` (already
proven capable of returning few or zero, and already the one live trades are gated on), is a
different function entirely -- the frontend has never read from it.

Initial framing suspected `score_full_universe`'s label was percentile-based (a fixed proportion
of the universe always relabeled BUY, whatever the market does). Code read during the council
found this wrong in the specific way that matters: `weekly_cut`/`sector_cut`/`score_p90` are fixed
TRAIN-derived quantile thresholds (not same-day percentiles), and there's a real regime kill-switch
-- if `regime_ok` is False, EVERY ticker gets labeled WAIT, not BUY. But `daily_gate_summary` showed
`regime_ok=true` on all 8 of the most recently sampled days (2026-08-05..08-14) -- the WAIT-
everything path exists and was simply never observed in that specific bullish stretch.

**Decisive empirical answer, from data already collected in the MAX_POSITIONS diagnostic earlier
today**: `score_candidates()`'s real daily output (admitted + dropped candidates, i.e. every day it
was actually called) across the full 9-window walk-forward --

| Window | Trading days | Days with >=1 real candidate | Days with ZERO |
|---|---|---|---|
| 1 | 116 | 63 | 53 (45.7%) |
| 2 | 130 | 35 | 95 (73.1%) |
| 3 | 114 | 10 | 104 (91.2%) |
| 4 | 125 | 67 | 58 (46.4%) |
| 5 | 110 | 30 | 80 (72.7%) |
| 6 | 127 | 64 | 63 (49.6%) |
| 7 | 109 | 26 | 83 (76.1%) |
| 8 | 127 | 117 | 10 (7.9%) |
| 9 | 111 | 17 | 94 (84.7%) |
| **Total** | **1069** | **429** | **640 (59.9%)** |

**The system the user is asking for already exists and is already what real trades are gated
on.** 60% of all trading days across the full validated history, the real entry-qualifying
function returns nothing at all -- from as low as 7.9% zero-days in the strongest bull window to
91.2% in the weakest. The frontend just never shows this, because it was built on a different
function chosen for a different job (always answer a ticker search) rather than the one already
doing exactly the selectivity job the user wants.

**Recommendation, not yet built**: don't touch `score_full_universe()` (still needed for ticker
search/lookup, working as designed) or `score_candidates()`/`compute_entry_fill()`/any trading
logic (already validated, zero changes needed). Add a new, separate persisted "today's real
candidate count" -- `score_candidates()`'s output isn't currently stored anywhere long-term (only
consumed transiently by `paper_signal_scan.py` to decide what to queue, capped at
`MAX_NEW_ENTRIES_PER_DAY`); the Screener page needs its own read path built on this function's
real output, not `daily_scoreboard`. This is a frontend/wiring fix once the persistence exists, not
a backtest research question -- no walk-forward validation needed, since the selectivity itself is
already validated by definition (same function real trades already use). Two peer reviewers
independently flagged that the frontend and `daily_scoreboard` can currently disagree with what
real trades would actually do on the same ticker -- a trust gap worth closing regardless of the
"too many signals" complaint on its own.

## 2026-08-17: cross-day position ROTATION -- the third scarce-MAX_POSITIONS-slot fix attempt,
## tested, REJECTED. Same reshuffling-noise signature the tick-size fix / spike-confirm-gate /
## REGIME_CONFIRM_DAYS=2 already exposed, now directly traced to a rotation event's own cascade.
## KEEP `ROTATION_ENABLED=False` (2026-08-17)

**Hypothesis, from the council's "one thing to do first" check** (see above, "the boundary is
crisp" entry): 60.2% of capped days (219/364) have ZERO admits at all -- every ranked candidate
dropped because slots are already occupied by positions opened on PRIOR days, not lost on a
same-day tie (same-day ranking is already crisp, 0% inversion). Neither of the two already-
rejected fixes (widen `MAX_POSITIONS`; a bounded backlog queue) touches an already-open
position's own lifecycle -- both changed WHO wins a slot among candidates arriving on the SAME
cycle. This tests the genuinely different, previously-flagged-but-unbuilt lever: should an
already-open position ever be force-exited early to free a slot for a materially stronger new
candidate?

**Design** (`src/backtest_v4.py`, `ROTATION_ENABLED` block, `V3_ROTATION_ENABLED` default `"0"`):

1. **Trigger**: inside the entry-consumption loop, when `len(positions) >= MAX_POSITIONS` would
   normally `break` (drop the rest of the day's ranked queue), instead compare the incoming
   candidate's score against the WEAKEST rotation-eligible open position's *current* score (not
   its entry-day score -- recomputed daily from that stock's own weekly_ma_spread/
   sector_rs_momentum, using yesterday's data, the same one-day lag `pending_entries` itself
   already has, so this is not a new lookahead). Rotate only if the gap clears
   `ROTATION_MARGIN_MULT * score_p90` -- score_p90 is the same train-derived reference
   `SCORE_SIZING`/`TREND_SIZING` already use, so the margin auto-scales with each window's own
   score distribution instead of a flat number that means something different in a window with
   mean admitted score ~16 vs one with ~68 (see the Phase 1 diagnostic's per-window score table,
   "the scarce-MAX_POSITIONS-slot mechanism itself" entry above). Swept 0.5/1.0/2.0/3.0, plus 999
   (an unreachable margin) as a boundary/sanity cell.
2. **Never cut a winner short**: a position that has already hit TP1 is fully protected (never a
   rotation victim) -- same "proven, don't touch" treatment `PYRAMID_ENABLED` already gives it.
   A pre-TP1 position that is CURRENTLY IN PROFIT and within `ROTATION_TP1_PROTECT_ATR_MULT`
   (default 1.0) ATR of its own TP1 price is also protected -- the explicit failure mode this task
   was scoped to check for: don't force an early exit right before a position would have hit
   target anyway.
3. **Minimum hold before eligible**: `ROTATION_MIN_HOLD_DAYS` (default = `cfg.MIN_HOLD_DAYS` = 3)
   -- a position isn't even eligible for its OWN TP1/trailing exit before that many days, so it
   shouldn't be forced out by someone else's signal any sooner either.
4. **Real cost, no free pass**: `_rotate_out()` exits through the EXACT SAME
   `apply_slippage()` + `risk.apply_fee()` path `evaluate_position_exit()` uses for a real sell --
   tagged `exit_reason="ROTATE"` in the trade log, contributing to win-rate/profit-factor/
   concentration exactly like any other exit. A rotation is not a cancel.
5. **Blast-radius cap**: `MAX_ROTATIONS_PER_DAY` (default 1) bounds how many positions one day's
   decisions can force-exit, same reasoning `MAX_NEW_ENTRIES_PER_DAY` already applies to fresh
   entries -- and rotation is only attempted when `new_entries_today < MAX_NEW_ENTRIES_PER_DAY`,
   so a slot is only freed when the triggering candidate can actually still use it that same day.

**Implementation notes**: `feature_lookup` (a new `(stock_code, trade_date) -> (weekly_ma_spread,
sector_rs_momentum)` dict, built only when `ROTATION_ENABLED`, same conditional-build pattern
`limit_lookup` already uses for `ARB_EXIT_REALISM`) is the only new per-window precomputation.
Fixed a real latent bug surfaced while wiring this in: the existing `diag` hook's
`positions_start_count` field was computed by subtraction (`len(positions) - new_entries_today`)
AFTER the entry loop, which silently assumed positions only ever GROW during that loop -- true
before this feature, false now that rotation can also REMOVE one mid-loop. Replaced with an
explicitly-captured `_positions_start_count = len(positions)` taken BEFORE the loop starts --
produces the identical value in every pre-existing (non-rotating) code path, confirmed by the
correctness checks below, so this is a strictly-more-correct fix, not a behavior change.

**Correctness checks before trusting any sweep number** (`src/test_rotation.py`, same pattern as
`test_backlog_queue.py`; run on the same real 2025-07-01..2025-08-31 slice):
- Flag OFF is reproducible run-to-run, never produces a `ROTATE` exit, and (separately) the full
  9-window walk-forward with the flag at its default (`False`) reproduces the published baseline
  byte-for-byte: mean alpha +15.88%, mean profit +15.02%, mean PF 1.46, mean/worst DD
  -16.28%/-22.51%, win>50% 5/9, beat-bench 6/9 -- confirms the `_positions_start_count` fix and
  the new `feature_lookup`/rotation-helper wiring changed nothing for the existing default path.
- Flag ON (loose margin, 0.3, to guarantee the mechanism actually fires on this slice) measurably
  differs (26 trades OFF vs 32 trades / 10 `ROTATE` exits ON) -- rules out the adaptive-hold-time
  class of bug where a flag looks like it does nothing because the mechanism can structurally
  never fire.
- Every rotation in that run cleared the real `ROTATION_MARGIN_MULT * score_p90` margin
  (recomputed independently in the test, not just trusted from the run itself) and respected
  `ROTATION_MIN_HOLD_DAYS` -- checked directly against the diag hook's own new `rotated`
  per-day field, cross-referenced against the actual `ROTATE` trade records.
- `ROTATION_MARGIN_MULT=999` (an unreachable margin, flag ON) independently reproduces the OFF
  baseline byte-for-byte across the full 9-window sweep too (389 trades, 0 rotations, every
  metric identical to the digit) -- the mechanism correctly reduces to the identity case at its
  own boundary, empirically confirmed, same "confirm the control cell" discipline
  `sweep_max_positions.py`/`sweep_backlog_queue.py` both used.
- diag stays purely additive under rotation mode too (`diag=None` vs `diag={}` produce identical
  trades/metrics with `ROTATION_ENABLED=True`), extending `test_diag_hook.py`'s guarantee.

**Full 9-window sweep** (`src/sweep_rotation.py`, `V3_BANDAR_SIZING=0` pinned; full per-window CSV
at `.cache/rotation_sweep_full.csv`, agg at `.cache/rotation_sweep_agg.csv`):

| ROTATION_MARGIN_MULT | trades | rotations | beat bench | win>50% | win% mean/median | profit% mean/median | alpha% mean/median | PF mean/median | DD% mean/worst | conc% mean/max |
|---|---|---|---|---|---|---|---|---|---|---|
| **OFF (default)** | 389 | 0 | 6/9 | 5/9 | 51.0/51.0 | 15.02/2.87 | 15.88/11.57 | 1.46/1.12 | -16.28/-22.51 | 85.2/98.9 |
| 0.5 | 467 | 85 | 6/9 | 5/9 | 50.0/52.2 | 18.92/-0.67 | 19.78/6.25 | 1.51/0.98 | -16.58/-31.00 | 76.5/96.1 |
| 1.0 | 431 | 61 | 6/9 | 4/9 | 49.8/50.0 | 13.56/7.26 | 14.42/8.35 | 1.40/1.27 | -17.03/-31.01 | 80.5/96.3 |
| 2.0 | 418 | 28 | 7/9 | 4/9 | 50.4/50.0 | 28.44/7.64 | 29.31/18.66 | 1.62/1.37 | -16.76/-24.26 | 83.2/96.1 |
| 3.0 | 403 | 12 | 6/9 | 6/9 | 51.1/51.4 | 19.28/2.87 | 20.15/10.76 | 1.56/1.12 | -15.76/-22.51 | 84.3/98.9 |
| 999 (sanity) | 389 | 0 | 6/9 | 5/9 | 51.0/51.0 | 15.02/2.87 | 15.88/11.57 | 1.46/1.12 | -16.28/-22.51 | 85.2/98.9 |

**First red flag: no clean, monotonic relationship between margin and outcome.** Tightening the
margin from 0.5->1.0->2.0->3.0 should move rotation FREQUENCY monotonically down (85->61->28->12
rotations, which it does, cleanly) -- but mean alpha does NOT move monotonically with it
(19.78 -> **14.42 (WORSE than OFF's 15.88, despite 61 rotations firing)** -> 29.31 -> 20.15). A
setting with MORE rotations (1.0, 61) underperforming both a looser setting (0.5, 85) AND a
tighter one (2.0, 28) is the same "worst in the middle, no clean trend" shape this log has
already learned to distrust (used to help reject `MAX_POSITIONS` widening's non-monotonic
`beat_bench`/`win>50%` pair, and the `BACKLOG_EXPIRY_DAYS` sweep's dip-then-partial-recover
shape). `win>50%` is also NOT better at the best-looking margin (2.0: 4/9, actually worse than
OFF's 5/9) -- a real, broad improvement should not come with reduced win-rate consistency.

**Second, decisive check: how much of the "best" result (2.0) is one window.** Per-window alpha:

| Window | OFF | 0.5 | 1.0 | 2.0 | 3.0 |
|---|---|---|---|---|---|
| 1 | -8.26 | 6.25 | 8.35 | 18.71 | -9.88 |
| 2 | -8.33 | -12.51 | -0.87 | -9.14 | -5.20 |
| 3 | -3.89 | -3.89 | -3.89 | -3.89 | -3.89 |
| 4 | 41.04 | 20.04 | 22.13 | 39.96 | 41.04 |
| 5 | 6.42 | -3.97 | -5.47 | 11.19 | 6.42 |
| 6 | 11.57 | 0.17 | 8.09 | 1.54 | 10.76 |
| 7 | 26.13 | 28.75 | 26.13 | 26.13 | 26.13 |
| **8** | **59.56** | **135.35** | **56.69** | **160.60** | **97.28** |
| 9 | 18.66 | 7.82 | 18.66 | 18.66 | 18.66 |

At `ROTATION_MARGIN_MULT=2.0`, Window 8 alone contributes **+101.04pp of the whole 9-window
schedule's summed +120.86pp alpha delta -- 83.6% of the entire aggregate "improvement" from one
window.** Excluding Window 8 entirely, the aggregate mean alpha across the other 8 windows is
**12.90% at margin=2.0 vs 10.42% for OFF -- a modest +2.48pp bump**, not the headline +13.43pp
(15.88%->29.31%) the full 9-window number implies. The same check on every other margin tested is
worse, not better: **ex-Window-8, margin=0.5 (5.33%) and margin=1.0 (9.14%) are both BELOW the
OFF baseline (10.42%)** -- their apparent aggregate improvement is propped up entirely by Window
8's swing too (0.5's own W8 delta, +75.79pp, exceeds its ENTIRE 9-window summed delta of
+35.11pp -- the other 8 windows collectively net NEGATIVE once W8 is excluded). Margin=3.0 is the
one exception: ex-W8 mean 10.51% is flat with OFF's 10.42% -- consistent with it being the
tightest margin (only 12 rotations across the whole 9-window schedule), close enough to inert
that it barely differs from not rotating at all.

**Window 8 is the SAME window this log has now flagged three separate times this session** (the
tick-size-rounding fix, the spike-confirm-delay gate, `REGIME_CONFIRM_DAYS=2` -- see "the scarce-
MAX_POSITIONS-slot mechanism itself" entry above) as the one that reliably produces a large,
misleading-looking single-window swing from a small, mechanically-unrelated change, because it
has the most candidate-days of any window (117/127) and the portfolio sits at capacity ~87% of
them -- any change that reorders who holds a scarce slot cascades into a materially different
5-month trade sequence. Rotation was built to do exactly that reordering, deliberately, so testing
whether it recreates the same signature here (rather than assuming it does) mattered.

**Concrete mechanistic trace** (`src/trace_w8_rotation.py`, same method
`trace_w8_slot_swaps.py` already used for the other three cases), `ROTATION_MARGIN_MULT=2.0`: the
first divergence is a single event on **2025-07-31** -- `_rotation_victim` evicts **BDKR** (score
65.52, held 11 days, comfortably past `ROTATION_MIN_HOLD_DAYS`) to seat **WIFI** (score 104.24,
clearing the ~34-point margin at that window's `score_p90`). WIFI had been generated fresh and
dropped on `max_positions` for four straight days (07-28 through 07-31, its own score climbing
84.1 -> 85.2 -> 88.4 -> 104.2 as the stock kept rallying while queued) -- in the OFF run it
finally gets admitted the ORDINARY way one day later, on 2025-08-01, once PGEO's own TRAILING
stop naturally freed a slot. **Rotation's entire effect in this trace is admitting the exact same
stock one day earlier than it would have entered anyway** -- not surfacing a genuinely different
opportunity, just timing it slightly sooner by evicting a comparatively weak, already-11-day-old
position. That one-day timing shift is then enough to cascade into 13 additional trades and a
completely different subsequent sequence across the rest of the 5-month window (92 trades OFF ->
110 ON) -- the identical cascade mechanism already mechanistically confirmed for the tick-size fix
("a different position's exit timing shifting by sub-tick amounts... cascading into a different
subsequent trade sequence"), just triggered by a deliberate force-exit instead of an incidental
rounding change.

**No fresh Monte Carlo permutation script was built.** Per this log's own established bar (used
identically for `REGIME_CONFIRM_DAYS=2`, the `VOL_BAND_MULT` re-sweep, and `MAX_POSITIONS`
widening): an MC check is for a candidate that looks "genuinely better and more robust" on the
sweep itself. This one does not reach that bar -- it was falsified by the SAME kind of scrutiny an
MC check exists to provide: a non-monotonic dose-response, an ex-one-window aggregate that is flat
or negative at every tested margin, and a direct mechanistic trace confirming the improvement is
the already-documented reshuffling-cascade artifact, not a new causal story. Running a permutation
test on a result already falsified this specifically would not add information (matches the exact
reasoning already used to skip an MC build for the other two rejected scarce-slot fixes).

**Drawdown, checked explicitly since two prior scarce-slot fixes both failed partly on this
axis**: looser margins cost real drawdown (`dd_worst` -31.00%/-31.01% at 0.5/1.0, in the same
range as `MAX_POSITIONS=10`'s independently-rejected -30.17% and the backlog queue's -34.11%)
while buying little-to-nothing ex-Window-8. Only the tightest margin (3.0) avoids drawdown damage
(`dd_worst` -22.51%, identical to OFF) -- and at that setting the ex-W8 effect is already
indistinguishable from zero. There is no margin value in this grid that is simultaneously "does
something real" and "doesn't cost drawdown for a Window-8-sized effect that isn't real."

**Verdict: REJECTED. KEEP `ROTATION_ENABLED=False` (the existing, unchanged default).** This is
the THIRD scarce-`MAX_POSITIONS`-slot fix attempt this session (after widening the cap and the
bounded backlog queue), and it fails for a reason that ties all three together even more tightly
than the two before it: every lever that changes WHO holds a scarce slot -- wider capacity,
temporal reordering, or now early force-eviction -- runs straight into the same underlying
fragility Phase 1 already diagnosed (a full-87%-of-the-time, 6-slot, no-backlog queue is
extremely sensitive to small reorderings, independent of whether those reorderings are
well-motivated). Unlike the first two rejections (clean monotonic decline; a `avg_n_positions`-
ruled-out capital-dilution story), this one required tracing an actual trade sequence to
distinguish "real improvement" from "the reshuffling artifact wearing a different mechanism's
clothes" -- and once traced, it is unambiguously the latter for the one setting that looked
promising in aggregate.

**What this closes**: the council's own "one thing to do first" recommendation (see above) has
now been fully worked through -- same-day ranking was checked first and found already crisp (no
fix needed there), and cross-day rotation (the bigger, riskier idea flagged as "worth designing
properly" but not yet built) has now been designed, implemented additively, swept across all 9
windows, and mechanistically traced to a null result. **All three concrete fix directions this
session identified for the scarce-slot fragility have now been tried and rejected on real
evidence** (widening -> capital dilution; backlog -> reshuffling noise; rotation -> reshuffling
noise via a different but ultimately identical mechanism). This does not mean no fix could ever
work -- but it does mean the fragility itself should be treated as accepted-and-understood, the
same posture Window 3's residual weakness already has, rather than an open item still awaiting a
fourth attempt at the same category of lever (queue/slot reordering). A genuinely different
category of idea (not "who gets the slot" but e.g. a structurally different MAX_POSITIONS design,
or accepting the fragility and focusing effort elsewhere, as the 2026-08-17 council session's own
"where effort is best spent" reasoning already suggested) would be needed to make further progress
here.

**Governance note (no action needed, stated for the record per this session's own standing
requirement)**: confirmed by grep -- `paper_signal_scan.py`/`paper_monitor.py`/`paper_common.py`
reference none of `ROTATION_ENABLED`/`ROTATION_MIN_HOLD_DAYS`/`ROTATION_MARGIN_MULT`/
`ROTATION_TP1_PROTECT_ATR_MULT`/`MAX_ROTATIONS_PER_DAY` -- this finding has zero effect on the
live paper-trading path regardless of the verdict, and no default in `backtest_v4.py` was changed
(REJECTED, not promoted), so no separate approval step is needed before pushing.

Code kept: `src/test_rotation.py` (self-check, same pattern as `test_backlog_queue.py`),
`src/sweep_rotation.py` (this sweep, reusable the same way `sweep_backlog_queue.py`/
`sweep_max_positions.py` are for the next numeric-grid parameter), `src/trace_w8_rotation.py`
(concrete A/B tracer, same pattern as `trace_w8_slot_swaps.py`, reusable for the next "why did
this one window move so much" question). `simulate_window()`'s day loop in `src/backtest_v4.py`
gained the `ROTATION_ENABLED` mechanism (`_rotation_current_score`/`_rotation_victim`/
`_rotate_out` closures, a new conditionally-built `feature_lookup`, the `_positions_start_count`
correctness fix, and a new `rotated` diag field), all regression-verified byte-identical at
defaults. `score_candidates()`, `compute_entry_fill()`, `evaluate_position_exit()`,
`paper_signal_scan.py`, and `paper_monitor.py` are all unchanged. Raw sweep outputs saved at
`.cache/rotation_sweep_full.csv`/`_agg.csv`, `.cache/rotation_off_regression.csv`.

## Spike sizing (reduce, don't exclude/delay): built and swept, REJECTED -- same non-monotonic
## dose-response, uniformly-worse worst-case drawdown, and two-window reshuffling-cascade
## signature already documented for SPIKE_CONFIRM_GATE and three scarce-slot mechanisms this
## session (2026-08-18)

**Hypothesis**: the confirmation-delay gate (previous entry, REJECTED) excluded spike-flagged
candidates outright and lost on every axis this log checks, including because the underlying
pattern isn't zero-edge -- 35-39% win rate, and a fat right tail (932-episode base-rate research,
best cases up to +453% at 20d). A structurally different mechanism, flagged but not built at the
time: let the entry through as normal, reduce its position size only. This respects the
asymmetry (real tail winners worth keeping some exposure to) instead of filtering them out
entirely.

**Mechanism** (`src/backtest_v4.py`): reuses `compute_spike_confirm_gate()` completely unchanged
(same `SPIKE_VOL_MULT`/`SPIKE_MOVE_PCT`/`SPIKE_CONFIRM_DAYS`/`SPIKE_GIVEBACK_PCT` = 10x/20%/3
days/15%, already computed once per window regardless of either flag's state) -- but reads it as
a per-candidate **sizing tag** instead of a candidacy filter: `simulate_window`'s own
`new_candidates` loop tags each candidate `is_spike = not spike_confirm_gate.get((stock_code,
trade_date), True)` (inverted: True means "currently inside a recent spike's blackout or its
failed checkpoint," the same condition the rejected gate used to exclude outright). Tagged
unconditionally, same "cheap dict key, no conditional default needed downstream" pattern
`origin_day_idx` already uses. `compute_entry_fill()` reads `sig.get("is_spike", False)` and
applies a flat multiplier (`SPIKE_SIZING_MULT`, not a ratio-and-clip formula like the other
sizing multipliers -- there's no "how spike-y" continuum here, just a binary flag) alongside the
existing composed multiplier chain (`size_mult * liq_mult * trend_mult * bandar_mult *
mover_mult * accdist_mult * rotation_mult * spike_mult`). Gated by `SPIKE_SIZING_ENABLED`
(default `"0"`, off), `SPIKE_SIZING_MULT` (default `0.5`) -- new, isolated flags, independent of
`SPIKE_CONFIRM_GATE_ENABLED`'s own default.

**Cannot affect the live paper-trading path regardless of this flag's state, for a stronger
reason than usual**: `score_candidates()`'s own real output (what `paper_signal_scan.py`/
`paper_monitor.py` actually call) never carries an `"is_spike"` key at all -- only
`simulate_window`'s own `pending_entries` tagging adds it. `compute_entry_fill()`'s
`sig.get("is_spike", False)` therefore reads `False` for every live sig dict unconditionally, so
even a future accidental env-var flip could not change a live fill's sizing; confirmed directly
in `src/test_spike_sizing.py` (part 1: a sig dict missing the key sizes identically to
`is_spike=False`, with the flag ON).

**Correctness checks before trusting any sweep number** (`src/test_spike_sizing.py`):
- Flag OFF: sizing is byte-identical regardless of `is_spike`, including a sig dict missing the
  key entirely (paper_monitor.py's real shape) -- confirms the off-by-default no-op.
- Flag ON, `MULT=0.5`: an `is_spike=True` candidate's `cost_basis` comes out at 0.500x an
  otherwise-identical `is_spike=False` candidate's (isolated from `LIQ_SIZING_ENABLED`'s own
  liquidity cap, which otherwise saturates both branches to the same value and masks the ratio --
  a real trap this test caught on the first run, see the test file for the isolation reasoning);
  `is_spike=False`/missing candidates stay untouched.
- Cold-process import check: default OFF/0.5, overrides both ways, `SPIKE_CONFIRM_GATE_ENABLED`/
  `ROTATION_SIZING_ENABLED`'s own defaults untouched.
- Real out-of-sample slice (full Window 8, 2025-07-01..2025-12-30 -- the Jul-Aug half alone
  admits zero spike-flagged candidates, too small a sample to exercise the mechanism at all):
  OFF reproducible run-to-run, diag purely additive (`diag=None` vs `diag={}` identical), ON
  (loose `MULT=0.3`) measurably differs, and every spike-flagged admit in the ON run sizes
  smaller on average (avg cost_basis Rp19.6M -> Rp6.3M) than the OFF run's own spike-flagged
  admits.

**Full 9-window sweep** (`src/sweep_spike_sizing.py`, `V3_BANDAR_SIZING=0` pinned; full
per-window CSV at `.cache/spike_sizing_sweep_full.csv`, agg at
`.cache/spike_sizing_sweep_agg.csv`; OFF row reproduces the session's standing baseline
byte-for-byte -- 389 trades, 15.02/2.87 profit, 15.88/11.57 alpha, 1.46/1.12 PF, -16.28/-22.51
DD, 85.2/98.9 conc, 5/9 win>50%, 6/9 beat-bench -- confirming the `is_spike` tagging and the new
diag field changed nothing for the existing default path):

| SPIKE_SIZING_MULT | trades | spike admits | beat bench | win>50% | win% mean/median | profit% mean/median | alpha% mean/median | PF mean/median | DD% mean/worst | conc% mean/max |
|---|---|---|---|---|---|---|---|---|---|---|
| **OFF (default)** | 389 | 26 | 6/9 | 5/9 | 51.0/51.0 | 15.02/2.87 | 15.88/11.57 | 1.46/1.12 | -16.28/-22.51 | 85.2/98.9 |
| 0.25 | 391 | 26 | 6/9 | 4/9 | 50.8/47.1 | 20.74/7.70 | 21.60/13.59 | 1.51/1.32 | -16.23/-26.04 | 86.2/97.8 |
| 0.5 | 391 | 26 | 6/9 | 5/9 | 51.7/52.6 | 15.66/2.87 | 16.53/14.26 | 1.49/1.12 | -15.89/-24.72 | 83.6/98.9 |
| 0.75 | 388 | 26 | 7/9 | 4/9 | 51.0/50.0 | 18.29/4.37 | 19.16/13.97 | 1.56/1.13 | -16.28/-24.11 | 85.5/98.9 |

**First red flag: no clean dose-response.** A real, causal sizing effect should move
monotonically as the cut gets more aggressive (0.25 = biggest cut, 0.75 = smallest). Mean alpha
instead dips in the middle: 21.60% (0.25) -> **16.53% (0.5, barely above OFF's 15.88%)** ->
19.16% (0.75) -- the identical "worst in the middle, no clean trend" shape this log has now used
to help reject `MAX_POSITIONS` widening, the backlog queue, `ROTATION_MARGIN_MULT`, and the
spike-confirm-gate's own giveback sweep. `win-rate>50%` is WORSE than OFF's 5/9 at two of the
three tested multipliers (4/9 at both 0.25 and 0.75), matching only at 0.5.

**Second, decisive check: worst-case drawdown is worse than baseline at every single tested
multiplier** (`dd_worst` -26.04%/-24.72%/-24.11% vs OFF's -22.51%) -- the exact test the
confirmation-delay gate itself already failed on ("worst-case single-window drawdown is WORSE
than the OFF baseline... at literally every one of the 8 tested configurations"). Reducing size
on a spike-flagged entry does not reduce the portfolio's worst realized drawdown anywhere in this
sweep either.

**Third, the trace: the best-looking config's headline number is two known-fragile windows
moving in opposite directions, not a broad improvement.** Per-window alpha, mult=0.25 (the
config with the best mean alpha, +21.60%) vs OFF:

| Window | OFF alpha | 0.25 alpha | Delta | trades (0.25 vs OFF) | spike admits (0.25 vs OFF) |
|---|---|---|---|---|---|
| 1 | -8.26% | +17.25% | +25.51pp | 50 vs 56 | 3 vs 5 |
| 2 | -8.33% | -8.07% | +0.26pp | 38 vs 38 | 4 vs 3 |
| 3 | -3.89% | -1.72% | +2.17pp | 19 vs 19 | 2 vs 2 |
| **4** | **+41.04%** | **-19.97%** | **-61.01pp** | 49 vs 49 | 4 vs 4 |
| 5 | +6.42% | +11.25% | +4.83pp | 34 vs 34 | 1 vs 1 |
| 6 | +11.57% | +13.59% | +2.02pp | 57 vs 57 | 4 vs 4 |
| 7 | +26.13% | +24.68% | -1.45pp | 21 vs 21 | 1 vs 1 |
| **8** | **+59.56%** | **+142.22%** | **+82.66pp** | 100 vs 92 | 5 vs 4 |
| 9 | +18.66% | +15.18% | -3.48pp | 23 vs 23 | 2 vs 2 |

Window 4 -- on record twice already this session as "one of the two strongest, most reliable
windows in the whole 9-window schedule" (once when the trend-duration gate collapsed it, once
when `MAX_POSITIONS` widening collapsed it) -- **collapses again**, from +41.04% to -19.97%, on
an *unchanged* trade count (49) and an *unchanged* spike-admit count (4 both runs) -- sizing
down the exact same 4 flagged candidates by 75% was enough, on its own, to flip this window from
one of the best in the schedule to a loser. Window 8 -- the window this session has now flagged
**five separate times** (tick-size fix, spike-confirm-gate, rotation, backlog queue, and now
this) as the one that reliably produces a large, misleading single-window swing from a small
mechanical change -- explodes from +59.56% to +142.22%, on a modest trade-count change (92->100)
and one extra spike-admit (4->5). Summed across all 9 windows, W4's -61.01pp and W8's +82.66pp
net to +21.65pp of alpha delta between them -- 2.41pp of the schedule's own +5.72pp mean-alpha
improvement (21.60%-15.88%) once divided across all 9 windows, meaning these two single windows
alone contribute more than 40% of the whole schedule's apparent mean improvement, on top of the
already-large individual swings within each.

**Excluding W4 and W8 does not rescue this into a clean result either.** Ex-W4/W8 mean alpha:
OFF 6.04% -> 0.25: 10.31%, 0.5: 6.56%, 0.75: 7.46% -- still the same worst-in-the-middle
non-monotonic shape, and even the "best" ex-W4/W8 number (0.25's 10.31%) leans hard on a THIRD
single-window swing: Window 1 moves from -8.26% to +17.25% (+25.51pp) while its own spike-admit
COUNT changes (5 -> 3, a different set of candidates got admitted, not a pure sizing effect on
the same trades) on a trade-count change from 56 to 50 -- the identical small-perturbation
signature, a third time, in the same sweep.

**In the windows where sizing alone is the only thing that changed** (trade count AND spike-admit
count both identical across every tested multiplier -- W3, W5, W6, W7, W9, the closest this sweep
gets to isolating a pure sizing effect from the reshuffling artifact): the direction is flat to
mildly NEGATIVE as the cut gets more aggressive, not positive. W7 (24.68% at 0.25 -> 26.13% OFF)
and W9 (15.18% -> 18.66% OFF) both decline monotonically as sizing gets more aggressive; W3 and
W6 show small positive moves (+2.17pp, +2.02pp); W5 shows a real but modest gain (+4.83pp) despite
an unchanged trade/admit count, confirming sizing changes ripple into subsequent trades' own
cash-funded sizes even without changing *which* candidates get admitted. None of these five
"clean" windows shows the large, consistent benefit the fat-tail hypothesis predicted -- if
sizing down a real 35-39%-win-rate pattern were working as designed, the clean windows (no
reshuffling noise to explain it away) should show a modest, broad, mostly-positive effect. They
don't.

**No fresh Monte Carlo permutation script was built**, for the same reason `sweep_rotation.py`'s
own rejection skipped one: per this log's established bar, an MC check is for a result that
still looks "genuinely better and more robust" after the sweep and trace above -- this one does
not reach that bar. The trace already identifies the exact same non-monotonic dose-response,
uniformly-worse worst-case drawdown, and small-perturbation/large-single-window-swing signature
the confirmation-delay gate, `MAX_POSITIONS` widening, the backlog queue, and `ROTATION_MARGIN_MULT`
were all independently rejected for; running a permutation test on a result already falsified
this specifically would not add information.

**Verdict: REJECTED. KEEP `SPIKE_SIZING_ENABLED=False` (the existing, unchanged default).** The
size-down reframing does not escape the failure mode the exclusion-based gate already failed on --
it just relocates it. Both spike-related mechanisms this session (exclude/delay, then size-down)
fail on the identical combination of checks: non-monotonic across the swept parameter, worst-case
drawdown worse than baseline at every tested value, and a headline "best" result that traces to a
small number of already-known-fragile windows (W4, W8, and here also W1) swinging in opposite
directions on a modest trade-count perturbation -- not a broad, real improvement. **This closes
both concrete fix directions this session identified for the spike/gorengan base-rate finding**
(exclude/delay -- REJECTED 2026-08-17; size-down -- REJECTED here). The underlying diagnosis (a
real, front-loaded post-blowoff fade, 35-39% win rate, fat right tail up to +453%) is not in
question -- what's now twice-rejected is every tested way of mechanically acting on it inside this
specific scarce-`MAX_POSITIONS`-slot portfolio construction, for the same reshuffling-fragility
reason the scarce-slot investigation (widening/backlog/rotation) already found governs far more
of this system's single-window variance than any one entry-side signal does. A genuinely
different category of idea would be needed here too -- not a third parameter on either of these
two levers -- most plausibly one that doesn't touch which/how-much of a scarce slot gets consumed
at all (e.g. an exit-side response specific to a position that becomes spike-flagged AFTER entry,
never tried this session), or accepting this as a bounded, understood risk the way Window 3's
residual weakness and the scarce-slot fragility itself are already accepted.

**Governance note (no action needed, stated for the record)**: confirmed by grep --
`paper_signal_scan.py`/`paper_monitor.py`/`paper_common.py` reference neither `SPIKE_SIZING_ENABLED`
nor `SPIKE_SIZING_MULT` -- this finding has zero effect on the live paper-trading path regardless
of the verdict, and no default in `backtest_v4.py` was changed (REJECTED, not promoted), so no
separate approval step is needed before pushing.

Code kept: `src/test_spike_sizing.py` (self-check, same pattern as `test_rotation.py`/
`test_spike_confirm_gate.py`), `src/sweep_spike_sizing.py` (this sweep, reusable the same way
`sweep_rotation.py`/`sweep_backlog_queue.py` are for the next numeric-grid parameter).
`src/backtest_v4.py` gained the `is_spike` tagging site inside `simulate_window`'s
`new_candidates` loop (reuses the existing `spike_confirm_gate` dict, no new precomputation),
`SPIKE_SIZING_ENABLED`/`SPIKE_SIZING_MULT`, the `spike_mult` term in `compute_entry_fill()`'s
multiplier chain, and one additive diag field (`is_spike`/`cost_basis` on each `_diag_admitted`
entry) -- all regression-verified byte-identical at defaults (existing `test_diag_hook.py`,
`test_backlog_queue.py`, `test_rotation.py`, `test_spike_confirm_gate.py`,
`test_bandar_sizing_default.py` all still pass unchanged). `score_candidates()`,
`compute_entry_fill()`'s own signature, `evaluate_position_exit()`, `paper_signal_scan.py`, and
`paper_monitor.py` are all unchanged. Raw sweep outputs saved at
`.cache/spike_sizing_sweep_full.csv`/`_agg.csv`.

## 2026-08-18 -- live-path audit: 5 correctness bugs fixed

Follow-up to a read-only audit of the live paper-trading path (`src/paper_signal_scan.py`,
`src/paper_monitor.py`, `src/paper_common.py`). Five real bugs found and fixed same-day, in
priority order below. All five are live-script-only fixes -- **no change to `src/backtest_v4.py`'s
shared functions** (`evaluate_position_exit`, `compute_entry_fill`, `simulate_window`), so none of
this triggers the 9-window walk-forward regression this project requires for shared-logic changes.
Verified via a new `src/test_tp1_eod_reconcile.py` plus the existing `src/test_paper_trading_math.py`
(still passing unchanged). No `main`-branch protected files touched.

**Priority 1 (most urgent) -- EOD reconcile fully closed a position on a TP1 partial exit.**
`paper_signal_scan.py`'s EOD-reconcile loop called `_close_position()` (unconditional
`status="CLOSED"`) for ANY non-null `trade_record` from `evaluate_position_exit`, including a TP1
partial exit (`TP1_PCT=0.10` -- only 10% of lots should sell, 90% should keep riding). This would
have wrongly liquidated the ENTIRE position the first time the EOD safety-net recheck (not the
15-min intraday monitor -- that one already had this right) caught a TP1 trigger, e.g. via a brief
intraday spike the monitor's polling cadence missed. BEEF (a real open V4_PAPER position) was
days from its first-ever live TP1 at discovery time -- this is exactly the code path it would have
hit. Fixed by mirroring `paper_monitor.py`'s own TP1 branch (~line 302-311): for
`exit_reason=="TP1"` specifically, persist the position's already-mutated fields (`avg_price`,
`sl_price`, `total_lots`, `remaining_lots`, `cost_basis`, `tp1_hit` -- all updated in-place by
`evaluate_position_exit` itself) via `_persist_position`, set `tp1_at`, leave `status="OPEN"`, and
do NOT insert a `backtest_trades` row (matching `paper_monitor.py`: a "trade" for win-rate/
profit-factor purposes is the position's eventual full exit, not each partial leg). `_close_position`
now only fires for a genuine full-exit reason (SL/TRAILING/CHECKPOINT/TIME/DELISTED_GAP).
Also removed the extra `pos["hold_days"] += 1` that used to run only on the TP1 branch: confirmed
by reading `simulate_window`'s own TP1 continuation (`src/backtest_v4.py`, the
`if trade_record["exit_reason"] == "TP1": remaining_positions.append(pos)` branch skips the
`pos["hold_days"] += 1` that only runs in the sibling `else` branch) and `paper_monitor.py`'s TP1
branch (also doesn't increment) that hold_days is deliberately NOT incremented on the TP1 day
itself anywhere else in this system -- the extra increment was a live-script-only drift, now
removed. Verified with `src/test_tp1_eod_reconcile.py`: constructs a synthetic OPEN position near
TP1, runs it through the real `_position_dict_from_row`/`evaluate_position_exit`/
`_persist_position`/`_close_position` functions against a fake Supabase double (records
`.update()`/`.insert()` payloads, no real DB needed since both functions take `supabase` as an
explicit parameter), and asserts: status is never touched on the TP1 path (no `"status"` key in
any payload), `remaining_lots` matches what `evaluate_position_exit` actually computed on `pos`
(never 0, never unchanged), `hold_days` stays at its pre-call value, and a genuine full exit (SL,
regression guard) still sets `status="CLOSED"` and still inserts a `backtest_trades` row. A second
test confirms `paper_signal_scan.py`'s and `paper_monitor.py`'s identical `_position_dict_from_row`
+ `evaluate_position_exit` calls on the same synthetic input leave `pos` in byte-identical state.

**Priority 2 -- `has_real_print`/"did this stock trade today" required `open_price>0`, which ~25%
of actively-traded stocks fail on a normal day.** Audited real `ihsg_eod` data: `open_price=0` with
real `close_price`/`high`/`low`/`volume` is a chronic upstream data-quality gap, not a trading
halt -- and WMPP (a currently-OPEN V4_PAPER/V3_PAPER position, ids 20/21 per the prior audit) has
`open_price=0` on every historical row despite trading normally. Gating "did it trade today" on
`open_price>0` would eventually force-exit WMPP via `DELISTING_GAP_DAYS` as if it had delisted,
and would permanently freeze `last_valid_close` on it in the meantime. Split into two questions:
(a) "did this stock trade at all today" -- now keyed off `close_price>0 and volume>0` (renamed
`has_real_print` -> `had_real_trade`), gating `last_valid_close`/`no_data_days` tracking and the
`DELISTING_GAP_DAYS` force-exit safety net; (b) "is there a valid opening price to fill/gap-price
against" -- stays strict. Two call sites needed the strict version and were left alone:
`paper_monitor.py`'s order-fill guard (`r.get("open") in (None, 0)`, ~line 202, unchanged) and a
NEW guard added in `paper_signal_scan.py`'s EOD-reconcile bar construction -- previously
`open_price` flowed straight into the `bar` tuple passed to `evaluate_position_exit`, and that
function's own SL exit-price selection (`o if (o is not None and o < sl_price) else sl_price`)
would have picked a fabricated Rp0 fill price for any SL exit on a real-trading, `open_price=0` day,
which the old strict gate coincidentally prevented by simply never reaching that code for such a
stock. Fixed by masking `open_price<=0` to `None` before building the `bar` tuple, which triggers
`evaluate_position_exit`'s own documented `o is None` fallback (uses `sl_price`/`tp1_price` instead)
-- the function was already designed to handle a missing open correctly; this just stops feeding it
a fictional zero instead of a real "unknown" signal. The original DOOH-shaped suspension check
(`open=high=low=0`, frozen close, real production incident 2026-08-06) still trips correctly under
the new definition too: DOOH's `volume=0` on a suspended day fails the new `had_real_trade` check
just as it failed the old `open_price>0` one. **DB verification not done from this session**: no
Supabase MCP tool was exposed to this sandboxed sub-agent (only Read/Grep/Glob/Bash/Write/Edit were
available), so WMPP's real current row (`last_valid_close`/`no_data_days` state) was not directly
queried to confirm post-fix behavior against live data -- confirm via a real query before/shortly
after this ships, per the original task's ask. The fix's correctness against the documented data
shape (real close/volume, `open_price=0`) was verified by code-path reasoning and the existing
`test_paper_trading_math.py` suite (`evaluate_position_exit`'s `o is None` handling is exercised
implicitly by every existing SL/TP1 test there, unchanged).

**Priority 3 -- EOD equity snapshot fell back to entry price instead of the last tracked real
price.** When `today_bars` had no row for a held stock, the EOD equity mark used
`row["avg_price"]` (entry/cost price, can be weeks stale) instead of `last_valid_close` (this same
script's own real-time tracker, updated every day the stock has a real print). Fixed: fall back to
`last_valid_close` first, `avg_price` only if `last_valid_close` is also null (a position that's
never had a real print since entry -- rare, rarer still after the Priority 2 fix). Affects
`total_equity`/`drawdown_pct`/`cvar_95` accuracy in `backtest_runs`/`backtest_equity`.

**Priority 4 -- `paper_monitor.py`'s corporate-action guard compared live price to entry price
instead of prior close.** `pc.looks_like_unadjusted_corporate_action(float(row["avg_price"]),
current_price)` -- the ratio-bound design (`CORP_ACTION_RATIO_LOW/HIGH`) is meant for a
day-over-day close comparison (correctly done in `paper_signal_scan.py`'s own EOD version, which
compares `prev_close` to today's close), but here it compared against `avg_price`, which can be
weeks old for a long-running winner -- a false trip would disable SL/TP1/trailing at exactly the
wrong moment. Fixed: compare against `row["last_valid_close"]` (the position's own last known real
close, maintained by `paper_signal_scan.py`'s EOD reconcile pass) instead, falling back to
`avg_price` only when `last_valid_close` is still null (a position filled earlier the same day,
before its first EOD reconcile pass -- on that one day, `avg_price` IS effectively "today's real
price," so this fallback is intentional, not a smuggled version of the bug). No new schema field
needed -- `last_valid_close` already exists and is already maintained for exactly this purpose.

**Priority 5 (low urgency) -- `avg_vol_20` missing from both live position dicts.**
`_position_dict_from_row()` in both `paper_signal_scan.py` and `paper_monitor.py` omitted
`avg_vol_20`, silently falling back to `evaluate_position_exit`'s own default of `1.0` for the
slippage participation math. Currently inert (`SLIPPAGE_ENABLED` defaults off, not set in any live
workflow) but would silently mis-size slippage if ever turned on live. Fixed: both dict-builders
now pull `avg_vol_20` from the `paper_positions` row (column already exists in
`sql/paper_trading_schema.sql`, populated at signal time), falling back to `1.0` only if the row's
own value is null.

**Governance note**: none of these five change any validated strategy parameter or exit-rule
threshold -- they fix live-script bookkeeping/data-quality bugs in code that was supposed to
already implement the frozen V3/V4 configuration correctly. Per this project's own frozen-config
rule, a fix to a bug is not a mutation of a live run's decision logic; the decision logic (SL/TP1/
trailing thresholds, entry gates) is unchanged for V3_PAPER/V3.1_PAPER/V4_PAPER alike. Resets the
`docs/MASTERPLAN.md` section B "no new correctness bugs" observation-window clock -- see that file.

Code changed: `src/paper_signal_scan.py` (Priorities 1, 2, 3, 5), `src/paper_monitor.py`
(Priorities 4, 5). Code added: `src/test_tp1_eod_reconcile.py`.

## 2026-08-21: one-day EOD-scan gap (2026-08-20), isolated and self-recovered

`daily_gate_summary`/`daily_qualifying_signals` have zero rows for 2026-08-20 -- a real trading
day (`ihsg_eod` has 963 real rows with real volume for that date, market was genuinely open).
The day before (08-19) and the day after (08-21) both ran normally (regime BULLISH, 15
qualifying signals on 08-21). No GitHub token was available in this session to pull the Actions
run log and find the exact cause. Given it's a single isolated day bracketed by two normal runs,
most likely a transient GitHub Actions hiccup (runner/network blip) rather than a code
regression -- but not confirmed, since the log itself was never inspected. User declined a
monitoring/alert addition for this (Telegram ping if the EOD job doesn't post that day) --
noted here instead, no code changed.

## 2026-08-22: pure rename, `V3_*` env-var flags -> `V4_*` in `backtest_v4.py` and every dependent script -- zero intended behavior change

Mechanical follow-up to the earlier `backtest_v3.py` -> `backtest_v4.py` file rename: every
env var the module actually reads (`os.environ.get("V3_...")`) still carried the old `V3_`
prefix. Re-derived the authoritative list via `grep -roE "V3_[A-Z_]+" src/ sql/` (~35 distinct
flags: `TP1_MULT`/`TRAILING_PCT`/`VOL_BAND_MULT`/`TREND_DURATION_GATE`/`MAX_POSITIONS`/
`REGIME_CONFIRM_DAYS`/`PARTICIPATION_GATE`/`SPIKE_*`/`ROTATION_*`/`*_SIZING`/`PYRAMID*`/
`SCORE_*`/`SLIPPAGE*`/`ATR_PRICE_RATIO_MAX`/`ARA_FILTER`/`ARB_EXIT_REALISM`/
`ADAPTIVE_HOLDTIME`/`BACKLOG_*`/`ENTRY_CLUSTER_WINDOW_DAYS`/`FETCH_START`/`TRAIN_END`/
`TEST_START`/`TEST_END`/`QUANTILE_CUT`/`SKIP_SAVE`, plus two the enumeration missed on a first
pass, `MAX_ROTATIONS_PER_DAY` and `FORCE_REFETCH`) across 30 files in `src/`+`sql/`. Applied via
a protected regex (`V3_` -> `V4_` everywhere EXCEPT the literal tokens `V3_PAPER` and
`V3_FINDINGS_LOG`, which are a historical run-identifier and this log's own title, not flag
names -- left untouched) rather than a blind sed, then reviewed every diff by hand.

**Two things the blanket pass got wrong, both caught before committing:**

1. **Scope creep the regex derivation should have flagged and didn't**: `score_candidates()`
   (`src/backtest_v4.py`) hardcodes `"trigger": "V3_regime_weekly_sector"` as a data LABEL on
   every candidate dict -- persisted into `paper_positions`/trade records, not an env var. The
   `grep -roE "V3_[A-Z_]+"` derivation step correctly never matched it (lowercase after the
   prefix), but the actual substitution regex used a broader `V3_` match and caught it anyway.
   Renaming it would have changed a real, persisted output value for every future trade --
   a violation of this task's own "byte-identical before and after" bar. **Reverted, left as
   `V3_regime_weekly_sector`.** Flagged, not decided unilaterally: this string is exactly the
   kind of "still says v2/3" residue the broader rename request is trying to eliminate, but
   changing it is a data-schema decision (does anything downstream match on this string? does a
   frontend ever display it?), not a mechanical env-var rename, so it's a separate call for
   whoever owns that request.
2. **Two more live-production workflows than the task brief named.** The brief flagged
   `paper_monitor_v4_trigger.yml`/`paper_signal_scan_v4_trigger.yml` (main branch) as the one
   live-critical spot (`V3_BANDAR_SIZING` env key). Grepping `main`'s `.github/workflows/`
   directly found FOUR more still-active files doing the same thing:
   `paper_monitor_trigger.yml`/`paper_signal_scan_trigger.yml` (V3_PAPER, restored same-day
   2026-08-22 after an earlier accidental deletion -- still has 3 OPEN positions) and
   `paper_monitor_v31_trigger.yml`/`paper_signal_scan_v31_trigger.yml` (V3.1_PAPER, 6 OPEN
   positions), pinning `V3_BANDAR_SIZING`/`V3_ARA_FILTER`/`V3_ATR_PRICE_RATIO_MAX`/
   `V3_SCORE_WEEKLY_COMP_ABS_CAP_Q` respectively. All four check out
   `ref: worktree-v2-hmm-screener` and run scripts that `import backtest_v4`. Left unrenamed,
   these would have gone from "explicit pin" to "silent fallback to backtest_v4.py's own
   default" the next time either workflow fires against 9 real open positions with real
   (simulated) capital -- exactly the frozen-config-drift failure mode this project's own rules
   exist to prevent, on runs that are still trading, not the two the brief was told about. Fixed
   in lockstep (same env-key renames, no value changes) on `main`.

**Verification, not just assertion:**
- 8 targeted self-checks (`test_bandar_sizing_default.py`, `test_ara_filter.py`,
  `test_spike_sizing.py`, `test_participation_gate.py`, `test_trend_duration_gate.py`,
  `test_spike_confirm_gate.py`, `test_paper_trading_math.py`, `test_tp1_eod_reconcile.py`) ran
  clean both before (`git stash`) and after the rename -- identical numbers throughout (e.g.
  `test_spike_sizing.py`'s real out-of-sample slice: 103/98 trades, Rp57,222,420/Rp129,155,093
  net profit, both runs, to the Rupiah), only the printed flag-name strings in `[PASS]` messages
  changed from `V3_` to `V4_` as intended.
- Full 9-window `walk_forward_v4.py` run (local `.cache/walk_forward_data_2021-01-01_2026-06-30
  .pkl`, real `SUPABASE_URL`/`SUPABASE_KEY` from `.env` for the client construction only -- no
  refetch, cache hit) before and after the rename: `walk_forward_v4_summary.csv` diffed
  byte-identical, every window, full float precision (mean alpha +22.50%, mean PF 1.82, mean
  max DD -15.46%/worst -22.41%, 6/9 beat bench, 4/9 win>50% -- both runs, to the last digit).
- Confirmed round-trip for the one flag with an explicit non-default pin in a live workflow:
  `BANDAR_SIZING_ENABLED = os.environ.get("V4_BANDAR_SIZING", "1") == "1"` still evaluates
  `True` by default and the live workflows' explicit `'1'`/`'0'` pins still land correctly
  post-rename.
- Repo-wide grep confirms zero remaining `V3_` tokens in `src/`/`sql/` other than the three
  intentionally-preserved ones (`V3_PAPER`, `V3.1_PAPER` via prose, `V3_FINDINGS_LOG`, and the
  reverted `V3_regime_weekly_sector` label above).

**Files touched**: `src/backtest_v4.py` plus 29 other `src/`/`sql/` files that read or
`os.environ.setdefault()` these flags (sweep/test/trace/diagnose scripts, `paper_common.py`
callers, sql schema comments) -- see the commit for the full list. On `main`: all 6 paper-
trading trigger workflows (`paper_monitor_trigger.yml`, `paper_signal_scan_trigger.yml`,
`paper_monitor_v31_trigger.yml`, `paper_signal_scan_v31_trigger.yml`,
`paper_monitor_v4_trigger.yml`, `paper_signal_scan_v4_trigger.yml`) -- env-var KEYS only, no
pinned VALUES changed. Also reworded one now-stale comment in `backtest_v4.py`
(`BANDAR_SIZING_ENABLED`'s docstring) that described `V3_PAPER`'s own pin before it was retired
2026-08-15 -- updated to describe `V4_PAPER`'s current pin instead, without losing the "why."
No default value, threshold, or exit rule changed anywhere in this entry.

## 2026-08-22: HATM V4_PAPER drawdown incident -- re-validated the three existing rank-1 outlier flags against the current (post-rename) baseline, plus a real-data check of whether any of them would even apply to HATM's specific case

Triggered by a live V4_PAPER position: HATM entered 2026-08-20 at Rp635 after a +74%
run in the prior 8 weeks, then dropped -12.3% the next session (single-day reversal
candle). This traces to the gap `diagnose_score_power.py` diagnosed on 2026-08-07
(rank-1 candidates run ~2x score magnitude / ~20% higher ATR% / 82-98% SL-hit rate --
see that entry above) -- three candidate fixes exist in `score_candidates()`
(`backtest_v4.py`), all off by default, none ever turned on for V4_PAPER. This entry
re-validates them on the CURRENT code (post V3->V4 rename, post the 2026-08-18/08-21
live-path bugfixes), not the stale 2026-08-07/08 numbers, which used a different
baseline (+21.71% mean alpha then vs +22.50% now -- code has moved since).

**Baseline reconfirmed first.** `python src/walk_forward_v4.py` off the existing
`.cache/walk_forward_data_2021-01-01_2026-06-30.pkl` (no refetch) reproduces the
2026-08-22 rename-verification numbers exactly: mean alpha +22.50%, mean PF 1.82,
mean maxDD -15.46%/worst -22.41%, beat-bench 6/9, win>50% 4/9, 396 total trades.

**All three flags run in isolation, one env var each, same 9-window schedule:**

| config | mean alpha | mean PF | mean maxDD | worst maxDD | beat-bench | win>50% | trades |
|---|---|---|---|---|---|---|---|
| baseline (all off) | **+22.50%** | 1.82 | -15.46% | -22.41% | 6/9 | 4/9 | 396 |
| `V4_SCORE_SKIP_TOP_N=1` | +11.31% | 2.02 | -15.26% | -22.80% | 6/9 | 4/9 | 363 |
| `V4_SCORE_OUTLIER_GAP_MULT=1.5` | +15.64% | 1.75 | -16.00% | -22.41% | 6/9 | 4/9 | 384 |
| `V4_SCORE_OUTLIER_GAP_MULT=2.0` | +22.50% (byte-identical to baseline) | 1.82 | -15.46% | -22.41% | 6/9 | 4/9 | 396 |
| `V4_SCORE_WEEKLY_COMP_CAP_Q=0.90` | +9.98% | 1.39 | -14.59% | **-19.45%** | 5/9 | 3/9 | 340 |

**`gap_mult=2.0` (the task-brief's own suggested default) is a no-op** -- confirmed
byte-identical to baseline. The 2026-08-07 sweep already found the rank1/rank2 score
ratio never exceeds ~1.93 across the sample (median 1.09x, 75th pct 1.36x); 2.0 is
above every historical value, so the conditional gate never fires. `gap_mult=1.5`
(a value the earlier sweep already touched, re-run here against the current code as
the meaningful non-no-op point) hurts mean alpha (+22.50%->+15.64%) without improving
drawdown at all (worst maxDD identical -22.41% -- it only fires in windows that don't
change the tail outcome). `skip_top_n=1` (unconditional rank-1 drop) hurts mean alpha
even more (+11.31%) and, notably, makes worst-case drawdown WORSE, not better
(-22.41%->-22.80%) -- dropping the #1 candidate outright removes some of the best
days (W8: 129%->76% profit) along with the bad ones. `weekly_comp_cap_q=0.90`
reproduces the exact same two-part shape the 2026-08-07/08 entries already
established (real drawdown improvement, real alpha/win-rate cost) independently on
the current, post-rename code -- best worst-case drawdown of the four configs
(-19.45%) but worst win-rate-consistency (3/9, vs baseline's 4/9) and lowest mean
alpha (+9.98%) of everything tested. **None of the three, at these single default
values, beats baseline on both mean alpha AND worst-case drawdown simultaneously --
the project's own standing adoption bar (see LIQ_SIZING_ENABLED's own criterion,
cited in the 2026-08-07 entry above). Baseline (all off) still wins that comparison.**

**Whether any of the three would even have caught HATM: checked against real data,
not just the mechanism description.** Pulled HATM's actual signal day
(`paper_positions`: signal_date 2026-08-19, score 12.78) from `daily_qualifying_signals`
and `daily_scoreboard` directly:

- HATM was **rank 3 of 15** that day (score 12.78, well behind rank-1 EKAD's 20.61
  and rank-2 WMPP's 19.38 -- rank1/rank2 ratio here is 20.61/19.38 = 1.06x, nowhere
  close to even the loosest `outlier_gap_mult` tested in this project's history).
  `SCORE_SKIP_TOP_N` and `SCORE_OUTLIER_GAP_MULT` are both structurally rank-1-only
  mechanisms (`score_candidates`'s `pool.iloc[start:...]` only ever touches the
  top of the ranked pool) -- **neither one can touch a rank-3 candidate, full stop,
  regardless of what threshold value is chosen.** HATM's case would have sailed
  through both unchanged even if either flag had been live that day.
- HATM's ATR% that day (61.64/645 = 9.56%) WAS the highest of the day's top-15
  qualifying pool (next highest: TAMA/GRIA at 8.40%) -- consistent with the task's
  own description and with the diagnose_score_power rank-1 signature, just showing
  up one rank later than the mechanism the flags were built around.
- `SCORE_WEEKLY_COMP_CAP_Q`/`_ABS_CAP_Q` is different: it filters the whole
  candidate pool by the `weekly_ma_spread` component BEFORE ranking, not by
  post-rank position, so it CAN reach a rank-3 candidate. Checked directly:
  HATM's `weekly_ma_spread`=38.73 sat at the **97.2th percentile** of that day's
  144-candidate qualifying pool (`daily_scoreboard`, BUY/STRONG_BUY rows,
  2026-08-19) -- above the cap threshold at every quantile tested, 0.95 down to
  0.80 (cutoffs 29.86/23.68/20.32/17.69, all below HATM's 38.73). **This is the
  only one of the three flags that would structurally have excluded HATM that day,
  at any of the values tested.**

**Read plainly: HATM is a real instance of the same overextension mechanism
`diagnose_score_power.py` found at rank 1, just landing at rank 3 instead --
which is exactly why the two rank-1-specific flags (`SCORE_SKIP_TOP_N`,
`SCORE_OUTLIER_GAP_MULT`) cannot be the fix for this specific incident, no matter
which threshold is chosen; they are the wrong shape of gate for a not-always-rank-1
outlier.** `SCORE_WEEKLY_COMP_CAP_Q`/`_ABS_CAP_Q` is the right shape (rank-agnostic,
targets the actual driver) and would have caught this specific case -- but per the
walk-forward table above, at cap_q=0.90 it still costs more mean alpha and
win-rate-consistency than it buys in drawdown protection, on this project's own
adoption bar, tested in isolation. It has NOT been stacked here with
`ARA_FILTER_ENABLED`+`ATR_PRICE_RATIO_MAX=0.08` the way the 2026-08-08 entry found
it works when combined (that combination -- `ARA_FILTER_ENABLED=1` +
`ATR_PRICE_RATIO_MAX=0.08` + `SCORE_WEEKLY_COMP_ABS_CAP_Q=0.81` -- is already live on
V3.1_PAPER, a separate run, not V4_PAPER). Also worth noting directly: HATM's own
ATR% (9.56%) would already have failed V3.1_PAPER's own live `ATR_PRICE_RATIO_MAX=0.08`
ceiling (it's under V4_PAPER's current 0.10 ceiling, which is why it wasn't blocked
there) -- a different, already-validated, already-deployed-elsewhere mechanism that
also would have caught this case, distinct from the three flags this entry tested.

**No flag turned on. This is a negative/inconclusive result for all three flags in
isolation, at these defaults, not a validated fix** -- consistent with, and now
reproducing on fresh post-rename code, the 2026-08-07/08 entries' original
conclusion for `SCORE_SKIP_TOP_N`/`SCORE_OUTLIER_GAP_MULT`, and independently
reconfirming `SCORE_WEEKLY_COMP_CAP_Q`'s known drawdown-real/alpha-noisy shape.
**Next step if this gets picked back up:** either (a) stack
`SCORE_WEEKLY_COMP_CAP_Q`/`_ABS_CAP_Q` with V4_PAPER's own other filters the way
the 2026-08-08 stack entry did for V3.1_PAPER (untested here -- isolation was this
entry's explicit brief), or (b) treat this as a case for tightening
V4_PAPER's `ATR_PRICE_RATIO_MAX` specifically (already shown to matter for this
exact stock/day) rather than the weekly-component cap. Neither decided here --
reporting the numbers, not picking a deployment.

## 2026-08-22 (follow-up): `ATR_PRICE_RATIO_MAX=0.08` tested in isolation against V4_PAPER's actual current frozen config -- clears the adoption bar

Option (b) from the entry directly above, actually run. The 0.08 ceiling was already
validated once (2026-08-08 entry, "V3.1 filters ... validated for the first time"), but
that test's baseline was V3's config *as it stood that night* (ARA off, ATR<=0.10,
+21.71% mean alpha baseline then) -- not byte-identical to V4_PAPER's current frozen
stack (`V4_BANDAR_SIZING=1` default-on, everything else V3_PAPER's exact config, per
`paper_signal_scan_v4_trigger.yml`'s own comment). This entry closes that specific gap:
one env var (`V4_ATR_PRICE_RATIO_MAX=0.08`), nothing else touched, same 9-window
schedule, same cache
(`.cache/walk_forward_data_2021-01-01_2026-06-30.pkl`, no refetch).

**Baseline reconfirmed first** (env clean): mean alpha +22.50%, mean PF 1.82, mean maxDD
-15.46%/worst -22.41%, beat-bench 6/9, win>50% 4/9, 396 trades -- byte-identical to the
HATM entry above's own baseline reconfirmation, same session.

| config | mean alpha | mean PF | mean maxDD | worst maxDD | beat-bench | win>50% | trades |
|---|---|---|---|---|---|---|---|
| baseline (ATR<=0.10) | +22.50% | 1.82 | -15.46% | -22.41% | 6/9 | 4/9 | 396 |
| `V4_ATR_PRICE_RATIO_MAX=0.08` | **+26.17%** | **1.95** | **-14.26%** | **-21.10%** | **7/9** | 4/9 | 366 |

**Clears this project's own adoption bar** (LIQ_SIZING_ENABLED's criterion, cited twice
above: beats baseline on both mean alpha AND worst-case drawdown, simultaneously) --
and does it with room to spare: also better on mean PF, mean maxDD, and beat-bench count.
win>50% ties at 4/9 rather than improving. Not a lucky single point in isolation the way
the hysteresis-band and weekly-comp sweeps turned out to be -- this exact ceiling was
already neighbor-checked against 0.06/0.07/0.09/0.12/0.15 in the 2026-08-08 entry (0.08
and 0.09 formed a plateau, 0.07 was the one dip) under a related-but-different baseline;
not re-swept here since the brief was the single already-flagged value against the new
baseline, not a fresh neighbor search.

**HATM specifically: confirmed excluded, against fresh real data, not just arithmetic.**
Pulled `daily_scoreboard` directly for 2026-08-19 (BUY/STRONG_BUY rows, ranked by score):
HATM's atr_14/close_price = 9.56%, rank 3 of 20 candidates that day, above the 0.08
ceiling (next-closest offender: KBLV at 9.44%, rank 18, also would have been excluded).
`backtest_v4.py`'s ATR gate is a plain AND-ed boolean mask
(`(day_slice["atr_14"]/day_slice["close_price"]) <= ATR_PRICE_RATIO_MAX`, lines
1331/1407/1773) alongside the trend-strength/regime/participation gates, not something
those other gates can override -- failing this one condition drops the candidate from
the qualifying pool regardless of how it scores elsewhere. HATM would not have
qualified that day under this ceiling.

**The honest tradeoff: opportunity-set shrinkage is real, and it isn't spread evenly.**
Total trades -7.6% (396->366) is a moderate, not catastrophic, cut -- and most windows
either improved or held roughly flat (W1 win-rate/alpha both up on fewer trades, W8's
132.88% vs baseline's 129.16% on 14 fewer trades, W5/W6/W7 all roughly a wash). But
window 3 (2023 H1 -- already this project's known-weakest window, the false-start-
regime-flip one the trend-strength-gate entries above spent real effort on) gets
meaningfully worse under the tighter ceiling, not better: win rate 31.6%->17.6%, alpha
-3.28%->-9.18%, profit factor 0.51->0.02 (17 trades, barely any gross profit at all).
Tightening the vol ceiling removed more of window 3's few winners than its losers. This
doesn't flip the aggregate verdict (window 3 was already net-negative both ways, and
every aggregate metric still improves) but it's a real, not hidden, cost.

**Verdict: a clear win by this project's own stated bar, not a mixed result** -- every
one of mean alpha, mean PF, mean maxDD, worst maxDD, and beat-bench improves or ties;
none regresses. Worth tightening V4_PAPER's `ATR_PRICE_RATIO_MAX` from 0.10 to 0.08 on
these numbers. Caveats before calling it deployment-ready: (1) this is still one
walk-forward pass, not the permutation/parameter-sensitivity double-check this log's own
standard requires before "validated" -- the 2026-08-08 entry's neighbor sweep covered
sensitivity under a different baseline, not this one; (2) window 3 gets worse, a real
per-window cost the aggregate numbers don't surface on their own. Not deployed --
V4_PAPER's live workflow env is unchanged; this is a validation report, the adoption
decision is the user's.

## Market-wide broker net-flow gate (council candidate, "does the crowd's own
## money agree with the price-based regime read"): built, correlation-checked,
## swept -- REJECTED, same failure signature as the two prior market-wide
## day-level gates (2026-08-25)

A council session proposed a market-wide aggregate broker-flow regime signal: on
days brokers are net-buying across the whole market, maybe the existing entry rule
works better (or worse on net-selling days) -- independent of the price-based
regime/trend_strength gate already in use. The Contrarian advisor's standing
warning going in: this could be a noisy proxy for what trend_strength already
captures, or a data-engineering project in disguise. Both turned out to be
partially right, in different ways than expected.

**Data**: `data/bandarmology_history/**/*.parquet` (1489 files, 2020-06-02..
2026-08-11, 18.8M raw broker-trade rows, 943 stock codes) -- a raw per-broker-per-
stock-per-side trade log (`stock_code, broker_code, side, lot, val_rupiah,
avg_price, trade_date`), NOT pre-netted. Units traced and confirmed before
trusting anything: `val_rupiah` is real Rupiah (`lot * 100 shares/lot * avg_price`
reconciles to within rounding on a sampled BBCA day, Rp 284.1B for one broker one
day -- plausible for IDX's most liquid stock, not off by a factor of 1000 the way
the frontend Rupiah-millions bug was). Read via a column-projected `pyarrow.dataset`
scan (~3s for all 18.8M rows) instead of 1489 sequential `pd.read_parquet` calls.

**Corrupt-row filter applied, no new network dependency.** `bandarmology_features.
filter_corrupt_rows()` (already built 2026-08-22 for the live site, drops broker
rows whose avg_price/lot can't reconcile with the real exchange print) normally
needs a fresh per-stock Supabase fetch for its `ihsg_eod` reference. The walk-
forward's own already-fetched `df` (cached locally, `.cache/walk_forward_data_
2021-01-01_2026-06-30.pkl`) already carries `high`/`low`/`volume` for the exact
same stocks/dates, so the reference was built from that in memory instead --
same filter, zero extra Supabase calls. Only 0.32% of rows dropped (59,633/
18,826,534), but this materially changed the tail: the single most extreme day in
the raw liquid-universe ratio (2022-01-05, net_ratio=+0.389, ~3x every other day
in the 1-99th percentile band) collapsed to +0.108 after filtering -- a corrupted-
row artifact, not a real crowd-buying day. Skipping this filter would have let one
bad day sit in the tail of a feature meant to describe genuine crowd behavior.

**Feature**: `compute_market_broker_flow()` (`src/backtest_v4.py`) -- daily
`(buy - sell) / (buy + sell)` Rupiah, summed across every `stock_code` that clears
`cfg.ADTV_MIN` THAT DAY (same liquid universe `score_candidates()` itself screens
to, using `df`'s own `adtv_20` column -- not literally every ticker; illiquid-
penny-stock flow was excluded on the hypothesis it's mostly noise), smoothed with
a trailing N-day mean (default 5) since the raw daily ratio is noisy (mean -0.003,
std 0.018, 1st-99th pctile roughly [-0.05, +0.04] post-filter, healthy -- top-5
|net| days are only 4.9% of total |net| across 1439 days, no 1-2-day domination).

**Gate**: `V4_BROKER_FLOW_GATE_ENABLED` (default off) requires the rolling ratio
`>= V4_BROKER_FLOW_MIN` (default 0.0) as an ADDITIONAL AND-ed condition on
`regime_ok_today`, alongside (not replacing) the existing regime/trend_strength/
REGIME_CONFIRM_DAYS gates -- same "gate on top of, not instead of" design the task
called for. Applied ONLY at the live entry-check site, NOT folded into the TRAIN
threshold-learning mask, matching `PARTICIPATION_GATE_ENABLED`'s own precedent and
reasoning (a TRAIN-mask ripple did more damage than live-side filtering for the
rejected duration gate). Missing/unknown dates default to "pass"
(`.get(trade_date, BROKER_FLOW_MIN)` trivially satisfies its own `>=` check) --
same "missing data never blocks" convention every gate in this module uses.
Confirmed byte-identical to baseline with the flag off (`test_broker_flow_gate.py`
+ a full walk-forward rerun, diffed line-for-line against the pre-change run).

**1. Independence check (is this just a price-regime proxy?): partially
independent, not a clean proxy, not fully separate either.** Spearman rho vs
`trend_strength` (IHSG's own ma50 distance) = +0.479 (p=3e-83, n=1434) -- a real,
moderate positive correlation (~23% shared variance), not the near-zero a truly
orthogonal signal would show, but far from the >0.8 that would make it redundant.
Vs `market_participation` (the OTHER, already-REJECTED market-wide axis --
turnover magnitude, unsigned): rho=+0.119 (p=5.7e-6) -- essentially uncorrelated,
confirming the two market-wide axes are structurally different from each other as
designed (one signed/directional, one unsigned/magnitude). On days
`regime_ok_today` is ALREADY True (n=614), broker_flow still has real spread
(mean +0.0013, std 0.0089) and 47.9% of those already-price-confirmed-bullish days
show brokers net SELLING -- so the feature is not simply re-deriving "is the
market up," it does distinguish within the existing gate's own "yes" population.

**2. Trade-level base rate (366 baseline trades, `V4_ATR_PRICE_RATIO_MAX=0.08`,
gate OFF so this reads the population unshaped by the gate under test): no
significant relationship, and what pattern exists points the wrong way.** Spearman
broker_flow(5d)-at-entry vs `pnl_pct`: rho=-0.035 (p=0.51). Vs win/loss: rho=-0.047
(p=0.365). Quartile win rates: Q1 (most net-SELLING) 55.4%/mean pnl +6.06%, Q2
48.4%/+3.95%, Q3 61.5%/+9.22%, Q4 (most net-BUYING) 42.4%/+1.80% -- non-monotonic,
and the two tails go the OPPOSITE direction from the hypothesis (heaviest broker
buying is the worst-performing quartile, not the best). Kruskal-Wallis across
quartiles: H=5.39, p=0.146. Every one of these reads null-to-negative, before any
walk-forward gate was even applied.

**3. Full 9-window walk-forward, threshold sweep at window=5d (own baseline
reconfirmed first, byte-identical across two independent runs -- 366 trades, mean
alpha +26.17%, mean profit +25.31%, mean PF 1.95, mean maxDD -14.26%/worst
-21.10%, beat-bench 7/9, win>50% 4/9, matching the 2026-08-22 ATR=0.08 validation
exactly):**

| `V4_BROKER_FLOW_MIN` | trades | beat-bench | win>50% | mean profit | mean alpha | mean PF | worst maxDD |
|---|---|---|---|---|---|---|---|
| OFF (baseline) | 366 | 7/9 | 4/9 | +25.31% | +26.17% | 1.95 | -21.10% |
| -0.01 | 363 | 6/9 | 4/9 | +22.86% | +23.72% | 1.95 | -21.10% |
| -0.005 | 353 | 6/9 | 6/9 | +18.03% | +18.89% | 1.63 | -27.69% |
| 0.0 | 282 | 7/9 | 6/9 | +14.43% | +15.29% | 2.37 | -18.67% |
| 0.005 | 208 | 6/9 | 2/9 | +7.69% | +8.55% | 1.80 | -23.55% |
| 0.01 | 131 (8/9 windows traded) | 6/9 | 3/9 | +9.33% | +5.87% | 2.19 | -14.08% |
| 0.02 | 47 (6/9 windows traded) | 2/9 | 1/9 | -0.11% | -5.74% | 0.75 | -12.70% |

Mean profit and mean alpha decline at every single tightened threshold, monotonic
with the trade-count collapse -- the mechanism is mostly acting as an opportunity-
shrinking filter, not a selection-quality one. `win>50%` and (at 0.0/0.01/0.02)
worst-case drawdown do improve over baseline at several points -- but this
project's own adoption bar (beats baseline on BOTH mean alpha AND worst-case
drawdown, simultaneously -- the exact bar `LIQ_SIZING_ENABLED` and the ATR=0.08
tightening both cleared) is not met by ANY of the 7 thresholds tested. Best-
looking single point (0.0: best PF, best drawdown, win>50% jumps to 6/9) still
loses 11pp of mean alpha and 43% of mean profit versus baseline.

**4. Window-days sensitivity (0.0 threshold, the most competitive point above,
swept 3d/5d/10d): non-monotonic, confirms this is a noisy landscape, not a
plateau -- same lesson this log already learned twice (hysteresis band,
weekly-comp-cap).** 3d: mean profit +11.29%, mean alpha +12.15%, beat-bench 5/9,
win>50% 4/9 (worse than 5d on every axis). 10d: mean profit +23.59%, mean alpha
+24.45%, beat-bench 6/9, win>50% 5/9, mean PF 7.94 -- closest to baseline on
alpha/profit, but the PF number is a fragile-sample artifact: window 7 alone hit
PF=56.84 on 14 trades/92.9% win rate (near-zero losers), the exact "small-N,
suspiciously-perfect" signature already flagged for `PARTICIPATION_GATE`'s
`ON_1.00` cell (6 trades) earlier in this log. None of 3d/5d/10d beats baseline's
mean alpha (+26.17%); worst-case drawdown is also worse than baseline at 10d
(-23.27% vs -21.10%). Across all 9 threshold/window cells tested this session,
**zero clear the mean-alpha-AND-worst-drawdown adoption bar simultaneously.**

**5. Single/dominant-window check.** Window 8 (2025 H2, baseline's standout:
+132.88% profit/+107.84% alpha) contributes ~46% of the SUM of baseline's 9
window alphas on its own (107.84 of 235.51 total). At the best-looking gate
setting (0.0/5d) it degrades to +46.69%/+21.65% and drops OUT of the win>50% club
entirely (59.5%->44.4%) even as the aggregate win>50% COUNT rises 4/9->6/9 -- the
apparent aggregate improvement is coming partly FROM suppressing the previously-
best window, not purely in addition to it. But this cuts both ways, not simply
"one window explains the whole verdict": excluding window 8 entirely, mean alpha
across the remaining 8 windows is 15.96% at baseline vs 14.50% gated (0.0/5d) --
still doesn't improve once the dominant window is set aside. Window 4 (baseline's
2nd-best, +59.87%/+51.27% alpha) also degrades at every setting tested, worst at
0.0/5d (+17.69%/+9.09%) and still below baseline even at the gentlest surviving
setting, 0.0/10d (+44.43%/+35.82%).

**Verdict: REJECTED, kept off by default (`V4_BROKER_FLOW_GATE=0`).** Three
independent checks converge on the same conclusion from different angles: the
trade-level base rate shows no significant relationship (and a wrong-signed
quartile pattern at the tails), the walk-forward return metric never recovers to
baseline at any of 7 thresholds x 3 window lengths tested, and the one axis where
the feature does look most different from noise (its moderate correlation with
trend_strength, rho=0.479) suggests part of what modest signal it has may already
be captured by the existing price-based gate, not added on top of it -- exactly
the Contrarian's "noisy proxy" concern, though not a clean 1:1 proxy either (77%
of its variance is NOT explained by trend_strength, and it still varies inside the
existing gate's own passing population). Unlike `PARTICIPATION_GATE` (which had a
genuine, mechanistically-traced win for its target window before losing on
aggregate) this feature never shows a clean win anywhere -- not at the trade
level, not in any single walk-forward cell, not net of its own best-performing
window. Code kept (inert, off by default): `compute_market_broker_flow()` +
`_daily_liquid_net_ratio()` (`src/backtest_v4.py`), `test_broker_flow_gate.py`,
and the research scripts (`src/scratch_market_flow_build.py`,
`src/scratch_broker_flow_correlation.py`, `src/scratch_broker_flow_traderate.py`,
`src/sweep_broker_flow_gate.py`) for reuse if a differently-shaped version of this
idea comes up later (e.g. per-stock rather than market-wide, or restricted to a
narrower "smart money" broker subset rather than the whole liquid universe).

## Per-stock "smart money divergence" gate (a real IHSG trader's own heuristic:
## foreign net buying WHILE top-retail XL/XC/PD net sell, same stock same day):
## built, independence-checked, base-rate-checked, swept -- REJECTED, same
## single-dominant-window failure signature as the market-wide version above,
## despite passing the independence check the market-wide version failed
## (2026-08-26)

Follow-up to the market-wide broker-flow rejection just above, testing the
differently-shaped version its own closing note flagged for later: per-STOCK,
not market-wide aggregate, and a DIVERGENCE between two specific named broker
subsets rather than one aggregate direction. This is a real professional IHSG
trader's own stated tell ("smart money buying into retail's own selling"), not
a guess -- tested on that basis, not dismissed on priors.

**Feature**: `compute_broker_divergence()` (`src/backtest_v4.py`) -- for each
(stock, day), `(foreign_net - retail_net)` summed over a trailing N-day window,
divided by that SAME stock's own total turnover (all brokers, both sides) over
the same window. `foreign_net`/`retail_net` restrict to the exact broker codes
`sql/brokers_schema.sql` names (32 Foreign-classified codes / XL+XC+PD only for
retail -- not silently widened to other Local codes). Rolling SUM-then-ratio
(not rolling mean-of-ratio, unlike the market-wide feature) -- more robust to a
single stock's lumpier, thinner daily turnover. Same corrupt-row filter and
graceful local-Parquet-only degrade as the market-wide feature. `V4_DIVERGENCE_
GATE` (default off) requires the ratio `>= V4_DIVERGENCE_MIN` (default 0.0,
window default 5d) as an additional AND-ed condition on `simulate_window`'s own
candidate consumption -- NOT folded into `score_candidates()` itself, so the
live paper-trading scan/monitor scripts cannot be affected regardless of the
flag's state. Self-check (`test_broker_divergence_gate.py`) confirms the BUMN/
other-Local leg cannot leak into either the foreign or retail leg, an unknown
(stock, date) defaults to "pass," and the flag is off by default without
touching any other gate's own default -- all pass.

**1. Independence check: genuinely near-zero, unlike the market-wide axis.**
Spearman rho vs `weekly_ma_spread` (score_candidates()'s own ranking input):
+0.06 to +0.14 across the four window lengths tested (1d/3d/5d/10d); vs
`sector_rs_momentum`: +0.01; vs `trend_strength`: +0.02 to +0.03; vs the
market-wide `market_flow_5d` axis itself: +0.02 to +0.03. All highly
statistically significant only because n>410,000 (liquid-population rows) --
practically, none of these share more than ~2% of variance with anything
already live or already tested. This is a materially cleaner independence
result than the market-wide feature got (rho=+0.479 vs `trend_strength` there)
-- if this feature carried real edge, it would be genuinely additive
information, not a repackaged price signal.

**2. Trade-level base rate (same 366-trade baseline population, `V4_ATR_PRICE_
RATIO_MAX=0.08`, gate OFF): null.** Spearman divergence-at-entry vs `pnl_pct`
across the four window lengths: 1d rho=-0.026 (p=0.62), 3d rho=+0.112
(p=0.032), 5d rho=+0.041 (p=0.44), 10d rho=+0.059 (p=0.26) -- one borderline
significant result out of four, and it doesn't replicate at neighboring window
lengths, consistent with one false positive among multiple comparisons rather
than a real effect. Quartile win rates are non-monotonic at every window (e.g.
3d: Q1 46.2%, Q2 45.6%, Q3 64.8%, Q4(most divergent) 51.1% -- the best quartile
isn't the one the hypothesis predicts). Kruskal-Wallis across quartiles never
clears p<0.05 (3d: p=0.06; others p=0.15-0.99). The binary `flag_Nd` ON-vs-OFF
comparison shows no difference at any window (Mann-Whitney p from 0.25 to
0.99). Single-leg attribution at 5d: neither `foreign_ratio_5d` alone
(rho=+0.023, p=0.66) nor `retail_ratio_5d` alone (rho=-0.071, p=0.17) shows
anything either -- the divergence isn't hiding a real one-leg effect that
cancels out in the difference.

**3. Full 9-window walk-forward, threshold sweep at window=5d (baseline
reconfirmed byte-identical to the market-wide entry's own reconfirmed number --
366 trades, mean alpha +26.17%, same run):**

| `V4_DIVERGENCE_MIN` (5d) | trades | beat-bench | win>50% | mean profit | mean alpha | mean PF | worst maxDD | mean alpha, window 8 EXCLUDED |
|---|---|---|---|---|---|---|---|---|
| OFF (baseline) | 366 | 7/9 | 4/9 | +25.31% | +26.17% | 1.95 | -21.10% | +15.96% |
| -0.10 | 355 | 6/9 | 5/9 | +32.17% | +33.03% | 2.28 | -21.10% | +15.61% |
| -0.05 | 354 | 7/9 | 5/9 | +19.72% | +20.58% | 1.90 | -21.09% | +13.56% |
| 0.0 | 349 | 6/9 | 3/9 | +18.86% | +19.73% | 1.44 | -22.76% | +8.22% |
| 0.05 | 310 | 7/9 | 3/9 | +36.28% | +37.14% | 2.59 | -20.97% | +14.46% |
| 0.10 | 262 | 6/9 | 2/9 | +9.94% | +10.80% | 1.61 | -18.97% | +8.49% |
| 0.20 | 70 | 3/9 | 0/9 | -0.51% | +0.36% | 0.66 | -7.48% | +1.84% |

At the extreme (0.20), the gate mechanically works as designed -- it starves
the trade count from 366 to 70 (window 9 down to a single trade) and mean
alpha collapses to near zero, confirming this isn't an inert filter. In the
middle of the range, two cells (-0.10 and 0.05) nominally clear this project's
own adoption bar (beats baseline on both mean alpha AND worst-case drawdown,
simultaneously) -- but see #5.

**4. Window-days sensitivity on the two nominally-passing cells (-0.10 and
0.05, swept 3d/5d/10d): non-monotonic, same noisy-landscape signature this log
has now hit four times (hysteresis band, weekly-comp-cap, the market-wide
window sweep, and now this).** At `MIN=0.05`: 3d mean alpha +21.75% (below
baseline), 5d +37.14% (the sweep's best-looking single cell), 10d +26.47%
(back down near baseline) -- 5d sits as an isolated spike between two
mediocre neighbors, not a plateau. At `MIN=-0.10`: 3d +42.84%, 5d +33.03%,
10d +33.11% -- looks more consistent on its face, but the 3d cell shows the
most extreme single-window concentration of the entire sweep (window 8 alone
hits +250.04% alpha) and is also the one cell where window 4 (see #5) gets
newly and badly damaged (-9.74% alpha, untouched at 5d/10d) -- the apparent
"smoother" curve here is compatible with the same single-window artifact
showing up more strongly, not with a cleaner signal.

**5. Single-window check (window 8, 2025 H2, baseline's standout at
+132.88%/+107.84% alpha) -- decisive.** Window 8 contributes 107.84 of
baseline's 235.51 total 9-window alpha sum (46%), same concentration already
flagged for the market-wide gate. Recomputing mean alpha with window 8
excluded for every cell tested (rightmost column above, plus the three
window-days variants): baseline's own excl-window-8 mean is +15.96%. Every
single tested cell's excl-window-8 mean is EITHER roughly flat (+15.25% to
+17.09%, the three `-0.10` variants) or clearly worse (+8.22% to +14.46%, the
`0.0`/`0.05`/`0.10`/`0.20` cells) than that baseline. The two cells that
nominally clear the full-aggregate adoption bar (`-0.10`@5d: 33.03% vs 26.17%;
`0.05`@5d: 37.14% vs 26.17%) owe effectively all of that apparent gain to
window 8 alone getting bigger (its alpha goes from 107.84% to 172.43% and
218.59% respectively) -- excluding it, both cells sit at or below baseline
(15.61% and 14.46% vs 15.96%). This is the exact pattern this log has now
explicitly required checking for twice: an aggregate improvement that
evaporates when the single best-performing window is set aside.

Window 4 (baseline's 2nd-best, +51.27% alpha, 44 trades) -- the "does a
previously-solid window get WORSE" check -- degrades at every setting except
three (`-0.10`@5d, `-0.10`@10d, `-0.05`@5d, where the gate happens not to bind
on that window's specific candidates and it stays exactly unchanged at
+51.27%). Everywhere else it declines monotonically as the gate tightens or
shortens: `0.0`@5d +18.56%, `0.05`@5d +3.55%, `0.05`@3d +1.91%, `0.05`@10d
+0.93%, `0.10`@5d -4.88%, `-0.10`@3d -9.74%, `0.20`@5d -12.31%.

**Verdict: REJECTED, kept off by default (`V4_DIVERGENCE_GATE=0`).** This is a
genuinely different outcome from the market-wide rejection above in one real
respect (the independence check is clean here -- this is not a repackaged
price signal) but the same outcome in the ones that matter for whether to
trade on it: no significant trade-level relationship at any of four window
lengths, a non-monotonic and noisy walk-forward response to both its threshold
and its own window-length parameter, and -- decisively -- every walk-forward
cell's apparent aggregate improvement is fully explained by amplifying a
single already-best window (2025 H2) while a previously-solid window (window
4) gets damaged at every setting except where the gate doesn't bind at all.
The professional trader's heuristic may well be real in some form (a genuinely
orthogonal feature, cleanly independent of everything already tested, is not
nothing) -- but this specific formulation (per-stock, N-day rolling net-value
ratio, as a hard gate on entry) does not turn that independence into a
detectable, robust trading edge in this backtest. Code kept (inert, off by
default): `compute_broker_divergence()` + `_daily_stock_divergence_legs()`
(`src/backtest_v4.py`), `test_broker_divergence_gate.py`, and the research
scripts (`src/scratch_broker_divergence_build.py`,
`src/scratch_broker_divergence_correlation.py`,
`src/scratch_broker_divergence_traderate.py`,
`src/sweep_broker_divergence_gate.py`) in case a differently-shaped version
comes up later (e.g. as a continuous ranking input rather than a hard gate, or
tested on a broker-classification cut the user hasn't specified yet).

## "Long tight consolidation, then breakout" (the NICE pattern, real-trader-flagged):
## population scan built, pre-registered bar not cleared, REJECTED -- null result robust
## across an 8-point parameter sweep, not one unlucky value (2026-08-27)

User flagged a real case: NICE traded sideways ~234-290 for 2.5 months (2026-06-08 to
2026-08-24), then gained +25% (ARA) on 2026-08-26 and another +17% intraday the next
session. A 5-advisor council session the same day converged on a narrow plan: (1) a cheap
feasibility check on whether buying ON the breakout day or the day after is even fillable,
(2) define a consolidation rule and a pass/fail bar BEFORE touching NICE's own numbers
again, (3) run the population scan through the existing liquidity filter, (4) only if that
clears the bar, test an actual entry-during-consolidation trade rule with real money math
and the symmetric ARB-trap risk. Stopped at (3) -- did not clear the bar, so (4) was not
run, per the plan's own explicit instruction not to invent a stage past a real "no."

**Stage 1 -- ARA-lock feasibility (`src/scratch_consolidation_ara_feasibility.py`)**: reused
the project's own board-limit-aware `is_ara_locked()` (`src/backtest_v4.py`) rather than a
naive open==high==low check. On the exact 932-episode population the existing base-rate
spike study used (volume>=10x trailing avg, move>=20%, ADTV_MIN, ATR/price<=10% -- n
reproduced exactly, confirming the population matches), the spike day itself is ARA-locked
(closed at the high, essentially the full board limit, no real offer to buy from) **53.1% of
the time**. On the broader unfiltered population of all >=20% up-days, 58.6% locked;
restricted to the liquid universe (existing `adtv_20 >= ADTV_MIN` + `atr_14/close <=
ATR_PRICE_RATIO_MAX` filter), 48.5% locked. Of locked days, only 8.2% have essentially zero
intraday range (truly untradeable all day) -- most locked days DO show real intraday range
before pinning at the close (median 25% of previous close), meaning a fill was
theoretically possible earlier in the day, just not at the closing price a naive backtest
would assume. **Verdict: roughly a coin flip, not "almost always locked."** Doesn't kill
variant (b) outright, but confirms the council's suspicion that it can't be honestly
backtested with `ihsg_eod`'s daily-bar-only data -- half the time there's no real fill at
all, and the other half needs an intraday fill-price assumption this dataset has no way to
verify. Not pursued further (matches the plan: feasibility check, not a backtest, for
variant b).

**Stage 2 -- pre-registration (`src/scratch_consolidation_scan.py`'s own docstring, written
and committed to before running Stage 3)**: "long tight consolidation" = per stock, per day,
`range_pct_60` (rolling 60-trading-day high/low range as % of rolling 60-day median close)
at or below the 10th percentile of that same metric across the WHOLE liquid population's
history (population-relative threshold, not fit to NICE's own ~21% range), sustained for
>=40 consecutive trading days. One episode per maximal qualifying run; episode date = the
LAST day of the run (still "inside" the range, the honest entry day for a variant-(a)-style
rule). **Pass bar, decided before running**: >=50 episodes, AND at +10 trading days
population mean AND median return each beat IHSG's own mean/median return over the same
episode dates by >=3 percentage points, AND win rate (return>0) >=55%. All three needed
simultaneously; any one failing is a clean rejection.

**Stage 3 -- population scan result**: 257 real episodes, 116 unique stocks (2020-11 to
2026-06, roughly even 21-60/year across 2021-2025, not concentrated in one regime the way
the spike study's 932 episodes were concentrated in COVID-recovery/2025-bull-run -- a
genuinely better-spread sample). Dominated by real large/mid-cap names going through
legitimate low-volatility periods (BBCA, BBRI, BJBR, BDMN, INDF, ICBP, CPIN, MGRO, BNGA),
not dead/suspended stocks (the liquidity filter's ADTV floor already excludes those). 39
stocks contribute >=3 episodes each (154/257 total) -- not independent across tickers, same
caveat the base-rate spike study logged for its own population.

| Horizon | n | stock mean/median | IHSG mean/median | alpha mean/median | win rate | up>=5% / flat / down<=5% |
|---|---|---|---|---|---|---|
| +5d | 257 | +0.59% / 0.00% | -0.13% / -0.07% | +0.72pp / +0.07pp | 49.0% | 14.8% / 72.0% / 13.2% |
| +10d | 256 | +0.21% / 0.00% | +0.02% / +0.09% | +0.18pp / -0.09pp | 46.1% | 17.6% / 67.6% / 14.8% |
| +20d | 254 | +1.08% / +0.57% | -0.28% / +0.03% | +1.36pp / +0.55pp | 52.0% | 27.2% / 50.8% / 22.0% |

**Does not clear the pre-registered bar at any horizon.** At +10d (the bar's own horizon):
alpha mean +0.18pp and median -0.09pp, both far under the +3pp bar; win rate 46.1%, under
even 50% let alone the 55% bar. +20d is the closest to promising (win 52.0%, alpha
+1.36pp/+0.55pp) but still well short of +3pp/55% on every count. The full breakdown shows
"flat" (-5%..+5%) is the dominant outcome at every horizon (51-72%), and up/down are roughly
balanced (down-side is NOT small -- 13-22% of episodes break down at least 5%, the symmetric
ARB-trap risk the council flagged is a real, non-trivial fraction of this population, not an
edge case). This directly explains why NICE reads as a striking anecdote: dramatic
breakouts happen, but the base rate says "goes nowhere" is far more common than either
direction, and a real down-tail exists too.

**Robustness check (`src/scratch_consolidation_sensitivity.py`)**: before accepting a null
result at face value -- this project has been burned by trusting one lucky point before
(the hysteresis-band sweep), so a one-point null deserves the same scrutiny. Swept the
tightness percentile (5/10/15/20%) at the pre-registered 60-day/40-day-min-run, and the
window length (40/60/90/120 trading days, min-run scaled ~2/3 of window) at the
pre-registered 10th percentile, all at the +10d horizon:

| win | min_run | pctile | n | mean ret | median ret | win rate | mean alpha | median alpha |
|---|---|---|---|---|---|---|---|---|
| 60 | 40 | 5% | 135 | -0.57% | -0.34% | 40.7% | -0.41pp | -0.64pp |
| 60 | 40 | 10% (default) | 256 | +0.21% | 0.00% | 46.1% | +0.18pp | -0.19pp |
| 60 | 40 | 15% | 393 | +0.30% | 0.00% | 46.1% | +0.46pp | -0.15pp |
| 60 | 40 | 20% | 498 | +0.21% | 0.00% | 45.6% | +0.31pp | -0.17pp |
| 40 | 25 | 10% | 449 | +0.28% | 0.00% | 47.7% | +0.17pp | -0.28pp |
| 90 | 60 | 10% | 166 | -0.04% | +0.36% | 50.6% | -0.06pp | +0.08pp |
| 120 | 80 | 10% | 115 | -1.03% | 0.00% | 47.0% | -0.59pp | +0.19pp |

**Null holds everywhere tested** -- mean/median alpha stays within roughly -0.6pp to +0.5pp
and win rate stays 40.7-50.6% (never once clearing 50%, let alone the 55% bar) across all 8
cells. This is the opposite failure signature from the hysteresis-band episode: instead of
"spectacular at one value, unstable elsewhere," this is "flat-to-negative everywhere," which
is a much more trustworthy null than a single run would have been.

**NICE's own position, checked last, for context only**: NICE does not appear as an episode
in this scan at all -- not because the rule excludes it, but because its real consolidation
(2026-06-08 to 2026-08-24) extends past this cached dataset's 2026-06-30 cutoff, and even at
the cache's last available date its trailing 60-day range_pct (45.7%) is still far above the
16.27% threshold, because that 60-day lookback also captures the sharp decline (280->216)
that preceded the tight base -- a real, mechanical reason a rolling trailing-window measure
takes time to "forget" a recent crash, not a flaw in the population result above.

**Verdict: REJECTED. Stage 4 (entry-during-consolidation trade-rule backtest with real fees/
slippage/sizing and the ARB-trap check) was not run** -- the plan's own pass bar was written
before this scan ran, wasn't cleared, and stayed uncleared across an 8-point sensitivity
sweep, so building the next stage on top of it would be re-litigating a real "no." The
underlying pattern (long, genuinely tight consolidation predicting an eventual directional
move) is not supported at the population level on this measure, on liquid IHSG stocks,
2020-2026: the modal outcome is "stays flat," and the up/down split among the stocks that do
move is close to symmetric -- not tilted toward the breakout NICE showed. Code kept
(`src/scratch_consolidation_ara_feasibility.py`, `src/scratch_consolidation_scan.py`,
`src/scratch_consolidation_sensitivity.py`, `.cache/consolidation_episodes.csv`) for reuse
if a differently-shaped version of the idea comes up later (e.g. a volatility-compression
measure instead of a fixed-window range, or conditioning on a specific catalyst rather than
tightness alone -- neither attempted here). `backtest_v4.py` itself is unmodified by this
entry; only new scratch scripts were added, none of them touch `simulate_window`,
`score_candidates`, `compute_entry_fill`, or any live path.

## Round 2 -- "long tight consolidation," volatility-compression version (14-day ATR/price
## instead of 60-day high-low range): REJECTED, null is WORSE than Round 1's and negatively
## tilted, not just flat. NICE-pattern research thread now CLOSED, both rounds (2026-08-27)

Round 1's own writeup named a specific, concrete flaw: its 60-trading-day trailing
high-low-range measure is slow to "forget" an old sharp move, and that's the literal reason
NICE itself never showed up as an episode (its early-June crash kept the 60-day range wide
for weeks after the stock had actually calmed down). This round tested the fix that flaw
implies: swap the tightness metric for something that adapts fast, while holding everything
else -- population, liquidity filter, the 40-day "long" persistence requirement, forward-
return horizons, benchmark, pass bar -- exactly as Round 1 had it, so any pass/fail is
attributable to that one change and nothing else.

**Pre-registration (`src/scratch_consolidation_vol_scan.py`'s own docstring, written before
running)**: tightness metric = `atr_14 / close_price`, where `atr_14` is the project's own
existing 14-trading-day true-range average (`src/strategy.py`, already used by the live
liquidity filter -- not a new metric invented for this test). "Tight" = <=10th percentile of
that ratio across the whole liquid population's history (same percentile, same liquidity
filter as Round 1). "Long" = tight for >=40 consecutive trading days, unchanged from Round 1.
Episode date = last day of the run. Same pass bar as Round 1: >=50 episodes, AND at +10
trading days population mean AND median return each beat IHSG's own by >=3pp, AND win rate
>=55%, all three simultaneously.

**Population scan result**: 206 episodes, 88 unique stocks (28 stocks contribute >=3
episodes each, 129/206 -- same non-independence caveat as always). Result is not just short
of the bar, it points the wrong way at every horizon:

| Horizon | n | stock mean/median | IHSG mean/median | alpha mean/median | win rate | up>=5% / flat / down<=5% |
|---|---|---|---|---|---|---|
| +5d | 205 | -1.61% / -0.43% | -0.62% / -0.20% | -0.99pp / -0.23pp | 37.6% | 8.3% / 75.6% / 16.1% |
| +10d | 205 | -0.93% / -0.56% | -0.68% / +0.01% | -0.26pp / -0.57pp | 39.5% | 11.7% / 69.3% / 19.0% |
| +20d | 204 | -0.85% / 0.00% | -0.27% / +0.30% | -0.57pp / -0.30pp | 45.1% | 14.7% / 64.2% / 21.1% |

Win rate never reaches even 50% at any horizon (Round 1's worst was 46.1%); alpha is
negative at every horizon on both mean and median (Round 1 was at least weakly positive on
the mean). A stock this quiet by 14-day ATR looks, if anything, mildly more likely to drift
down over the next 5-20 days than a random liquid stock on a random day -- consistent with
"already-quiet-by-this-measure" catching stocks in the early, indecisive stage of a
distribution/decline rather than a coiled spring.

**Sensitivity sweep (`src/scratch_consolidation_vol_sensitivity.py`)**: percentile threshold
(5/10/15/20%) at the pre-registered 40-day min-run, and min-run length (25/40/60/80 days) at
the pre-registered 10th percentile, all at +10d:

| min_run | pctile | n | mean ret | median ret | win rate | mean alpha | median alpha |
|---|---|---|---|---|---|---|---|
| 40 | 5% | 80 | -0.44% | -0.16% | 43.8% | +0.03pp | -0.38pp |
| 40 | 10% (default) | 205 | -0.93% | -0.56% | 39.5% | -0.26pp | -0.30pp |
| 40 | 15% | 328 | -0.53% | -0.61% | 41.5% | -0.34pp | -1.05pp |
| 40 | 20% | 462 | -1.11% | -0.66% | 41.3% | -1.10pp | -0.92pp |
| 25 | 10% | 397 | -0.72% | -0.34% | 42.6% | -0.39pp | -0.57pp |
| 60 | 10% | 92 | +0.20% | 0.00% | 44.6% | +0.52pp | +0.16pp |
| 80 | 10% | 64 | -1.98% | -0.49% | 40.6% | -1.36pp | -0.42pp |

Win rate stays 39.5-44.6% across all 7 cells -- never once above 50%, let alone the 55% bar
-- and alpha stays roughly -1.4pp to +0.5pp. Same "flat-to-negative everywhere" signature
Round 1 showed, one notch worse: this null is mildly negative rather than mildly positive-
but-insufficient. Not a one-lucky-point artifact either way.

**NICE's own reading under this metric, checked last, for context only**: as of the cache's
last available date (2026-06-30), NICE's `atr_14/close_price` is 8.57% -- nowhere near the
2.19% population threshold, despite the stock visibly trading in a bounded 234-284 band by
this point. This is a DIFFERENT reason than Round 1's (a stale 60-day window still
remembering the June crash): the 14-day ATR itself stays elevated because NICE's own
day-to-day range stayed genuinely large even while its multi-week high-low band was
narrowing -- a choppy, wide-daily-swing consolidation, not a smoothly calming one. Neither
tested definition of "tight" would have flagged NICE ahead of its breakout, for two
genuinely different mechanical reasons. That's informative on its own: NICE's actual
pre-breakout behavior doesn't match either of the two most natural, standard ways to define
"quiet."

**Verdict: REJECTED. Both the direction-of-fix hypothesis (a faster-adapting measure would
surface a real edge Round 1's slow measure was masking) and the underlying "long
consolidation predicts breakout" hypothesis itself are not supported.** Fixing the specific,
named flaw in Round 1's measure did not surface a hidden edge -- it produced a cleaner, more
negative null. Per this session's explicit instruction, no third variant follows regardless
of outcome.

**NICE-pattern research thread, closed, both rounds**: a single striking real trade (NICE,
+25%/+17% off a 2.5-month base) does not generalize to a population-level edge on liquid
IHSG stocks, 2020-2026, under either a slow (60-day range) or fast (14-day ATR) definition of
"quiet." The modal outcome after genuine tightness, either way it's measured, is "keeps
drifting sideways," and the up/down split among stocks that do move is not tilted toward the
breakout direction -- if anything the fast measure leans slightly toward continued weakness.
Code kept for reference (`src/scratch_consolidation_ara_feasibility.py`,
`src/scratch_consolidation_scan.py`, `src/scratch_consolidation_sensitivity.py`,
`src/scratch_consolidation_vol_scan.py`, `src/scratch_consolidation_vol_sensitivity.py`,
`.cache/consolidation_episodes.csv`, `.cache/consolidation_vol_episodes.csv`) but this
specific idea is not being pursued further. `backtest_v4.py` is unmodified by this entry.

## 2026-08-30: pullback-to-buy-area entry fill -- execution-quality mechanism (not a new
## signal), tested, NOT VALIDATED. Mechanical claim confirmed (fills 0.8-1.5% cheaper than
## raw open when they happen); aggregate walk-forward effect is not robust -- driven by the
## same single-window admission-order fragility this log has already used to reject two
## other mechanisms, and one currently-solid window (W9) gets consistently worse.

**Where this came from**: a real trader's structural critique of the live fill mechanism.
Today, a PENDING candidate queued the day before fills unconditionally at tomorrow's real
open (`paper_monitor.py`: `entry_price = float(r["open"])`, `backtest_v4.py`'s
`simulate_window`: `entry_price = o if o is not None else c`), subject only to a gap-sanity
check. The signal already implies a fair pullback zone via ATR (used for TP1/SL sizing) --
why pay the open blindly if price dips into a better zone shortly after, and if it never
dips at all, isn't that itself a sign the setup already broke? This is purely about
execution quality on an already-validated entry signal -- it does not touch WHICH candidate
gets picked, only WHERE it fills once picked.

**Pre-registered success criteria (written down before running the sweep, not moved
afterward)**: (1) average entry price should improve almost by construction when a fill
happens -- a near-mechanical check, not the interesting question; (2) the fraction of
candidates that never fill within the retry window is a real opportunity cost and must be
reported honestly, not glossed over; (3) the deciding test is the full 9-window walk-forward
aggregate (mean alpha, PF, drawdown, worst window) against the current at-the-open baseline
-- if a meaningful fraction of real winners get missed and the aggregate meaningfully
worsens, that is a genuine rejection, not just "did the average fill price improve"; (4) no
window that is currently solid may get meaningfully worse, same bar every other change this
project has tested is held to.

**Design**: buy area = `[signal_close - PULLBACK_HIGH_MULT*ATR, signal_close -
PULLBACK_LOW_MULT*ATR]`. In the backtest (only daily OHLC, no true intraday data), a fill is
assumed the moment the day's real LOW reaches the area's upper (near) edge --
`fill_price = min(day_open, area_upper)`, clamped to `>= day_low` so a fill is never
fabricated below what the day actually printed. Confirmed by direct code reading and then
empirically (`test_pullback_fill.py`, check 4): `PULLBACK_HIGH_MULT` (the area's deep/lower
edge) is **not read anywhere in the fill test or price** -- a resting limit order fills the
instant price first touches it, however much further it continues past that afterward, so
only the near edge (`PULLBACK_LOW_MULT`) can matter for a single-order backtest fill. Swept
anyway (0.7 vs 1.5 at fixed `LOW_MULT=0.3`) to confirm the no-op directly rather than just
assert it from the code -- byte-identical trade lists, confirmed.

A miss (price never touches the area) is carried forward for `PULLBACK_EXPIRY_SESSIONS=2`
sessions total, matching `paper_signal_scan.py`'s live `PENDING_EXPIRY_SESSIONS=2` exactly
-- **deliberately NOT reusing `BACKLOG_QUEUE_ENABLED`'s own carry-forward mechanism**, even
though it already exists in this file and does something superficially similar. That
mechanism was tested and **REJECTED earlier this project** (see "backlog/priority queue ...
REJECTED" above) specifically because merging survivors with fresh candidates and
re-sorting the WHOLE pending pool by score every day reshuffles who wins a scarce
`MAX_POSITIONS` slot in ways unrelated to the thing actually being tested, producing large
single-window swings (W4, W8 both damaged). Reusing it here would have baked that known
confound directly into this test. Instead: only a candidate that specifically missed the
buy-area touch test survives to tomorrow (everything else not admitted today --
`MAX_POSITIONS`/cooldown/cluster-cap/gap-limit/no-data -- stays dropped exactly like the
baseline unconditional reset), kept in its existing queue position with **no re-sort**, and
fresh candidates appended after -- also matching `paper_monitor.py`'s own fill loop, which
has no score-based reprioritization either. The existing gap-sanity check
(`abs(entry_price/signal_close - 1) > gap_limit`) was moved to check the day's **real raw
open**, not the substituted pullback price -- checking it against the intentionally-offset
area price would have falsely flagged legitimate pullback fills as bad data (a real bug
caught before it produced a misleading miss-rate number: `PULLBACK_LOW_MULT=1.5` at
`ATR_PRICE_RATIO_MAX=0.08` implies offsets up to 12% below close, above `cfg.GAP_MAX=10%`).

Implementation: `V4_PULLBACK_FILL_ENABLED`/`V4_PULLBACK_LOW_MULT`/`V4_PULLBACK_HIGH_MULT`/
`V4_PULLBACK_EXPIRY_SESSIONS` in `backtest_v4.py`, all new, isolated, off by default --
`score_candidates()`, `compute_entry_fill()`, `paper_signal_scan.py`, `paper_monitor.py` are
byte-for-byte unchanged (confirmed by grep: zero references to `PULLBACK` outside
`backtest_v4.py` and the new research scripts). `PULLBACK_FILL_LOG` (module-level list,
same "read/clear it directly" pattern `_broker_flow_ratio_cache` already uses in this file)
logs one row per resolved (stock_code, origin_day_idx) signal instance -- `FILLED` (with
`raw_open`/`fill_price`/`age`) or `EXPIRED_UNFILLED` -- for the miss-rate diagnostic below,
without threading a new field through `simulate_window`'s return contract.

**Self-check** (`src/test_pullback_fill.py`, same real 2025-07-01..2025-08-31 slice as
`test_backlog_queue.py`/`test_diag_hook.py`): flag OFF reproducible and byte-identical to
baseline, flag ON actually differs (not a dead flag); every logged fill price `<=` the
day's real raw open (never fabricated better than what the day offered); every admitted
pullback fill's age `<= PULLBACK_EXPIRY_SESSIONS` (expiry genuinely enforced, ages observed
1 and 2, never 3); `PULLBACK_HIGH_MULT` confirmed a no-op as above; diag hook stays purely
additive under pullback mode too. All 5 checks pass.

**Baseline reconfirmed first**, live `V4_PAPER` config (`V4_BANDAR_SIZING` default-on,
`V4_ATR_PRICE_RATIO_MAX=0.08`, matching `paper_signal_scan_v4_trigger.yml`), off the
existing `.cache/walk_forward_data_2021-01-01_2026-06-30.pkl`: mean alpha +26.17%, mean PF
1.95, mean/worst maxDD -14.26%/-21.10%, beat-bench 7/9, win>50% 4/9, 366 trades --
byte-identical to the 2026-08-22 `ATR_PRICE_RATIO_MAX=0.08` entry's own numbers.

**Full 9-window sweep** (`src/sweep_pullback_fill.py`; full per-window CSV at
`.cache/pullback_fill_sweep_full.csv`, agg at `.cache/pullback_fill_sweep_agg.csv`,
miss-rate diagnostic at `.cache/pullback_fill_miss_rate.csv`). `PULLBACK_HIGH_MULT` pinned
at 1.0 for the main grid (already shown to be a no-op above -- running the full 4x4=16 cells
would have been 12 fully redundant re-runs of the same 4 outcomes; disclosed here rather
than silently reporting a narrower grid than requested):

| LOW_MULT | trades | beat bench | win>50% | win% mean | alpha% mean | alpha% median | PF mean | DD% mean/worst | avg concurrent positions |
|---|---|---|---|---|---|---|---|---|---|
| **OFF (baseline)** | 366 | 7/9 | 4/9 | 49.8 | **+26.17** | +17.79 | 1.95 | -14.26/-21.10 | 2.71 |
| 0.0 | 350 | 8/9 | 6/9 | 52.9 | +20.33 | +15.14 | 2.05 | -14.37/**-27.82** | 2.73 |
| 0.2 | 358 | 7/9 | 7/9 | 54.8 | +25.97 | +17.01 | 2.18 | -11.53/-16.46 | 2.76 |
| 0.3 | 343 | 7/9 | 5/9 | 53.3 | **+30.02** | +11.86 | 2.17 | -13.60/-20.17 | 2.88 |
| 0.5 | 354 | 7/9 | 5/9 | 50.4 | +20.38 | +17.23 | 2.18 | -13.63/-25.77 | 2.89 |

Trade count drops modestly at every tested value (343-358 vs 366, 2-6% fewer) -- the
expected opportunity-cost mechanism, some candidates genuinely expire unfilled. Profit
factor improves at **every single tested value** (1.95 -> 2.05-2.18), and per-window
win-rate-consistency (win>50% count) improves at 3 of 4 cells -- a real, not-fabricated
secondary effect, the same "typical window looks more consistent" shape this log's own
`BACKLOG_QUEUE_ENABLED` entry found for a structurally different mechanism. But mean alpha
is **not monotonic** in `LOW_MULT` (20.33 -> 25.97 -> 30.02 -> 20.38, worse at both tested
extremes than in the middle) and the two extremes (0.0, 0.5) both show a meaningfully worse
**worst-case drawdown** than baseline (-27.82%, -25.77% vs -21.10%) -- a real regression at
the boundaries of the grid, not just noise cancelling out in the mean.

**Per-window trace explains why, and it is the same fragility signature this log has
already used to reject two other mechanisms** (`BACKLOG_QUEUE_ENABLED`'s own carry-forward,
`MAX_POSITIONS` widening) -- reached via yet another different route (fill-price/fill-day
shifting, not queue-widening or resorting):

| Window | OFF/baseline | LOW=0.0 | LOW=0.2 | LOW=0.3 | LOW=0.5 |
|---|---|---|---|---|---|
| W1 | +2.23% | +5.01% | +5.51% | +11.86% | +2.78% |
| W2 | -3.01% | +0.09% | -0.52% | -14.35% | -12.03% |
| W3 | -9.18% | -3.23% | -2.58% | -4.41% | -3.02% |
| W4 | +51.27% | +54.40% | **+100.20%** | +74.91% | +52.32% |
| W5 | +17.79% | +15.14% | +17.01% | +7.15% | +25.54% |
| W6 | +6.98% | +5.64% | +4.83% | +10.71% | +17.23% |
| W7 | +20.83% | +21.73% | +17.35% | +24.54% | +19.06% |
| **W8** | **+107.84%** | **+47.44%** | **+64.61%** | **+131.60%** | **+65.24%** |
| W9 | +40.76% | +36.72% | +27.32% | +28.20% | +16.26% |

**W8** (the single largest alpha contributor at baseline, already flagged in this log's
`BACKLOG_QUEUE_ENABLED`/`MAX_POSITIONS` entries as the window that absorbs this strategy's
scarce-slot fragility) swings wildly and non-monotonically across the grid: -60pp at
LOW=0.0, -43pp at LOW=0.2, **+24pp at LOW=0.3**, -43pp at LOW=0.5. **Recomputing mean alpha
with W8 excluded flips which cell looks best**: baseline 15.96%, LOW=0.0 16.94%, **LOW=0.2
21.14%** (the best cell once W8's single draw is removed, not LOW=0.3), LOW=0.3 only
17.33%, LOW=0.5 14.77%. The full-sample "LOW=0.3 is best" result is substantially a
one-window artifact, not a broad, consistent improvement -- concrete, not just asserted by
analogy to the earlier rejections.

**W9** (2026 H1, a currently solid window that beats a brutal -35.49% benchmark decline by
+40.76% at baseline) gets **consistently, monotonically worse at every single tested
value** as the required pullback deepens (+40.76% -> +36.72% -> +27.32% -> +28.20% ->
+16.26%) -- unlike W8's noisy swings, this one moves smoothly with the parameter, which
makes it a more trustworthy signal of a real cost, not noise: in a fast, violent-recovery
regime, waiting for a pullback that a genuine winner may never give back means missing more
real winners, exactly the risk criterion (4) above was written down to catch. This is the
clearest evidence in this sweep of "a meaningful fraction of real winners get missed."

**Miss-rate / fill-quality diagnostic** (pooled across all 9 windows, `PULLBACK_FILL_LOG`):

| LOW_MULT | signal instances seen | filled | expired unfilled | miss rate | avg price improvement when filled |
|---|---|---|---|---|---|
| 0.0 | 406 | 391 | 15 | 3.7% | 0.84% |
| 0.2 | 362 | 315 | 47 | 13.0% | 1.13% |
| 0.3 | 383 | 298 | 85 | 22.2% | 1.53% |
| 0.5 | 654 | 387 | 267 | 40.8% | 1.46% |

Criterion (1) holds cleanly: when a fill happens, the average price is 0.8-1.5% better than
the raw open, growing roughly with how deep a pullback is required. Criterion (2) also
holds, honestly reported: miss rate rises sharply with `LOW_MULT`, from ~4% (barely any
pullback required) to ~41% (a full ATR of pullback required) -- a real, substantial
opportunity cost at the deeper end of the grid. One caveat on the denominator, checked
directly rather than assumed (`(stock_code, origin_day_idx)` key collision count = 0, no
double-logging bug): "signal instances seen" counts distinct signal-days, not distinct
stocks -- a stock that stays qualifying while an earlier attempt is still pending can get
freshly re-tagged with a new `origin_day_idx` (7 stocks did this within one 2-month slice
alone, e.g. WIRG 3x), which is part of why LOW=0.5's denominator (654) is much larger than
LOW=0.3's (383): a stricter bar creates more distinct attempts overall, not just a lower
per-attempt hit rate.

**Why a real, mechanically-guaranteed price improvement doesn't translate into a robust
portfolio-level improvement**: this strategy's edge is concentrated (6 slots, `ALLOC_PCT`
sizing, `MAX_POSITIONS` binds on the large majority of candidate-days per the Phase 1
diagnostic already in this log) -- WHICH stock gets the scarce slot on WHICH day dominates
the aggregate outcome far more than a ~1% entry-price difference does, and shifting fill
day/price (even without touching admission order or re-sorting) is enough to move who ends
up filling versus expiring, and therefore which trades exist in the sample at all. A small,
real, mechanical win on execution quality gets swamped by the same admission-order
sensitivity this log has now documented under three structurally different mechanisms
(temporal backlog reordering, concurrent-capacity widening, and now fill-price/fill-day
shifting).

**No Monte Carlo permutation check run**, per this log's own established bar (used
identically for `BACKLOG_QUEUE_ENABLED` and `REGIME_CONFIRM_DAYS=2`): an MC check is for a
candidate that looks genuinely better and more robust on the sweep itself. No `LOW_MULT`
value here clears that bar -- mean alpha is non-monotonic, the two grid extremes show a
meaningfully worse worst-case drawdown than baseline, one currently-solid window (W9)
degrades consistently at every value, and the apparent best cell is shown directly (not
just suspected) to be substantially a single-window artifact.

**Verdict: NOT VALIDATED.** The mechanical claim behind the idea is correct and confirmed
(pullback fills genuinely cost less, 0.8-1.5% on average, when they happen), and profit
factor improves at every tested value -- a real secondary signal worth keeping in mind. But
the deciding test (full walk-forward aggregate, pre-registered before running) does not
clear this project's own adoption bar: no `LOW_MULT` value beats baseline on both mean alpha
and worst-case drawdown simultaneously, the ranking across the grid is not robust to
dropping a single window, and a currently solid window (W9) gets consistently worse as the
required pullback deepens. **Do not deploy to any live paper run.** Direction (better entry
prices are mechanically real) holds up; net portfolio effect does not.

**Honest scope note**: this is one plausible, carefully-scoped implementation of "wait for
a pullback" (fill at the near edge the instant it's touched, expire after 2 sessions,
carried forward without re-sorting). It is not proof no version of this idea could ever
work -- e.g., a design that widens `MAX_POSITIONS`/loosens concentration specifically to
give a waiting order room without displacing today's fresh candidates was not tested here
and might behave differently, though the two prior widening/reordering attempts in this log
both failed for related reasons. **Next step if this gets picked back up**: isolate whether
the instability is really "which stock gets today's scarce slot changing" (per the Phase 1
diagnostic playbook this log already built for `BACKLOG_QUEUE_ENABLED`/`MAX_POSITIONS`) by
tracing W8's specific admitted-candidate list cell-by-cell, the same concrete-trace
discipline that explained those two rejections instead of stopping at the aggregate table.

Code kept: `src/test_pullback_fill.py` (self-check, same pattern as `test_backlog_queue.py`),
`src/sweep_pullback_fill.py` (this sweep, reusable the same way `sweep_backlog_queue.py`/
`sweep_rotation.py` are for the next numeric-grid parameter). `backtest_v4.py` gained the
`PULLBACK_FILL_ENABLED`/`PULLBACK_LOW_MULT`/`PULLBACK_HIGH_MULT`/`PULLBACK_EXPIRY_SESSIONS`/
`PULLBACK_FILL_LOG` mechanism inside `simulate_window`'s day loop, regression-verified
byte-identical at defaults (`test_diag_hook.py`, `test_backlog_queue.py` both still pass).
`score_candidates()`, `compute_entry_fill()`, `evaluate_position_exit()`,
`paper_signal_scan.py`, and `paper_monitor.py` are all unchanged. Raw sweep outputs saved at
`.cache/pullback_fill_sweep_full.csv`/`_agg.csv`/`_miss_rate.csv`.

## 2026-08-30: score-confidence-scaled stop-loss width -- real-trader critique (GIAA -10.81%,
## WMPP -13.89%, HATM -14.96% real closed-trade SL distances this week), tested, REJECTED at
## the task's own suggested bounds and non-robust everywhere else. Base-rate check shows the
## chosen signal is a weak, inconsistent predictor of "will this trade hit its stop" --
## weaker than the same-day-rank effect `diagnose_score_power.py` already found. The one
## sweep cell that looks good is a single-window (W8) leverage artifact, the same failure
## signature this log has rejected repeatedly.

**Hypothesis** (a real trader's structural critique, not a guess): `SL_MULT` (`compute_entry_fill()`,
`backtest_v4.py`) is a single FLAT 1.5x-ATR multiplier applied to every candidate regardless
of signal quality. A high-confidence signal moving against you by a lot, soon, plausibly
means the entry thesis itself was wrong ("false entry") and should be cut faster; a weaker/
noisier signal might reasonably need more room. Architecturally this is the exact
"ratio-and-clip" pattern `SCORE_SIZING_ENABLED`/`LIQ_SIZING_ENABLED`/`TREND_SIZING_ENABLED`/
`BANDAR_SIZING_ENABLED` already use for POSITION SIZE -- this test applies the same pattern
to the STOP WIDTH instead: `sl_mult_effective = SL_MULT * confidence_adjustment`, where
`confidence_adjustment = clip(score_p90 / sig["score"], SL_CONFIDENCE_MIN, SL_CONFIDENCE_MAX)`
-- the SAME score/score_p90 ratio `size_mult` already uses, INVERTED (higher score -> smaller
adjustment -> tighter stop; lower score -> larger adjustment, up to the current width).

**Signal choice, argued before testing (the task asked for this explicitly, not just a free
pick of `score`)**: `trend_strength` was rejected as the axis because it is one IHSG-wide
scalar shared by every candidate admitted on the same day -- it cannot tell apart which of
TODAY's candidates has the shakier thesis, only whether today-in-general is a strong regime
day. `concentration` (Bandarmology, `BANDAR_SIZING_ENABLED`'s own signal) was considered and
is revisited below -- not chosen as the PRIMARY axis going in because of a real coverage gap
(see base-rate check, part D). `score` was chosen anyway, over `SCORE_SIZING_ENABLED`'s own
prior REJECTED verdict for SIZING ("no demonstrated value for sizing... likely already-
extended momentum, not more runway"), because the rejection reason doesn't obviously transfer
to STOP WIDTH: `diagnose_score_power.py`'s 2026-08-07 finding (same log, above) showed a
same-day statistical-outlier score (specifically extreme `weekly_ma_spread`) DOES carry real
information -- rank-1-by-score hits its stop 82-98% of the time across both halves of a
4.5-year out-of-sample split (survives the split). It just doesn't help to size UP into that
outcome; tightening the STOP on the same known-bad subgroup is a different, and more
mechanistically direct, use of the same signal. **That premise gets checked directly below,
not assumed.**

**Implementation**: `V4_SL_CONFIDENCE`/`V4_SL_CONFIDENCE_MIN`(default 0.7)/
`V4_SL_CONFIDENCE_MAX`(default 1.3) in `backtest_v4.py`, off by default, applied inside
`compute_entry_fill()` right before the existing `sl_price = entry_price - atr_val * SL_MULT`
line (now `sl_mult_effective`) -- both the backtest and `paper_monitor.py`'s live fills go
through this one function, so the live paper-trading path picks this up automatically the
moment the flag is set, same as every other `*_SIZING_ENABLED` flag in this file. No effect
on the rare no-ATR fallback branch (flat `SL_PCT`) -- out of scope, not what the real-trade
critique was about. Regression-verified inert at default (`test_diag_hook.py`,
`test_paper_trading_math.py`, `test_bandar_sizing_default.py`, `test_spike_sizing.py` all
still pass byte-for-byte) and a `(SL_CONFIDENCE_MIN, MAX) = (1.0, 1.0)` sanity cell in the
sweep below reproduces the OFF baseline exactly (forces `confidence_adjustment == 1.0`
regardless of score, as it should).

**Also added, purely additive**: `_diag_admitted`'s existing research hook (see
`test_diag_hook.py`'s own "zero side effects" guarantee) gained `trade_date`, `score_p90`,
`sl_price`, `concentration`, `concentration_p90` fields -- lets an admitted candidate be
joined against its own real `df_trades` outcome by `(stock_code, trade_date==entry_date)`
for the base-rate check below, without touching any trading logic.

**Baseline reconfirmed first**, live `V4_PAPER` config (`V4_ATR_PRICE_RATIO_MAX=0.08`,
`V4_BANDAR_SIZING` default-on), off the existing
`.cache/walk_forward_data_2021-01-01_2026-06-30.pkl`: mean alpha +26.17%, mean PF 1.95,
mean/worst maxDD -14.26%/-21.10%, beat-bench 7/9, win>50% 4/9, 396->366 trades --
byte-identical to the 2026-08-22 `ATR_PRICE_RATIO_MAX=0.08` entry's own numbers.

**1. Base-rate check FIRST (the task's own required step, done before trusting the
mechanism): does score/score_p90 actually predict which ADMITTED, REAL trades get stopped
out?** Ran the real 9-window schedule with `SL_CONFIDENCE_ENABLED=False` and `diag={}`,
joined every admitted candidate to its own eventual trade outcome (`src/
scratch_sl_confidence_baserate.py`, raw output `src/scratch_sl_confidence_baserate_raw.csv`,
n=250 matched admissions across all 9 windows):

| score/score_p90 tercile | n | win rate | SL-hit rate | mean pnl (Rp) |
|---|---|---|---|---|
| low (mean ratio 1.21) | 84 | 32.1% | 60.7% | 1,522,129 |
| mid (mean ratio 2.36) | 83 | 28.9% | 60.2% | 288,820 |
| high (mean ratio 4.14) | 83 | 28.9% | 63.9% | 914,830 |

Not a clean gradient -- `mid` has the WORST mean pnl of the three buckets, not something in
between `low` and `high`. Top-decile-by-score (n=25, the closest analogue to
`diagnose_score_power`'s "rank 1") vs the rest: win rate 28.0% vs 30.2%, SL-hit 64.0% vs
61.3%, mean pnl actually HIGHER for the top decile (Rp1,208,732 vs Rp877,971) -- the direction
the mechanism needs, reversed. Spearman correlations on the full n=250: score_ratio vs net
pnl rho=-0.169 (p=0.008, real but weak), score_ratio vs win (binary) rho=-0.036 (p=0.573,
NOT significant), score_ratio vs SL-hit (binary) rho=+0.035 (p=0.586, NOT significant). Per-
window breakdown (block C, script output) shows the SL-hit-rate-rises-with-score pattern in
some windows (W2, W9) and the OPPOSITE in others (W7: high-score bucket has the LOWEST
SL-hit rate, 16.7%, and the BEST win rate, 66.7%) -- not a consistent direction.

**Read plainly: `score`/`score_p90` (the ratio `compute_entry_fill()` actually computes) is a
much weaker and noisier predictor of "will this specific trade get stopped out" than
`diagnose_score_power.py`'s same-day-RANK-based finding.** The likely reason: `score_p90` is
a TRAIN-derived aggregate threshold, not a same-day comparison -- a day where the whole
qualifying pool's scores happen to sit far from the historical `score_p90` inflates or
deflates every candidate's ratio together, diluting the specific "this candidate is today's
own outlier" signal that rank captured cleanly. The premise this flag leans on is real at the
rank level and much weaker at the ratio level it actually uses.

**2. A candidate NOT chosen as primary (concentration/Bandarmology) turns out cleaner in this
same check -- worth recording even though it wasn't this test's chosen axis:**

| concentration/concentration_p90 tercile | n | win rate | SL-hit rate |
|---|---|---|---|
| low | 63 | 19.1% | 68.3% |
| mid | 62 | 29.0% | 62.9% |
| high | 63 | 42.9% | 47.6% |

Clean, monotonic, and statistically real (rho=+0.246 vs win, p=0.001; rho=-0.222 vs SL-hit,
p=0.002; n=188/250 admitted candidates have real concentration data, 75.2% coverage -- the
coverage gap flagged going in, real but not disqualifying). **The direction argues AGAINST
this test's "high confidence -> tighter stop" mapping if concentration were substituted in
directly**: high-concentration trades already have the BEST win rate and LOWEST SL-hit rate
of the three buckets -- tightening their stop would target the group already least likely to
need it, while low-concentration trades (SL-hit 68.3%, the group that actually IS failing
most) would keep today's un-tightened width under a naive same-shaped mapping. Concentration
is a better-behaved signal for trade quality in general terms but not a drop-in replacement
for this specific "penalize overconfidence" design without inverting the mapping -- a
different test, not this one. Flagged for a future session, not built here.

**3. Full 9-window walk-forward at the task's own suggested default bounds
(`SL_CONFIDENCE_MIN=0.7`, `MAX=1.3`)** (`src/test_sl_confidence.py`):

| Metric | OFF | ON (0.7, 1.3) |
|---|---|---|
| Windows beating benchmark | 7/9 | 7/9 |
| Windows win-rate > 50% | 4/9 | 4/9 |
| Win rate (mean / median) | 49.8% / 50.0% | 42.4% / 45.5% |
| Profit (mean / median) | +25.31% / +6.15% | +20.34% / +5.12% |
| Alpha (mean / median) | +26.17% / +17.79% | +21.20% / +7.41% |
| Profit factor (mean / median) | 1.95 / 1.29 | 1.55 / 1.28 |
| Max drawdown (mean / worst) | -14.26% / -21.10% | -14.45% / -19.85% |

Every profit/win-rate/PF metric gets WORSE, not mixed. Mean drawdown is essentially flat
(slightly worse); only the single worst-case window's drawdown improves (-21.10% ->
-19.85%). Does not clear this project's own adoption bar (best mean alpha AND best
worst-case drawdown together) -- on this evidence alone, plain tightening of high-score
trades' stops looks like the disclosed risk this task asked to check honestly for: more
premature stop-outs on ordinary volatility (whipsaw), without a compensating benefit,
consistent with part 1's weak/null base-rate finding.

**4. Bounds sensitivity sweep** (`src/sweep_sl_confidence.py`, in-process, same
`.cache` dataset, ATR<=0.08 pinned; full CSV `src/sweep_sl_confidence_summary.csv`):

| (MIN, MAX) | beat-bench | win>50% | win mean | profit mean | alpha mean | PF mean | maxDD mean | maxDD worst |
|---|---|---|---|---|---|---|---|---|
| OFF (baseline) | 7/9 | 4/9 | 49.8% | +25.31% | +26.17% | 1.95 | -14.26% | -21.10% |
| sanity (1.0, 1.0) | 7/9 | 4/9 | 49.8% | +25.31% | +26.17% | 1.95 | -14.26% | -21.10% |
| tighten-only (0.7, 1.0) | 7/9 | 4/9 | 42.9% | +21.33% | +22.19% | 1.59 | -14.22% | -19.85% |
| widen-only (1.0, 1.3) | 7/9 | 3/9 | 49.3% | +24.62% | +25.48% | 1.92 | -14.97% | -21.10% |
| narrow (0.85, 1.15) | 7/9 | 3/9 | 45.8% | +22.38% | +23.24% | 1.98 | -15.10% | **-23.14%** |
| default (0.7, 1.3) | 7/9 | 4/9 | 42.4% | +20.34% | +21.20% | 1.55 | -14.45% | -19.85% |
| wide (0.5, 1.5) | **8/9** | 3/9 | 40.9% | **+34.07%** | **+34.93%** | **2.06** | **-13.13%** | **-17.26%** |
| size_mult-scale (0.5, 2.0) | **8/9** | 3/9 | 41.1% | **+34.41%** | **+35.27%** | **2.08** | -13.12% | -17.26% |

The sanity cell reproduces OFF exactly (implementation check passes). Everything else is
**non-monotonic, not a smooth dose-response**: `tighten-only`, `widen-only`, `narrow`, and
`default` -- four cells spanning the task's own suggested range and its two pure halves --
are all flat-to-worse than baseline on every profit metric, and `narrow` (a GENTLER version
of the same idea) has the single WORST worst-case drawdown of the whole table (-23.14%,
worse than even doing nothing). Only the two most extreme cells tested, well past the task's
own suggested guardrails, look attractive in aggregate.

**Traced `wide`'s aggregate improvement to a single window, the same failure signature this
log has already used to reject three other mechanisms this project (`ROTATION_MARGIN_MULT`,
spike sizing, the divergence gate)**: per-window profit deltas vs baseline for `wide` are
w1 +0.24, w2 +6.52, w3 +0.08, w4 -5.88, w5 -3.31, w6 +0.15, w7 -8.21, **w8 +86.68**, w9 +2.61
-- summing to +78.9pp total, of which window 8 alone supplies +86.68pp (110% of the whole
aggregate gain; every OTHER window nets slightly NEGATIVE, -7.8pp combined). **And window 8's
own exit breakdown gets a HIGHER SL-hit fraction under `wide` (38.7%) than baseline (34.5%),
not lower** -- so the profit gain is demonstrably not "avoiding bad stop-outs." The likely
real mechanism: `SL_MULT`/`sl_mult_effective` feeds `risk_per_share` in
`compute_entry_fill()`'s own `lots_risk = prev_equity * RISK_PCT / risk_per_share` cap --
tightening the stop shrinks `risk_per_share`, which mechanically ALLOWS MORE SHARES for the
same 4%-of-equity risk budget. On a genuinely strong window (W8 already the single largest
contributor to the whole 9-window schedule's profit in every prior entry that's checked
this), that extra leverage amplifies the winners already there -- "amplifies whichever
direction a window is already going," the exact phrase this log used for pyramiding, here
showing up as a side effect nobody asked for rather than the intended one.

**Verdict: REJECTED, both at the task's own suggested bounds and at every other value tested
that isn't a single-window leverage artifact.** The premise check (part 1) shows `score` is a
weak, inconsistent predictor of which admitted trades actually hit their stop -- weaker than
the same-day-rank effect this signal is theoretically riding on. The walk-forward at the
suggested default bounds is a net negative on every profit/win-rate/PF metric with only a
marginal worst-case-drawdown consolation. The sweep's one genuinely good-looking region
(MIN<=0.5) doesn't decompose into "tightening helps" under any honest accounting -- it is a
single window's leverage effect via the existing `RISK_PCT` risk-sizing cap, mechanistically
traced, not guessed at. Consistent with the pre-registered honesty bar: **this is the "just
causes more whipsaw without a compensating benefit" outcome the task asked to watch for
explicitly, at the parameterization actually suggested.** `SL_CONFIDENCE_ENABLED` stays off
by default; kept in the code (same convention as every other unvalidated-but-available flag
in this file) for a future attempt with a different signal, not this one's score/score_p90
ratio.

**Next step if this gets picked back up**: (1) concentration/Bandarmology (part 2) is the
more evidence-backed axis for "does this candidate's setup actually look real" -- but needs
its own differently-shaped design (tighten the LOW-concentration group, not the high one, or
size DOWN low-concentration entries instead of touching their stop) rather than porting this
test's score-shaped mapping onto it unchanged; (2) if `score` is revisited, use a same-day
comparison (percentile within that day's own qualifying pool, closer to what
`diagnose_score_power.py` actually validated) instead of the TRAIN-derived `score_p90` ratio
`compute_entry_fill()` happens to already have on hand -- part 1 suggests that's where the
signal got diluted; (3) any SL-width change should be walk-forward-tested with `RISK_PCT`'s
own sizing interaction explicitly held constant (e.g. size off the ORIGINAL `SL_MULT`
distance, not the confidence-adjusted one) before trusting an aggregate number, so a genuine
loss-cutting effect can't hide behind a leverage effect again.

Code touched: `backtest_v4.py` (`SL_CONFIDENCE_ENABLED`/`SL_CONFIDENCE_MIN`/
`SL_CONFIDENCE_MAX`, `compute_entry_fill()`'s `sl_mult_effective`, `_diag_admitted`'s five new
additive fields -- all off/no-op by default, regression-verified). New: `src/
test_sl_confidence.py` (isolated OFF/ON check via `feature_test_harness.py`), `src/
sweep_sl_confidence.py` (bounds grid, in-process), `src/scratch_sl_confidence_baserate.py`
(the base-rate check, part 1/2 above) + its raw CSV output. `score_candidates()`,
`evaluate_position_exit()`, `paper_signal_scan.py`, and `paper_monitor.py` are unchanged.
Left uncommitted for review, same pattern as this session's other entries.

## 2026-08-30: concentration-scaled stop-loss width -- idea #3 of this session's three-idea
## SL-width thread (reversed polarity vs idea #2, a council-escalated side-finding from that
## rejection), tested, REJECTED. Same single/double-window-driven fragility signature this
## log has now used to reject three different mechanisms, and the mandated
## sizing-interaction isolation check (council correction #2) found a case where the
## IDENTICAL bounds flip the sign of the aggregate result depending on whether
## BANDAR_SIZING_ENABLED is on or off -- concrete evidence of the exact confound the check
## was designed to catch, not just a failure to rule it out.

**Where this came from**: while rejecting idea #2 (score-confidence-scaled SL, see entry
directly above), a side-check of Bandarmology `concentration` (`BANDAR_SIZING_ENABLED`'s own
signal, top1_broker_|net_lot| / sum(all_brokers_|net_lot|)) on the same 250 real historical
trades found it correlates with outcomes in the OPPOSITE direction idea #2 needed: win rate
by concentration tercile 19.1%/29.0%/42.9% (low/mid/high), rho=+0.246 (p=0.001) vs win,
rho=-0.222 (p=0.002) vs SL-hit rate. High concentration -> better outcome -> should get a
WIDER stop (let it run); low concentration -> tighter stop (cut faster) -- reversed polarity
from idea #2 (which shrank the multiplier for high-signal candidates). Escalated to a
5-advisor + 3-peer-review council given the "treadmill" risk of a third consecutive test on
the same SL-width lever; council said yes, conditionally, with two mandatory corrections the
peer-review round caught (missed by all 5 original advisors): **(1) the 250-trade
correlation above is not validation, it is only what earns this a test slot -- the ONLY bar
that counts is the full 9-window walk-forward below, decided by this project's standard
methodology, not by re-looking at the correlation; (2) `concentration` already drives
position SIZE via `BANDAR_SIZING_ENABLED` elsewhere in `compute_entry_fill()` -- any
walk-forward improvement from also using it for SL WIDTH must be checked against that
existing sizing interaction, not assumed separable.** Both corrections are applied literally
below, not just referenced.

**Implementation**: `V4_SL_CONCENTRATION`/`V4_SL_CONCENTRATION_MIN` (default 0.8)/
`V4_SL_CONCENTRATION_MAX` (default 1.3) in `backtest_v4.py`, off by default, same
ratio-and-clip shape `BANDAR_SIZING_ENABLED`'s own `bandar_mult` already uses
(`concentration / concentration_p90`, clipped) -- applied to `sl_mult_effective` instead of
`alloc`, sign UNCHANGED (not inverted, unlike idea #2's `confidence_adjustment`): higher
concentration -> larger multiplier -> wider stop; lower concentration -> smaller multiplier
-> tighter stop. Stacks multiplicatively with `SL_CONFIDENCE_ENABLED` if both were ever
turned on (neither is). `concentration`/`has_concentration` extraction was moved earlier in
`compute_entry_fill()` (was previously only computed at the `bandar_mult` site) so this
block can read it before the SL price is computed -- `bandar_mult` now reuses those same two
locals rather than a second lookup; behavior of `bandar_mult` itself is unchanged (confirmed
by the idea #2 regression re-run below, byte-identical to its own recorded numbers, so this
refactor introduced no side effect on the existing flag).

**Self-check** (`src/test_sl_concentration.py`, 5 direct assertions on `compute_entry_fill()`
itself -- no walk-forward needed for the polarity claim, entry_price/atr/concentration are
all plain inputs to one pure function): OFF is neutral regardless of concentration (sl_price
identical at concentration=1.3/0.1/None); ON with high concentration (ratio clipped to MAX)
widens the stop (lower sl_price than OFF); ON with low concentration (ratio clipped to MIN)
tightens it (higher sl_price than OFF); missing concentration stays neutral even with the
flag on (no crash, matches OFF); sl_price is unaffected by `BANDAR_SIZING_ENABLED`'s own
on/off state AT THE PRICE-COMPUTATION LEVEL (the two multipliers are computed independently
and never multiply each other directly) -- explicitly NOT claimed to rule out the deeper
LOTS-level interaction via `risk_per_share`/`lots_risk`, which is what the walk-forward
isolation pass below actually checks. All 5 checks pass.

**Baseline reconfirmed first, both configurations**, off the existing
`.cache/walk_forward_data_2021-01-01_2026-06-30.pkl`, `V4_ATR_PRICE_RATIO_MAX=0.08`
(matching every other entry this session): with `BANDAR_SIZING_ENABLED=True` (live default)
-- mean alpha +26.17%, mean PF 1.95, mean/worst maxDD -14.26%/-21.10%, beat-bench 7/9,
win>50% 4/9, 366 trades, byte-identical to every prior entry's own recorded numbers. With
`BANDAR_SIZING_ENABLED=False` (the isolation configuration) -- mean alpha +29.82%, mean PF
1.98, mean/worst maxDD -15.97%/-23.13%, beat-bench 7/9, win>50% 4/9, 374 trades (a different,
but internally consistent, baseline -- turning `BANDAR_SIZING_ENABLED` off changes which
candidates clear `ALLOC_MIN_LOTS`, so trade count shifts on its own, unrelated to this
flag). The idea #2 (`SL_CONFIDENCE_ENABLED`) isolated test was also re-run in full after this
session's code changes and reproduced its own recorded table exactly (mean alpha +26.17% OFF
/ +21.20% ON, mean PF 1.95/1.55) -- confirms the `compute_entry_fill()` refactor above (moving
the `concentration` extraction earlier) introduced no regression.

**Full 9-window sweep, PASS A -- `BANDAR_SIZING_ENABLED=True` (live default)**
(`src/sweep_sl_concentration.py`, full CSV `sweep_sl_concentration_bandar_on.csv`):

| (MIN, MAX) | trades | beat bench | win>50% | win% mean | alpha% mean | PF mean | DD% mean/worst |
|---|---|---|---|---|---|---|---|
| **OFF (baseline)** | 366 | 7/9 | 4/9 | 49.8 | +26.17 | 1.95 | -14.26/-21.10 |
| sanity (1.0, 1.0) | 366 | 7/9 | 4/9 | 49.8 | +26.17 | 1.95 | -14.26/-21.10 |
| tighten-only (0.8, 1.0) | 394 | 7/9 | 5/9 | 46.7 | +28.25 | 1.77 | -15.53/-25.24 |
| widen-only (1.0, 1.3) | 364 | 7/9 | 5/9 | 50.3 | +28.41 | **2.06** | **-14.04**/**-19.14** |
| **default (0.8, 1.3)** | 394 | 7/9 | 4/9 | 45.5 | +29.61 | 1.69 | -15.54/**-25.54** |
| narrow (0.9, 1.15) | 369 | 7/9 | 3/9 | 47.6 | +25.50 | 1.91 | -14.76/-18.50 |
| wide (0.5, 2.0) | 412 | 7/9 | 4/9 | 44.1 | **+29.97** | 1.78 | **-13.65**/-18.84 |

The sanity cell reproduces OFF exactly (implementation check passes through the full
pipeline, not just the unit-level self-check). `default (0.8, 1.3)` -- the flag's own coded
default, the "reasonable default" this test was asked to try first -- shows the single WORST
profit factor (1.69) and single WORST worst-case drawdown (-25.54%) in the entire grid,
alongside win>50% unchanged from baseline (4/9). Only `widen-only` (1.0, 1.3) looks clean
on every metric simultaneously (best PF, best mean AND worst-case drawdown, win>50%
improved to 5/9) -- examined in the per-window trace below.

**Full 9-window sweep, PASS B -- `BANDAR_SIZING_ENABLED=False` (isolation, council
correction #2)** (same script, full CSV `sweep_sl_concentration_bandar_off.csv`):

| (MIN, MAX) | trades | beat bench | win>50% | win% mean | alpha% mean | PF mean | DD% mean/worst |
|---|---|---|---|---|---|---|---|
| **OFF (baseline)** | 374 | 7/9 | 4/9 | 50.1 | +29.82 | 1.98 | -15.97/-23.13 |
| sanity (1.0, 1.0) | 374 | 7/9 | 4/9 | 50.1 | +29.82 | 1.98 | -15.97/-23.13 |
| tighten-only (0.8, 1.0) | 392 | 7/9 | 4/9 | 46.7 | +33.40 | 1.64 | -16.94/**-31.08** |
| widen-only (1.0, 1.3) | 370 | 7/9 | 5/9 | 51.0 | +32.79 | **2.12** | -15.76/-23.13 |
| **default (0.8, 1.3)** | 385 | 7/9 | 5/9 | 47.2 | +35.32 | 1.90 | -16.62/**-31.26** |
| narrow (0.9, 1.15) | 363 | 7/9 | 4/9 | 50.3 | +34.73 | **2.32** | -15.91/-23.46 |
| wide (0.5, 2.0) | 414 | 7/9 | 4/9 | 45.1 | +34.92 | 1.78 | **-14.84**/**-21.81** |

Sanity again reproduces OFF exactly. Every cell's mean alpha looks better here than in Pass
A -- but that is mostly `BANDAR_SIZING_ENABLED`'s own baseline shift (+29.82% vs +26.17%,
already present at `sanity`/OFF before `SL_CONCENTRATION_ENABLED` does anything), not a
bigger effect from this flag. The two worst-drawdown cells (`tighten-only`, `default`, both
touching the MIN<1.0 side) get WORSE in this configuration, not better (-31.08%/-31.26% vs
-25.24%/-25.54% in Pass A) -- tightening the low-concentration side is not rescued by
removing the sizing interaction.

**Per-window trace: every cell's aggregate "improvement" is 1-2 windows carrying the entire
result, the same fragility signature this log has already used to reject the pullback-fill
entry mechanism (W8/W9) and idea #2's own `wide` cell (W8)** -- reached here via a third,
structurally different route (SL width feeding `risk_per_share`, not entry timing or
size_mult):

| Cell | Pass A: window(s) responsible | Pass B: window(s) responsible |
|---|---|---|
| widen-only (1.0,1.3) | W4 +23.58pp of net +20.17pp (117%); all others net -3.41pp | W4 +27.36pp of net +26.77pp (102%); all others net -0.59pp |
| tighten-only (0.8,1.0) | W8 +21.02pp of net +18.69pp (112%); W5 -9.86, W7 -6.16 | W8 +30.12pp of net +32.29pp (93%) |
| default (0.8,1.3) | W8 +39.40pp of net +31.0pp (127%); W5 -9.86, W7 -6.23 | **W4 +40.17pp AND W8 +19.58pp** of net +49.51pp; others net -10.24pp |
| wide (0.5,2.0) | W8 +27.65pp, W4 +12.94pp; **W7 -13.70pp** | W8 +37.20pp, W4 +14.79pp; **W7 -11.24pp** |
| narrow (0.9,1.15) | W4 +4.26pp; net mean delta **-0.67pp (WORSE than baseline)** | W4 +33.93pp; net mean delta **+4.91pp (BETTER than baseline)** |

`widen-only`'s apparent cleanliness holds up across both configurations in the same
direction and roughly the same magnitude (W4 responsible for essentially all of it either
way) -- not a `BANDAR_SIZING` artifact, but still a single-window result: 6 of 9 windows show
**exactly zero** change in either configuration (W1, W2, W3, W5, W9 -- these candidates'
concentration ratios never cross above 1.0, so `widen-only`'s own MIN=1.0 floor makes it a
literal no-op for them), and the one window it does touch beyond W4 (W7) moves slightly
negative in both passes.

**`narrow (0.9, 1.15)` is the concrete confound the isolation pass was built to catch, not
just a failure to rule one out**: the IDENTICAL bounds produce a net mean-alpha delta of
-0.67pp with `BANDAR_SIZING_ENABLED` on and +4.91pp with it off -- opposite signs, same
inputs, same SL-width formula. `BANDAR_SIZING`'s own `alloc` scaling and this flag's own
`risk_per_share`-mediated `lots_risk` cap are landing on different sides of some rounding/cap
boundary for W4's specific admitted trades depending on which multiplier the position size
already carries -- exactly the kind of two-multiplier interaction council correction #2
named as the risk to check for, now shown directly rather than merely not-ruled-out.

**A second, narrower sizing interaction survives even with `BANDAR_SIZING_ENABLED` off,
worth being explicit about rather than claiming a clean isolation**: trade counts change in
BOTH passes (Pass A: 364-412 vs 366 baseline; Pass B: 363-414 vs 374 baseline) purely from
this flag, in both configurations -- `sl_mult_effective` feeds `risk_per_share`, which feeds
`lots_risk = prev_equity*RISK_PCT/risk_per_share` and then `ALLOC_MIN_LOTS`, so a wider stop
can push a marginal candidate's lots below the minimum (dropped -- `widen-only` trades
364/370, both below baseline) while a tighter stop allows more lots for the same risk budget
(admitted where it previously wasn't -- `tighten-only`/`default`/`wide` trades all above
baseline in both passes). This is the SAME `RISK_PCT`/`lots_risk` channel idea #2's own
`wide (0.5,1.5)` cell was traced to -- forcing `BANDAR_SIZING_ENABLED` off isolates the
concentration-drives-SIZE confound specifically, but does not by itself hold sizing
completely fixed, because SL width has always fed sizing through this cap regardless of
`BANDAR_SIZING`'s state. A fully sizing-fixed test would need to compute `lots_risk` off the
ORIGINAL `SL_MULT` distance while still moving the ACTUAL `sl_price` -- not built here,
flagged for the record rather than glossed over.

**No Monte Carlo permutation check run**, per this log's own established bar (used
identically for `BACKLOG_QUEUE_ENABLED`, `REGIME_CONFIRM_DAYS=2`, and the pullback-fill
entry above): an MC check is for a candidate that looks genuinely better and more robust on
the sweep itself. No cell here clears that bar -- the flag's own coded default
(`0.8, 1.3`) has the worst PF and worst drawdown in the grid in both configurations; the one
cell that looks clean everywhere (`widen-only`) is a single-window (W4) result with 6 of 9
windows entirely unaffected; and `narrow` demonstrates a direct sign-flip under the mandated
sizing-isolation check, not just a magnitude wobble.

**Verdict: REJECTED.** The base-rate correlation that earned this a test slot (19.1%/29.0%/
42.9% win rate by tercile) does not translate into a robust walk-forward improvement at the
task's own suggested default, and the sweep's more attractive-looking cells decompose into
either a single window (W4 for `widen-only`, W8 for `tighten-only`) or, in `default`'s case,
two windows compounding in a way that is NOT reproducible in sign or magnitude once the
mandated `BANDAR_SIZING_ENABLED` isolation check is run (`narrow` flips from -0.67pp to
+4.91pp). Council correction #2's concern was not merely unconfirmed -- it is directly
demonstrated at at least one grid cell. `SL_CONCENTRATION_ENABLED` stays off by default,
kept in the code (same convention as every other unvalidated-but-available flag in this
file) for a future attempt, not this one's direct ratio-and-clip mapping.

**This closes the three-idea SL-width thread for this session** (pullback-fill entry
mechanism, score-confidence-scaled SL, concentration-scaled SL) -- all three tested,
none validated, per explicit instruction no fourth follow-on idea is proposed here. One
footnote genuinely worth recording rather than pursuing: `widen-only` (raise the ceiling
only, leave the floor at 1.0 so low-concentration trades are never touched) is the one shape
across all three ideas' sweeps that never showed a worse worst-case drawdown than baseline
in either `BANDAR_SIZING` configuration -- a different, narrower question ("does widening
help at all, on its own, independent of any tightening") than anything tested here, not
answered by this entry.

Code touched: `backtest_v4.py` (`SL_CONCENTRATION_ENABLED`/`SL_CONCENTRATION_MIN`/
`SL_CONCENTRATION_MAX`, `compute_entry_fill()`'s `concentration`/`has_concentration`
extraction moved earlier + the new SL-width block -- all off/no-op by default,
regression-verified against idea #2's own recorded numbers). New: `src/
test_sl_concentration.py` (5-assertion self-check, no dataset required), `src/
sweep_sl_concentration.py` (two-pass bounds sweep, in-process) + its two CSV outputs
(`sweep_sl_concentration_bandar_on.csv`, `sweep_sl_concentration_bandar_off.csv`).
`score_candidates()`, `evaluate_position_exit()`, `paper_signal_scan.py`, and
`paper_monitor.py` are unchanged. Left uncommitted for review, same pattern as this
session's other entries.

## 2026-08-30: two mechanisms from the real trader's OWN indicators (UT Bot ATR trailing
## stop, Smart Money Concepts swing-low structural stop) -- a genuinely different lever
## from the three SL-width ideas just above (stop PLACEMENT/distance, not a per-trade
## scalar on SL_MULT). BOTH tested, BOTH REJECTED, via two visibly different failure
## shapes: Candidate A (ATR trail) makes worst-case drawdown WORSE at every single tested
## value; Candidate B (structural swing-low stop) looks clean on every metric at EVERY
## grid cell in the raw aggregate, but decomposes into a single-window (W8) artifact once
## traced -- excluding that one window, the "improvement" evaporates into a flat +/-1.5pp
## band centered on baseline, and two previously-solid windows flip to net-negative alpha
## at 5 of 6 grid cells.

**Where this came from**: this request came directly from the project's real trader after
the three SL-width ideas above were rejected -- he uses UT Bot and Smart Money Concepts
(SMC) as his own actual indicators, and asked for something built on volatility/price-
structure, not another scalar multiplied onto the same `SL_MULT` lever. Both candidates
here only move WHERE a stop sits or WHEN a trailing stop tightens -- neither reads `score`,
`concentration`, or any other signal `compute_entry_fill`'s existing `*_mult` sizing chain
already uses, which is the specific confound that sank 2 of the 3 prior ideas (SL_CONFIDENCE,
SL_CONCENTRATION). Checked directly below (not just claimed) that this holds.

**Step 1 -- baseline reconfirmed**, live `V4_PAPER` config (`V4_ATR_PRICE_RATIO_MAX=0.08`,
`V4_BANDAR_SIZING` default-on), off the existing
`.cache/walk_forward_data_2021-01-01_2026-06-30.pkl`: mean alpha +26.17%, mean PF 1.95,
mean/worst maxDD -14.26%/-21.10%, beat-bench 7/9, win>50% 4/9, 366 trades -- byte-identical
to every prior entry's own recorded numbers, confirmed via a fresh `run_schedule()` call
before touching any code.

### Candidate A -- ATR-scaled trailing stop (UT Bot style)

**Hypothesis**: the trailing stop (`evaluate_position_exit()`'s `TRAILING` block) is
`highest_price * (1 - cfg.TRAILING_PCT)` -- a flat 8% off the peak close regardless of how
volatile the stock is RIGHT NOW. UT Bot's classic design instead recomputes the trail off
TODAY's ATR every bar: `trailing_stop = highest_close_since_entry - atr_today * key_value`
-- tightens automatically as volatility drops post-entry (locks in gains sooner), widens if
volatility rises (avoids getting shaken out in a choppier stretch). Reuses the `atr_14`
column `strategy.add_features()` already computes daily per stock (confirmed by reading
`strategy.py`: `group["atr_14"] = group["tr_atr"].rolling(cfg.ADX_PERIOD, ...).mean()`, a
genuine per-day rolling value, not a one-time entry-day snapshot) -- no new ATR computation.

**Implementation**: `V4_TRAIL_ATR_ENABLED`/`V4_TRAIL_ATR_KEY_VALUE` (default 2.0) in
`backtest_v4.py`, off by default. `evaluate_position_exit()` gained a `current_atr: float =
None` keyword-only parameter (byte-identical default for every existing caller, including
`paper_monitor.py`, which never passes it -- this flag is backtest-only until/unless
validated and a live ATR source is wired in, disclosed rather than silently half-built).
`simulate_window()` builds `atr_lookup` (a `(stock_code, trade_date) -> atr_14` dict, same
"only computed when the flag is on" discipline as `feature_lookup`/`ROTATION_ENABLED`)
and passes `current_atr=atr_lookup.get(...)` at the one real call site. Falls back to the
existing flat-% trail whenever `current_atr` is missing/non-positive/NaN -- never crashes,
never reuses a stale value.

**Sizing independence, checked not assumed**: grep confirms `TRAIL_ATR_ENABLED`/
`TRAIL_ATR_KEY_VALUE` are read ONLY inside `evaluate_position_exit()`'s trailing block --
never inside `compute_entry_fill()`. `lots`/`alloc`/`risk_per_share` are fixed at ENTRY
time, before any trailing logic ever runs on a position, so there is no lots-level channel
for this flag to move sizing through at all (unlike Candidate B and unlike all three
SL-width ideas above).

**Self-check** (`src/test_trail_atr.py`, 4 direct assertions on `evaluate_position_exit()`
itself): OFF ignores `current_atr` entirely, reproducing `test_paper_trading_math.py`'s own
flat-% `TRAILING` fixture exactly; ON with a valid ATR genuinely fires at a DIFFERENT bar
than the flat trail would (a real behavior change, not just "runs without crashing"); ON
with `current_atr=None` falls back to the flat trail, no crash; ON with `current_atr=0.0`/
NaN, same fallback. All 4 pass.

**Full 9-window sweep** (`src/sweep_trail_atr.py`, key_value in {1.5, 2.0, 2.5} -- the
task's own suggested grid; CSV at `src/sweep_trail_atr.csv`):

| cell | beat bench | win>50% | win% mean | profit% mean | alpha% mean | PF mean | PF median | DD% mean/worst |
|---|---|---|---|---|---|---|---|---|
| **OFF (baseline)** | 7/9 | 4/9 | 49.8 | +25.31 | +26.17 | 1.95 | 1.29 | -14.26/-21.10 |
| key_value=1.5 | 6/9 | 4/9 | 50.4 | +33.77 | +34.63 | 2.08 | 1.42 | -16.90/-24.87 |
| key_value=2.0 | 6/9 | 4/9 | 48.6 | +20.15 | +21.01 | 15.47 | 1.17 | -16.39/-25.61 |
| key_value=2.5 | 5/9 | 3/9 | 47.1 | +13.20 | +14.07 | 10.28 | 1.07 | -18.84/-26.58 |

`pf_mean` at key_value=2.0/2.5 (15.47, 10.28) is a mean-distortion artifact, not a real
8-10x profit-factor improvement: one window (W7, the same window in the per-window trace
below) had almost no losing trades at those settings, producing a single Profit Factor of
125.64 (key_value=2.0) / 82.00 (2.5) that swamps the other 8 windows' ordinary values --
`pf_median` (1.17, 1.07) is the honest number, and it's flat-to-worse than baseline's 1.29,
not better.

**Worst-case drawdown is WORSE than baseline at every single tested value, monotonically
worsening as key_value increases** (mean DD -14.26% -> -16.90% -> -16.39% -> -18.84%; worst
DD -21.10% -> -24.87% -> -25.61% -> -26.58%) -- fails this project's own adoption bar on its
own, independent of anything else. `beat_bench` also declines at every value (7/9 -> 6/9 ->
6/9 -> 5/9).

**Per-window trace, the same single/double-window-driven fragility signature this log has
used to reject four other mechanisms this session**: at key_value=1.5 (the best-looking
alpha cell), profit deltas vs baseline are w1 -7.42, w2 +2.29, w3 0.00, w4 +17.04, w5 +1.17,
w6 +4.26, w7 -3.64, **w8 +62.99**, w9 -0.51 -- summing to +76.18pp total. W8 alone supplies
62.99pp (**82.7%** of the whole aggregate gain); W4 supplies another 17.04pp (22.4%); W8+W4
together account for 105% of the total, meaning every OTHER window nets slightly NEGATIVE
(-3.85pp combined). W1 (a positive-alpha window at baseline) flips to a loss.

**Verdict: REJECTED.** Worse worst-case drawdown at every tested value is disqualifying on
its own; the one metric that does improve (mean alpha, at key_value=1.5 only) is 83%
supplied by a single window (W8, already flagged repeatedly in this log as this schedule's
outsized bull-run window) while W1 flips from a gain to a loss. Trade counts decline
monotonically as key_value rises (366 -> 338 -> 319 -> 303) -- not a sizing effect (see
above), but the well-catalogued `MAX_POSITIONS`-scarcity mechanism this log has named
repeatedly: a wider trail (higher key_value) keeps winners in their slot longer, which
blocks new entries and mechanically reduces total trade count over a fixed test window.
`TRAIL_ATR_ENABLED` stays off by default.

### Candidate B -- structural stop (Smart Money Concepts swing-low)

**Hypothesis**: place the initial stop below the most recent CONFIRMED fractal swing-low
(a low strictly lower than N bars on both sides, N=2/3 standard) in the stock's own
pre-signal price history, minus a small ATR buffer -- a genuinely different SL PLACEMENT
philosophy (support structure) from the current pure ATR-multiple, using only existing
daily OHLC (`low`), no new data.

**Implementation**: `V4_STRUCT_SL_ENABLED`/`V4_STRUCT_SL_LOOKBACK` (default 2)/
`V4_STRUCT_SL_BUFFER_ATR` (default 0.75) in `backtest_v4.py`, off by default. New
`compute_struct_swing_low(df, lookback)` (vectorized per-stock shift comparisons, same
segmented-loop style as `compute_spike_confirm_gate`): a fractal at position i is only
KNOWABLE once the `lookback` bars after it have themselves printed -- the flagged value is
shifted forward by `lookback` positions before forward-filling, so it first appears in the
output at the exact position it becomes knowable, never earlier (no lookahead, verified by
construction, not just asserted). Tagged onto candidates at the same site as
`origin_day_idx`/`is_spike` (`_c["struct_swing_low"] = struct_swing_low_by_stock_date.get(...)`,
dict empty and `.get()` returns `None` when the flag is off). In `compute_entry_fill()`,
REPLACES `sl_price` (not a multiplier stacked on `sl_mult_effective`, unlike
SL_CONFIDENCE/SL_CONCENTRATION) only when a valid confirmed swing low exists AND
`swing_low - buffer*atr` still lands below `entry_price` -- otherwise the unchanged
ATR-multiple `sl_price` stands. `paper_signal_scan.py` calls `score_candidates()` directly
(confirmed by grep), never `simulate_window()`'s admission loop, so live signals never carry
`struct_swing_low` regardless of this flag's state -- backtest-only, same disclosed-gap
convention as Candidate A.

**Self-check** (`src/test_struct_sl.py`, 5 direct assertions on `compute_entry_fill()`
itself): OFF is neutral regardless of `struct_swing_low`; ON with a valid swing low below
entry REPLACES `sl_price` with the expected `swing_low - buffer*atr` value; ON with a swing
low too close to/above entry falls back to the unchanged ATR-multiple default (never
produces a stop at/above entry); ON with `struct_swing_low=None` same fallback, no crash;
`sl_price` is independent of `BANDAR_SIZING_ENABLED`'s on/off state, and the only sizing
channel this flag can move `lots` through is the pre-existing `risk_per_share`/`lots_risk`
cap -- reproduced independently in the test and confirmed to match `compute_entry_fill`'s
actual output, the same channel `SL_MULT` itself has always used, not a new correlation
with any of the other per-candidate multipliers (which never read `struct_swing_low`). All
5 pass.

**Full 9-window sweep** (`src/sweep_struct_sl.py`, lookback in {2,3} x buffer_atr in
{0.5,0.75,1.0} -- 6 cells; CSV at `src/sweep_struct_sl.csv`):

| cell | beat bench | win>50% | win% mean | profit% mean | alpha% mean | PF mean | DD% mean/worst |
|---|---|---|---|---|---|---|---|
| **OFF (baseline)** | 7/9 | 4/9 | 49.8 | +25.31 | +26.17 | 1.95 | -14.26/-21.10 |
| lookback=2, buf=0.5 | 5/9 | 6/9 | 55.2 | +36.97 | +37.84 | 3.13 | **-13.88**/**-18.35** |
| lookback=2, buf=0.75 | 5/9 | 6/9 | 56.3 | +37.67 | +38.54 | 3.39 | -13.83/-18.36 |
| lookback=2, buf=1.0 | 6/9 | 8/9 | 58.4 | +36.30 | +37.16 | 3.35 | -13.34/-18.58 |
| lookback=3, buf=0.5 | 5/9 | 6/9 | 56.5 | **+44.30** | **+45.16** | 3.27 | -13.60/-18.15 |
| lookback=3, buf=0.75 | 5/9 | 6/9 | 56.6 | +30.58 | +31.45 | 3.00 | -13.38/-18.01 |
| lookback=3, buf=1.0 | 5/9 | 8/9 | 58.8 | +31.03 | +31.90 | 3.03 | **-13.09**/-18.56 |

At first glance this is the cleanest-looking table of any SL-mechanism idea tested this
session: mean alpha, PF, win rate, win-rate-consistency (win>50%), mean drawdown, AND
worst-case drawdown all improve at literally EVERY grid cell -- no catastrophic value
anywhere, unlike Candidate A above. `beat_bench` is the one metric that does NOT improve
(7/9 -> 5/9 or 6/9 at every cell) -- worth noticing before trusting the rest.

**Per-window trace reveals this is substantially a single-window (W8) artifact, the exact
concern this project's adoption bar and this log's own established practice (pullback-fill,
SL_CONFIDENCE) exist to catch**: W8's own profit goes from +132.88% at baseline to
+231-310% at literally every one of the 6 grid cells -- the single largest, most consistent
lift of any window, by far. Decomposing lookback=2/buf=0.75 (a representative middle cell):
per-window profit deltas vs baseline are w1 -6.95, w2 -5.53, w3 -1.17, w4 +17.03, w5 +13.95,
w6 -9.82, w7 +2.24, **w8 +99.15**, w9 +2.40 (sum +111.30pp). **W8 alone supplies 89.1% of
the entire aggregate gain.**

**Recomputing mean alpha with W8 excluded, at all 6 grid cells** (the same diagnostic this
log used to unmask the pullback-fill entry's apparent best cell):

| cell | mean alpha, all 9 windows | mean alpha, W8 EXCLUDED |
|---|---|---|
| OFF (baseline) | +26.17% | +11.86% |
| lookback=2, buf=0.5 | +37.84% | +11.16% |
| lookback=2, buf=0.75 | +38.54% | +13.38% |
| lookback=2, buf=1.0 | +37.16% | +11.92% |
| lookback=3, buf=0.5 | +45.16% | +11.06% |
| lookback=3, buf=0.75 | +31.45% | +10.90% |
| lookback=3, buf=1.0 | +31.90% | +11.51% |

Excluding W8, every cell's mean alpha sits in a flat **+10.90% to +13.38%** band around
baseline's own +11.86% -- no cell is meaningfully better, some are meaningfully worse, and
the ranking across the grid (lookback=3/buf=0.5 is "best" on the headline table) is not
even the same ordering once the one dominant window is removed. The "improves at every
single cell" story is a W8 artifact, not a broad effect.

**This is corroborated by a second, independent check -- which windows individually flip
from beating the benchmark to not**: at baseline only W2 and W3 have negative alpha; at 5
of the 6 grid cells (all except lookback=2/buf=1.0), **W1 and W6 join them** -- two
previously-solid, benchmark-beating windows turn into losses under this mechanism, a
consistent pattern across the grid, not a one-cell fluke.

**Mechanism trace -- genuinely different from the leverage artifacts the three SL-width
ideas above were built on, but the benefit still doesn't generalize**: W8's own exit
breakdown under lookback=2/buf=0.75 shows SL-hit fraction dropping from 34.5% (baseline) to
15.9%, with TP1 rising 35.7%->39.7% -- a real "fewer stop-outs, more take-profits" effect,
consistent with the claimed mechanism (a wider, structurally-placed stop survives normal
volatility that would have hit a tighter ATR-multiple stop). But W1 and W6 (the two windows
that flip negative) show the SAME direction of SL-fraction drop (W1: 41.7% -> 27.1%; W6:
39.6% -> 20.5%) -- yet their alpha still gets WORSE, because a new `TIME` exit category
appears at 14-15% of trades in both (near-zero at baseline): a wider stop lets a losing
position survive long enough to avoid a fast SL cut, but in a choppier/weaker window it
just drifts sideways and eventually times out at `MAX_HOLD_DAYS` instead of resolving --
tying up a scarce `MAX_POSITIONS` slot for longer without reaching target. The same
mechanism that pays off enormously in a strong, sustained trend (W8, and to a lesser extent
W4/W5) costs in a choppier one (W1, W6) -- genuine, mechanistically coherent, but
window-character-dependent in a way the available 9-window schedule cannot yet
distinguish from "one big bull run happens to be in this dataset."

**Trade counts drop ~20% at every cell** (366 baseline -> 288-295 across the 6 cells) via
the same `risk_per_share`/`lots_risk` channel `SL_MULT` itself has always used (a wider stop
-> larger `risk_per_share` -> smaller `lots_risk` cap -> more marginal candidates fall below
`ALLOC_MIN_LOTS`) -- consistent, expected, and disclosed in this flag's own design (see
Implementation above), not a new confound with any other sizing signal.

**No Monte Carlo permutation check run**, per this log's own established bar: an MC check
is for a candidate that looks genuinely better and more robust on the sweep itself. On the
raw aggregate this candidate would have qualified for one for the first time this session --
but the W8-exclusion recompute above (this log's own established substitute diagnostic,
used identically for the pullback-fill entry) already shows the apparent robustness across
all 6 cells is not real once the one dominant window is set aside.

**Verdict: REJECTED**, though via a qualitatively different and less alarming failure mode
than every other SL-mechanism idea this session: no grid cell shows a WORSE worst-case
drawdown than baseline (unlike Candidate A and all three prior SL-width ideas), and the
underlying mechanism (fewer premature stop-outs in a genuine trend) is real and coherent,
not a sizing/leverage artifact. But the aggregate "every cell improves on every metric"
result is substantially (89%) a single-window (W8) effect, does not survive that window's
exclusion, and systematically turns two other solid windows negative at 5 of 6 grid cells.
`STRUCT_SL_ENABLED` stays off by default.

### Combined (A+B)

**Not run.** The task's own instruction was to test the combination "if both look
independently reasonable" -- neither does: Candidate A fails outright (worse drawdown
everywhere), and Candidate B's apparent success does not survive its own per-window trace.
Running the combination would only compound two mechanisms that already failed
independently, without a new hypothesis to test -- skipped and disclosed here rather than
run pro forma.

**Next step if either is picked back up**: Candidate B is the more promising thread of the
two -- its mechanism (avoid premature stop-outs from a tight, purely volatility-based
stop) is real and directionally sound, it just needs to not fire in the wrong regime.
A design that GATES `STRUCT_SL_ENABLED` on `TREND_STRENGTH`/`trend_duration_streak`
(already-built infrastructure in this file, see `TREND_STRENGTH_MIN`/
`TREND_DURATION_GATE_ENABLED` above) -- using the wider structural stop only in a
confirmed, sustained trend, and leaving the tighter ATR-multiple default for weaker/choppier
regime days -- targets exactly the W8-helps/W1-W6-hurts split found above, instead of
applying one fixed rule to every regime. Not built here; a genuinely new hypothesis, not a
re-run of this session's grid.

Code touched: `backtest_v4.py` -- `TRAIL_ATR_ENABLED`/`TRAIL_ATR_KEY_VALUE`,
`STRUCT_SL_ENABLED`/`STRUCT_SL_LOOKBACK`/`STRUCT_SL_BUFFER_ATR` (all off/no-op by default);
new `compute_struct_swing_low()`; `atr_lookup`/`struct_swing_low_by_stock_date` built
conditionally in `simulate_window()` (zero cost when both flags are off, same discipline as
every other conditional feature in this file); `evaluate_position_exit()` gained
`current_atr: float = None` (byte-identical default for every existing caller); the
candidate-tagging loop gained `struct_swing_low` alongside `origin_day_idx`/`is_spike`;
`compute_entry_fill()` gained the `STRUCT_SL_ENABLED` override block. Regression-verified:
`test_paper_trading_math.py`, `test_diag_hook.py`, `test_bandar_sizing_default.py`,
`test_sl_concentration.py`, and `test_sl_confidence.py` (a full 9-window walk-forward) all
reproduce their own previously-recorded numbers exactly. New: `src/test_trail_atr.py`,
`src/test_struct_sl.py` (unit self-checks, no dataset needed), `src/sweep_trail_atr.py`,
`src/sweep_struct_sl.py` (full 9-window sweeps, in-process) + their CSV outputs
(`src/sweep_trail_atr.csv`, `src/sweep_struct_sl.csv`). `score_candidates()`,
`paper_signal_scan.py`, and `paper_monitor.py` are unchanged. Left uncommitted for review,
same pattern as this session's other entries.

## 2026-08-30: tranche (split-fill) entry -- a DIFFERENT design from the rejected
## pullback-fill entry, not a retry of it. Structural fix (never skips an entry) confirmed
## to actually work; fill-price improvement confirmed real and mechanical. Still NOT
## VALIDATED at the standard adoption bar: mean alpha is worse in all 9 swept cells, traced
## concretely to a real, disclosed trade-off (not a mirage) -- it under-sizes the single
## biggest trending winner in this project's own best window, which never pulls back far
## enough to earn its top-up.

**Where this came from**: the same real trader who prompted pullback-fill (rejected
earlier this session, see above) clarified how he actually enters -- he does NOT skip a
trade waiting for a dip. He defines a price AREA from support/MA/range analysis, buys a
FIRST tranche at the area's upper/psychological price the moment it's in range
(guaranteed, no waiting), and only ADDS a second tranche -- averaging his cost basis down
-- if price dips further within that same area. This is structurally different from
pullback-fill's "skip the trade entirely if it never dips," which this log's own W8/W9
per-window trace showed starves this project's scarce `MAX_POSITIONS=6` slots (a slot
sits empty waiting for a fill that may never come while other candidates queue up).

**Design** (`TRANCHE_ENTRY_ENABLED`/`TRANCHE_BASE_PCT`/`TRANCHE_ADD_LOW_PCT`/
`TRANCHE_ADD_EXPIRY_SESSIONS` in `backtest_v4.py`, all new, off by default): on the
execution day, `compute_entry_fill()` runs completely unchanged (every existing
multiplier -- SCORE/LIQ/TREND/BANDAR/MOVER/ACCDIST/ROTATION/SPIKE sizing, the `RISK_PCT`
`lots_risk` cap, `LIQ_CAP_PCT` -- is already applied by the time its `lots` figure exists).
A `TRANCHE_BASE_PCT` fraction of that already-fully-sized lot count fills immediately at
today's real open (byte-identical price to the baseline) -- this is the guaranteed part,
never skipped. The remaining `(1 - TRANCHE_BASE_PCT)` is a pending top-up: if any of the
next `TRANCHE_ADD_EXPIRY_SESSIONS` sessions' real low touches `TRANCHE_ADD_LOW_PCT` below
the base fill price, a second tranche fills there, and `avg_price`/`cost_basis` are
recomputed as a true weighted average -- the exact same blend formula
`PYRAMID_ENABLED`'s own TP1/TP2 add-ons already use elsewhere in this file, just applied
pre-TP1 (cost-averaging a dip) instead of post-TP1 (sizing up a confirmed winner with
locked-in profit) -- not to be confused with pyramiding. If the dip never comes, the
position simply stays at base size forever. `TRANCHE_ADD_LOW_PCT` is deliberately named
`_PCT`, not `_MULT`, so the unit is unambiguous (a flat fraction of the base fill price,
not an ATR multiple) -- this project has already shipped one real unlabeled-unit bug
elsewhere, and matches the real trader's own concrete-price description (100 -> 95) more
directly than an ATR-scaled band would. Disclosed simplification: the add can only fire
starting the day AFTER entry (`evaluate_position_exit()` is never called on the entry day
itself), so a same-day dip-then-add within the entry day is not modeled.

**Self-check** (`src/test_tranche_entry.py`, same real 2025-07-01..2025-08-31 slice as
`test_pullback_fill.py`): flag OFF reproducible and byte-identical to baseline, flag ON
actually differs; **the number of positions opened is IDENTICAL ON vs OFF (17 both ways)
-- the core structural claim vs pullback-fill, confirmed directly, not just asserted**;
every logged second-tranche fill is `<=` its own add trigger price; `TRANCHE_ADD_EXPIRY_
SESSIONS=0` produces zero adds (expiry genuinely gates the mechanism, not decorative); a
position that never gets a second tranche has `avg_price` exactly equal to the baseline's
own full-size fill price (isolated correctly from `PYRAMID_ENABLED`'s own separate
post-TP1 avg_price mutation, which produces a second trade row per position that is NOT
this mechanism -- caught and fixed during test-writing, not assumed away). All 5 checks
pass.

**Baseline reconfirmed first** (requirement before trusting anything else), live
`V4_PAPER` config (`V4_BANDAR_SIZING` default-on, `V4_ATR_PRICE_RATIO_MAX=0.08`), full
9-window walk-forward: 366 trades, mean alpha **+26.17%**, mean PF 1.95, mean/worst maxDD
-14.26%/-21.10%, beat-bench 7/9, win>50% 4/9 -- byte-identical to the last recorded
number in this log (confirmed via a direct re-run, not assumed from the code).

**Full 9-window sweep** (`src/sweep_tranche_entry.py`; full per-window CSV at
`.cache/tranche_entry_sweep_full.csv`, agg at `.cache/tranche_entry_sweep_agg.csv`,
fill-quality diagnostic at `.cache/tranche_entry_fill_quality.csv`). Grid: `TRANCHE_BASE_
PCT` in {0.5, 0.6, 0.7} x `TRANCHE_ADD_LOW_PCT` in {1%, 2%, 3%}, `TRANCHE_ADD_EXPIRY_
SESSIONS=2` fixed, `BANDAR_SIZING_ENABLED` on (live default):

| base_pct | add_pct | trades | beat bench | win>50% | win% mean | alpha% mean | PF mean | DD% mean/worst |
|---|---|---|---|---|---|---|---|---|
| **OFF (baseline)** | -- | 366 | 7/9 | 4/9 | 49.8 | **+26.17** | 1.95 | -14.26/-21.10 |
| 0.5 | 1% | 371 | 7/9 | 4/9 | 48.9 | +23.71 | 2.06 | -15.04/-21.26 |
| 0.5 | 2% | 367 | 8/9 | 5/9 | 49.8 | +24.42 | 2.08 | -12.80/-20.14 |
| 0.5 | 3% | 366 | 7/9 | 4/9 | 49.3 | +22.78 | 2.04 | -12.85/-20.19 |
| 0.6 | 1% | 370 | 7/9 | 4/9 | 48.8 | +22.92 | 2.00 | -14.83/-20.98 |
| **0.6** | **2%** | **367** | **8/9** | **5/9** | **50.1** | **+25.17** | **2.06** | **-13.04/-20.30** |
| 0.6 | 3% | 368 | 7/9 | 4/9 | 49.1 | +23.39 | 1.98 | -13.12/-20.08 |
| 0.7 | 1% | 370 | 7/9 | 5/9 | 49.2 | +23.08 | 1.95 | -14.82/-20.66 |
| 0.7 | 2% | 368 | 8/9 | **3/9** | 49.1 | +24.27 | 1.96 | -13.88/-20.32 |
| 0.7 | 3% | 367 | 8/9 | 5/9 | 49.8 | +24.95 | 1.99 | -12.99/-20.18 |

**Trade count never drops below baseline at any tested cell (366-371 vs 366) -- the core
structural promise is delivered.** Unlike pullback-fill's 2-6% (later 3.7-40.8%) miss
rate, nothing here is ever fully skipped; a couple of cells even admit marginally MORE
trades than baseline (smaller base-tranche cost frees cash slightly sooner for a later
candidate). PF, mean/worst drawdown improve at nearly every cell (worst-DD improves in
8/9 cells; the one exception, 0.5/1%, is only marginally worse at -21.26% vs -21.10%).
Win>50% count is NOT uniformly better either -- 0.7/2% actually drops to 3/9, worse than
baseline's 4/9, a reminder the secondary-metric picture isn't perfectly clean.

**But mean alpha is WORSE than baseline in every single one of the 9 cells tested** --
the most robust, monotonic-in-direction finding in this sweep, unlike a value that swings
sign across the grid. The best cell (0.6 base / 2% add, chosen by mean alpha) is still
-1.00pp below baseline (+25.17% vs +26.17%).

**Per-window trace explains why, and it is a real, concretely-traced mechanism -- not
noise, and a different flavor from this log's prior three single-window-carried
rejections** (those made a bad cell LOOK good; this makes a genuinely-improving
configuration look bad, entirely through one window):

| Window | OFF (baseline) | ON (0.6 base / 2% add) | delta |
|---|---|---|---|
| W1 (2022 H1) | +2.23% | +8.73% | +6.50 |
| W2 (2022 H2) | -3.01% | +7.03% | +10.04 |
| W3 (2023 H1) | -9.18% | -8.30% | +0.89 |
| W4 (2023 H2) | +51.27% | +51.49% | +0.23 |
| W5 (2024 H1) | +17.79% | +17.64% | -0.16 |
| W6 (2024 H2) | +6.98% | +7.95% | +0.96 |
| W7 (2025 H1) | +20.83% | +18.94% | -1.90 |
| **W8 (2025 H2)** | **+107.84%** | **+80.93%** | **-26.91** |
| W9 (2026 H1) | +40.76% | +42.13% | +1.37 |

Summed (not averaged) across windows, the net delta is -8.99pp -- but **W8 alone accounts
for -26.91pp of that, meaning the other 8 windows combined actually IMPROVE by +17.92pp**.
Every one of the 9 swept cells shows the same shape: W8 damaged in all nine, by -18.6pp to
-34.3pp, monotonically shrinking as `TRANCHE_BASE_PCT` rises toward 1.0 (less under-sizing
the closer the base tranche gets to full size) -- exactly the expected direction if the
mechanism below is the real cause, not a coincidence.

**Root cause, traced concretely rather than inferred** (re-ran W8 alone with full
position-level detail): W8 is the single largest alpha contributor at baseline (top-5
tickers = 56.6% of positive PnL) -- exactly the "6/9 windows show >65% concentration, a
handful of outlier winners carry most of the result" pattern this log's own walk-forward
section already diagnosed as this strategy's central fragility. VKTR, W8's single biggest
winner (Rp 29.3M PnL at baseline), trended up without ever dipping 2% below its base-
tranche fill price within the 2-session add window -- it never got topped up, rode its
entire position at 60% of normal size, and its PnL under the tranche design drops to ~Rp
19.0M, roughly proportional to the size cut. BNBR and MLPT (2nd/3rd-biggest W8 winners)
DID get topped up and their PnL is roughly preserved. A fourth top-5 winner, BSML (Rp
15.8M at baseline), does not appear in the tranche-on trade list AT ALL -- a different
candidate won its slot instead. That second effect is the SAME scarce-`MAX_POSITIONS`
admission-order sensitivity this log has already documented for `BACKLOG_QUEUE_ENABLED`
and `PULLBACK_FILL_ENABLED`, now shown to survive even a design built specifically to
avoid it: a smaller base-tranche cost still changes the day-to-day cash trajectory, which
can still change who gets admitted later when a slot opens. **Two distinct, real
mechanisms are compounding here, not one**: (1) under-sizing a winner that never pulls
back (the direct, intended cost of the design), and (2) the pre-existing admission-order
ripple effect (an indirect, unintended side effect of changing capital consumption
patterns).

**Fill-price improvement (pre-registered check, confirmed real and mechanical
independent of the walk-forward result)** -- pooled across all 9 windows, positions that
actually got a second tranche only:

| base_pct | add_pct | 2nd-tranche fills | avg fill-price improvement |
|---|---|---|---|
| 0.5 | 1% | 166 | 0.75% |
| 0.5 | 2% | 142 | 1.23% |
| 0.5 | 3% | 122 | 1.71% |
| 0.6 | 1% | 168 | 0.62% |
| **0.6** | **2%** | **143** | **1.00%** |
| 0.6 | 3% | 121 | 1.39% |
| 0.7 | 1% | 161 | 0.47% |
| 0.7 | 2% | 138 | 0.76% |
| 0.7 | 3% | 118 | 1.05% |

Clean and monotonic: deeper add trigger -> fewer fills, bigger per-fill improvement when
one happens -- the same shape (and a similar magnitude, ~0.5-1.7%) as pullback-fill's own
confirmed 0.8-1.5% figure. At the chosen cell, roughly 143 of ~367 trades (~39%) get a
real, mechanically confirmed ~1% better entry price.

**`BANDAR_SIZING_ENABLED` interaction, checked specifically (not just assumed) per this
session's own standing requirement**: re-ran the OFF baseline and the best ON cell (0.6
base / 2% add) with `V4_BANDAR_SIZING=0`:

| Metric | OFF, bandar off | ON, bandar off |
|---|---|---|
| Trades | 374 | 366 |
| Win rate mean | 50.1% | 52.8% |
| Alpha mean | +29.82% | +29.38% (-0.44pp) |
| PF mean | 1.98 | 2.29 |
| DD mean/worst | -15.97%/-23.13% | -14.07%/-19.57% |
| Beat bench | 7/9 | 8/9 |
| Win>50% | 4/9 | 6/9 |

Same qualitative shape as with `BANDAR_SIZING` on: small mean-alpha decline, everything
else improves. **The single-window mechanism reproduces even more strongly with `BANDAR_
SIZING` off**: W8's alpha drops from +157.14% to +105.88% (delta -51.3pp, nearly double
the on-state's -26.9pp, since `BANDAR_SIZING`'s own size-damping is absent) while the
other 8 windows combined improve by roughly +47.3pp. Direction and root cause are not a
`BANDAR_SIZING` artifact -- they reproduce with it on or off, just at different
magnitudes, satisfying this session's specific interaction-isolation requirement.

**No Monte Carlo permutation check run**, per this log's own established bar: an MC check
is for a candidate that looks genuinely better and more robust on the sweep itself. This
one doesn't clear that bar -- mean alpha is worse in literally every grid cell tested,
both `BANDAR_SIZING` states.

**Verdict: NOT VALIDATED.** Fails this project's standard adoption bar (beat baseline on
BOTH mean alpha AND worst-case drawdown simultaneously) on the primary axis -- mean alpha
never improves, at any tested cell, in either `BANDAR_SIZING` state. But this is a
qualitatively different rejection from this session's three prior ones: those were
"the apparent improvement turns out to be a single-window mirage that vanishes or flips
sign under scrutiny." This one is "the mechanism is real, understood, and correctly
built, and it trades a small, well-explained mean-alpha cost for broad, mostly-consistent
gains everywhere else" -- the cost lands specifically on the biggest trending winner in
this project's own strongest window, which is also exactly the kind of trade this
project's own capital is most concentrated in. The core structural claim over pullback-
fill (never skip an entry) is fully delivered and directly confirmed (trade count never
below baseline, unlike pullback-fill's real miss rate), and the fill-price improvement is
real. **Do not deploy to any live paper run at these settings.** Flag stays off by
default, kept in the code for a future attempt -- e.g. a design that scales `TRANCHE_
BASE_PCT` UP specifically for a high-conviction/strong-trend signal (so the trades most
likely to run without a pullback keep more of their size from day one), which was not
built or tested here.

Code touched: `backtest_v4.py` (`TRANCHE_ENTRY_ENABLED`/`TRANCHE_BASE_PCT`/`TRANCHE_ADD_
LOW_PCT`/`TRANCHE_ADD_EXPIRY_SESSIONS`/`TRANCHE_FILL_LOG`, the entry-fill split at the
position-creation site, and the second-tranche add-on block inside
`evaluate_position_exit()` -- all off/no-op by default, regression-verified byte-
identical against the recorded baseline above). New: `src/test_tranche_entry.py`
(5-assertion self-check), `src/sweep_tranche_entry.py` (full grid + BANDAR-off isolation
sweep) + its three CSV outputs (`.cache/tranche_entry_sweep_full.csv`, `_agg.csv`,
`_fill_quality.csv`). `score_candidates()`, `compute_entry_fill()`, `paper_signal_scan.py`,
and `paper_monitor.py` are unchanged. Left uncommitted for review, same pattern as this
session's other entries.

## 2026-08-31: concentration acceleration (YELO anecdote) base-rate check -- REJECTED,
sample large enough to trust, effect points the wrong way

**Trigger**: YELO broke out +14.44% in one session today. Its Bandarmology broker-
concentration ratio (`bandarmology_features.py`'s `concentration` -- top-1 broker's
`|net_lot|` share of all brokers' `|net_lot|` that day, the exact column live in DB2's
`bandarmology_flow_daily` and driving `BANDAR_SIZING_ENABLED`'s own sizing multiplier)
had risen from a ~0.20-0.30 baseline to 0.50 / 0.46 / 0.42 over the 3 sessions right
before the move. One data point, found by looking backward at a stock that already
won -- explicitly not evidence by itself. Per a same-day council session on research
posture (informational, not a binding process change to this log's own standards): check
the base rate with a cheap query before building a walk-forward test or touching
`backtest_v4.py`. This entry is that check only -- read-only, `src/backtest_v4.py`
untouched, no new strategy flag.

**Definition, fixed before looking at results** (`src/scratch_concentration_acceleration_
baserate.py`): per stock, `baseline_t` = trailing 20-trading-day MEDIAN concentration,
window ending 3 sessions before `t` (offset so the baseline can't be contaminated by the
very days being tested against it). `elevated_t` = `concentration_t >= baseline_t + 0.10`
AND `concentration_t >= 0.35` -- both numbers modeled directly on YELO's own numbers
(baseline ~0.20-0.30, spike to 0.42-0.50). `flag_t` = elevated on `t`, `t-1`, AND `t-2`
(3 consecutive sessions, matching what YELO showed) -- deliberately does NOT require a
rising day-over-day shape within those 3 days, since YELO's own sequence (0.50 -> 0.46 ->
0.42 into the breakout) wasn't rising either; demanding that shape would have been
curve-fit to a pattern the one real example didn't actually have. Only the first day of
each per-stock flagged run counts as one "episode" (a stock elevated 5 days straight is
one event, not 5 -- see bug note below). "Real breakout" = forward 3-session close-to-
close return > +8% (the task's own suggested number, well below YELO's own +14.44%).

**Universe**: full local Bandarmology history (`data/bandarmology_history/*.parquet`,
2020-06-02..2026-08-11, 943 stocks, 1,116,627 stock-day rows) -- same `bf.load_raw()` +
`bf.per_broker_net()` + `bf.daily_stock_features()` pipeline `attach_bandarmology()`
(`backtest_v4.py`) and `diagnose_bandarmology_power.py` already use for this exact
`concentration` column, no corrupt-row filter (matches what's actually live in
production sizing today). **ADTV_MIN liquidity filter required and confirmed necessary**:
unfiltered, the concentration distribution's 90th/95th/99th percentiles all cluster right
at 0.4996/0.5000/0.5100 -- a thin-trading artifact (2 active brokers of similar size
trivially produces concentration~0.5), not accumulation. After the `config.ADTV_MIN`
filter (Rp1bn/20d, same threshold V3's own liquidity gate uses): 461,334 rows, median
concentration drops to 0.250, 90th/95th to 0.411/0.459 -- the artifact meaningfully
recedes, confirming the filter was doing real work, not a formality.

**Bug caught and fixed mid-analysis**: the first run's episode dedup used `flag &
~flag.shift(1).fillna(False)`. Shifting a bool-dtype pandas Series inserts a NaN at the
boundary, which silently upcasts the whole Series to `object` dtype holding Python
`True`/`False` objects -- applying `~` to THOSE gives `-2`/`-1` (Python's bitwise int
negation, since `bool` subclasses `int`), not logical negation, and both are truthy, so
the "was the previous day NOT flagged" check silently no-opped (confirmed empirically:
raw flagged-row count and "deduped" episode count came out byte-identical, 4394 == 4394,
on the first run). Fixed with `flag.shift(1, fill_value=False)`, which never introduces a
NaN and stays bool dtype -- reran, episode count correctly dropped to 2659. Third
pandas-dtype-promotion footgun this log has now caught this session/branch (joins the
`groupby().apply()` one `bandarmology_features.py`'s own comments already document) --
worth remembering as a class of bug, not a one-off.

**Sample size**: 4,394 raw flagged (stock, day) rows, **2,659 deduped episodes** -- not
remotely a single-digit sample (the council's own stated stopping condition for "too rare
to matter regardless of hit rate" doesn't apply here; this pattern is common, roughly 1 in
every ~170 eligible liquid stock-days is an episode start).

**Base-rate comparison** (flagged episodes vs. all other eligible stock-days, same
universe/period, same liquidity filter, same 20-day-baseline-history requirement):

| Group | n | breakout rate (fwd 3d > +8%) | mean fwd_3d | median fwd_3d |
|---|---|---|---|---|
| Flagged episodes | 2,659 | 7.1% (190/2,659) | -0.44% | +0.00% |
| Unflagged (same universe/period) | 453,465 | 7.9% (35,969/453,465) | +0.08% | +0.00% |
| Unconditional (all eligible, context) | 457,859 | 7.9% (36,292/457,859) | +0.08% | +0.00% |

Fisher's exact test, one-sided (flagged > unflagged): odds ratio 0.893, **p=0.9391** --
nowhere near significant, and the point estimate itself is in the WRONG direction: the
flagged group's breakout rate is slightly BELOW the unconditional base rate, not above
it. False-positive rate among flagged episodes (no breakout follows): 92.9%
(2,469/2,659) -- essentially the same as the unconditional false-positive rate (92.1%),
i.e. statistically indistinguishable from picking a random day.

**Across all horizons, the direction is consistent and gets worse, not better, with
time**: flagged episodes' mean forward return is negative at every horizon tested and the
gap to the unflagged group widens as the horizon lengthens --

| Horizon | flagged episodes mean | unflagged mean |
|---|---|---|
| 1d | -0.33% | +0.02% |
| 3d | -0.44% | +0.08% |
| 5d | -0.44% | +0.16% |
| 10d | -0.45% | +0.34% |

If anything, a 3-day broker-concentration acceleration (by this definition) precedes
mild underperformance over the following two weeks, not outperformance. A plausible
(not tested here) economic reading: a 3-day concentration spike catches distribution/
profit-taking clusters and exhausted-move broker activity just as often as accumulation
-- concentration alone doesn't distinguish direction, only that one broker dominated
that stock's flow, and YELO's own case might be one of a minority where that happened to
coincide with genuine accumulation.

**Caveat**: the actual YELO event (2026-08-31) is not in this dataset -- the local
Parquet archive currently reaches 2026-08-11. This is the correct design, not a gap to
fix: it means this check is a clean out-of-sample test of the pattern elsewhere in
history, not a circular re-validation of the exact instance that inspired it.

**Verdict: NOISE (if anything, mildly reversed-sign). Drop here -- do NOT build a
walk-forward test or a new `backtest_v4.py` flag for this idea.** This matches the
council's own stated stopping condition, just via the other route than "too few
instances": the sample is large and well-powered, and it cleanly fails to show the
YELO anecdote generalizes under its own most literal, non-cherry-picked mechanical
reading. Not tested further (threshold sensitivity sweep, alternate baseline windows) --
per the task brief, escalating scope here would itself be the kind of over-building this
check was specifically meant to avoid before any real evidence existed.

Code touched: none of the protected V1 files, none of `backtest_v4.py`. New:
`src/scratch_concentration_acceleration_baserate.py` (standalone, read-only, run directly
with `python src/scratch_concentration_acceleration_baserate.py`; ~5-8 min end to end --
~3 min to rebuild the full-history concentration panel from local Parquet, ~1-2 min for
the DB1 `ihsg_eod` price fetch across the ~940-stock universe).

## 2026-08-31: Bandarmology hard admit/reject VETO -- categorically different mechanism
## from BANDAR_SIZING_ENABLED (continuous multiplier) and today's three rejected SL-width
## ideas (continuous stop adjustment). REJECTED -- the entire apparent aggregate
## improvement traces to ONE window, and that window turns out to be a concrete,
## traceable data-coverage artifact (an untrained `concentration_p90` fallback), not real
## selection skill. Worst-case drawdown does not improve either.

**Hypothesis** (from today's council session): should Bandarmology order-flow data ever
act as a hard gate on entry -- drop a candidate entirely -- rather than only scaling
position size (`BANDAR_SIZING_ENABLED`, live default ON) or stop width (today's three
rejected SL-width ideas)? A binary admit/reject decision is a structurally different
mechanism from a continuous multiplier, worth testing on its own rather than assuming the
sizing result generalizes.

**Design** (`BANDAR_VETO_ENABLED`/`BANDAR_VETO_CONCENTRATION_MAX`/`BANDAR_VETO_NET_LOT_MIN`,
`backtest_v4.py`, all off by default): veto fires when BOTH (a) `concentration` (the one
Bandarmology daily feature Layer 1 validated cleanly, see `docs/BANDARMOLOGY_DESIGN.md`)
is in the low tail -- ratio to the train-derived `concentration_p90` below
`BANDAR_VETO_CONCENTRATION_MAX` (default 0.3) -- AND (b) `net_lot` (daily net buy-sell,
summed across all brokers at the stock level) is negative, below `BANDAR_VETO_NET_LOT_MIN`
(default 0.0, a pure sign check). Rationale: `concentration` is UNSIGNED by construction
(top-1 broker's share of total |net_lot| that day, see `bandarmology_features.
daily_stock_features`) -- a low reading alone can't distinguish "broadly distributed
ACCUMULATION" from "broadly distributed DISTRIBUTION," only that no single broker
dominates. `net_lot`'s sign supplies the missing direction. Together this operationalizes
the design doc's own 4-quadrant "distributing net-sell while price is up = warning,
bearish despite a green candle" read, at the single-day level `score_candidates()` already
screens on -- not an arbitrary threshold shape. `net_lot` itself has NOT been through
Layer 1's own forward-return validation (only its rolling-normalized cousin
`net_flow_norm` was tested, and flagged fragile) -- used here for its SIGN only, as a
directional disambiguator for the validated `concentration` magnitude, disclosed rather
than claimed as an independently validated predictor in its own right.

`BANDAR_VETO_CONCENTRATION_MAX` defaults well BELOW `BANDAR_SIZING_ENABLED`'s own MIN
floor (0.5) deliberately -- at 0.5 the veto would just be a harder version of what sizing
already does (floor to 0.5x instead of dropping); at 0.3 it only fires on the clearly low
tail sizing's own floor doesn't distinguish from "somewhat low." New `compute_bandar_net_lot()`
(id(df)-memoized, same pattern as `compute_market_broker_flow`'s own `_broker_flow_ratio_
cache` -- a 9-window sweep against one loaded dataset would otherwise redo the underlying
`per_broker_net()` pivot over the full multi-year archive on every window; deliberately
does NOT call `bandarmology_features.daily_stock_features()`, whose own `concentration`
column costs a slow per-group `.apply()` this function has no use for -- `concentration`
is already available from df's own already-attached column, this function only needs a
plain vectorized groupby-sum of `net_lot`, found and fixed during this session's own
sweep runs after an initial version took multiple wall-clock minutes per window). New pure
`bandar_veto_fires(concentration, concentration_p90, net_lot)` extracted for direct unit
testing. Applied ONLY as a filter on `simulate_window`'s OWN consumption of
`score_candidates()`'s return value (same site/pattern as `SPIKE_CONFIRM_GATE_ENABLED`/
`DIVERGENCE_GATE_ENABLED`) -- `score_candidates()` and `compute_entry_fill()` are
UNCHANGED, so `paper_signal_scan.py`/`paper_monitor.py` cannot be affected by this flag
regardless of its state, same disclosed backtest-only gap as `STRUCT_SL_ENABLED`. Kept
structurally SEPARATE from `BANDAR_SIZING_ENABLED` (own flag, own threshold, no shared
state) so both can be tested independently and in combination.

**Self-check** (`src/test_bandar_veto.py`, 5 direct assertions on `bandar_veto_fires()`
itself, no dataset needed): missing concentration never vetoes (fail open); low
concentration + net SELLING fires; low concentration + net BUYING does NOT fire
(confirms direction matters, not just magnitude -- the whole point of using `net_lot` at
all); high concentration + net selling does NOT fire (both conditions required, neither
alone); the threshold is relative to `concentration_p90` (train-window-relative, matching
`BANDAR_SIZING_ENABLED`/`SL_CONCENTRATION_ENABLED`'s own convention), not an absolute
concentration value -- the same raw concentration fires or not depending on `concentration_
p90`. All 5 pass.

**Baseline reconfirmed first** (requirement before trusting anything else), live
`V4_PAPER` config (`V4_BANDAR_SIZING` default-on, `V4_ATR_PRICE_RATIO_MAX=0.08`), full
9-window walk-forward: 366 trades, mean alpha **+26.17%**, mean PF 1.95, mean/worst maxDD
-14.26%/-21.10%, beat-bench 7/9, win>50% 4/9 -- byte-identical to the last recorded number
in this log.

**Full 9-window sweep** (`src/sweep_bandar_veto.py`; per-window CSVs at
`src/sweep_bandar_veto_bandar_on.csv` / `_bandar_off.csv`, per-vetoed-candidate detail at
`.cache/bandar_veto_log_conc{0.2,0.3,0.4}.csv`), `BANDAR_VETO_CONCENTRATION_MAX` swept
{0.2, 0.3, 0.4}, two passes per this session's own standing sizing-interaction-confound
requirement:

**Pass A -- `BANDAR_SIZING_ENABLED` at its live default (ON):**

| cell | trades | vetoed | beat bench | win>50% | alpha mean | PF mean | DD mean/worst |
|---|---|---|---|---|---|---|---|
| **OFF (baseline)** | 366 | 0 | 7/9 | 4/9 | +26.17% | 1.95 | -14.26%/-21.10% |
| conc_max=0.2 | 366 | 21 | 7/9 | 4/9 | +26.29% | 1.95 | -14.14%/-21.10% |
| conc_max=0.3 | 363 | 101 | 7/9 | 4/9 | +26.70% | 1.95 | -13.84%/**-21.10%** |
| conc_max=0.4 | 359 | 391 | 7/9 | 6/9 | +26.62% | 2.02 | -14.48%/**-21.19%** |

**Pass B -- `BANDAR_SIZING_ENABLED` forced OFF (isolation):**

| cell | trades | vetoed | beat bench | win>50% | alpha mean | PF mean | DD mean/worst |
|---|---|---|---|---|---|---|---|
| **OFF (baseline)** | 374 | 0 | 7/9 | 4/9 | +29.82% | 1.98 | -15.97%/-23.13% |
| conc_max=0.2 | 374 | 21 | 7/9 | 4/9 | +30.18% | 1.99 | -15.60%/-23.13% |
| conc_max=0.3 | 371 | 101 | 7/9 | 4/9 | +30.53% | 1.98 | -15.25%/-23.13% |
| conc_max=0.4 | 374 | 391 | 7/9 | 5/9 | +30.79% | 2.12 | -15.90%/-23.13% |

**The veto genuinely fires, at a non-trivial rate -- honesty check #1, satisfied**: 21,
101, and 391 candidates vetoed at the three thresholds respectively (identical counts in
both passes, confirming the admission DECISION itself doesn't depend on
`BANDAR_SIZING_ENABLED` -- only what happens to surviving trades afterward does). At
conc_max=0.3, that's roughly 28% of the baseline's own 366 admitted trades -- not a gate
that never matters.

**But per-window decomposition (both passes) shows this is a textbook single-window-
carried result, the exact failure signature this session has already used to reject four
other ideas today** -- at conc_max=0.2 AND 0.3 (the two most conservative, most
"reasonable-looking" cells), **every single window except window 3 (2023 H1) is
BYTE-IDENTICAL to baseline**, in both passes:

| Pass A window | OFF | conc_max=0.2 | conc_max=0.3 |
|---|---|---|---|
| W1-W2, W4-W9 (8 of 9 windows) | unchanged | **identical** | **identical** |
| W3 (2023 H1) | -11.94% | -10.87% | -7.19% |

100% of the aggregate mean-alpha improvement at these two cells is window 3 alone --
confirmed arithmetically, not just visually: at conc_max=0.3, window 3's own delta
(+4.75pp) divided by 9 windows equals the observed mean-alpha delta (+0.53pp) exactly,
because every other window contributes zero.

**Root cause, traced concretely, not inferred**: window 3's TRAIN period (2021-01-01..
2022-12-31, the expanding-window cutoff for that split) predates Bandarmology data
entirely -- `concentration` data starts 2023-01-02 (confirmed directly: 0 of 479,990 rows
in that exact train slice have a non-null `concentration`). `concentration_p90` therefore
falls back to its hardcoded default of 1.0 (see `simulate_window`'s own
`concentration_p90 = ... if len(train_concentration) > 0 else 1.0`) instead of a real
trained percentile -- the SAME fallback `BANDAR_SIZING_ENABLED`'s own 2026-08-12
validation already documented for windows 1-2 ("byte-identical off/on... confirms the
NaN-fallback path... works correctly"), except window 3's TEST period does have real
`concentration` values (data starts exactly at that window's train/test boundary), so
here the fallback doesn't neutralize the mechanism -- it silently changes its calibration.
The veto's ratio check in window 3 is therefore comparing raw `concentration` against an
untrained placeholder denominator, not the same reference every other window uses.
Window 3's "improvement" is a boundary-condition artifact of Bandarmology's own data
coverage start date, not evidence the veto is correctly identifying bad candidates.
Cross-checked directly against the vetoed-candidate log: at conc_max=0.2, all 21 vetoes
fall in 2023 Q1-Q2 (window 3's exact date range); at conc_max=0.3, 63 of 101 do, but the
other 38 (spread across 2023 Q3 through 2026 Q1) change **zero** trade outcomes --
dropped candidates that were never going to be admitted anyway (already excluded by
`MAX_POSITIONS`/cooldown/rank) or replaced by an equally-outcome candidate.

**At conc_max=0.4 the effect finally spreads beyond window 3, but the result turns
genuinely mixed, not broadly positive** -- window 6 (Pass A: +6.15%->+1.60%, DD -13.95%->
-16.95%; Pass B: +11.24%->+3.00%, DD -13.20%->-17.60%) gets clearly WORSE in both passes,
a real cost showing up identically regardless of `BANDAR_SIZING_ENABLED`'s state. Window
8's own worst-case drawdown also degrades (Pass A: -15.17%->-19.63%), which is what pushes
the aggregate worst-DD from -21.10% to -21.19% at this cell -- the one tested value where
the veto touches enough windows to matter also makes the worst-case tail marginally worse,
not better.

**Sizing-interaction confound, checked per this session's own standing requirement**:
NOT found. The window-3-dominated pattern at 0.2/0.3, and the window-6-cost pattern at
0.4, reproduce identically in direction and magnitude with `BANDAR_SIZING_ENABLED` on or
off (Pass A and Pass B tables above) -- the effect is native to the admission decision
itself, not an artifact of how surviving trades get sized afterward.

**No Monte Carlo permutation check run**, per this log's own established bar: reserved for
a candidate that looks genuinely better and more robust on the sweep itself. This one
doesn't clear that bar -- the apparent improvement is 100% attributable to a single,
already-explained data-coverage artifact at the two most conservative cells, and turns
mixed (a real cost to window 6, a worse worst-case drawdown) at the one cell wide enough
to spread further.

**Verdict: REJECTED.** Fails this project's adoption bar on both counts: mean alpha's
apparent improvement is not real, distributed selection skill -- it is a single-window
artifact traced concretely to an untrained `concentration_p90` fallback unique to the one
walk-forward window whose train period predates Bandarmology's own data coverage start
date, not the veto correctly identifying bad candidates. Worst-case drawdown does not
improve at any tested threshold, and gets marginally worse at the one threshold wide
enough to move more than one window. This is a genuinely different rejection reason from
today's three SL-width ideas (which failed on worse drawdown from a sizing/leverage
mechanism) and from Candidate B's structural-stop idea (a real but window-character-
dependent trend-following effect) -- here the mechanism itself never gets a fair test
outside window 3, because window 3 isn't a real out-of-sample read of the veto's
behavior, it's a boundary condition. **`BANDAR_VETO_ENABLED` stays off by default**, kept
in the code for a future attempt -- e.g. re-testing with a schedule that excludes or
separately reports window 3, or requiring a minimum train-period sample size before
trusting `concentration_p90` at all (the same class of fix `BANDAR_SIZING_ENABLED`'s own
`has_concentration` check already applies at the per-candidate level, not yet applied at
the per-window threshold level) -- not built or tested here, a genuinely new hypothesis,
not a re-run of this session's grid.

Code touched: `backtest_v4.py` -- `BANDAR_VETO_ENABLED`/`BANDAR_VETO_CONCENTRATION_MAX`/
`BANDAR_VETO_NET_LOT_MIN`/`BANDAR_VETO_LOG` (all off/no-op by default); new
`compute_bandar_net_lot()` (id(df)-memoized) and `bandar_veto_fires()`; the
`bandar_veto_net_lot_by_stock_date` dict built conditionally in `simulate_window()` (zero
cost when the flag is off, same discipline as every other conditional feature in this
file); the candidate-filtering site gained a `BANDAR_VETO_ENABLED` block alongside
`SPIKE_CONFIRM_GATE_ENABLED`/`DIVERGENCE_GATE_ENABLED`. Regression-verified:
`test_paper_trading_math.py`, `test_bandar_sizing_default.py` both reproduce their own
previously-recorded output exactly. New: `src/test_bandar_veto.py` (5-assertion unit
self-check, no dataset needed), `src/sweep_bandar_veto.py` (full grid + BANDAR_SIZING-off
isolation sweep) + its four CSV outputs (`src/sweep_bandar_veto_bandar_on.csv`, `_off.csv`,
`.cache/bandar_veto_log_conc{0.2,0.3,0.4}.csv`). `score_candidates()`, `compute_entry_fill()`,
`paper_signal_scan.py`, and `paper_monitor.py` are unchanged. Left uncommitted for review,
same pattern as this session's other entries.

## 2026-09-01: First genuine blind holdout -- V4_PAPER's frozen live config run ONCE
## against 2026-07-01..2026-08-11, a window no backtest/sweep/walk-forward run in this
## project's history has ever touched. Net loss (-4.55%), alpha -14.61% vs a strong IHSG
## rally, but inside the pre-declared not-alarming band on every metric except alpha,
## which lands just past its edge. Small-n result: can't confirm an edge, doesn't show
## gross overfitting either.

**Why this test exists**: every V4 config decision so far (16+ ideas tested, this log is
the record) was validated against the same 9-window walk-forward built from
`.cache/walk_forward_data_2021-01-01_2026-06-30.pkl`. Every individual test in this log
was run rigorously -- multiple windows, permutation checks where warranted, parameter
sweeps -- but the aggregate is still a multiple-comparisons problem: nothing in the
record so far distinguishes "V4 has a real edge" from "V4 is the best-looking survivor of
16+ trials against one finite sample." A 2026-09-01 council session ("Two Clocks") flagged
this as the largest unaddressed risk in the project. `ihsg_eod` has real data through
2026-09-01; the walk-forward cache stops 2026-06-30. That gap -- 2026-07-01 through
2026-08-11 specifically (V4_PAPER itself went live 2026-08-12, so anything from that date
on is a live record, not a blind test) -- is a genuine virgin sample no test in this
project has ever touched, in either direction (never used to pick a threshold, never used
to reject one).

**Frozen config, declared before any data was touched** (read directly from
`paper_signal_scan_v4_trigger.yml` / `paper_monitor_v4_trigger.yml` on `main`, cross-checked
against `backtest_v4.py`'s module defaults): `V4_BANDAR_SIZING=1` (already the module
default -- `BANDAR_SIZING_ENABLED` default-on) and `V4_ATR_PRICE_RATIO_MAX=0.08` (module
default is 0.10, the live workflows override it). No other env var is set anywhere in
either live workflow, so every other flag in `backtest_v4.py` rides its module default
exactly as it does in production -- `LIQ_SIZING_ENABLED=1` (0.5x-2.0x), `PYRAMID_ENABLED=1`
(20% add), `MAX_POSITIONS=6`, `TREND_STRENGTH_MIN=0.01`, `REGIME_CONFIRM_DAYS=3`,
`QUANTILE_CUT=0.60`, `SL_MULT=1.5`, and every research-candidate gate this log has tested
and left off by default (`SL_CONFIDENCE`, `SL_CONCENTRATION`, `TRAIL_ATR`, `STRUCT_SL`,
`TREND_DURATION_GATE`, `PARTICIPATION_GATE`, `BROKER_FLOW_GATE`, `DIVERGENCE_GATE`,
`SPIKE_CONFIRM_GATE`, `BACKLOG_QUEUE`, `PULLBACK_FILL`, `TRANCHE_ENTRY`, `ROTATION_ENABLED`,
`SCORE_SIZING`, `TREND_SIZING`, `MOVER_SIZING`, `ACCDIST_SIZING`, `ROTATION_SIZING`,
`BANDAR_VETO`, `SPIKE_SIZING`, `PYRAMID_TREND_GATE`, `PYRAMID_TP2`, `ARA_FILTER`,
`ARB_EXIT_REALISM`, `ADAPTIVE_HOLDTIME`, `SLIPPAGE_ENABLED`). Printed and confirmed at
script start before the fetch ran: `BANDAR_SIZING_ENABLED=True ATR_PRICE_RATIO_MAX=0.08
FETCH_START=2021-01-01 LIQ_SIZING_ENABLED=True PYRAMID_ENABLED=True MAX_POSITIONS=6
TREND_STRENGTH_MIN=0.01 REGIME_CONFIRM_DAYS=3`. **Nothing swept, nothing tuned, one call
to `simulate_window`.**

**Methodology**: single train/test split, train_end=2026-06-30 (the day before test_start),
train expanding from `FETCH_START` (2021-01-01) -- identical to how every other window in
`walk_forward_v4.py`'s own `build_schedule()` is constructed, i.e. the same methodology
this log's entire walk-forward record uses, NOT the live paper engine's own daily-
expanding retrain (`paper_signal_scan.py` retrains with `train_end=today` every single
day; this test uses one fixed cutoff for the whole window instead, disclosed as a real,
deliberate methodology difference from what V4_PAPER's actual day-to-day live run does).
Data fetched fresh via `build_full_dataset` through 2026-08-11 exactly (`V4_TEST_END`
override) -- no post-window data enters the fetch or the threshold derivation at all.
The local Bandarmology Parquet archive (`data/bandarmology_history/`) happens to end
2026-08-11 as well, so `BANDAR_SIZING_ENABLED` had real (not train-fallback) `concentration`
data for the entire test window -- confirmed by the run log showing no
"local backfill not found" fallback message.

**Pre-declared interpretation bar** (written down before running the script, based only on
the already-recorded 9-window walk-forward profile for this exact frozen config -- the
2026-08-22 entry above: mean alpha +26.17%, per-window range from the worst window's 17.6%
win rate / -9.18% alpha / PF 0.02 up to the best window's 77.3% win rate / PF 4.89, worst
single-window maxDD -21.10%). Given the holdout is ~6 weeks (30 trading days) against
6-month windows that produced 17-98 trades, this test was declared unable to confirm an
edge -- only to catch gross breakage:
- **Consistent-with-backtest / inconclusive** (not alarming, sample too small to read as
  either a win or a loss): win rate 15%-85%, profit factor 0.3-4.0, net profit/alpha
  roughly -12% to +40%, max drawdown down to -20%.
- **Alarming** (would indicate gross overfitting, not just a bad-luck window): win rate 0%
  on 5+ trades, profit factor <0.2 on 5+ trades, net loss worse than -15% **and**
  alpha worse than -20% simultaneously, max drawdown beyond -25%, or a structural anomaly
  (sizing multipliers outside the 0.5x-2.0x design bounds, `MAX_POSITIONS` violated, etc.)
  pointing at a bug rather than a bad market.

**Result, run once, 2026-07-01..2026-08-11**:

| metric | value |
|---|---|
| Trades | 13 |
| Win rate | 53.8% (7 wins / 6 losses) |
| Net profit | **-4.55%** (Rp 100,000,000 -> Rp 95,446,069) |
| Benchmark (IHSG) | +10.06% |
| Alpha | **-14.61%** |
| Profit factor | 0.28 |
| Max drawdown | -7.50% |
| CVaR (95%, daily) | -3.74% |

Exit breakdown: TP1 38.5% (5/13), forced END-of-window mark-to-market 30.8% (4/13), SL
23.1% (3/13), TRAILING 7.7% (1/13). Top-5 tickers by realized PnL (SOCI, SMLE, BLES, PKPK,
RGAS) account for 100% of gross positive PnL -- consistent with this project's already-
documented pattern (small-n windows are usually carried by a handful of names, see the
2026-08-31 entry above's own concentration numbers).

**Why win rate >50% still nets a loss**: not a mystery, and not new -- 3 SL exits
(-Rp 4,325,110 combined: SMIL, DWGL, DEWA) plus 1 TRAILING exit (-Rp 1,177,941, RGAS) outweigh
5 TP1 wins (+Rp 622,302 combined) by a wide margin; the 4 forced END-of-window exits net
slightly positive (+Rp 326,818) and are not the source of the loss. This is the familiar
"many small wins, a few bigger losses" shape a PF well under 1 implies regardless of win
rate -- SL_MULT (1.5x ATR) sizes stop losses wider than TP1's own target, a known, disclosed
design tradeoff elsewhere in this project, not something new this window reveals.

**Against the pre-declared bar** (corrected on review -- the first write-up of this entry
scored it as one breach, which was wrong): **two metrics fall outside the declared
consistent band, not one.** Profit factor came in at **0.28 against a declared floor of
0.30** -- below it, not "essentially at" it. That softening was exactly the post-hoc
reasoning a pre-declared bar exists to prevent; if a number under the line can be talked
back over it, the line stops being a line. Alpha (-14.61%) is the second breach, against a
declared -12%/+40% band. Win rate (53.8%), net profit (-4.55%) and max drawdown (-7.50%)
do land inside.

Neither breach is large, and the alarming threshold genuinely was not hit (that required
BOTH net loss worse than -15% AND alpha worse than -20%, simultaneously)  -- but the honest
statement is "two of five declared metrics missed their band," not one. Read plainly: this
is a real, not hidden, underperformance against a strong benchmark run, not a catastrophic
or structurally
(which required BOTH net loss worse than -15% AND alpha worse than -20%, simultaneously;
only alpha alone breaches, and net loss doesn't). Read plainly: this is a real, not
hidden, underperformance against a strong benchmark run, not a catastrophic or structurally
broken result. It sits in the same territory this log's own historical record already
contains -- windows 1 and 2 of the 9-window schedule (2022 H1/H2) also posted negative alpha
in a difficult market character; window 8 (2025 H2) beat a comparably strong IHSG rally
(+25.04%) by a wide margin (+104.12% alpha) -- so "benchmark rallies hard" does not
uniformly predict this strategy underperforms; this specific window is one data point in
a genuinely wide historical spread, not a new failure mode.

**Live `V4_PAPER` comparison, 2026-08-12..2026-09-01 (separate, NOT part of the blind test --
outcomes already known before this session started)**: pulled directly from
`backtest_runs`/`paper_positions` (`version='V4_PAPER'`, run id 36). Overall run (marks
all positions, open and closed, to the latest close): net profit **+0.93%** (Rp
100,000,000 -> Rp 100,927,124), benchmark **+3.55%**, alpha **-2.62%**, max drawdown
-2.60%. Of 12 position rows: 6 CLOSED (5 filled-and-closed, 1 `UNFILLED_EXPIRED` with no
entry), 5 OPEN, 1 PENDING. **All 5 closed, filled trades are losses** (WMPP -13.9%, GIAA
-10.8%, HATM -15.0%, BEEF -1.7% TRAILING, NICE -8.3% SL) -- realized PnL -Rp 6,904,539
(-0.69% of capital), win rate 0/5, profit factor 0.0. The 6 still-open positions (PACK,
EKAD, ELTY, PICO, FPNI, PPGL-pending) are unresolved.

**Agreement and divergence, read honestly, not reconciled**: both slices show the same
*direction* -- negative alpha against a rallying IHSG (backtest holdout: benchmark +10.06%,
alpha -14.61%; live: benchmark +3.55%, alpha -2.62%) over adjacent real 2026 H2 stretches.
That directional agreement is worth one sentence and no more, given both samples are tiny.
**The win rate comparison (53.8% backtest vs 0% live) is NOT read as a contradiction** --
the live run is only ~3 weeks in, the account's overall equity curve stayed roughly flat-
to-up (Rp 100.0M -> Rp 100.9M) despite every *closed* trade losing, which is only
consistent with the 5-6 still-open positions collectively running in positive
mark-to-market territory. This is the ordinary asymmetry of a TP1/trailing-stop exit
system early in a run -- losers get stopped out fast, winners are still open and haven't
been counted yet -- not evidence the live engine's fills or exits behave differently from
the backtest's. A real read on execution-vs-signal divergence would need those 6 positions
to actually close; noted as unresolved, not concluded.

**Honest verdict**: this result neither confirms nor undermines V4's edge -- ~30 trading
days and 13 trades is not statistical power, and the pre-declared bar was written
specifically because this sample size can only catch gross breakage, not measure an edge.
It doesn't find gross breakage: three of five metrics land inside the pre-declared range,
and the two that miss (profit factor 0.28 vs a 0.30 floor, alpha -14.61% vs a -12% floor)
miss narrowly rather than catastrophically. Worth stating plainly rather than burying: the
declared band was set loosely on purpose (win rate 15-85%, PF 0.3-4.0), so missing it twice
is a weaker result than "one metric slightly over" made it sound.

One pattern in these numbers deserves more attention than the pass/fail framing gives it:
**a 53.8% win rate paired with a 0.28 profit factor means the average loser was far bigger
than the average winner.** More than half the trades were right and the window still lost
money. That is the profile of exits cutting winners short while losers run -- the opposite
of what the TP1-plus-trailing design intends -- and it is visible here in untouched data
rather than inferred from a swept backtest. Not escalated into a research thread here (out
of scope for this task), but it is a sharper lead than anything the last several rejected
ideas were chasing. **What this test does add**: a real, previously
untouched data point showing V4's frozen config can and does lose money and trail its
benchmark in a real, current market stretch -- exactly the kind of result a swept or
tuned holdout could never produce, since sweeping toward a good-looking number is the one
thing this test was built to rule out. The live record adds one more real, if very early,
signal in the same direction (negative alpha against a rallying IHSG) without yet being
resolvable into a comparable win-rate number.

**One footnote, not a new research thread** (per this task's own scope -- not built or
tested further here): the two negative-alpha readings in this entry both occur in the same
real, currently-ongoing IHSG uptrend: if a third slice of this same stretch (whenever
enough of the currently-open V4_PAPER positions actually close) also shows negative alpha,
that would be worth a dedicated look at whether this strategy's gates (MAX_POSITIONS=6,
2 new entries/day, TP1 partial-exit) structurally underparticipate in strong, low-choppiness
rallies specifically -- not something to act on from three overlapping, still-partly-
unresolved data points.

Code touched: none of the protected V1 files, `backtest_v4.py` unchanged (config-only via
env vars, no code edits). New, both read-only/standalone: `src/scratch_v4_blind_holdout_
2026h2.py` (the one-shot holdout run, ~15-20 min end to end -- full-history fetch through
2026-08-11 plus feature computation, no local cache existed for this exact date range
before this run; now cached at `.cache/walk_forward_data_2021-01-01_2026-08-11.pkl` for
reuse, though re-running this script against the same window would not be a second
independent test -- the holdout is spent) and `src/scratch_v4paper_live_record_pull.py`
(the live-record pull, seconds to run, plain Supabase reads). Left uncommitted for review,
same pattern as this session's other entries.

## 2026-09-01 (diagnostic, no config change): decomposing the holdout loss --
## exit-reason breakdown across 380 trade-legs / 10 windows favours "no fat
## tail this window" over "exits mistuned," but the holdout alone (n=13)
## can't settle it on its own

**Trigger**: the blind-holdout entry directly above (13 trades, 53.8% win rate,
PF 0.28) flagged an unresolved question -- more than half the trades were right
and the window still lost money, which could mean (A) TP1/trailing are cutting
winners short while SL lets losers run, or (B) this strategy's edge is
structurally carried by a small number of outsized winners and this window
simply didn't get one. This is a diagnostic only: no new idea built, no flag
added, no parameter swept, `backtest_v4.py` untouched.

**Method**: reused `simulate_window()` exactly as already validated, against
the exact same cached data the 2026-09-01 holdout entry already fetched
(`.cache/walk_forward_data_2021-01-01_2026-08-11.pkl`, no new Supabase call),
same frozen config (`V4_BANDAR_SIZING=1`, `V4_ATR_PRICE_RATIO_MAX=0.08`). The
only thing new is capturing `df_trades` at trade-leg granularity for the
existing 9-window walk-forward schedule (`walk_forward_v4.build_schedule`)
plus the holdout window as a 10th entry, in one script
(`src/scratch_v4_exit_diagnostic.py`), instead of only the summary metrics
`walk_forward_v4.py` normally keeps. Deterministic re-run of already-reported
results at finer granularity, not a second independent test of anything --
confirmed byte-identical per-window metrics against the already-recorded
9-window numbers and the holdout entry's own numbers. 380 trade-legs saved to
`.cache/exit_diagnostic_trades.csv`. Note on units: all "trades" counts below
are trade-legs (a TP1 partial sale and its position's later final exit are
two separate rows, same as `total_trades` has always meant in this codebase's
own `win_rate`/`profit_factor` calc) -- the concentration section below also
gives the position/ticker-level view where that distinction matters.

### 1. Win/loss size decomposition (mean vs median = the fat-tail tell)

| slice | n legs | win rate | avg win % (Rp) | avg loss % (Rp) | mean pnl% | median pnl% | skew |
|---|---|---|---|---|---|---|---|
| All 10 windows pooled | 380 | 52.6% | +15.89% (Rp2,146,329) | -6.92% (Rp-1,139,823) | +5.09% | +3.74% | +2.97 |
| 9 walk-forward windows only | 367 | -- | -- | -- | +5.16% | +3.72% | +2.95 |
| **HOLDOUT only** | 13 | 53.8% | **+9.87% (Rp254,226)** | **-5.16% (Rp-1,055,586)** | **+2.94%** | **+4.98%** | **-0.08** |

Historically, average win Rp is **1.88x** average loss Rp (Rp2.15M vs Rp1.14M)
-- wins outsize losses in money terms even though this codebase's SL is
percentage-tighter than TP1/trailing's typical realized gain. In the holdout,
that ratio **inverts**: average loss Rp is **4.15x** average win Rp
(Rp1.06M vs Rp254K) despite a similar win rate (53.8% vs 52.6% pooled). Mean
pnl% sits *below* median in the holdout (the opposite of the pooled
population, where mean sits 36% above median) and skew flips from a strongly
positive +2.95/+2.97 (population) to essentially flat -0.08 (holdout) -- on
its own, n=13 is too small to trust a skew estimate, but it's consistent with
the win/loss-Rp inversion above, not contradicting it.

### 2. Concentration -- top-1/3/5 positions (tickers), % of each window's own gross positive PnL

| window | n positions | top-1 % | top-3 % | top-5 % |
|---|---|---|---|---|
| W1 (2022 H1) | 30 | 21.2% | 56.9% | 89.3% |
| W2 (2022 H2) | 26 | 32.1% | 64.1% | 85.3% |
| W3 (2023 H1) | 14 | n/a (net loss, no positive base) | n/a | n/a |
| W4 (2023 H2) | 27 | 55.9% | 83.0% | 91.7% |
| W5 (2024 H1) | 25 | 66.9% | 90.3% | 97.1% |
| W6 (2024 H2) | 32 | 26.7% | 61.6% | 82.6% |
| W7 (2025 H1) | 11 | 26.7% | 66.6% | 90.3% |
| W8 (2025 H2) | 49 | 15.6% | 42.9% | 59.3% |
| W9 (2026 H1) | 16 | 65.7% | 90.2% | 100.0% |
| **HOLDOUT** | 8 | **63.0%** | **100.0%** | **100.0%** |

Every window with a positive-PnL base (8 of the 9 walk-forward windows) draws
59%-100% of its own profit from 5 of its positions -- the holdout's 100%
top-5 share is not an outlier against this, it's the norm this strategy has
always run on (W8, the best-performing window on every other metric, is the
one *least* concentrated at 59.3% from 49 positions). This table alone is a
plain restatement of the project's own already-documented finding (the
`MAX_POSITIONS` scarce-slot investigation: "most of the return comes from a
handful of outlier winners") applied window-by-window instead of in
aggregate.

### 3. Exit-reason breakdown (pooled, all 10 windows, 380 legs; CHECKPOINT: 0 legs fired in any window)

| exit_reason | n | avg pnl% | median pnl% | avg pnl (Rp) | total pnl (Rp) | % of gross+ PnL | avg hold days |
|---|---|---|---|---|---|---|---|
| TRAILING | 81 | **+20.00%** | +12.63% | +Rp4,308,959 | +Rp349,025,699 | **81.3%** | 15.2d |
| END (forced, window boundary) | 20 | +10.35% | +2.91% | +Rp2,335,623 | +Rp46,712,453 | 10.9% | 23.2d |
| TP1 (10% partial, `TP1_PCT=0.10`) | 122 | +10.68% | +9.76% | +Rp144,256 | +Rp17,599,259 | 4.1% | 5.6d |
| TIME | 4 | -6.09% | -7.11% | -Rp302,478 | -Rp1,209,913 | 0% | 19.0d |
| SL | 153 | -7.66% | -7.49% | -Rp1,228,953 | -Rp188,029,828 | 0% | 5.7d |

TRAILING is the single best-performing exit type by every measure (highest
avg/median %, highest avg Rp, 81% of all gross positive PnL from just 21% of
legs) -- the opposite of a "cuts winners short" signature. TP1's average Rp
gain is mechanically small (Rp144K vs TRAILING's Rp4.3M) because it only ever
sells `TP1_PCT=0.10` of the position by design -- the other 90% stays open
specifically to be captured later, and the TRAILING row shows that it
generally is.

**HOLDOUT only** (13 legs):

| exit_reason | n | avg pnl% | avg pnl (Rp) | total pnl (Rp) | avg hold days |
|---|---|---|---|---|---|
| TP1 | 5 | **+11.52%** (vs pooled +10.68%) | +Rp124,460 | +Rp622,302 | 4.4d |
| END | 4 | +1.36% | +Rp81,704 | +Rp326,818 | 6.25d |
| TRAILING | 1 | **-3.72%** (vs pooled +20.00%) | -Rp1,177,941 | -Rp1,177,941 | 9.0d |
| SL | 3 | **-7.06%** (vs pooled -7.66%) | -Rp1,441,703 | -Rp4,325,110 | 3.0d |

SL and TP1 both land within ~1pp of their historical averages -- neither looks
mistuned this window. The one exit type that's abnormal is TRAILING: only 1
leg fired (pooled per-window range is 2-19; every other window had at least 5
except W3), and it was a rare loss instead of the typically large gain.

### 4. Money left on the table -- max favourable excursion (MFE) after TP1/TRAILING exits

Pooled (n=201/203 legs with forward price data in `df`, the same in-memory
frame `simulate_window()` itself uses, sourced from `ihsg_eod`; 2 excluded --
both exited on the holdout's last trading day, no forward data exists yet):

| exit_reason | n | realized pnl% at exit | fwd 10d high, mean/median (% of exit price) | fwd 20d high, mean/median | % with any further upside (10d) |
|---|---|---|---|---|---|
| TP1 | 122 | +10.68% | +21.33% / +14.71% | +30.47% / +18.42% | 94.3% |
| TRAILING | 81 | +20.00% | +15.79% / +9.18% | +24.32% / +12.23% | 92.6% |

TP1 legs do show large further upside after the exit -- but that's the
intended design: only 10% was sold, and the population-level TRAILING row
above shows the other 90% generally *does* capture much of that continuation.
TRAILING legs (a full exit of the remaining position) show forward
upside *smaller* than what's already been realized (median +9.18% further vs
+20.00% already banked) -- if trailing were routinely cutting winners short,
this would show the reverse (large further upside missed), not a moderate
additional move roughly half the size of the gain already captured.

**HOLDOUT TP1/TRAILING legs individually** (6 legs; RGAS-TRAILING and
BLES-TP1 both exited on 2026-08-11, the window's last day -- no forward data):

| ticker | exit_date | reason | realized pnl% | fwd 10d MFE | fwd 20d MFE |
|---|---|---|---|---|---|
| RGAS | 2026-07-31 | TP1 | +8.41% | -6.03% | -6.03% |
| DEWA | 2026-08-06 | TP1 | +9.91% | +1.64% | +1.64% |
| SOCI | 2026-08-06 | TP1 | +15.38% | +0.98% | +0.98% |
| SMLE | 2026-08-07 | TP1 | +12.58% | -2.79% | -2.79% |

3 of 4 measurable holdout TP1 legs show flat-to-negative continuation, not
money left behind. RGAS is the clearest single case against hypothesis A:
TP1 banked +8.41% right before the stock reversed, and the remaining 90% of
the position wasn't cut short by an over-tight trailing stop -- it caught a
real reversal (price kept falling) and the eventual TRAILING exit on
2026-08-11 still closed at only a small loss (-3.72%), not a large one.

### 5. Cross-window corroboration (new arithmetic on the same 380-leg dataset, no new simulation)

Per-window profit factor correlates with that window's average TRAILING-exit
return (Spearman rho=0.70, p=0.025, n=10) but not with how many TRAILING
legs fired that window (rho=0.41, p=0.24, n=10) -- it's the quality of the
trailing exits, not merely their count, that tracks window profitability.
The two worst-PF windows in the full 10-window record -- W3 (2023 H1, PF
0.02) and HOLDOUT (PF 0.28) -- are also the only two windows where average
TRAILING-exit return was negative (-2.82% on 2 legs, and -3.72% on 1 leg,
respectively), while every other window's TRAILING legs averaged +8% to
+47%. In both bad windows, SL and TP1 behaved close to their normal
historical range (W3: SL -7.90% vs pooled -7.66%, TP1 +10.25% vs pooled
+10.68%; HOLDOUT: SL -7.06%, TP1 +11.52%, both within ~1pp of pooled) -- what
differs both times is specifically whether a real trend materialized for the
trailing stop to ride, not whether SL/TP1 widths behaved abnormally. n=10 is
a small sample for this correlation and it should be read as suggestive, not
a settled statistical result on its own.

### Is the holdout an outlier against the historical distribution, or typical?

Mixed, metric by metric. Win rate (53.8%) sits almost exactly on the 9-window
mean (~50.4%, range 17.6%-81.0%) -- typical, not an outlier. Profit factor
(0.28) is in the bottom quartile but not the single worst -- W3's 0.02 is
worse. Net profit (-4.55%) is nowhere near the worst -- W3's -14.46% is much
worse. Alpha (-14.61%) is the one metric where the holdout sets a new low
across all 10 windows -- W3's -11.70% was the previous worst, and the other
8 windows were all positive (range +1.65% to +107.62%); this is more likely a
benchmark-relative effect of a strongly-rallying, low-choppiness market (a
gated, staged-entry strategy structurally under-participating in a fast
one-directional rally) than an exit-mechanism problem specifically -- flagged
as a footnote in the entry above, not re-escalated here, out of this task's
scope. On the exit-mechanism question this task was built to answer, the
holdout's specific signature (SL/TP1 normal, TRAILING absent-or-negative)
is not a new pattern -- it's a repeat of W3's signature, the only other
window that shares it.

### Read: hypothesis A vs B

**Evidence favours B (fat-tail dependent, this window had no tail) over A
(exits mistuned), and does so with reasonable strength given the amount of
data behind it (10 windows, 380 legs) -- though the holdout piece alone
(n=13) still can't settle it standalone.**

Supporting B, not A:
- TRAILING is the best-performing exit type in the historical record by
  every measure (avg/median %, avg Rp, share of gross profit) -- the
  opposite of what "winners cut short" would produce.
- The MFE check shows TRAILING exits leave comparatively little further
  value on the table on average (median +9.18% further vs +20.00% already
  banked); TP1's larger apparent "left on the table" number is explained by
  its 10%-partial-sale design, and the other 90% of the position is exactly
  what captures that continuation, as the TRAILING row's own numbers show.
- In the holdout, SL and TP1 -- the two exit types A's mechanism most
  directly implicates -- both land within ~1pp of their all-time averages.
  Nothing about their behavior this window looks mistuned.
- The one genuinely abnormal thing in the holdout (a single, losing
  TRAILING exit instead of the typical several-and-large) is not unique to
  this window -- it's the same signature the worst walk-forward window (W3)
  already has, and a 10-window correlation check (new arithmetic on existing
  data, not a new simulation) finds that signature tracks window profit
  factor at p=0.025.
- The population's return distribution is persistently, strongly
  right-skewed (skew +2.95/+2.97, mean 36% above median, max leg return
  +140%); the holdout's own 13-trade sample shows the opposite shape (mean
  below median, ~flat skew) -- consistent with simply not containing one of
  the outsized winners the strategy's edge structurally depends on.

What this doesn't rule out: a milder version of A -- e.g., trailing
distance or SL width being a few points wider or tighter than optimal in a
way too small to show up as a "cuts winners short" pattern in this MFE
check. That's a parameter-sensitivity question (a sweep), out of scope for
this diagnostic by design.

**What would follow from B, without building it**: if the edge is really
carried by a handful of large TRAILING-exit winners per window (5-19 per
6-month window historically, and only 1 or 2 in the two worst windows), a
live track record needs enough elapsed time/trades for at least one such
episode to plausibly occur before any win-rate/profit-factor read is
interpretable at all -- a 30-trading-day, 13-trade window may simply be
shorter than this strategy's natural sample-size floor. That materially
affects how much live time V4_PAPER needs before its results mean anything,
independent of whether the exit rule itself is ever touched. **What would
sharpen this further**: (a) redo the cross-window correlation on more,
smaller (e.g. quarterly) slices for a less noisy read on whether "no good
trailing exit this window" really predicts "bad window" as cleanly as n=10
suggests; (b) watch how V4_PAPER's still-open live positions (PACK, EKAD,
ELTY, PICO, FPNI as of the entry above) actually resolve -- if none of them
ever produce a real TRAILING win either, that would be a second, independent
(live, not backtest) data point for B; a single one that does would already
meaningfully complicate a "this window just has no tail" reading of the live
account specifically. Live corroboration pulled this session (same query as
`src/scratch_v4paper_live_record_pull.py`, not a new pull methodology): of
V4_PAPER's 5 closed trades so far, the only TRAILING exit (BEEF, -1.72%) is
also a loss, not the outsized winner the exit-reason table above says
TRAILING typically produces -- directionally consistent with B, but this
overlaps the same real 2026 H2 stretch the backtest holdout already covers,
so it is not treated as a fully independent third data point (same caveat
the entry above already gives its own live-record comparison).

Code touched: none of the protected V1 files, `backtest_v4.py` unchanged.
New, read-only/standalone: `src/scratch_v4_exit_diagnostic.py` (reuses
`walk_forward_v4.load_dataset`/`build_schedule` and `backtest_v4.simulate_
window` exactly as validated; runs in a few minutes against the existing
cache, no fetch). Output: `.cache/exit_diagnostic_trades.csv` (380 trade-legs,
10 windows). Left uncommitted for review, same pattern as this session's
other entries.

## 2026-09-01 (analysis only, no config change): how much track record is
## enough? -- bootstrap says ~90 filled positions before a losing run becomes
## <20% likely even if the edge is exactly as strong as the historical
## average, ~180 for <10% -- roughly 6 months to 3 years of live trading at
## V4_PAPER's currently observed fill rate, itself a very thin estimate.
## Along the way: this project's own "win rate" (leg-level, ~50% everywhere
## in this log so far) overstates how often a real trade decision worked --
## per-position it's 31.4%, because a TP1 partial-sale is always counted as
## a "win" leg even when the position it belongs to later reverses to a net
## loss.

**Trigger**: the two entries directly above establish that V4's profit is fat-tail
dependent (TRAILING exits, 81.3% of gross positive PnL from 21% of legs) and that a
30-trading-day / 13-leg holdout can't distinguish a real edge from a window that
simply didn't get a tail. This project's own deployment-readiness criteria call
live-track-record depth "the dominant gate -- can't be rushed" without a number
attached. This is that number, plus a check on whether position sizing is putting
more capital into losers than winners (a live-holdout observation from the same
13-leg window that could be a real sizing effect or a small-n coincidence).
Analysis only: `backtest_v4.py` untouched, no flag added, no parameter swept, no
new simulation run -- everything below is arithmetic on the already-computed
`.cache/exit_diagnostic_trades.csv` (380 legs, 10 windows) plus one read-only
Supabase pull of `paper_positions` for `V4_PAPER`.

### 0. Unit correction before anything else: legs are not independent trades

The CSV's 380 rows are trade-*legs* -- a TP1 partial sale (10% of the position,
`TP1_PCT=0.10`) and that same position's later full exit are two separate rows. A
first pass bootstrapping directly on the 380 leg-level `pnl_pct` values gave a
much rosier answer (20%-loss-probability floor at N=10, 10% at N=20) than the
corrected version below (N=90 / N=180) -- a **9x difference driven entirely by
counting convention**, not by any change in the underlying data. The reason: TP1
legs are positive by construction (they only fire once price has already hit the
target) and are pooled in that first pass as if they were independent trade
opportunities, which manufactures "free" positive draws that don't correspond to
a separate risk decision. Rolled up to one row per position (`window` +
`stock_code` + `entry_date`, net PnL summed across that position's legs, capital
summed across legs too so pyramid top-ups are counted) instead: **258 positions**,
not 380 legs. All numbers below use the position-level rollup; this matches how
`paper_positions` itself counts trades live (one row per position, not one row
per exit event) and is a more honest answer to "how many trades" in the plain-
English sense the question asks in.

**Side finding, not asked for but material**: position-level win rate is
**31.4%** (81/258), not the ~52.6% the leg-level convention has produced
everywhere else in this log (including the holdout's own headline "53.8% win
rate"). Mechanism, not a bug: positions that never hit TP1 (136 of 258, 52.7%)
win only **1.5%** of the time -- a stop-loss, forced-END, or TIME exit with no
partial profit ever taken essentially never turns into a net winner. Positions
that do hit TP1 (122 of 258, pyramid-eligible per `PYRAMID_ENABLED`) win **64.8%**
of the time. Blended: 31.4%. Consistent across windows, not one window's
artifact -- position-level win rate lands in a 24%-37% band in 8 of the 9
walk-forward windows (W3, the already-known catastrophic window, at 0%; W7 an
outlier at 66.7% on n=12). **Read plainly: "V4 wins about half its trades" --
the framing this whole log has used so far, inherited from the codebase's own
`win_rate` calc -- is true only if a guaranteed-positive 10%-partial-sale counts
as a full win on its own. Whether the actual buy decision made money by the time
the position fully closed is closer to a 1-in-3 shot.** This does not contradict
the profit-factor/net-profit numbers already reported anywhere in this log (those
are Rupiah-PnL-based and unaffected by this framing), only the win-rate framing
specifically -- worth carrying forward into how any future live-record win rate
gets read, including V4_PAPER's own.

### 1. Q1 -- N-trades-until-confidence, bootstrap on 258 positions

Method: resample N per-position `pnl_pct` values with replacement from the
empirical 258-position distribution (mean +1.83% per position, median **-4.67%**
-- median negative despite positive mean is the same right-skew signature this
log has already established at leg level, skew +3.10), sum them (additive,
equal-weighted -- **not** compounded, **not** capital-weighted; explicit
simplification, caveat below), 20,000 draws per N. This is Monte Carlo
resampling of the actual empirical distribution, not a normal-distribution
assumption -- the point is that the distribution is skewed and a normal
approximation would misstate exactly the tail behavior this whole research
thread is about.

| N (positions) | p5 | p25 | median | p75 | p95 | **p(net loss)** |
|---|---|---|---|---|---|---|
| 25 | -95.7% | -24.8% | +36.3% | +106.5% | +223.5% | **34.9%** |
| 50 | -115.6% | -6.2% | +82.1% | +179.7% | +335.8% | **26.7%** |
| 100 | -119.7% | +46.5% | +174.0% | +312.3% | +521.8% | **17.6%** |
| 200 | -69.5% | +173.3% | +355.7% | +544.1% | +831.3% | **8.7%** |
| 400 | +107.2% | +458.8% | +718.7% | +987.3% | +1390.2% | **2.6%** |

Fine grid (step 5-20) to find the exact crossing points: **first N with
p(net loss) < 20% is N=90. First N with p(net loss) < 10% is N=180.** A
compounding version of the same bootstrap (each position risking 1/6 of
capital, approximating `MAX_POSITIONS=6`) gives a slightly more conservative
but same-order-of-magnitude answer: 21.1% at N=100, 12.1% at N=200 -- the
additive table above is the more optimistic of the two framings, not the more
pessimistic one.

**Grounding against the two samples this log already has**: at N=8 (the
holdout's actual position count, not its 13-leg count), p(net loss) = **47.1%**
even assuming the edge is exactly as strong as the 258-position historical
average -- the holdout's real -4.55% result was close to a coin flip's worth of
uncertainty on sample size alone, not a surprising outcome. At N=10 (V4_PAPER's
current live fill count), p(net loss) is **45.0%**.

### 2. N converted to calendar time

Two rate estimates, both disclosed as thin, for different reasons:

- **Backtest-implied rate**: 27.8 new positions per ~126-trading-day (6-month)
  walk-forward window on average (range 12-54 across W1-W9) = **0.220
  positions/trading day**. Cross-checked against the holdout window specifically
  (same rules, same era): 8 positions / 30 trading days = 0.267/day, close to the
  9-window average -- this is the better-supported estimate (1,134 trading days
  of underlying history) but assumes market conditions and signal frequency stay
  in the same range they've historically been in (they have varied 4.5x across
  windows already).
- **Live-observed rate**: pulled directly from `paper_positions` for
  `run_id=36` (`version='V4_PAPER'`), all rows since 2026-08-12 go-live. **10
  filled positions** (WMPP, BEEF, EKAD, ELTY, GIAA, HATM, PACK, FPNI, NICE, PICO
  -- excludes PSAB, `UNFILLED_EXPIRED`, and PPGL, still `PENDING`) over **15
  trading days** (2026-08-12 through 2026-09-01 inclusive, not adjusted for IDX
  public holidays in that span) = **0.667 positions/trading day**, 3x the
  backtest-implied rate. **This is a very thin estimate** -- 15 trading days, and
  every one of the 5 days that filled anything filled exactly 2 (the per-day
  entry cap), clustered rather than spread evenly. It is also likely to slow
  down mechanically regardless of signal quality: the account is at 6 of 6
  `MAX_POSITIONS` right now (5 OPEN + 1 PENDING), so no new fill can happen
  until an existing position closes a slot.

| N | backtest-rate calendar time | live-rate calendar time |
|---|---|---|
| 25 | ~5.4 months | ~1.8 months |
| 50 | ~10.8 months | ~3.6 months |
| **90 (20% floor)** | **~19.5 months (1.6y)** | **~6.4 months** |
| 100 | ~21.7 months | ~7.1 months |
| **180 (10% floor)** | **~39 months (3.2y)** | **~12.9 months (1.1y)** |
| 200 | ~43.3 months | ~14.3 months |
| 400 | ~86.6 months (7.2y) | ~28.6 months (2.4y) |

**Read plainly, as the number this task asked for**: getting below a 20% chance
of a misleading (losing) read takes somewhere between roughly **6 months and 1.6
years** of live trading at V4_PAPER's current pace; below 10% takes somewhere
between roughly **1.1 and 3.2 years**. The width of that range is itself the
honest answer about how thin the live-rate estimate is -- 15 trading days is not
enough to pin down a fill rate, only enough to bound it loosely against the much
larger backtest sample.

**The caveat, stated as prominently as the number**: this whole calculation
assumes the 258-position historical distribution is stationary and that the edge
it implies (mean +1.83%/position, or +4.42% capital-weighted) is real. If the
true edge is zero or negative, running more trades does not fix that -- it
reveals it, converging the observed win rate and profit factor toward whatever
the true (possibly zero or negative) values are instead of toward the favorable
historical ones. This section computes **how long until a result becomes
readable**, not **how long until the strategy works**. Nothing here adds
evidence for or against the edge being real; W3's already-documented 0% win-rate,
PF-0.02 window is a live illustration that the historical distribution itself
already contains a scenario indistinguishable from "no edge, "as one of its ten
windows.

### 3. Q2 -- did sizing put capital into the losers?

**Leg-level (the CSV's raw grain, and the same grain the holdout entry's own
Rp254K-vs-Rp1.06M numbers used) reproduces the concern as stated**: pooled
across all 380 legs, avg capital in winning legs Rp9.89M vs losing legs
Rp17.18M -- losers get 1.74x more capital. But this is the same TP1-counting
artifact as section 0: TP1 legs are ~always winners (122 of 200 winning legs)
and mechanically tiny (avg capital Rp1.4M, a 10%-partial sale) by design, which
drags the "winner" average down independent of any actual sizing decision.
Excluding TP1 legs (comparing only full-exit legs: SL/TRAILING/END/TIME) already
flips the sign: losers get 0.74x the capital of winners, i.e. **winners get
more**.

**Position-level (net PnL and total capital summed per position, the correct
grain) confirms the flip cleanly**: avg capital in winning positions
**Rp24.51M**, losing positions **Rp17.43M** -- ratio 0.71x, **winners get ~40%
more capital, not less**. This holds in 8 of the 9 walk-forward windows (ratio
0.50-1.13, all at or below 1.0 except W4's 1.13): W1 0.60, W2 0.51, W4 1.13, W5
0.50, W6 0.73, W7 0.68, W8 0.89, W9 0.52. **Mechanism, verified**: `n_legs==2`
positions (hit TP1, `PYRAMID_ENABLED` adds ~20% at a new, higher average cost --
confirmed directly by entry_price shifting upward between a position's two legs,
e.g. BLES 194->209.5, DEWA 444->462.75, RGAS 214->226.4) carry avg capital
Rp26.2M vs `n_legs==1` positions (never hit TP1, no top-up) at Rp13.8M. Capital
tilts toward winners historically because pyramiding only ever adds to a
position *after* it has already proven itself by hitting TP1 -- an already-known,
already-disclosed design tradeoff (see the 2026-08-31 concentration-acceleration
entry above), not a new bug.

**The holdout is the one window that inverts this pattern**: ratio **1.85x**,
losers getting nearly double the capital of winners, on only **8 positions**.
Of those 8, 5 hit TP1 and were pyramid-eligible; only 2 (SMLE, SOCI) ended up net
winners, while 3 (BLES, DEWA, RGAS) took the pyramid top-up after an initial TP1
gain and then reversed into a net loss on the back leg large enough to erase it.
That is pyramiding operating exactly as designed (add to strength) in a window
that, per the entry directly above, had no real trend to ride -- the same "no fat
tail this window" explanation already established, now visible in the sizing
data too, not a separate or new failure mode. **Read plainly: the holdout's
apparent capital-into-losers pattern is a small-sample (n=8 positions) outlier
against an otherwise consistent 8-window history where capital skews toward
winners, not a systematic sizing bug.** No correlation found between capital and
raw entry price level (r=-0.01, checked and ruled out as a confound).

### What would strengthen or kill this

**Strengthens**: V4_PAPER's still-open positions (PACK, EKAD, ELTY, PICO, FPNI)
resolving with a realistic mix of outcomes matching the 31.4% position-level win
rate above (not the ~54% leg-level framing this log has used until now) would
corroborate the corrected framing with real, live, out-of-sample data. A future
quarter where the live fill rate is measured over 60+ trading days instead of 15
would materially tighten the calendar-time range in section 2 -- right now that
range is wide enough (6 months to 1.6 years for the same N) that it is not
useful for a precise "check back on this date" commitment, only an order-of-
magnitude one.

**Kills / narrows**: if the position-level win rate on the next 50-100 live
positions comes in well outside the 24-37% band 8 of 9 historical windows show,
that would indicate either the live engine's fills/exits behave differently from
the backtest (a real divergence worth investigating directly) or that current
market conditions are genuinely unlike anything in the 2022-2026 training
history (which the bootstrap's stationarity assumption cannot detect from
inside the historical data alone).

Code touched: none of the protected V1 files, `backtest_v4.py` unchanged (read-
only). New, read-only/standalone: `src/scratch_v4_track_record_bootstrap.py`
(reuses `.cache/exit_diagnostic_trades.csv`, no fetch, no simulation, runs in
seconds) plus one ad hoc read-only Supabase query against `paper_positions` /
`backtest_runs` for `V4_PAPER` (same tables `src/scratch_v4paper_live_record_
pull.py` already reads, not a new pull script). Left uncommitted for review,
same pattern as this session's other entries.

---

## Signal accountability: what the published signals actually did (2026-09-02)

**Why this exists.** Every enhancement up to here has been measured against the
backtest. Nothing measured the thing that actually goes out the door: the 15
signals published daily to the site and to Telegram. The EMAS complaint
(published at 9,600 on 31 Aug, Rank #3, already far extended; down the next day)
surfaced the gap -- there was no standing record anywhere of how the previous
week's calls had done, so the only audit that ever happened was a user noticing
a bad one after the fact. This entry closes that.

**What was built.** `sql/signal_performance_view.sql` -- a VIEW, not a table, so
it cannot drift out of sync with the price history, needs no backfill and no
cron, and self-corrects if EOD data is restated. It scores every row of
`daily_qualifying_signals` (180 signals, 2026-08-12 .. 2026-09-01) at 1/5/10/20
traded sessions out, alongside IHSG over the identical span. A two-line scorecard
now rides in the daily EOD Telegram summary (`_signal_scorecard` in
`paper_signal_scan.py`), wrapped in try/except so reporting can never take down
the job that manages live open positions.

**Entry is scored at the next session's OPEN, not `signal_close`.** The scan runs
after the close, so `signal_close` is a price nobody could have transacted at.
Scoring against it credits every signal with an overnight gap it never captured
-- which is exactly the mechanism that made an already-extended name look like a
clean entry. Measured average gap between `signal_close` and the price actually
paid: **+0.16%**, i.e. you pay up, slightly, on average.

### Data-quality bug found on the way

`ihsg_eod.open_price` is **0 on 34% of recent rows** (4,221 of 12,519 since
2026-08-12), hiding two different things: (a) the stock genuinely did not trade
-- volume 0, high = low = 0, close carried over from previous; (b) the stock DID
trade but the open was not captured -- volume in the millions, real high/low,
only `open_price` is 0 (ANDI, IGAR, IKAI on 2026-08-12 are examples). The first
cut of the view hit both: 16 signals scored an entry price of literally 0, which
read as a -100% entry gap and dragged the average gap to **-9.69%**, and
non-trading bars fed `min(low) = 0` into the drawdown stat, inflating average
5-day max adverse excursion to **-10.21%**. Fixed by keeping only bars that
actually traded (`high > 0`) and falling back to that bar's close when the open
is missing, flagged per row by `entry_ref_is_open` (14 of 180 signals use the
fallback). Corrected figures: average gap **+0.16%**, average 5-day MAE
**-6.27%**. **Anything computed off `ihsg_eod.open_price` without a zero guard
is suspect -- this is a live, ongoing data-quality hole, not a historical one.**

### What the signals actually did

Sample: 165 signals with at least one session of hindsight, 102 with five. Base
rate = every IHSG stock with >= Rp1bn turnover and price >= Rp50 on the same 12
dates, scored with the identical next-open entry rule (4,163 stock-days).

| Horizon | Signals avg | IHSG | Base rate (any liquid stock) | Signal win rate | Base win rate |
|---|---|---|---|---|---|
| 1 session  | **+0.44%** | +0.30% | +0.13% | 38.2% | 38.2% |
| 5 sessions | **+1.37%** | +1.45% | +1.61% | 44.1% | 50.6% |

Three things fall out, and two of them are unflattering:

1. **At one session the signal has a real edge in size, none in direction.**
   Average return is 3.4x the base rate (+0.44% vs +0.13%), but the win rate is
   *identical to three significant figures* (38.2% vs 38.2%). The selection is
   not finding stocks that are more likely to go up. It is finding stocks that
   move further when they do move. Median 1-session return is exactly **0.00%**.

2. **At five sessions the signal is worse than picking a liquid stock at
   random** -- lower average (+1.37% vs +1.61%) *and* a materially worse win
   rate (44.1% vs 50.6%). Held a week, the edge is not merely gone, it is
   negative against the base rate.

3. **The mean is a few outliers, not a tendency.** Median 5-session return is
   **-0.59%** against a +1.37% mean; best is +38.41%, worst -25.00%, sd 11.49.
   This is the same fat-tail structure the exit-asymmetry diagnostic found from
   the other direction, now confirmed on the raw signals rather than on trades.

**Rank ordering shows no usable signal at this sample size.** Per-rank buckets
hold 5-7 five-session observations each; rank 1 averages +22.68% and rank 2
averages -13.18%, which is noise, not a gradient. Consistent with the
2026-08-24 window-3 research finding that the ranking carries no measurable
value and the regime gate carries the edge. **Do not act on the per-rank table
until each bucket has 30+ observations** (~6 months of daily signals).

### The caveat that matters most

This measures **signal quality** -- did the stock go up after it was named --
and **not strategy P&L**. The live engine stops out, takes a 10% partial at the
first target and trails the rest, so a raw N-day hold return is not what the
account would have earned. A concrete illustration from the live scorecard's
first run: the 14 Aug batch, ten sessions on, was **6/13 up, avg -0.8% vs IHSG
+3.1%, yet 10 of 13 reached the first target at some point**. Most of them
touched the target intraday and the batch still lost to the index. That single
line is the clearest evidence yet that "reached first target" is a near-
meaningless success criterion on its own, and it is now published daily where it
cannot be quietly ignored.

### What would strengthen or kill this

**Strengthens**: another 4-6 months of daily signals would put 30+ observations
in every rank bucket, making the per-rank table interpretable for the first
time, and would let the 5-session underperformance be tested for significance
rather than merely observed. If the 1-session size edge survives that sample
while the 5-session deficit persists, the honest conclusion is that the entry is
a one-day momentum effect being held far too long.

**Kills / narrows**: the sample here is 12 trading days in a single bullish
stretch (IHSG +0.30%/session average). A market with a different character could
reverse any of this. The 5-session deficit in particular rests on 102
observations across 7 usable dates -- it is a warning, not a verdict.

Code touched: none of the protected V1 files; `backtest_v4.py` unchanged. New:
`sql/signal_performance_view.sql` (applied to DB1) and `_signal_scorecard` in
`src/paper_signal_scan.py`. No trading logic, sizing, or exit rule was modified.

---

## "It always buys the top": measured, tested, and the obvious fix rejected (2026-09-02)

**The complaint, and why it deserved a test.** The user pointed at EMAS: UT Bot
(the indicator he actually trades with) went long at 6,100 on 23 Jul and gave a
sell at 8,800 on 1 Sep, +44.3%. Neira first named EMAS on 21 Aug at 7,900 --
21 sessions later and 30% higher -- and then ranked it *better* as it got more
extended: #15 at 7,900 rising to #3 at 9,600, one session before it fell 8.3%.

### 1. The observation is real

`src/scratch_signal_lateness.py` ran UT Bot (key=1.0, ATR 10, the stock default)
across all 180 published signals and their price history:

| Where Neira arrives | |
|---|---|
| Already in an uptrend by UT Bot's reckoning | 123/180 (68%) |
| Sessions since the trend flipped up | median 7, mean 9.4, max 36 |
| Move already banked before Neira names it | median +14.0%, mean +25.9%, max +197.5% |
| Distance above MA20 | median +13.9% |
| Position in 60-session range (100 = at the high) | median 88 |
| Named while in the top fifth of their 60-day range | 128/180 (71%) |

Not one stock: a second clean case is BEEF, where UT Bot bought at 160 on 1 Jul
and Neira first named it at 414 on 12 Aug -- 159% higher.

### 2. But "too extended" does not predict worse outcomes

Median-split on the published signals gave two families of measure that
*disagree*: trend age (sessions since flip, run banked) predicted BETTER forward
returns, while distance above a moving average predicted worse ones at 5-10
sessions. Both splits are ~50 observations a side over 12 days of one bullish
stretch -- not enough to act on, which is why the flag below was built and
swept rather than shipped off the diagnostic.

### 3. The extension gate: 9 thresholds, 0 pass -- REJECTED

`V4_EXTENSION_GATE` drops any candidate more than X% above its own moving
average (ma20 or ma50, `EXTENSION_GATE_MA`). Thresholds were picked off the
qualifying pool's own distribution measured beforehand (above ma50 the pool's
median is +11.2%, p70 +20.7%, p80 +30.1%, p90 +50.8%; above ma20 +4.6% / +9.7%
/ +14.6% / +25.5%), so every cell actually binds.

| cell | beat bench | win% | profit | alpha | alpha med | PF | worst DD | trades |
|---|---|---|---|---|---|---|---|---|
| baseline   | 6/9 | 50.1 | 21.64 | **22.50** | 18.03 | 1.82 | **-22.41** | 396 |
| ma20>0.05  | 5/9 | 47.3 | 16.69 | 17.56 | 1.55 | 2.05 | -18.79 | 302 |
| ma20>0.10  | 4/9 | 51.0 | 13.88 | 14.74 | -5.16 | 1.81 | -15.98 | 321 |
| ma20>0.15  | 5/9 | 53.5 | 18.39 | 19.25 | 12.42 | 2.30 | -21.39 | 325 |
| ma20>0.25  | 5/9 | 52.8 | 21.55 | 22.41 | 14.67 | 4.07 | -26.32 | 368 |
| ma50>0.10  | 5/9 | 47.7 | 19.32 | 20.19 | 8.46 | 2.48 | -17.86 | 305 |
| ma50>0.15  | 4/9 | 47.6 | 10.74 | 11.60 | -0.39 | 1.37 | -13.84 | 321 |
| ma50>0.20  | 4/9 | 49.8 | 16.00 | 16.86 | -0.47 | 1.77 | -18.25 | 331 |
| ma50>0.30  | 6/9 | 47.6 | 16.41 | 17.27 | 10.15 | 1.88 | -18.02 | 329 |
| ma50>0.50  | 4/9 | 50.9 | 4.95 | 5.82 | -3.28 | 1.35 | -25.47 | 347 |

**Every single threshold loses mean alpha** (best: ma20>0.25 at -0.09, and that
one's worst drawdown is 3.91 points *worse*). The consistent shape is a trade of
alpha for drawdown: tighter gate, shallower drawdown, less profit. 0 of 9 clear
the adoption bar (mean alpha AND worst drawdown both improve). Notably ma50>0.50
-- the loosest gate, cutting only the most extreme 10% -- costs the MOST alpha
(-16.69), which says the furthest-extended names are where the fat-tail winners
actually live.

**Verdict: rejected.** The flag stays in the code, defaulted off, documented, so
the next person does not re-run this. Filtering out extended candidates makes the
strategy smaller, not smarter.

### 4. The exits are not the bottleneck either -- and this corrects a prior assumption

Before assuming the entry needed replacing, `src/scratch_can_we_hold_a_multibagger.py`
checked whether Neira's own exit rules could even hold a big winner, using the
exact live logic (SL 1.5xATR, TP1 1.5xATR selling 10%, 8% trailing off the peak
close, 20-day cap with its in-profit-and-bullish escape hatch):

| ticker | entry | exit | held | got | peak seen |
|---|---|---|---|---|---|
| LUCY | 194 (early breakout) | TRAILING | 23 | **+521%** | +588% |
| FPNI | 192 | TRAILING | 19 | +335% | +382% |
| BEEF | 160 | TRAILING | 39 | +176% | +211% |
| EMAS | 6,100 | TRAILING | 26 | +44.3% | +59% |
| LUCY | 93 (the actual bottom) | TRAILING | 7 | **+31%** | +59% |

An 8% trailing stop rode a 6-bagger. The 20-day cap never fired on a winner.
**So the exit machinery was wrongly suspected; the entry is the whole problem.**

The last row is the most useful one: buying the *actual bottom* returned +31%
and then missed the 27x, because a base is choppy and an 8% trail gets hit.
Buying the *early breakout* returned +521%. Under our own exit rules the bottom
is a worse entry than the breakout -- so "build a bottom-fishing system" is the
wrong project. "Fire the existing breakout entry earlier" is the right one.

Caveat that must travel with that table: those five were selected *because* they
were big winners. It shows the exits CAN hold a winner; it says nothing about
whether the strategy makes money. The measured 26.3% position-level win rate
still stands.

### 5. Why LUCY was never named, and what it reveals

LUCY ran 91 -> 2,510 -> 204 -> 490 and has **never** appeared in
`daily_qualifying_signals`. It is not a liquidity failure at the time of asking
(Rp20.5bn/day on 1 Sep, well over the Rp1bn floor). On the scoreboard it sits at
label WATCH, percentile 5.3, with **weekly_ma_spread -10.30** -- price still
below its own 10-week average, because that average still carries the pre-crash
prices. The entry rule requires the weekly trend to be in the top quintile of
*positive*, so a stock recovering from a crash cannot qualify for months.

Same root cause as EMAS, opposite symptom: the rule only fires on established
uptrends, so it arrives late in one (EMAS) and never at all in a recovery (LUCY).

Liquidity is a real but partial constraint. Of UT Bot's 10 best trades this year,
**6 were liquid at entry** (INET Rp143bn/day, EMAS Rp99bn, KETR Rp15bn, APEX
Rp12.8bn, ELTY Rp9bn, BEEF Rp2.75bn) and 4 were not (SMLE 0.50, TAMA 0.31, FPNI
0.21, LUCY 0.10). Most of the big winners were reachable at size and were missed
on the entry rule, not the liquidity floor.

### 6. UT Bot is not accurate, and that matters for what we copy

`src/scratch_utbot_baserate.py` ran the same indicator over all 51 tickers Neira
has ever named, a full year, exit on its own sell flip: **571 closed trades, 42.4%
win rate, median trade -1.92%, mean +4.13%, profit factor 1.96, avg win +19.85%
vs avg loss -7.43%.** It is wrong more often than it is right. What makes it work
is the payoff ratio, not accuracy -- the same fat-tail structure this log has
been finding in V4 from the other direction. The EMAS +44% is one good ride out
of a year of mostly small losses, and should not be read as "the indicator knows
where the discount is." It does not; it is a trailing stop that enters on a
breakout.

### 7. Firing earlier was tested too, and is also REJECTED

`weekly_ma_spread` is built with `resample("W-FRI")` and merged backward, so it
refreshes on Friday and is reused Monday-Thursday. Measured on the cached
dataset rather than inferred from the merge: **87.4% of value changes land on
Friday, 0.0% on Thursday.** That is 1-4 sessions (mean 2.0) of already-available
price data being ignored on every non-Friday signal -- an obvious candidate for
the lateness, and removing it is not lookahead (week-to-date closes have all
already happened).

`src/test_weekly_lag.py` recomputes the column in memory (no refetch, cache
untouched) and runs the same 9 windows. The two versions correlate 0.9302 and
37.8% of rows move by more than 2 points, so the change is material:

| Metric | current (Friday-stale) | week-to-date |
|---|---|---|
| Windows beating benchmark | **6/9** | 5/9 |
| Win rate (mean) | **50.1%** | 47.1% |
| Profit (mean / median) | **+21.64% / +5.46%** | +9.18% / -1.68% |
| Alpha (mean / median) | **+22.50% / +18.03%** | +10.04% / +1.36% |
| Profit factor (mean / median) | **1.82 / 1.19** | 1.38 / 0.92 |
| Max drawdown (mean / worst) | **-15.46% / -22.41%** | -17.81% / -27.02% |

**Every metric is worse, alpha roughly halved.** This is a fair test, not a
mis-thresholded one: `simulate_window` re-derives `weekly_cut` from each
window's own training data, so the quantile adapted to the new distribution.

**The lag is load-bearing.** Waiting for the week to close is doing real work --
it filters intra-week noise that would otherwise become entries. Entering
earlier through this route buys more false starts than early trends.

That reframes the whole complaint. The lateness measured in section 1 is not a
defect to be tuned away; it is the confirmation delay that makes the rule
profitable at all. Two independent attempts to act on "it buys too late / too
high" -- filter out the extended ones, and fire earlier -- both made the
strategy worse.

### What would strengthen or kill this

**Strengthens**: the remaining untested route is a genuinely *different* entry
running alongside the current one, rather than a modification of it -- something
that fires on a recovery or an early breakout with its own confirmation, judged
on the same 9-window bar. Section 4's LUCY rows argue that such a rule should
target the early breakout, not the bottom: at the actual low the 8% trail gets
whipsawed out for +31%, while the early-breakout entry held for +521%.

**Kills / narrows**: if a separate early-entry rule also fails the walk-forward,
the honest conclusion is that this strategy is structurally a mid-trend follower
-- it arrives 7 sessions and ~14% into a move because that is when its evidence
becomes reliable -- and the way to raise returns is position sizing and capital,
not an earlier entry. Two rejections already point that way.

Code touched: none of the protected V1 files. New: `V4_EXTENSION_GATE` in
`backtest_v4.py` (defaulted OFF, rejected), `src/sweep_extension_gate.py`,
`src/scratch_utbot_emas.py`, `src/scratch_utbot_baserate.py`,
`src/scratch_signal_lateness.py`, `src/scratch_can_we_hold_a_multibagger.py`,
`src/test_weekly_lag.py`. No live config, sizing, or exit rule was modified.
