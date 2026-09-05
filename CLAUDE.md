# Project context (read this first, every session)

## What this repo is
IHSG (Indonesian stock exchange) screener + backtester. Live production
bot posts daily signals to Telegram via GitHub Actions.

## Branch map
- `main` (this branch) — V1 production: `src/screener.py`, `src/backtest.py`,
  `src/strategy.py`, `src/config.py`, `src/notifier.py`. **Never modify
  these** — live pipeline, protected by design across all V2/V3 work.
- `worktree-v2-hmm-screener` — active experimental branch (V2 + V3). All
  the detail lives there: **`CLAUDE.md` and `docs/V3_FINDINGS_LOG.md` on
  that branch** are the full record of what's been tried, what worked,
  bugs found/fixed, and standing cautions. Check out that branch (or read
  it via `git show worktree-v2-hmm-screener:docs/V3_FINDINGS_LOG.md`)
  before starting any new work on the screener/backtester logic.

## One-line status (as of 2026-09-05)

V1's live entry signal (squeeze + volume spike) was statistically proven to have
no edge on liquid stocks. The active system is **V4**, on the worktree branch,
paper-trading forward data since 2026-08-12.

Three things a new session needs to know before reading any number in this repo:

1. **The historical windows are closed for promotion.** At least 262 distinct
   configurations have been graded against the same 2022-2026 nine-window
   walk-forward. Under a zero-edge null, the best of 262 draws would be expected
   to return roughly +52.71% mean alpha -- more than the +26.27% actually
   reported. Those windows can rule an idea *out*; they cannot let one *in*.
   Only forward paper-trading data can promote a change. See
   `docs/HOLDOUT_PROTOCOL.md` on the worktree branch.
2. **Every published profit figure assumes a perfect fill.** `V4_SLIPPAGE`
   defaults to off: no spread paid, no market impact, on exits that are
   market-on-close.
3. **The edge is in the right tail, not in direction.** Measured buy-and-hold
   from entry against liquid names sampled on the same dates, the median pick is
   indistinguishable from random -- but the odds of a +25% run over 20 sessions
   are roughly doubled (16.4% vs 7.5%), and that gap is statistically
   significant while the median gap is not. Eleven earlier selection experiments
   were graded on hit rate, which is the one axis where the filter is average.

Treat any single backtest headline in this repo as an optimistic case, not an
expectation. **The worktree branch's `CLAUDE.md` and `docs/V3_FINDINGS_LOG.md`
are the real record** -- don't trust a summary shorter than they are.
