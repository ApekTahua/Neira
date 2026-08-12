"""diagnose_bandarmology_2025_split.py -- tests the user's "2025 turning
point" claim (2026-08-12 domain conversation, docs/BANDARMOLOGY_DESIGN.md):
mostly-retail broker codes (XL/CC/XC/MG/YP) allegedly became the dominant
stock movers starting around 2025, a possible sign of bandar disguising
activity inside retail-labeled accounts. Not checkable directly (would
need per-trade execution size, which this project doesn't have -- see
the user's own caveat) but checkable INDIRECTLY: did the COMPOSITION of
flagged mover_pairs shift toward these five codes after 2025?

Splits the full mover-pair detection into two independent windows
(2023-01-02..2024-12-31 "pre", 2025-01-01..latest "post") and compares
each retail code's share of ALL candidate-mover flags in each window.
A real compositional shift shows up as a rising share; a flat share
across both windows argues against the "turning point" framing (retail
codes may just always have been broadly active, per broker_characteristics'
own active_stock_count numbers, without a real regime change).

Usage: python src/diagnose_bandarmology_2025_split.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402
from diagnose_bandarmology_power import load_prices, add_forward_returns  # noqa: E402
from bandarmology_broker_profile import per_broker_daily, candidate_movers  # noqa: E402

RETAIL_CODES = {"XL", "CC", "XC", "MG", "YP"}
SPLIT_DATE = pd.Timestamp("2025-01-01").date()


def movers_for_window(raw: pd.DataFrame, label: str) -> pd.DataFrame:
    stock_codes = raw["stock_code"].unique().tolist()
    start = raw["trade_date"].min().isoformat()
    end = raw["trade_date"].max().isoformat()
    print(f"[{label}] loading prices for {len(stock_codes)} stocks, {start} to {end}...")
    prices = load_prices(stock_codes, start, end)
    prices = add_forward_returns(prices)
    broker_daily = per_broker_daily(raw)
    movers = candidate_movers(broker_daily, prices)
    movers = movers[movers["candidate_mover"]]
    print(f"[{label}] candidate movers: {len(movers)}")
    return movers


def report_composition(movers: pd.DataFrame, label: str) -> None:
    total = len(movers)
    counts = movers["broker_code"].value_counts()
    retail_count = counts[counts.index.isin(RETAIL_CODES)].sum()
    print(f"\n=== {label}: {total} total candidate-mover flags ===")
    print(f" retail codes (XL/CC/XC/MG/YP) combined: {retail_count} ({retail_count/total*100:.1f}%)")
    for code in sorted(RETAIL_CODES):
        n = counts.get(code, 0)
        print(f"   {code}: {n} ({n/total*100:.1f}%)")
    print(" top 10 codes overall:")
    for code, n in counts.head(10).items():
        tag = " <- retail" if code in RETAIL_CODES else ""
        print(f"   {code}: {n} ({n/total*100:.1f}%){tag}")


def main():
    raw_all = bf.load_raw()
    pre = raw_all[raw_all["trade_date"] < SPLIT_DATE]
    post = raw_all[raw_all["trade_date"] >= SPLIT_DATE]
    print(f"pre-2025 rows: {len(pre)} ({pre['trade_date'].min()}..{pre['trade_date'].max()})")
    print(f"post-2025 rows: {len(post)} ({post['trade_date'].min()}..{post['trade_date'].max()})")

    movers_pre = movers_for_window(pre, "PRE-2025 (2023-01-02..2024-12-31)")
    movers_post = movers_for_window(post, "POST-2025 (2025-01-01..latest)")

    report_composition(movers_pre, "PRE-2025")
    report_composition(movers_post, "POST-2025")


if __name__ == "__main__":
    main()
