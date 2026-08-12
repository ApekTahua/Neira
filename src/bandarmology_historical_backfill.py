"""bandarmology_historical_backfill.py -- LOCAL scrape of Indopremier
broker-summary data, one Parquet file per trading day (see
docs/BANDARMOLOGY_DESIGN.md). Covers BOTH the one-off historical
backfill (2023+) AND ongoing daily collection -- see STATUS below,
2026-08-09 decided this replaces the n8n daily pipeline entirely, not
just the historical gap.

Writes local Parquet, NOT Supabase. Raw per-broker rows are backtest/
research material, not something the website needs to query directly --
no reason to pay for cloud storage/query capacity nobody uses live.
Does not touch broker_summary/brokers on either Supabase project.

Folder layout: data/bandarmology_history/<year>/<month>/<date>.parquet
One file per trading day, all stocks' broker rows for that day in one
file (same column shape as the `broker_summary` table). A day already on
disk is skipped, so an interrupted run just gets re-invoked with the same
year -- no separate checkpoint file needed.

Run one year at a time (the user's own checkpoint boundary):
    SUPABASE_URL=... SUPABASE_KEY=... python src/bandarmology_historical_backfill.py 2023

Needs SUPABASE_URL/SUPABASE_KEY for DB1 (ihsg_eod) ONLY -- to build the
real trading calendar and stock universe per day, same source and same
`volume>0` rule the n8n "Get Stock Universe" node already uses (see
chat 2026-08-09, the ALMI zero-regular-volume decision). Never writes to
Supabase.

STATUS 2026-08-09: fully wired. This REPLACES the n8n daily scrape too
(decided 2026-08-09, see docs/BANDARMOLOGY_DESIGN.md "Architecture
pivot" -- n8n's per-item loop took ~90min for ONE day; a 20-way burst
test against the real endpoint returned all 200s in 0.36s total, proving
the bottleneck was n8n's own execution model, not the source). Because
the day-file-exists check already makes this resumable, running this
same script again later for the current year IS the daily job -- no
separate daily script needed, it just picks up whatever new trading
day(s) appeared since the last run.

Supabase (DB2) now only ever holds the latest trading day (decided
2026-08-09, replacing the earlier "rolling operational window" plan --
see docs/BANDARMOLOGY_DESIGN.md for the still-open follow-up: the
planned rolling accumulation chart needs multi-day history from
SOMEWHERE, proposed as a second small derived-features table, not yet
built/confirmed). This script does not push to Supabase at all -- it is
LOCAL-ONLY. A separate small push step (once the derived-table question
is settled) reads today's freshly-written local Parquet and syncs it.
"""

import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from supabase import create_client

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "bandarmology_history"

# Burst-tested 2026-08-09: 20 concurrent requests against the real
# endpoint, all 200 OK, 0.16-0.33s each, 0.36s total wall time -- no
# rate limiting observed. REQUEST_DELAY_SEC isn't needed for correctness,
# kept as a small courtesy per the user's request.
FETCH_CONCURRENCY = 20
REQUEST_DELAY_SEC = 0.1

BROKERSUMMARY_URL = "https://indopremier.com/module/saham/include/data-brokersummary.php"
BROKERSUMMARY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "*/*",
}

# Two independent passes (not one combined per-row regex) so an uneven
# buy/sell count (one side has fewer than 10 real entries some days)
# doesn't break parsing -- text-up/text-down self-identify which side a
# numeric triplet belongs to regardless of table position.
# Investor-type CSS class (text-local/text-foreign/text-bumn) is present
# in the HTML but deliberately NOT used -- checked 2026-08-09, conflicts
# with the user's own firm-ownership classification on 4 codes
# (BQ/CP/DR/XA showed text-local here despite being Foreign-owned firms
# per brokers_schema.sql), most likely because this tags the
# TRANSACTION's investor origin, not the BROKERAGE FIRM's ownership --
# a different axis. User's call: keep using the manual `brokers` table,
# ignore this entirely.
_SIDE_RE = (
    r'<span class="(?:text-local|text-foreign|text-bumn)">([A-Z]{{1,3}})</span></td>\s*'
    r'<td[^>]*><span class="{cls}">\s*([^<]*?)\s*</span></td>\s*'
    r'<td[^>]*><span class="{cls}">\s*([^<]*?)\s*</span></td>\s*'
    r'<td[^>]*><span class="{cls}">\s*([^<]*?)\s*</span></td>'
)
BUY_RE = re.compile(_SIDE_RE.format(cls="text-up"))
SELL_RE = re.compile(_SIDE_RE.format(cls="text-down"))

CALENDAR_ANCHOR_STOCK = "BBCA"  # always-liquid -- same trick used for progress SQL this session


def get_trading_dates(supabase, year: int) -> list[date]:
    """Real trading dates for `year`, sourced from ihsg_eod via one
    always-liquid stock (no native SELECT DISTINCT over PostgREST,
    same workaround used earlier this session for the progress query)."""
    start, end = f"{year}-01-01", f"{year}-12-31"
    rows, offset = [], 0
    while True:
        batch = (
            supabase.table("ihsg_eod")
            .select("trade_date")
            .eq("stock_code", CALENDAR_ANCHOR_STOCK)
            .gte("trade_date", start)
            .lte("trade_date", end)
            .order("trade_date")
            .range(offset, offset + 999)
            .execute()
        )
        if not batch.data:
            break
        rows.extend(batch.data)
        offset += 1000
    return sorted({date.fromisoformat(r["trade_date"]) for r in rows})


