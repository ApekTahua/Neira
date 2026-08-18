# Neira Masterplan

High-level roadmap tracker: what's live, what's in progress, what's idea-stage.
Blow-by-blow experiment detail (every sweep, every neighbor-check, every
negative result) lives in `V3_FINDINGS_LOG.md` -- this file tracks WHAT and
WHY at the initiative level, not every run.

## Real-money deployment readiness -- concrete criteria (written 2026-08-17)

This section didn't exist until today. One month into full dev, the user
asked directly: "sampai kapan sistemnya anda anggap deployment ready" (until
when do you consider this deployment-ready) -- fair question, overdue answer.
Everything below is a checkable criterion, not a vibe. Update the checkbox
state as evidence comes in; don't move a box to done on a promise.

**Immediate trigger for writing this now**: user asked whether tomorrow's
real-money trade could use Friday 2026-08-14's stale Screener signal (market
closed today, Hari Kemerdekaan). Answer was no -- a 4-trading-day-stale
signal violates the system's own T+1 entry design, and several of that day's
names matched the exact "already spiked, chasing it" pattern this session's
own TEBE base-rate research (932 historical episodes) found has a 35-39% win
rate and negative median return. That specific question is closed. This
section is the answer to the bigger one behind it.

### A. Live track record depth (the dominant gate -- can't be rushed)
- [ ] **>= 25-30 CLOSED trades** on V4_PAPER (not open positions -- closed
      ones are what prove SL/TP1/trailing exits behave the way the backtest
      predicts against real fills, real slippage, a real live feed).
      Status 2026-08-17: launched 2026-08-12, 5 trading days in, 2 OPEN, **0
      CLOSED**. This is the real bottleneck, not a formality.
- [ ] **>= 6-8 calendar weeks** of continuous live running, even if the trade
      count above is hit faster -- need to see the system survive ordinary
      operational reality (holidays, feed hiccups, a real regime wobble),
      not just get lucky with an active week.
- [ ] Live win rate / profit factor roughly consistent with the backtest's
      own prediction for whatever regime actually occurred over that window
      -- doesn't need to match exactly, but a live win rate far below the
      45-60% band this system's edge is built on, sustained over 20+ trades,
      is a stop signal, not noise to wait out.

### B. No new correctness bugs for a real observation window
**Clock reset 2026-08-18**: a live-path audit found and fixed FIVE more
correctness bugs the same day, on top of the two from 2026-08-17 (tick-size
rounding, holiday-calendar gap) this section already counted. Full detail
in `docs/V3_FINDINGS_LOG.md` ("2026-08-18 -- live-path audit: 5 correctness
bugs fixed"); one-line summary of each: (1) EOD reconcile fully closed a
position on a TP1 partial exit instead of selling only TP1_PCT and leaving
the rest OPEN -- the highest-severity of the five, would have wrongly
liquidated BEEF's entire position on its first-ever live TP1 (days away at
discovery time); (2) the "did this stock trade today" check required
open_price>0, which ~25% of actively-traded stocks fail on a normal day
(a data-quality gap, not a halt) -- WMPP, a currently-OPEN position, would
eventually have been wrongly force-exited as "delisted"; (3) the EOD equity
snapshot fell back to entry price instead of the last real tracked close
when a stock had no fresh bar, skewing `total_equity`/`drawdown_pct`/
`cvar_95`; (4) `paper_monitor.py`'s corporate-action guard compared live
price against entry price (can be weeks stale) instead of the last known
real close, risking a false trip that disables SL/TP1/trailing at the
wrong moment; (5) `avg_vol_20` was missing from both live position dicts,
inert today (`SLIPPAGE_ENABLED` off) but would silently mis-size slippage
if ever turned on live. All five fixed same-day, verified via
`src/test_tp1_eod_reconcile.py` (new) plus existing
`src/test_paper_trading_math.py` (still passing) -- no backtest_v4.py
shared-function changes, so no 9-window walk-forward regression was
triggered. "Found seven total across two days" is a stronger signal than
"found two" that this surface hasn't been fully audited yet -- don't treat
the clock reset as a formality.
- [ ] **>= 3-4 consecutive weeks with zero newly-discovered correctness
      bugs** in the live pipeline (`paper_monitor.py`/`paper_signal_scan.py`),
      counted starting from 2026-08-18's fixes (the latest reset), not from
      project start or from 2026-08-17.

