"""bandarmology_cluster_detector.py -- "correlated cluster" pattern
detector, the SAME-direction counterpart to bandarmology_rotation_detector.py
(which finds recurring OPPOSITE-side pairs, "tuker barang"). Motivated
directly by domain research (docs/BANDARMOLOGY_DESIGN.md, 2026-08-12):
the most sophisticated real-world implementation of this technique
(Stockbit's productized "Bandar Detector") explicitly looks for the SAME
directional bias spread across 3-10 different broker codes at once,
reasoning that a real bandar splits orders across multiple houses to
avoid single-broker detection -- single-broker net flow alone understates
true accumulation/distribution.

Full clique-finding (actual groups of size 3-10 acting together) is
combinatorially expensive and needs its own validation methodology --
this is the tractable first step: PAIRWISE same-side co-occurrence lift,
reusing the exact statistical framework validated on the rotation
detector this session (observed vs expected co-occurrence rate under
independence, given each broker's own individual buy/sell base rate).
A pair with high same-side lift is a building block for a real cluster
(chain pairs with shared high-lift edges into a group later, once this
pairwise layer itself is trusted) -- not a cluster itself yet.

STATUS 2026-08-12: first pass, against the full 2023-2026-07-31 backfill.
MIN_PAIR_DAYS/MIN_LIFT are unvalidated placeholders, same caveat as the
rotation detector -- this is a structurally sounder way to flag
candidates, not yet a forward-return-tested signal (see
diagnose_bandarmology_power.py for that class of check).

Usage: python src/bandarmology_cluster_detector.py
"""

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402

MIN_PAIR_DAYS = 15  # unvalidated placeholder, same floor as the rotation detector
MIN_LIFT = 1.5      # unvalidated placeholder, same threshold as the rotation detector


def find_cluster_pairs(raw: pd.DataFrame) -> pd.DataFrame:
    broker_net = bf.per_broker_net(raw)
    broker_net = broker_net[broker_net["net_lot"] != 0]

    pair_days = defaultdict(int)      # (stock, pair) -> days both were on the SAME side
    pair_volume = defaultdict(float)
    both_active_days = defaultdict(int)
    broker_active = defaultdict(int)  # (stock, broker) -> active days
    broker_buy = defaultdict(int)     # (stock, broker) -> net-buyer days

    for (stock_code, trade_date), day_df in broker_net.groupby(["stock_code", "trade_date"]):
        buyers = day_df[day_df["net_lot"] > 0][["broker_code", "net_lot"]].values
        sellers = day_df[day_df["net_lot"] < 0][["broker_code", "net_lot"]].values
        active_codes = day_df["broker_code"].tolist()

        for code in active_codes:
            broker_active[(stock_code, code)] += 1
        for b_code, _ in buyers:
            broker_buy[(stock_code, b_code)] += 1

        for i, a in enumerate(active_codes):
            for b in active_codes[i + 1:]:
                pair = tuple(sorted((a, b)))
                both_active_days[(stock_code, pair)] += 1

        # Same-side co-occurrence: both net buyers together, OR both net
        # sellers together (the rotation detector instead pairs one buyer
        # with one seller -- this is the mirror case).
        for side_group in (buyers, sellers):
            for i in range(len(side_group)):
                a_code, a_lot = side_group[i]
                for j in range(i + 1, len(side_group)):
                    b_code, b_lot = side_group[j]
                    pair = tuple(sorted((a_code, b_code)))
                    key = (stock_code, pair)
                    overlap = min(abs(a_lot), abs(b_lot))
                    pair_days[key] += 1
                    pair_volume[key] += overlap

    rows = []
    for (stock_code, pair), days in pair_days.items():
        if days < MIN_PAIR_DAYS:
            continue
        n_both = both_active_days[(stock_code, pair)]
        if n_both == 0:
            continue
        a, b = pair
        p_a_buy = broker_buy[(stock_code, a)] / broker_active[(stock_code, a)]
        p_b_buy = broker_buy[(stock_code, b)] / broker_active[(stock_code, b)]
        # Same-side (both buy OR both sell) under independence:
        expected_rate = p_a_buy * p_b_buy + (1 - p_a_buy) * (1 - p_b_buy)
        observed_rate = days / n_both
        lift = observed_rate / expected_rate if expected_rate > 0 else float("inf")
        if lift < MIN_LIFT:
            continue
        rows.append({
            "stock_code": stock_code, "broker_a": a, "broker_b": b,
            "same_side_days": days, "both_active_days": n_both,
            "observed_rate": observed_rate, "expected_rate": expected_rate, "lift": lift,
            "total_overlap_lot": pair_volume[(stock_code, pair)],
        })
    return pd.DataFrame(rows).sort_values("lift", ascending=False)


def main():
    raw = bf.load_raw()
    print(f"raw rows: {len(raw)}, dates: {raw['trade_date'].min()} to {raw['trade_date'].max()}")

    result = find_cluster_pairs(raw)
    print(f"\nsame-side cluster candidate pairs (>= {MIN_PAIR_DAYS} days, lift >= {MIN_LIFT}): {len(result)}")
    print(result.head(25).to_string(index=False))


if __name__ == "__main__":
    main()
