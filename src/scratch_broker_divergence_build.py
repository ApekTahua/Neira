"""scratch_broker_divergence_build.py -- SCRATCH/RESEARCH ONLY. Builds the
PER-STOCK, PER-DAY "smart money divergence" feature the user (a real IHSG
trader) proposed: on a given stock, is FOREIGN money net buying WHILE the
top RETAIL brokers (XL/XC/PD specifically -- named by the user, not silently
expanded to other Local codes) are net selling, at the same time.

Structurally different from the REJECTED market-wide broker-flow gate
(docs/V3_FINDINGS_LOG.md 2026-08-25) in two ways: (1) per-STOCK not
market-wide aggregate, (2) a DIVERGENCE between two specific broker subsets,
not one aggregate direction.

Units traced: val_rupiah is real Rupiah (already confirmed 2026-08-25, see
findings log). Every ratio here is (Rupiah net) / (that SAME stock's own
total same-day turnover, all brokers, both sides) -- scale-free, bounded
[-1,1] per leg, comparable across stocks of very different size. This is a
deliberately different normalizer from the market-wide feature (which used
the whole liquid universe's turnover) -- per-stock has to use per-stock
turnover or a big-cap's Rupiah volume would swamp a small-cap's in a naive
sum.

Output: .cache/broker_divergence_by_stock.pkl -- one row per (stock_code,
trade_date) that appears in the walk-forward dataset, columns:
  foreign_net, retail_net, total_turnover        (raw Rupiah, window=1)
  divergence_{w}d, flag_{w}d   for w in (1, 3, 5, 10)
    divergence_w = (foreign_net_sum_w - retail_net_sum_w) / turnover_sum_w
      (rolling SUM of value over the trailing w trading days for this stock,
      THEN ratio -- not a rolling mean of daily ratios -- more robust to
      thin/zero-activity single days for a single ticker than the market-
      wide feature's rolling-mean-of-ratio design, which is fine at market
      aggregate scale but would let sparse per-stock days dominate here.)
    flag_w = (foreign_net_sum_w > 0) & (retail_net_sum_w < 0)  -- sign of
      the WINDOW's cumulative net, not "every single day in the window was
      individually divergent" (a stricter, redundant third shape -- skipped,
      see report).

Run directly: python src/scratch_broker_divergence_build.py
"""
import pickle

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

import config as cfg  # noqa: F401  (kept for parity with sibling scripts; ADTV filtering NOT applied here on purpose, see module docstring)
from bandarmology_features import filter_corrupt_rows

DATA_DIR = "data/bandarmology_history"
CACHE_PATH = ".cache/walk_forward_data_2021-01-01_2026-06-30.pkl"
OUT_PATH = ".cache/broker_divergence_by_stock.pkl"

# From sql/brokers_schema.sql (2026-08-09, user-confirmed authoritative list) -- static,
# hardcoded per the task brief's own instruction (short values list, safe to hardcode).
FOREIGN_CODES = frozenset({
    "AK", "ZP", "YP", "CP", "BK", "YU", "RX", "HD", "KK", "BQ", "DR", "XA", "KZ", "TP",
    "AG", "AI", "LS", "RB", "FS", "DP", "DU", "GI", "AH", "BW", "CG", "CS", "DB", "FG",
    "GW", "LH", "ML", "MS",
})
assert len(FOREIGN_CODES) == 32, "must match brokers_schema.sql's documented 32 Foreign codes"

# The user named these three explicitly ("XL XC PD Top retail brokers") -- do NOT
# silently expand to other Local codes (Mandiri/Sinarmas/Panin etc are Local but not
# retail-app brokers). A wider-Local variant is a separate thing to test, not this.
RETAIL_CODES = frozenset({"XL", "XC", "PD"})

WINDOWS = (1, 3, 5, 10)


def load_broker_raw() -> pd.DataFrame:
    """Column-projected pyarrow scan, same fast pattern as
    scratch_market_flow_build.py's load_broker_raw() (~3s for 18.8M rows) --
    just with broker_code added, needed here to split Foreign/retail/other."""
    dataset = ds.dataset(DATA_DIR, format="parquet")
    raw = dataset.to_table(
        columns=["stock_code", "broker_code", "side", "lot", "avg_price", "val_rupiah", "trade_date"]
    ).to_pandas()
    raw["trade_date"] = pd.to_datetime(raw["trade_date"]).dt.date
    return raw


