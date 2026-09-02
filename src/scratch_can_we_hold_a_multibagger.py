"""If Neira HAD bought the bottom, would it have kept the multi-bagger?

The user's proposal: stop churning, buy near the bottom, hold for the big one --
"kalau sekali trade bisa cuan ratusan juta, ngapain trading terus2an rugi cuan
rugi cuan". LUCY (91 -> 2,510, a 27-bagger) is the case in point, and Neira
never named it.

Fixing the ENTRY is the obvious half. This checks the other half first, because
it is cheaper to check and it decides whether the entry work is even worth
doing: given a perfect bottom entry, do Neira's own exit rules let the position
run? If a 27-bagger gets cut at +40% by an 8% trailing stop, then buying the
bottom changes nothing and the entry research would be wasted.

Mirrors evaluate_position_exit() exactly as of 2026-09-02:
  SL       = entry - 1.5 * ATR(entry), checked on the bar's LOW
  TP1      = entry + 1.5 * ATR(entry), sells 10%, gated by MIN_HOLD_DAYS = 3
  TRAILING = only after TP1 has fired; exits the rest when CLOSE <= the higher
             of (highest close so far) * (1 - 0.08) and the SL
  TIME     = at MAX_HOLD_DAYS = 20, but ONLY if the position is not (in profit
             AND the market regime is bullish) -- winners are not force-closed
Ignores fees and slippage, which flatters the strategy slightly; the point here
is the exit path, not the last decimal.

Read-only. No config change, no live table touched.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from supabase import create_client  # noqa: E402

import config as cfg  # noqa: E402
from scratch_utbot_emas import fetch_bars, wilder_atr  # noqa: E402

CASES = [
    # (ticker, entry date, what makes this the interesting entry)
    ("LUCY", "2025-10-01", "near the base, before the 27x run"),
    ("LUCY", "2025-12-01", "early in the breakout"),
    ("EMAS", "2026-07-23", "the exact UT Bot buy the user pointed at"),
    ("BEEF", "2026-07-01", "UT Bot's second-best trade this year (+176%)"),
    ("FPNI", "2025-10-21", "UT Bot's best trade this year (+335%)"),
]


def simulate(bars, entry_idx, atr_series, regime_bullish=True):
    """Returns (exit_reason, exit_idx, pct_from_entry, peak_pct_seen)."""
    entry = float(bars[entry_idx]["close_price"])
    atr = atr_series[entry_idx]
    if not atr:
        return ("NO_ATR", None, None, None)
    sl = entry - cfg.ATR_SL_MULTIPLIER * atr
    tp1 = entry + cfg.TP1_MULT * atr
    tp1_hit = False
    highest = entry
    peak = entry

    for i in range(entry_idx + 1, len(bars)):
        hold_days = i - entry_idx
        hi, lo, c = (float(bars[i]["high"]), float(bars[i]["low"]),
                     float(bars[i]["close_price"]))
        peak = max(peak, hi)
        if c > highest:
            highest = c
        hold_ok = hold_days >= cfg.MIN_HOLD_DAYS

        if lo <= sl:
            return ("SL", i, 100 * (sl / entry - 1), 100 * (peak / entry - 1))
        if not tp1_hit:
            if hold_ok and hi >= tp1:
                tp1_hit = True          # sells 10%, the rest rides on
            elif hold_days >= cfg.MAX_HOLD_DAYS - 1:
                in_profit = c > entry
                if not (in_profit and regime_bullish):
                    return ("TIME", i, 100 * (c / entry - 1), 100 * (peak / entry - 1))
        elif hold_ok:
            stop_eff = max(highest * (1 - cfg.TRAILING_PCT), sl)
            if c <= stop_eff:
                return ("TRAILING", i, 100 * (c / entry - 1), 100 * (peak / entry - 1))
    return ("STILL_OPEN", len(bars) - 1,
            100 * (float(bars[-1]["close_price"]) / entry - 1), 100 * (peak / entry - 1))


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    print(f"Exit rules: SL {cfg.ATR_SL_MULTIPLIER}xATR | TP1 {cfg.TP1_MULT}xATR sells "
          f"{cfg.TP1_PCT:.0%} | trail {cfg.TRAILING_PCT:.0%} of peak close | "
          f"max hold {cfg.MAX_HOLD_DAYS}d | min hold {cfg.MIN_HOLD_DAYS}d\n")
    print(f"{'ticker':<7}{'entry date':<13}{'entry':>8}{'exit':>10}{'held':>7}"
          f"{'got':>10}{'was up':>10}   note")
    print("-" * 104)

    for code, entry_date, note in CASES:
        bars = fetch_bars(sb, code, "2025-06-01")
        idx = {b["trade_date"]: i for i, b in enumerate(bars)}
        # First traded session on or after the requested date.
        cand = [d for d in sorted(idx) if d >= entry_date]
        if not cand:
            print(f"{code:<7}{entry_date:<13}  no bars")
            continue
        ei = idx[cand[0]]
        atr = wilder_atr([float(b["high"]) for b in bars],
                         [float(b["low"]) for b in bars],
                         [float(b["close_price"]) for b in bars], 14)
        reason, xi, got, was = simulate(bars, ei, atr)
        entry_px = float(bars[ei]["close_price"])
        held = (xi - ei) if xi is not None else 0
        print(f"{code:<7}{bars[ei]['trade_date']:<13}{entry_px:>8,.0f}{reason:>10}"
              f"{held:>7}{got:>9.1f}%{was:>9.1f}%   {note}")

    print("\n'got' = what the exit rules actually delivered. "
          "'was up' = the best the position ever showed, intraday, before exiting.")


if __name__ == "__main__":
    main()
