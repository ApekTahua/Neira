-- Paper trading schema (2026-07-31). See docs/V3_FINDINGS_LOG.md
-- "Live paper trading" section for the full design.
--
-- Run this once in the Supabase SQL editor (or via the MCP execute_sql/
-- apply_migration tools when connected) before the first
-- paper_signal_scan.py run. Reuses backtest_runs / backtest_trades /
-- backtest_equity as-is (same schema src/backtest_v3.py already writes) --
-- only these two tables are new.

-- backtest_runs predates this file and isn't otherwise defined here, but
-- both src/backtest_v3.py (_save_to_supabase) and src/paper_signal_scan.py
-- (EOD summary update) now write a cvar_95 value into it -- recorded here
-- so the column isn't only real in the live Supabase project and missing
-- from a from-scratch rebuild off this repo's SQL files.
alter table backtest_runs add column if not exists cvar_95 numeric;

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
  no_data_days int not null default 0, -- consecutive trading days with no EOD print -- DELISTED_GAP detection
  last_valid_close numeric,           -- forced-exit price once no_data_days hits DELISTING_GAP_DAYS
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
drop policy if exists paper_positions_select_anon on paper_positions;
create policy paper_positions_select_anon on paper_positions
  for select to anon, authenticated using (true);
drop policy if exists paper_account_select_anon on paper_account;
create policy paper_account_select_anon on paper_account
  for select to anon, authenticated using (true);

-- One-time seed: creates the single ongoing paper-trading run and its cash
-- ledger in one statement (no manual id copy-paste). is_published=false so
-- it never appears in the /backtest page's published-versions dropdown --
-- the new dedicated /paper-trading page queries version='V3_PAPER'
-- directly instead. Both new Python scripts look up the run id at
-- startup via `select id from backtest_runs where version='V3_PAPER'
-- order by id desc limit 1` -- never hardcoded, so this seed is the only
-- manual step.
-- Guarded so re-running this migration never creates a second paper run.
with new_run as (
  insert into backtest_runs (
    version, period_start, period_end, initial_capital, final_capital,
    net_profit_pct, benchmark_pct, alpha_pct, total_trades, win_rate,
    profit_factor, max_drawdown, notes, strategy_summary, is_published
  )
  select
    'V3_PAPER', current_date, current_date, 100000000, 100000000,
    0, 0, 0, 0, 0,
    null, 0,
    'Live paper trading, current best validated V3 configuration (LIQ_SIZING on, PYRAMID on, QUANTILE_CUT=0.60, TP1_MULT=1.5, TRAILING_PCT=0.08, MAX_POSITIONS=6, ALLOC_PCT=0.20). Frozen at launch -- see docs/V3_FINDINGS_LOG.md governance note.',
    'V3 Paper Trading (started 2026-08-03)',
    false
  where not exists (select 1 from backtest_runs where version = 'V3_PAPER')
  returning id
)
insert into paper_account (run_id, cash, last_signal_date)
select id, 100000000, null from new_run;