### C. Known structural risks -- each needs an explicit decision, not silence
Don't need to be solved. Need to be consciously accepted or fixed --
un-examined is the only unacceptable state.
- [x] **Scarce-slot fragility** (`MAX_POSITIONS=6` binds on 84.8% of
      candidate-days, drops ~4,000 real candidates/year averaging 89% of
      admitted candidates' own score). THREE fix attempts this session --
      widening the cap, a bounded backlog queue, and cross-day position
      rotation (2026-08-17, `docs/V3_FINDINGS_LOG.md`) -- all rejected on
      real evidence. Rotation's apparent aggregate improvement traced
      directly to a single-window (Window 8) reshuffling cascade, the same
      artifact already confirmed for three unrelated changes this session;
      excluding that one window, no tested rotation margin showed a real
      broad benefit. Checked off as a CONSCIOUSLY ACCEPTED risk, not a
      solved one: the fragility is real and understood, all three
      identified "who gets the slot" fix directions have been exhausted,
      and no fourth attempt in that same category is planned without new
      evidence. A structurally different idea (not slot/queue reordering)
      would be needed to actually clear this, not another parameter on the
      same lever.
- [ ] **Spike/"gorengan" entry risk** (932-episode base rate: 35-39% win
      rate, negative median return, buying a stock the day after a >=20%
      single-day spike on >=10x volume). TWO fix attempts now rejected, both
      concrete directions this session identified: confirmation-delay gate
      (exclude/delay, 2026-08-17) and size-down-on-spike (let the entry
      through, reduce size only, 2026-08-18, `docs/V3_FINDINGS_LOG.md`
      "Spike sizing"). Both fail on the identical combination -- non-monotonic
      across the swept parameter, worst-case drawdown worse than baseline at
      every tested value, and the best-looking config traced to known-fragile
      windows (W4, W8, W1) swinging in opposite directions on a small
      trade-count perturbation, the same scarce-`MAX_POSITIONS`-slot
      reshuffling artifact already documented for widening/backlog/rotation.
      The underlying base-rate diagnosis is not in question; every tested way
      of mechanically acting on it inside this portfolio construction is.
      CURRENTLY AN ACCEPTED RISK, not a solved one -- a genuinely different
      category of idea (not entry-side exclude/delay/size, e.g. an exit-side
      response to a position becoming spike-flagged AFTER entry) would be
      needed for a third attempt; no third attempt on the same
      exclude-or-size lever is planned without new evidence.
- [x] **Window 3 (2023 H1)** -- already resolved as an accepted, bounded
      cost (-5.44%, alpha now close to its own benchmark) after 4 fix
      attempts, 2026-08-16. Nothing further needed here.

### D. Staged capital rollout -- even once A-C clear, don't go 0 to 100
- [ ] Start real deployment at a **small fraction of intended capital**
      (proposed: 10-20%) for a further observation window (proposed: another
      ~4 weeks / ~15-20 closed trades) before scaling to full intended size.
      This is the step that catches "works in paper, breaks against real
      slippage/execution friction/psychology," a gap paper trading cannot
      fully simulate no matter how long it runs.

### E. Personal risk fit -- the user's call, not mine, but a real precondition
User's own stated tolerance (this session): comfortable with 45-60% win
rate, wants occasional multibagger winners, accepts 20-25% drawdown for
>100%/year returns. Before any real capital moves: size the position
relative to money you can genuinely absorb a 20-25% drawdown on without it
changing your life -- not a number I can set for you, but not a step to
skip either.

### Honest timeline read
V4_PAPER is 5 trading days in with 2 open, 0 closed -- entry frequency looks
moderate-to-sparse, consistent with today's own finding that the real entry
gate returns zero qualifying candidates on 60% of days. Hitting 25-30 closed
trades realistically takes longer than it sounds; this runs on the market's
clock, not a sprint calendar. A genuinely honest earliest-case estimate for
criterion A alone is **8-12+ weeks from now (into October-November 2026)**,
and only if B and C also clear cleanly by then -- could easily run longer,
and rushing this specific criterion is exactly the failure mode the rest of
this section exists to prevent.

## Repo housekeeping

`src/` audited 2026-08-11 (user asked to declutter, worried it was
getting hard to navigate). Import-graph grep, not filename guessing --
11 files with zero references from any currently-active script moved
to `src/archive_v2/` (not deleted, git history intact): the original
`backtest_v2*.py`/`screener_v2.py`/`train_hmm.py` HMM regime-gate
approach, and a self-contained `phase0e`-`phase0i` ML research cluster.
`strategy.py`/`hmm_model.py` and `phase0_signal_validation.py`/`phase0b`/
`phase0c`/`phase0d` stayed in `src/` despite looking similarly old --
`backtest_v4.py` genuinely still imports them. See
`src/archive_v2/README.md` for the full breakdown.

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

## V4 -- IDEA STAGE, named 2026-08-11

V3 (regime + trend) merged with Bandarmology (broker conviction layer)
-- this IS the Layer 2 integration already scoped in
`docs/BANDARMOLOGY_DESIGN.md` ("Two consumers, one feature set"), just
given a version name now. Motivated by a live example the same day:
2026-08-11, IHSG pulled back -2.21% from Friday's peak (still +3.48%
above its own MA50, pullback-in-uptrend not a broken regime) while
DWGL rallied +7.58% against that weak tape. Live-checked DWGL's real
broker_summary the same day rather than assume a story: net flow was
actually THIN (+6,873 lot net vs ~140k lot gross each side) --
concentrated Foreign buying from one broker (YP, net +50,893 lot)
offset by three others (XL, CC, KK) net SELLING into the rally. Not
"bandar accumulating," a mixed/concentrated picture a naive green-
candle read would have missed entirely -- the exact justification for
this whole initiative, not just a nice anecdote.

