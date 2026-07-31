-- Paper trading schema (2026-07-31). See docs/V3_FINDINGS_LOG.md
-- "Live paper trading" section for the full design.
--
-- Run this once in the Supabase SQL editor (or via the MCP execute_sql/
-- apply_migration tools when connected) before the first
-- paper_signal_scan.py run. Reuses backtest_runs / backtest_trades /
-- backtest_equity as-is (same schema src/backtest_v3.py already writes) --
-- only these two tables are new.

create table if not exists paper_positions (
  id bigserial primary key,
  run_id bigint not null references backtest_runs(id),
  stock_code text not null,
  status text not null check (status in ('PENDING', 'OPEN', 'CLOSED')),
  signal_date date not null,          -- day the candidate was generated
  entry_date date,                    -- day actually filled (null while PENDING)
  trigger text,
  score numeric,
  adtv_20 numeric,
  avg_vol_20 numeric,                 -- needed for compute_entry_fill()'s LIQ_CAP_PCT lot cap
  atr_at_entry numeric,
  entry_price_original numeric,
  avg_price numeric,
  total_lots int,
  remaining_lots int,
  cost_basis numeric,
  sl_price numeric,
  tp1_price numeric,
  tp1_hit boolean not null default false,
  tp2_hit boolean not null default false,
  highest_price numeric,              -- peak close since entry, for the trailing stop
  day_high numeric,                   -- reset daily, built up from 15-min polls
  day_low numeric,
  hold_days int not null default 0,
  checkpoint_day int,
  target_price numeric,
  exit_date date,
  exit_price numeric,
  exit_reason text,
  pnl numeric,
  pnl_pct numeric,
  updated_at timestamptz not null default now()
);

create index if not exists paper_positions_status_idx on paper_positions (status);
create index if not exists paper_positions_run_id_idx on paper_positions (run_id);
create index if not exists paper_positions_stock_code_idx on paper_positions (stock_code);

create table if not exists paper_account (
  run_id bigint primary key references backtest_runs(id),
  cash numeric not null,
  last_signal_date date,              -- guards against double-processing a non-trading day
  log_adtv_p90 numeric,               -- train-derived reference for LIQ_SIZING, refreshed
                                       -- daily by paper_signal_scan.py, read by paper_monitor.py
                                       -- so it doesn't rebuild the full dataset every 15 min
  updated_at timestamptz not null default now()
);

alter table paper_positions enable row level security;
alter table paper_account enable row level security;

-- Frontend reads directly with the anon key (same pattern as backtest_trades/
-- backtest_equity) -- no anon write policy, backend writes with the
-- service-role SUPABASE_KEY already used by run_screener.yml.
create policy if not exists paper_positions_select_anon on paper_positions
  for select to anon, authenticated using (true);
create policy if not exists paper_account_select_anon on paper_account
  for select to anon, authenticated using (true);

-- One-time seed: creates the single ongoing paper-trading run and its cash
-- ledger in one statement (no manual id copy-paste). is_published=false so
-- it never appears in the /backtest page's published-versions dropdown --
-- the new dedicated /paper-trading page queries version='V3_PAPER'
-- directly instead. Both new Python scripts look up the run id at
-- startup via `select id from backtest_runs where version='V3_PAPER'
-- order by id desc limit 1` -- never hardcoded, so this seed is the only
-- manual step.
with new_run as (
  insert into backtest_runs (
    version, period_start, period_end, initial_capital, final_capital,
    net_profit_pct, benchmark_pct, alpha_pct, total_trades, win_rate,
    profit_factor, max_drawdown, notes, strategy_summary, is_published
  ) values (
    'V3_PAPER', current_date, current_date, 100000000, 100000000,
    0, 0, 0, 0, 0,
    null, 0,
    'Live paper trading, current best validated V3 configuration (LIQ_SIZING on, PYRAMID on, QUANTILE_CUT=0.60, TP1_MULT=1.5, TRAILING_PCT=0.08, MAX_POSITIONS=6, ALLOC_PCT=0.20). Frozen at launch -- see docs/V3_FINDINGS_LOG.md governance note.',
    'V3 Paper Trading (started 2026-08-03)',
    false
  )
  returning id
)
insert into paper_account (run_id, cash, last_signal_date)
select id, 100000000, null from new_run;