-- V3.1_PAPER seed (2026-08-08): second, independent, concurrent paper run --
-- V3_PAPER above stays untouched and frozen (governance rule, see
-- paper_common.py's module docstring). V3.1 config = V3_PAPER's config plus
-- three stacked, walk-forward-validated changes from docs/V3_FINDINGS_LOG.md
-- ("Fine neighbor sweep confirms the wcap plateau", 2026-08-08):
-- ARA_FILTER_ENABLED=1, ATR_PRICE_RATIO_MAX=0.08 (was 0.10),
-- SCORE_WEEKLY_COMP_ABS_CAP_Q=0.81 (was off). Set via env on the V3.1
-- trigger workflows (PAPER_VERSION, V4_ARA_FILTER, V4_ATR_PRICE_RATIO_MAX,
-- V4_SCORE_WEEKLY_COMP_ABS_CAP_Q), not in this repo's frozen config.py.
with new_run_v31 as (
  insert into backtest_runs (
    version, period_start, period_end, initial_capital, final_capital,
    net_profit_pct, benchmark_pct, alpha_pct, total_trades, win_rate,
    profit_factor, max_drawdown, notes, strategy_summary, is_published
  )
  select
    'V3.1_PAPER', current_date, current_date, 100000000, 100000000,
    0, 0, 0, 0, 0,
    null, 0,
    'Live paper trading, V3.1: V3_PAPER''s frozen config plus ARA_FILTER_ENABLED=1, ATR_PRICE_RATIO_MAX=0.08, SCORE_WEEKLY_COMP_ABS_CAP_Q=0.81 -- strongest walk-forward-validated (neighbor-checked) candidate found in research. Frozen at launch -- see docs/V3_FINDINGS_LOG.md governance note.',
    'V3.1 Paper Trading (started 2026-08-08)',
    false
  where not exists (select 1 from backtest_runs where version = 'V3.1_PAPER')
  returning id
)
insert into paper_account (run_id, cash, last_signal_date)
select id, 100000000, null from new_run_v31;

-- BANDAR_SIZING_ENABLED support columns (2026-08-12): same persist-and-
-- reread pattern paper_account.log_adtv_p90 already established for
-- LIQ_SIZING -- paper_signal_scan.py computes concentration_p90 once/day
-- and persists it (paper_account), and the per-position concentration
-- value at signal time (paper_positions), so paper_monitor.py can fill
-- entries with the exact same BANDAR_SIZING reference without rebuilding
-- the full dataset every 15 minutes. Additive, safe on already-live
-- V3_PAPER/V3.1_PAPER rows (both columns just stay NULL there, and
-- BANDAR_SIZING_ENABLED defaults off for both anyway).
alter table paper_account add column if not exists concentration_p90 numeric;
alter table paper_positions add column if not exists concentration numeric;

-- V4_PAPER seed (2026-08-12): third, independent, concurrent paper run --
-- V3_PAPER and V3.1_PAPER above stay untouched and frozen. V4 config =
-- V3_PAPER's EXACT frozen config plus exactly ONE change:
-- BANDAR_SIZING_ENABLED=1 (backtest_v3.py) -- the Bandarmology
-- concentration-based sizing multiplier, walk-forward validated
-- (docs/BANDARMOLOGY_DESIGN.md, "V4 sizing integration built + validated"):
-- mean alpha +21.71%->+24.09%, median alpha +12.60%->+19.09%, mean profit
-- factor 1.58->1.88, mean max drawdown -16.08%->-15.03% (better), worst
-- max drawdown -21.61%->-21.84% (slightly worse, disclosed tradeoff).
-- Deliberately NOT combined with V3.1's ARA_FILTER/ATR_PRICE_RATIO_MAX/
-- SCORE_WEEKLY_COMP_ABS_CAP_Q changes or MOVER_SIZING_ENABLED (mover_pairs
-- sizing tested mixed, needs a redesign first, not launch-ready) -- single-
-- variable-change discipline, so any V4-vs-V3 difference is cleanly
-- attributable to Bandarmology alone. Set via env on the V4 trigger
-- workflows (PAPER_VERSION, V4_BANDAR_SIZING), not in this repo's frozen
-- config.py.
with new_run_v4 as (
  insert into backtest_runs (
    version, period_start, period_end, initial_capital, final_capital,
    net_profit_pct, benchmark_pct, alpha_pct, total_trades, win_rate,
    profit_factor, max_drawdown, notes, strategy_summary, is_published
  )
  select
    'V4_PAPER', current_date, current_date, 100000000, 100000000,
    0, 0, 0, 0, 0,
    null, 0,
    'Live paper trading, V4: V3_PAPER''s exact frozen config plus BANDAR_SIZING_ENABLED=1 (Bandarmology concentration-based position sizing) -- the single validated change, isolated for clean attribution. See docs/BANDARMOLOGY_DESIGN.md for the full validation writeup.',
    'V4 Paper Trading -- Bandarmology (started 2026-08-12)',
    false
  where not exists (select 1 from backtest_runs where version = 'V4_PAPER')
  returning id
)
insert into paper_account (run_id, cash, last_signal_date)
select id, 100000000, null from new_run_v4;