**Not started.** Still gated behind the same validation bar as
everything else: Layer 1 (does a bandarmology feature carry real
forward-return information -- `src/diagnose_bandarmology_power.py`,
first smoke-test run 2026-08-10 on partial data, promising for
`consistency` specifically but N far too small to trust) must clear on
the FULL 2023-2026 backfill before Layer 2 (wiring into V3 as a gate/
sizing multiplier, full walk-forward + neighbor-check + Monte Carlo)
is even attempted. V4 is the name for that destination, not a
green light to start building it now.

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
- Storage audit (prompted by this work) dropped 3 tables thought fully
  dead (`quant_results`, `stock_universe`, `app_scrape_state` -- zero
  references in either repo) and 8 dead `ihsg_eod` columns.
  **CORRECTION 2026-08-10**: `stock_universe` and `app_scrape_state`
  were WRONG to drop -- both were live support tables for an n8n
  Stockbit-scrape pipeline (created just 3 days earlier, migration
  `add_stockbit_scrape_support_tables`, 2026-08-06) that replaces the
  frozen `ihsg_realtime` feed. The audit only grepped the two git
  repos; n8n workflow logic isn't text in either repo, so it was a
  structural blind spot, not a sloppy search. Broke Live Movers for a
  day before the user reported the exact n8n error. Restored both with
  their original DDL (migration `restore_stockbit_scrape_support_tables`).
  **Lesson for future table drops**: grepping both repos is NOT
  sufficient proof of "dead" when n8n is in play -- also check recent
  migration history for tables created shortly before (like this one)
  and ask the user to confirm no n8n workflow touches it. `quant_results`
  wasn't reported broken, but given this miss, treat its "dead" status
  as unconfirmed too, not proven, until something exercises it or the
  user explicitly confirms.
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
- **Backfill running live as of 2026-08-09** (n8n, resumable nested-loop
  workflow, ~1 week ETA for full January full-universe). Track progress
  with the two SQL queries in chat history (DB2 `broker_summary` landed
  count vs DB1 `ihsg_eod` expected count, per date) -- a date sitting well
  below expected AFTER the run has clearly moved past it is the signal to
  re-trigger just that date via the Batch Range node, not any lower count
  by itself (the run is sequential, in-progress dates are expected to be
  partial).
- NOT yet analyzed, NOT yet wired into any scoring or gating logic.
- **Algorithm design started 2026-08-09, concurrent with the backfill.**
  Full domain-informed spec (net-vs-gross, crossing trades, persistence
  over single-day, price-flow divergence quadrants, per-broker-per-stock
  learned profiles, proposed score components, deterministic
  human-readable labels) now in `docs/BANDARMOLOGY_DESIGN.md` -- that
  file is the source of truth for the scoring design, this section just
  tracks status. **Decision: algorithm before UI** -- UI needs a stable
  output schema to build against, and the interesting features
  (persistence, divergence) can't even be computed until enough days of
  real data exist, so there's no ordering where UI-first saves time.
  Next: prototype scoring in pandas against partial data as it lands,
  don't wait for the full month.
- **Backtest legitimacy plan settled 2026-08-09**: two layers. Layer 1
  (standalone signal check, same forward-return-by-rolling-window
  pattern as `src/diagnose_score_power.py` -- bucket stocks by score/
  label, measure forward 5/10/20-day return spread, broken down by
  window so a lucky single-period read doesn't pass as validated, same
  trap as the hysteresis-band sweep). Layer 2 (only once Layer 1
  clears): wire into V3 as a gate/sizing multiplier, full 9-window
  walk-forward + neighbor-check + Monte Carlo, the same non-negotiable
  bar stated below.
- **Architecture pivot 2026-08-09: n8n dropped for this pipeline
  entirely.** Live n8n daily injection measured at ~90min/day; a direct
  burst test against the real Indopremier endpoint (20 concurrent
  requests, 0.36s total, no rate limiting) proved the bottleneck was
  n8n's own sequential loop, not the source. `src/
  bandarmology_historical_backfill.py` now handles BOTH the 2023+
  historical backfill AND ongoing daily collection (same resumable
  script, local Parquet, `data/bandarmology_history/<year>/<month>/
  <date>.parquet`) -- fully wired and smoke-tested against the live
  endpoint. DB2 Supabase now holds only the latest trading day, not a
  rolling window -- **open follow-up, not yet built**: the planned
  accumulation chart needs multi-day history from somewhere, proposed
  as a small derived per-stock-per-day features table separate from
  raw rows, needs explicit confirmation before building. Full detail:
  `docs/BANDARMOLOGY_DESIGN.md`, "Architecture pivot" section.

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
