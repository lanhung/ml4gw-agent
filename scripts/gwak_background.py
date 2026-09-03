#!/usr/bin/env python3
"""Time-shifted background study for the GWAK anomaly score.

Same design as ``aframe_background.py`` (same stretches, gap splitting,
event exclusion, circular L1 shifts, peak clustering, incremental output),
applied to the ``gwak.scan`` statistic: the negative log probability of the
SimCLR embedding under the background flow, computed exactly as the adapter
does (``ml4gw_agent.adapters.gwak``: normalised strain, PSD from the first
``psd_length`` seconds, whitening, 0.5 s kernels at the adapter stride).

The output JSON has the ``aframe_background.py`` layout so
``update_aframe_calibration.py --table calibration/gwak_thresholds.json``
folds it into the GWAK table.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

SECONDS_PER_YEAR = 365.25 * 86400.0
SECONDS_PER_DAY = 86400.0


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from aframe_background import cluster_peaks, far_table, threshold_for_far

    from ml4gw_agent.adapters.gwak import (
        default_model_dir,
        load_gwak_backend,
        load_manifest,
        unfold,
        verify_models,
    )

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--stretch", nargs=2, type=float, action="append", required=True
    )
    parser.add_argument("--event", type=float, action="append", default=[])
    parser.add_argument("--exclude-half-width", type=float, default=16.0)
    parser.add_argument("--shifts", type=int, default=10)
    parser.add_argument("--shift-step", type=float, default=8.0)
    parser.add_argument("--cluster-window", type=float, default=8.0)
    parser.add_argument("--min-segment", type=float, default=512.0)
    parser.add_argument("--batch", type=int, default=2048)
    parser.add_argument("--output", type=Path, default=Path("gwak_background.json"))
    args = parser.parse_args(argv)

    import torch
    from gwpy.timeseries import TimeSeries

    model_dir = args.model_dir or default_model_dir()
    manifest = load_manifest(model_dir)
    paths = verify_models(model_dir, manifest)
    pre = manifest["preprocessing"]
    sample_rate = float(pre["sample_rate"])
    kernel = int(round(float(pre["kernel_length_seconds"]) * sample_rate))
    stride_s = float(pre.get("stride_seconds", 0.0625))
    stride = max(1, int(round(stride_s * sample_rate)))
    psd_length = float(pre["psd_length_seconds"])
    fduration = float(pre["fduration_seconds"])
    fftlength = float(pre["fftlength_seconds"])
    highpass = pre.get("highpass_hz")
    backend = load_gwak_backend()
    embedder = backend.load_jit(paths["embedder"], args.device)
    metric = backend.load_jit(paths["metric"], "cpu")
    rate = 1.0 / stride_s

    result = {
        "model": {"repo_id": "models/gwak", "revision": manifest["revision"]},
        "statistic": "gwak -log p(embedding) (S4 SimCLR embedder + background flow)",
        "sample_rate": sample_rate,
        "offline_sampling_rate": rate,
        "burn_in_seconds": psd_length + fduration / 2,
        "exclude_half_width_seconds": args.exclude_half_width,
        "cluster_window_seconds": args.cluster_window,
        "shift_step_seconds": args.shift_step,
        "stretches": [],
        "excluded_events": args.event,
        "lags": [],
        "livetime_seconds": 0.0,
        "n_peaks": 0,
    }
    all_peaks: list[float] = []

    def write():
        peaks = np.asarray(all_peaks)
        livetime = result["livetime_seconds"]
        thresholds = np.round(np.arange(10.0, 20.01, 0.25), 3)
        result["n_peaks"] = int(peaks.size)
        result["peak_quantiles"] = (
            {
                str(q): float(np.quantile(peaks, q))
                for q in (0.5, 0.9, 0.99, 0.999, 0.9999)
            }
            if peaks.size
            else {}
        )
        result["loudest_background_peaks"] = [
            float(v) for v in np.sort(peaks)[::-1][:20]
        ]
        result["far_table"] = far_table(peaks, livetime, thresholds)
        result["thresholds"] = {
            "far_1_per_day": threshold_for_far(
                peaks, livetime, SECONDS_PER_YEAR / SECONDS_PER_DAY
            ),
            "far_1_per_month": threshold_for_far(peaks, livetime, 12.0),
            "far_1_per_year": threshold_for_far(peaks, livetime, 1.0),
            "far_1_per_100_years": threshold_for_far(peaks, livetime, 0.01),
        }
        result["livetime_days"] = livetime / SECONDS_PER_DAY
        result["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        args.output.write_text(json.dumps(result, indent=2) + "\n")

    def score(h1: np.ndarray, l1: np.ndarray, start: float):
        whitened = backend.whiten(
            np.stack([h1, l1]), sample_rate, psd_length, fduration, fftlength, highpass
        )
        kernels, starts = unfold(np.asarray(whitened, dtype="f4"), kernel, stride)
        scores = []
        with torch.no_grad():
            for i in range(0, kernels.shape[0], args.batch):
                emb = embedder(
                    backend.to_tensor(kernels[i : i + args.batch], args.device)
                )
                log_prob = metric(backend.to_tensor(backend.to_numpy(emb), "cpu"))
                scores.append(
                    -np.asarray(backend.to_numpy(log_prob), dtype="f8").reshape(-1)
                )
        scores = np.concatenate(scores)
        times = start + psd_length + fduration / 2 + (starts + kernel / 2) / sample_rate
        return scores, times

    segments = []
    for start, end in args.stretch:
        print(f"fetching [{start}, {end}) ...", file=sys.stderr)
        series = {}
        for ifo in ("H1", "L1"):
            ts = TimeSeries.fetch_open_data(ifo, start, end)
            if abs(float(ts.sample_rate.value) - sample_rate) > 1e-9:
                ts = ts.resample(sample_rate)
            series[ifo] = np.asarray(ts.value, dtype="f8")
        n = min(len(series["H1"]), len(series["L1"]))
        h1_all, l1_all = series["H1"][:n], series["L1"][:n]
        finite = np.isfinite(h1_all) & np.isfinite(l1_all)
        padded = np.concatenate(([0], finite.view(np.int8), [0]))
        edges = np.flatnonzero(np.diff(padded))
        minimum = int(args.min_segment * sample_rate)
        for lo, hi in zip(edges[::2], edges[1::2], strict=True):
            seg_start = start + lo / sample_rate
            duration = (hi - lo) / sample_rate
            usable = bool(hi - lo >= minimum)
            result["stretches"].append(
                {
                    "start": seg_start,
                    "end": seg_start + duration,
                    "duration": duration,
                    "analysed": usable,
                }
            )
            if usable:
                segments.append((seg_start, h1_all[lo:hi], l1_all[lo:hi]))

    for start, h1, l1 in segments:
        for lag_index in range(args.shifts + 1):
            shift = lag_index * args.shift_step
            shifted = np.roll(l1, int(round(shift * sample_rate))) if shift else l1
            t_run = time.time()
            scores, times = score(h1, shifted, start)
            keep = np.ones_like(scores, dtype=bool)
            for event in args.event:
                for t_ev in (event, event + shift):
                    keep &= np.abs(times - t_ev) > args.exclude_half_width
            kept = scores[keep]
            peaks = cluster_peaks(kept, rate, args.cluster_window)
            livetime = float(keep.sum()) / rate
            all_peaks.extend(peaks.tolist())
            result["livetime_seconds"] += livetime
            result["lags"].append(
                {
                    "stretch_start": start,
                    "shift_seconds": shift,
                    "livetime_seconds": livetime,
                    "n_peaks": int(peaks.size),
                    "max_statistic": float(kept.max()) if kept.size else None,
                    "runtime_seconds": time.time() - t_run,
                }
            )
            write()
            loudest = kept.max() if kept.size else float("nan")
            print(
                f"  stretch {start:.0f} shift {shift:5.1f}s: livetime {livetime:7.1f}s "
                f"peaks {peaks.size:5d} max {loudest:.3f} ({time.time() - t_run:.1f}s) "
                f"total {result['livetime_seconds'] / SECONDS_PER_DAY:.3f} d",
                file=sys.stderr,
            )
    print(json.dumps(result["thresholds"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
