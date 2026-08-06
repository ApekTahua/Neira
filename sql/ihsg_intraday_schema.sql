-- Intraday session aggregate, built inside Supabase by pg_cron (2026-08-04).
--
-- Problem it solves: ihsg_realtime is a CURRENT-STATE table -- one row per
-- stock, upserted in place. It has no history at all, which means:
--   * nothing can prove the feed was fresh at 14:00, because the 18:00
--     write overwrites the evidence;
--   * paper_monitor.py can only reconstruct a session's high/low from its
--     own sparse polls, and GitHub Actions dropped ~90% of those on
--     2026-08-04 (3 runs fired out of ~28 scheduled);
--   * an intraday chart is impossible.
--
-- Deliberately an AGGREGATE, not a tick log. One row per (trade_date,
-- stock_code) that accumulates the session's real high/low/last: ~1,000
-- rows per trading day instead of ~120,000 for full snapshots, while still
-- answering every question above. A raw tick table can be added later if
-- intraday charting actually needs one -- that's a bigger appetite for
-- storage than the current need justifies.
--
-- Runs entirely in the database: no n8n involvement (n8n stays read-only),
-- no Vercel cron, no GitHub Actions. pg_cron was already installed (1.6.4).

create table if not exists ihsg_intraday (
  trade_date        date        not null,
  stock_code        text        not null,
  day_open          numeric,
  day_high          numeric,
  day_low           numeric,
  last_close        numeric,
  last_volume       bigint,
  last_change_pct   numeric,
  -- updated_at copied from the source row: lets a reader tell "the feed
  -- stopped updating" apart from "the price genuinely didn't move", which
  -- is exactly the distinction that was unanswerable before.
  source_updated_at timestamptz not null,
  first_seen_at     timestamptz not null default now(),
  last_tick_at      timestamptz not null default now(),
  tick_count        integer     not null default 1,
  primary key (trade_date, stock_code)
);

create index if not exists ihsg_intraday_date_idx on ihsg_intraday (trade_date desc);

alter table ihsg_intraday enable row level security;

drop policy if exists ihsg_intraday_select_anon on ihsg_intraday;
create policy ihsg_intraday_select_anon on ihsg_intraday
  for select to anon, authenticated using (true);


-- Folds the current ihsg_realtime snapshot into today's aggregate row.
--
-- REDESIGNED 2026-08-05 (v1 had a real bug, see below). trade_date is the
-- SERVER's own wall-clock date, not derived from ihsg_realtime.updated_at,
-- and every call updates every liquid row unconditionally rather than
-- gating on that column advancing.
--
-- Why: v1 trusted ihsg_realtime.updated_at as the freshness signal (both
-- the trade_date bucket AND the update guard). Two full trading sessions
-- (2026-08-04, 2026-08-05) showed zero rows ever landed in today's bucket
-- during market hours -- despite the user directly confirming n8n's own
-- execution log shows successful upserts every 3 minutes. That means
-- updated_at is not a trustworthy freshness signal (it may be an upstream
-- "last trade" stamp passed through verbatim, or something else -- unknown
-- without n8n access, which stays off-limits per standing instruction).
-- Gating on it meant this tool could be systematically blind to real
-- price ticks. Capturing unconditionally on the fixed 3-min cron schedule
-- removes the dependency on that column entirely; source_updated_at is
-- kept only as a diagnostic (so a future session can see whether it ever
-- moves), never as a gate. ~1,000 rows every 3 minutes is trivial cost.
create or replace function capture_ihsg_intraday()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  affected integer;
  today date := (now() at time zone 'Asia/Jakarta')::date;
begin
  insert into ihsg_intraday as t (
    trade_date, stock_code, day_open, day_high, day_low,
    last_close, last_volume, last_change_pct, source_updated_at
  )
  select
    today,
    r.stock_code,
    nullif(r.open, 0),
    greatest(r.close, coalesce(nullif(r.open, 0), r.close)),
    least(r.close, coalesce(nullif(r.open, 0), r.close)),
    r.close,
    r.volume,
    case when r.color = 'red' then -abs(r.change_percentage) else abs(r.change_percentage) end,
    r.updated_at
  from ihsg_realtime r
  where r.close > 0
  on conflict (trade_date, stock_code) do update set
    -- Running extremes across the session. The source only carries a live
    -- `close` and a fixed daily `open`, so this IS where a real intraday
    -- high/low comes from -- it cannot be recovered afterwards.
    day_high        = greatest(t.day_high, excluded.last_close),
    day_low         = least(t.day_low, excluded.last_close),
    day_open        = coalesce(t.day_open, excluded.day_open),
    last_close      = excluded.last_close,
    last_volume     = excluded.last_volume,
    last_change_pct = excluded.last_change_pct,
    source_updated_at = excluded.source_updated_at,
    last_tick_at    = now(),
    -- Only counts as a real "tick" if the price actually moved since the
    -- last poll -- otherwise tick_count would just measure how often cron
    -- fired, not how often the feed genuinely updated. No WHERE guard on
    -- the insert itself: every liquid row gets touched every 3 minutes.
    tick_count      = t.tick_count + (case when t.last_close is distinct from excluded.last_close then 1 else 0 end);

  get diagnostics affected = row_count;
  return affected;
end;
$$;


-- Every 3 minutes, 02:00-10:00 UTC = 09:00-17:00 WIB (pg_cron schedules in
-- UTC). IDX itself trades 09:00-15:00 WIB; the window runs to 17:00 to cover
-- the upstream feed's full write window, and over-running past the real
-- close costs nothing since a repeated identical read is a cheap no-op tick.
--
-- Stops before 18:00 WIB deliberately. Existing pg_cron job
-- `eod-to-realtime-snapshot` (0 11 * * * = 18:00 WIB) overwrites ALL of
-- ihsg_realtime from ihsg_eod -- that is where every row's 18:00 timestamp
-- comes from, and why intraday write history was previously unrecoverable:
-- the evidence was being erased every evening. Session aggregates are
-- already complete by then, and ihsg_eod is authoritative for the close.
select cron.unschedule('capture-ihsg-intraday')
  where exists (select 1 from cron.job where jobname = 'capture-ihsg-intraday');

select cron.schedule(
  'capture-ihsg-intraday',
  '*/3 2-10 * * 1-5',
  $$select capture_ihsg_intraday()$$
);

-- To stop it:  select cron.unschedule('capture-ihsg-intraday');
-- To inspect:  select * from cron.job where jobname = 'capture-ihsg-intraday';
--              select * from cron.job_run_details order by start_time desc limit 20;
