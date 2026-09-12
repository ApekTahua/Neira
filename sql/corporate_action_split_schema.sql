-- T-7 phase 1: corporate-action adjustment for SPLITS and REVERSE SPLITS.
--
-- ihsg_eod is NOT touched. It stays the immutable source of truth; everything
-- here is derived, so it self-corrects if EOD is ever restated and there is no
-- second copy of the price history to drift.
--
-- WHY NO SCRAPE IS NEEDED. On an ex-split date IDX reports `previous` ALREADY
-- RESCALED while the prior row's close_price is still the raw pre-split price,
-- so the ratio falls straight out of a self-join. Measured over 1,291,370 rows
-- (2020-06-02..2026-09-11): 106 rows disagree by more than 35% -- beyond any
-- IDX auto-reject band, so no ordinary session produces one. 75 snap to a clean
-- corporate-action ratio (73 splits, 2 reverse splits). The 31 that do not are
-- rights issues, whose ex-price depends on the subscription price and cannot be
-- inferred from price at all; those are phase 2 and will read their ratio from
-- the filings (%right issue% / %hmetd% were always on the prune whitelist, so
-- they survive). This is why the split announcements deleted before T-17 are
-- not needed.
--
-- Cross-checked independently: FKS Multi Agro (FISH) ran a 1:10 split and
-- trading at the new nominal began 2025-09-09 -- the exact date and ratio this
-- detection produces.
--
-- MATERIALIZED on purpose. As a plain view it measured 36.8s: the lag() has to
-- sweep all 1.29M rows before the filter cuts them to 106, and stock_split_factor
-- references it, so any query touching both paid that twice and timed out. The
-- output is ~75 rows that change only when IDX runs a split. Refreshed by the
-- existing daily job (cron 'refresh-disclosures-flat', 12:00 UTC / 19:00 WIB,
-- after n8n's 17:30 WIB EOD ingestion).
--
-- A matview cannot carry security_invoker -- that option does not exist for
-- them -- so access is by grant. The content derives entirely from public EOD
-- prices that anon can already read directly.

create materialized view public.corporate_action_split as
with seq as (
  select stock_code, trade_date, previous,
         lag(close_price) over (partition by stock_code order by trade_date) as prior_close
  from public.ihsg_eod
  where close_price > 0 and previous > 0
),
ev as (
  select stock_code, trade_date as ex_date, prior_close, previous as reported_previous,
         prior_close / previous as raw_ratio
  from seq
  where prior_close is not null and abs(previous / prior_close - 1) > 0.35
),
-- Nearest IDX corporate-action ratio wins. Anything further than 1% from every
-- target is dropped entirely rather than forced onto the closest one.
snapped as (
  select e.*, t.target, abs(e.raw_ratio / t.target - 1) as dev
  from ev e
  cross join lateral (
    select unnest(array[2,3,4,5,6,8,10,20,25,40,50,100,
                        0.5,0.25,0.2,0.1,0.05,0.04,0.02,0.01]::numeric[]) as target
  ) t
),
best as (
  select distinct on (stock_code, ex_date) *
  from snapped order by stock_code, ex_date, dev
)
select
  stock_code,
  ex_date                                   as source_event_date,
  prior_close,
  reported_previous,
  round(raw_ratio::numeric, 6)              as raw_ratio,
  target                                    as inferred_ratio,
  round((1 - dev)::numeric, 6)              as snap_confidence,
  case when target > 1 then 'split' else 'reverse_split' end as kind
from best
where dev <= 0.01;

create unique index corporate_action_split_pk
  on public.corporate_action_split (stock_code, source_event_date);

-- Back-propagated divisor. A price on date t is comparable with today once it is
-- divided by the product of every ratio whose ex_date is AFTER t, so the factor
-- is a step function per stock, one row per era between consecutive events.
-- ~75 events over 72 stocks -> 147 rows, so a consumer just joins on the range.
--
-- Every row carries what produced it -- source_event_dates, source_ratios,
-- min_snap_confidence -- so any adjusted number traces back to the raw rows
-- behind it.
create or replace view public.stock_split_factor as
with ev as (
  select stock_code, source_event_date, inferred_ratio, snap_confidence
  from public.corporate_action_split
),
rev as (
  select stock_code, source_event_date, inferred_ratio,
    round(exp(sum(ln(inferred_ratio)) over (
      partition by stock_code order by source_event_date desc
      rows between unbounded preceding and current row))::numeric, 10) as divisor,
    array_agg(source_event_date) over (
      partition by stock_code order by source_event_date desc
      rows between unbounded preceding and current row) as src_dates,
    array_agg(inferred_ratio) over (
      partition by stock_code order by source_event_date desc
      rows between unbounded preceding and current row) as src_ratios,
    min(snap_confidence) over (
      partition by stock_code order by source_event_date desc
      rows between unbounded preceding and current row) as min_conf
  from ev
)
select
  stock_code,
  coalesce(lag(source_event_date) over (partition by stock_code order by source_event_date),
           '1900-01-01'::date)               as valid_from,
  (source_event_date - 1)                    as valid_to,
  divisor,
  src_dates                                  as source_event_dates,
  src_ratios                                 as source_ratios,
  min_conf                                   as min_snap_confidence
from rev
union all
-- the open-ended era after the most recent event: prices are already current
select stock_code, max(source_event_date), '9999-12-31'::date, 1::numeric,
       array[]::date[], array[]::numeric[], 1::numeric
from ev group by stock_code;

alter view public.stock_split_factor set (security_invoker = on);

grant select on public.corporate_action_split to anon, authenticated, service_role;
grant select on public.stock_split_factor to anon, authenticated, service_role;

-- Wired into the existing daily job rather than a second schedule:
--   select cron.alter_job(
--     (select jobid from cron.job where jobname = 'refresh-disclosures-flat'),
--     command := 'select public.prune_unimportant_disclosures();'
--                ' refresh materialized view concurrently public.disclosures_flat;'
--                ' refresh materialized view concurrently public.corporate_action_split;');
