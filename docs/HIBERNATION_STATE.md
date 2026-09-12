# Hibernation state — 2026-09-12

The system is being left to run unattended. This file is the starting point for
whoever picks it up, whenever that is.

Read this first, then `CLAUDE.md` (both branches), then
`docs/POST_HIBERNATION_STUDIES.md` for anything that touches the algorithm.

Every claim below is marked **VERIFIED** (with the evidence) or **NOT
VERIFIED**. Nothing is marked done on the strength of intent.

---

## 1. Can it run on its own?

**Yes — with one P0 to close before sealing, and a dead-man's switch now in
place for the failures nobody would otherwise see.**

### The clock it runs on

| Time (WIB) | What | Where |
|---|---|---|
| 09:00–17:59, every 15 min | `ihsg_realtime` scrape; also **dispatches the V4 paper monitor** | n8n `eZD9l8Ch1juESJdg` |
| 17:30 | `ihsg_eod` | n8n `q4SqvDFolc7CmnZV` |
| 18:00 | `broker_summary` | n8n `UL3afVcCwYOaEPFn` |
| 18:00/18:30 | disclosures | n8n `IhRCa2NKOrjHdfom` |
| 18:10 | **V4_PAPER signal scan** | GitHub Actions `paper_signal_scan_v4_trigger.yml` |
| 19:00 | prune + refresh `disclosures_flat` + refresh `corporate_action_split` | pg_cron `refresh-disclosures-flat` |

Order matters: the 18:10 scan needs that day's `ihsg_eod` already in place.

**VERIFIED 2026-09-12** — every table current to 2026-09-11, the last trading
day:

| Table | Latest | Rows |
|---|---|---|
| `ihsg_eod` | 2026-09-11 | 1,291,370 |
| `daily_scoreboard` | 2026-09-11 | 9,341 |
| `daily_qualifying_signals` | 2026-09-11 | 300 |
| `disclosures_flat` | 2026-09-11 17:40 | 1,711 |
| `news_items` | 2026-09-12 08:07 | 1,081 |
| `broker_summary` (DB2) | 2026-09-11 | 15,374 |
| `bandarmology_flow_daily` (DB2) | 2026-09-11 | 161,883 |

### P0 - the GitHub PAT inside n8n

**Raised from "known issue" to P0 on the owner's call, 2026-09-12.** If this
token expires, n8n's own run still succeeds, GitHub never hears from it, and
**open positions stop being checked against their stop and target with no
alarm.** That is a real-money failure during a period when nobody is looking.

**ANSWERED BY THE OWNER, 2026-09-12: the token was created with NO EXPIRATION
DATE, deliberately.** This file previously carried an open action asking for
that date, because the expiry could not be read from here - extracting the
credential from the n8n workflow was blocked by the environment's permission
classifier, correctly, since it is a credential read. The question is now
closed, and the risk it described has changed shape rather than gone away.

**What that removes.** There is no clock. The token will not silently lapse
mid-hibernation, which was the specific failure this section was written
around. Good: that was the single most likely silent failure, and it is off the
table.

**What it leaves.** A non-expiring credential sitting in cleartext in an
internet-facing n8n node, readable by a plain API GET, for as long as the
system runs. The failure mode flips from *"it stops working"* to *"if it ever
leaks, it never stops working for whoever has it"* - and with `Actions: write`
on this repo, whoever has it can dispatch workflows against the trading engine.
There is no revocation clock to limit that window.

**The owner has accepted this risk explicitly and it is his to accept.** One
change would keep the convenience and remove most of the blast radius, if he
ever wants it: make the token **fine-grained, scoped to `ApekTahua/Neira` only,
with `Actions: write` and nothing else**, still with no expiry. Same
never-breaks property, far smaller reach if it leaks. Better still, move it out
of the node parameter into an n8n credential so a workflow GET stops returning
it at all - flagged 2026-09-01, still not done.

#### How to check and rotate it

*(Kept because a token with no expiry can still be revoked, scope-changed, or
edited out of the node by accident - "no expiry" is not "cannot fail".)*