def get_stock_universe(supabase, trade_date: date) -> list[str]:
    """Stocks with real regular-market volume that day -- mirrors the
    n8n Get Stock Universe node (volume>0 filter, see the ALMI decision
    2026-08-09: no broker data wanted for a stock with zero regular
    volume that day, regardless of any off-market Nego/Tunai activity)."""
    rows, offset = [], 0
    while True:
        batch = (
            supabase.table("ihsg_eod")
            .select("stock_code")
            .eq("trade_date", trade_date.isoformat())
            .gt("volume", 0)
            .order("stock_code")
            .range(offset, offset + 999)
            .execute()
        )
        if not batch.data:
            break
        rows.extend(batch.data)
        offset += 1000
    return sorted({r["stock_code"] for r in rows})


def parse_abbrev_num(raw) -> float | None:
    """Port of the n8n Tidy Up Variables parser -- K/M/B/T suffixes
    apply to BOTH lot counts and rupiah values (the bug fixed this
    session: only val_rupiah had this originally, lot needs it too)."""
    if raw is None:
        return None
    s = str(raw).strip().upper().replace(",", "")
    if s in ("", "-", "N/A"):
        return None
    mult = 1.0
    if s.endswith("T"):
        mult, s = 1_000_000_000_000.0, s[:-1]
    elif s.endswith("B"):
        mult, s = 1_000_000_000.0, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000.0, s[:-1]
    elif s.endswith("K"):
        mult, s = 1_000.0, s[:-1]
    s = s.strip()
    try:
        return float(s) * mult
    except ValueError:
        return None


def fetch_broker_summary(session: requests.Session, stock_code: str, trade_date: date) -> list[dict]:
    """One dict per (broker_code, side), matching the `broker_summary`
    table shape: {"stock_code", "broker_code", "side", "lot",
    "val_rupiah", "avg_price"}. `trade_date` is added by the caller.

    Retries transient failures -- at ~851 trading days x ~800 stocks,
    a full run is ~680k requests; without a retry, one dropped request
    silently loses that stock's data for that day and only shows up as
    a smaller-than-expected count in the progress SQL from earlier,
    same class of gap that query was built to catch."""
    d = trade_date.strftime("%m/%d/%Y")  # confirmed MM/DD/YYYY 2026-08-09
    last_err = None
    for attempt in range(3):
        try:
            resp = session.get(
                BROKERSUMMARY_URL,
                params={"code": stock_code, "start": d, "end": d, "fd": "all", "board": "all"},
                headers=BROKERSUMMARY_HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            html = resp.text
            break
        except requests.RequestException as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    else:
        raise last_err

    rows = []
    for side, pattern in (("buy", BUY_RE), ("sell", SELL_RE)):
        for broker_code, lot, val, avg in pattern.findall(html):
            rows.append({
                "stock_code": stock_code,
                "broker_code": broker_code,
                "side": side,
                "lot": parse_abbrev_num(lot),
                "val_rupiah": parse_abbrev_num(val),
                "avg_price": parse_abbrev_num(avg),
            })
    return rows


def day_path(trade_date: date) -> Path:
    return DATA_DIR / f"{trade_date.year}" / f"{trade_date.month:02d}" / f"{trade_date.isoformat()}.parquet"


def backfill_day(session, supabase, trade_date: date) -> None:
    out_path = day_path(trade_date)
    if out_path.exists():
        return  # resumable: already have this day

    stocks = get_stock_universe(supabase, trade_date)
    all_rows: list[dict] = []

    def _fetch_one(stock_code: str) -> list[dict]:
        time.sleep(REQUEST_DELAY_SEC)
        return fetch_broker_summary(session, stock_code, trade_date)

    with ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as pool:
        futures = {pool.submit(_fetch_one, sc): sc for sc in stocks}
        for fut in as_completed(futures):
            stock_code = futures[fut]
            try:
                rows = fut.result()
            except Exception as e:
                print(f"  ! {trade_date} {stock_code}: {e}", file=sys.stderr)
                continue
            for r in rows:
                r["trade_date"] = trade_date.isoformat()
            all_rows.extend(rows)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(all_rows).to_parquet(out_path, index=False)
    print(f"{trade_date}: {len(stocks)} stocks, {len(all_rows)} broker rows -> {out_path}")


def main():
    if len(sys.argv) != 2:
        print("usage: python src/bandarmology_historical_backfill.py <year>", file=sys.stderr)
        sys.exit(1)
    year = int(sys.argv[1])

    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    session = requests.Session()  # no cookies needed -- confirmed 2026-08-09, plain headers work

    trading_dates = get_trading_dates(supabase, year)
    print(f"{year}: {len(trading_dates)} trading dates")

    for d in trading_dates:
        backfill_day(session, supabase, d)


if __name__ == "__main__":
    main()
