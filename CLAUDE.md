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
multiple-testing luck. **But a hysteresis-band sensitivity sweep then
showed the 2% figure was one lucky point in a noisy landscape, not a
validated optimum** (window 1 swung 61%-501% profit across nearby band
values) — the direction of the fix holds up (every band, both windows,
keeps win rate above 50%), the exact magnitude doesn't. **Redesigned the
band as volatility-relative** (scales with IHSG's own trailing
volatility instead of a flat %) — no catastrophic breakdown at any
tested multiplier in either window, unlike the fixed-% design's collapse
at its extreme, though drawdown is consistently a bit worse than the
fixed design's best case. Kept the redesign: predictable-across-
parameters beats spectacular-at-one-value.

**A THIRD OOS window (2023-01..2023-06) then returned -22.10% net
profit, 17.9% win rate — a real loss, traced to six positions opening
simultaneously on a false-start regime flip, all stopped out together.**
Fixed in two steps (a per-day entry cap, then requiring the regime to
hold 3 days before trusting it) — win rate and profit factor improved
in all three windows, and window 3's loss roughly halved (-22.10%→
-12.28%). **But window 3 still loses money**, still under 50% win rate —
timing wasn't the whole story. **Diagnostic: IHSG's own separation from
ma50 averaged 5.49%/2.18%/1.13% across windows 1/2/3** — window 3 was
bullish by direction but barely, a weak trend. Added a trend-strength
gate requiring genuine separation, not just direction; swept 1%/2% and
kept 1%: **window 1 stays strong (+152.75%, win rate up to 60.1%),
window 2 basically unchanged, window 3's loss shrinks to -5.44% with
alpha now nearly matching its own benchmark. Win rate clears 50% in all
three windows simultaneously for the first time all session.**
**STILL NOT DEPLOYMENT-READY** — not a full fix, but meaningfully
better: the failure mode changed from a big loss badly missing the
benchmark to a small loss roughly tracking it.
See the worktree branch for the real detail — don't trust a summary
shorter than this one for anything V3-related.
