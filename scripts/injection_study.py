#!/usr/bin/env python3
"""Aframe and GWAK detection efficiency versus injected network SNR.

IMRPhenomD binary-black-hole signals are injected into 128 s windows of
public GWOSC strain (H1+L1) drawn from the stretches around GW150914 (O1),
GW170817 (O2) and GW190521 (O3) with the real events excluded, and each
injected window is analysed with the *real* ``aframe.detect`` and
``gwak.scan`` adapters exactly as the planner would invoke them (calibrated
1/day thresholds from the shipped tables, target time = injection time).

    uv run python scripts/injection_study.py --output docs/acceptance/injections \
        --runs-dir /root/autodl-tmp/ml4gw-agent-runs/injections --n-per-bin 20

Artifacts of each injection are deleted after analysis; the JSON keeps
every injection's parameters and both adapters' outputs.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

AFRAME_REVISION = "3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4"
GWAK_REVISION = "gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad"
WINDOW = 128.0
OFFSET = 96.0
# (start, end, excluded event zone) of cached GWOSC 4096 s stretches
STRETCHES = [
    ("O1", 1126256640, 1126260736, (1126259400.0, 1126259520.0)),
    ("O2", 1187006835, 1187010931, (1187008700.0, 1187008950.0)),
    ("O3", 1242440920, 1242445016, (1242442900.0, 1242443030.0)),
]


def windows() -> list[tuple[str, float]]:
    out = []
    for run, start, end, (ex_lo, ex_hi) in STRETCHES:
        t = start + 32.0
        while t + WINDOW <= end - 32.0:
            if t + WINDOW < ex_lo or t > ex_hi:
                out.append((run, float(t)))
            t += WINDOW
    return out


def cached_files() -> list[tuple[str, float, float, Path]]:
    """GWOSC HDF5 files already in the astropy download cache.

    Returns (ifo, start, duration, path). The study reads windows straight
    from these files so that no download is attempted (the GPU node's system
    disk is full and GWOSC transfers there run at ~70 kB/s).
    """
    import re

    from astropy.config import get_cache_dir

    root = Path(get_cache_dir()) / "download" / "url"
    out = []
    for url_file in root.glob("*/url"):
        url = url_file.read_text().strip()
        match = re.search(r"/([HLV])-([HLV]1)_[A-Z0-9_]+-(\d+)-(\d+)\.hdf5$", url)
        if match:
            _, ifo, start, duration = match.groups()
            out.append(
                (ifo, float(start), float(duration), url_file.parent / "contents")
            )
    return out


def fetch_window(t0: float, ifos: list[str], sample_rate: float):
    from gwpy.timeseries import TimeSeries

    from ml4gw_agent.adapters.strain_io import StrainData

    files = cached_files()
    series = {}
    for ifo in ifos:
        hits = [
            path
            for f_ifo, start, duration, path in files
            if f_ifo == ifo and start <= t0 and t0 + WINDOW <= start + duration
        ]
        if not hits:
            raise ValueError(f"no cached GWOSC file covers {ifo} [{t0}, {t0 + WINDOW})")
        ts = TimeSeries.read(
            str(hits[0]), format="hdf5.gwosc", start=t0, end=t0 + WINDOW
        )
        if abs(float(ts.sample_rate.value) - sample_rate) > 1e-9:
            ts = ts.resample(sample_rate)
        series[ifo] = np.asarray(ts.value, dtype="f8")
        if not np.isfinite(series[ifo]).all():
            raise ValueError(f"{ifo} has non-finite samples in [{t0}, {t0 + WINDOW})")
    n = min(len(v) for v in series.values())
    return StrainData(
        ifos=list(ifos),
        series={k: v[:n] for k, v in series.items()},
        t0=t0,
        sample_rate=sample_rate,
        source="gwosc",
    )


def draw_params(rng: np.random.Generator, tc: float, snr: float | None):
    from ml4gw_agent.adapters.injection import BBHInjection

    m1 = float(rng.uniform(10, 80))
    m2 = float(rng.uniform(10, m1))
    return BBHInjection(
        mass_1=m1,
        mass_2=m2,
        tc=tc,
        chi1=float(rng.uniform(-0.5, 0.5)),
        chi2=float(rng.uniform(-0.5, 0.5)),
        inclination=float(np.arccos(rng.uniform(-1, 1))),
        phase=float(rng.uniform(0, 2 * np.pi)),
        psi=float(rng.uniform(0, np.pi)),
        ra=float(rng.uniform(0, 2 * np.pi)),
        dec=float(np.arcsin(rng.uniform(-1, 1))),
        target_snr=snr,
    )


def run_adapter(registry, skill, task_id, params, run_dir):
    from ml4gw_agent.adapters import PYTHON_ADAPTERS
    from ml4gw_agent.adapters.base import ExecutionContext
    from ml4gw_agent.models import TaskSpec

    entry = {"aframe.detect": "aframe_inference", "gwak.scan": "gwak_snakemake"}
    context = ExecutionContext(
        skill=registry.get(skill),
        task=TaskSpec(id=task_id, skill=skill, parameters=params),
        parameters=params,
        run_dir=run_dir,
        mode="real",
        records={},
        prompt="injection study",
    )
    outcome = PYTHON_ADAPTERS[entry[skill]]().execute(context)
    keep = (
        "candidate_found",
        "detection_statistic",
        "predicted_coalescence_time",
        "peak_near_target",
        "target_offset_seconds",
        "anomaly_found",
        "max_score",
        "target_score",
        "target_zscore",
        "target_rank",
        "target_far_per_year",
        "max_far_per_year",
        "threshold",
        "threshold_calibrated",
    )
    return {k: outcome.outputs.get(k) for k in keep if k in outcome.outputs}


def _fmt(value, digits: int = 2) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}f}"


def efficiency(records: list[dict], key, bins):
    table = []
    for snr in bins:
        rows = [r for r in records if r["target_snr"] == snr and "error" not in r]
        if not rows:
            continue
        hits = sum(1 for r in rows if key(r))
        n = len(rows)
        table.append(
            {
                "target_snr": snr,
                "n": n,
                "detected": hits,
                "efficiency": hits / n,
                "err": float(np.sqrt(hits * (n - hits) / n) / n) if n else None,
            }
        )
    return table


def snr_at(table: list[dict], level: float) -> float | None:
    """Linear interpolation of the SNR where efficiency crosses ``level``."""
    pts = [(row["target_snr"], row["efficiency"]) for row in table if row["target_snr"]]
    pts.sort()
    for (s0, e0), (s1, e1) in zip(pts, pts[1:], strict=False):
        if e0 < level <= e1:
            return float(s0 + (level - e0) * (s1 - s0) / (e1 - e0))
    if pts and pts[0][1] >= level:
        return float(pts[0][0])
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--n-per-bin", type=int, default=20)
    parser.add_argument(
        "--snr", type=float, nargs="+", default=[6, 8, 10, 12, 15, 20, 30]
    )
    parser.add_argument("--controls", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--limit", type=int, default=None, help="debug: stop early")
    args = parser.parse_args(argv)

    from ml4gw_agent.adapters.deepclean_model import resample
    from ml4gw_agent.adapters.injection import inject_bbh
    from ml4gw_agent.adapters.strain_io import StrainData, write_strain
    from ml4gw_agent.calibration import aframe_threshold, gwak_threshold
    from ml4gw_agent.registry import load_default_registry

    registry = load_default_registry()
    aframe_cal = aframe_threshold(AFRAME_REVISION, 365.25)
    gwak_cal = gwak_threshold(GWAK_REVISION, 365.25)
    assert aframe_cal is not None and gwak_cal is not None
    rng = np.random.default_rng(args.seed)
    wins = windows()
    plan = [(None, i) for i in range(args.controls)]
    for snr in args.snr:
        plan += [(float(snr), i) for i in range(args.n_per_bin)]
    rng.shuffle(plan)
    if args.limit:
        plan = plan[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    args.runs_dir.mkdir(parents=True, exist_ok=True)
    out_json = args.output / "injection_study.json"
    records = []
    if out_json.is_file():
        records = json.loads(out_json.read_text())["records"]
        done = {(r["target_snr"], r["index"]) for r in records}
        plan = [p for p in plan if p not in done]
    print(f"{len(wins)} noise windows, {len(plan)} injections to run", file=sys.stderr)

    def save():
        result = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "aframe": {
                "revision": AFRAME_REVISION,
                "calibration": aframe_cal.as_dict(),
            },
            "gwak": {"revision": GWAK_REVISION, "calibration": gwak_cal.as_dict()},
            "window_seconds": WINDOW,
            "injection_offset_seconds": OFFSET,
            "stretches": [
                dict(run=r, start=s, end=e, excluded=x) for r, s, e, x in STRETCHES
            ],
            "n_windows": len(wins),
            "records": records,
            "efficiency": summarise(records, args.snr),
        }
        out_json.write_text(json.dumps(result, indent=1) + "\n")

    bad_windows: set[float] = set()
    for k, (snr, index) in enumerate(plan):
        slot = index * 7 + int(snr or 0)
        strain4k = None
        for attempt in range(len(wins)):
            run_label, t0 = wins[(slot + attempt) % len(wins)]
            if t0 in bad_windows:
                continue
            try:
                strain4k = fetch_window(t0, ["H1", "L1"], 4096.0)
                break
            except ValueError as exc:  # gaps (NaN) in the public data
                print(f"skipping window {t0}: {exc}", file=sys.stderr)
                bad_windows.add(t0)
        tc = t0 + OFFSET
        started = time.time()
        rec = {
            "target_snr": snr,
            "index": index,
            "run": run_label,
            "window_t0": t0,
            "tc": tc,
        }
        run_dir = args.runs_dir / f"inj_{k:04d}"
        try:
            if strain4k is None:
                raise RuntimeError("no gap-free noise window available")
            if snr is not None:
                params = draw_params(rng, tc, snr)
                strain4k, params = inject_bbh(strain4k, params)
                rec["injection"] = params.as_dict()
            run_dir.mkdir(parents=True, exist_ok=True)
            art4k = write_strain(
                run_dir / "artifacts" / "fetch_data_4k" / "strain.hdf5", strain4k
            )
            strain2k = StrainData(
                ifos=strain4k.ifos,
                series={
                    i: resample(strain4k.series[i], 4096.0, 2048.0)
                    for i in strain4k.ifos
                },
                t0=t0,
                sample_rate=2048.0,
                source="gwosc",
            )
            art2k = write_strain(
                run_dir / "artifacts" / "fetch_data" / "strain.hdf5", strain2k
            )
            rec["aframe"] = run_adapter(
                registry,
                "aframe.detect",
                "run_aframe",
                {
                    "strain_artifact": art2k.relative_to(run_dir).as_posix(),
                    "ifos": ["H1", "L1"],
                    "model_revision": AFRAME_REVISION,
                    "device": args.device,
                    "threshold": aframe_cal.threshold,
                    "threshold_calibration": aframe_cal.as_dict(),
                    "target_time": tc,
                    "candidate_window_seconds": 2.0,
                    "seed": args.seed,
                },
                run_dir,
            )
            rec["gwak"] = run_adapter(
                registry,
                "gwak.scan",
                "run_gwak",
                {
                    "strain_artifact": art4k.relative_to(run_dir).as_posix(),
                    "model_revision": GWAK_REVISION,
                    "top_k": 10,
                    "threshold": gwak_cal.threshold,
                    "threshold_calibration": gwak_cal.as_dict(),
                    "target_time": tc,
                    "device": args.device,
                    "seed": args.seed,
                },
                run_dir,
            )
        except Exception as exc:  # noqa: BLE001 - record and continue
            rec["error"] = f"{type(exc).__name__}: {exc}"[:400]
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)
        rec["seconds"] = time.time() - started
        records.append(rec)
        af = rec.get("aframe", {})
        gw = rec.get("gwak", {})
        print(
            f"[{k + 1}/{len(plan)}] snr {snr} {run_label} aframe stat "
            f"{_fmt(af.get('detection_statistic'))} found {af.get('candidate_found')}"
            f" | gwak target {_fmt(gw.get('target_score'))} z "
            f"{_fmt(gw.get('target_zscore'), 1)} rank {gw.get('target_rank')} | "
            f"{rec['seconds']:.0f}s {rec.get('error', '')}",
            file=sys.stderr,
            flush=True,
        )
        save()
    plot(out_json, args.output / "efficiency.png")
    return 0


def summarise(records, bins):
    def aframe_hit(r):
        return bool(r.get("aframe", {}).get("candidate_found"))

    def gwak_flag(r):
        return bool(r.get("gwak", {}).get("anomaly_found"))

    def gwak_loudest(r):
        return r.get("gwak", {}).get("target_rank") == 0

    def gwak_z5(r):
        z = r.get("gwak", {}).get("target_zscore")
        return z is not None and z >= 5.0

    tables = {
        "aframe_candidate_1_per_day": efficiency(records, aframe_hit, bins),
        "gwak_anomaly_1_per_day": efficiency(records, gwak_flag, bins),
        "gwak_target_is_loudest_kernel": efficiency(records, gwak_loudest, bins),
        "gwak_target_zscore_ge_5": efficiency(records, gwak_z5, bins),
    }
    controls = [r for r in records if r["target_snr"] is None and "error" not in r]
    summary = {
        name: {
            "table": table,
            "snr_50": snr_at(table, 0.5),
            "snr_90": snr_at(table, 0.9),
        }
        for name, table in tables.items()
    }
    summary["controls"] = {
        "n": len(controls),
        "aframe_false_candidates": sum(1 for r in controls if aframe_hit(r)),
        "gwak_false_anomalies": sum(1 for r in controls if gwak_flag(r)),
        "aframe_statistic_median": float(
            np.median([r["aframe"]["detection_statistic"] for r in controls])
        )
        if controls
        else None,
        "gwak_target_zscore_median": float(
            np.median(
                [
                    r["gwak"]["target_zscore"]
                    for r in controls
                    if r["gwak"].get("target_zscore") is not None
                ]
            )
        )
        if controls
        else None,
    }
    return summary


def plot(json_path: Path, png_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    result = json.loads(json_path.read_text())
    eff = result["efficiency"]
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    styles = {
        "aframe_candidate_1_per_day": ("Aframe candidate (1/day cut)", "o-"),
        "gwak_anomaly_1_per_day": ("GWAK anomaly (1/day cut)", "s--"),
        "gwak_target_is_loudest_kernel": ("GWAK: injection is loudest kernel", "^:"),
        "gwak_target_zscore_ge_5": ("GWAK: z-score >= 5", "d-."),
    }
    for name, (label, style) in styles.items():
        table = eff[name]["table"]
        x = [row["target_snr"] for row in table]
        y = [row["efficiency"] for row in table]
        e = [row["err"] or 0 for row in table]
        ax.errorbar(x, y, yerr=e, fmt=style, label=label, capsize=2)
    ax.set_xlabel("injected optimal network SNR")
    ax.set_ylabel("efficiency")
    ax.set_ylim(-0.02, 1.02)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(png_path, dpi=150)


if __name__ == "__main__":
    raise SystemExit(main())
