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
   already in `src/backtest_v4.py`/V3, don't reinvent); (b) consistency --
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

Built `BANDAR_SIZING_ENABLED` (`backtest_v4.py`, default OFF): a
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

Built `MOVER_SIZING_ENABLED` (`backtest_v4.py`, off by default, separate
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

### Directional Big/Small Accumulation/Distribution classifier -- gap found, redesign started (2026-08-15)

User's explicit V4 request (2026-08-12 message, "detect accumulation/distribution big or small, based on transactions, for V4, regardless the minimum lack of full data"): revisited after re-reading this doc + `attach_mover_signal()` closely rather than starting a fresh Phase-1 validation (that work is already done, exhaustively, above -- redoing it would waste the existing evidence).

**Real gap found in the current `mover_score` (`backtest_v4.py:558-606`), not previously documented:** the event condition is `sign(net_lot) == predicted_sign` -- this fires equally for a broker with NEGATIVE `predicted_sign` net-SELLING today (a bearish-predicting event) as for a broker with POSITIVE `predicted_sign` net-BUYING (bullish-predicting). Both increment the same unsigned `mover_score` count. **`mover_score` is not directional** -- it measures "how many flagged movers are acting true to their own historical pattern today," not Accumulation vs Distribution. This is a second, previously-undiagnosed candidate explanation for the "genuinely mixed" `MOVER_SIZING_ENABLED` walk-forward result (line 669-718 above), alongside the already-documented bimodal-integer-count discontinuity.

**Proposed fix, addresses both known problems at once:**
```
signed_score = sum(predicted_sign * |net_val|)  # per (stock_code, trade_date), over qualifying events
```
- Signed: positive = net Accumulation-predicting activity, negative = net Distribution-predicting.
- Magnitude-weighted + continuous: fixes the small-p90 bimodal-count discontinuity the same way `concentration`'s percentile transform already does.
- Big/Small buckets: train-derived percentiles of `signed_score`, same pattern as every other feature in this doc (no hand-picked thresholds before real distribution data).

**Plan**: build as a new isolated flag (own name, not merged into `BANDAR_SIZING_ENABLED` or `MOVER_SIZING_ENABLED`, same isolation discipline as every prior feature here so each one's own contribution stays measurable), full 9-window walk-forward, off vs on, same promotion bar as everything else in this doc. Dispatched to a quant-analyst pass; results to be appended here once back, honest either way (a real negative result is exactly as valuable as a positive one, per this doc's own established standard).

### ACCDIST_SIZING_ENABLED built + isolated walk-forward: fixes MOVER's specific symptom, still doesn't clear the bar (2026-08-15)

Built `attach_accdist_signal()`/`_accdist_aggregate()` (`backtest_v4.py`), wired as `ACCDIST_SIZING_ENABLED` (env `V3_ACCDIST_SIZING`, default OFF, own `ACCDIST_SIZING_MIN`/`_MAX` bounds, 0.5/2.0 same as the other two multipliers). Reuses `attach_mover_signal()`'s exact candidate-mover detection (`per_broker_daily`/`candidate_movers`/`_bandar_add_forward_returns`, same `predicted_sign` derivation) -- only the aggregation step changed, per the plan above: `accdist_score = sum(predicted_sign * |net_val|)` over the same qualifying events (`sign(net_lot) == predicted_sign`), instead of an unsigned count. Same NaN-vs-0 semantics as `mover_score`/`concentration` (pre-coverage dates NaN, post-coverage merge-misses a real 0). `compute_entry_fill`'s `accdist_mult` reuses the identical `min(MAX, max(MIN, value/train_p90))` clip formula `bandar_mult`/`mover_mult` already use -- the directionality comes entirely from `accdist_score` itself being signed (a Distribution-dominated train day divides out negative and clips straight to the 0.5x floor; a strong Accumulation day scales toward the 2.0x cap), not from new branching logic. Added `src/test_accdist_signal.py` (assert-based, no Supabase/Parquet needed) covering the three behaviors that actually differ from `mover_score`: a bullish and bearish qualifying event on the same stock-day net to a signed sum (not an unsigned count of 2); a sign-mismatched event is excluded, not flipped; a stock/day with no flagged movers produces no row (the NaN-vs-0 boundary is `attach_accdist_signal`'s job one layer up, not the aggregator's).

**Side-finding while regenerating the cache, unrelated to this feature's own result:** the local Parquet backfill (`data/bandarmology_history/`) now has real data back to 2020-06-02 (file mtimes 2026-08-13/14), not 2023-01-01 as this doc's "Local historical backfill" section still states -- extended by someone/something between the last cache build (2026-08-12) and this session, not documented elsewhere. Patched the existing `.cache/walk_forward_data_2021-01-01_2026-06-30.pkl` in place (loaded the pickle, ran `attach_accdist_signal()` against it, re-saved -- no Supabase refetch, no `SUPABASE_URL`/`KEY` needed or available in this environment) rather than a full rebuild; confirmed the OFF baseline reproduces the exact previously-recorded numbers below byte-for-byte after the patch, so the patch itself didn't disturb anything. One real consequence: `accdist_score` has 0 NaN rows across the whole cached df (full 2020-2026 coverage), while `concentration`/`mover_score` in the same cached df still show their original NaN gaps before 2023-01-02 (computed before the backfill was extended) -- harmless for this isolated test specifically (their multipliers are gated off regardless of data presence when their own flags are off), but flagging so a future combined-feature run doesn't assume all three columns share one coverage start.

9-window walk-forward, isolated test (`BANDAR_SIZING`/`MOVER_SIZING` both off, so this isolates `accdist_score`'s own contribution):

| metric | off (baseline, reproduced byte-identical) | accdist_score on |
|---|---|---|
| Windows beating bench | 6/9 | 6/9 (same count, different windows -- W6 drops out, W1 joins) |
| Win rate >50% | 4/9 | 4/9 (same count, different windows -- W1 drops out, W4 joins) |
| Mean alpha | +21.71% | +17.02% (worse) |
| Median alpha | +12.60% | **+20.32% (better)** |
| Mean profit | +20.84% | +16.15% (worse) |
| Median profit | +2.96% | **+16.77% (better, stays solidly positive)** |
| Mean profit factor | 1.58 | **1.91 (better)** |
| Median profit factor | 1.12 | **1.50 (better, stays above breakeven)** |
| Mean max drawdown | -16.08% | -16.06% (~flat) |
| Worst max drawdown | -21.61% | -26.92% (worse) |

**Genuinely mixed, same as `MOVER_SIZING_ENABLED` -- but the specific failure mode is different, and the fix does what it was designed to do on one axis.** `MOVER_SIZING_ENABLED`'s damning symptom was the median flipping negative (median profit +2.96%->-1.48%, median PF 1.12->0.96, below breakeven) despite decent means -- the signature of a bimodal, discontinuous-integer-count multiplier. `accdist_score` does not reproduce that: median profit and median profit factor both improve substantially and stay clearly positive/above breakeven (continuous, magnitude-weighted sizing behaving as intended). But it introduces a different problem -- mean alpha/profit both get worse and worst-case drawdown gets meaningfully worse (-21.61%->-26.92%), traced almost entirely to one window (W8, 2025 H2: baseline's best window by far at +129.13% profit/-20.55% drawdown on 96 trades collapses to +53.04%/-26.92% on 84 trades under ACCDIST sizing) -- one exceptional baseline window getting sized down/fewer-filled dominates the mean-level metrics even though per-window alpha actually improved in 6 of 9 windows (W1, W2, W4, W5, W7, W9) and only worsened in 3 (W3, W6, W8). Win rate itself moved against the feature in 5/9 windows (worse in W1/W2/W3/W6/W8, better in W4/W5, flat in W7/W9), though the two headline gate counts (beats-bench, win-rate>50%) land at the identical 6/9 and 4/9 as baseline, just via a different set of windows.

**Verdict: does not clear this doc's promotion bar.** Both headline window-counts are unchanged from baseline (not an improvement), and the worst single-window drawdown gets materially worse -- real tail-risk cost, not just noise, concentrated in the one window that was carrying most of the baseline's average return. The magnitude-weighted signed redesign is a real, targeted fix for the specific mechanism diagnosed in `MOVER_SIZING_ENABLED`'s post-mortem (median/PF no longer collapse below breakeven), which is useful evidence the diagnosis was right -- but fixing that one mechanism didn't turn this into a net-positive sizing input on its own. `ACCDIST_SIZING_ENABLED` stays off, not promoted, same hold as `BANDAR_SIZING_ENABLED`/`MOVER_SIZING_ENABLED`. Not pursuing further this round; a plausible next step (not started) would be investigating W8 specifically -- which broker/stock combinations drove the sizing shrinkage that turned a +129% window into +53%, and whether that reflects the classifier correctly downsizing genuine distribution-flagged positions or an artifact of the multiplier's clip bounds -- before trying any parameter sweep on `ACCDIST_SIZING_MIN`/`_MAX`.

### CORRECTION 2026-08-15: the 2026-08-15 accdist_score result above is invalidated by a real bug, not a real finding

Critic pass (same "investigate then critique" discipline as everything else this session) found the "mixed" verdict above rests on a broken percentile threshold, not the intended magnitude-weighted design. `accdist_score` is exactly 0 on ~92% of stock-days (no qualifying candidate-mover event) -- so `train.quantile(0.90)` lands at exactly 0.0 in **all 9 windows**, tripping the degenerate-guard fallback (`if p90 <= 0: p90 = 1.0`) 100% of the time, not occasionally as that guard was meant for. Since `accdist_score` is Rupiah-scaled (~1e8-1e11), dividing by the fallback constant `1.0` instantly saturates the clip: verified against all 1,242,246 rows, **0.00% land strictly between the 0.5x/2.0x bounds** -- 96.2% clip to exactly 0.5x, 3.8% to exactly 2.0x. It degenerated into a binary sign switch, not the continuous magnitude-weighted redesign this was built to test. The aggregation formula itself (`sum(predicted_sign * |net_val|)`) was independently re-verified correct (`test_accdist_signal.py` passes, `_accdist_aggregate` logic confirmed) -- the bug is entirely in the train-derived scaling step, not the signal computation. The prior table's numbers are real (independently reproduced), but they tested an accidental binary switch, not the design -- do not cite that table as evidence about magnitude-weighted accdist sizing either way. Fix: percentile must be computed over NONZERO accdist_score days only (or an equivalent robust scale that isn't dominated by the zero-mass), then rerun. Not yet fixed -- next step.

