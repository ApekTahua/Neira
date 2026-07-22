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
(bullish regime + weekly-trend + sector-RRG intersection). Portfolio
backtest currently shows real, distributed, out-of-sample profit — but
two serious bugs (survivorship bias, hypervolatile-penny-stock leak
through the liquidity filter) were found and fixed mid-session, and both
materially changed the headline number. **Treat any backtest result in
this repo as unverified until you've checked it against the "standing
caution" list in `docs/V3_FINDINGS_LOG.md`.**

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
