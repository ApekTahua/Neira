-- Real daily qualifying-signal list (2026-08-17). See docs/V3_FINDINGS_LOG.md
-- "why the Screener page never shows fewer than ~90 signals": daily_scoreboard
-- is built by score_full_universe(), a ticker-lookup function that deliberately
-- never drops a row -- not the real selectivity answer. score_candidates() is
-- the function that actually decides real trade entries (proven selective: 60%
-- of days across the 9-window walk-forward return zero qualifying candidates),
-- but its real daily output was never persisted anywhere long-term before this.
--
-- One row per (trade_date, stock_code) that PASSED score_candidates()'s real
-- entry gate that day -- independent of portfolio capacity (MAX_POSITIONS
-- slots free) or which paper run is retired; see paper_signal_scan.py's
-- comment at the `scored` hoist for why those are a different question.
--
-- Only ever written by the PRIMARY_PAPER_VERSION run (V4_PAPER) -- V3_PAPER/
-- V3.1_PAPER apply different filter env vars (V4_ARA_FILTER,
-- V4_ATR_PRICE_RATIO_MAX, V4_SCORE_WEEKLY_COMP_ABS_CAP_Q) that make their own
-- score_candidates() output a different computation, not fit for the public
-- Screener page. Display/explain only, same isolation as daily_scoreboard /
-- daily_gate_summary -- never read back into a trading decision.
create table if not exists daily_qualifying_signals (
  trade_date     date not null,
  stock_code     text not null,
  rank           int not null,  -- 1-indexed position in that day's score-sorted list
  score          numeric not null,
  trigger        text,
  adtv_20        numeric,
  avg_vol_20     numeric,
  atr            numeric,
  signal_close   numeric,
  tp_target      numeric,
  concentration  numeric,
  updated_at     timestamptz not null default now(),
  primary key (trade_date, stock_code)
);

create index if not exists daily_qualifying_signals_stock_code_idx on daily_qualifying_signals (stock_code);

alter table daily_qualifying_signals enable row level security;

drop policy if exists daily_qualifying_signals_select_anon on daily_qualifying_signals;
create policy daily_qualifying_signals_select_anon on daily_qualifying_signals
  for select to anon, authenticated using (true);