**Side-finding resolved**: the "local backfill now starts 2020-06-02" note above is not an extended/complete backfill -- confirmed live source data exists back to at least 2020-01-06 (direct curl against Indopremier, real 10-broker rows returned), but the local Parquet folder has zero files for Jan-May 2020. This is an incomplete partial run someone else started outside this session, not a completed extension -- answers the very first question of this session ("kok backfill loncat ke 2020-06-02, bukan Januari") honestly: it's not done yet, not a mystery. Re-running the backfill for Jan-May 2020 would close the gap; not done as part of this round, flagged for whenever Bandarmology work resumes (still not done in this round either -- `bandarmology_historical_backfill.py` takes a `<year>` argument and queries Supabase directly for the trading-day list/stock universe, and this environment has no live `SUPABASE_URL`/`SUPABASE_KEY` -- not runnable here, not just deprioritized).

### Fix applied + rerun 2026-08-15: threshold corrected, multiplier confirmed continuous, walk-forward verdict unchanged (for a different, now-legitimate reason)

**Fix** (`backtest_v4.py`, new `_accdist_score_p90()` helper, replacing the inline `train.quantile(0.90)` at the old call site): restrict to TRAIN days where `accdist_score != 0` (an event actually happened), then take `.abs().quantile(0.90)` of that subset -- magnitude-based, always positive regardless of the accumulation/distribution mix in the train window, immune to the zero-mass. `concentration_p90`/`mover_score_p90` don't need this treatment because `concentration` is computed from `daily_stock_features(per_broker_net(raw))` -- every actively-traded stock-day gets a value, no "candidate mover" gate -- while `accdist_score`/`mover_score` both require a broker to be flagged as a historically-predictive mover for that specific stock AND act in its predicted direction that specific day, a much narrower intersection. Degenerate fallback (`p90 = 1.0` if no nonzero training days exist at all) kept for the genuine edge case.

