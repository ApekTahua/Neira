-- Rolling 90-day history of broker_summary (2026-08-16). broker_summary
-- itself is overwritten daily by n8n and only ever holds the LATEST trading
-- day (see broker_summary_schema.sql) -- this table is the fix for that,
-- same architectural pattern already proven live for
-- bandarmology_broker_flow_daily (see docs/ROADMAP.md in the frontend repo,
-- "P1 -- per-broker daily flow -- DONE 2026-08-14"): a daily plpgsql sync
-- function + pg_cron job copies whatever broker_summary currently holds
-- into here before it gets overwritten, then prunes anything past 90 days.
--
-- SAME granularity as broker_summary (one row per broker per side per stock
-- per day, not aggregated/netted) -- unlike bandarmology_broker_flow_daily,
-- which nets buy-sell into one row per (stock, broker, day). This table
-- exists so the frontend's Broker Summary table (top-10 buyers/sellers +
-- avg price per side) can show any of the last 90 days, not just today.
--
-- Deliberately narrower than the abandoned 2026-08-12 broker_summary_history
-- attempt (see BANDARMOLOGY_DESIGN.md "CORRECTION 2026-08-12" -- that one
-- was sized wrong and would have tried to hold FULL history, ~1.3-1.5GB
-- even trimmed, on a 500MB free-tier project): no bigserial id, no
-- created_at/investor_type columns, composite primary key doubles as the
-- lookup index, one extra index for the prune step. 90-day bound, same as
-- bandarmology_broker_flow_daily, not full history.
--
-- Size estimate (2026-08-16, no live pg_database_size access this session --
-- derived from real local data instead of a guess). Loaded the actual
-- 90-calendar-day slice of the local Parquet archive
-- (broker_summary_history_backfill.py's own file-selection logic, dry-run
-- without a network call): 57 trading days (2026-05-18..2026-08-11,
-- calendar weekends/holidays excluded), 874,627 rows, ~15,344 rows/day --
-- matches broker_summary's live 15,113 rows/day closely, cross-validating
-- both numbers. A full 90-calendar-day window floats ~60-65 trading days
-- depending where the holiday calendar lands, so ~920K-1.0M rows, not the
-- naive 90-calendar-days-as-if-all-trading-days 1.36M first assumed.
-- Byte-per-row calibration reused from the abandoned 2026-08-12
-- broker_summary_history attempt (same granularity, trimmed schema, real
-- backfilled data: 11.9M rows -> 1.3-1.5GB, ~109-126 bytes/row). 920K-1.0M
-- rows * 109-126 bytes ~= 100-126MB. DB2's total was ~108MB/500MB as of
-- 2026-08-14 per ROADMAP.md (dominated by bandarmology_broker_flow_daily's
-- already-live 90-day window, ~70MB/618K rows, confirmed via count this
-- session) -- adding ~100-126MB lands around ~210-235MB/500MB, comfortable
-- (~42-47% used). 90 days kept as designed; would need re-checking before
-- ever widening past 90 (same open question already flagged for
-- bandarmology_broker_flow_daily in ROADMAP.md).

create table if not exists broker_summary_history (
  trade_date   date not null,
  stock_code   text not null,
  broker_code  text not null,
  side         text not null check (side in ('buy', 'sell')),
  lot          bigint not null,
  val_rupiah   bigint,
  avg_price    numeric,
  primary key (stock_code, trade_date, broker_code, side)
);

-- Leading (stock_code, trade_date) in the PK already serves the frontend's
-- only query pattern ("this ticker, this day") without a second index.
-- One extra index needed for the daily prune step (`delete ... where
-- trade_date < cutoff`), which doesn't lead with stock_code.
create index if not exists broker_summary_history_date_idx on broker_summary_history (trade_date);

alter table broker_summary_history enable row level security;

-- Same pattern as every other DB2 table the frontend reads directly --
-- anon-select only, no anon write policy. The sync function below writes
-- with elevated (definer) privileges, same shape as
-- refresh_bandarmology_flow_daily.
drop policy if exists broker_summary_history_select_anon on broker_summary_history;
create policy broker_summary_history_select_anon on broker_summary_history
  for select to anon, authenticated using (true);
