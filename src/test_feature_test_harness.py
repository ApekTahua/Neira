"""Self-check for feature_test_harness.py. Two things a broken
implementation could silently get wrong:

  1. _aggregate()/_format_table() compute and label the right numbers from
     a run_schedule()-shaped DataFrame (same "Windows beating benchmark /
     win-rate>50% / mean-median alpha,profit,PF / mean-worst maxDD" shape
     every hand-written table in docs/V3_FINDINGS_LOG.md already used).
  2. run_isolated_feature_test() calls set_flag(False) before the OFF run,
     set_flag(True) before the ON run, and always restores set_flag(False)
     afterward -- including if a run raises. Checked with fakes standing in
     for wf.load_dataset/wf.run_schedule, no real dataset or Supabase needed.

Usage: python src/test_feature_test_harness.py
"""

import pandas as pd

import feature_test_harness as fth
import walk_forward_v4 as wf

# ---- _aggregate(): matches walk_forward_v4.main()'s own AGGREGATE block ----
res_df = pd.DataFrame([
    {"window": 1, "trades": 10, "win_rate": 60.0, "profit_pct": 5.0, "alpha_pct": 2.0, "profit_factor": 1.5, "max_dd": -10.0},
    {"window": 2, "trades": 8, "win_rate": 40.0, "profit_pct": -3.0, "alpha_pct": -1.0, "profit_factor": 0.8, "max_dd": -20.0},
    {"window": 3, "trades": 0},  # no-trade window must be excluded, like main()'s `traded` filter
])
agg = fth._aggregate(res_df)
assert agg["beat_bench"] == "1/2", agg["beat_bench"]
assert agg["win_gt50"] == "1/2", agg["win_gt50"]
assert agg["win_mean"] == 50.0 and agg["win_median"] == 50.0
assert agg["alpha_mean"] == 0.5
assert agg["dd_worst"] == -20.0, "worst drawdown is the MIN (most negative), not min(abs)"
print("[PASS] _aggregate() matches walk_forward_v4.main()'s own beat-bench/win-rate/mean-median math")

empty_agg = fth._aggregate(pd.DataFrame([{"window": 1, "trades": 0}]))
assert empty_agg["beat_bench"] == "0/0" and pd.isna(empty_agg["alpha_mean"])
print("[PASS] _aggregate() handles an all-no-trade schedule without raising")

# ---- _format_table(): produces the same header/row shape as the hand-written tables ----
table = fth._format_table(agg, agg, "my_gate")
assert table.startswith("| Metric | OFF | ON (my_gate) |\n|---|---|---|")
assert "Windows beating benchmark | 1/2 | 1/2 |" in table
assert "Alpha (mean / median) | +0.50% / +0.50% | +0.50% / +0.50% |" in table
print("[PASS] _format_table() produces the standard '| Metric | OFF | ON (label) |' shape")

# ---- run_isolated_feature_test(): off-then-on call order, always restores to OFF ----
calls = []


def fake_load_dataset(supabase=None):
    return "DF", "IDX_DF"


def fake_run_schedule(df, idx_df, schedule):
    calls.append("ran")
    return res_df


orig_load_dataset, orig_run_schedule = wf.load_dataset, wf.run_schedule
wf.load_dataset, wf.run_schedule = fake_load_dataset, fake_run_schedule
try:
    flag_calls = []
    rows, table_md = fth.run_isolated_feature_test("fake", lambda enabled: flag_calls.append(enabled))
    assert flag_calls == [False, True, False], f"expected OFF, ON, restore-OFF, got {flag_calls}"
    assert calls == ["ran", "ran"], "run_schedule should be called once per state (OFF, ON)"
    assert rows["OFF"]["beat_bench"] == "1/2" and rows["ON"]["beat_bench"] == "1/2"
    print("[PASS] run_isolated_feature_test() calls set_flag(False), runs, set_flag(True), "
          "runs, then restores set_flag(False)")

    # restores to OFF even if the ON run raises
    def flaky_run_schedule(df, idx_df, schedule):
        if flag_calls_2 and flag_calls_2[-1] is True:
            raise RuntimeError("boom")
        return res_df

    flag_calls_2 = []
    wf.run_schedule = flaky_run_schedule
    try:
        fth.run_isolated_feature_test("fake2", lambda enabled: flag_calls_2.append(enabled))
        raised = False
    except RuntimeError:
        raised = True
    assert raised and flag_calls_2 == [False, True, False], (
        f"must still restore set_flag(False) after a mid-run exception, got {flag_calls_2}"
    )
    print("[PASS] run_isolated_feature_test() restores set_flag(False) even if a run raises")
finally:
    wf.load_dataset, wf.run_schedule = orig_load_dataset, orig_run_schedule

print("\nAll feature_test_harness checks passed.")
