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

Research/prototype code, not wired into anything live. Run directly:
    python src/bandarmology_features.py
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "bandarmology_history"
WINDOW = 10  # trading days -- placeholder, see design doc "Open questions"


def load_raw() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob("*/*/*.parquet"))
    if not files:
        raise SystemExit(f"no parquet files under {DATA_DIR} yet -- run the backfill first")
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


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
