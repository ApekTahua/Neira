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
- Schema applied to Supabase 2026-08-08: `sql/broker_summary_schema.sql`,
  table `broker_summary` (normalized: one row per broker per side
  per stock per day, not a JSON blob per stock-day -- needed for
  plain-SQL rolling accumulation queries).
- n8n workflow built and debugged 2026-08-08, full node-by-node recipe in
  chat history. Fixed along the way: dynamic `stockCode` (was hardcoded
  `"INCO"`), `val` parsed to a real Rupiah integer (was the raw `"10.2 B"`
  display string), date passed through from the workflow's own input
  instead of re-scraped from a hidden HTML field.
- **Real finding, not a bug**: Indopremier's `data-brokersummary.php`
  (with `fd=all&board=all`) has NO investor-type (Foreign/Local/BUMN)
  column in the actual table data -- confirmed by fetching the raw page.
  The column that looked like it might be type was a rank number (1st/2nd/
  3rd biggest broker that day). `investor_type` stays a nullable column on
  `broker_summary` for now, unpopulated. Getting real Foreign/Local/
  BUMN classification needs either (a) a separate static broker-code
  reference table (IDX broker classifications are largely static, a
  one-time lookup, not scraped per request) or (b) re-querying per `fd`
  value if Indopremier's filter actually segments by investor type
  server-side (unconfirmed, would ~3x the request volume) -- (a) is the
  saner path, do that before (b).
- Storage checked 2026-08-08: DB is ~360MB total, `ihsg_eod` is 306MB of
  that (expected, years of data). Jan-2026-only broker backfill is
  trivial (<100MB); a full-year full-universe backfill would land
  ~900MB-1GB, comparable to `ihsg_eod` itself -- not a blocker, just
  something to weigh before backfilling past the initial test.
- `brokers` reference table built 2026-08-09 (99 rows: 4 BUMN, 32
  Foreign, 63 Local) -- joined against `broker_summary.broker_code`
  at analysis time for investor-type classification, since Indopremier's
  own table has none (see finding above). First pass sourced from a
  public compiled list caught 2 real errors when the user cross-checked
  against real data (RB's name AND type were wrong, BB was wrongly
  guessed Foreign); user then supplied the complete authoritative
  Foreign/BUMN lists, resolving all 99 rows. `DB` and `ML` still have no
  known company name (type confirmed Foreign, name unverified).
- Storage audit (prompted by this work) also found and dropped 3 fully
  dead tables (`quant_results`, `stock_universe`, `app_scrape_state` --
  zero references in either repo) and 8 dead `ihsg_eod` columns
  (`first_trade`, `tradeable_shares`, `weight_for_index`,
  `non_regular_volume/value/frequency`, `index_individual`,
  `delisting_date` -- confirmed empty on every row, not just unread).
  `ihsg_eod.foreign_buy`/`foreign_sell` (per-stock aggregate foreign flow)
  turned up ALREADY live and used elsewhere -- worth knowing for this
  initiative, since `broker_summary` adds per-broker detail on top
  of it rather than duplicating it.
- **Moved to a dedicated second Supabase project 2026-08-09** (separate
  from the main one) -- user's call, keeps this dataset's storage growth
  (est. 900MB-1GB at full year/full universe) from eating into the main
  project's headroom. `broker_summary` (table renamed from
  `broker_summary_daily` during setup, keep this file in sync with that)
  + `brokers` both confirmed live and correct there (99/99 rows verified
  via REST). Dropped from the main project 2026-08-09 -- cutover
  complete, one source of truth now. No native SQL join between the two
  projects -- combine in Python/pandas at analysis time, same as every
  other multi-source script in this repo already does.
- NOT yet backfilled (workflow built, not yet run for real), NOT yet
  analyzed, NOT yet wired into any scoring or gating logic.

**Validation bar (non-negotiable)**: broker-flow "bandarmology" is a
hypothesis to test, not an assumed edge. Before it touches live scoring it
must clear the same bar every other V3 feature cleared this session --
walk-forward across all 9 windows, neighbor-checked (not one lucky
threshold), ideally a Monte Carlo permutation check too. A plausible
folklore idea ("this broker is always the bandar") is not evidence; a
backtested, out-of-sample, neighbor-stable result is.

**Next steps** (in order):
1. ~~Apply `sql/broker_summary_schema.sql` to the (second) Supabase.~~ DONE 2026-08-09.
2. Run n8n backfill for January 2026, full universe (user's call --
   chose full ~900-emiten over a smaller test subset).
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
