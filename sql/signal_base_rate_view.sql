-- signal_base_rate -- the "compared to what" row behind /signal-report: every
-- IDX stock over Rp1bn turnover at Rp50+, on the same dates the screener
-- published signals, scored with the identical entry rule (next session's
-- open, falling back to its close). Without it a signal's 1d/5d return has no
-- baseline and reads as skill when it may only be the market.
--
-- This file exists because the view did NOT have one -- it was created live
-- and never version-controlled, so a rebuild from this repo would not have
-- produced it. The external audit flagged exactly this ("do the same for
-- signal_base_rate if present"); it was present, and it was missing here.
-- Found 2026-09-12. Definition below is pg_get_viewdef's own output for the
-- running view, so replaying this file is a no-op against it.
--
-- security_invoker is ON (audit finding SQL-3): otherwise the view runs as its
-- OWNER and RLS on ihsg_eod / daily_qualifying_signals is bypassed for anyone
-- who can select it. Verified live with an anon-key request returning real
-- rows.

create or replace view public.signal_base_rate as
 WITH dates AS (
         SELECT DISTINCT daily_qualifying_signals.trade_date
           FROM daily_qualifying_signals
        ), universe AS (
         SELECT e.trade_date,
            e.stock_code
           FROM ihsg_eod e
             JOIN dates d ON d.trade_date = e.trade_date
          WHERE e.value >= 1000000000 AND e.close_price >= 50::numeric AND e.high > 0::numeric
        ), fwd AS (
         SELECT u.trade_date,
            u.stock_code,
            COALESCE(max(NULLIF(f.open_price, 0::numeric)) FILTER (WHERE f.n = 1), max(f.close_price) FILTER (WHERE f.n = 1)) AS entry_ref,
            max(f.close_price) FILTER (WHERE f.n = 1) AS c1,
            max(f.close_price) FILTER (WHERE f.n = 5) AS c5
           FROM universe u
             LEFT JOIN LATERAL ( SELECT e.open_price,
                    e.close_price,
                    row_number() OVER (ORDER BY e.trade_date) AS n
                   FROM ihsg_eod e
                  WHERE e.stock_code::text = u.stock_code::text AND e.trade_date > u.trade_date AND e.high > 0::numeric AND e.low > 0::numeric AND e.close_price > 0::numeric
                  ORDER BY e.trade_date
                 LIMIT 5) f ON true
          GROUP BY u.trade_date, u.stock_code
        )
 SELECT trade_date,
    count(*) AS universe_size,
    count(c1) AS n_1d,
    round(avg(100::numeric * (c1 / NULLIF(entry_ref, 0::numeric) - 1::numeric)), 2) AS base_ret_1d,
    round(100.0 * count(*) FILTER (WHERE c1 > entry_ref)::numeric / NULLIF(count(c1), 0)::numeric, 1) AS base_win_1d,
    count(c5) AS n_5d,
    round(avg(100::numeric * (c5 / NULLIF(entry_ref, 0::numeric) - 1::numeric)), 2) AS base_ret_5d,
    round(100.0 * count(*) FILTER (WHERE c5 > entry_ref)::numeric / NULLIF(count(c5), 0)::numeric, 1) AS base_win_5d
   FROM fwd
  GROUP BY trade_date;

alter view public.signal_base_rate set (security_invoker = on);
