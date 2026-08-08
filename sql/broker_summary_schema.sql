-- Broker summary schema (2026-08-08). Bandarmology data source -- see
-- docs/MASTERPLAN.md "Bandarmology" section and docs/V3_FINDINGS_LOG.md.
--
-- Written by an n8n workflow pulling Indopremier's public
-- data-brokersummary.php per (stock_code, trade_date), NOT by any Python
-- script in this repo -- n8n is the source of truth for this table's
-- writes. This repo only defines the schema n8n writes into (see
-- feedback-never-touch-n8n memory: never touch n8n directly, only
-- document the exact change for the user to apply by hand).
--
-- One row per broker per side per stock per day (not one JSON blob per
-- stock-day) -- normalized so rolling per-broker/per-stock accumulation
-- queries (the whole point of bandarmology analysis) are plain SQL, not
-- JSON parsing on every read.

create table if not exists broker_summary_daily (
  id bigserial primary key,
  trade_date date not null,
  stock_code text not null,
  broker_code text not null,
  side text not null check (side in ('buy', 'sell')),
  investor_type text,          -- raw label from source (Foreign/Local/BUMN/Pemerintah) --
                                -- taxonomy isn't normalized across sources (Indopremier vs
                                -- Stockbit label these differently), stored as-is
  lot bigint not null,
  val_rupiah bigint,           -- parsed to a real Rupiah integer -- NOT the raw "10.2 B"
                                -- string the source HTML shows, see n8n Code node fix
  avg_price numeric,
  source text not null default 'indopremier',
  created_at timestamptz not null default now(),
  unique (trade_date, stock_code, broker_code, side, source)
);

create index if not exists broker_summary_daily_stock_date_idx on broker_summary_daily (stock_code, trade_date);
create index if not exists broker_summary_daily_broker_date_idx on broker_summary_daily (broker_code, trade_date);
create index if not exists broker_summary_daily_date_idx on broker_summary_daily (trade_date);

alter table broker_summary_daily enable row level security;

-- Frontend reads directly with the anon key (same pattern as backtest_trades/
-- paper_positions) -- no anon write policy, n8n writes with the service-role
-- key already used by its other Supabase-writing workflows.
drop policy if exists broker_summary_daily_select_anon on broker_summary_daily;
create policy broker_summary_daily_select_anon on broker_summary_daily
  for select to anon, authenticated using (true);
