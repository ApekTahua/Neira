# Post-hibernation study tickets

Written 2026-09-12, the last working session before the system is left to run
unattended. Nothing in this file has been executed. Every item here is a
**study**, not a patch: it needs pre-registration in `EXPERIMENT_REGISTER.md`
and a 3-partition walk-forward before it may touch a live config, per
`HOLDOUT_PROTOCOL.md`.

The reason is in that protocol and worth repeating, because it is the trap this
project keeps walking into: at least 262 configurations have been graded against
the same 2022-2026 nine-window walk-forward. Under a zero-edge null, the best of
262 draws would be expected to return roughly **+52.71%** mean alpha -- more than
the **+26.27%** actually reported by the winner. Those windows can rule an idea
OUT. They cannot let one IN. Only forward paper-trading data promotes a change.

---

## Background: what V4_PAPER's entry actually does

Established by reading the code and the live workflow, not from memory.

**Live config** (`.github/workflows/paper_signal_scan_v4_trigger.yml:65-72`):
`PAPER_VERSION=V4_PAPER`, `V4_BANDAR_SIZING=1`, `V4_ATR_PRICE_RATIO_MAX=0.08`.
Everything else runs on the defaults in `src/backtest_v4.py`.

**Day-level gate, before any stock is looked at** (`backtest_v4.py:650`,
`:668`, `:2118-2143`): IHSG must read BULLISH, for `REGIME_CONFIRM_DAYS=3`
consecutive days, with `trend_strength >= TREND_STRENGTH_MIN=0.01` (IHSG at
least 1% above its own 50-day average). If that fails, the day produces no
entries at all, regardless of how any individual stock looks.

**Per-stock filter** (`backtest_v4.py:2032-2040`), all five must pass:

| Filter | Threshold | What it is |
|---|---|---|
| `adtv_20 >= cfg.ADTV_MIN` | Rp 1,000,000,000 | 20-day average **turnover** -- can I get out |
| `weekly_ma_spread >= weekly_cut` | learned per window | price vs its own 10-week moving average |
| `sector_rs_momentum >= sector_cut` | learned per window | its sector vs the whole market, 20 sessions |
| `atr_14` present and `> 0` | — | a stop can be computed at all |
| `atr_14 / close_price <= 0.08` | live override | not too wild to set a stop on |

**Score, which sets the rank** (`backtest_v4.py:2065-2071`), two terms:

```
score = (weekly_ma_spread - weekly_cut) / |weekly_cut|
      + (sector_rs_momentum - sector_cut) / |sector_cut|
```

**Off by default, and off live** -- confirmed from the defaults, since the live
workflow sets none of them: `EXTENSION_GATE_ENABLED` (`:1305`),
`ARA_FILTER_ENABLED` (`:1354`), `PRICE_RANGE_PENALTY=0` (`:1247`),
`PARTICIPATION_GATE_ENABLED` (`:727`), `SPIKE_CONFIRM_GATE_ENABLED` (`:812`),
`TREND_DURATION_GATE_ENABLED` (`:685`).

**Where Bandarmology enters**: `BANDAR_SIZING_ENABLED` (`:1022`, live `=1`)
scales **position size** through `bandar_mult`. It does not filter candidates
and it does not affect rank. There is no broker term anywhere in the score.

---

## The owner's four words, checked against the code

He asked for an algorithm explainable as *"look at the MA, check IHSG first,
volume, netflow."* Three of the four are real. One is not.

| His word | In the engine? | Where |
|---|---|---|
| **check IHSG first** | ✅ Yes, and it is the first thing checked | day-level regime gate, `:2143` |
| **look at the MA** | ✅ Yes, twice over | `weekly_ma_spread` (10-week MA) is both a filter and half the score |
| **volume** | ⚠️ **Not as he means it** | see below |
| **netflow** | ⚠️ **Size only, never selection** | `BANDAR_SIZING_ENABLED`, `:1022` |

### "Volume" is the real gap

`adtv_20` is average **turnover** in Rupiah, used as a floor -- it answers
*"can I sell this without moving it"*, not *"is something happening today"*.
`avg_vol_20` appears in the filter only as a `notna()` check. **V4 has no
volume-spike signal in the live path.** `SPIKE_CONFIRM_GATE_ENABLED` exists and
is off.

