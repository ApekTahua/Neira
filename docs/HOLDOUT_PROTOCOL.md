# Holdout protocol

Written 2026-09-02, deliberately **before** the score-normalisation re-baseline
finished running. A holdout declared after seeing a result is not a holdout; it
is a search for a window that agrees with you. This document is the commitment,
made while the answer was still unknown.

## Why this exists

A council review on 2026-09-02 flagged that the original V4 validation and all
ten subsequently-rejected ideas were measured against the **same fixed
2022-01-01..2026-06-30 nine-window dataset**. Every additional pass over
recycled data is worth less than the last, and by test eleven the number that
comes back is partly a measure of how many times the data has been asked.

## What is already spent, and cannot be reused

| Window | Spent on | Date |
|---|---|---|
| 2022-01-01 .. 2026-06-30 | The 9-window walk-forward: original validation plus 11 graded experiments | ongoing |
| 2026-07-01 .. 2026-08-11 | The first genuine blind holdout, run once on V4_PAPER's frozen config | 2026-09-01 |
| 2026-08-12 .. 2026-09-02 | Not backtested, but **thoroughly examined by eye** this session — signal accountability scoring, the UT Bot lateness diagnostic, EMAS's own distance-above-MA50 at each signal date | 2026-09-02 |

That third row matters and is easy to fool yourself about. No backtest has run
on those dates, so it is tempting to call them clean. They are not: decisions
made today were informed by looking at them. A holdout has to be unseen, not
merely un-simulated.

**Conclusion: no historical window is clean any more.** The only genuinely
untouched data is data that has not happened yet.

## The holdout

**Everything from 2026-09-03 onward, forward only.**

- Config frozen as of 2026-09-02. `V4_EXTENSION_GATE`, `V4_TP1_PARTIAL_SELL=0`
  and `V4_SCORE_NORM=train_sd` all stay OFF in the live pipeline regardless of
  what the backtest says, until this holdout is scored.
- Scored on **V4_PAPER's own closed positions**, not on a re-simulation. A
  backtest of a period cannot be a holdout for a config chosen partly by
  backtesting.
- Scored **once**, when the position count reaches the threshold below. Not
  monitored for an early read, because watching a running number and stopping
  when it looks good is the same error as picking the window afterwards.

## The bar, declared now

Minimum sample: **60 closed positions.** Below that the bootstrap done on
2026-09-01 puts the false-negative rate above 30%, which is not a test. 90 is
the number for a confident read; 60 is the point at which a result becomes worth
looking at at all. Currently at 5.

Judged against the historical distribution the walk-forward produced:

| Outcome | Reading |
|---|---|
| Position win rate 24-37% **and** profit factor > 1.0 | Consistent with the validated backtest. The edge survives contact with live data. |
| Win rate inside 24-37% but profit factor < 1.0 | The hit rate holds and the payoff does not. Points at exits or costs, not selection. |
| Win rate below 24% | Either the live engine's fills differ from the backtest, or current conditions are outside 2022-2026. Both need diagnosis before any further tuning. |
| Win rate above 37% | Suspicious rather than good. Check for leg-vs-position counting before celebrating — that exact error inflated the published number from 26.3% to 49.3% once already. |

Alpha versus IHSG is recorded but is **not** the pass condition, because 60
positions over a few months is far too short a span for an alpha figure to mean
much, and dressing it up as one would be the same overreach this protocol exists
to prevent.

## What this protocol forbids

- Re-running the nine windows to justify a change and calling the result
  validation. It is now a development set, not a test set.
- Declaring any historical slice a holdout retroactively.
- Reading the live record early and stopping at a flattering point.
- Shipping a config change to the live pipeline because the backtest liked it,
  while this holdout is open.

## What it does not forbid

Research on the nine windows continues — it is the right tool for *ruling
things out* and for diagnosing mechanism, which is most of what it has been
used for. What changed is the claim it can support: it can now say "this idea is
not worth pursuing", but it can no longer say "this idea is validated". Only
forward data can say the second thing.

## Related

- `docs/V3_FINDINGS_LOG.md` — the 2026-09-01 blind-holdout entry (the previous
  one, now spent) and the eleven graded experiments.
- `docs/MASTERPLAN.md` — the real-capital readiness criteria this feeds.
