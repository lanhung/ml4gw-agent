#!/usr/bin/env python3
"""Population statistics and figures from ``population_compare.py`` output.

    python scripts/population_figures.py docs/acceptance/population-2026-09-04/summary.json \
        --outdir docs/acceptance/population-2026-09-04
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("summary", type=Path)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = json.loads(args.summary.read_text())
    completed = [r for r in rows if r.get("status") == "completed"]
    failed = [r for r in rows if r.get("status") != "completed"]
    # runs whose Aframe step was skipped by the data-quality gate are not misses
    gated = [
        r for r in completed if (r.get("tasks") or {}).get("run_aframe") == "skipped"
    ]
    done = [r for r in completed if r not in gated]
    stats: dict = {
        "events": len(rows),
        "completed": len(completed),
        "quality_gated": [r["event"] for r in gated],
        "analysed": len(done),
        "failed": [
            {"event": r["event"], "task": next(iter(r.get("errors") or {}), None)}
            for r in failed
        ],
    }
    # Aframe recovery
    found = [r for r in done if (r.get("aframe") or {}).get("candidate_found")]
    stats["aframe_found"] = len(found)
    in_range = [r for r in done if (r["catalog"].get("m2") or 0) >= 5]
    found_in_range = [
        r for r in in_range if (r.get("aframe") or {}).get("candidate_found")
    ]
    stats["aframe_found_m2_ge_5"] = [len(found_in_range), len(in_range)]
    bins = [(0, 8), (8, 10), (10, 12), (12, 15), (15, 20), (20, 100)]
    stats["aframe_recovery_by_snr"] = []
    for lo, hi in bins:
        sel = [r for r in done if lo <= (r["catalog"].get("snr") or 0) < hi]
        n = sum(1 for r in sel if (r.get("aframe") or {}).get("candidate_found"))
        stats["aframe_recovery_by_snr"].append(
            {"snr": [lo, hi], "found": n, "of": len(sel)}
        )
    misses = sorted(
        (
            {
                "event": r["event"],
                "snr": r["catalog"].get("snr"),
                "m1": r["catalog"].get("m1"),
                "m2": r["catalog"].get("m2"),
                "statistic": (r.get("aframe") or {}).get("statistic"),
                "tc_offset": (r.get("aframe") or {}).get("tc_offset_seconds"),
            }
            for r in done
            if not (r.get("aframe") or {}).get("candidate_found")
        ),
        key=lambda x: -(x["snr"] or 0),
    )
    stats["aframe_misses"] = misses
    stats["aframe_misses_m2_lt_5"] = [m["event"] for m in misses if (m["m2"] or 0) < 5]
    stats["aframe_misses_bbh_snr"] = sorted(
        round(m["snr"] or 0, 1) for m in misses if (m["m2"] or 0) >= 5
    )
    offsets = [
        abs(r["aframe"]["tc_offset_seconds"])
        for r in found
        if r["aframe"].get("tc_offset_seconds") is not None
    ]
    if offsets:
        offsets.sort()
        stats["tc_offset_abs_median"] = statistics.median(offsets)
        stats["tc_offset_abs_p90"] = offsets[int(0.9 * (len(offsets) - 1))]
    # AMPLFI coverage
    for key in ("chirp_mass_source", "mass_1_source", "mass_2_source", "distance"):
        vals = [
            r["amplfi"][key]
            for r in found
            if key in (r.get("amplfi") or {}) and "catalog_in_90" in r["amplfi"][key]
        ]
        if vals:
            stats[f"amplfi_{key}"] = {
                "n": len(vals),
                "in_90": sum(v["catalog_in_90"] for v in vals),
                "median_ratio": statistics.median(v["ratio"] for v in vals),
            }
    # GWAK
    g = [
        r["gwak"]
        for r in done
        if r.get("gwak") and r["gwak"].get("target_score") is not None
    ]
    if g:
        stats["gwak"] = {
            "n": len(g),
            "rank0": sum(1 for x in g if x.get("target_rank") == 0),
            "rank_le_10": sum(1 for x in g if (x.get("target_rank") or 999) <= 10),
            "median_zscore": statistics.median(
                x["target_zscore"] for x in g if x.get("target_zscore") is not None
            ),
            "anomaly_found": sum(1 for x in g if x.get("anomaly_found")),
        }
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "population_stats.json").write_text(
        json.dumps(stats, indent=1) + "\n"
    )
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:  # pragma: no cover
        print(json.dumps(stats, indent=1))
        return 0
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    snr = [r["catalog"].get("snr") or 0 for r in done]
    stat = [(r.get("aframe") or {}).get("statistic") or 0 for r in done]
    col = [
        "C0" if (r.get("aframe") or {}).get("candidate_found") else "C3" for r in done
    ]
    axes[0].scatter(snr, stat, c=col, s=18)
    axes[0].axhline(2.701, ls="--", c="k", lw=0.8, label="1/day threshold")
    axes[0].set_xlabel("catalog network SNR")
    axes[0].set_ylabel("Aframe statistic")
    axes[0].legend()
    axes[0].set_title(f"Aframe: {len(found)}/{len(done)} recovered")
    cat = [
        r["amplfi"]["chirp_mass_source"]["catalog"]
        for r in found
        if "chirp_mass_source" in (r.get("amplfi") or {})
        and "catalog" in r["amplfi"]["chirp_mass_source"]
    ]
    med = [
        r["amplfi"]["chirp_mass_source"]["median"]
        for r in found
        if "chirp_mass_source" in (r.get("amplfi") or {})
        and "catalog" in r["amplfi"]["chirp_mass_source"]
    ]
    lo = [
        r["amplfi"]["chirp_mass_source"]["p5"]
        for r in found
        if "chirp_mass_source" in (r.get("amplfi") or {})
        and "catalog" in r["amplfi"]["chirp_mass_source"]
    ]
    hi = [
        r["amplfi"]["chirp_mass_source"]["p95"]
        for r in found
        if "chirp_mass_source" in (r.get("amplfi") or {})
        and "catalog" in r["amplfi"]["chirp_mass_source"]
    ]
    if cat:
        axes[1].errorbar(
            cat,
            med,
            yerr=[[m - l for m, l in zip(med, lo)], [h - m for m, h in zip(med, hi)]],
            fmt="o",
            ms=3,
            lw=0.6,
        )
        m = max(cat + med)
        axes[1].plot([0, m], [0, m], "k--", lw=0.8)
        axes[1].set_xscale("log")
        axes[1].set_yscale("log")
        axes[1].set_xlabel("GWTC source chirp mass [Msun]")
        axes[1].set_ylabel("AMPLFI median (90% interval)")
        axes[1].set_title("AMPLFI vs catalog")
    gs = [
        (r["catalog"].get("snr") or 0, r["gwak"]["target_zscore"])
        for r in done
        if r.get("gwak") and r["gwak"].get("target_zscore") is not None
    ]
    if gs:
        axes[2].scatter([a for a, _ in gs], [b for _, b in gs], s=18, c="C2")
        axes[2].set_xlabel("catalog network SNR")
        axes[2].set_ylabel("GWAK z-score at target")
        axes[2].set_title("GWAK")
    fig.tight_layout()
    fig.savefig(args.outdir / "population.png", dpi=130)
    print(
        json.dumps({k: v for k, v in stats.items() if k != "aframe_misses"}, indent=1)[
            :1500
        ]
    )
    print("misses:", [(m["event"], m["snr"], m["m2"]) for m in misses][:25])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
