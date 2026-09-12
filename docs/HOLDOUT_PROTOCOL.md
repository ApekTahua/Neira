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

---

# Amendment, 2026-09-05: three rules the methodology audit forced

The audit in `docs/V3_FINDINGS_LOG.md` (commit `140d40f`) established three
things this protocol did not cover. Each becomes a rule, because each one has
already produced a wrong answer that shipped.

## Rule 1 — the nine windows are closed for promotion, not just "weak evidence"

The earlier wording said the nine windows can no longer say "this idea is
validated". In practice that softness was ignored: `BANDAR_SIZING` went live on
the strength of a nine-window run.

The rule is now mechanical. **No configuration change reaches the live pipeline
on the strength of a nine-window result, whatever the margin.** The nine windows
may rule an idea *out*. They may not let one *in*. The only promotion evidence
is forward data scored under the holdout above.

## Rule 2 — a partition re-cut is a mandatory pre-filter, run before anything else

Every result must be reproduced on all three cuts before it is reported at all:

| Cut | Definition |
|---|---|
| `orig` | 6-month test windows from 2022-01-01 |
| `shift3mo` | the same, shifted one quarter to 2022-04-01 |
| `quarterly` | 3-month test windows from 2022-01-01 (18 windows) |

A window boundary is an arbitrary choice, so a result that only survives one
placement of the boundary is a property of the boundary. Measured on
2026-09-05, this is not hypothetical:

| Config | orig | shift3mo | quarterly |
|---|---|---|---|
| walk-forward alpha, adopted config | +22.50% | +22.89% | +8.51% |
| worst drawdown | −22.41% | **−30.02%** | **−30.02%** |

`BANDAR_SIZING` — which is **in production right now** — cleared the drawdown
leg by 0.10pp on `orig` and loses it by 3.81pp on *both* alternate cuts. It was
adopted on the one cut that happened to be cut first.

It stays in production anyway: V4_PAPER's config is frozen at 7 of 60 closed
positions and rewriting it mid-holdout would destroy the only clean test this
project has. That is a deliberate, disclosed cost, not an endorsement.

## Rule 3 — the hypothesis and its metric are written down before the run

The audit could only establish that **at least 262 distinct configurations**
have been graded against these windows. "At least", because nothing was
recorded; 262 is a floor recovered from CSVs and git history. Under a zero-edge
null, the best of 262 draws would be expected to return about **+52.71%** mean
alpha — so the reported +26.27% cannot be used as evidence of an edge, only as
evidence that the manual filtering was not the worst case.

The count has to be knowable in advance. Before a sweep runs, append one line to
`docs/EXPERIMENT_REGISTER.md`:

    date | what varies | how many cells | the ONE metric that decides | pre-run prediction

The metric is the part that matters most. Eleven selection experiments were
graded on hit rate and direction accuracy — the single axis on which the entry
filter is provably average — while the axis where it is significant (the fatness
of the right tail; see the 2026-09-05 entry in the findings log) went unmeasured
for months. Choosing the metric after seeing the numbers is how that happens.

## Rule 4 — costs are on by default

`V4_SLIPPAGE` defaults to `"0"`. Every headline figure this project has
published therefore assumes a fill at the exact close with no spread paid and no
market impact, on an exchange where the strategy's own exits are market-on-close
in names trading a billion rupiah a day. Any number reported outside an explicit
cost-sensitivity study runs with slippage **on**.

---

# Amendment, 2026-09-12: what n=60 can and cannot do, and what promotion means

Written **before any holdout result was looked at** (V4_PAPER stood at 11 closed
positions), at the reviewer's instruction, so that neither rule below can be
read as a rationalisation of an outcome. Pre-registration, not post-hoc.

## Rule 5 - n=60 is a FAIL-ONLY gate. It cannot promote anything.

"The bar, declared now" above already conceded that 60 puts the false-negative
rate above 30% and that 90 is the number for a confident read. It then said the
holdout is *scored* at 60, which quietly contradicts that. This rule removes the
contradiction by naming the consequence instead of only the caveat.

**Independent recomputation, 2026-09-12**, arriving at the same place as the
2026-09-01 bootstrap by a different route. The measured edge is a tail property:
P(+25% over 20 sessions) of **16.4%** against **7.5%** for a random liquid stock
sampled on the same dates. One-sample test against that fixed baseline, alpha
0.05:

