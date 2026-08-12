-- Same-side cluster candidates (src/bandarmology_cluster_detector.py),
-- third table in this family alongside bandarmology_mover_pairs and
-- bandarmology_rotation_pairs -- see
-- sql/bandarmology_movers_and_rotation_schema.sql for the shared
-- reasoning (structural flag, not a validated signal; full-table
-- replace on each push, not upsert).

create table if not exists bandarmology_cluster_pairs (
  stock_code        text not null,
  broker_a          text not null,
  broker_b          text not null,
  same_side_days    int not null,
  both_active_days  int not null,
  observed_rate     numeric,
  expected_rate     numeric,
  lift              numeric,
  total_overlap_lot numeric,
  computed_at       timestamptz not null default now(),
  primary key (stock_code, broker_a, broker_b)
);

create index if not exists bandarmology_cluster_pairs_stock_idx on bandarmology_cluster_pairs (stock_code);

alter table bandarmology_cluster_pairs enable row level security;

drop policy if exists bandarmology_cluster_pairs_select_anon on bandarmology_cluster_pairs;
create policy bandarmology_cluster_pairs_select_anon on bandarmology_cluster_pairs
  for select to anon, authenticated using (true);