This is not an oversight to quietly fix. V1's entry signal **was** a volume
spike, and it was measured to have no edge on liquid stocks -- which is why V1
stopped publishing (`CLAUDE.md`, 2026-09-08, after 52 runs). Putting volume back
in has to clear the same bar as anything else, not ride in on intuition.

### So: UI problem or algorithm problem?

**Both, and they are separable.**

- **UI problem, now fixed**: the regime gate and the liquidity floor were doing
  real work that the pages never said out loud. The gate checklist on the stock
  page now reads *"The whole market is rising"* instead of *"Market regime
  confirmed"*, and the liquidity pill says how many times over the minimum a
  stock trades rather than naming `ADTV_MIN`.
- **Algorithm problem, deliberately left alone**: the score has two terms, one
  of which (`sector_rs_momentum`) carries **no per-stock information at all** --
  it is one identical value for every stock in a sector. So the ranking is
  driven almost entirely by a single number: how far a stock sits above its own
  10-week average. Broker money, volume, and how extended the stock already is
  are all absent from it. That is a real design question, and it is the subject
  of tickets S-1 and S-2 below.

---

## Why the same names repeat

**Mechanism, from the code.** Nothing in `score_candidates` knows a stock was
listed yesterday. Each day is scored from scratch. A stock that is 40% above its
own 10-week average in a rising sector will be 40% above it tomorrow too -- the
inputs barely move day to day, so the output barely moves. The list is *supposed*
to persist while the trend does. Re-appearing is the system being consistent, not
the system repeating itself by accident.

**Measured** (`daily_qualifying_signals`, 2026-08-12..2026-09-11, 300 rows over
22 trading days, 65 distinct stocks):

| Stock | days listed (of 22) |
|---|---|
| SOCI | 20 |
| APEX | 14 |
| CUAN | 11 |
| TOBA | 11 |
| SGER | 11 |

**Forward 5-day return by how many times the stock had already been listed:**

| Times listed before | n | mean 5d | median 5d | % positive |
|---|---|---|---|---|
| 1st time | 59 | +3.85% | +2.74% | 62.7% |
| 2nd-3rd | 75 | +1.37% | 0.00% | 46.7% |
| 4th-7th | 69 | −1.44% | −1.90% | 33.3% |
| 8th+ | 22 | +2.66% | +1.37% | 68.2% |

**This table must not be acted on.** It looks like decay, and the 8th+ row
breaks the pattern, which is the tell. Three reasons it is not evidence:

1. **One month.** 22 trading days, a single market regime.
2. **Not independent.** 225 observations come from 65 stocks; SOCI alone
   contributes 20 of them, and its overlapping 5-day windows share most of
   their price action. The effective sample is far smaller than n suggests.
3. **Non-monotone.** If repetition genuinely decayed, the 8th+ bucket would be
   the worst. It is the best. That is what noise looks like.

It is enough to justify **telling the reader** which listings are new and which
have been there for weeks -- done, see below -- and nowhere near enough to
justify a rule.

**Shipped instead (UI only, no engine change):**

- `🆕 New to this list` badge, the counterpart to the existing `Repeat Pick`
  badge. Its tooltip says explicitly that it is not a claim that new beats
  repeat.
- `📋 Listed Nd · never bought` was already there and stays -- a stock listed
  ten times and never bought is the page telling on itself.
- Broker tiers renamed so a reader can tell absence from opposition (see
  `HIBERNATION_STATE.md`), and the "No Broker Signal" tooltip now names the
  actual risk: *"this pick rests on the price trend alone, so if that trend
  breaks there is nothing else holding it up."*

---

## S-1 -- Should broker tier affect rank, not just size?

**Status:** NOT STARTED. Pre-registration required.

**The observation that prompted it.** TEBE ranked top-4 while tagged as brokers
*selling*, and SGER sat on the list for 11 of 22 days with no broker signal
either way. Rank is `weekly + sector` and nothing else, so both are working as
designed -- the badge and the ordering genuinely have nothing to do with each
other.