1. **Check it is still alive.** In n8n, open workflow `eZD9l8Ch1juESJdg`
   (*15 Min Inject ihsg_realtime*), then the `Trigger Paper Monitor` node at the
   end, then *Execute node*. A `204` is healthy; `401` means the token is dead.
   Do not copy the token out of the node - it is stored there in cleartext, so
   anything it is pasted into becomes a secret too.
2. **Check GitHub's side instead, which is safer.** Actions ->
   *[Every 15 Min] - Paper Trading V4 Intraday Monitor* -> confirm
   `workflow_dispatch` runs are still appearing every ~15 minutes on trading
   days. Those dispatches are n8n. Their absence is the symptom.
3. **Rotate.** Create a fine-grained PAT scoped to `ApekTahua/Neira` only, with
   *Actions: write* and nothing else. Paste it into the node's `Authorization`
   header as `Bearer <token>`. Save, then **deactivate and reactivate** the
   workflow - a schedule change does not take effect otherwise.
4. **Better than rotating: stop storing it in the node.** Move it into an n8n
   credential so a plain workflow GET stops returning it in cleartext. This was
   first flagged 2026-09-01 and has not been done.

#### Mitigation that IS in place

Partly. Two things reduce the blast radius, and neither removes the need to
rotate the token.

- **The V4 monitor has its own GitHub cron.** `paper_monitor_v4_trigger.yml`
  carries `cron: '*/15 2-4,6-8 * * 1-5'`, so it does not depend solely on the
  n8n dispatch. The n8n path exists because GitHub delays or drops scheduled
  runs under load - it is a second path, not the only one. **VERIFIED** by
  reading the workflow. So a dead PAT degrades the cadence rather than stopping
  it outright. It is still a fault worth an alarm.
- **A dead-man's switch now exists**, and it still earns its place even with
  the expiry question closed. PAT expiry was the failure it was designed
  around, but it was never the only one it catches: the three signals below
  fire on the n8n EOD job dying, on the 18:10 scan not finishing, and on the
  monitor stopping for **any** reason - a revoked or scope-changed token, an
  n8n outage, a Stockbit `buildId` break, a GitHub Actions incident, or a
  crash in the script itself. `.github/workflows/hibernation_watchdog.yml`
  (on `main`, branch `ops/hibernation-watchdog`) plus
  `src/hibernation_watchdog.py` (here). Daily at 19:30 WIB, on **GitHub's own
  schedule** so it cannot die in the outage it reports, it checks three things
  and sends Telegram on any fault:

  | Signal | Catches |
  |---|---|
  | newest `ihsg_eod` row vs today (>3 days) | n8n's 17:30 EOD job dying |
  | newest `daily_scoreboard` row vs newest EOD | the 18:10 scan not finishing - invisible from the site, which just shows yesterday |
  | age of the last **successful** `paper_monitor_v4_trigger` run on a trading day (>24h) | the monitor no longer being called, PAT expiry included |

  The scoreboard signal was checked rather than assumed: `daily_scoreboard` is
  written by `paper_signal_scan.py:520`, and **only V4's scan still has a
  schedule** - `paper_signal_scan_trigger.yml` and `paper_signal_scan_v31_trigger.yml`
  both have their cron removed. So a fresh scoreboard row proves V4's own 18:10
  scan ran, not merely that something did.

  It reads the Actions API with the workflow's own `GITHUB_TOKEN`, never the
  n8n PAT. It runs its decision logic through a self-check before trusting it,
  and it alerts if it cannot reach the database rather than exiting clean and
  looking healthy - a watchdog that goes quiet when it breaks is worse than
  none. `python src/hibernation_watchdog.py --selftest` passes.

  **UNTESTED: the alert path itself.** The self-check covers the decision
  logic only. The Telegram send and the Actions API call have never been
  exercised - their credentials are GitHub secrets, unavailable from the
  machine this was written on. A watchdog whose alarm has never been heard is
  the exact failure it was built to prevent, so **on the first manual run,
  confirm a message actually arrives** before trusting it. The `if: failure()`
  step is the one to watch: it fires on any fault, so a deliberately broken run
  (or simply reading the Actions log) proves the path end to end.

  **What it deliberately does not use:** `paper_positions.updated_at`. That
  looked like the obvious liveness signal and is not one - the column defaults
  to `now()` but has **no trigger**, and `paper_monitor.py` never writes it on
  its per-poll `day_high`/`day_low` update. **Measured 2026-09-12:** OPEN rows
  last stamped 2026-09-10 17:45, a **40.9-hour** gap, on a system that was
  working correctly. An alarm built on that column would have cried wolf on day
  one and been muted by day three.

