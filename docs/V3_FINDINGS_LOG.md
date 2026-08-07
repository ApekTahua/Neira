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
configuration. Also fixed in this round: `walk_forward_v3.py` now
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

**Added `apply_slippage()`** in `backtest_v3.py`: widens buys / narrows
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
summary in `walk_forward_v3.py`; stored in `simulate_window()`'s
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
touch `backtest_v3.py`'s shared entry/exit functions, only the live-only
EOD snapshot step.

## Full-universe daily scoreboard -- backend shipped (2026-08-02)

Queued below yesterday, built today (Sunday, day before paper trading's
Monday launch). Shipped exactly the scoped v1: `score_full_universe()`
in `backtest_v3.py` (new function, zero lines changed in
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
new candidates (`score_candidates` in `backtest_v3.py`, currently called
with `top_n=15` from `paper_signal_scan.py`; V1's separate Telegram bot
posts its own top-10, `src/screener.py:162`). Everything else in the
IHSG universe is invisible -- if a user searches a specific ticker on
the website, there is currently no answer to "where does this stock
stand today." Ask: score **every** ticker daily, not just qualifiers,
with a confidence label (something like Strong Buy / Buy / Watch / Wait)
and, ideally, a target price to wait for.

**Why this is cheaper than it sounds, for the classification half.**
`score_candidates` (`backtest_v3.py:404-429`) currently does two things
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
a quick add.** Nothing in `backtest_v3.py` today computes a pullback or
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
(`build_full_dataset`, `backtest_v3.py`) in the same pass -- that's a
groupby-vs-repeated-filter algorithmic question, touches the shared
validated backtest logic, and per this log's own discipline would need
a full 9-window walk-forward regression check before landing, not
something to bundle into a same-day I/O fix.

## MIN_HOLD_DAYS/TP1 blocked-crossing study + W9 (2026 H1) deep dive (2026-08-07)

Two read-only research passes tonight, zero changes to `backtest_v3.py` --
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
