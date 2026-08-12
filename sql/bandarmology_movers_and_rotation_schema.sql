-- Two candidate-flag tables, second Supabase project (ptuvkgleurjcniznveye),
-- same pattern as bandarmology_flow_daily_schema.sql. Both are structural/
-- correlational flags surfaced by src/bandarmology_broker_profile.py and
-- src/bandarmology_rotation_detector.py -- NOT forward-return-validated
-- signals (see docs/BANDARMOLOGY_DESIGN.md, Layer 1 section). Fine to ship
-- as "who plays actively here" user-facing insight (lower bar, per "Two
-- consumers, one feature set"); not fine to treat as a trading gate without
-- the same walk-forward discipline everything else in V3 went through.
--
-- Computed locally (src/bandarmology_push_movers_rotation.py) against the
-- full local Parquet history, upserted here -- read-only cache for the
-- frontend, not a source of truth. Full-table replace on each push (small:
-- a few thousand rows each), not an incremental upsert -- candidate sets
-- can shrink as well as grow when re-run against more/different data, and
-- there's no natural row identity to diff against.

create table if not exists bandarmology_mover_pairs (
  stock_code        text not null,
  broker_code       text not null,
  active_days       int not null,
  corr_first_half   numeric,
  corr_second_half  numeric,
  computed_at       timestamptz not null default now(),
  primary key (stock_code, broker_code)
);

create index if not exists bandarmology_mover_pairs_stock_idx on bandarmology_mover_pairs (stock_code);

alter table bandarmology_mover_pairs enable row level security;

drop policy if exists bandarmology_mover_pairs_select_anon on bandarmology_mover_pairs;
create policy bandarmology_mover_pairs_select_anon on bandarmology_mover_pairs
  for select to anon, authenticated using (true);

create table if not exists bandarmology_rotation_pairs (
  stock_code          text not null,
  broker_a            text not null,
  broker_b            text not null,
  opposite_side_days  int not null,
  both_active_days    int not null,
  observed_rate       numeric,
  expected_rate       numeric,
  lift                numeric,
  total_overlap_lot   numeric,
  computed_at         timestamptz not null default now(),
  primary key (stock_code, broker_a, broker_b)
);

create index if not exists bandarmology_rotation_pairs_stock_idx on bandarmology_rotation_pairs (stock_code);

alter table bandarmology_rotation_pairs enable row level security;

drop policy if exists bandarmology_rotation_pairs_select_anon on bandarmology_rotation_pairs;
create policy bandarmology_rotation_pairs_select_anon on bandarmology_rotation_pairs
  for select to anon, authenticated using (true);
