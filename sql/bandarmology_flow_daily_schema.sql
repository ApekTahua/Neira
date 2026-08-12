-- Derived daily flow features, one row per (stock_code, trade_date).
-- Second Supabase project (ptuvkgleurjcniznveye), same as broker_summary/
-- brokers -- see docs/BANDARMOLOGY_DESIGN.md "Two consumers, one feature
-- set" + the storage-split discussion 2026-08-10.
--
-- This is what the Bandarmology page's chart/trend actually reads --
-- NOT the raw broker_summary table (which only ever holds the latest
-- trading day). Cheap enough per row (~10 numeric columns) to keep the
-- FULL history, no pruning needed -- estimated ~100MB for 2023-2026 at
-- full universe, ~30MB/year growth after that. Comfortably inside the
-- free tier for years.
--
-- Computed locally (src/bandarmology_push_daily.py, reusing
-- src/bandarmology_features.py's net/turnover/rolling logic against the
-- full local Parquet history) and upserted here -- this table is a
-- read-only cache for the frontend, not a source of truth. Score/label
-- columns intentionally not here yet -- thresholds aren't tuned (need
-- the full backfill first, see design doc "Open questions"), added
-- later via a plain ALTER TABLE once they exist, no reason to block
-- shipping the chart on that.

create table if not exists bandarmology_flow_daily (
  stock_code        text not null,
  trade_date        date not null,
  net_lot           bigint,
  net_val           bigint,
  turnover_lot      bigint,
  concentration     numeric,
  net_flow_norm     numeric,
  consistency       numeric,
  cumulative_net_val numeric,
  computed_at       timestamptz not null default now(),
  primary key (stock_code, trade_date)
);

create index if not exists bandarmology_flow_daily_date_idx on bandarmology_flow_daily (trade_date);

alter table bandarmology_flow_daily enable row level security;

-- Frontend reads directly with the anon key (same pattern as
-- broker_summary/brokers) -- no anon write, the local push script
-- writes with the service-role key.
drop policy if exists bandarmology_flow_daily_select_anon on bandarmology_flow_daily;
create policy bandarmology_flow_daily_select_anon on bandarmology_flow_daily
  for select to anon, authenticated using (true);