def _net_and_turnover(raw: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """One row per (trade_date, stock_code): {prefix}_net (buy-sell), {prefix}_turnover (buy+sell)."""
    g = raw.groupby(["trade_date", "stock_code", "side"])["val_rupiah"].sum().unstack("side", fill_value=0.0)
    out = pd.DataFrame({
        f"{prefix}_net": g.get("buy", 0.0) - g.get("sell", 0.0),
        f"{prefix}_turnover": g.get("buy", 0.0) + g.get("sell", 0.0),
    }).reset_index()
    return out


def build() -> pd.DataFrame:
    with open(CACHE_PATH, "rb") as f:
        df, _idx_df = pickle.load(f)

    raw = load_broker_raw()
    eod_ref = df[["stock_code", "trade_date", "high", "low", "volume"]].drop_duplicates(
        ["stock_code", "trade_date"]).copy()
    eod_ref["high"] = eod_ref["high"].where(eod_ref["high"] > 0, df["close_price"])
    eod_ref["low"] = eod_ref["low"].where((eod_ref["low"] > 0) & (eod_ref["low"] <= eod_ref["high"]), df["close_price"])
    raw = filter_corrupt_rows(raw, eod_ref)

    total = _net_and_turnover(raw, "total")  # every broker, both investor types + BUMN -- the per-stock normalizer
    foreign = _net_and_turnover(raw[raw["broker_code"].isin(FOREIGN_CODES)], "foreign")
    retail = _net_and_turnover(raw[raw["broker_code"].isin(RETAIL_CODES)], "retail")

    panel = df[["stock_code", "trade_date"]].drop_duplicates().copy()
    panel = panel.merge(total[["trade_date", "stock_code", "total_turnover"]], on=["trade_date", "stock_code"], how="left")
    panel = panel.merge(foreign[["trade_date", "stock_code", "foreign_net"]], on=["trade_date", "stock_code"], how="left")
    panel = panel.merge(retail[["trade_date", "stock_code", "retail_net"]], on=["trade_date", "stock_code"], how="left")
    # A (stock,day) with no matching broker rows at all in one of these subsets is a genuine
    # zero (that broker subset traded nothing in that stock that day), not missing data.
    for c in ("total_turnover", "foreign_net", "retail_net"):
        panel[c] = panel[c].fillna(0.0)

    panel = panel.sort_values(["stock_code", "trade_date"]).reset_index(drop=True)
    g = panel.groupby("stock_code", sort=False)

    for w in WINDOWS:
        fn_sum = g["foreign_net"].transform(lambda s: s.rolling(w, min_periods=w).sum())
        rn_sum = g["retail_net"].transform(lambda s: s.rolling(w, min_periods=w).sum())
        tt_sum = g["total_turnover"].transform(lambda s: s.rolling(w, min_periods=w).sum())
        panel[f"divergence_{w}d"] = (fn_sum - rn_sum) / tt_sum.replace(0, np.nan)
        flag = (fn_sum > 0) & (rn_sum < 0)
        # fn_sum/rn_sum/tt_sum share the same NaN rows (all three rolled from fillna(0)
        # inputs, so only min_periods=w start-of-series rows are NaN) -- mask those to
        # "unknown" rather than a fake False, no window history yet.
        panel[f"flag_{w}d"] = flag.where(tt_sum.notna())

    return panel


def sanity_check(panel: pd.DataFrame):
    print(f"panel: {len(panel)} (stock,day) rows, {panel['stock_code'].nunique()} stocks, "
          f"{panel['trade_date'].min()} .. {panel['trade_date'].max()}")
    for w in WINDOWS:
        s = panel[f"divergence_{w}d"].dropna()
        flag = panel[f"flag_{w}d"].dropna()
        print(f"\n--- divergence_{w}d (n={len(s)}) ---")
        print(s.describe(percentiles=[.01, .05, .25, .5, .75, .95, .99]).to_string())
        print(f"flag_{w}d True rate: {flag.mean():.1%} (n={len(flag)})")


if __name__ == "__main__":
    panel = build()
    panel.to_pickle(OUT_PATH)
    print(f"[OK] saved {OUT_PATH}")
    sanity_check(panel)
