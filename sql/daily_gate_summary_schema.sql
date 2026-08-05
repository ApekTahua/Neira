-- One row per trading day: the actual gate thresholds paper_signal_scan.py
-- computed and applied that day. weekly_cut/sector_cut/regime/streak/
-- trend_strength were always computed locally but discarded after use --
-- daily_scoreboard stores each ticker's OWN weekly_ma_spread/sector_rs_momentum,
-- but not the threshold they were measured against, so the frontend had no
-- way to show *why* a ticker got a given label beyond the label itself.
--
-- Display/explain only, same isolation as daily_scoreboard -- never read
-- back into a trading decision.
create table if not exists daily_gate_summary (
  trade_date        date primary key,
  regime            text not null,
  bullish_streak    int not null,
  trend_strength    numeric not null,
  regime_ok         boolean not null,
  weekly_cut        numeric not null,
  sector_cut        numeric not null,
  score_p90         numeric not null,
  atr_ratio_max     numeric not null,
  adtv_min          numeric not null,
  updated_at        timestamptz not null default now()
);

alter table daily_gate_summary enable row level security;

drop policy if exists daily_gate_summary_select_anon on daily_gate_summary;
create policy daily_gate_summary_select_anon on daily_gate_summary
  for select to anon, authenticated using (true);
