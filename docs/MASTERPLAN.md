# Neira Masterplan

High-level roadmap tracker: what's live, what's in progress, what's idea-stage.
Blow-by-blow experiment detail (every sweep, every neighbor-check, every
negative result) lives in `V3_FINDINGS_LOG.md` -- this file tracks WHAT and
WHY at the initiative level, not every run.

## V1 -- Live production (main branch)

DONE. `src/screener.py` + `src/backtest.py` + `src/strategy.py` +
`src/config.py` + `src/notifier.py`. Posts daily signals to Telegram.
Frozen by design -- never modified for V2/V3 work.

## V2/V3 -- Quant screener/backtest research (worktree-v2-hmm-screener)

V3's entry rule is validated (Monte Carlo p=0.0000 in both OOS windows --
real selection skill, not multiple-testing luck) but explicitly **not
deployment-ready for real capital** -- regime-dependent, one OOS window
(2023 H1) still loses money after every fix applied so far. Full detail
and status in `V3_FINDINGS_LOG.md`.

V3.1 filter stack (`ARA_FILTER_ENABLED=1` + `ATR_PRICE_RATIO_MAX=0.08` +
`SCORE_WEEKLY_COMP_ABS_CAP_Q=0.81`) walk-forward validated 2026-08-08,
neighbor-checked (not a lucky spike) -- deployed as V3.1_PAPER, see below.

## Paper trading -- live, public via newscraper.ai

- **V3_PAPER**: live since 2026-08-01, Rp100M simulated, frozen config.
- **V3.1_PAPER**: live since 2026-08-08, Rp100M simulated, frozen config
  (the V3.1 stack above). Second concurrent independent run, doesn't touch
  V3_PAPER. Not yet visible on the frontend (deferred, see below).

Both runs frozen for their own lifetime -- a further improvement ships as
a new versioned run, never a silent edit to a running one.

## Bandarmology / broker summary data -- IDEA STAGE, nothing backfilled yet

Started 2026-08-08. User is prototyping an n8n pull of per-stock daily
broker summary data (top buy/sell brokers, lot, value, avg price,
investor type Foreign/Local/BUMN/Pemerintah) from Indopremier's public
`data-brokersummary.php` endpoint (also explored Stockbit's
`marketdetectors` endpoint as an alternate source, session-token-based,
expires ~24h -- Indopremier is the one actually wired into n8n so far,
no auth token needed).

**Goal**: feed broker accumulation/distribution behavior into the quant
signal + paper trading as an added conviction layer, e.g. gate or size
entries by whether foreign/big-broker flow agrees with the existing
regime+weekly+sector signal, not just size/regime/trend-strength as today.

**Status**:
- Schema designed: `sql/broker_summary_schema.sql`, table
  `broker_summary_daily` (normalized: one row per broker per side per
  stock per day, not a JSON blob per stock-day -- needed for plain-SQL
  rolling accumulation queries). Not yet applied to Supabase (MCP was
  disconnected when this was written -- apply manually or once reconnected).
- n8n workflow guidance given for a January 2026 test backfill (see chat
  history 2026-08-08 for the exact node-by-node recipe). NOT yet run.
- Two real bugs flagged in the user's existing "Tidy Up Variables" Code
  node before this can scale past a single manual test: `stockCode` is
  hardcoded to `"INCO"` (needs to come from the loop's current item), and
  `val` is stored as the raw display string (`"10.2 B"`) instead of a
  parsed Rupiah number.
- NOT yet backfilled, NOT yet analyzed, NOT yet wired into any scoring or
  gating logic.

**Validation bar (non-negotiable)**: broker-flow "bandarmology" is a
hypothesis to test, not an assumed edge. Before it touches live scoring it
must clear the same bar every other V3 feature cleared this session --
walk-forward across all 9 windows, neighbor-checked (not one lucky
threshold), ideally a Monte Carlo permutation check too. A plausible
folklore idea ("this broker is always the bandar") is not evidence; a
backtested, out-of-sample, neighbor-stable result is.

**Next steps** (in order):
1. Apply `sql/broker_summary_schema.sql` to Supabase.
2. Run n8n backfill for a small test batch, January 2026 only (scope --
   full ~900-emiten universe vs a smaller liquid subset -- is an open
   decision, see chat).
3. Eyeball parsed data against a few known accumulation stories, sanity-check.
4. Once >=1 clean month exists: engineer candidate features (net foreign
   flow, broker concentration/top-N share, rolling N-day accumulation by
   broker or investor type).
5. Backtest as an additional score component or entry gate, full
   walk-forward + neighbor-check discipline, same as W1-W9.
6. Only if it clears that bar: wire into live scoring / paper trading.

## Frontend (newscraper.ai)

- Konglo/News/Disclosures/Paper-trading dense-text simplification: done 2026-08-08.
- News Stream date-range filter: done 2026-08-08.
- Disclosure AI summarizer (read filtered disclosures, surface the gist):
  deferred at user's choice ("Hold off", 2026-08-08) -- no LLM/AI provider
  infra exists in the repo yet.
- V3.1_PAPER visibility (run-selector/tabs on `/paper-trading`): deferred
  at user's choice ("Later", 2026-08-08) -- revisit once V3.1_PAPER has a
  few days of track record.
- Broker summary / Bandarmology visualization: not started, blocked on
  backend validation above.
