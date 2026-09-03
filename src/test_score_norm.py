"""Re-baseline after repairing the score's normalisation.

This is NOT idea #11. Ten improvement ideas were graded against a walk-forward
whose stock-ranking step is now measured to be miscalibrated
(src/diagnose_score_scale.py): the two score components are each divided by
their own threshold, those thresholds sit three orders of magnitude apart and
move independently (sector_cut swings 6.7x across windows, weekly_cut 1.8x), and
the weekly component's share of the score's variation therefore wanders between
18.3% and 48.0% instead of sitting near 50%. In window 7 the sector component
alone drives 81.7% of the ranking.

The score picks which 6 of 15 daily candidates get bought, so this sits upstream
of every number those ten experiments were judged on. Putting both components on
a common scale moves 21.5% of each day's top-6 picks.

So the question here is not "does this beat the bar" but "was the bar itself
measured on a sound instrument". Two outcomes are both informative:
  - the baseline MOVES: ten rejections were graded against the wrong number, and
    the ones that were close deserve re-running.
  - the baseline HOLDS: the ranking genuinely carries little information, which
    corroborates the 2026-08-24 finding that the regime gate carries the edge
    and the stock-picking does not -- and closes the question.

Default (V4_SCORE_NORM="cut") reproduces the current formula exactly, so the
live path through paper_signal_scan.py is untouched either way.

Usage:
    python src/test_score_norm.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("V4_TEST_END", "2026-06-30")

import backtest_v4 as bt  # noqa: E402
from feature_test_harness import run_isolated_feature_test  # noqa: E402


def set_train_sd_norm(enabled: bool) -> None:
    """ON = the repair = both components normalised on a common train-derived
    scale. simulate_window reads SCORE_NORM when it computes the scales, so
    setting the module attribute is enough."""
    bt.SCORE_NORM = "train_sd" if enabled else "cut"


def main():
    rows, table_md = run_isolated_feature_test("common score scale", set_train_sd_norm)
    print(table_md)

    off, on = rows["OFF"], rows["ON"]
    d_alpha = on["alpha_mean"] - off["alpha_mean"]
    d_dd = on["dd_worst"] - off["dd_worst"]
    print("\nadoption bar: mean alpha AND worst drawdown must both improve")
    print(f"  alpha    {off['alpha_mean']:+.2f} -> {on['alpha_mean']:+.2f}  ({d_alpha:+.2f})")
    print(f"  worst DD {off['dd_worst']:+.2f} -> {on['dd_worst']:+.2f}  ({d_dd:+.2f})")
    print(f"  verdict: {'ADOPT' if (d_alpha > 0 and d_dd > 0) else 'REJECT'}")
    print("\nEither way, read the size of the move first: a baseline that shifts")
    print("materially means the ten prior rejections were graded on a different")
    print("number than the one that should have been used.")


if __name__ == "__main__":
    main()