### Other things that will break quietly

1. **Stockbit's `buildId`.** `ihsg_realtime` scrapes a Next.js data API whose
   build hash changes when Stockbit redeploys. The workflow re-scrapes it and
   caches it in `app_scrape_state`, so it usually self-heals — but a site-wide
   scrape failure is almost always a stale `buildId`, not credentials or
   network. Check that before anything else.
2. **The 15-minute sweep takes ~14.5 minutes.** Measured 818–914s against a
   900s interval, scraping all 985 stocks with a 0.1s throttle. Runs nearly
   touch. A given stock's `updated_at` can lag the run start by up to ~15 min,
   so `ihsg_realtime` is a rolling sweep, not a snapshot. Do not read all its
   rows as same-instant data.

### What already alerts by itself

- `ihsg_eod`'s n8n job ends in an `If` → Telegram node ("No EoD Data") that
  fires when a day's scrape comes back empty.
- `paper_signal_scan_v4_trigger.yml` posts to Telegram on failure.

Do not build monitoring on top of these without checking them first.

### The holdout clock

**V4_PAPER has 11 closed positions** (plus 4 open, 2 pending) — VERIFIED
2026-09-12 by joining `paper_positions` to `backtest_runs`. The gate for
unfreezing the config is **60 closed**. At the observed rate (11 closed in the
31 days since 2026-08-12) that is roughly **five more months**. Nothing should
touch the frozen config before then, and the system has to keep running
unattended for that whole period for the holdout to mean anything.

#### Two problems with the gate itself, raised 2026-09-12, NOT resolved

**(a) Nothing announces when 60 is reached.** No job counts closed positions
and says so. During an unattended period the gate will be crossed in silence,
and the only way anyone learns is by opening the site and counting. The
watchdog already queries Supabase daily, so adding the count is a few lines -
deliberately **not** added without the owner's word, because the seal was
already approved when this was noticed.

**(b) 60 may be the wrong number.** The measured edge is a tail property:
P(+25% over 20 sessions) of **16.4%** against **7.5%** for a random liquid
stock. Treating that as a one-sample test against the fixed 7.5% baseline, at
alpha 0.05:

| closed positions | statistical power | expected tail events |
|---|---|---|
| 11 (today) | 28% | 1.8 |
| **60 (the gate)** | **68%** | **9.8** |
| 87 | 80% | 14.3 |
| 120 | 89% | 19.7 |

**60 positions carries roughly a one-in-three chance of missing a real edge.**
80% power needs about **87**. And that arithmetic is optimistic twice over: it
assumes the 7.5% baseline is known exactly rather than estimated, and it
assumes 60 independent draws - but the same tickers recur constantly (SOCI was
listed on 20 of 22 trading days), so the effective independent sample is
smaller than the count. If the gate were instead graded against a **concurrent
control arm** rather than a fixed baseline, it would need about **207 per arm**.

This does not mean the gate is wrong to exist - it is far better than promoting
on the 262-times-reused historical windows. It means **60 is strong enough to
rule an idea OUT and weak enough that failing to clear it is not evidence of no
edge.** Whoever resumes should decide deliberately whether to hold at 60 or
extend to ~87, and should write that decision down before looking at the
results, not after.

---

## 2. What was done this session

