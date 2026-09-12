-- market_marquee -- the 40 names the site's ticker strip scrolls, biggest
-- turnover first, one row per stock at its freshest ihsg_realtime timestamp.
--
-- This file exists because the view did NOT have one. It was created live and
-- never version-controlled, so rebuilding the database from this repo would
-- simply not have produced it -- found 2026-09-12 while proving that the repo
-- reproduces live state exactly. Definition below is pg_get_viewdef's own
-- output for the running view, so replaying this file is a no-op against it.
--
-- security_invoker is ON: without it the view runs as its OWNER and RLS on
-- ihsg_realtime is bypassed for anyone who can select it (audit finding
-- SQL-3). Verified live with a real anon-key request returning real rows --
-- an empty 200 is what a silently-blocked read looks like, so row content is
-- the test, not the status code.

create or replace view public.market_marquee as
 WITH freshest AS (
         SELECT DISTINCT ON (ihsg_realtime.stock_code) ihsg_realtime.stock_code,
            ihsg_realtime.close,
            ihsg_realtime.change_percentage,
            ihsg_realtime.color,
            ihsg_realtime.volume,
            ihsg_realtime.updated_at,
            ihsg_realtime.change
           FROM ihsg_realtime
          WHERE ihsg_realtime.volume > 0 AND ihsg_realtime.close > 0::numeric
          ORDER BY ihsg_realtime.stock_code, ihsg_realtime.updated_at DESC
        )
 SELECT stock_code,
    close,
    change_percentage,
    color,
    updated_at,
    change
   FROM freshest
  ORDER BY (volume::numeric * close) DESC
 LIMIT 40;

alter view public.market_marquee set (security_invoker = on);