| closed positions | power | expected tail events | reached (at 10.8/month) |
|---|---|---|---|
| 11 | 28% | 1.8 | 2026-09-12, today |
| **60** | **68%** | 9.8 | ~2027-01-28 |
| **87** | **80%** | 14.3 | ~2027-04-14 |
| 90 (this doc's own bootstrap) | 81% | 14.8 | ~2027-04-22 |

That two independent methods land on 87 and 90 is the useful part: the number is
not an artifact of either one.

**Therefore, and this is the rule:**

1. **At n=60 the holdout may only RULE OUT.** A result inside the failure bands
   in "The bar" above is actionable. A result that merely fails to clear them is
   **not evidence of no edge** - at 68% power roughly one real edge in three
   fails to show. Recording "V4 did not clear its holdout" at n=60 as a verdict
   on V4 would be the same error as promoting on the nine windows, pointed the
   other way.
2. **Promotion requires n>=87** against the fixed baseline, or the concurrent
   control route in Rule 6. No exceptions on the grounds that the number looks
   good earlier - that is the "reading the live record early" this protocol
   already forbids.
3. **Effective N is smaller than raw N, and the count must say so.** The table
   above assumes 60 independent draws. They are not independent: the same names
   recur constantly - SOCI appeared on **20 of 22** trading days in
   2026-08-12..09-11, and its overlapping 20-session windows share most of their
   price action. So the real power at any raw N is **below** the figure quoted.
   Nobody has computed the effective N; until someone does, treat every power
   number here as a ceiling, not an estimate. Computing it (a cluster-robust or
   block-bootstrap count, clustering on ticker) is itself a post-hibernation
   ticket.

## Rule 6 - the promotion mechanism, stated explicitly

The protocol forbade promotion on the nine windows and said only forward data
may promote. It never said what forward evidence is *sufficient*. With
V3_PAPER and V3.1_PAPER both retired, **V4_PAPER is the only forward arm
running**, so there is no concurrent comparison - and the rule was silent on
whether one is required. That silence made promotion structurally impossible
while appearing to be merely pending. Naming the three routes ends that.

**Route A - fixed-baseline, one-sample.** Grade V4_PAPER's own closed positions
on tail rate against the 7.5% random-liquid baseline. Needs **n>=87**, reached
around **2027-04-14**. Cheapest, and available without changing anything today.
Its weakness is that the baseline is itself an estimate and is not sampled from
the same market conditions as the live run, so a market-wide regime shift lands
entirely in the result.

**Route B - concurrent control arm.** Grade against a second forward arm running
over the identical dates. This is the only route that separates the strategy
from the market. Two-proportion test at the same alpha and power needs
**~207 per arm**:

| | positions needed | reached |
|---|---|---|
| V4 arm (from 11 today) | +196 | ~2028-03-17 |
| a control arm started today (from 0) | +207 | ~2028-04-17 |

**That is 19 months, not 5.** And the arithmetic only starts if the control arm
begins now - every month it is not running pushes that date out by a month. This
is the consequence the reviewer asked to be recorded as a conscious owner
decision rather than a discovery made later: **the owner chose on 2026-09-12 not
to start a control arm.** Route B therefore is not available on any near horizon,
and that was decided deliberately, with the date known.

**Route C - no promotion.** Treat V4_PAPER's config as terminal. Use forward
data only to remove things that fail, never to add. This is a legitimate
position and costs nothing; it just has to be chosen rather than arrived at by
default, which is what would otherwise happen.

**Until one of these is chosen in writing, the live config stays frozen.** A
change that cannot state which route licenses it does not ship.

## Rule 7 - the gate must announce itself

Scored **once, at the threshold** only works if somebody knows the threshold was
crossed. Nothing counted closed positions and said so, and the system is about
to run unattended for months, so the gate would have been crossed in silence and
read late - which is its own selection effect, since "late" means after the
number has been visible for a while.

`src/hibernation_watchdog.py` now sends a Telegram message when V4_PAPER's
closed-position count reaches 60, and again at 87. It reports the count only -
never the win rate, profit factor or P&L - so being told the gate is open cannot
become an early read of the result Rule 5 forbids.