| Change | Where | SHA | State |
|---|---|---|---|
| T-7 phase 1 — split/reverse-split adjustment layer | Neira | `1bdd401` | merged into `worktree-v2-hmm-screener` (`a845f74`), pushed |
| Honest note that live ACLs are wider than the file's grant line | Neira | `bd17857` | merged, pushed |
| Version-control the two views that only existed live | Neira | `4c0d7c9` | merged (`c8e5a87`), pushed |
| T-14 — `TRAIL_ATR` fails loud on the live path | Neira | — | already merged before this session |
| Prune migration reproduces the live function exactly | newscraper.ai | `f712802` | **branch pushed, NOT merged** |
| Plain-language sweep across every page | newscraper.ai | `41ba06c` | **branch pushed, NOT merged** |
| New-signal badge, retired-version labels, trend-only risk | newscraper.ai | `7a24284` | **branch pushed, NOT merged** |
| This file + `POST_HIBERNATION_STUDIES.md` | Neira | this commit | branch `docs/hibernation-closeout` |

### MERGE ORDER MATTERS — read before clicking

`.github/workflows/hibernation_watchdog.yml` lives on `main` and runs
`src/hibernation_watchdog.py`, which it checks out from
`worktree-v2-hmm-screener`. **Merge the script first.** If the workflow lands on
`main` while the script is not yet on the work branch, its first scheduled run
fails at the self-check step and sends a Telegram alert — loud rather than
silent, which is the intended failure mode, but it is avoidable noise.

Correct order:

1. `Neira` → `docs/hibernation-closeout` into `worktree-v2-hmm-screener`
   (carries `src/hibernation_watchdog.py` and both documents)
2. `Neira` → `ops/hibernation-watchdog` into `main` (the workflow)
3. `newscraper.ai` → `ui/plain-language-sweep` into `main`
4. `newscraper.ai` → `audit/sql-repo-reproduces-live` into `main`

3 and 4 are independent of each other and of 1-2; they touch different files in
a different repo. After step 2, trigger the watchdog once by hand
(Actions → *[Daily 19:30 WIB] - Unattended Health Watchdog* → *Run workflow*)
and confirm it reports healthy rather than waiting for the first 19:30 run.

### Branches awaiting a merge

The GitHub CLI is not authenticated in this environment and reading a stored
credential is blocked, so **no pull request object could be opened from here**,
and the merge into `newscraper.ai`'s `main` was blocked as well. The branches
are pushed and ready; merging them is a manual step:

| Repo | Branch | Head | Carries |
|---|---|---|---|
| Neira | `docs/hibernation-closeout` | `8857199` | the watchdog script, `HIBERNATION_STATE.md`, `POST_HIBERNATION_STUDIES.md` |
| Neira | `ops/hibernation-watchdog` | `9b66d61` | the watchdog workflow (branched from `main`) |
| newscraper.ai | `ui/plain-language-sweep` | `2fd29e3` | the plain-language sweep and every UI change |
| newscraper.ai | `audit/sql-repo-reproduces-live` | `f712802` | the prune migration, byte-identical to live |

Build state at those heads: `tsc --noEmit` clean, `next build` clean on all 16
routes, re-run after the final commit. Verified against the **branch heads**,
not against a merged `main` — the merges could not be performed from here.

### T-7's out-of-order deployment — closed

The matview and cron went live before the PR existed. Rather than roll them
back, the repo was **proven to reproduce live**, which is the stronger of the
two remedies:

| Check | Result |
|---|---|
| `pg_get_viewdef('corporate_action_split')` repo vs live | **true** |
| `pg_get_viewdef('stock_split_factor')` repo vs live | **true** |
| `corporate_action_split_pk` unique index | present |
| `security_invoker=on` on `stock_split_factor` | present |
| cron command on `refresh-disclosures-flat` | matches the file |

Method: the repo file was replayed into a scratch schema and the two
definitions compared with schema qualifiers normalised away; the scratch schema
was then dropped. `pg_get_viewdef` equality is the right standard here, not a
text diff — Postgres normalises SQL, so a text diff produces false alarms.

