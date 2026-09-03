#!/usr/bin/env python3
"""Compare an ML4GW Agent run against a direct Buoy run of the same event.

Usage:
    python scripts/compare_with_buoy.py <agent_run_dir> <buoy_outdir>/<EVENT> \
        [--tc-tolerance 0.01] [--stat-tolerance 1e-3] [--pe-tolerance 0.05]

The agent run may be either the Buoy vertical slice (task ``analyze_event``)
or the decomposed plan (tasks ``run_aframe`` and ``run_amplfi``). The script
prints a JSON comparison and exits non-zero when any quantity differs by
more than its tolerance. Posterior medians are compared as relative
differences; with a fixed seed and identical revisions they should agree to
well under a percent, and without a shared seed the tolerance should be
loosened to the Monte Carlo scatter of the sample size.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import h5py
import numpy as np

PE_PARAMETERS = ("chirp_mass", "mass_ratio", "distance", "mass_1", "mass_2")


def aframe_summary(path: Path) -> dict[str, float]:
    with h5py.File(path, "r") as handle:
        signif = np.asarray(handle["signif_integrated"][:]).reshape(-1)
        timing = np.asarray(handle["timing_integrated"][:]).reshape(-1)
        return {
            "detection_statistic": float(np.max(signif)),
            "predicted_tc": float(handle.attrs["predicted_tc"]),
            "n_steps": int(timing.size),
        }


def posterior_medians(path: Path) -> dict[str, float]:
    table = np.genfromtxt(path, names=True)
    return {
        name: float(np.median(table[name]))
        for name in PE_PARAMETERS
        if name in table.dtype.names
    }


def agent_files(run_dir: Path) -> tuple[Path | None, Path | None, str | None]:
    """Return the agent's Aframe file, posterior file, and AMPLFI network."""
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    tasks = manifest["tasks"]
    if "analyze_event" in tasks:
        outputs = tasks["analyze_event"]["outputs"]
        return (
            run_dir / outputs["aframe_output"],
            run_dir / outputs["posterior_samples"],
            outputs.get("amplfi_network"),
        )
    aframe = tasks.get("run_aframe", {}).get("outputs", {}).get("output_artifact")
    amplfi_outputs = tasks.get("run_amplfi", {}).get("outputs", {})
    amplfi = amplfi_outputs.get("posterior_artifact")
    network = "".join(ifo[0] for ifo in amplfi_outputs.get("ifos", [])) or None
    return (
        run_dir / aframe if aframe else None,
        run_dir / amplfi if amplfi else None,
        network,
    )


def buoy_network(event_dir: Path) -> str | None:
    candidates = sorted((event_dir / "data").glob("amplfi_*.fits"))
    return candidates[0].stem.split("_", 1)[1] if candidates else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("agent_run_dir", type=Path)
    parser.add_argument("buoy_event_dir", type=Path)
    parser.add_argument("--tc-tolerance", type=float, default=0.01)
    parser.add_argument("--stat-tolerance", type=float, default=1e-3)
    parser.add_argument("--pe-tolerance", type=float, default=0.05)
    args = parser.parse_args(argv)

    agent_aframe, agent_posterior, agent_net = agent_files(args.agent_run_dir)
    buoy_aframe = args.buoy_event_dir / "data" / "aframe_outputs.hdf5"
    buoy_posterior = args.buoy_event_dir / "data" / "posterior_samples.dat"
    buoy_net = buoy_network(args.buoy_event_dir)

    report: dict[str, object] = {
        "agent_run": str(args.agent_run_dir),
        "agent_amplfi_network": agent_net,
        "buoy_amplfi_network": buoy_net,
        "checks": [],
    }
    failures = 0

    def check(name: str, agent: float, buoy: float, tolerance: float, relative: bool):
        nonlocal failures
        delta = abs(agent - buoy)
        if relative and buoy != 0:
            delta /= abs(buoy)
        passed = delta <= tolerance
        failures += 0 if passed else 1
        report["checks"].append(
            {
                "quantity": name,
                "agent": agent,
                "buoy": buoy,
                "difference": delta,
                "relative": relative,
                "tolerance": tolerance,
                "passed": passed,
            }
        )

    if agent_aframe and agent_aframe.exists() and buoy_aframe.exists():
        a, b = aframe_summary(agent_aframe), aframe_summary(buoy_aframe)
        check(
            "detection_statistic",
            a["detection_statistic"],
            b["detection_statistic"],
            args.stat_tolerance,
            relative=True,
        )
        check(
            "predicted_tc",
            a["predicted_tc"],
            b["predicted_tc"],
            args.tc_tolerance,
            relative=False,
        )
    else:
        report["aframe"] = "not compared (missing file)"

    if agent_posterior and agent_posterior.exists() and buoy_posterior.exists():
        if agent_net and buoy_net and agent_net != buoy_net:
            # Different AMPLFI networks (HL versus HLV) are different models;
            # their posteriors are not expected to agree, so this is a failed
            # setup rather than a numerical disagreement.
            failures += 1
            report["amplfi"] = (
                f"not comparable: agent used the {agent_net} network, Buoy used "
                f"{buoy_net}; rerun with the same detector set"
            )
        else:
            a = posterior_medians(agent_posterior)
            b = posterior_medians(buoy_posterior)
            for name in sorted(a.keys() & b.keys()):
                check(
                    f"median_{name}", a[name], b[name], args.pe_tolerance, relative=True
                )
    else:
        report["amplfi"] = "not compared (missing file)"

    report["passed"] = failures == 0
    print(json.dumps(report, indent=2))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
