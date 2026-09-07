-- public.stock_price_limit
--
-- Each stock's own IDX auto-reject ceiling (ARA), inferred from its trading
-- history. Read by newscraper.ai's stock page and screener so the site's ARA
-- badge gives the same answer backtest_v4.py already computes internally
-- (ARA_FILTER_ENABLED / is_ara_locked), rather than a second, worse model.
--
-- WHY THE PRICE TIER IS NOT ENOUGH. IDX enforces four steps -- 10, 20, 25 and
-- 35 percent. Measured over the last ~400 sessions, 91 stocks cap near 10%
-- while sitting at prices whose tier implies 25% or 35%, and the board label
-- does not identify them either: Akselerasi caps near 10% for 97.3% of its
-- members, Pemantauan Khusus for only 31.0%. A tier-only model therefore misses
-- every 10%-board stock. It never produces a false positive (such a stock
-- cannot reach 25%), so the failure is under-reporting -- but on 2026-09-04
-- five stocks closed at a 10% ceiling (PPGL, KING, MGLV, MSIE, EURO) and a
-- tier-only badge flagged none of them. PPGL was an open V4_PAPER position.
--
-- THE RULE. Snap the stock's MAXIMUM single-session gain to a step, then
-- require that same step to have been reached at least twice. A limit is where
-- moves STOP, not where they pass. Stocks failing either test return NULL and
-- callers fall back to the price tier, which is the conservative direction: a
-- stock that has never sat on a ceiling also cannot be mistaken for locked.
--
-- TWO EARLIER VERSIONS WERE WRONG, recorded so they are not reintroduced:
--   1. Snapping the max to any step within 3.5pp gave BBCA a 10% limit off a
--      single 9.71% day. It is a calm blue chip, not a 10%-board stock.
--   2. Taking the highest step touched twice gave EKAD a 25% limit despite a
--      34.83% max, because a 35%-board stock passes THROUGH the lower bands on
--      its way up.
--
-- COST. An earlier shape referenced a `moves` CTE twice (aggregate + LATERAL
-- touch count), which made Postgres materialise it and scan all ~230,000 rows
-- of the window before the caller's stock_code filter could apply: 2.0 s to
-- return five tickers, on a page that calls it on every load, on a project that
-- has already hit an egress quota once. Folding both into a single GROUP BY
-- with conditional aggregates lets the filter push down into unique_stock_date:
-- 2,017 ms -> 64 ms, 230,619 rows scanned -> 1,820, same answers.
create or replace view public.stock_price_limit as
with per_stock as (
  select
    stock_code,
    count(*) as sessions,
    max(100.0 * (close_price - previous) / nullif(previous, 0)) as max_gain,
    count(*) filter (where 100.0 * (close_price - previous) / nullif(previous, 0)
                           between  9.0 and 10.6) as n10,
    count(*) filter (where 100.0 * (close_price - previous) / nullif(previous, 0)
                           between 19.0 and 20.6) as n20,
    count(*) filter (where 100.0 * (close_price - previous) / nullif(previous, 0)
                           between 24.0 and 25.6) as n25,
    count(*) filter (where 100.0 * (close_price - previous) / nullif(previous, 0)
                           between 34.0 and 35.6) as n35
  from ihsg_eod
  where trade_date >= current_date - 400
    and trade_date < current_date
    and previous >= 50
    and close_price > 0
  group by stock_code
  having count(*) >= 60
)
select
  stock_code,
  round(max_gain::numeric, 2) as max_gain_pct,
  sessions,
  case
    when max_gain between 34.0 and 35.6 and n35 >= 2 then 35
    when max_gain between 24.0 and 25.6 and n25 >= 2 then 25
    when max_gain between 19.0 and 20.6 and n20 >= 2 then 20
    when max_gain between  9.0 and 10.6 and n10 >= 2 then 10
    else null
  end as observed_limit_pct
from per_stock;