**One real mismatch, deliberately not fixed.** The file says
`grant select ... to anon, authenticated, service_role`; live the objects carry
`arwdDxtm` for `anon`. The cause is not this migration —
`pg_default_acl` on this project grants ALL on tables in `public` to
anon/authenticated/service_role, and that fires at CREATE before the explicit
grant. `disclosures_flat`, `market_marquee`, `signal_base_rate` and
`stock_price_limit` all carry the identical ACL. Narrowing one object right
before an unattended period would be an untested inconsistency; the extra
privileges are inert anyway (Postgres rejects all DML on a materialized view,
and `stock_split_factor` is not auto-updatable — UNION ALL plus window
functions). Listed under known issues below.

---

## 3. Ticket status — every open item, no blanks

### Done

| Ticket | Status | Evidence |
|---|---|---|
| **T-7 phase 1** | **DONE** | 75 events (73 splits, 2 reverse), 147 factor rows, 72 stocks, worst snap confidence 0.9921. 66 raw cliffs >50% → 0 adjusted. `src/test_split_adjustment.py` passes all four checks. `ihsg_eod` untouched — the raw cliffs are still there in the source. |
| **T-14** | **DONE** | `strict_atr` parameter; only `paper_monitor.py` passes `True`. Owner raised this from INFERRED to VERIFIED. |
| **T-16** (tier drift) | **DONE, re-verified today** | One definition in `components/shared/confidence-badge.tsx`, used by Screener, Paper Trading and the Bandarmology panel. Grep for the old literals across `app/` and `components/` returns nothing. |
| **T-8 type half** | **DONE** | `ignoreBuildErrors: false`, build verified. |
| **FE-2 (RATU)** | **DONE — no change was correct** | Three independent sources put RATU under Hapsoro via RAJA (68.68%); Prajogo's CDIA is an explicit minority. Acting on the instruction would have deleted the correct entry. Owner retracted. |

### Deferred, with the reason

| Ticket | Why it is not done |
|---|---|
| **T-1** (realistic-fill flags) | The capital-scaling gate, and the last item by design. Needs the 60-closed-position holdout first. |
| **T-12 follow-up** (fee-inclusive `pnl_pct`) | Ships **with** T-1 or not at all. Making `pnl_pct` fee-inclusive now would move every already-published live number while the holdout is open, which `HOLDOUT_PROTOCOL.md` forbids. The slipped-price half is already in and is a provable no-op while `V4_SLIPPAGE` is off. |
| **/saved** | **DECIDED 2026-09-12 — keep it, with the per-device disclaimer.** The owner accepted the recommendation. The page stores the price at the moment of saving, so it answers "what has this done since I got interested" — the only page that can. Disclaimer now appears in two places: on the page, and on the Save button itself at the moment of clicking. No accounts, so cross-device is out of scope. |
| **T-8b** (ESLint) | **P2, open, deferred — NOT resolved.** This project has no ESLint config at all, so `ignoreDuringBuilds: true` is masking "no config", not masking findings. Order: add `next/core-web-vitals`, fix what it surfaces, *then* flip the flag. Owner's explicit adjudication: do not record this as closed. |
| **T-18** (`SCORE_NORM="train_sd"`) | Needs pre-registration plus a 3-partition walk-forward. It is not a patch. → **S-3**. |
| **T-7 phase 2** (rights issues) | 31 events; ratios cannot be inferred from price and must be read from filings. → **S-4**. |
| **T-7 phase 2b** (use the factors) | The factor table exists and is live but nothing consumes it. → **S-5**. |
| **FE-3** (BUMI in two groups) | **HOLD, confirmed by the owner 2026-09-12: do not touch before hibernation without the ownership check.** BUMI is listed under both Salim and Bakrie in `lib/konglo.ts`, so it double-counts across two equal-weight group indices — and it is far more liquid than RATU was, so it distorts harder. Needs the same two-source discipline RATU got. Salim did historically hold a large BUMI stake, so this is not obviously wrong in either direction. |
| **RATU under Prajogo Pangestu** | **DECIDED 2026-09-12 — remove, and already removed.** The owner ruled: groups are named per controlling individual, so the "affiliation" reading does not apply; RAJA's 68.68% is control and CDIA's 4.99% is below even the 5% disclosure threshold. `lib/konglo.ts` already carries the removal (done 2026-09-12) with the three-source evidence in a comment above it. **Verified today: RATU appears only under Happy Hapsoro. No further change needed.** |

