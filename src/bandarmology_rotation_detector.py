"""bandarmology_rotation_detector.py -- "internal rotation" pattern
detector (see docs/BANDARMOLOGY_DESIGN.md, "Named pattern added" /
MASTERPLAN.md V4 section). User's framing ("tuker barang"): distinct
from a single day's same-broker crossing (already handled -- net per
broker per day washes that out automatically, see
bandarmology_features.per_broker_net). This is the broader case: a
small CLUSTER of DIFFERENT brokers repeatedly ending up on opposite
sides of each other, day after day, over time -- volume moving back
and forth within a recurring group rather than either a one-off cross
or real market-wide accumulation/distribution.

Method: for each stock, for each day, find broker PAIRS active on
opposite sides that day (one net buyer, one net seller). The overlap
volume for that pair that day is min(|buyer's net|, |seller's net|) --
how much of one side's net position the other side's net position could
plausibly have absorbed. Aggregate over the window: a pair that shows
up together on opposite sides on many distinct days, with real volume,
is a rotation candidate -- NOT validated as real bandar behavior (that
needs the same forward-return check as everything else, see
diagnose_bandarmology_power.py), just flagged as a recurring structural
pattern worth a human/future-score look.

First pass (raw co-occurrence count) turned up 464,717 "candidate" pairs
at a floor of 5 shared days -- useless, and for a diagnosable reason:
big full-service brokers (AK/YP/ZP/CC/PD) are active on nearly every
session for any liquid name, so they land on opposite sides of each
other constantly just from base rates, nothing to do with any real
relationship. Raw count can't tell "always busy" apart from "actually
paired." Fixed by comparing OBSERVED co-occurrence against EXPECTED
co-occurrence under independence (each broker's own P(buyer)/P(seller)
on days both were active) -- a lift ratio. A pair only qualifies if it
co-occurs MORE than its individual activity rates would predict by
chance, not just often in absolute terms.

STATUS 2026-08-11: second pass, against partial local data (through
2025-08, backfill still running). MIN_PAIR_DAYS/MIN_LIFT are
unvalidated placeholder thresholds -- this still isn't a forward-
return-tested signal (see diagnose_bandarmology_power.py for that
class of check), just a structurally sounder way to flag candidates.

Usage: python src/bandarmology_rotation_detector.py
"""

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bandarmology_features as bf  # noqa: E402

MIN_PAIR_DAYS = 15  # unvalidated placeholder -- floor against small-sample noise
MIN_LIFT = 1.5      # unvalidated placeholder -- co-occur >=50% more than independence predicts


def find_rotation_pairs(raw: pd.DataFrame) -> pd.DataFrame:
    broker_net = bf.per_broker_net(raw)
    broker_net = broker_net[broker_net["net_lot"] != 0]

    pair_days = defaultdict(int)
    pair_volume = defaultdict(float)
    both_active_days = defaultdict(int)
    broker_active = defaultdict(int)   # (stock, broker) -> active days
    broker_buy = defaultdict(int)      # (stock, broker) -> net-buyer days

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

        if len(buyers) == 0 or len(sellers) == 0:
            continue
        for b_code, b_lot in buyers:
            for s_code, s_lot in sellers:
                pair = tuple(sorted((b_code, s_code)))
                key = (stock_code, pair)
                overlap = min(b_lot, abs(s_lot))
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
        expected_rate = p_a_buy * (1 - p_b_buy) + (1 - p_a_buy) * p_b_buy
        observed_rate = days / n_both
        lift = observed_rate / expected_rate if expected_rate > 0 else float("inf")
        if lift < MIN_LIFT:
            continue
        rows.append({
            "stock_code": stock_code, "broker_a": a, "broker_b": b,
            "opposite_side_days": days, "both_active_days": n_both,
            "observed_rate": observed_rate, "expected_rate": expected_rate, "lift": lift,
            "total_overlap_lot": pair_volume[(stock_code, pair)],
        })
    return pd.DataFrame(rows).sort_values("lift", ascending=False)


def main():
    raw = bf.load_raw()
    print(f"raw rows: {len(raw)}, dates: {raw['trade_date'].min()} to {raw['trade_date'].max()}")

    result = find_rotation_pairs(raw)
    print(f"\nrotation candidate pairs (>= {MIN_PAIR_DAYS} days, lift >= {MIN_LIFT}): {len(result)}")
    print(result.head(25).to_string(index=False))


if __name__ == "__main__":
    main()
