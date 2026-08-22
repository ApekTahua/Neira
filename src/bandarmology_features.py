"""bandarmology_features.py -- prototype feature pipeline over the local
Parquet broker-summary history (see docs/BANDARMOLOGY_DESIGN.md). Reads
data/bandarmology_history/**/*.parquet, computes per (stock_code,
trade_date):
  - net_lot, net_val: buy-sell netted, summed across all brokers
    (crossing self-cancels automatically, see design doc point 1)
  - turnover_lot: buy+sell, the churn/rebalancing signal (design doc
    point 2)
  - concentration: the single biggest broker's |net| as a share of
    total |net| across brokers that day (one dominant player vs broad
    participation)
Then rolling per stock (WINDOW trading days):
  - net_flow_norm: rolling sum of net_val / that window's own turnover
    (magnitude, scale-free so stocks aren't compared in raw Rupiah)
  - consistency: days net_lot > 0 / active days in the window
    (design doc point 3 -- persistence over a single lucky day)

Started as prototype code; `load_raw()`'s output now actually feeds the live
site via bandarmology_push_daily.py/_cluster_detector.py/_rotation_detector.py/
_broker_profile.py (all call `bf.load_raw()` or `bf.load_raw_clean()`) --
this docstring line was stale, corrected 2026-08-22.

Run directly: python src/bandarmology_features.py
"""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "bandarmology_history"
WINDOW = 10  # trading days -- placeholder, see design doc "Open questions"

# ---- Corrupted-row sanity filter (added 2026-08-22) ----
# broker_summary/broker_summary_history (DB2, n8n-scraped from Indopremier's
# data-brokersummary.php with board=all -- see sql/broker_summary_schema.sql)
# has NO segment flag distinguishing a real regular-market trade from a
# privately-negotiated one (Nego/Tunai board, rights issues, private
# placements) at an arbitrary price/lot count -- that comment already
# documents this as deliberate (Nego deals are a real bandarmology signal,
# not noise to filter blindly), but with no flag, a corrupted row is
# indistinguishable from a real large Nego block without checking it against
# the day's real exchange print.
#
# Confirmed real, not rare: PACK 2026-07-24..2026-08-18 shows a recurring
# broker avg_price of ~Rp99-101 against a real ihsg_eod day range of
# Rp214-386 (a >50% deviation -- there's no legitimate Nego discount that
# large), and buy-side lot counts up to 24.8x that day's real exchange
# volume (2026-08-04). A 12-sampled-date scan of the WHOLE universe
# (2026-05-25..2026-08-21) found this on 2.74% of all (stock, day) pairs
# checked, concentrated in a recurring ~100-ticker subset (GOTO, APIC, SMMA,
# YULE, BOGA, CASA, OBMD, BBHI, MKPI, MORA, NSSS, CARE flagged on 5-8 of 12
# sampled dates each) -- not a one-off PACK incident.
#
# Two independent checks, at different confidence: PRICE is the strong,
# almost-unambiguous signal (a REAL trade's average price mathematically
# can't fall far outside that day's own recorded [low, high] -- those are
# themselves the min/max of all real trades that day). VOLUME is a much
# more generous backstop -- a genuinely huge Nego block on an illiquid stock
# CAN legitimately dwarf a thin regular-market print (same schema comment
# above), so this only catches the truly implausible end (PACK's 4.6x-24.8x
# range), not ordinary Nego-heavy illiquid names.
#
# ponytail: fixed multiplier bands (not per-stock or per-liquidity
# calibrated) -- reasonable given the evidence above, not statistically
# tuned. Revisit if a specific ticker turns out to have a legitimately wide
# Nego band that this wrongly excludes.
PRICE_BAND_LO = 0.7
PRICE_BAND_HI = 1.3
VOLUME_IMPLAUSIBLE_MULT = 10  # lot count > this x the day's real exchange volume
_EOD_FETCH_CONCURRENCY = 12  # same 12-worker convention as data_fetch.py's own Supabase fetch helper


def load_raw() -> pd.DataFrame:
    """Pure local-file read, no network -- deliberately left unfiltered (see
    load_raw_clean() below) so this stays usable offline/for debugging the
    real archived data, including the corrupted rows themselves."""
    files = sorted(DATA_DIR.glob("*/*/*.parquet"))
    if not files:
        raise SystemExit(f"no parquet files under {DATA_DIR} yet -- run the backfill first")
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


