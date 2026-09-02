"""How late is Neira, and does being late actually cost anything?

EMAS on its own proves nothing -- one stock, chosen because it went wrong, is
an anecdote. This runs the same comparison across every signal ever published
and asks two separate questions:

  1. LATENESS -- when Neira names a stock, how long has a plain trend-following
     entry (UT Bot, the exact indicator the user uses) already been long, and
     how much of the move has already happened?
  2. DOES IT MATTER -- do the late, already-extended signals actually do worse
     afterwards than the early ones? If they do not, "you always buy the top"
     is a real observation about the entries but not a reason to change them.

Also measures plain extension (distance above MA20/MA50, position in the
60-session range) because those are cheaper to compute than a UT Bot state and,
if they carry the same information, are the better thing to gate on.

Read-only: reads ihsg_eod, daily_qualifying_signals and the signal_performance
view. Writes nothing, changes no config, touches no protected V1 file.
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from supabase import create_client  # noqa: E402

from db_retry import retry as _retry  # noqa: E402
from scratch_utbot_emas import fetch_bars, ut_bot  # noqa: E402

# UT Bot warmup plus enough room for a 60-session range and an MA50.
HISTORY_START = "2025-09-01"


def pct(a: float, b: float) -> float:
    return 100 * (a / b - 1) if b else float("nan")


def summarize(label: str, rows: list[dict], key: str, ret_key: str) -> None:
    """Split on the median of `key` and compare mean forward return either side.

    Median split, not fixed thresholds: with ~100 usable rows, any threshold I
    pick by eye is a free parameter fitted to this sample. The median at least
    is not chosen.
    """
    usable = [r for r in rows if r.get(key) is not None and r.get(ret_key) is not None]
    if len(usable) < 20:
        print(f"  {label:<34} n={len(usable):<4} too few to read")
        return
    vals = sorted(r[key] for r in usable)
    mid = vals[len(vals) // 2]
    lo = [r[ret_key] for r in usable if r[key] <= mid]
    hi = [r[ret_key] for r in usable if r[key] > mid]
    if not lo or not hi:
        print(f"  {label:<34} n={len(usable):<4} no split")
        return
    m_lo, m_hi = sum(lo) / len(lo), sum(hi) / len(hi)
    w_lo = 100 * sum(1 for v in lo if v > 0) / len(lo)
    w_hi = 100 * sum(1 for v in hi if v > 0) / len(hi)
    print(f"  {label:<34} split at {mid:>7.2f} | "
          f"low  n={len(lo):<3} {m_lo:+6.2f}% ({w_lo:4.1f}% up)  | "
          f"high n={len(hi):<3} {m_hi:+6.2f}% ({w_hi:4.1f}% up)  | "
          f"gap {m_lo - m_hi:+.2f}")


def main():
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    perf = _retry(lambda: supabase.table("signal_performance")
                  .select("trade_date, stock_code, rank, score, signal_close, "
                          "ret_1d, ret_5d, ret_10d, mae_5d, ihsg_1d, ihsg_5d")
                  .execute()).data
    print(f"{len(perf)} published signals\n")

    codes = sorted({r["stock_code"] for r in perf})
    bars_by_code: dict[str, list[dict]] = {}
    for i, code in enumerate(codes, 1):
        bars_by_code[code] = fetch_bars(supabase, code, HISTORY_START)
        if i % 20 == 0:
            print(f"  fetched {i}/{len(codes)} tickers...")
    print()

    # UT Bot state per (code, date): current leg direction, leg start, leg entry.
    state_by_code: dict[str, dict[str, dict]] = {}
    for code, bars in bars_by_code.items():
        if len(bars) < 40:
            continue
        signals, series = ut_bot(bars, key=1.0, atr_period=10)
        flips = {d: (kind, close) for d, kind, close, _ in signals}
        leg_kind, leg_start, leg_price = None, None, None
        per_date = {}
        for i, b in enumerate(bars):
            d = b["trade_date"]
            if d in flips:
                leg_kind, leg_price = flips[d]
                leg_start = i
            closes_ = [float(x["close_price"]) for x in bars[: i + 1]]
            ma20 = sum(closes_[-20:]) / 20 if len(closes_) >= 20 else None
            ma50 = sum(closes_[-50:]) / 50 if len(closes_) >= 50 else None
            window = bars[max(0, i - 59): i + 1]
            hi60 = max(float(x["high"]) for x in window)
            lo60 = min(float(x["low"]) for x in window)
            c = float(b["close_price"])
            per_date[d] = {
                "long": leg_kind == "BUY",
                "days_in_leg": (i - leg_start) if leg_start is not None else None,
                "run_since_flip": pct(c, leg_price) if (leg_kind == "BUY" and leg_price) else None,
                "above_ma20": pct(c, ma20) if ma20 else None,
                "above_ma50": pct(c, ma50) if ma50 else None,
                "range_pos": (100 * (c - lo60) / (hi60 - lo60)) if hi60 > lo60 else None,
                "stop_dist": pct(c, series[i]) if series[i] else None,
            }
        state_by_code[code] = per_date

    rows = []
    missing = 0
    for r in perf:
        st = state_by_code.get(r["stock_code"], {}).get(r["trade_date"])
        if st is None:
            missing += 1
            continue
        rows.append({**r, **st,
                     "ret_1d": float(r["ret_1d"]) if r["ret_1d"] is not None else None,
                     "ret_5d": float(r["ret_5d"]) if r["ret_5d"] is not None else None,
                     "ret_10d": float(r["ret_10d"]) if r["ret_10d"] is not None else None,
                     "mae_5d": float(r["mae_5d"]) if r["mae_5d"] is not None else None})
    print(f"matched {len(rows)} signals to price state ({missing} unmatched)\n")

    # ---- Question 1: how late? ----
    longs = [r for r in rows if r["long"]]
    print("=== 1. Where in the move does Neira arrive? ===")
    print(f"  Already in an uptrend by UT Bot's reckoning: {len(longs)}/{len(rows)} "
          f"({100 * len(longs) / len(rows):.0f}%)")
    if longs:
        dl = sorted(r["days_in_leg"] for r in longs if r["days_in_leg"] is not None)
        rs = sorted(r["run_since_flip"] for r in longs if r["run_since_flip"] is not None)
        print(f"  Sessions since the trend flipped up: median {dl[len(dl) // 2]}, "
              f"mean {sum(dl) / len(dl):.1f}, max {dl[-1]}")
        print(f"  Move already banked before Neira names it: median {rs[len(rs) // 2]:+.1f}%, "
              f"mean {sum(rs) / len(rs):+.1f}%, max {rs[-1]:+.1f}%")
    ext = sorted(r["above_ma20"] for r in rows if r["above_ma20"] is not None)
    rp = sorted(r["range_pos"] for r in rows if r["range_pos"] is not None)
    print(f"  Distance above MA20: median {ext[len(ext) // 2]:+.1f}%, mean {sum(ext) / len(ext):+.1f}%")
    print(f"  Position in 60-session range (100 = at the high): "
          f"median {rp[len(rp) // 2]:.0f}, mean {sum(rp) / len(rp):.0f}")
    print(f"  Named while sitting in the top 20% of their 60-day range: "
          f"{sum(1 for v in rp if v >= 80)}/{len(rp)} ({100 * sum(1 for v in rp if v >= 80) / len(rp):.0f}%)\n")

    # ---- Question 2: does being late cost anything? ----
    for ret_key in ("ret_1d", "ret_5d", "ret_10d"):
        n = sum(1 for r in rows if r.get(ret_key) is not None)
        print(f"=== 2. Does lateness predict {ret_key}? (n={n}, low half vs high half) ===")
        for key, label in (("run_since_flip", "run already banked"),
                           ("days_in_leg", "sessions since trend flip"),
                           ("above_ma20", "distance above MA20"),
                           ("above_ma50", "distance above MA50"),
                           ("range_pos", "position in 60-day range"),
                           ("stop_dist", "distance above trailing stop")):
            summarize(label, rows, key, ret_key)
        print()

    # Worst-dip angle: even if returns do not differ, a stretched entry may just
    # be a rougher ride, which is its own reason to hold back.
    print("=== 3. Does lateness predict a deeper dip (mae_5d)? ===")
    for key, label in (("run_since_flip", "run already banked"),
                       ("above_ma20", "distance above MA20"),
                       ("range_pos", "position in 60-day range")):
        summarize(label, rows, key, "mae_5d")


if __name__ == "__main__":
    main()
