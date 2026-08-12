# Bandarmology Design Notes

Started 2026-08-09, while the January 2026 full-universe `broker_summary`
backfill runs (n8n, ETA ~1 week). Captures the user's domain knowledge
(2026-08-09 message) as engineering spec BEFORE any code gets written --
this is the source of truth for the scoring design, `MASTERPLAN.md` just
tracks status/dates. See `sql/broker_summary_schema.sql` +
`sql/brokers_schema.sql` for the two source tables (second Supabase
project, `ptuvkgleurjcniznveye`).

## Why algorithm before UI

Backfill takes ~1 week either way -- that week is dev time, not dead time.
Building the UI first means guessing a schema (what fields does a score
card need? what does the detail page chart?) before the score itself
exists. Algorithm first fixes the output shape once; UI then gets built
against a stable contract instead of twice. Also: the interesting
patterns below (persistence, divergence, per-broker-per-stock behavior)
need >1 trading day of history to even compute -- can't validate them
until backfill has produced a real multi-week window anyway, so there's
no version of this where UI-first would have been faster.

**Plan**: prototype scoring in Python/pandas against whatever's landed so
far (partial January data), converge on features + output schema, full
validation once the month completes, THEN build the UI.

## Domain knowledge: Indonesian bandarmology + broker landscape (researched 2026-08-12)

User's explicit instruction before any further build: master this domain
first, don't just curve-fit statistics. Full research (web-sourced,
citations kept) ran via a dedicated research agent; condensed here to
what actually changes engineering decisions. Full report not saved
verbatim -- this is the distilled, actionable version.

**Broker codes.** ~88-92 registered IDX securities firms, 2-letter codes.
Verified (cross-checked against 2+ independent sources) foreign-licensed
subset relevant to our data: AG=Kiwoom, AH=Shinhan, AI=UOB Kay Hian,
AK=UBS Sekuritas, BK=J.P. Morgan, BQ=Korea Investment, CP=KB Valbury,
DP=DBS Vickers, DR=RHB, DU=KAF, FS=Yuanta, GI=Webull, GW=HSBC, HD=KGI,
KI=Ciptadana, KK=Phillip, KZ=CLSA, QA=Tuntun, RX=Macquarie, TP=OCBC,
XA=NH Korindo, YP=Mirae Asset, YU=CGS International, ZP=Maybank. Also
confirmed: CC=Mandiri Sekuritas (local, BUMN-affiliated, #1 by value
despite not being foreign), PD=Indo Premier (local, largest RETAIL
broker by client count). **Warning found in the research itself**:
multiple Indonesian retail blogs circulate wrong code mappings for the
same codes (contradicting each other and the verified list above) --
only `idx.co.id`'s own Anggota Bursa listing counts as ground truth;
any future mapping table must cross-validate against 2+ sources before
being trusted, same discipline as everything else in this doc.

**A structural fact that changes how we should read `concentration`:**
a broker code is an AGGREGATE of that firm's entire client base --
retail, active traders, institutional, and prop, all bucketed under one
code. YP (Mirae) and PD (Indo Premier) are foreign-owned-and-massive
vs. local-and-massive respectively, but both are functionally giant
RETAIL aggregators -- their "net flow" is mostly aggregate retail
sentiment, not one informed actor. A small, low-volume institutional
code carries a cleaner per-unit-volume signal than a big retail-app
code. **Implication**: raw net-flow/concentration treating all ~90
codes uniformly is probably diluting signal with retail noise from the
biggest codes -- normalizing by each broker's own baseline activity
(already partially done via the rolling-window z-score in
`rolling_features`) may need a broker-tier weighting on top, not yet
built. Don't act on this without testing it as its own feature variant.