**Confirmed the fix, not just asserted it.** Old (buggy): `accdist_score_p90 = 1.0` in all 9 windows (verified in the correction above). New: `accdist_score_p90` ranges Rp 707,990,000 -- Rp 1,000,000,000 across the 9 windows -- a real, positive, Rupiah-scale reference, not the degenerate fallback. `test_accdist_signal.py` gained a direct unit test for `_accdist_score_p90()` (a mostly-zero fixture that reproduces the exact bug -- plain `quantile(0.90)` lands at 0.0 -- then confirms the fixed function returns a positive magnitude scale instead; plus the genuine all-zero/empty edge case still falls back to 1.0). Then checked the actual multiplier distribution two ways:
- **Among the population capable of ever landing off the floor** (nonzero `accdist_score` days, n=101,153, evaluated against all 9 windows' train-derived p90, n=910,377 window-observations): **3.95% now land strictly between 0.5x/2.0x**, vs the verified **0.00%** under the bug. 93.06% still clip to the 0.5x floor and 2.99% to the 2.0x cap -- expected, not a residual bug: roughly half of nonzero `accdist_score` values are negative (Distribution-predicting), and the ratio-clip formula floors *any* negative value regardless of magnitude by design (same as `bandar_mult`/`mover_mult`'s formula shape). The fix's job was only to stop the zero-mass from forcing a degenerate denominator -- confirmed done.
- **At real trade fills** (instrumented `compute_entry_fill` directly during the actual 9-window walk-forward, 285 total entries): **283/285 (99.3%) still land at exactly 0.5x, 1 at 2.0x, 1 strictly between.** This is the honest caveat: `accdist_score` is exactly 0 (a real "no event," not "distribution") on the entry day for the specific stock the strategy actually entered, for nearly every real trade -- and 0 divided by any positive scale floors to 0.5x whether that scale is the broken 1.0 or the fixed ~7-10e8. The screener's entry signal (`weekly_ma_spread`/`sector_rs_momentum`) and `accdist_score`'s candidate-mover-event population are two independently narrow filters that rarely intersect on the same stock+day. This is a structural sparsity limit on this multiplier's practical reach, not something the threshold fix could address -- and it explains the next finding.

