-- Daily sync: copies broker_summary's current snapshot into
-- broker_summary_history before n8n's next run overwrites it, then prunes
-- anything past the 90-day window. Same pattern as sync_broker_flow_daily()
-- (live on DB2, applied directly via migration, never checked into this
-- repo as a file -- see docs/ROADMAP.md "P1 -- per-broker daily flow" for
-- its documented behavior, which this mirrors).
--
-- Idempotent + self-healing for weekends/holidays: if broker_summary's
-- max(trade_date) was already synced (n8n hasn't posted a new day since
-- the last run), this no-ops instead of re-inserting or erroring. No
-- explicit day-of-week logic needed, same reasoning as the sibling job.
--
-- Simpler than refresh_bandarmology_flow_daily() -- that one aggregates
-- buy/sell into net rows and computes a rolling window. This one is a
-- straight copy (same schema, same granularity) plus a date-cutoff prune,
-- because broker_summary_history's whole job is preserving the raw
-- snapshot broker_summary would otherwise lose, not deriving new features.

create or replace function sync_broker_summary_history() returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_max_date date;
begin
  select max(trade_date) into v_max_date from broker_summary;
  if v_max_date is null then
    return; -- broker_summary itself is empty -- nothing to sync yet
  end if;

  if exists (select 1 from broker_summary_history where trade_date = v_max_date limit 1) then
    return; -- already synced this date (weekend/holiday no-op, or a retried run)
  end if;

  insert into broker_summary_history (trade_date, stock_code, broker_code, side, lot, val_rupiah, avg_price)
  select trade_date, stock_code, broker_code, side, lot, val_rupiah, avg_price
  from broker_summary
  where trade_date = v_max_date
  on conflict (stock_code, trade_date, broker_code, side) do nothing;

  delete from broker_summary_history where trade_date < (v_max_date - interval '90 days');
end;
$$;

-- pg_cron registration -- run 5 minutes after sync-broker-flow-daily's
-- 18:30 WIB slot so this doesn't race broker_summary's own n8n write
-- window (n8n posts ~18:00-18:25 WIB, per broker_summary_schema.sql).
select cron.schedule(
  'sync-broker-summary-history',
  '35 11 * * *', -- 18:35 WIB
  $$select sync_broker_summary_history();$$
);
