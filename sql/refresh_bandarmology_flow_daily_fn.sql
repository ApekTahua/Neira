-- Computes ONE day's row in bandarmology_flow_daily directly from
-- broker_summary (raw, that day's rows) + bandarmology_flow_daily's own
-- trail_rows history (for the rolling window + running cumulative) --
-- entirely in SQL so the daily n8n workflow doesn't need to replicate
-- the rolling-window math in a Code node (that's where every real bug
-- happened earlier this session: empty-array handling, abbreviated-
-- number parsing, etc -- less n8n logic, less surface for that class
-- of bug).
--
-- n8n's daily job becomes: scrape today -> upsert broker_summary ->
-- POST to /rest/v1/rpc/refresh_bandarmology_flow_daily with
-- {"p_trade_date": "<today>"}. One more HTTP node, nothing else.
--
-- Idempotent (on_conflict upsert) -- safe to call twice for the same
-- date if a run is retried.

create or replace function refresh_bandarmology_flow_daily(
  p_trade_date date,
  p_window int default 10
) returns void
language plpgsql
as $$
begin
  with today_broker_net as (
    select
      stock_code,
      broker_code,
      coalesce(sum(lot) filter (where side = 'buy'), 0) - coalesce(sum(lot) filter (where side = 'sell'), 0) as net_lot,
      coalesce(sum(val_rupiah) filter (where side = 'buy'), 0) - coalesce(sum(val_rupiah) filter (where side = 'sell'), 0) as net_val,
      coalesce(sum(lot) filter (where side = 'buy'), 0) + coalesce(sum(lot) filter (where side = 'sell'), 0) as turnover_lot
    from broker_summary
    where trade_date = p_trade_date
    group by stock_code, broker_code
  ),
  today_stock as (
    select
      stock_code,
      sum(net_lot)::bigint as net_lot,
      sum(net_val)::bigint as net_val,
      sum(turnover_lot)::bigint as turnover_lot,
      case when sum(abs(net_lot)) > 0
        then max(abs(net_lot))::numeric / sum(abs(net_lot))
        else 0 end as concentration
    from today_broker_net
    group by stock_code
  ),
  combined as (
    select stock_code, trade_date, net_lot, net_val, turnover_lot
    from bandarmology_flow_daily
    where trade_date < p_trade_date
      and stock_code in (select stock_code from today_stock)
    union all
    select stock_code, p_trade_date, net_lot, net_val, turnover_lot from today_stock
  ),
  ranked as (
    select *, row_number() over (partition by stock_code order by trade_date desc) as rn
    from combined
  ),
  trail_rows as (
    select * from ranked where rn <= p_window
  ),
  rolled as (
    select
      stock_code,
      sum(net_val) as roll_net_val,
      sum(abs(turnover_lot)) as roll_turnover,
      avg((net_lot > 0)::int)::numeric as consistency
    from trail_rows
    group by stock_code
  ),
  prev_cum as (
    select distinct on (stock_code) stock_code, cumulative_net_val
    from bandarmology_flow_daily
    where trade_date < p_trade_date
    order by stock_code, trade_date desc
  )
  insert into bandarmology_flow_daily (
    stock_code, trade_date, net_lot, net_val, turnover_lot,
    concentration, net_flow_norm, consistency, cumulative_net_val
  )
  select
    t.stock_code, p_trade_date, t.net_lot, t.net_val, t.turnover_lot, t.concentration,
    case when r.roll_turnover > 0 then r.roll_net_val / r.roll_turnover else null end,
    r.consistency,
    coalesce(pc.cumulative_net_val, 0) + t.net_val
  from today_stock t
  join rolled r on r.stock_code = t.stock_code
  left join prev_cum pc on pc.stock_code = t.stock_code
  on conflict (stock_code, trade_date) do update set
    net_lot = excluded.net_lot,
    net_val = excluded.net_val,
    turnover_lot = excluded.turnover_lot,
    concentration = excluded.concentration,
    net_flow_norm = excluded.net_flow_norm,
    consistency = excluded.consistency,
    cumulative_net_val = excluded.cumulative_net_val,
    computed_at = now();
end;
$$;
