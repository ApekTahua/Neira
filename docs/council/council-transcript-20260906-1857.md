# Council: start a parallel V5_PAPER arm at 3 ATR, or wait 5-6 months?

Date: 2026-09-06. 5 advisors, 3 peer reviewers (tiered per
`feedback_council_cost_efficiency`). Sonnet throughout, no forced opus.

## The framed question

Should Neira start a second, silent, parallel paper run ("V5_PAPER") — identical
to the frozen live config V4_PAPER except the stop widens from 1.5 ATR to 3 ATR —
so both accumulate forward evidence at once? Or wait ~5-6 months for V4_PAPER to
reach the 60 closed positions its own freeze protocol requires (it has 8)?

Evidence handed to every advisor, including what argues against:

| partition | MEAN alpha | MEDIAN alpha | worst DD | windows beaten | PF |
|---|---|---|---|---|---|
| orig | +24.05 -> +36.74 | +17.28 -> +19.55 | -21.31 -> -21.34 | 7/9 -> 6/9 | 1.90 -> 2.89 |
| shift3mo | +20.08 -> +30.23 | +15.13 -> +10.86 | -24.44 -> -26.91 | 5/8 -> 5/8 | 2.30 -> 3.80 |
| quarterly | +12.66 -> +17.44 | +8.19 -> +3.51 | -19.28 -> -20.39 | 9/14 -> 8/14 | 2.36 -> 4.61 |

Mean rises on 3/3, median FALLS on 2/3. Drawdown worsens on 2/3. ~290
configurations have now been graded against these same nine windows; under a
zero-edge null, best-of-262 would be expected at ~+52.71% mean alpha, MORE than
the +36.74% observed.

## Advisor positions

**All five said START.** It was unanimous, which is itself a warning sign and is
treated as one below.

- **Contrarian** — start, but "silent means unaccountable". A run with no
  notifications is one bad cron away from drifting unnoticed for weeks. Needs a
  heartbeat, not just failure alerts. Also: V5 does not reach 60 trades any
  faster; this is a head start, not a shortcut past the sample-size problem.
- **First Principles** — the framing is a category error. The freeze governs
  PROMOTION, not OBSERVATION. Nobody is proposing to act on the backtest;
  starting collection is what the protocol says the backtest is FOR. Waiting
  spends the one resource no backtest can manufacture: calendar time.
- **Expansionist** — ship it, and add a second arm (4.5 ATR) to map the curve
  rather than test one point.
- **Outsider** — the mean-up/median-down split is not a subtle finding, it is
  the definition of a wider stop: you removed a ceiling on per-trade loss, so
  you added variance. Say that plainly. And the "pre-registered" 10 ATR
  prediction is NOT independent evidence — the same history was already in hand.
- **Executor** — two-hour job, proven pattern. Verify no downstream view
  hard-codes a version allowlist that would silently merge V5 into V4's numbers.
  Guard against maintenance drift with cross-referencing comments.

## What the peer review caught that no advisor said

1. **Nobody pre-registered a promotion rule for V5 itself.** All five argued
   start-vs-wait; none specified in advance what forward result promotes 3 ATR,
   what kills it, and at what n. Starting without that relocates the exact
   discipline failure that produced this situation five months forward.
2. **V4 and V5 are a PAIRED comparison, not two independent samples.** Same
   entries, same days, differing only in exit. Two reviewers flagged this
   independently. It cuts both ways: pairing is more powerful than independent
   sampling, but the effective sample is only the positions where the two arms
   actually diverge, and nobody computed that.
3. **The 60-trade bar was written for grading ONE strategy, not for comparing
   two stop widths on shared entries.** Applying it here is cargo-culting the
   number rather than the reasoning.
4. **A targeted alternative was never considered:** widen the stop only AFTER a
   position shows unrealised profit. The diagnosed leak is winners being stopped
   before they run; that variant addresses it without loosening the leash on
   positions that never work — i.e. without the added variance the Outsider named.
5. **Two reviewers named the Expansionist's extra-arm proposal as the worst
   idea in the room**, and both noted it overstated the evidence: an
   "inverted-U confirmed on 3/3 partitions" is doing more work than the data
   supports, and adding forward arms compounds the very multiple-comparisons
   problem the caveat exists to warn about.

## The power question, computed rather than argued

Measured on run 37 (published v4, 262 positions, legs combined share-weighted):

- 168 of 262 positions (64.1%) exit via SL at 1.5 ATR — the only ones that CAN
  diverge between the arms.
- The live-book replay found 3 of 4 stop-outs surviving a wider stop, so roughly
  half of all positions would differ between the two arms.
- SD of position return is 18.71pp overall; only 4.12pp among stopped positions
  (a stop mechanically compresses the outcome).

So 60 closed positions yields roughly **29 divergent pairs**, enough for a paired
test to detect about a **10pp per-divergent-position** difference at 80% power.
Adequate for a large effect, not for a subtle one — which matches what we care
about, since nothing subtle would justify changing a frozen config.

## Verdict

Start ONE arm, at 3 ATR, silent, with a pre-registered promotion rule written
BEFORE it runs, a heartbeat check, and an explicitly paired analysis plan.
Reject the extra-arm proposal. Test the widen-after-profit variant on the
backtest first, since if it dominates, that is what the forward arm should carry.
