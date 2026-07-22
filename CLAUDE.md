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

## One-line status (as of this writing)
V1's live entry signal (squeeze + volume spike) was statistically proven
to have no edge on liquid stocks. V3 (on the worktree branch) replaced it
with a validated rule and found + fixed two serious backtest bugs
(survivorship bias, a liquidity-filter gap that let hypervolatile penny
stocks through) that were inflating the headline number. Not yet
deployed to production. See the worktree branch for the real detail —
don't trust a summary shorter than this one for anything V3-related.
