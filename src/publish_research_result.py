"""publish_research_result.py -- pushes a research CSV into Supabase.

Why: research jobs run in GitHub Actions and drop their output as a build
artifact, which needs an authenticated download to read. Writing the same
summary to a table instead makes every future run readable straight from
the database, with no token handling anywhere.

research_results is display/analysis only. Nothing reads it back into a
trading decision, and it is never touched by paper_signal_scan.py or
paper_monitor.py -- same isolation rule as daily_scoreboard.

Usage:
    python src/publish_research_result.py <job_name> <csv_path> [notes]
"""

import json
import os
import sys

import pandas as pd
from supabase import create_client


def main():
    if len(sys.argv) < 3:
        sys.exit("Usage: publish_research_result.py <job_name> <csv_path> [notes]")
    job, csv_path = sys.argv[1], sys.argv[2]
    notes = sys.argv[3] if len(sys.argv) > 3 else None

    if not os.path.exists(csv_path):
        print(f"[PUBLISH] {csv_path} not found -- nothing to publish.")
        return

    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("Missing SUPABASE_URL / SUPABASE_KEY")

    df = pd.read_csv(csv_path)
    # NaN is not valid JSON; None round-trips to SQL NULL.
    payload = json.loads(df.where(pd.notna(df), None).to_json(orient="records"))

    params = {
        k: v for k, v in os.environ.items()
        if k.startswith(("V4_", "SWEEP_", "DIAG_"))
    }

    create_client(url, key).table("research_results").insert({
        "job": job,
        "git_sha": os.environ.get("GITHUB_SHA"),
        "params": params,
        "rows": payload,
        "notes": notes,
    }).execute()
    print(f"[PUBLISH] {job}: {len(payload)} rows -> research_results")


if __name__ == "__main__":
    main()
