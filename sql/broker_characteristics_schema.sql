-- Cross-stock broker personality rollup, one row per broker_code. Answers
-- "what kind of trader is broker X in general" -- different from
-- bandarmology_mover_pairs (which answers "which brokers move THIS
-- stock"). See docs/BANDARMOLOGY_DESIGN.md, broker-characteristic
-- profile section. investor_type deliberately NOT duplicated here --
-- frontend joins against the existing `brokers` table on broker_code
-- to avoid two copies of the same fact going stale independently.
--
-- Computed locally (src/bandarmology_push_movers_rotation.py, same run
-- as the three candidate tables -- reuses the same loaded data, no
-- extra cost) and pushed here. Same monthly-refresh cadence as the
-- other candidate tables (see the CORRECTION 2026-08-12 entry in the
-- design doc for why monthly, not daily).

create table if not exists broker_characteristics (
  broker_code             text primary key,
  active_stock_count      int not null,
  pct_days_net_buy        numeric,
  avg_turnover_to_net_ratio numeric,
  mover_stock_count       int not null default 0,
  rotation_pair_count     int not null default 0,
  cluster_pair_count      int not null default 0,
  computed_at             timestamptz not null default now()
);

alter table broker_characteristics enable row level security;

drop policy if exists broker_characteristics_select_anon on broker_characteristics;
create policy broker_characteristics_select_anon on broker_characteristics
  for select to anon, authenticated using (true);
