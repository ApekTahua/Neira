"""trace_w8_rotation.py -- concrete mechanistic trace for the fourth "small change,
huge W8 swing" case this session, following the exact pattern trace_w8_slot_swaps.py
already used for the tick-size fix / spike-confirm-gate / REGIME_CONFIRM_DAYS=2:
ROTATION_ENABLED at ROTATION_MARGIN_MULT=2.0, the sweep's own best-looking single
value (docs/V3_FINDINGS_LOG.md, "cross-day position rotation" entry) -- W8 alpha
+59.56% (OFF) -> +160.60% (ON), +101.04pp, 83.6% of the entire 9-window schedule's
net aggregate delta at that setting.

Usage: SUPABASE_URL=... SUPABASE_KEY=... python src/trace_w8_rotation.py
(no creds needed if .cache/walk_forward_data_*.pkl already exists.)
"""

import os
from datetime import date

import pandas as pd

os.environ.setdefault("V3_BANDAR_SIZING", "0")

import walk_forward_v4 as wf  # noqa: E402
from trace_w8_slot_swaps import run_w8, report_pair  # noqa: E402

bt = wf.bt

if __name__ == "__main__":
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    sb = None
    if url and key:
        from supabase import create_client
        sb = create_client(url, key)

    df, idx_df = wf.load_dataset(sb)

    print("Running baseline (ROTATION_ENABLED=False) ...")
    bt.ROTATION_ENABLED = False
    alpha_off, trades_off, diag_off = run_w8(df, idx_df, "W8-rotation-off")

    print("\nRunning ROTATION_ENABLED=True, ROTATION_MARGIN_MULT=2.0 ...")
    bt.ROTATION_ENABLED = True
    bt.ROTATION_MARGIN_MULT = 2.0
    alpha_on, trades_on, diag_on = run_w8(df, idx_df, "W8-rotation-on")
    bt.ROTATION_ENABLED = False

    report_pair("ROTATION_MARGIN_MULT=2.0 (OFF=no rotation, ON=rotation enabled)",
                alpha_off, trades_off, diag_off, alpha_on, trades_on, diag_on)

    # Extra, rotation-specific: how many rotations fired before the first divergence date,
    # and what were they -- directly shows whether the cascade's ORIGIN is a rotation event.
    only_off, only_on = set(zip(trades_off["stock_code"], trades_off["entry_date"])), set(zip(trades_on["stock_code"], trades_on["entry_date"]))
    diverge_dates = [d for _, d in (only_off - only_on)] + [d for _, d in (only_on - only_off)]
    first_date = min(diverge_dates) if diverge_dates else None
    print(f"\nRotations in the ON run before/at first divergence ({first_date}):")
    for d in diag_on.get("days", []):
        if d["date"] <= first_date and d.get("rotated"):
            for r in d["rotated"]:
                print(f"  {d['date']}: rotated OUT {r['stock_code']} (score {r['victim_score']:.2f}, "
                      f"held {r['victim_hold_days']}d) to admit {r['incoming_stock_code']} "
                      f"(score {r['incoming_score']:.2f})")
    print(f"\nTotal rotations in the full ON run: {sum(len(d.get('rotated') or []) for d in diag_on.get('days', []))}")
