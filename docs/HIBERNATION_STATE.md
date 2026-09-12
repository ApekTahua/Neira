# Hibernation state — 2026-09-12

The system is being left to run unattended. This file is the starting point for
whoever picks it up, whenever that is.

Read this first, then `CLAUDE.md` (both branches), then
`docs/POST_HIBERNATION_STUDIES.md` for anything that touches the algorithm.

Every claim below is marked **VERIFIED** (with the evidence) or **NOT
VERIFIED**. Nothing is marked done on the strength of intent.

---

## 1. Can it run on its own?

**Yes, with one hard dependency and two things that will go wrong silently.**

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

### What will break quietly

1. **Stockbit's `buildId`.** `ihsg_realtime` scrapes a Next.js data API whose
   build hash changes when Stockbit redeploys. The workflow re-scrapes it and
   caches it in `app_scrape_state`, so it usually self-heals — but a site-wide
   scrape failure is almost always a stale `buildId`, not credentials or
   network. Check that before anything else.
2. **The GitHub PAT inside n8n.** The `Trigger Paper Monitor` node carries a
   personal access token as a literal `Authorization` header value, so a plain
   workflow GET returns it in cleartext. It has not been moved into an n8n
   credential. **When it expires, the V4 monitor stops being dispatched and
   nothing announces it** — paper positions will simply stop being checked
   against their stop and target. This is the single most likely silent
   failure during hibernation.
3. **The 15-minute sweep takes ~14.5 minutes.** Measured 818–914s against a
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

### Branches awaiting a merge

The GitHub CLI is not authenticated in this environment and reading a stored
credential is blocked, so **no pull request object could be opened from here**,
and the merge into `newscraper.ai`'s `main` was blocked as well. The branches
are pushed and ready; merging them is a manual step:

- `newscraper.ai` → `ui/plain-language-sweep` (`7a24284`)
- `newscraper.ai` → `audit/sql-repo-reproduces-live` (`f712802`)
- `Neira` → `docs/hibernation-closeout`

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
| **T-8b** (ESLint) | **P2, open, deferred — NOT resolved.** This project has no ESLint config at all, so `ignoreDuringBuilds: true` is masking "no config", not masking findings. Order: add `next/core-web-vitals`, fix what it surfaces, *then* flip the flag. Owner's explicit adjudication: do not record this as closed. |
| **T-18** (`SCORE_NORM="train_sd"`) | Needs pre-registration plus a 3-partition walk-forward. It is not a patch. → **S-3**. |
| **T-7 phase 2** (rights issues) | 31 events; ratios cannot be inferred from price and must be read from filings. → **S-4**. |
| **T-7 phase 2b** (use the factors) | The factor table exists and is live but nothing consumes it. → **S-5**. |
| **FE-3** (BUMI in two groups) | BUMI is listed under both Salim and Bakrie in `lib/konglo.ts`. Held pending the same two-source ownership check RATU got. Salim did historically hold a large BUMI stake, so this is not obviously wrong. |
| **RATU under Prajogo Pangestu** | Owner's call, not a defect to fix unilaterally: either drop it, or keep it and state that a KONGLO group means affiliation rather than control. |

### Never verified — say so rather than guess

**T-5, T-6b, T-10, T-11, T-13, T-15, phase0i, phase0-horizon, SQL-1.**

These came from the external (Kiro) audit, which was pasted into a
conversation and never committed to either repo. They were not verified
against the code in that session and were not reached in this one. **I cannot
state what they contain from any committed source, so I am not assigning them
a status.** Whoever resumes should get the audit text from the owner first.
Do not treat their absence from the "done" list as evidence either way.

---

## 4. Known issues to watch while it runs alone

1. **The n8n PAT** (section 1) — the highest-probability silent failure.
2. **Live ACLs are wider than the repo's grant lines** (section 2). Inert, but
   if `public` ever gains a genuinely writable view, the default ACL will make
   it writable by `anon`. A project-wide pass is the right fix, not a
   per-object exception.
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
7. **Visual verification was not possible this session.** The Playwright and
   Chrome DevTools MCP servers both failed to connect (`CONNECT_TIMEOUT`). The
   UI changes were verified by `tsc --noEmit` (clean, 29 app files) and a full
   `next build` (clean, all 16 routes) — **but no screenshot was taken.** This
   project has caught real visual bugs by screenshot before that grep and tsc
   both missed. Treat the UI as build-verified, not eye-verified.

---

## 5. Where the study tickets live

`docs/POST_HIBERNATION_STUDIES.md` — S-1 through S-5, each with what prompted
it, what is already known, and what the pre-registration has to say. None of
them has been started. None of them may touch a live config without a
3-partition walk-forward first.