**Why it is not obvious that it should change.** Bandarmology already feeds
position size, and `BANDAR_SIZING` was promoted on a full nine-window
walk-forward. Feeding the same signal into rank as well is not a free addition:
it double-counts one input, and the nine windows are closed for promotion, so
there is no cheap way to test it.

**Design before touching anything.** Three arms, pre-registered:

- **A** (control): rank unchanged.
- **B**: `score − λ · 1[tier = contradicted]`, a demotion only -- never a
  promotion, so a broker-confirmed name cannot jump a better-scoring one.
- **C**: `score + λ · signed_flow_z`, symmetric.

Grade on **tail probability** (P(+25% over 20 sessions)), never hit rate. The
edge in this system is in the right tail, not in direction: the median pick is
indistinguishable from random, while the odds of a +25% run are roughly doubled
(16.4% vs 7.5%). Eleven earlier selection experiments were graded on hit rate,
the one axis where this filter is average, and all eleven misled.

**Data constraint:** broker data starts 2023. Any partition before that has no
signal, so arm B and C collapse to arm A there -- the walk-forward has to be
built on 2023+ only, which is a smaller sample than the standard nine windows.
Say so in the pre-registration rather than discovering it in the results.

---

## S-2 -- What happens to a trend-only pick when the trend breaks?

**Status:** NOT STARTED.

The question behind the owner's TEBE concern. A `No Broker Signal` pick rests on
one number: distance above its own 10-week average. If that reverts, nothing
else is holding it up.

**What already catches it, and what does not.** Nothing in the *entry* path
looks at trend fragility. The exits do: `TRAIL_ATR` follows the price up, and
`SL` is fixed at entry. `EXTENSION_GATE_ENABLED` -- which would reject a stock
already stretched too far above its 50-day average, the most direct version of
this concern -- exists at `backtest_v4.py:1305` and is **off**.

**Study:** split closed positions by tier at entry (`confirmed` / `only` /
`contradicted`) and compare stop-hit rate, time to stop, and tail rate. If
`only` stops out materially faster, the fix is an exit-side rule (tier-dependent
stop width), not an entry filter -- and note that a side-finding already points
the other way on a neighbouring signal: on 250 real historical trades, win rate
by broker-concentration tercile was 19.1% / 29.0% / 42.9%, implying high
concentration deserves a **wider** stop, not a tighter one (`backtest_v4.py`
comment at `:1121`).

**Do not run this until V4_PAPER has 60 closed positions.** With fewer, the
per-tier cells are single digits.

---

## S-3 -- T-18: is `SCORE_NORM="train_sd"` real?

**Status:** NOT STARTED, and deliberately NOT a patch.

Carried over unchanged. Needs pre-registration plus a 3-partition walk-forward.
It was raised as a one-line change; it is not one, because the nine windows it
would be graded on are the same nine windows 262 configurations have already
been fitted to.

---

## S-4 -- T-7 phase 2: rights issues

**Status:** NOT STARTED. Phase 1 (splits and reverse splits) is done and live.

31 price discontinuities remain unexplained after splits are removed. They are
rights issues, and **they cannot be inferred from price**: the theoretical
ex-rights price depends on the subscription price, so the implied ratio lands
anywhere (1.57-1.90 observed) instead of snapping to a clean 2 / 5 / 10 / 25 the
way a split does.

The ratios have to be read from the filings. `%right issue%` and `%hmetd%` were
always on the prune whitelist, so the announcements survive in
`disclosures_flat` -- but 43% of recent filings arrive as a PDF whose text
cannot be extracted at all, so expect to read some by hand.

---

## S-5 -- T-7 phase 2b: use the split factors in multi-year returns

**Status:** NOT STARTED. The factor table is built, tested and live; nothing
consumes it yet.

`stock_split_factor` (147 rows, 72 stocks) is not joined by the backtest. Until
it is, any return computed across a split date is still wrong. Measured scale of
the error: on 20-day windows over affected stocks, **2,432** moves exceeded 70%
on raw prices versus **1,537** on adjusted -- **895 (37%) were split artifacts,
not price moves.**

Do this before anything that reads long-horizon returns, including S-1's
walk-forward.
