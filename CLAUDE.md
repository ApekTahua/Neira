# Project context (read this first, every session)

**Full findings/status log: `docs/V3_FINDINGS_LOG.md`** -- 8,000 lines, newest
entries at the bottom. Read the last few before touching anything in `src/`.
**`docs/HOLDOUT_PROTOCOL.md` binds what you are allowed to conclude** from a
backtest run; read it before reporting any number.

## What this repo is
IHSG (Indonesian stock exchange) screener + backtester. A live paper-trading
bot posts daily signals to Telegram via GitHub Actions, dispatched from n8n.

## Branch map
- `main` -- V1 production (`src/screener.py`, `src/backtest.py`,
  `src/strategy.py`, `src/config.py`, `src/notifier.py`). **Never modify
  these files.**
- `worktree-v2-hmm-screener` (this branch) -- everything since. V2, V3, and the
  current V4. `main`'s own CLAUDE.md still describes the V3 era and is stale;
  this file is the current one.

## Where things actually stand (2026-09-05)

**V4_PAPER is live and frozen.** It has been paper-trading real forward data
since 2026-08-12 and is at **7 of the 60 closed positions** needed to score the
holdout. The config does not change until then -- including parts of it that are
known to be weakly supported (see `BANDAR_SIZING` below). Freezing a config you
have doubts about is the price of having one clean test.

**No historical window is clean.** 2022-01-01..2026-06-30 has had **at least 262
distinct configurations** graded against it. Under a zero-edge null, the best of
262 draws would return about +52.71% mean alpha; the reported +26.27% sits below
that ceiling, so it is not evidence of an edge. `docs/HOLDOUT_PROTOCOL.md` Rule 1
now closes those windows for promotion: they can rule an idea *out*, they cannot
let one *in*. Forward data is the only promotion evidence.

**Re-cutting the windows changes the answer.** Worst drawdown is -22.41% on the
original cut and -30.02% on both a three-month shift and a quarterly re-cut.
`BANDAR_SIZING`, in production, cleared its adoption bar by 0.10pp on the
original cut and loses it by 3.81pp on both alternates. All three cuts are now a
mandatory pre-filter (Rule 2).

**What the strategy actually is, corrected 2026-09-05.** For months this log
said stock selection has no measurable edge, on an equal-weight profit factor of
0.95. That number is measured at *our exit*, so it answers a question about
direction. Measured at the *idea* -- buy-and-hold from entry, equal weight,
against liquid names sampled on the same dates -- the picture is different:

| hold | our median | our mean | random mean | p90 gap | share >+25% |
|---|---|---|---|---|---|
| 20d | -1.90% | +3.36% | +1.13% | **+20.37 (sig)** | **16.4% vs 7.5%** |
| 60d | -4.28% | +6.37% | +2.00% | **+31.33 (sig)** | 14.9% vs 7.0% (>+50%) |

The median pick is indistinguishable from a random liquid stock; the right tail
is about twice as fat, and that gap is statistically significant while the median
gap is not. **The system is a right-tail harvester, not a direction predictor.**
The stop cuts the losing median, the trailing stop rides the tail, and the
trailing stop is where **92.1% of gross profit** comes from across 80 exits.

Eleven selection experiments were graded on hit rate and direction accuracy --
the one axis where the filter is provably average. That is the single most
expensive methodology error in this project's history, and Rule 3
(`docs/EXPERIMENT_REGISTER.md`) exists to stop it recurring: the deciding metric
is written down before the run.

**Open, in flight:** the trailing stop carries 92.1% of gross profit and has
never been stress-tested. `src/loadtest_trail.py` sweeps its width across three
partitions and re-prices every result with realistic slippage -- `V4_SLIPPAGE`
defaults to `"0"`, so every headline figure this project has published assumes a
fill at the exact close with no spread and no market impact.

## Do not repeat these mistakes
1. Don't trust a backtest headline number without a top-5-ticker
   concentration check (V1/V2 had 90%+ concentration hiding behind a
   great-looking equity curve).
2. Don't build any historical-universe query that snapshots a single
   date — check for survivorship bias (delisted stocks silently missing).
3. Don't assume Rupiah-value ADTV means genuine liquidity — a stock can
   clear that bar via huge share count while being either dead-flat
   (REAL/HDIT) or hypervolatile (PIPA/FUTR/ISAP). Check ATR/price ratio
   too.
4. Don't default to ML for this data without testing the explicit-rule
   hypothesis first — two separate ML attempts (kitchen-sink and
   leaner-with-interactions) underperformed a simple hand-built
   intersection rule on the same features, both times.
5. Don't trust one out-of-sample window as proof of a stable edge — the
   same rule scored +216.94%/55.4% win in one window and +16.29%/50.0%
   win in another. Always test at least two windows spanning different
   regime conditions before believing a headline number.
6. Don't treat a single a-priori parameter choice as validated just
   because it produced a good result on the first try — the 2%
   hysteresis band looked great once, then a sensitivity sweep showed
   window 1 swinging 61%->501% profit across nearby values. Sweep any
   new fixed-threshold parameter across multiple values AND windows
   before trusting it, and prefer a data-driven band (e.g. volatility-
   relative) over an arbitrary fixed percentage.
7. Don't trust a "no effect" A/B result without checking whether the
   feature could even fire — adaptive hold-time first looked like it
   changed nothing in window 2 (byte-identical to baseline, zero
   CHECKPOINT exits). That was a bug (expected_hold_days computed
   against tp1_price collapsed to a fixed constant, TP1_MULT, that could
   never reach the trigger threshold), not a real null result. A
   suspiciously exact match to a baseline is a signal to check the
   mechanism, not a result to report.
8. Entry-timing concentration was found (window 3) and partially fixed
   (`MAX_NEW_ENTRIES_PER_DAY` + `REGIME_CONFIRM_DAYS`) — win rate and
   profit factor improved in all three windows, but window 3 still loses
   money. Don't assume this is fully solved; the remaining loss may be
   entry-rule selection quality, not timing. Any future entry-rule
   change should re-test all three windows, not just the two good ones.
9. A one-variable fix can help some windows a lot while barely touching
   the one it was aimed at, and vice versa — the per-day cap alone
   transformed window 2 (+26%→+99%) while barely moving window 3
   (-22.10%→-21.11%), the window it was built for. Test every fix
   against ALL windows, not just the one that motivated it.
10. Don't grade an entry rule on hit rate. Eleven experiments did, and hit
    rate is the one axis on which this filter is average -- its edge is in
    the fatness of the right tail. Before any selection test, write down the
    metric that would actually distinguish the hypothesis from the null, and
    write it down *before* seeing the numbers (`docs/EXPERIMENT_REGISTER.md`).
11. Don't report a walk-forward result from one partition. Re-cut the windows
    (three-month shift, quarterly) first -- a boundary is an arbitrary choice
    and a result that only survives one placement of it is a property of the
    placement. This is how `BANDAR_SIZING` was adopted on a 0.10pp margin it
    loses on both alternate cuts.
12. Don't report a profit figure with `V4_SLIPPAGE` off. It defaults to `"0"`,
    which means zero spread and zero market impact on an exchange where the
    exits are market-on-close. Every headline number before 2026-09-05 was
    computed that way.
13. Don't measure a strategy's selection quality at its own exit. Profit factor,
    win rate and average return all pass through the stop and the trail, so they
    answer a question about the exit design, not about the picks. To ask about
    the picks, measure buy-and-hold from entry against a same-date random
    baseline.