### Supplied by the reviewer after the gap was reported — now on record

These nine came from the external (Kiro) audit, which was pasted into a
conversation and never committed to either repo. This session refused to give
them a status, because there was no committed source to check them against and
a plausible-sounding guess would have been worse than an admitted gap. **The
reviewer then supplied their contents directly (2026-09-12), and they are
recorded here so they cannot be lost again.**

Their titles and priorities are the reviewer's. **None of them has been
verified against the code by me**, and none may touch the frozen V4_PAPER
config. Every one is post-hibernation work.

| Ticket | Priority | What it says | Kind |
|---|---|---|---|
| **T-15** | P1 | The live daily drift threshold differs from the backtest's fixed-window one. Data is in `daily_scoreboard`; nobody has measured the gap. | measurement |
| **T-13** | P1 | Proxy high/low on the live path biases exit timing against the backtest. | measurement |
| **T-11** | P1 | The broker-sanity band (0.7 / 1.3 / 10×) was never calibrated. The fail-safe **direction** is already verified correct; only the thresholds are unjustified. | calibration |
| **T-10** | P1 | No attestation that the published live track record matches what actually happened. | integrity |
| **SQL-1** | P1 | The rolling Bandarmology window spans data gaps, so a window crossing a gap silently reads stale. | correctness |
| **phase0i** | P2 | The permutation significance test measures the **mean**, while this system's edge is in the **tail**. Legacy: it graded the wrong statistic. | legacy |
| **phase0-horizon** | P2 | `shift(-h)` steps by row, not by trading day. Minor, but it makes horizons uneven across gaps. | minor |
| **T-5** | P2 | The Telegram payload carries no position sizing and no gap-standdown notice. | completeness |
| **T-6b** | P3 | The `RISK_PCT` floor-clamp behaviour is undocumented. | documentation |

Two of these deserve a note beyond their one-liner:

- **phase0i** is the same trap `HOLDOUT_PROTOCOL.md` and S-1 both warn about,
  found in a different place: grading on the mean (or the hit rate) when the
  measured edge is the right tail. The median pick here is indistinguishable
  from random while the odds of a +25% run over 20 sessions are roughly doubled
  (16.4% vs 7.5%). Any re-run of that significance test should grade the tail.
- **T-11**'s framing is the useful part: the direction is verified and only the
  numbers are arbitrary. That makes it a calibration job with a known-safe
  fallback, not a redesign — cheaper than its P1 label suggests.

---

## 4. Known issues to watch while it runs alone

1. **The n8n PAT** (section 1) — the highest-probability silent failure.
2. **Live ACLs are wider than the repo's grant lines - TESTED, and RLS holds.**
   Section 2 flagged that `anon` carries `arwdDxtm` (which includes INSERT,
   UPDATE and DELETE) on every view and matview in `public`, against repo files
   that say `grant select`. The owner's question was the right one: is that
   actually reachable, or does RLS stop it? **Answered by probing the live REST
   API with the real anon key**, the same method as the 2026-09-03 audit:

   | Probe (as `anon`) | Result |
   |---|---|
   | `POST disclosure_summary_queue` - the one auto-updatable view | **blocked**, `42501` row-level security |
   | `POST ihsg_eod` | **blocked**, `42501` |
   | `PATCH disclosure_extracts` on a row anon **can** see, no-op value | **blocked**, 0 rows changed |
   | `DELETE disclosure_extracts` on a row anon **can** see | **blocked**, 0 rows deleted, row survived |
   | `POST corporate_action_split` (matview) | **blocked**, `42809` cannot change a materialized view |
   | `SELECT stock_split_factor` (control) | works, as intended |

   The first two probes of the session used filters matching **no rows**, and
   returned `200 []` - which means "zero rows", not "denied". Those were
   inconclusive and were re-run against real, anon-visible rows; only the
   re-runs above are evidence. The UPDATE and DELETE probes used a no-op value
   and a disposable row created and removed for the purpose, so no production
   data was at risk. Probe row cleaned up, verified `remaining: 0`.

   **Why it holds:** RLS is ON for every base table in `public`, and **every
   policy is `SELECT`-only** (17 policies, all `cmd = SELECT`) - Postgres denies
   a command with no matching policy, so the table-level grant never gets a
   chance to matter. All ten views carry `security_invoker=on`, so even the one
   auto-updatable view (`disclosure_summary_queue`) writes as the caller and
   hits the same RLS wall rather than the owner's privileges.

   **Verdict: the wide ACL is cosmetic, not a write hole.** It is still worth
   narrowing project-wide, because the protection currently rests entirely on
   RLS - the day someone adds a table and forgets `enable row level security`,
   the default ACL makes it anon-writable. That is a housekeeping ticket, not
   an open vulnerability.
