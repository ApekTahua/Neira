"""Does the strategy lose anything if TP1 stops selling?

The user's critique of the exit machinery, verbatim: "Orang tuh kalau beli saham
simple, beli, pasang SL, TP, udah... lu tuh ada trailing2, ada TP1 lagi."

TP1 currently does three jobs at once: it sells 10% of the position, raises the
stop to breakeven, and unlocks the trailing stop and pyramiding. Only the first
is a trade. This tests removing exactly that one job -- V4_TP1_PARTIAL_SELL=0
keeps every piece of TP1's bookkeeping and sells nothing.

Why it is worth testing, from what this log already measured: TRAILING exits
carry 81.3% of gross positive PnL while TP1 contributes ~Rp144K per leg, and
every TP1 leg is positive by construction, which is what inflated the reported
win rate from a true 26.3% to 49.3%. Selling a slice at a fixed 1.5xATR trims
precisely the trades the strategy lives on.

Unlike the nine ideas rejected before it, this is a REMOVAL. Every addition has
failed, so the question worth asking now is what the existing machinery costs.

Judged on the same 9-window walk-forward and the same adoption bar as everything
else: mean alpha AND worst drawdown must both improve.

Usage:
    python src/test_tp1_partial_removal.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("V4_TEST_END", "2026-06-30")

import backtest_v4 as bt  # noqa: E402
from feature_test_harness import run_isolated_feature_test  # noqa: E402


def set_no_partial_sell(enabled: bool) -> None:
    """ON = the candidate = TP1 sells nothing. The flag itself is named for the
    current behaviour, so it is inverted here rather than in the module."""
    bt.TP1_PARTIAL_SELL_ENABLED = not enabled


def main():
    rows, table_md = run_isolated_feature_test("TP1 sells nothing", set_no_partial_sell)
    print(table_md)

    off, on = rows["OFF"], rows["ON"]
    d_alpha = on["alpha_mean"] - off["alpha_mean"]
    d_dd = on["dd_worst"] - off["dd_worst"]   # both negative; higher = shallower
    print(f"\nadoption bar: mean alpha AND worst drawdown must both improve")
    print(f"  alpha    {off['alpha_mean']:+.2f} -> {on['alpha_mean']:+.2f}  ({d_alpha:+.2f})")
    print(f"  worst DD {off['dd_worst']:+.2f} -> {on['dd_worst']:+.2f}  ({d_dd:+.2f})")
    print(f"  verdict: {'ADOPT' if (d_alpha > 0 and d_dd > 0) else 'REJECT'}")


if __name__ == "__main__":
    main()
