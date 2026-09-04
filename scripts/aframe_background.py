#!/usr/bin/env python3
"""Time-shifted background study for the Aframe detection statistic.

Runs the pinned ``buoy.models.Aframe`` over long public GWOSC stretches,
both at zero lag and with the L1 series circularly shifted against H1 by
multiples of ``--shift-step`` seconds, and records the peak values of Buoy's
offline integrated statistic (``signif_integrated``, the quantity the agent
reports as ``detection_statistic``). The output JSON gives the empirical
false-alarm rate as a function of threshold, so ``aframe.detect`` can carry
a calibrated threshold instead of the raw ``0.0`` cut.

Method:

- every stretch is fetched through ``gwpy`` (set ``GWPY_CACHE=1`` and
  pre-fetch the files with ``prefetch_gwosc.py`` on slow nodes), resampled
  to the model's sample rate exactly as Buoy does, and analysed as one
  continuous segment;
- the first ``--burn-in`` seconds of each analysis (PSD estimation and
  whitening start-up) and ``--exclude-half-width`` seconds around every
  known event time are dropped;
- peaks are clustered with a ``--cluster-window`` minimum separation and
  counted; the background livetime is the sum of analysed durations over
  all lags, and FAR(x) = N(peaks >= x) / livetime;
- results are written incrementally after every lag so an interrupted run
  still yields a calibration.

Example::

    GWPY_CACHE=1 CUDA_VISIBLE_DEVICES=2 uv run python scripts/aframe_background.py \
        --revision 3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4 \
        --stretch 1126256640 1126260736 --event 1126259462.4 \
        --stretch 1187006835 1187010931 --event 1187008882.4 \
        --stretch 1242440920 1242445016 --event 1242442967.4 \
        --shifts 12 --output aframe_background.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

SECONDS_PER_YEAR = 365.25 * 86400.0
SECONDS_PER_DAY = 86400.0


def cluster_peaks(values: np.ndarray, rate: float, window: float) -> np.ndarray:
    """Return the values of local maxima separated by at least ``window`` s."""
    if values.size == 0:
        return values
    min_sep = max(1, int(round(window * rate)))
    order = np.argsort(values)[::-1]
    taken = np.zeros(values.size, dtype=bool)
    peaks = []
    for idx in order:
        if taken[idx]:
            continue
        peaks.append(float(values[idx]))
        lo, hi = max(0, idx - min_sep), min(values.size, idx + min_sep + 1)
        taken[lo:hi] = True
    return np.asarray(peaks)


def far_table(peaks: np.ndarray, livetime: float, thresholds: np.ndarray):
    counts = np.array([(peaks >= t).sum() for t in thresholds])
    return [
        {
            "threshold": float(t),
            "count": int(c),
            "far_per_second": float(c / livetime) if livetime else None,
            "far_per_year": (
                float(c / livetime * SECONDS_PER_YEAR) if livetime else None
            ),
        }
        for t, c in zip(thresholds, counts, strict=True)
    ]


def threshold_for_far(peaks: np.ndarray, livetime: float, far_per_year: float):
    """Smallest statistic whose empirical FAR is at or below the target."""
    if livetime <= 0 or peaks.size == 0:
        return None
    allowed = far_per_year / SECONDS_PER_YEAR * livetime
    ordered = np.sort(peaks)[::-1]
    n_allowed = int(np.floor(allowed))
    if n_allowed >= ordered.size:
        return float(ordered[-1])
    if n_allowed == 0:
        # no peak may exceed the threshold: place it just above the loudest
        return float(ordered[0]) + 1e-6
    return float(ordered[n_allowed - 1]) + 1e-6


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--revision", required=True, help="immutable Aframe revision")
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--stretch",
        nargs=2,
        type=float,
        action="append",
        required=True,
        metavar=("START", "END"),
        help="GPS interval to analyse (repeatable)",
    )
    parser.add_argument(
        "--event",
        type=float,
        action="append",
        default=[],
        help="known event time to exclude (repeatable)",
    )
    parser.add_argument("--exclude-half-width", type=float, default=16.0)
    parser.add_argument("--burn-in", type=float, default=80.0)
    parser.add_argument(
        "--shifts", type=int, default=10, help="time-shifted lags per stretch"
    )
    parser.add_argument("--shift-step", type=float, default=8.0)
    parser.add_argument("--cluster-window", type=float, default=8.0)
    parser.add_argument(
        "--min-segment",
        type=float,
        default=512.0,
        help="shortest gap-free segment (seconds) worth analysing",
    )
    parser.add_argument("--output", type=Path, default=Path("aframe_background.json"))
    parser.add_argument(
        "--peaks-output",
        type=Path,
        default=None,
        help="also save every clustered background peak (npy) for merging shards",
    )
    args = parser.parse_args(argv)

    import torch
    from buoy.models import Aframe
    from gwpy.timeseries import TimeSeries

    model = Aframe(device=args.device, revision=args.revision)
    sample_rate = float(model.sample_rate)
    offline_rate = float(model.offline_sampling_rate)
    stride = int(round(float(model.inference_sampling_rate) / offline_rate))
    print(
        f"Aframe {args.revision[:12]} sample_rate={sample_rate} "
        f"offline_rate={offline_rate} device={args.device}",
        file=sys.stderr,
    )

    result = {
        "model": {"repo_id": "ML4GW/aframe", "revision": args.revision},
        "statistic": "buoy signif_integrated (offline integrated network output)",
        "sample_rate": sample_rate,
        "offline_sampling_rate": offline_rate,
        "burn_in_seconds": args.burn_in,
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
        thresholds = np.round(np.arange(0.0, 12.01, 0.25), 3)
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
        if args.peaks_output is not None:
            np.save(args.peaks_output, peaks)

    segments: list[tuple[float, np.ndarray, np.ndarray]] = []
    for start, end in args.stretch:
        print(f"fetching [{start}, {end}) ...", file=sys.stderr)
        series = {}
        for ifo in ("H1", "L1"):
            # gwpy keeps gaps as NaN; they are split into segments below
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
        print(
            f"  {len(segments)} finite segments so far; dropped "
            f"{(~finite).sum() / sample_rate:.1f} s of gaps in this stretch",
            file=sys.stderr,
        )

    for start, h1, l1 in segments:
        for lag_index in range(args.shifts + 1):
            shift = lag_index * args.shift_step
            shifted_l1 = np.roll(l1, int(round(shift * sample_rate))) if shift else l1
            data = torch.as_tensor(np.stack([h1, shifted_l1])[None]).double()
            t_run = time.time()
            with torch.no_grad():
                times, _, _, signif = model(data, start)
            signif = np.asarray(signif, dtype="f8")
            signif_times = start + np.arange(signif.size) * stride / float(
                model.inference_sampling_rate
            )
            keep = signif_times >= start + args.burn_in
            for event in args.event:
                # the shifted L1 carries the event at event+shift as well
                for t_ev in (event, event + shift):
                    keep &= np.abs(signif_times - t_ev) > args.exclude_half_width
            kept = signif[keep]
            peaks = cluster_peaks(kept, offline_rate, args.cluster_window)
            livetime = float(keep.sum()) / offline_rate
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
                f"peaks {peaks.size:5d} max {loudest:.3f} "
                f"({time.time() - t_run:.1f}s) total livetime "
                f"{result['livetime_seconds'] / SECONDS_PER_DAY:.3f} d",
                file=sys.stderr,
            )
    print(json.dumps(result["thresholds"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