**Multi-broker CORRELATED CLUSTER buying -- a technique we haven't
built.** The most sophisticated real-world implementation
(Stockbit's productized "Bandar Detector") explicitly looks for the
SAME directional bias spread across 3-10 different broker codes
simultaneously, reasoning that a real bandar splits orders across
multiple houses to avoid single-broker detection. This is DIFFERENT
from `bandarmology_rotation_detector.py` (which finds recurring
OPPOSITE-side pairs -- internal rotation/"tuker barang"). A same-
direction cluster detector is a new, currently-unbuilt feature --
worth its own round once the daily-feature redesign settles.

**Context-conditioning confirms the existing 4-quadrant design.** Folk
technique treats accumulation-during-price-weakness and distribution-
during-price-strength as the credible ("hidden") signal, and same-
direction-as-price as weak/noisy -- this is exactly the price-flow
divergence quadrant already in this doc's original design (2026-08-09,
user's own domain input), now independently corroborated by the wider
retail-education literature, not just one user's intuition.

**20-day horizon dominance is domain-consistent, not just a lucky
regression result.** Folklore is explicit that accumulation phases run
weeks to months (the commonly-cited SMGR example: ~5-6 months, Nov
2021-Apr 2022, sideways/declining most of that time before markup).
The Layer 1 finding above (20d horizon clean 3/3 across both the full-
range and 2024+-restricted runs, for both `net_flow_norm` and
`concentration`) lines up with that timescale rather than contradicting
it -- a fast (5d) feature losing to a slow (20d) one is what the
domain predicts, which raises confidence this isn't p-hacking.

**Manipulation is real, OJK-documented, and recent.** Nominee accounts
are the confirmed mechanism (BEBS/Mirae 2026: 58 nominee accounts, one
beneficial owner controlling 98.5% of an IPO, ~Rp14.5T in alleged
illegal gains). Multiple older cases follow the same pattern (Jiwasraya/
Asabri, IMPC 2016, Belvin Tannadi 2021-22 social-media pump). OJK's
active 2026 enforcement sweep: ~Rp240B+ in sanctions across 151-233
parties. Concentrated in small-cap/"gorengan" names -- the same
liquidity-contamination risk this project already learned the hard way
on the V3 backtester (survivorship bias, delisted-position handling,
the ATR/price-ratio filter gap). **Implication**: validate Bandarmology
features on liquid names first, same as V3's own liquidity discipline,
before trusting them on the full ~900-stock universe.

**IDX's own official early-warning signal we're not using: UMA
(Unusual Market Activity).** Publicly published flags for abnormal
price/volume movement, frequently tied to repeated Auto Reject Atas/
Bawah hits in small-caps. A legitimate, low-noise, non-folklore
exclusion/validation signal, historically pullable -- not yet wired
into anything here.

**No broker-code regime break in our data window.** Real-time broker-
code display was closed IDX-wide on 2021-12-06 (reducing
herding/front-running), but the END-OF-DAY broker summary -- our exact
data source -- was never affected. Our full 2023-2026 backfill sits
inside one consistent regulatory regime for this data; the 2023
weakness found in Layer 1 is not explained by a data-availability
policy change.

**Academic verdict (thin but real)**: one Indonesian university study
found bandarmology alone has no significant effect on investor returns,
but bandarmology + technical + fundamental analysis combined does have
a significant joint effect. Consistent with this project's own framing
from day one -- Bandarmology as one input alongside the V3 quant score,
not a standalone signal -- and consistent with Layer 1's own result
(2 of 3 features show real but modest, horizon-dependent effects, not
an overwhelming standalone edge).

## Core corrections to naive net-buy/net-sell (user's domain input)

Naive approach ("foreign net buy = bullish, avoid net sell") is explicitly
wrong per the user and must not be how this is built:

1. **Net per broker, not gross.** A broker can appear in both the buy-10
   and sell-10 for the same stock same day (crossing/nego activity --
   client A buys through broker X, client B sells through the same broker
   X). Scoring off "how many times broker X appears on the buy side"
   double-counts this. Always use `buy_lot - sell_lot` per
   `(broker_code, stock_code, trade_date)`, never raw side counts. This is
   mostly self-correcting once done right -- net washes out same-broker
   crossing automatically.
2. **Track turnover separately from net.** `buy_lot + sell_lot` (gross
   churn) vs `buy_lot - sell_lot` (net) per broker per stock per window.
   High turnover + near-zero net = churn/rebalancing/no real conviction,
   not accumulation, even if the broker looks "active." This is exactly
   the "average terus2an tapi rebalancing" case the user flagged.
3. **Single-day net buy is not a signal, persistence is.** A bandar can
   buy big one day and dump the next specifically to mislead followers
   (user's explicit point). Score a rolling window (10-20 trading days),
   not a single day. Two features: (a) magnitude -- sum of net flow over
   the window, normalized by the stock's own ADTV (reuse the ADTV concept
   already in `src/backtest_v3.py`/V3, don't reinvent); (b) consistency --
   `days_net_positive / active_days` in the window. High magnitude + low
   consistency (one huge day, rest flat/negative) is a weaker signal than
   the same magnitude spread evenly -- flag, don't just sum.
4. **Broker "type" (Foreign/Local/BUMN) is a coarse prior, not the whole
   story.** Real signal is which SPECIFIC broker(s) actually move THIS
   specific stock -- the user's "saham A digerakkan Broker A dan B"
   point. This is stock-specific, not universal, and needs to be learned
   from history per (broker_code, stock_code) pair, not assumed from the
   broker's type alone.

## Price-flow relationship (the interesting part, per user)

Four quadrants, comparing rolling net-flow trend against rolling price
trend (vs its own MA, same style as existing regime detection):

| Flow | Price | Read |
|---|---|---|
| accumulating (net buy, consistent) | flat / mild up | **healthy accumulation** -- bandar holding price down while collecting, textbook case per user |
| accumulating (net buy, consistent) | down | **anomaly** -- either defending/supporting price while underwater, or accumulation isn't the real story (distribution happening elsewhere/off-book). Flag, don't auto-score bullish -- this is exactly the trap the user warned about |
| distributing (net sell, consistent) | down | distribution confirmed, unsurprising |
| distributing (net sell, consistent) | up | **warning** -- selling into strength/demand, bearish despite a green candle |

The "flat/up price during accumulation" and "down price during
accumulation" cases look identical if you only read net-buy magnitude --
this is precisely why the user said not to just look at direction and
conclude. The price-flow divergence read is the actual value-add over a
naive net-buy screener.

## Per-broker-per-stock behavior profile (learned, not assumed)

Derived table, recomputed periodically (not static config): for each
`(broker_code, stock_code)` pair with enough history, test whether that
broker's net-flow changes actually lead that stock's price moves
(lagged correlation/rolling backtest, walk-forward style). Only promote a
broker to "known mover for this stock" if the relationship is real across
multiple periods -- same validation discipline as the rest of this repo
(`docs/MASTERPLAN.md`'s "Validation bar" section already states this for
anything touching live scoring; applies here too even though this is a
descriptive/research feature first, not a trading gate yet). A plausible
story ("broker X is always the bandar for Y") is not evidence on its own,
same standard as every V3 finding.

## Proposed score components (deterministic, rule-based -- no LLM)

Matches the rest of this repo's "100% algorithmic" constraint (see
`serialized-stargazing-sprout` paper-trading plan) even though this isn't
a live trading decision yet -- keep it consistent, and rule-based is also
just less code than standing up an LLM call for a bounded classification
problem (lazy-correct, not lazy-cut-corner).

Rolling window per stock (10-20 trading days, exact window TBD once real
data exists to tune against):

1. **Net flow magnitude** -- sum(net_lot or net_value) over window /
   ADTV.
2. **Buy consistency ratio** -- days net-positive / active days.
3. **Concentration** -- top-1/top-3 broker share of total buy value
   (one dominant player vs broad participation -- both are real patterns,
   neither is automatically better, just different).
4. **Price-flow divergence bucket** -- one of the four quadrants above.
5. **Known-mover boost** -- only applied if this stock has a validated
   broker profile (previous section) and that broker is currently active.

Composite: a 0-100 "Smart Money Accumulation Quality" score OR a
categorical label (Strong Accumulation / Moderate / Distribution /
Anomaly-Flagged), built from the features above via fixed thresholds --
tune thresholds against real backfilled data, don't hand-pick before any
data exists.

**Human-readable line** (e.g. "Smart money accumulating steadily, broad
across N brokers, price holding sideways") is a deterministic template
selected by which feature buckets fired -- not generated text. Keeps it
inspectable/debuggable and matches the algorithmic-only constraint.

## UI shape (build AFTER the score schema is stable)

- Per-ticker: a compact score badge + short checklist (mirrors existing
  card patterns on newscraper.ai) on whatever card/list already shows the
  stock -- "See more" links to a dedicated Bandarmology detail page.
- New nav entry: **Bandarmology** (separate menu, per user).
- Detail page: cumulative net-flow line chart with price overlay (OBV-style
  accumulation/distribution line) -- built to catch flow reversing before
  price does, exactly the "flow sudah berbalik, harga belum" case the user
  described. Reference the `dataviz` skill when this gets built (diverging
  categorical bars were already scoped for a different Foreign Flow
  component earlier this session -- this is a new chart type, a cumulative
  time series with a price overlay, needs its own pass through that
  skill's form/color/interaction checklist, not a reuse of the earlier one).
- Broker behavior profile surfaced per stock (which broker(s) historically
  move this ticker, per the learned-profile table above) -- exact layout
  TBD, likely part of the same detail page.

**Explicitly not started**: no code yet, this is spec only. Frontend work
also blocked on `docs/MASTERPLAN.md`'s existing "Bandarmology visualization:
not started, blocked on backend validation" note -- that note still holds,
this file is what "backend validation" now means concretely.

## Architecture pivot 2026-08-09: n8n dropped, local script is now the ONLY scraper

Superseded the "Storage split" plan below same day, same conversation --
kept the old text further down for the historical record, this section
is what's actually true now.

Trigger: the live n8n daily injection (Jan-2026-forward, DB2) turned out
to take **~90 minutes for ONE trading day**. Diagnosed before reacting
(never touch n8n, but the *source* is fair game to test directly): a
20-way concurrent burst against the real Indopremier endpoint returned
all 200s in 0.36s total wall time, no rate limiting. So the bottleneck
was n8n's own per-item sequential loop overhead, not the source being
slow or protected -- confirms this repo's standing "verify before
reacting" discipline once again (see [[feedback-verify-dont-trust-empty-success]]-style
reasoning applied to a slowness claim instead of a silent-failure one).

**Decision: replace n8n for this pipeline entirely**, both historical
AND ongoing daily -- `src/bandarmology_historical_backfill.py` is now
the one script for both. It already writes local Parquet with a
day-file-exists resumability check (built for the "resume a failed
historical year" case) -- that same mechanism means re-running it for
the current year picks up whatever new trading day(s) landed since the
last run. No separate "daily" script needed.

**Supabase DB2's role changes**: no longer an accumulating rolling
window written by n8n. User's call: DB2 should hold only the latest
trading day. **Still open** (flagged 2026-08-09, not yet built): the
planned rolling accumulation chart / score badge on the website needs
multi-day history from *somewhere*. Proposed resolution, not yet
confirmed: split into two tables --
1. `broker_summary` (existing raw shape) -- last trading day only,
   mirrors what the local Parquet just collected, mainly for a
   "today's biggest buyers/sellers" drill-down if wanted.
2. A new small DERIVED table, one row per (stock_code, trade_date):
   score + feature columns (net_flow, consistency_ratio, divergence
   bucket, label) computed locally from the full local Parquet history.
   Tiny per row (~1 row/stock/day vs ~20 raw rows/stock/day), cheap to
   keep a real rolling window (weeks/months) of even on the free tier --
   this is what would actually power the chart, not raw broker rows.

**CONFIRMED 2026-08-10**: option 2, built. `sql/bandarmology_flow_daily_schema.sql`
(table `bandarmology_flow_daily`, DB2) + `src/bandarmology_push_daily.py`
(recomputes the full local feature history via bandarmology_features.py,
upserts it all, batched). Turns out this table is cheap enough to hold
the FULL history, not just a bounded window -- ~100MB estimated for
2023-2026 full universe, ~30MB/year after -- comfortably inside the free
tier for years, so no pruning logic needed for this one (unlike the raw
`broker_summary` table, which does stay last-day-only). Score/label
columns deliberately not in this table yet -- thresholds aren't tuned
(need the full backfill), added later via a plain column add once they
exist, doesn't block shipping the chart now. Not yet run for real --
needs `SUPABASE_BROKER_URL`/`SUPABASE_BROKER_KEY` in a local `.env`
(DB2 service-role key, never pasted into chat again, never committed).

**Investor-type CSS class, found and rejected same day**: the live
HTML actually tags each broker row `text-local`/`text-foreign`/
`text-bumn` (revises the earlier "no type column at all" finding --
true for the raw table DATA, not true for the rendered class). Tested
against ATIC 2026-08-04: 4 codes (BQ, CP, DR, XA) the user classified
Foreign by firm ownership showed `text-local` here. Likely explanation:
this tags the TRANSACTION's investor origin (whose money, that specific
trade, that day) rather than the BROKERAGE FIRM's ownership -- a
different, real bandarmology concept, not a data error. **User's call:
ignore it, keep using the manual `brokers` table as the sole source of
investor-type classification.** Noted here so a future session doesn't
rediscover and re-litigate this.

## Storage split: cloud (operational) vs local (backtest-only) -- SUPERSEDED above, kept for history

Decided 2026-08-09, same day superseded by the pivot above once the
n8n speed problem surfaced. Original plan: DB2 stays a bounded rolling
operational window, deep history goes local. Still correct about ONE
thing that carried forward: raw broker-level history has no business
living in a paid/limited cloud DB when nothing queries it live -- that
principle is why the pivot above still keeps everything local-first.

## Local historical backfill (2023+, backtest-only)

`src/bandarmology_historical_backfill.py` -- one-off Python script,
separate from n8n's daily production pipeline. Decided 2026-08-09:

- **Scope: 2023-01-01 forward**, start year is a CLI arg so extending
  back to 2020 (user says the source has data that far back, unverified
  by me) is a one-line change, not a rewrite.
- **Folder layout**: `data/bandarmology_history/<year>/<month>/<date>.parquet`
  -- one file per trading day, all stocks' broker rows for that day.
  Resumable for free: a day already on disk is skipped, so a run
  interrupted mid-year just gets re-invoked with the same year.
- **Run granularity: one year per invocation** (user's own checkpoint
  boundary) -- `python src/bandarmology_historical_backfill.py 2023`.
- Trading calendar + per-day stock universe both sourced from DB1
  `ihsg_eod` (read-only) -- same `volume>0` rule and same
  one-liquid-stock-for-distinct-dates trick already used elsewhere this
  session. Script never writes to Supabase.
- Concurrency 12 + a small per-request delay per worker (matches
  `data_fetch.py`'s existing `FETCH_CONCURRENCY=12` reasoning: I/O-bound,
  gentle enough not to look like a burst attack) -- user confirmed no
  known rate-limiting on the source, but asked for a small delay anyway.
- **DONE 2026-08-09**: real URL/params/headers supplied by the user
  (from their working n8n node), `fetch_broker_summary()` implemented
  and smoke-tested end-to-end against the live endpoint (BBCA
  2026-08-04, real rows, correct units). Confirmed no cookies needed.
  This script is now also the daily production job, see "Architecture
  pivot" above.

## Two consumers, one feature set (clarified 2026-08-10)

User asked directly: is this building user-facing insight (which broker
is the mover, quiet accumulation/distribution) or a score that feeds
quant signal -- answer is both, same features, different validation bar:

1. **User insight** (narrative, checklist, charts on the Bandarmology
   page) -- descriptive only, human stays in the loop and decides.
   Lower bar: ships once Layer 1 shows a feature carries real
   information, doesn't need to wait for Layer 2. This is the nearer-
   term deliverable.
2. **Quant signal integration** (gate/sizing multiplier in V3) --
   automated, moves real capital decisions. Full bar: walk-forward +
   neighbor-check + Monte Carlo, same as every other V3 feature, per
   the "Validation bar" section below. Does not ship before that.

**Named pattern added**: "internal rotation" -- distinct from generic
crossing (point 1 above). Turnover high, net near zero, but concentrated
in a small recurring CLUSTER of brokers trading with each other
repeatedly over time (not just one broker crossing itself one day) --
user's "tuker barang" framing. Worth its own checklist item once the
per-broker-per-stock profile (learned-mover section above) is built,
since detecting a recurring cluster needs that same historical
broker-pair tracking, not just a single day's crossing check.

## Layer 1 validation results (full dataset, 2026-08-12)

Ran `diagnose_bandarmology_power.py` against the complete backfill
(2023-01-02..2026-07-31, 928 stocks, 692,820 merged feature/price rows,
3 subperiods x 5/10/20-session horizons = 9 checks per feature). Prior
runs this session were on partial data (2023 H1 only) and explicitly
flagged untrustworthy -- this is the first real read. Agreed pass bar
going in: top quantile beats bottom in >=6/9 checks AND no systematic
sign reversal across a whole subperiod (a feature that flips direction
for an entire window is worse than noise as a gate, not just weaker).

| feature | wins/9 | notes |
|---|---|---|
| `net_flow_norm` | 6/9 | Numerically clears the bar, but period 1 (2023-01..2024-03) reverses at ALL THREE horizons (top<bottom every time), not scattered noise -- a sustained wrong-direction stretch across an entire subperiod. Strengthens steadily with horizon (1/3 -> 2/3 -> 3/3 at 5d/10d/20d) and periods 2-3 are solid. Fails the no-reversal condition as stated. |
| `consistency` | 4/9 | **Reverses the earlier read.** The 2026-08-10 partial-data smoke test flagged this as the most promising feature (3/3, 2/3, 3/3 on Jan-Jul 2023 only) -- on full data it's the weakest of the three and flips sign in periods 2 and 3 after being strong in period 1. Textbook small-sample overfit: the partial-data run WAS period 1, so of course it looked great in isolation. Exactly the "don't trust one lucky window" lesson from V3's hysteresis-band sweep, now confirmed on this feature too. |
| `concentration` | 5/9 | Same shape as `net_flow_norm` -- weak/reversed in period 1, strengthens with horizon in periods 2-3 (0/3 -> 2/3 -> 2/3). Under the bar. |

**Verdict: none of the three features cleanly passes as-is.** Common
pattern across all three: period 1 (2023-01..2024-03) is where every
feature breaks down, while periods 2-3 (2024-03 onward) look
progressively better as horizon lengthens. Two live hypotheses, not yet
distinguished: (a) genuine regime dependence -- these features need a
trending/liquid market to mean anything, same regime-sensitivity V3's
own score has, and 2023 was choppier; or (b) 2023 data quality is worse
(the backfill's earliest months, thinner broker participation, more
gaps) than 2024-2026. Next step before any redesign: rerun the same
check restricted to periods 2-3 only, and separately profile row
counts/completeness for 2023 vs later years -- don't touch the feature
formulas until that's answered, or risk fixing a data problem with a
model change.

Not dead ends -- `net_flow_norm` and `concentration` both show a
believable, monotonic "better at longer horizons, better in later
periods" shape that's worth understanding rather than discarding. But
none are gated into anything yet, and `consistency` specifically should
not be described as "the most promising feature" anywhere going
forward -- that was the partial-data artifact.

### Follow-up: periods-2-3-only rerun (2024-03-06..2026-07-31, excludes 2023)

Row-count/completeness check first: 2023 has 239 trading days, 852
stocks, 12,742 rows/day; 2024/2025/2026(partial) climb smoothly to 237d/
887stk/13.6k, 236d/897stk/15.1k, 134d/880stk/15.8k. No missing days, no
stock-count collapse -- a gradual ~10-15%/year activity ramp, not a
backfill defect. That points toward genuine regime dependence over data
quality, and the rerun confirms it differently per feature:

| feature | wins/9 (2024+) | vs full-range | verdict |
|---|---|---|---|
| `net_flow_norm` | 7/9 | up from 6/9 | **Passes.** 20d horizon clean 3/3 in both the full-range AND restricted run (6/6 total) -- the strongest, most repeated result of this whole check. Only weak at short horizons in the most recent subperiod (2025-10-14..2026-07-31), not a full-subperiod reversal. |
| `consistency` | 4/9 | **unchanged from 4/9** | **Still fails.** Excluding 2023 didn't move this feature's win rate at all -- proof its weakness isn't a 2023-data-quality artifact, it's a genuine property of the feature. Weak/reversed at 10d and 20d in 2 of 3 windows regardless of which window. Drop as a standalone signal, don't rework by tuning -- the shape itself is wrong, not the calibration. |
| `concentration` | 7/9 | up from 5/9 | **Passes.** Same clean-20d pattern as `net_flow_norm` (3/3 both runs, 6/6 total). Only weak at short horizons in the oldest restricted-run subperiod (2024-03..2024-12). |

**Conclusion: `net_flow_norm` and `concentration` are real, 2024+
data, especially at the 20-session horizon** -- both clear the >=6/9
bar with no full-subperiod-all-horizon reversal once 2023 is excluded.
`consistency` is confirmed dead as designed; excluding 2023 was a fair
test and it didn't move. The 20d-horizon dominance (a ~1-month window)
is worth cross-checking against the domain research: Indonesian
bandarmology folklore describes accumulation phases as running weeks,
not days, before markup -- if that holds up, a slow feature outlasting
a fast one isn't a coincidence, it's the folklore's own timescale
showing up in the data. 2023 itself is not yet explained (still
unresolved whether it's regime or something else) but is no longer
blocking -- treat pre-2024 data as suspect for these two features until
further notice, don't silently include it in any future score.

Reran `bandarmology_broker_profile.py` against the same full backfill.
35,944 (stock, broker) pairs tested (>=20 active days), 2,767 candidate
movers (same-sign correlation both halves, |corr| >= 0.15 both halves)
-- up from 18,127 tested / 2,101 candidates on the earlier Jan-Oct 2023
partial run, and now resting on real 3.5-year history instead of ~9
months. Top candidates by active-days are dominated by large full-
service brokers (XC, YP, XL, CC, AK) active 700-837 days out of ~880 --
expected, since more active days mechanically means more opportunity to
clear the threshold, not necessarily a stronger relationship. Individual
correlations are modest (0.15-0.63), consistent with this being a loose
screen with no multiple-testing correction, exactly as the script's own
docstring already caveats. A `RuntimeWarning: invalid value encountered
in divide` appeared for a handful of pairs -- traced to a half-period
with a constant (all-zero) net_lot series producing a zero standard
deviation; those pairs correctly resolve to NaN and get excluded by the
threshold check, not a correctness bug.

This is the per-stock-per-broker "who plays actively here" mechanism
the user asked about directly (2026-08-12) -- confirmed working on real
data, but still not persisted anywhere or exposed on any page. Two
follow-ups this surfaces, not yet designed: (1) push candidate-mover
pairs to a DB2 table so the frontend can query "which brokers move this
stock" per ticker; (2) a broker-level (cross-stock) characteristic
profile is a separate, currently-undesigned entity -- this script only
answers "which brokers move THIS stock," not "what kind of trader is
broker XC in general."

### Same-side cluster detector (2026-08-12)

`bandarmology_cluster_detector.py` -- the SAME-direction counterpart to
`bandarmology_rotation_detector.py`, built directly from the domain
research: Stockbit's productized "Bandar Detector" explicitly looks for
the same directional bias spread across 3-10 broker codes at once
(splitting orders across houses to avoid single-broker detection), not
just single-broker net flow. Reuses the exact lift-ratio methodology
already proven on the rotation detector (observed vs. expected
co-occurrence rate under independence), just for BOTH-buy or BOTH-sell
co-occurrence instead of one-buyer-one-seller. Pairwise only for now --
real clique-finding (actual 3-10-broker groups) is a later step once
this pairwise layer is trusted, per the script's own docstring.

First run, full 2023-2026-07-31 data: **1,879 candidate pairs**
(>= 15 same-side days, lift >= 1.5) -- comparable scale and shape to the
rotation detector's 4,368. Same caveats apply: unvalidated placeholder
thresholds, structural flag only, needs the same forward-return
discipline as everything else before being trusted as a signal.

### Liquidity-gate test (2026-08-12) -- hypothesis refuted, redirected into a stronger finding

Domain research (above) warned that OJK-documented manipulation
concentrates in small-cap/"gorengan" names, same contamination risk V3
already learned the hard way -- hypothesis: restricting to liquid names
(ADTV_20 >= `config.ADTV_MIN`, same threshold V3 itself uses) should
clean up the edge. Tested on the 2024+ window (473,954 -> 191,487 rows):

| feature | 2024+ (all liquidity) | 2024+ liquid-only |
|---|---|---|
| `net_flow_norm` | 7/9 | **1/9** |
| `concentration` | 7/9 | 6/9 |

**Hypothesis refuted** -- liquid-only made both features worse, sharply
so for `net_flow_norm`. Two follow-up robustness checks
(`diagnose_bandarmology_robustness.py`) to find out why, rather than
just discarding the liquidity idea:

**Check A -- winsorize forward returns at 1%/99%, same 2024+ data (tests
outlier/manipulation-spike dependence):**

| feature | unwinsorized | winsorized |
|---|---|---|
| `net_flow_norm` | 7/9 | **5/9 (drops)** |
| `concentration` | 7/9 | **8/9 (improves)** |

**Check B -- 20d-horizon top/bottom spread by per-day liquidity
quintile (Q1=illiquid..Q5=liquid), tests WHERE the edge lives:**
- `net_flow_norm`: positive and fairly strong Q1-Q3 (+0.020, +0.032,
  +0.010), weak Q4 (+0.002), reversed Q5 (-0.010). Edge is broad across
  illiquid-to-mid names, breaks down only at the very top of the
  liquidity spectrum.
- `concentration`: **reversed** in Q1-Q2 (-0.015, -0.019), positive in
  Q3-Q4 (+0.008, +0.010), reversed again in Q5 (-0.009). Non-monotonic
  -- the edge is NOT in the most illiquid names at all, it lives in the
  middle of the liquidity spectrum and fails at both extremes.

**Conclusion -- the two features are not equally trustworthy, and this
resolves cleaner than the liquidity-gate test alone suggested:**

- **`concentration` is the stronger, more robust candidate.** Its edge
  survives (even improves under) winsorizing, and it does NOT live in
  the manipulation-risk-prone illiquid tail -- it's actually reversed
  there. This is real evidence against the manipulation-contamination
  worry for this specific feature.
- **`net_flow_norm` is the more fragile one.** Its edge drops
  meaningfully under winsorizing (real dependence on extreme-return
  prints) AND is strongest specifically in the most illiquid quintiles
  -- both point the same direction: some real part of this feature's
  apparent edge may be extreme, possibly manipulation-adjacent moves in
  small-cap names, not clean broad-based accumulation signal. Not
  disqualified outright (Q1-Q3 are still directionally positive, not
  reversed), but should not be treated as equally trustworthy as
  `concentration` going into any further design work -- lead with
  `concentration`, treat `net_flow_norm` as secondary/supporting until
  it gets more scrutiny (e.g. manually inspecting the specific extreme
  prints driving the winsorize-sensitivity).

### CORRECTION 2026-08-12: broker_summary_history table dropped, monthly local refresh instead

Proposed a permanent per-broker DB2 archive table (`broker_summary_history`)
to solve "how do mover/rotation/cluster get refreshed without the laptop
being on." Sized it wrong the first time (guessed 500-700MB/year); a
proper estimate from the REAL row counts (11,949,299 rows for 2023-2026-
07-31, 15,329 rows/day measured) came out to ~2.3-2.5GB for the full
backfill alone, ~700-750MB/year growth -- even after trimming the schema
(drop archived_at, narrower int types, one fewer index) that's still
~1.3-1.5GB, and **the user is on Supabase's free tier: 500MB total.**
Would have blown the quota on the very first push.

**Fix, no new table needed**: local Parquet already IS the permanent
archive (free, 3.5 years deep, lives on disk, zero Supabase quota
impact) -- the only real gap was keeping it current. Mover/rotation/
cluster patterns are slow-moving (broker behavioral relationships don't
flip day to day) and don't need daily refresh the way the flow chart
does. So: refresh MONTHLY, not daily -- briefly resume
`bandarmology_historical_backfill.py` for the past month (re-scrapes
from Indopremier directly, not from Supabase's overwritten
`broker_summary`, so no data is ever actually lost even across a
month-long gap), rerun the three detector scripts, push just the small
result tables again (mover_pairs + rotation_pairs + cluster_pairs,
~9,000 rows combined -- trivial size, already what's live in DB2).
`broker_summary` (last-day-only) and `bandarmology_flow_daily`
(~100MB, aggregate history) are untouched by this and stay 100%
automatic via n8n either way. Net effect: laptop dependency drops from
"daily" (the original worry that motivated moving to n8n) to "monthly"
for this one piece -- without ever touching the 500MB limit.
`broker_summary_history` was left created but empty (harmless, ~0
storage) rather than immediately dropped -- no urgency either way.
**Update same day**: user decided to drop it anyway, gone.

**UI requirement noted for the frontend build (not yet built)**: user
wants a visible reminder that the monthly mover/rotation/cluster refresh
is due -- a staleness indicator on the Bandarmology page (e.g. "last
refreshed N days ago" pulled from `computed_at` on the three candidate
tables, flagged/highlighted once N exceeds ~30 days), not just something
tracked in this doc. Whoever builds the frontend page must include this.

### V4 sizing integration built + validated, promotion explicitly deferred (2026-08-12)

Built `BANDAR_SIZING_ENABLED` (`backtest_v3.py`, default OFF): a
`bandar_mult` on position size, same pattern/bounds as `size_mult`/
`liq_mult`/`trend_mult`, driven by `concentration` (the one feature that
survived Layer 1). `attach_bandarmology()` merges it in from local
Parquet for backtesting; live paper trading would read from DB2's
`bandarmology_flow_daily` instead (not yet wired -- see below).

9-window walk-forward, off vs on (cache regenerated first -- the old
`.cache/walk_forward_data_*.pkl` predated the new `concentration`
column):

| metric | off (baseline, confirmed byte-identical to prior record) | on |
|---|---|---|
| Windows beating bench | 6/9 | 6/9 |
| Win rate >50% | 4/9 | 4/9 |
| Mean alpha | +21.71% | **+24.09%** |
| Median alpha | +12.60% | **+19.09%** |
| Mean profit factor | 1.58 | **1.88** |
| Mean max drawdown | -16.08% | **-15.03% (better)** |
| Worst max drawdown | -21.61% | -21.84% (slightly worse) |

Windows 1-2 (2022, before Bandarmology data exists) are byte-identical
off/on -- confirms the NaN-fallback path (`has_concentration` check in
`compute_entry_fill`) works correctly; `bandar_mult` stays neutral when
there's no real data rather than doing something undefined. Real
disclosed tradeoff, same standard as every prior promotion: window 3
(2023 H1, already the known historically-weak window) gets a slightly
worse profit factor and marginally deeper single-window drawdown.

**Result would clear the same bar `LIQ_SIZING_ENABLED` cleared for
default-ON promotion.** User's explicit call, though: **not promoting
yet.** Keep `BANDAR_SIZING_ENABLED` off, do not wire the live
paper-trading path (`paper_monitor.py`), and continue deepening
Bandarmology itself (more scrutiny, more features, the frontend) before
any aggregation with the live algorithm -- "sampai bener2 gak ada lagi
yang perlu dikerjain." Revisit promotion only when explicitly asked.

### Pair-level Layer 1: mover/rotation/cluster pairs forward-return tested (2026-08-12)

Biggest remaining gap after validating the daily features: `mover_pairs`,
`rotation_pairs`, `cluster_pairs` were pure structural/co-occurrence
flags, never checked against actual forward returns. Built
`diagnose_bandarmology_pairs_power.py` -- one EVENT-DAY definition per
table (movers: broker acting in its own historically-predicted
direction; rotation: both brokers active on OPPOSITE sides that day;
cluster: both brokers active on the SAME side), then compares mean
forward return on event days vs all other days for the SAME stocks (own
baseline, controls for stock-level differences), 3 subperiods, same
discipline as every other check.

Real bug found and fixed en route: `is_event` came out of a left-merge
as object dtype (NaN in the unmatched rows forces pandas to box the
column), so `~sub["is_event"]` did Python bitwise-NOT on the boxed
bools (`~True == -2`, `~False == -1`) instead of logical negation --
crashed immediately with a nonsense KeyError. Fixed with an explicit
`.astype(bool)` after `.fillna(False)`.

| pair type | wins/9 | verdict |
|---|---|---|
| `mover_pairs` | **9/9** | Passes cleanly. Largest effect size of anything tested this session -- 20d horizon, period 3: event mean +6.34% vs baseline +3.88% (n=33,376 event rows). The split-half-correlation selection method (already an anti-fluke filter by construction) turns out to carry real, substantial forward-return information beyond the selection artifact. |
| `rotation_pairs` | **9/9** | Also passes cleanly, no reversal anywhere. Smaller effect sizes than movers (e.g. 20d period 3: +5.52% vs +4.16%) but consistent across all 9 checks. |
| `cluster_pairs` | 6/9 | **Fails the bar.** Reverses at ALL THREE horizons in period 3 (2025-06-03..2026-08-11) -- same full-subperiod-reversal pattern that disqualified `net_flow_norm`/`concentration` in their weak window. A real, structurally-sound co-occurrence pattern (same-side brokers moving together), but not a validated forward-return signal as currently defined. Don't present as validated; fine to keep shipping as insight-only (per the "two consumers" split), not as anything score-worthy. |

**Net result: `mover_pairs` and `rotation_pairs` join `concentration` as
validated Bandarmology signals. `mover_pairs` specifically now looks
like the strongest single Bandarmology feature found all session** --
stronger than the daily `concentration` feature currently wired into
the (not-yet-promoted) V4 sizing multiplier. Worth designing a
`mover_pairs`-based V4 candidate in a future round, same discipline
(off by default, full walk-forward before any promotion) -- not started
yet, per the explicit "keep enhancing before aggregating" instruction.

### mover_pairs V4 sizing candidate: strongest RAW signal, weaker SIZING multiplier (2026-08-12)

Built `MOVER_SIZING_ENABLED` (`backtest_v3.py`, off by default, separate
flag from `BANDAR_SIZING_ENABLED` so each feature's own contribution
stays isolable): `mover_score` = count of flagged `mover_pairs` brokers
acting in their own historically-predicted direction that stock-day,
merged in via `attach_mover_signal()` (reuses the backtest's own
already-fetched price history for candidate-mover selection, avoiding a
second slow per-stock Supabase fetch). Same NaN-vs-0 handling as
`concentration` (missing data stays NaN/neutral; confirmed-zero-signal
days are a real 0, not "unknown").

9-window walk-forward, isolated test (BANDAR_SIZING left off so this
result is `mover_score`'s own effect, not combined with `concentration`):

| metric | off (baseline) | mover_score on |
|---|---|---|
| Windows beating bench | 6/9 | 5/9 (worse) |
| Mean alpha | +21.71% | +16.44% (worse) |
| Median alpha | +12.60% | +18.69% (better) |
| Mean profit | +20.84% | +15.58% (worse) |
| Median profit | +2.96% | **-1.48% (flips negative)** |
| Mean profit factor | 1.58 | 1.85 (better) |
| Median profit factor | 1.12 | **0.96 (below breakeven)** |
| Mean max drawdown | -16.08% | -15.02% (better) |
| Worst max drawdown | -21.61% | -20.76% (better) |

**Genuinely mixed, not a clean win like `concentration`.** Despite
`mover_pairs` being the STRONGEST raw forward-return signal found all
session (the pair-level Layer 1 check above, 9/9, biggest effect size
of anything tested), it makes a weaker SIZING multiplier -- mean/median
profit and alpha get worse even though drawdown/CVaR improve. Likely
cause: `mover_score` is an integer count with a typically-small
train-derived p90 (often 1-2), so the resulting multiplier is bimodal/
discontinuous (many days snap straight to the 2.0x cap on >=2 movers,
others sit at exactly 1.0x, zero-mover days clip down to 0.5x) rather
than the smooth continuous percentile `concentration` produces --
compounded by small per-window trade counts (23-99), where a handful of
oversized/undersized positions swing the aggregate a lot.

**Real, useful negative result -- exactly why this V4-level check
exists on top of Layer 1, not a redundant step.** A feature can be the
strongest *predictor* in isolation and still make a poor *sizing input*
once real fees, TP1/trailing exits, and portfolio mechanics are in
play. Not pursuing this specific formulation further right now; a
future redesign (e.g. magnitude-weighted instead of a raw count, or a
smoother percentile-based transform matching `concentration`'s
approach) could fix the discontinuity, but that's follow-up work, not
this round. `MOVER_SIZING_ENABLED` stays off, not promoted, same hold
as `BANDAR_SIZING_ENABLED`.

### User domain knowledge, cross-checked against real data (2026-08-12)

User shared real trading-floor knowledge -- broker-conglomerate
affiliations, a claimed 2025 "turning point" where retail codes (XL/CC/
XC/MG/YP) became dominant movers (possible bandar hiding inside retail
accounts, undetectable without per-trade execution-size access), the
"tuker barang" mechanics, a real example (unnamed here) of a beneficial
owner quietly buying back shares for months with zero price movement
until deciding to "terbangin" the stock, and detailed character
profiles for 10 broker codes (MG/AK/BK/YP/CC/NI/PD/YU/XL/XC).
Explicitly asked for this to be cross-checked against real data before
ever being shown to end users, not taken as ground truth -- "ini hanya
POV saya pribadi."

**Confirmed, strongly:**
- **AK-BK "tandem" claim.** Directly queried `bandarmology_cluster_pairs`
  for the AK-BK pair: shows up as a flagged same-side cluster in **41
  different stocks**, lift 1.5-2.0 (e.g. WMPP lift=2.03, PADI lift=1.8,
  WSKT lift=1.78). This is a strong, concrete confirmation -- exactly
  what "tandem" would look like in this data.
- **Retail-app churn pattern.** `avg_turnover_to_net_ratio` from
  `broker_characteristics`: YP=2.03, XL=2.29, XC=1.50, CC=1.82 (elevated,
  more two-sided/churny days) vs AK/BK/DH/LG/MG/NI/RB/SQ/YU all sitting
  at exactly 1.0 (predominantly one-sided days). Supports the "YP/XL/XC
  are busy retail scalper/FOMO hubs" characterization reasonably well.
- **YU commodity/regional-speculative claim, partially.** Top YU-flagged
  stocks include ELTY (Bakrieland Development -- literally a Bakrie Group
  entity), DKFT (nickel mining), ZINC (metal mining), CNKO (coal-adjacent)
  -- real presence, but mixed in with non-commodity names (BIRD, TSPC,
  RDTX at the very top) -- partial support, not a clean sweep.

**NOT confirmed by current data -- don't present these as validated:**
- **LG-ENRG** (Thohir claim): LG doesn't appear in `mover_pairs` for
  ENRG at all. ENRG's actual flagged movers are IF/DX/AG/YJ/PS.
- **SQ-BBCA** (Djarum/BCA claim): zero rows, SQ never flagged as a
  BBCA mover. Plausible reason below.
- **DH-Sinarmas, RB-Salim** (group-level claims): top DH/RB-flagged
  stocks by active_days (DH: TRIS/GWSA/DYAN/INOV/MIDI/BPTR/WIDI/SMKM/
  PTBA/MGLV; RB: IMAS/BMBL/MSIE/TAXI/BCAP/YELO/MARI/RAFI/DYAN/PIPA)
  don't obviously match the named conglomerate ecosystems -- PTBA is
  BUMN (state-owned), MIDI is a different group entirely; IMAS is
  plausibly Indomobil-adjacent but the rest are unclear. Caveat: this
  session doesn't have a verified conglomerate-to-ticker mapping to
  check against, so "doesn't match the top-10 by active_days" is as far
  as this check goes -- not a definitive refutation, just "not
  confirmed by what we can currently check."

**The important insight this surfaces, methodological, not just a
scorecard:** `mover_pairs` is built on SHORT-term (5-day) return-
predictive correlation. The user's own point #3 -- a beneficial owner
quietly accumulating for months with **zero price movement** ("bikin
sahamnya sideways... gak bisa cuan") until deciding to move the stock
-- describes a pattern that, BY CONSTRUCTION, cannot show up in a
detector built to find brokers whose net flow predicts near-term price
moves. Quiet, long-horizon, non-price-moving accumulation is close to
invisible to a short-horizon correlation test almost by definition.
This is the most likely explanation for why LG-ENRG/SQ-BBCA/DH-Sinarmas/
RB-Salim don't show up: `mover_pairs` may simply be the wrong tool to
detect a house broker's quiet structural accumulation, not evidence
those relationships aren't real. **A genuinely different, not-yet-built
detector is needed for that pattern specifically** -- long-horizon
persistent net-buying regardless of short-term price impact, tested
against LONG (multi-month) forward outcomes rather than 5/10/20-session
ones. Distinct from `consistency` (which measured short-horizon
persistence and failed Layer 1) -- this would be a genuinely new
hypothesis, not a rerun of a already-failed one. Not built this round.

**2025 "turning point" claim** (retail codes became dominant movers,
possible bandar disguised as retail, undetectable without per-trade
execution size which this project doesn't have access to): not checked
yet -- would need a before/after 2025 split on mover_pairs/dominant-
broker-type composition, flagged as a follow-up, not done this round.

### Autonomous follow-up round (2026-08-12, user AFK ~1hr): long-horizon test + 2025-split check, both honest negatives

**Long-horizon "quiet accumulator" test, first operationalization,
FAILS -- and reverses.** Built `diagnose_bandarmology_long_horizon.py`:
reused `bandarmology_features.rolling_features`'s own `window` parameter
to compute `consistency`/`net_flow_norm` at a 60-trading-day window
(vs. the original 10d) and tested against 60/90/120-session forward
returns (vs. the original 5/10/20d). Result: `long_consistency` scored
**1/9** -- and not just weak, INVERTED in periods 2-3, by a large
margin (120d, period 3: top quantile +15.8% vs bottom quantile
**+59.8%** -- low-consistency stocks massively outperformed high-
consistency ones). `long_net_flow_norm` also failed (2/9, 0/9, 2/9
across horizons). **Real methodological lesson, not just "hypothesis
wrong":** this tested AGGREGATE market-wide 60-day consistency across
ALL brokers combined -- a fundamentally different question from "does a
SPECIFIC flagged mover broker's persistent activity predict long-
horizon returns," which is what the user's actual story described (one
beneficial owner's broker, not the whole market's aggregate behavior).
The right test would extend `mover_pairs`' own broker-specific
correlation framework to a long horizon, not blunt-instrument aggregate
consistency. Not built this round -- flagged as the correct next
attempt, not a dead end.

**"2025 turning point" claim (retail codes XL/CC/XC/MG/YP allegedly
becoming dominant movers), checked via mover_pairs composition --
doesn't confirm.** Built `diagnose_bandarmology_2025_split.py`: split
mover-pair detection into two fully independent windows (pre:
2023-01-02..2024-12-30, 2549 candidates; post: 2025-01-02..2026-08-11,
2591 candidates) and compared the five retail codes' combined share of
all flagged movers. **6.6% pre-2025 -> 6.0% post-2025 -- flat, if
anything slightly down.** The two biggest COMPOSITION shifts were LG
(3.3%->4.0%, staying #1) and YU (not in the pre-2025 top 10 -> #2
post-2025 at 3.9%) -- both institutional/foreign-leaning codes per the
domain research, not retail. **This doesn't confirm the retail-
dominance hypothesis via this structural lens** -- but it also can't
rule out the user's actual mechanism (bandar disguising trades as
retail-sized activity), which is explicitly unobservable without
per-trade execution size, something this project doesn't have access
to, exactly as the user caveated when raising it. Same "wrong tool for
the job" pattern as the long-horizon test above: absence of evidence in
a correlation-based structural detector isn't evidence of absence for a
claim about disguised execution mechanics.

**Both honest negative results, written up as such -- not hidden
because they didn't confirm the hypothesis.** Consistent with this
project's whole discipline: a negative result that closes off a wrong
path is exactly as valuable as a positive one that opens a right path.

### Frontend page built (2026-08-12, newscraper.ai)

`/bandarmology` route live in the newscraper.ai repo (nav entry added,
"Bandarmology" label + Radar icon -- deliberately NOT reusing "Rotation",
already taken by `/konglo`'s unrelated conglomerate-RRG feature).
TypeScript typecheck passes clean (`npx tsc --noEmit`, exit 0). Two
sections:
- **Broker Explorer**: sortable/searchable table joining `brokers` +
  `broker_characteristics`, with the staleness badge the design doc
  required (computed_at -> "N hari lalu", flags itself once >30 days
  stale -- monthly refresh cadence, not a bug).
- **Per-stock lookup**: ticker search (`?ticker=` URL param, shareable
  links) showing that stock's flagged movers (color-coded bullish/
  bearish by the mover's own predicted-direction sign), rotation pairs,
  cluster pairs, and a cumulative-flow area chart (`components/
  bandarmology/flow-chart.tsx`, dataviz-skill-reviewed: single series so
  no legend needed, colored by current-sign using the site's existing
  --profit/--loss tokens, not new hues).

**Blocked on one thing, cannot self-resolve:** the page reads from a
NEW second Supabase client (`lib/supabase-broker.ts`, DB2 --
`ptuvkgleurjcniznveye`) that needs `NEXT_PUBLIC_SUPABASE_BROKER_URL` and
`NEXT_PUBLIC_SUPABASE_BROKER_ANON_KEY` in `.env.local`. Only have DB2's
service-role key (backend-only, must never go in a `NEXT_PUBLIC_` var --
that would expose full write access client-side). Structure/types/UI
are real and typecheck-clean; **cannot verify against live data or
screenshot it working until the anon/public key is supplied** (Supabase
dashboard -> broker project -> Settings -> API -> anon public key).
Explicitly not tested in a browser yet -- flagging this rather than
claiming it works.

### Corrected long-horizon test: broker-specific persistence PASSES (2026-08-12)

Immediate follow-up to the failed aggregate-consistency attempt above --
`diagnose_bandarmology_long_horizon_movers.py` extends
`bandarmology_broker_profile.py`'s own validated per-(stock,broker)
split-half-correlation methodology (already proven 9/9 at a 5-day
horizon) out to 60/90/120-session horizons instead, rather than testing
blunt aggregate market consistency.

| horizon | candidates | wins/3 |
|---|---|---|
| 60d | 2,468 | **3/3** |
| 90d | 2,564 | **3/3** |
| 120d | 2,571 | **3/3** |

**9/9 total, cleanly passes.** Confirms the methodological diagnosis
was right: the FIRST long-horizon attempt failed because it tested the
wrong thing (whole-market aggregate behavior), not because the
underlying "persistent broker activity predicts long-horizon returns"
idea was wrong. Broker-specific persistence carries real signal at
every tested horizon from 5 sessions out to 120 -- the single most
robust Bandarmology finding across the whole session, now validated at
4 different horizon scales (5d already via the original mover_pairs
check, plus 60/90/120d here) using the same core methodology throughout.
Not wired into anything (same hold on aggregation as everything else)
-- but this is the strongest evidence yet that `mover_pairs`' underlying
approach (not just its original 5-day parameterization) is the right
shape for a Bandarmology feature, and reinforces treating `mover_pairs`
as the lead candidate for whenever V4 integration resumes.

## Open questions (resolve once real data exists, not before)

- Exact rolling window length (10d vs 20d vs adaptive) -- tune against
  real backfilled data, don't guess now.
- Score thresholds for the categorical buckets -- same, needs real
  distribution of the features first.
- Whether `investor_type` (Foreign/Local/BUMN) enters the score directly
  or only as a display filter/grouping on top of the per-broker features
  above -- leaning toward the latter per the user's point that type is a
  coarse prior, not the real signal.