3. **43% of recent filings cannot be read at all.** Measured 2026-09-12:
   `disclosure_extracts` is 1,341 `pdf_text` / 370 `failed`, no `ocr`. Of
   filings whose text extracted, **100% are summarised** (69 of 69 in the last
   30 days). The gap is extraction, not the model — "Gemini is underused" was
   the wrong diagnosis. `/disclosures` now states the ratio on the page
   instead of leaving the reader to notice.
4. **The signal list is one sector most days.** `sector_rs_momentum` is one
   identical value for every stock in a sector, so two of the five gates carry
   zero per-stock information. This is named on the page, not hidden, but it
   is the structural reason SOCI-type names persist.
5. **Everything published assumes a perfect fill.** `V4_SLIPPAGE` defaults
   off: no spread, no market impact, on exits that are market-on-close.
6. **The nine walk-forward windows are closed for promotion.** At least 262
   configurations have been graded against them. They can rule an idea out;
   they cannot let one in.
7. **UI is BUILD-VERIFIED, NOT EYE-VERIFIED.** The Playwright and Chrome
   DevTools MCP servers both failed to connect (`CONNECT_TIMEOUT`), so **no
   screenshot was taken of any change.** What was verified: `tsc --noEmit`
   clean across 29 app files, and a full `next build` clean on all 16 routes,
   re-run after the final commit. What was not verified: that anything looks
   right.

   This matters more than usual because the sweep replaced roughly 40
   user-visible strings, several of them **longer than what they replaced
   inside fixed-width grid cells** - exactly the class of regression a
   screenshot catches and a type-checker cannot. This project has already
   caught real visual bugs this way that grep and tsc both missed.

   **Check these first, in this order** - ranked by how many strings changed
   and how tight the layout is:

   | Page | Why it is the riskiest | What to look at |
   |---|---|---|
   | `/screener` | most strings changed; the level block is a 3-column grid of 10px uppercase labels | "First sell" / "Cut loss at" / "No fixed price" cells, the new-signal and Repeat badges wrapping beside the tier pill, the hold-days line |
   | `/stock/[ticker]` | gate checklist lines grew from 3-4 words to full sentences | "The whole market is rising" row, "First sell price" / "Cut loss at" grid, the live market-condition banner |
   | `/backtest` | exit badges went from 3-letter codes to phrases | exit pills in the trades table, the filter chips row (`Sold off the peak: 12 (4.1%)`), the retired-version notices |
   | `/paper-trading` | alert table column widths | the `Cut loss` / `First sell` / `Follows the price up` pills, "Now sells on / a fall from its peak" |
   | `/konglo` | SVG axis labels are positioned, not flowed | "Stronger than IHSG" and "Getting stronger" must stay inside the viewBox |
   | `/disclosures` | one new control | the "Major actions only" chip, and that the row count stays consistent when it is on |

   Everything else changed one or two labels and is low risk.

---

## 5. Where the study tickets live

`docs/POST_HIBERNATION_STUDIES.md` — S-1 through S-5, each with what prompted
it, what is already known, and what the pre-registration has to say. None of
them has been started. None of them may touch a live config without a
3-partition walk-forward first.
