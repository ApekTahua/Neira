"""test_sl_confidence.py -- isolated OFF-vs-ON 9-window walk-forward for
V4_SL_CONFIDENCE (research candidate, docs/V3_FINDINGS_LOG.md 2026-08-30 entry:
score-based confidence adjustment on the ATR stop-loss multiplier).

V4_ATR_PRICE_RATIO_MAX pinned to 0.08 (V4_PAPER's actual live config, per
.github/workflows/paper_signal_scan_v4_trigger.yml on main and the two most
recent broker-flow/divergence-gate sessions' own baseline convention) -- must be
set BEFORE backtest_v4 is imported (module-level constant, read once at import).

Usage:
    python src/test_sl_confidence.py               # default bounds (0.7/1.3)
    SL_CONF_MIN=0.5 SL_CONF_MAX=1.5 python src/test_sl_confidence.py
"""

import os

os.environ.setdefault("V4_ATR_PRICE_RATIO_MAX", "0.08")

import walk_forward_v4 as wf  # noqa: E402

bt = wf.bt

SL_CONF_MIN = float(os.environ.get("SL_CONF_MIN", "0.7"))
SL_CONF_MAX = float(os.environ.get("SL_CONF_MAX", "1.3"))


def set_sl_confidence(enabled: bool) -> None:
    bt.SL_CONFIDENCE_ENABLED = enabled
    bt.SL_CONFIDENCE_MIN = SL_CONF_MIN
    bt.SL_CONFIDENCE_MAX = SL_CONF_MAX


if __name__ == "__main__":
    from feature_test_harness import run_isolated_feature_test

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    sb = None
    if url and key:
        from supabase import create_client
        sb = create_client(url, key)

    label = f"sl_confidence [{SL_CONF_MIN},{SL_CONF_MAX}]"
    rows, table_md = run_isolated_feature_test(label, set_sl_confidence, supabase=sb)
    print("\n" + table_md)
