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
with a validated rule and found + fixed three serious backtest bugs
(survivorship bias, delisted-position handling, a liquidity-filter gap
that let hypervolatile penny stocks through) that were inflating the
headline number. A second out-of-sample window showed the edge is real
but inconsistent across market conditions; adding hysteresis to regime
detection then improved every metric in both windows (one window now
+267.18% profit/57.3% win; the other, a choppier period, +28.44%/51.2%
win — gap narrowed, not closed). A Monte Carlo permutation test then
confirmed p=0.0000 in both windows (the rule beat 5000/5000 random draws
from the same opportunity set) — the edge is real selection skill, not
multiple-testing luck. Not yet deployed to production. See the worktree
branch for the real detail — don't trust a summary shorter than this one
for anything V3-related.
