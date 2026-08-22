"""bandarmology_push_daily.py -- computes derived flow features from the
full local Parquet history (reusing bandarmology_features.py) and
upserts them to DB2's `bandarmology_flow_daily` table (see
sql/bandarmology_flow_daily_schema.sql), the table the Bandarmology
page's chart actually reads.

Recomputes and upserts the FULL local history every run -- cheap
(pandas, local, no network cost per row) and simplest correct thing;
`on_conflict` upsert makes it idempotent. Batches the REST upload since
a single request with the whole history would be an oversized payload.

Needs DB2 write credentials -- put these in a local .env (see
.gitignore, already covers .env/.env.*, never commit it):
    SUPABASE_BROKER_URL=https://ptuvkgleurjcniznveye.supabase.co
    SUPABASE_BROKER_KEY=<service_role key>
Loaded via python-dotenv so the key is never typed into a prompt or
printed by this script.

Usage: python src/bandarmology_push_daily.py
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402

BATCH_SIZE = 2000


def main():
    load_dotenv()
    url = os.environ["SUPABASE_BROKER_URL"]
    key = os.environ["SUPABASE_BROKER_KEY"]

    # load_raw_clean(), not load_raw() -- drops broker_summary rows that don't
    # reconcile with real ihsg_eod price/volume (Nego/rights-issue leakage
    # with no segment flag, see bandarmology_features.py's module comment;
    # confirmed on PACK and ~100 other tickers 2026-08-22). This table feeds
    # the live Bandarmology page's verdict badge directly.
    raw = bf.load_raw_clean()
    broker_net = bf.per_broker_net(raw)
    daily = bf.daily_stock_features(broker_net)
    feats = bf.rolling_features(daily)
    feats = feats.sort_values(["stock_code", "trade_date"])
    feats["cumulative_net_val"] = feats.groupby("stock_code")["net_val"].cumsum()

    cols = ["stock_code", "trade_date", "net_lot", "net_val", "turnover_lot",
            "concentration", "net_flow_norm", "consistency", "cumulative_net_val"]
    records = feats[cols].copy()
    for col in ("net_lot", "net_val", "turnover_lot"):  # bigint columns -- pandas floats serialize as "18.0", Postgres rejects that
        records[col] = records[col].round().astype("Int64")
    records["trade_date"] = records["trade_date"].astype(str)
    records = records.where(records.notna(), None).to_dict("records")

    print(f"pushing {len(records)} rows to bandarmology_flow_daily...")
    endpoint = f"{url}/rest/v1/bandarmology_flow_daily"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        resp = requests.post(endpoint, json=batch, headers=headers, timeout=30)
        if not resp.ok:
            print(f"  ERROR {resp.status_code}: {resp.text}", file=sys.stderr)
        resp.raise_for_status()
        print(f"  {i + len(batch)}/{len(records)}")

    print("done")


if __name__ == "__main__":
    main()
