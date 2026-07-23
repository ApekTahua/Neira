# Project context (read this first, every session)

**Full findings/status log: `docs/V3_FINDINGS_LOG.md` — read it before touching
anything in `src/*v2*` or `src/*v3*` or `src/phase0*`.**

## What this repo is
IHSG (Indonesian stock exchange) screener + backtester. Live production
bot posts daily signals to Telegram via GitHub Actions.

## Branch map
- `main` — V1 production (`src/screener.py`, `src/backtest.py`,
  `src/strategy.py`, `src/config.py`, `src/notifier.py`). **Never modify
  these files** — they're the live pipeline, protected by design.
- `worktree-v2-hmm-screener` (this branch) — V2 + V3 experimental work.
  All new files, V1 untouched.

## One-line status (as of this writing)
V1's entry signal (squeeze + volume spike) was proven to have **no
statistical edge** on liquid stocks. V3 replaced it with a validated rule
(bullish regime + weekly-trend + sector-RRG intersection), and three real
bugs (survivorship bias, delisted-position handling, hypervolatile-penny-
stock leak through the liquidity filter) were found and fixed mid-session
— all three materially changed the headline number. A second
out-of-sample window then showed the edge is real but NOT stable across
market conditions (window 1: +216.94%/55.4% win; window 2, choppier
period: +16.29%/50.0% win). **Adding hysteresis to regime detection
(V3-only, `strategy.py` untouched) improved every metric in both
windows** — window 1 now +267.18%/57.3% win, window 2 now +28.44%/51.2%
win — narrowing but not eliminating the gap. **A Monte Carlo permutation
test then confirmed p=0.0000 in both windows** (zero of 5000 random
draws from the same opportunity set matched the rule's actual return) —
the edge is real selection skill, not multiple-testing luck; only its
*size* is regime-dependent.

**WALK-BACK: a hysteresis-band sensitivity sweep (0.01/0.02/0.03/0.05)
showed the 2% figure above is one point in a noisy landscape, not a
validated optimum** — window 1 swings 61%→501% profit across those
bands with no clean trend, and window 2 breaks down entirely at 5%
(only 50 trades, 82% concentration — a fragile-result signature).

**Redesigned the band as volatility-relative** (`VOL_BAND_MULT`, scales
with IHSG's own trailing 20-day return volatility instead of a flat %)
— swept 1.0/2.0/3.0 on both windows: **no catastrophic breakdown at any
multiplier**, trade counts and concentration stay sane everywhere
(unlike the fixed-% design's collapse at 5%), and window 1's results
cluster far tighter (123-226%, ~1.8x range vs the old 61-501%, ~8x
range). Tradeoff: drawdown is consistently a bit worse than the fixed
design's *best* case (28-35% vs 23-29%). **Kept the volatility-relative
design anyway — predictable-across-parameters beats
spectacular-at-one-value.** Default `VOL_BAND_MULT=2.0`.

**A THIRD OOS window (2023-01..2023-06) then returned -22.10% net
profit, 17.9% win rate — a real loss, not just a weak win.** Traced to a
specific cause: six positions opened simultaneously on a false-start
regime flip (`MAX_POSITIONS=6` filled in one day), all stopped out
together within days.

**Fixed in two steps**: `MAX_NEW_ENTRIES_PER_DAY=2` (capped new
positions per day) alone barely moved window 3, because the false
regime read persisted for several consecutive days, not just one.
`REGIME_CONFIRM_DAYS=3` (require the regime to hold 3 days before ANY
new entries) combined with the cap actually worked: **win rate and
profit factor improved in all three windows** — window 3 specifically
went from -22.10%/17.9% win to -12.28%/38.5% win. Real, consistent
improvement. **But window 3 STILL loses money and underperforms the
benchmark**, and drawdown got worse in windows 1/2. Win rate 38.5% in
window 3 (still under 50%) suggests the remaining issue may be entry-
rule stock-selection quality in that market character, not just timing
— a different, still-open question.

**STILL NOT DEPLOYMENT-READY** — meaningfully better after tonight's
fixes, not solved.

**Treat any single backtest number in this repo as an optimistic case,
not the expectation** — see `docs/V3_FINDINGS_LOG.md` for the full
detail and the standing cautions below.

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
