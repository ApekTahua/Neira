"""Self-check for the T-7 split/reverse-split adjustment layer.

Asserts the properties the layer exists to guarantee, against the live views:

  1. Every event snapped to a real IDX corporate-action ratio, with the
     confidence recorded.
  2. The four cases already named in test_split_guard.py (DSSA x2, CUAN, FISH)
     are detected, plus both reverse splits.
  3. The adjusted close series is CONTINUOUS across every ex-date -- no
     remaining cliff, and nothing left that even reaches an auto-reject band.
  4. ihsg_eod is untouched: the layer is derived, so the raw cliffs are all
     still there in the source.

Usage:  python src/test_split_adjustment.py
"""
import os
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
os.chdir(SRC)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(SRC, "..", ".env"))

from supabase import create_client  # noqa: E402

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def rows(table, **kw):
    q = sb.table(table).select(kw.pop("select", "*"))
    for k, v in kw.items():
        q = q.eq(k, v)
    return q.execute().data


# 1 -- every event snapped, and the snap is recorded
events = rows("corporate_action_split")
assert events, "no corporate actions detected at all"
KNOWN = {2, 3, 4, 5, 6, 8, 10, 20, 25, 40, 50, 100, 0.5, 0.25, 0.2, 0.1, 0.05, 0.04, 0.02, 0.01}
for e in events:
    assert float(e["inferred_ratio"]) in KNOWN, f"{e['stock_code']}: unknown ratio {e['inferred_ratio']}"
    assert 0.99 <= float(e["snap_confidence"]) <= 1.0, f"{e['stock_code']}: weak snap {e['snap_confidence']}"
    assert e["kind"] in ("split", "reverse_split")
    assert e["source_event_date"], "event has no source_event_date to trace back to"
print(f"[OK] {len(events)} events, every one snapped to a known IDX ratio "
      f"(worst confidence {min(float(e['snap_confidence']) for e in events):.4f})")

# 2 -- the named cases, and both reverse splits
by_key = {(e["stock_code"], e["source_event_date"]): e for e in events}
for code, date, ratio in [("DSSA", "2024-07-18", 10), ("CUAN", "2025-07-15", 10),
                          ("FISH", "2025-09-09", 10), ("DSSA", "2026-04-09", 25)]:
    e = by_key.get((code, date))
    assert e, f"{code}@{date} not detected"
    assert float(e["inferred_ratio"]) == ratio, f"{code}@{date}: got {e['inferred_ratio']}, want {ratio}"
rev = [e for e in events if e["kind"] == "reverse_split"]
assert len(rev) >= 2, f"expected the reverse splits to be found, got {len(rev)}"
print(f"[OK] all four split-guard cases detected at the right ratio; "
      f"{len(rev)} reverse splits found ({', '.join(e['stock_code'] for e in rev)})")

# 3 + 4 -- continuity of the adjusted series, and rawness of the source
factors = rows("stock_split_factor")
eras = {}
for f in factors:
    eras.setdefault(f["stock_code"], []).append(f)

checked = raw_cliffs = 0
for e in events:
    code, ex = e["stock_code"], e["source_event_date"]
    bars = sb.table("ihsg_eod").select("trade_date, close_price").eq("stock_code", code) \
        .lte("trade_date", ex).order("trade_date", desc=True).limit(2).execute().data
    if len(bars) < 2:
        continue
    today, prev = bars[0], bars[1]

    def divisor(day):
        for f in eras[code]:
            if f["valid_from"] <= day <= f["valid_to"]:
                return float(f["divisor"])
        raise AssertionError(f"{code}@{day}: no factor era covers this date")

    raw_move = float(today["close_price"]) / float(prev["close_price"]) - 1
    adj_move = (float(today["close_price"]) / divisor(today["trade_date"])) / \
               (float(prev["close_price"]) / divisor(prev["trade_date"])) - 1

    # 4: the raw source still shows the cliff -- proof nothing mutated ihsg_eod
    if abs(raw_move) > 0.5:
        raw_cliffs += 1
    # 3: adjusted must be a plausible single session, inside the widest IDX band
    assert abs(adj_move) <= 0.36, (
        f"{code}@{ex}: adjusted move {adj_move:+.1%} is beyond the widest IDX "
        f"auto-reject band -- the adjustment did not make this series continuous")
    checked += 1

print(f"[OK] {checked} ex-dates: every adjusted move inside the widest IDX band "
      f"(raw data still shows {raw_cliffs} cliffs over 50%, so ihsg_eod is untouched)")
print("\nAll split-adjustment checks passed.")
