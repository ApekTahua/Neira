-- Broker summary schema (2026-08-08, moved to a dedicated second Supabase
-- project 2026-08-09 -- see docs/MASTERPLAN.md "Bandarmology" section).
-- Table renamed broker_summary_daily -> broker_summary 2026-08-09 (user
-- call while setting up the second project) -- this file is the source of
-- truth for the name, keep it in sync with whatever's actually deployed.
-- `source` column dropped 2026-08-09 -- single source (Indopremier),
-- hardcoded constant, wasn't earning its keep (same call as dropping
-- `brokers.confidence` earlier the same day).
--
-- Written by an n8n workflow pulling Indopremier's public
-- data-brokersummary.php per (stock_code, trade_date), NOT by any Python
-- script in this repo -- n8n is the source of truth for this table's
-- writes. This repo only defines the schema n8n writes into (see
-- feedback-never-touch-n8n memory: never touch n8n directly, only
-- document the exact change for the user to apply by hand).
--
-- `board=all` deliberately includes Nego/Tunai (off-market negotiated
-- block deals), not just regular continuous-auction trades -- a stock can
-- show zero regular-market activity in ihsg_eod (open/high/low/volume
-- all 0) while still having real broker rows here from a Nego deal that
-- day. That's correct, not a bug -- negotiated block trades are often the
-- more telling bandarmology signal, not noise to filter out.
--
-- One row per broker per side per stock per day (not one JSON blob per
-- stock-day) -- normalized so rolling per-broker/per-stock accumulation
-- queries (the whole point of bandarmology analysis) are plain SQL, not
-- JSON parsing on every read. Indopremier's own report caps at top-10
-- buyers + top-10 sellers by volume (not every broker that transacted) --
-- a source limit, not something this schema or the scrape truncates.
--
-- Lives on its own Supabase project now, separate from the main one --
-- no native SQL join with ihsg_eod/backtest_* tables, combine in Python
-- (pandas) at analysis time instead.

create table if not exists broker_summary (
  id bigserial primary key,
  trade_date date not null,
  stock_code text not null,
  broker_code text not null,
  side text not null check (side in ('buy', 'sell')),
  investor_type text,          -- NOT populated by the scrape -- Indopremier's table has no
                                -- type column (confirmed by fetching the real page). Left here
                                -- for a future direct source that does provide it; for now,
                                -- join against the `brokers` reference table on broker_code.
  lot bigint not null,          -- can ALSO carry a "2.0 M" style abbreviation for big lot
                                 -- counts, same as val_rupiah -- both need the same K/M/B/T
                                 -- parser in the n8n Code node, not a plain Number() cast
  val_rupiah bigint,           -- parsed to a real Rupiah integer -- NOT the raw "10.2 B"
                                -- string the source HTML shows, see n8n Code node fix
  avg_price numeric,
  created_at timestamptz not null default now(),
  unique (trade_date, stock_code, broker_code, side)
);

create index if not exists broker_summary_stock_date_idx on broker_summary (stock_code, trade_date);
create index if not exists broker_summary_broker_date_idx on broker_summary (broker_code, trade_date);
create index if not exists broker_summary_date_idx on broker_summary (trade_date);

alter table broker_summary enable row level security;

-- Frontend reads directly with the anon key (same pattern as backtest_trades/
-- paper_positions on the main project) -- no anon write policy, n8n writes
-- with the service-role key for this second project.
drop policy if exists broker_summary_select_anon on broker_summary;
create policy broker_summary_select_anon on broker_summary
  for select to anon, authenticated using (true);