9-window walk-forward, isolated test (`BANDAR_SIZING`/`MOVER_SIZING` both off), fixed threshold:

| metric | off (baseline, unaffected by this fix -- flag-gated, reproduces prior byte-identical) | accdist_score on (FIXED threshold) |
|---|---|---|
| Windows beating bench | 6/9 | 6/9 (same windows as the buggy run: W6 drops out, W1 joins) |
| Win rate >50% | 4/9 | 4/9 (same windows as the buggy run: W1 drops out, W4 joins) |
| Mean alpha | +21.71% | +16.31% (worse) |
| Median alpha | +12.60% | +18.31% (better) |
| Mean profit | +20.84% | +15.44% (worse) |
| Median profit | +2.96% | +17.40% (better, stays solidly positive) |
| Mean profit factor | 1.58 | 1.90 (better) |
| Median profit factor | 1.12 | 1.65 (better, stays above breakeven) |
| Mean max drawdown | -16.08% | -15.25% (~flat) |
| Worst max drawdown | -21.61% | -25.06% (worse) |

**This table is numerically close to the buggy run's table** (mean alpha 17.02%->16.31%, median alpha 20.32%->18.31%, mean profit 16.15%->15.44%, median profit 16.77%->17.40%, mean PF 1.91->1.90, median PF 1.50->1.65, mean DD -16.06%->-15.25%, worst DD -26.92%->-25.06%), and reproduces the exact same per-window beat/win-rate membership. That's consistent with, not contradicted by, the fill-level finding above: since 283/285 real fills floor to 0.5x under *both* the broken and the fixed threshold (because their `accdist_score` is 0, not because of the bug), fixing the denominator could only have changed the outcome for the tiny number of fills where `accdist_score` was actually nonzero that day -- which is exactly what happened.

**Verdict: still does not clear this doc's promotion bar -- same headline gate counts unchanged from baseline, worst-case drawdown still meaningfully worse.** But this is now a real, verified result about the corrected design, not an artifact -- the multiplier itself is confirmed no longer a binary switch among the rows capable of expressing it, and the aggregation formula's earlier independent verification (`test_accdist_signal.py`) stands unchanged. The reason fixing the bug barely moved the backtest outcome is a separate, genuine finding: this sizing input is a near-no-op for real trades not because of a threshold bug but because a same-day, same-stock bandarmology event essentially never coincides with this particular screener's entry signal. `ACCDIST_SIZING_ENABLED` stays off, not promoted. A next step for anyone continuing this (not started): a rolling/lookback version of `accdist_score` (e.g. trailing N-day sum, the way `mover_pairs`' validated long-horizon persistence result -- see above -- already suggests broker behavior matters over weeks, not just the entry day) would shrink the sparsity gap `concentration` doesn't have, before any further MIN/MAX bound sweep on a same-day-only version of this feature.

### ROTATION_SIZING_ENABLED: rotation_pairs V4 sizing candidate -- same mixed/sparse shape as accdist_score, not promoted (2026-08-15)

Fourth, independent Bandarmology V4 sizing candidate, following the exact
isolation discipline as `BANDAR_SIZING_ENABLED`/`MOVER_SIZING_ENABLED`/
`ACCDIST_SIZING_ENABLED` before it: `rotation_pairs` was the other feature
that passed Layer 1's pair-level forward-return check 9/9 with no reversal
(see "Pair-level Layer 1" above) but had never been tried as a sizing input
-- this round designs and tests that.

