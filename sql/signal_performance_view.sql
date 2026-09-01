-- signal_performance -- accountability layer over daily_qualifying_signals.
--
-- Answers, for every signal Neira has ever published: what did the stock
-- actually do afterwards, and was that better than doing nothing?
--
-- Deliberately a VIEW, not a table. Everything is derived from ihsg_eod +
-- index_eod, so it cannot drift out of sync with the price history, needs no
-- backfill and no cron, and self-corrects if EOD data is later restated.
--
-- ihsg_eod stores open_price = 0 on ~34% of recent rows, hiding two different
-- things: (a) the stock genuinely did not trade -- volume 0, high = low = 0,
-- close carried over; (b) the stock DID trade but the open was not captured --
-- real volume, real high/low, only open is 0. The lateral keeps only bars that
-- actually traded (high > 0), which drops (a); entry_ref falls back to that
-- bar's close for (b), flagged by entry_ref_is_open. Without this, 16 signals
-- scored an entry price of 0 (read as a -100% entry gap, dragging the average
-- gap to -9.69% when the true average is +0.16%) and non-trading bars fed
-- min(low) = 0 into the drawdown stat.
--
-- Consequence: bar numbering counts TRADED sessions, not calendar days. For a
-- halted stock, "5 days later" means five sessions in which it actually traded.
-- That is the tradeable reading; entry_date and d*_date are exposed so the real
-- calendar span is always visible.
--
-- Entry reference is the NEXT traded session's OPEN, never the signal-day
-- close: the scan runs after the close, so signal_close is a price nobody could
-- have transacted at, and scoring against it silently credits every signal with
-- an overnight gap it never captured -- which is precisely what made an
-- already-extended name like EMAS look like a clean entry.
--
-- Benchmark caveat: index_eod has no open column, so the COMPOSITE leg is
-- measured close-to-close from the signal date and therefore collects the
-- overnight gap the strategy cannot. That biases the comparison against the
-- strategy, which is the safe direction.
--
-- NOTE: this measures SIGNAL QUALITY (did the stock go up after we named it),
-- not strategy P&L. The live engine stops out, takes partials and trails, so a
-- raw N-day hold return is not what the account would have earned. Read it as
-- "was this a good stock to point at", not "this is what we made".
drop view if exists public.signal_performance;

create view public.signal_performance as
with bars as (
  select
    s.trade_date,
    s.stock_code,
    s."rank",
    s.score,
    s."trigger",
    s.signal_close,
    s.tp_target,
    s.atr,
    f.bar_date,
    f.n,
    f.open_price,
    f.high,
    f.low,
    f.close_price
  from public.daily_qualifying_signals s
  left join lateral (
    select
      e.trade_date as bar_date,
      e.open_price,
      e.high,
      e.low,
      e.close_price,
      row_number() over (order by e.trade_date) as n
    from public.ihsg_eod e
    where e.stock_code = s.stock_code
      and e.trade_date > s.trade_date
      and e.high > 0
      and e.low > 0
      and e.close_price > 0
    order by e.trade_date
    limit 20
  ) f on true
),
agg as (
  select
    trade_date,
    stock_code,
    "rank",
    score,
    "trigger",
    signal_close,
    tp_target,
    atr,
    coalesce(max(n), 0)                                       as bars_available,
    max(bar_date)    filter (where n = 1)                     as entry_date,
    coalesce(max(nullif(open_price, 0)) filter (where n = 1),
             max(close_price)           filter (where n = 1)) as entry_ref,
    bool_or(open_price > 0)  filter (where n = 1)             as entry_ref_is_open,
    max(close_price) filter (where n = 1)                     as c1,
    max(close_price) filter (where n = 5)                     as c5,
    max(close_price) filter (where n = 10)                    as c10,
    max(close_price) filter (where n = 20)                    as c20,
    max(bar_date)    filter (where n = 1)                     as d1_date,
    max(bar_date)    filter (where n = 5)                     as d5_date,
    max(bar_date)    filter (where n = 10)                    as d10_date,
    max(bar_date)    filter (where n = 20)                    as d20_date,
    max(high)        filter (where n <= 5)                    as hi5,
    min(low)         filter (where n <= 5)                    as lo5,
    max(high)                                                 as hi20,
    min(low)                                                  as lo20,
    min(n)           filter (where high >= tp_target)         as tp_hit_bar
  from bars
  group by 1, 2, 3, 4, 5, 6, 7, 8
)
select
  a.trade_date,
  a.stock_code,
  a."rank",
  a.score,
  a."trigger",
  a.signal_close,
  a.tp_target,
  a.entry_date,
  a.entry_ref,
  a.entry_ref_is_open,
  a.bars_available,
  round(100 * (a.entry_ref / nullif(a.signal_close, 0) - 1), 2)   as entry_gap_pct,
  round(100 * (a.c1  / nullif(a.entry_ref, 0) - 1), 2)            as ret_1d,
  round(100 * (a.c5  / nullif(a.entry_ref, 0) - 1), 2)            as ret_5d,
  round(100 * (a.c10 / nullif(a.entry_ref, 0) - 1), 2)            as ret_10d,
  round(100 * (a.c20 / nullif(a.entry_ref, 0) - 1), 2)            as ret_20d,
  round(100 * (a.hi5  / nullif(a.entry_ref, 0) - 1), 2)           as mfe_5d,
  round(100 * (a.lo5  / nullif(a.entry_ref, 0) - 1), 2)           as mae_5d,
  round(100 * (a.hi20 / nullif(a.entry_ref, 0) - 1), 2)           as mfe_20d,
  round(100 * (a.lo20 / nullif(a.entry_ref, 0) - 1), 2)           as mae_20d,
  a.tp_hit_bar,
  (a.tp_hit_bar is not null)                                      as hit_tp,
  round(100 * (b1.close  / nullif(b0.close, 0) - 1), 2)           as ihsg_1d,
  round(100 * (b5.close  / nullif(b0.close, 0) - 1), 2)           as ihsg_5d,
  round(100 * (b10.close / nullif(b0.close, 0) - 1), 2)           as ihsg_10d,
  round(100 * (b20.close / nullif(b0.close, 0) - 1), 2)           as ihsg_20d
from agg a
left join public.index_eod b0
  on b0.index_code = 'COMPOSITE' and b0.trade_date = a.trade_date
left join public.index_eod b1
  on b1.index_code = 'COMPOSITE' and b1.trade_date = a.d1_date
left join public.index_eod b5
  on b5.index_code = 'COMPOSITE' and b5.trade_date = a.d5_date
left join public.index_eod b10
  on b10.index_code = 'COMPOSITE' and b10.trade_date = a.d10_date
left join public.index_eod b20
  on b20.index_code = 'COMPOSITE' and b20.trade_date = a.d20_date;

grant select on public.signal_performance to anon, authenticated, service_role;
