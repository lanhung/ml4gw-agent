#!/usr/bin/env python3
"""Merge sharded background studies (one JSON + one peaks .npy per shard,
from ``aframe_background.py`` / ``gwak_background.py --peaks-output``) into a
single result with the same layout, so ``update_aframe_calibration.py`` can
fold it into a calibration table.

    python scripts/merge_background.py shards/*.json --output merged.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aframe_background import (  # noqa: E402
    SECONDS_PER_DAY,
    SECONDS_PER_YEAR,
    far_table,
    threshold_for_far,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("shards", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--peaks-output", type=Path, default=None)
    args = parser.parse_args(argv)

    merged: dict | None = None
    peaks: list[np.ndarray] = []
    for shard in args.shards:
        result = json.loads(shard.read_text())
        npy = shard.with_suffix(".npy")
        if not npy.is_file():
            raise SystemExit(f"{shard}: no peaks file {npy} (run with --peaks-output)")
        peaks.append(np.load(npy))
        if merged is None:
            merged = {
                k: v
                for k, v in result.items()
                if k
                not in (
                    "lags",
                    "stretches",
                    "excluded_events",
                    "livetime_seconds",
                    "n_peaks",
                    "peak_quantiles",
                    "loudest_background_peaks",
                    "far_table",
                    "thresholds",
                    "livetime_days",
                    "generated_at",
                )
            }
            merged.update(
                {"lags": [], "stretches": [], "excluded_events": [], "shards": []}
            )
        elif result["model"] != merged["model"]:
            raise SystemExit(f"{shard}: model {result['model']} differs")
        merged["lags"].extend(result["lags"])
        merged["stretches"].extend(result["stretches"])
        merged["excluded_events"].extend(result.get("excluded_events", []))
        merged["shards"].append(
            {"file": shard.name, "livetime_seconds": result["livetime_seconds"]}
        )
    assert merged is not None
    all_peaks = np.concatenate(peaks) if peaks else np.zeros(0)
    livetime = float(sum(s["livetime_seconds"] for s in merged["shards"]))
    lo, hi = (0.0, 12.01) if "aframe" in json.dumps(merged["model"]) else (10.0, 20.01)
    thresholds = np.round(np.arange(lo, hi, 0.25), 3)
    merged["livetime_seconds"] = livetime
    merged["n_peaks"] = int(all_peaks.size)
    merged["peak_quantiles"] = {
        str(q): float(np.quantile(all_peaks, q))
        for q in (0.5, 0.9, 0.99, 0.999, 0.9999)
    }
    merged["loudest_background_peaks"] = [
        float(v) for v in np.sort(all_peaks)[::-1][:20]
    ]
    merged["far_table"] = far_table(all_peaks, livetime, thresholds)
    merged["thresholds"] = {
        "far_1_per_day": threshold_for_far(
            all_peaks, livetime, SECONDS_PER_YEAR / SECONDS_PER_DAY
        ),
        "far_1_per_month": threshold_for_far(all_peaks, livetime, 12.0),
        "far_1_per_year": threshold_for_far(all_peaks, livetime, 1.0),
        "far_1_per_100_years": threshold_for_far(all_peaks, livetime, 0.01),
    }
    merged["livetime_days"] = livetime / SECONDS_PER_DAY
    merged["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    args.output.write_text(json.dumps(merged, indent=2) + "\n")
    if args.peaks_output is not None:
        np.save(args.peaks_output, all_peaks)
    print(
        f"{len(args.shards)} shards, livetime {merged['livetime_days']:.2f} d, "
        f"{merged['n_peaks']} peaks, thresholds {merged['thresholds']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
