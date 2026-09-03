#!/usr/bin/env python3
"""Fold an ``aframe_background.py`` result into the shipped calibration table.

Only false-alarm rates the study can actually measure are written: a rate
needs at least one expected background event above the threshold within the
analysed livetime, so with L days of livetime the tightest rate is 1/L per
day. Rates below that are left out rather than extrapolated; the planner
then falls back to the raw cut with a warning for such requests.

    python scripts/update_aframe_calibration.py background.json \
        --table src/ml4gw_agent/calibration/aframe_thresholds.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SECONDS_PER_YEAR = 365.25 * 86400.0
NAMED_RATES = {
    "far_1_per_day": 365.25,
    "far_1_per_month": 12.0,
    "far_1_per_year": 1.0,
    "far_1_per_100_years": 0.01,
}


def measurable_thresholds(result: dict) -> dict[str, float]:
    livetime = float(result["livetime_seconds"])
    thresholds: dict[str, float] = {}
    for name, per_year in NAMED_RATES.items():
        value = result.get("thresholds", {}).get(name)
        expected_events = per_year / SECONDS_PER_YEAR * livetime
        if value is None or expected_events < 1.0:
            continue
        thresholds[f"{per_year:g}"] = float(value)
    return thresholds


def far_curve(result: dict) -> list[list[float]]:
    """Monotone (threshold, FAR per year) points: the far table plus the
    loudest background peaks (rank / livetime), so a score above the table's
    last row still maps to a measured rate."""
    livetime = float(result["livetime_seconds"])
    points = {
        float(row["threshold"]): float(row["far_per_year"])
        for row in result.get("far_table", [])
        if row.get("far_per_year") is not None
    }
    loudest = sorted(result.get("loudest_background_peaks", []), reverse=True)
    for rank, value in enumerate(loudest, start=1):
        points.setdefault(float(value), rank / livetime * SECONDS_PER_YEAR)
    return [[t, points[t]] for t in sorted(points)]


def entry_from_result(result: dict, source: str) -> dict:
    return {
        "source": source,
        "generated_at": result.get("generated_at"),
        "statistic": result.get("statistic"),
        "livetime_seconds": float(result["livetime_seconds"]),
        "livetime_days": float(result["livetime_seconds"]) / 86400.0,
        "n_peaks": int(result.get("n_peaks", 0)),
        "loudest_background_peaks": result.get("loudest_background_peaks", [])[:5],
        "stretches": [
            {k: s[k] for k in ("start", "end", "duration") if k in s}
            for s in result.get("stretches", [])
            if s.get("analysed", True)
        ],
        "excluded_events": result.get("excluded_events", []),
        "shift_step_seconds": result.get("shift_step_seconds"),
        "n_lags": len(result.get("lags", [])),
        "thresholds_by_far_per_year": measurable_thresholds(result),
        "far_curve": far_curve(result),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("result", type=Path)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument(
        "--source", default="scripts/aframe_background.py (time-shifted GWOSC)"
    )
    args = parser.parse_args(argv)
    result = json.loads(args.result.read_text())
    table = json.loads(args.table.read_text())
    revision = result["model"]["revision"]
    entry = entry_from_result(result, args.source)
    table.setdefault("revisions", {})[revision] = entry
    args.table.write_text(json.dumps(table, indent=2) + "\n")
    print(
        f"{revision[:12]}: livetime {entry['livetime_days']:.2f} d, "
        f"{entry['n_peaks']} peaks, thresholds {entry['thresholds_by_far_per_year']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
