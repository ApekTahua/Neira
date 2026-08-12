"""bandarmology_push_movers_rotation.py -- computes the broker-mover
candidates (bandarmology_broker_profile.py) and rotation-pair candidates
(bandarmology_rotation_detector.py) from the full local Parquet history
and pushes both to DB2 (see sql/bandarmology_movers_and_rotation_schema.sql).
This is what makes "which brokers move this stock" and "which broker pairs
rotate volume between each other" queryable by the frontend for the first
time -- both scripts previously only printed to stdout.

Full-table replace on each push (DELETE all, then insert), not an upsert --
candidate sets can shrink as well as grow when rerun against more/different
data or a tuned threshold, and there's no stable row identity to diff a
shrinking set against. Both tables are small (thousands of rows), so a full
replace is cheap.

Needs DB2 write credentials in a local .env (see bandarmology_push_daily.py
for the exact variable names -- same file, never printed here).

Usage: python src/bandarmology_push_movers_rotation.py
"""

import os
import sys
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402
from diagnose_bandarmology_power import load_prices, add_forward_returns  # noqa: E402
from bandarmology_broker_profile import per_broker_daily, candidate_movers  # noqa: E402
from bandarmology_rotation_detector import find_rotation_pairs  # noqa: E402
from bandarmology_cluster_detector import find_cluster_pairs  # noqa: E402


def replace_table(url: str, key: str, table: str, records: list[dict], key_col: str = "stock_code") -> None:
    endpoint = f"{url}/rest/v1/{table}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    del_resp = requests.delete(f"{endpoint}?{key_col}=not.is.null", headers=headers, timeout=30)
    if not del_resp.ok:
        print(f"  DELETE ERROR {del_resp.status_code}: {del_resp.text}", file=sys.stderr)
    del_resp.raise_for_status()

    batch_size = 2000
    print(f"pushing {len(records)} rows to {table}...")
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        resp = requests.post(endpoint, json=batch, headers=headers, timeout=30)
        if not resp.ok:
            print(f"  ERROR {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()
        print(f"  {i + len(batch)}/{len(records)}")


def main():
    load_dotenv()
    url = os.environ["SUPABASE_BROKER_URL"]
    key = os.environ["SUPABASE_BROKER_KEY"]

    raw = bf.load_raw()

    # --- broker-mover candidates ---
    broker_daily = per_broker_daily(raw)
    stock_codes = broker_daily["stock_code"].unique().tolist()
    start = raw["trade_date"].min().isoformat()
    end = raw["trade_date"].max().isoformat()
    print(f"loading prices for {len(stock_codes)} stocks, {start} to {end}...")
    prices = load_prices(stock_codes, start, end)
    prices = add_forward_returns(prices)
    movers = candidate_movers(broker_daily, prices)
    movers = movers[movers["candidate_mover"]]
    print(f"mover candidates: {len(movers)}")

    mover_cols = ["stock_code", "broker_code", "active_days", "corr_first_half", "corr_second_half"]
    mover_records = movers[mover_cols].copy()
    mover_records = mover_records.where(mover_records.notna(), None).to_dict("records")

    # --- rotation-pair candidates ---
    rotation = find_rotation_pairs(raw)
    print(f"rotation candidates: {len(rotation)}")
    rotation_cols = ["stock_code", "broker_a", "broker_b", "opposite_side_days",
                      "both_active_days", "observed_rate", "expected_rate", "lift", "total_overlap_lot"]
    rotation_records = rotation[rotation_cols].copy()
    rotation_records = rotation_records.where(rotation_records.notna(), None).to_dict("records")

    # --- same-side cluster candidates ---
    cluster = find_cluster_pairs(raw)
    print(f"cluster candidates: {len(cluster)}")
    cluster_cols = ["stock_code", "broker_a", "broker_b", "same_side_days",
                     "both_active_days", "observed_rate", "expected_rate", "lift", "total_overlap_lot"]
    cluster_records = cluster[cluster_cols].copy()
    cluster_records = cluster_records.where(cluster_records.notna(), None).to_dict("records")

    # --- broker-characteristic rollup (cross-stock, "what kind of trader
    # is broker X in general" -- reuses broker_net/movers/rotation/cluster
    # already computed above, no extra loading cost) ---
    broker_net = bf.per_broker_net(raw)
    active_days = broker_net.groupby(["stock_code", "broker_code"]).size()
    active_days = active_days[active_days >= 20]  # MIN_ACTIVE_DAYS, same floor as the mover detector
    active_stock_count = active_days.reset_index()["broker_code"].value_counts()

    directional = broker_net[broker_net["net_lot"] != 0]
    pct_net_buy = directional.groupby("broker_code").apply(
        lambda g: (g["net_lot"] > 0).mean(), include_groups=False)
    turnover_ratio = (directional["turnover_lot"] / directional["net_lot"].abs())
    avg_turnover_ratio = turnover_ratio.groupby(directional["broker_code"]).median()

    mover_stock_count = movers.groupby("broker_code")["stock_code"].nunique()
    rotation_pair_count = pd.concat([rotation["broker_a"], rotation["broker_b"]]).value_counts()
    cluster_pair_count = pd.concat([cluster["broker_a"], cluster["broker_b"]]).value_counts()

    all_brokers = broker_net["broker_code"].unique()
    profile = pd.DataFrame({"broker_code": all_brokers}).set_index("broker_code")
    profile["active_stock_count"] = active_stock_count
    profile["pct_days_net_buy"] = pct_net_buy
    profile["avg_turnover_to_net_ratio"] = avg_turnover_ratio
    profile["mover_stock_count"] = mover_stock_count
    profile["rotation_pair_count"] = rotation_pair_count
    profile["cluster_pair_count"] = cluster_pair_count
    profile = profile.reset_index()
    for col in ("active_stock_count", "mover_stock_count", "rotation_pair_count", "cluster_pair_count"):
        profile[col] = profile[col].fillna(0).astype(int)
    profile = profile[profile["active_stock_count"] > 0]  # brokers with no stock clearing MIN_ACTIVE_DAYS anywhere
    print(f"broker characteristics: {len(profile)} brokers")

    profile_records = profile.where(profile.notna(), None).to_dict("records")

    replace_table(url, key, "bandarmology_mover_pairs", mover_records)
    replace_table(url, key, "bandarmology_rotation_pairs", rotation_records)
    replace_table(url, key, "bandarmology_cluster_pairs", cluster_records)
    replace_table(url, key, "broker_characteristics", profile_records, key_col="broker_code")
    print("done")


if __name__ == "__main__":
    main()