def load_eod_bands(stock_codes: list[str], start: str, end: str) -> pd.DataFrame:
    """trade_date/stock_code/high/low/volume from ihsg_eod (DB1) -- the real-
    market reference filter_corrupt_rows() checks broker rows against. One
    query per stock code (a single stock's full 2020-2026 history is well
    under PostgREST's 1000-row page cap, same reasoning as
    diagnose_bandarmology_power.py's load_prices), fired concurrently
    (data_fetch.py's proven pattern) since the ~950-stock universe run
    serially would take many minutes."""
    from dotenv import load_dotenv
    load_dotenv()
    from supabase import create_client
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    def _fetch_one(code):
        rows, offset = [], 0
        while True:
            batch = (
                supabase.table("ihsg_eod")
                .select("trade_date,close_price,high,low,volume")
                .eq("stock_code", code)
                .gte("trade_date", start).lte("trade_date", end)
                .range(offset, offset + 999)
                .execute()
            )
            if not batch.data:
                break
            rows.extend({**r, "stock_code": code} for r in batch.data)
            if len(batch.data) < 1000:
                break
            offset += 1000
        return rows

    all_rows = []
    with ThreadPoolExecutor(max_workers=_EOD_FETCH_CONCURRENCY) as pool:
        for rows in pool.map(_fetch_one, stock_codes):
            all_rows.extend(rows)
    df = pd.DataFrame(all_rows)
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    for c in ("close_price", "high", "low", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Same get_bar-style sanitizing backtest.py/backtest_v4.py already use for
    # this exact upstream gap (see docs/V3_FINDINGS_LOG.md's open_price=0
    # audit) -- a 0/missing/out-of-order high or low is itself missing data,
    # not a real Rp0 print; fall back to close so the band check below has a
    # real number instead of a fabricated [0, close] or [close, 0] band.
    df["high"] = df["high"].where(df["high"] > 0, df["close_price"])
    df["low"] = df["low"].where((df["low"] > 0) & (df["low"] <= df["high"]), df["close_price"])
    return df[["stock_code", "trade_date", "high", "low", "volume"]]


def filter_corrupt_rows(raw: pd.DataFrame, eod: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """Drops rows whose reported avg_price/lot can't be reconciled with that
    day's real ihsg_eod print -- see the module-level comment above for what
    this catches and why. Pure (no network) so it's independently testable
    against a synthetic `eod` -- see test_broker_sanity_filter.py. A
    (stock_code, trade_date) with no `eod` reference at all (e.g. a code
    load_eod_bands didn't cover) is never flagged -- "can't judge" is not the
    same as "suspect"."""
    if eod.empty:
        if verbose:
            print("[filter_corrupt_rows] no ihsg_eod reference data -- skipping filter, returning raw unchanged")
        return raw

    tagged = raw.reset_index(drop=True)
    tagged["_row_id"] = tagged.index
    merged = tagged.merge(eod, on=["stock_code", "trade_date"], how="left", suffixes=("", "_eod"))

    has_ref = merged["low"].notna() & merged["high"].notna() & (merged["low"] > 0) & (merged["high"] > 0)
    price_bad = has_ref & merged["avg_price"].notna() & (
        (merged["avg_price"] < merged["low"] * PRICE_BAND_LO) | (merged["avg_price"] > merged["high"] * PRICE_BAND_HI)
    )
    real_lot = merged["volume"].fillna(0) / 100.0  # IDX: 1 lot = 100 shares
    vol_bad = has_ref & (real_lot > 0) & (merged["lot"] > real_lot * VOLUME_IMPLAUSIBLE_MULT)
    suspect_ids = set(merged.loc[price_bad | vol_bad, "_row_id"])

    if verbose and suspect_ids:
        n, total = len(suspect_ids), len(tagged)
        print(f"[filter_corrupt_rows] dropping {n}/{total} broker rows ({100*n/total:.2f}%) as price/volume-"
              f"implausible vs real ihsg_eod (price outside [{PRICE_BAND_LO}x,{PRICE_BAND_HI}x] day range, "
              f"or lot > {VOLUME_IMPLAUSIBLE_MULT}x real volume)")
    return tagged.loc[~tagged["_row_id"].isin(suspect_ids)].drop(columns="_row_id").reset_index(drop=True)


def load_raw_clean() -> pd.DataFrame:
    """load_raw() + the real-market sanity filter, in one call -- what every
    current consumer (bandarmology_push_daily.py, _cluster_detector.py,
    _rotation_detector.py, _broker_profile.py) should call instead of
    load_raw() alone."""
    raw = load_raw()
    eod = load_eod_bands(sorted(raw["stock_code"].unique()), raw["trade_date"].min().isoformat(), raw["trade_date"].max().isoformat())
    return filter_corrupt_rows(raw, eod)


def per_broker_net(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per (trade_date, stock_code, broker_code): net_lot/net_val
    = buy - sell. A broker on only one side that day gets a 0 on the
    other (crossing and one-sided activity both handled the same way)."""
    pivot = raw.pivot_table(
        index=["trade_date", "stock_code", "broker_code"],
        columns="side",
        values=["lot", "val_rupiah"],
        aggfunc="sum",
        fill_value=0,
    )
    pivot.columns = [f"{a}_{b}" for a, b in pivot.columns]
    pivot = pivot.reset_index()
    for col in ("lot_buy", "lot_sell", "val_rupiah_buy", "val_rupiah_sell"):
        if col not in pivot.columns:
            pivot[col] = 0
    pivot["net_lot"] = pivot["lot_buy"] - pivot["lot_sell"]
    pivot["net_val"] = pivot["val_rupiah_buy"] - pivot["val_rupiah_sell"]
    pivot["turnover_lot"] = pivot["lot_buy"] + pivot["lot_sell"]
    return pivot


def daily_stock_features(broker_net: pd.DataFrame) -> pd.DataFrame:
    """One row per (trade_date, stock_code): summed net/turnover across
    brokers, plus concentration (top-1 broker's share of total |net|)."""
    g = broker_net.groupby(["trade_date", "stock_code"])

    def concentration(sub: pd.DataFrame) -> float:
        abs_net = sub["net_lot"].abs()
        total = abs_net.sum()
        return abs_net.max() / total if total > 0 else 0.0

    out = g.agg(net_lot=("net_lot", "sum"), net_val=("net_val", "sum"),
                turnover_lot=("turnover_lot", "sum")).reset_index()
    conc = g.apply(concentration, include_groups=False).reset_index(name="concentration")
    return out.merge(conc, on=["trade_date", "stock_code"])


def rolling_features(daily: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    """Adds rolling net_flow_norm + consistency per stock, chronological
    order required (assumes `daily` already covers a contiguous or
    near-contiguous trading history per stock -- gaps from a stock not
    trading some days are tolerated, just fewer active days that window)."""
    daily = daily.sort_values(["stock_code", "trade_date"])

    parts = []
    for _, sub in daily.groupby("stock_code"):
        sub = sub.copy()
        net_sum = sub["net_val"].rolling(window, min_periods=1).sum()
        turnover_sum = sub["turnover_lot"].abs().rolling(window, min_periods=1).sum()
        sub["net_flow_norm"] = net_sum / turnover_sum.replace(0, pd.NA)
        sub["consistency"] = (sub["net_lot"] > 0).rolling(window, min_periods=1).mean()
        parts.append(sub)
    return pd.concat(parts, ignore_index=True)


def main():
    raw = load_raw()
    print(f"raw rows: {len(raw)}, dates: {raw['trade_date'].min()} to {raw['trade_date'].max()}, "
          f"stocks: {raw['stock_code'].nunique()}")

    broker_net = per_broker_net(raw)
    daily = daily_stock_features(broker_net)
    feats = rolling_features(daily)

    print(f"\nfeature rows: {len(feats)}")
    print(feats.head(10).to_string(index=False))

    for code in ("BBCA", "DOOH", "SMLE"):
        sub = feats[feats["stock_code"] == code].tail(5)
        if sub.empty:
            continue
        print(f"\n--- {code}, last 5 rows in local data ---")
        print(sub.to_string(index=False))


if __name__ == "__main__":
    main()