**Event/score design -- UNSIGNED, unlike accdist_score.** Re-read the
Layer 1 event definition carefully before assuming the signed pattern
carries over: the test that validated `rotation_pairs` used "both brokers
in a flagged pair active on OPPOSITE sides that day" -- a symmetric
condition. `bandarmology_rotation_detector.find_rotation_pairs()` stores
`broker_a`/`broker_b` sorted alphabetically with no `predicted_sign` the
way `candidate_movers()` attaches one to each mover -- which broker buys
vs. sells on any given day is not part of what got flagged, and the Layer 1
test itself didn't care which side was which, only that the pattern fired.
Treating this as directional (accdist-style) would have invented a
market-direction call the underlying detector and its own validation don't
support. Designed instead as a magnitude/participation signal: per
(stock_code, trade_date), `rotation_score = sum(min(|net_val_a|,
|net_val_b|))` over every flagged pair active on opposite sides that day --
the overlap value (Rupiah) each side's net position could plausibly have
absorbed from the other, summed across every flagged pair active for that
stock, unsigned by construction (always >= 0). Implemented as
`_rotation_aggregate()`/`_rotation_score_p90()`/`attach_rotation_signal()`
in `src/backtest_v4.py`, wired as `ROTATION_SIZING_ENABLED` (env
`V3_ROTATION_SIZING`, default OFF, own `ROTATION_SIZING_MIN`/`_MAX` = 0.5/2.0,
same bounds as the other three). `src/test_rotation_signal.py` covers the
aggregation logic (opposite-side vs. same-side vs. one-side-only-active,
unsigned output, empty-pairs edge case) and the sparsity-aware threshold
(mirrors `test_accdist_signal.py`'s mostly-zero fixture).

**Sparsity checked empirically before assuming, per the accdist lesson --
confirmed real, applied the nonzero-percentile fix from the start.**
`rotation_score` is nonzero on only 9.02% of stock-days (112,099 of
1,242,246 rows in the full cached dataset) -- not as extreme as
`accdist_score`'s ~92% zero-mass, but the same failure mode would still
apply (`train.quantile(0.90)` over a 91%-zero population lands well inside
the zero-mass). `_rotation_score_p90()` was built nonzero-only from the
start rather than discovering the bug after the fact.

**Real operational finding along the way, unrelated to the signal's own
merit: `find_rotation_pairs()` does not finish in practical time against
the current local backfill.** Its per-(stock, day) pair-counting step is a
pure-Python O(k^2) nested loop over that day's active broker codes (k up to
~90 for the most liquid names); against the now-six-year local Parquet
history (extended to 2020-06-02, see the 2026-08-15 accdist correction's
side-finding) it ran 65+ minutes without finishing and was killed -- it was
fast enough on the smaller 2023-2026 slice the detector script's own prior
runs used, just doesn't scale to the larger history now on disk. Fix:
`attach_rotation_signal()` sources the flagged PAIRS from DB2's already-
computed `bandarmology_rotation_pairs` table (4,438 rows, paginated fetch,
~1s) instead of recomputing `find_rotation_pairs(raw)` in-process --
justified by this doc's own framing of that table as a slow-moving,
monthly-refreshed structural artifact ("CORRECTION 2026-08-12" above:
"mover/rotation/cluster patterns are slow-moving... don't need daily
refresh"), not something that needs a fresh local recompute per backtest
run. Only the pair-level flags come from DB2; the per-day EVENT data (which
stock-days actually saw opposite-side activity) is still computed entirely
from the local Parquet `broker_net`, same as every sibling signal. Confirmed
this doesn't affect the live paper-trading path either way: `data/` is
gitignored, so in CI `bf.load_raw()` raises immediately and
`attach_rotation_signal()` takes the fast NaN fallback regardless of DB2 --
identical to `attach_mover_signal`/`attach_accdist_signal`'s existing
behavior there. `bandarmology_rotation_detector.py` itself was not modified.

**Multiplier distribution sanity check (same discipline as the accdist
fix round) -- confirmed not degenerate, but real fills mostly floor
anyway, same structural sparsity story as accdist_score:**
- **Population level** (nonzero `rotation_score` rows, n=112,099,
  evaluated against all 9 windows' train-derived p90, n=1,008,891
  window-observations): train p90 ranges Rp 4.7B-13.7B across the 9
  windows -- a real, positive, always-computed Rupiah scale, never the
  degenerate fallback. **3.46% land strictly between 0.5x/2.0x**, 93.50%
  floor, 3.04% cap -- the floor-heavy shape is expected given `rotation_score`
  is compared against its own 90th percentile (most nonzero days are well
  under that magnitude), not a bug.
- **At real trade fills** (instrumented `compute_entry_fill` during the
  actual 9-window walk-forward, 285 total entry attempts -- same count as
  the accdist check, expected: entry-signal generation is identical
  regardless of which downstream sizing multiplier is toggled):
  **281/285 (98.6%) floor to exactly 0.5x, 1 (0.4%) caps to 2.0x, 3 (1.1%)
  land strictly between.** Only 32/285 (11.2%) of real fills had a
  genuinely nonzero `rotation_score` for that specific stock+day -- nearly
  identical to `accdist_score`'s 99.3%-floor finding, and the same root
  cause: a flagged-pair opposite-side event essentially never coincides
  with the specific stock+day this screener's weekly/sector-momentum entry
  rule actually fires on. Practical consequence: in this portfolio's real
  trade set, `ROTATION_SIZING_ENABLED` behaves close to (not literally, per
  the population-level check above) a blanket "halve most position sizes"
  toggle rather than the graded participation signal it was designed to
  express.

9-window walk-forward, isolated test (`BANDAR_SIZING`/`MOVER_SIZING`/
`ACCDIST_SIZING` all off, so this isolates `rotation_score`'s own
contribution). Baseline reproduced byte-identical to every prior recorded
run in this doc (confirms the DB2-sourced patch didn't disturb anything
when the flag is off):

| metric | off (baseline, byte-identical) | rotation_score on |
|---|---|---|
| Windows beating bench | 6/9 | 6/9 (same count, different windows -- W6 drops out, W1 joins) |
| Win rate >50% | 4/9 | 4/9 (same count, different windows -- W1 drops out, W4 joins) |
| Mean alpha | +21.71% | +16.41% (worse) |
| Median alpha | +12.60% | **+18.42% (better)** |
| Mean profit | +20.84% | +15.54% (worse) |
| Median profit | +2.96% | **+17.40% (better, stays solidly positive)** |
| Mean profit factor | 1.58 | **1.90 (better)** |
| Median profit factor | 1.12 | **1.67 (better, stays above breakeven)** |
| Mean max drawdown | -16.08% | -15.00% (~flat, slightly better) |
| Worst max drawdown | -21.61% | -25.05% (worse) |

**Verdict: does not clear this doc's promotion bar -- and the shape is
close to a repeat of `ACCDIST_SIZING_ENABLED`'s result, not a new
finding.** Same headline gate counts (6/9 beat-bench, 4/9 win-rate>50%)
unchanged from baseline, just different window membership. Median
profit/alpha/PF all improve and stay clearly positive/above breakeven
(continuous magnitude-weighted sizing behaving as designed, not the
bimodal-count collapse `MOVER_SIZING_ENABLED` showed) -- but mean-level
metrics get worse and worst-case drawdown gets meaningfully worse
(-21.61%->-25.05%), traced to the same window as the accdist finding: W8
(2025 H2, baseline's best window by far) shrinks from +129.13%
profit/-20.55% drawdown/96 trades to +41.92%/-25.05%/103 trades. Per-window
alpha actually improved in 7/9 windows (W1, W2, W3, W4, W5, W7, W9) and only
worsened in 2 (W6, and W8 by a large margin, -87.21pp) -- the mean-level
regression is concentrated almost entirely in how much W8 alone carries the
baseline's average, same dynamic as every other Bandarmology sizing
candidate tested this session. `ROTATION_SIZING_ENABLED`
stays off, not promoted, same hold as `BANDAR_SIZING_ENABLED`/
`MOVER_SIZING_ENABLED`/`ACCDIST_SIZING_ENABLED`. Consistent with, not
contradicted by, `accdist_score`'s prior finding: **two independently
designed Bandarmology sizing candidates (one signed/directional, one
unsigned/magnitude) now show the same structural ceiling** -- the
underlying signals may carry real information (both passed Layer 1 9/9),
but same-day, same-stock candidate-mover/rotation-pair events rarely
coincide with this specific screener's entry day, so the sizing multiplier
mostly degenerates to a near-constant floor at real fills regardless of how
the raw feature is designed. The rolling/lookback redesign flagged at the
end of the accdist section above (a trailing N-day sum instead of
same-day-only) would very plausibly help this feature too, for the same
reason -- not attempted this round.

### BANDAR_SIZING_ENABLED promoted to default ON (2026-08-15)

Three follow-on candidates (`MOVER_SIZING_ENABLED`, `ACCDIST_SIZING_ENABLED`,
`ROTATION_SIZING_ENABLED`) all failed to clear this doc's promotion bar for
the same structural reason: same-day, same-stock candidate-mover/rotation
events rarely coincide with this screener's own entry day, so the
multiplier degenerates toward a near-constant floor at real fills.
`concentration` doesn't share that sparsity problem -- it's computed for
every actively-traded stock-day, which is exactly why it was the one
candidate that cleared the bar back on 2026-08-12 (see that section
above). User explicitly asked to revisit promotion now that the
alternatives are exhausted.

**Change**: `BANDAR_SIZING_ENABLED`'s default flipped from
`os.environ.get("V3_BANDAR_SIZING", "0") == "1"` to `"1"` (`backtest_v4.py`)
-- env var override kept intact in both directions, only the default
changed.

**Final confirm walk-forward** (same 9-window schedule/cache as the
2026-08-12 validation, rerun after this session's three new sizing flags
landed -- MOVER/ACCDIST/ROTATION all still default OFF, so this isolates
BANDAR_SIZING's own effect exactly as before):

| metric | off (baseline) | on |
|---|---|---|
| Windows beating bench | 6/9 | 6/9 |
| Win rate >50% | 4/9 | 4/9 |
| Mean alpha | +21.71% | +24.09% |
| Median alpha | +12.60% | +19.09% |
| Mean profit factor | 1.58 | 1.88 |
| Mean max drawdown | -16.08% | -15.03% (better) |
| Worst max drawdown | -21.61% | -21.84% (slightly worse) |

**Byte-identical to the 2026-08-12 record in every cell.** Windows 1-2
(pre-Bandarmology-data 2022) still byte-identical off/on, confirming the
NaN-fallback path is unaffected by anything that changed this session.
No discrepancy to explain -- the three new flags' own code paths are
fully inert when their own env vars are unset.

**Live-wiring status: already fully wired, nothing new to build.**
Traced the entire live path end to end before touching anything:
- `paper_signal_scan.py` calls `bt.build_full_dataset()`, which already
  calls `attach_bandarmology()` unconditionally (not gated behind the
  flag) -- local Parquet first, DB2's `bandarmology_flow_daily` fallback
  second via `_fetch_concentration_from_db2()` (confirmed the `concentration`
  column exists there, `sql/bandarmology_flow_daily_schema.sql` line 28).
  GitHub Actions runners have no local Parquet, so this fallback is what
  actually executes live -- it was built and working since the 2026-08-12
  session, just never previously exercised because the flag was off.
- `score_candidates()` already returns `concentration` in every signal
  dict (`backtest_v4.py:1081`); `paper_signal_scan.py` already persists it
  onto the `PENDING` `paper_positions` row (line 408) and already persists
  `concentration_p90` onto `paper_account` (line 460).
- `paper_monitor.py` already reads `concentration_p90` back off
  `paper_account` and `concentration` off the `PENDING` row, and already
  calls `compute_entry_fill(..., concentration_p90=concentration_p90)`
  (lines 142, 189, 193) -- which already branches on the module-level
  `BANDAR_SIZING_ENABLED` constant.
- V4_PAPER's own trigger workflow (`paper_signal_scan_v4_trigger.yml` /
  `paper_monitor_v4_trigger.yml`, on `main`) has set `V3_BANDAR_SIZING: '1'`
  explicitly since 2026-08-12 -- V4_PAPER has been trading with
  Bandarmology sizing live the whole time. The default flip changes
  nothing observable for V4_PAPER; it was already effectively on.

**Real consequence of the default flip, caught before shipping: it would
have silently changed V3_PAPER too.** `BANDAR_SIZING_ENABLED` is a shared
module-level constant with no per-run override outside the env var.
V3_PAPER's own live workflows (`paper_signal_scan_trigger.yml`,
`paper_monitor_trigger.yml`, on `main`) never set `V3_BANDAR_SIZING` --
they rely entirely on the module default, precisely because V4_PAPER was
split off as an isolated attribution run so V3_PAPER could stay untouched
("V3 = V3_PAPER's EXACT frozen config plus exactly ONE change", see the
2026-08-12 section). Flipping the shared default without also pinning
V3_PAPER's own workflows would have been exactly the kind of silent
frozen-config mutation this project's own governance rule forbids -- new
capital allocation logic changing under a run that never opted in.
**Fix**: pinned `V3_BANDAR_SIZING: '0'` explicitly in both of V3_PAPER's
`main`-branch trigger workflows, so V3_PAPER's entry-fill sizing stays
byte-identical going forward. V3.1_PAPER's workflows were left unpinned
on purpose -- it stopped opening new positions entirely on 2026-08-14
(see that section above), so `BANDAR_SIZING_ENABLED`'s value is
categorically unreachable for it: `paper_signal_scan.py`'s
`stop_new_entries` check skips the whole candidate-generation block
before `compute_entry_fill` is ever called for that run. Confirmed by
inspection, not just assumed.

Added `src/test_bandar_sizing_default.py`: confirms the default is ON
with the env var unset, confirms explicit `'0'`/`'1'` still override in
both directions (via a real subprocess re-import, not just re-reading the
same cached module), and confirms `compute_entry_fill()` actually sizes a
high-concentration signal up when the flag is on vs off -- not just that
the flag flips, but that the flip reaches the sizing math.

Not touched, per explicit instruction: `MOVER_SIZING_ENABLED`,
`ACCDIST_SIZING_ENABLED`, `ROTATION_SIZING_ENABLED` all remain default
OFF, unpromoted.

### `broker_summary_history` designed + prepared, DDL blocked (2026-08-16)

User pushed back on the frontend's "no history, single-day-only" framing
of the Broker Summary table (`ca11dfc`, 2026-08-15) -- believed 90 days
were already stored. True for `bandarmology_broker_flow_daily`, false for
`broker_summary` itself: reconfirmed directly, `select count(distinct
trade_date) from broker_summary` = 1 (2026-08-14, 15,113 rows). Unlike the
abandoned 2026-08-12 `broker_summary_history` attempt (dropped that day,
sized wrong the first time), this round has a real precedent to copy:
`bandarmology_broker_flow_daily`'s already-live sync-function + pg_cron
pattern (see `newscraper.ai/docs/ROADMAP.md`, "per-broker daily flow" --
that table's own SQL was never checked into this repo either, applied
directly via migration).

**Designed and checked in, not yet applied**: `sql/broker_summary_history_schema.sql`
(table, same raw per-broker/per-side granularity as `broker_summary`,
composite PK doubles as the lookup index, one extra `trade_date` index for
the daily prune -- narrower than the abandoned attempt per its own "one
fewer index" lesson) + `sql/sync_broker_summary_history_fn.sql`
(`sync_broker_summary_history()`, a straight copy-then-prune, simpler than
`sync_broker_flow_daily()` since this table doesn't aggregate/net --
registers `sync-broker-summary-history` at `35 11 * * *`, 5 min after the
sibling job so it doesn't race `broker_summary`'s own n8n write window).

**Size re-derived from real data, not the earlier session's guess**: dry-ran
`src/broker_summary_history_backfill.py`'s own file-selection logic against
the real local Parquet archive -- the exact 90-calendar-day window ending
2026-08-11 is 57 trading days / 874,627 rows (~15,344 rows/day, closely
matching `broker_summary`'s live 15,113/day and cross-validating both
numbers). A full window floats ~60-65 trading days depending on the
holiday calendar, ~920K-1.0M rows -- notably less than a naive
90-calendar-days-as-if-every-day-trades estimate (1.36M). At the abandoned
2026-08-12 attempt's own measured bytes/row for this exact granularity
(~109-126 bytes/row, trimmed schema, real backfilled data), that's
~100-126MB. DB2 was ~108MB/500MB as of 2026-08-14 (dominated by
`bandarmology_broker_flow_daily`'s live 90-day window, ~70MB/618K rows,
reconfirmed via count this round) -- landing around ~210-235MB/500MB
total, comfortable. 90 days kept, not widened.

**Backfill feasible from local Parquet, not just seed-forward**: the
archive's schema (`stock_code, broker_code, side, lot, val_rupiah,
avg_price, trade_date`) maps exactly to what `broker_summary_history`
needs -- confirmed against the real archive (1,489 files,
2020-06-02..2026-08-11, three trading days behind `broker_summary`'s own
live 2026-08-14, an ordinary freshness lag not a gap).
`src/broker_summary_history_backfill.py` selects the last 90 calendar days
of files, batches a `Prefer: resolution=merge-duplicates` upsert via
`requests` + the service-role key, same shape as
`bandarmology_push_daily.py`. Self-check (`--self-check`, no network) and
a dry run against the real archive both pass -- the script is ready to
run the moment the table exists, not run yet.

**Genuinely blocked, not shipped**: the DDL itself could not be applied
this round. The dispatched session had no MCP Supabase tool access
despite the task's premise that it would (5 distinct tool-name attempts
across both DB2 and DB1 projects all returned "no such tool," a stable
not-registered error, not an auth failure) -- had the DB2 service-role key
(sufficient for REST-level reads/writes on *existing* tables, which is
how the row-count/Parquet verification above happened), but PostgREST has
no DDL endpoint by design, and there was no Postgres connection string or
Supabase Management API token available to reach one another way.
Checked whether an existing RPC could substitute (introspected the
OpenAPI spec with the service-role key): only `refresh_bandarmology_flow_daily`
and `sync_broker_flow_daily` are callable, no generic SQL executor exists.
**Next step, ~5 minutes once DDL access exists**: apply the two SQL files
above (MCP `apply_migration` or the dashboard SQL editor), run the
backfill script once, then verify the frontend end-to-end against a real
non-latest day.

Frontend (`newscraper.ai/components/bandarmology/broker-summary-table.tsx`)
was rebuilt regardless and IS safe to ship on its own: queries
`broker_summary_history` for a per-ticker horizon and shows a single-day
Popover+Calendar picker when history exists, but falls back cleanly to
the original single-latest-day `broker_summary` view (no picker, no
error) when the history table has nothing for a ticker -- verified via
Playwright against a real dev server (BBCA) to render identically to the
pre-existing card with zero new console errors, both before this table
exists. `npx tsc --noEmit` and `npm run build` both clean. Also found +
fixed a real, live bug while reusing `BrokerFlowChart`'s date-picker
pattern for this: its `toDateStr()` round-tripped a picked Date through
`.toISOString()` (UTC), which for Jakarta (UTC+7) silently shifted every
custom-picked date back one day in the query actually sent to Supabase --
the button label (formatted straight from the Date, no round-trip) showed
the correct date the whole time, so this was invisible in normal use.
Fixed in both files.

## Open questions (resolve once real data exists, not before)

- Exact rolling window length (10d vs 20d vs adaptive) -- tune against
  real backfilled data, don't guess now.
- Score thresholds for the categorical buckets -- same, needs real
  distribution of the features first.
- Whether `investor_type` (Foreign/Local/BUMN) enters the score directly
  or only as a display filter/grouping on top of the per-broker features
  above -- leaning toward the latter per the user's point that type is a
  coarse prior, not the real signal.
