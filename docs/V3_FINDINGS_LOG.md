# V3 Findings Log

Read this first if you're picking up this project cold. It's the log of
what's been tried, what worked, what didn't, and the bugs that made early
numbers look better than they were. Full plan/spec context:
`docs/superpowers/plans/2026-07-15-v2-hmm-screener.md` and
`docs/superpowers/specs/2026-07-15-v2-hmm-screener-design.md` (that's the
V2 HMM-gate plan — superseded, see below).

**UPDATE, most important finding in this file**: everything below the
TL;DR was written from 3 hand-picked windows. A real 9-window rolling
walk-forward (`walk_forward_v3.py`, see "Walk-forward validation" section
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
| Adaptive hold-time (`expected_hold_days = |TP-entry|/ATR`, checkpoint exit) | `phase0f_holdtime_exit_backtest.py`, integrated into `backtest_v3.py` (`V3_ADAPTIVE_HOLDTIME`) | **Integrated, verified correct, and essentially inert for this entry rule's population.** First integration attempt had a real bug (computed against `tp1_price`, which by definition made `expected_hold_days` collapse to the fixed constant `TP1_MULT=1.5` — never variable, never able to reach the 5-day gate; caught via a suspiciously-exact match to the no-hold-time baseline, not accepted at face value). Fixed to use `tp_target` (SMC swing-high). Diagnostic trace then showed only 1 of 118 entries in window 2 ever reaches `HOLDTIME_MIN_DAYS=5` (median ~1-2 days, matching phase0f's original population almost exactly) — the mechanism fires correctly when it should, there's just almost nothing for it to act on in this specific rule's trade population. Left off by default; not worth pursuing further here. |

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
`backtest_v3.py`: caps how many of the *currently open* positions may
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

Refactored `backtest_v3.py` (`simulate_window()` extracted from `main()`,
behavior-preserving — verified by rerunning window 3 post-refactor,
exact match to -5.44%/41.7%/PF0.29/DD-6.22%/12 trades) and built
`walk_forward_v3.py`: fetches the full history ONCE, then runs 9 rolling
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
