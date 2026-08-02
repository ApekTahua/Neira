-- Daily full-universe scoreboard (2026-08-02). See docs/V3_FINDINGS_LOG.md
-- "NEXT ENHANCEMENT -- full-universe daily scoreboard" section for the
-- design. Pure read/display table -- paper_signal_scan.py writes to it
-- AFTER the real trading-decision steps, never read back into
-- paper_positions/paper_account. Zero risk to the live paper track record.

create table if not exists daily_scoreboard (
  trade_date date not null,
  stock_code text not null,
  score numeric not null,
  label text not null check (label in ('STRONG_BUY', 'BUY', 'WATCH', 'WAIT')),
  weekly_ma_spread numeric,
  sector_rs_momentum numeric,
  close_price numeric,
  adtv_20 numeric,
  updated_at timestamptz not null default now(),
  primary key (trade_date, stock_code)
);

create index if not exists daily_scoreboard_stock_code_idx on daily_scoreboard (stock_code);

alter table daily_scoreboard enable row level security;

drop policy if exists daily_scoreboard_select_anon on daily_scoreboard;
create policy daily_scoreboard_select_anon on daily_scoreboard
  for select to anon, authenticated using (true);
