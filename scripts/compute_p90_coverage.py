"""Retrospective P90 interval coverage for the Croston/SBA nightly bake.

For a stockout-risk agent, interval coverage is a more load-bearing accuracy
signal than sMAPE: the question is not "how far off is the point forecast"
but "does the P90 envelope actually contain realized demand 90% of the time?"
If coverage is well below 0.90, stockout-date estimates are systematically
over-optimistic; if it is well above, safety stock is being over-recommended.

Methodology
-----------
- Load the carparts benchmark (200 parts x 51 months, real Hyndman data).
- Holdout the last 12 months. Train on months 1..39.
- Run Croston/SBA with the same code path the nightly bake uses
  (`fabops.tools._croston_numpy.croston(..., variant="sba")`).
- Count: for each (part, holdout_month), does realized <= p90?
- Coverage = fraction of (part, month) pairs where the inequality holds.
- Also report per-part coverage summary so the distribution is visible.

Result is printed to stdout and written as JSON to
`evals/results/p90_coverage.json` for the REPORT to cite.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import median
from typing import Dict, List

from fabops.tools._croston_numpy import croston


REPO_ROOT = Path(__file__).resolve().parent.parent
CARPARTS_CSV = REPO_ROOT / "data" / "carparts.csv"
OUT_JSON = REPO_ROOT / "evals" / "results" / "p90_coverage.json"

HOLDOUT_MONTHS = 12
TRAIN_MIN_LEN = 12  # fewer than 12 months of history: skip the part


def load_carparts_wide() -> Dict[str, List[float]]:
    """Return {part_id: [demand_month_0, ...]} from the wide-format carparts.csv."""
    with CARPARTS_CSV.open() as f:
        reader = csv.reader(f)
        header = next(reader)
        part_ids = header[1:]
        columns: List[List[float]] = [[] for _ in part_ids]
        for row in reader:
            for i, cell in enumerate(row[1:]):
                # Carparts has sporadic 'NA' values for the earliest months of
                # some parts. Treat as zero demand (consistent with the
                # intermittent-series convention the nightly bake uses).
                columns[i].append(0.0 if cell == "NA" else float(cell))
    return dict(zip(part_ids, columns))


def compute_coverage() -> Dict:
    series = load_carparts_wide()
    per_part_coverage: List[float] = []
    total_pairs = 0
    covered_pairs = 0
    skipped_too_short = 0
    per_part_rows: List[Dict] = []

    for part_id, full in series.items():
        if len(full) < TRAIN_MIN_LEN + HOLDOUT_MONTHS:
            skipped_too_short += 1
            continue
        train = full[:-HOLDOUT_MONTHS]
        holdout = full[-HOLDOUT_MONTHS:]
        _, _, p90 = croston(train, horizon=HOLDOUT_MONTHS, variant="sba")
        hits = sum(1 for realized, envelope in zip(holdout, p90) if realized <= envelope)
        part_cov = hits / HOLDOUT_MONTHS
        per_part_coverage.append(part_cov)
        total_pairs += HOLDOUT_MONTHS
        covered_pairs += hits
        per_part_rows.append({
            "part_id": part_id,
            "holdout_months": HOLDOUT_MONTHS,
            "hits": hits,
            "coverage": round(part_cov, 4),
        })

    overall = covered_pairs / total_pairs if total_pairs else 0.0
    per_part_coverage.sort()

    def pct(data: List[float], p: float) -> float:
        if not data:
            return 0.0
        idx = min(len(data) - 1, int(len(data) * p))
        return data[idx]

    summary = {
        "metric": "p90_interval_coverage",
        "definition": (
            "Fraction of (part, holdout_month) pairs where realized demand <= "
            "Croston/SBA p90 forecast envelope. Target: 0.90."
        ),
        "training_months": "1..39",
        "holdout_months": "40..51",
        "model": "croston_sba",
        "n_parts_evaluated": len(per_part_coverage),
        "n_parts_skipped": skipped_too_short,
        "total_pairs": total_pairs,
        "covered_pairs": covered_pairs,
        "overall_coverage": round(overall, 4),
        "per_part_coverage_summary": {
            "mean": round(sum(per_part_coverage) / len(per_part_coverage), 4) if per_part_coverage else 0.0,
            "median": round(median(per_part_coverage), 4) if per_part_coverage else 0.0,
            "p10": round(pct(per_part_coverage, 0.10), 4),
            "p90": round(pct(per_part_coverage, 0.90), 4),
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({"summary": summary, "per_part": per_part_rows}, indent=2))
    return summary


if __name__ == "__main__":
    s = compute_coverage()
    print(json.dumps(s, indent=2))
