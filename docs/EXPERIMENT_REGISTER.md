# Experiment register

One line per sweep, **written before it runs**. Rule 3 of
`docs/HOLDOUT_PROTOCOL.md`.

The point is arithmetic, not bureaucracy. A multiple-comparisons correction
needs to know how many comparisons were made, and on 2026-09-05 that number
could only be recovered as "at least 262" by digging through CSV filenames and
git history. Anything not in this file is an unknown addition to that count, and
every unlogged run makes every reported figure weaker.

Fields: **date | what varies | cells | the one deciding metric | prediction
before running**. The prediction field is not decoration — writing it down is
what stops the metric being chosen after the numbers are in.

---

## Backfill (recovered, not pre-registered)

| Period | What | Cells | Note |
|---|---|---|---|
| 2026-06 .. 2026-09-04 | V4 development: 11 graded experiments plus the original validation, all against the same nine windows | **≥ 262** | Floor, recovered by audit `140d40f`. The true count is unknown and unknowable. |

---

## Pre-registered

| Date | What varies | Cells | Deciding metric | Prediction |
|---|---|---|---|---|
| 2026-09-05 | Slippage cost: `(base_bps, impact_bps)` ∈ {(0,0), (5,16), (10,30), (20,50), (35,80)} × 3 partitions | 15 | Mean walk-forward alpha at the production trail (0.08), read as a *slope* across cost levels, not a level | The trailing exit fills at `close_price` and carries 92.1% of gross profit, so cost should bite roughly linearly. If alpha at (20,50) is still clearly positive on all three cuts, the result is not an artifact of the zero-cost assumption. If it goes to zero by (10,30), it is. |
| 2026-09-05 | Trailing-stop width ∈ {0.05 .. 0.12 step 0.01} × 3 partitions | 24 | Shape of the alpha surface around production 0.08 — specifically the drop to the worst immediate neighbour (0.07 or 0.09) | 0.08 was never swept; it was chosen. If the two neighbours cost more than ~5pp of mean alpha, 0.08 is a spike and the 92.1% figure is a coincidence of one parameter value. A plateau means the mechanism is real even if the exact number is not. |
| 2026-09-05 | Nothing -- a measurement, not a sweep. Capture ratio (realised position return / best close-to-close gain available in the 60 sessions after entry), split by exit reason, on run 37's positions | 1 | **Median capture ratio by exit reason, restricted to positions whose available peak beat +25%** -- the tail draws, since capture on a position that never ran is not a question about the tail | The trailing stop already carries 92.1% of gross profit, so it should show the highest capture. The hypothesis worth killing is that the leak is spread evenly: if it is, the exit is roughly as good as an 8% trail can be and the entry is the thing to improve. If one exit reason is far worse than the others on tail positions, that reason is the leak and it is fixable. |

**Neither of the two above may promote anything** — they run on the nine
windows, which Rule 1 closes for promotion. They are robustness readings: they
can only tell us that something we already believe is fragile.

---

## How to add a row

Append the row, commit it, *then* start the run. A row added afterwards is
backfill and goes in the section above, labelled as such.
