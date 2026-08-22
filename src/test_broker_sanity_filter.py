"""test_broker_sanity_filter.py -- one runnable check for
bandarmology_features.filter_corrupt_rows(): real PACK numbers (confirmed
corrupted, 2026-08-22 audit -- see that module's own comment) must get
dropped; a normal day must survive untouched. No network -- `eod` here is a
synthetic, already-loaded band, matching exactly what filter_corrupt_rows()
consumes (the network fetch itself lives in load_eod_bands(), which needs
real Supabase credentials and isn't exercised here).

Usage: python src/test_broker_sanity_filter.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402


def demo():
    raw = pd.DataFrame([
        # PACK 2026-07-24, real ihsg_eod: close=234 high=240 low=214
        # volume=196,407,600 shares (~1,964,076 lots). This broker row (a
        # Nego-style buy at Rp99, ~9.1M lots -- 4.6x real volume) is real
        # data pulled from broker_summary_history the same day -- must drop.
        {"stock_code": "PACK", "trade_date": pd.Timestamp("2026-07-24").date(),
         "broker_code": "XX", "side": "buy", "lot": 9_095_090, "val_rupiah": 900_414_910, "avg_price": 99.0},
        # BBCA 2026-08-21, real ihsg_eod: close=6450 high=6475 low=6400
        # volume=100,684,300. A plausible, ordinary broker row -- must survive.
        {"stock_code": "BBCA", "trade_date": pd.Timestamp("2026-08-21").date(),
         "broker_code": "YY", "side": "buy", "lot": 50_000, "val_rupiah": 322_500_000, "avg_price": 6450.0},
    ])
    eod = pd.DataFrame([
        {"stock_code": "PACK", "trade_date": pd.Timestamp("2026-07-24").date(),
         "high": 240.0, "low": 214.0, "volume": 196_407_600.0},
        {"stock_code": "BBCA", "trade_date": pd.Timestamp("2026-08-21").date(),
         "high": 6475.0, "low": 6400.0, "volume": 100_684_300.0},
    ])
    clean = bf.filter_corrupt_rows(raw, eod, verbose=False)
    assert list(clean["stock_code"]) == ["BBCA"], f"expected only BBCA to survive, got {list(clean['stock_code'])}"

    # A (stock_code, trade_date) with NO real ihsg_eod reference at all (e.g.
    # a code load_eod_bands didn't cover that day) must be KEPT, not dropped
    # -- "can't judge" is not the same as "suspect".
    raw2 = pd.DataFrame([
        {"stock_code": "ZZZZ", "trade_date": pd.Timestamp("2026-01-01").date(),
         "broker_code": "XX", "side": "buy", "lot": 999_999_999, "val_rupiah": 1, "avg_price": 1.0},
    ])
    eod2 = pd.DataFrame(columns=["stock_code", "trade_date", "high", "low", "volume"])
    clean2 = bf.filter_corrupt_rows(raw2, eod2, verbose=False)
    assert len(clean2) == 1, "row with no real-market reference must be kept, not dropped"

    # A big-but-real Nego block on an illiquid name (price still inside the
    # day's real band) must survive -- volume alone, with a plausible price,
    # is exactly the "legitimate Nego block" case this filter deliberately
    # tolerates (see module comment on the volume check being a backstop,
    # not a tight bound).
    raw3 = pd.DataFrame([
        {"stock_code": "SMMA", "trade_date": pd.Timestamp("2026-06-02").date(),
         "broker_code": "XX", "side": "buy", "lot": 100_868, "val_rupiah": 1, "avg_price": 17_950.0},
    ])
    eod3 = pd.DataFrame([
        {"stock_code": "SMMA", "trade_date": pd.Timestamp("2026-06-02").date(),
         "high": 18_000.0, "low": 17_950.0, "volume": 1_300.0},  # real_lot = 13
    ])
    clean3 = bf.filter_corrupt_rows(raw3, eod3, verbose=False)
    assert len(clean3) == 0, "100,868 lots vs 13 real lots (7,759x) must be dropped even with a plausible price"

    print("test_broker_sanity_filter: OK")


if __name__ == "__main__":
    demo()
