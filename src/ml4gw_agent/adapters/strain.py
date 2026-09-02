"""Real ``data.inspect`` adapter: deterministic strain quality checks.

Checks are intentionally conservative and every failure is recorded as an
issue. ``quality_passed`` is true only when no required check failed, so a
downstream ``when`` condition on it is a real scientific gate rather than a
formality.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from ..errors import AdapterError
from .base import (
    AdapterOutcome,
    ExecutionContext,
    SkillAdapter,
    artifact_directory,
    relative_to_run,
)
from .gwosc import load_gwosc_backend, missing_modules
from .strain_io import StrainData, package_versions, read_strain, resolve_artifact

SEGMENT_MODULES = ("gwosc",)


def science_segment_issues(
    backend: Any, data: StrainData, tolerance: float = 1e-3
) -> list[str]:
    """Verify that the GWOSC ``<IFO>_DATA`` flag covers the whole interval."""
    issues: list[str] = []
    start, end = data.t0, data.gps_end
    for ifo in data.ifos:
        try:
            segments = backend.get_segments(f"{ifo}_DATA", int(start), int(end) + 1)
        except Exception as exc:
            issues.append(
                f"{ifo}: science-segment query failed ({type(exc).__name__}: {exc})"
            )
            continue
        covered = any(
            seg_start <= start + tolerance and seg_end >= end - tolerance
            for seg_start, seg_end in segments
        )
        if not covered:
            issues.append(
                f"{ifo}: {ifo}_DATA flag does not cover [{start}, {end}]; "
                f"segments {list(segments)}"
            )
    return issues


class StrainInspectAdapter(SkillAdapter):
    name = "strain-inspect-v0.2"

    def probe(self) -> str:
        missing = missing_modules(SEGMENT_MODULES)
        return (
            "available"
            if not missing
            else f"available without science-segment checks (missing: "
            f"{', '.join(missing)})"
        )

    def describe_invocation(
        self, context: ExecutionContext
    ) -> tuple[list[str] | None, dict[str, Any]]:
        return None, {
            "adapter": self.name,
            "checks": [
                "readable_hdf5",
                "expected_detectors",
                "equal_lengths",
                "finite_values",
                "non_constant",
                "minimum_duration",
                "science_segments",
            ],
        }

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        params = context.parameters
        path = resolve_artifact(str(params["strain_artifact"]), context.run_dir)
        data = read_strain(path)

        issues: list[str] = []
        per_ifo: dict[str, dict[str, float | int | bool]] = {}
        expected = [str(ifo) for ifo in params.get("expected_ifos") or []]
        missing = [ifo for ifo in expected if ifo not in data.series]
        if missing:
            issues.append(f"expected detectors missing from strain: {missing}")

        min_duration = float(params.get("min_duration_seconds", 0) or 0)
        if data.duration + 1e-9 < min_duration:
            issues.append(
                f"duration {data.duration:g} s is shorter than the required "
                f"{min_duration:g} s"
            )

        lengths = {ifo: int(array.shape[0]) for ifo, array in data.series.items()}
        if len(set(lengths.values())) != 1:
            issues.append(f"detector series have unequal lengths: {lengths}")

        for ifo, array in data.series.items():
            finite = np.isfinite(array)
            finite_fraction = float(finite.mean()) if array.size else 0.0
            valid = array[finite]
            std = float(np.std(valid)) if valid.size else 0.0
            per_ifo[ifo] = {
                "samples": int(array.size),
                "finite_fraction": finite_fraction,
                "std": std,
                "max_abs": float(np.max(np.abs(valid))) if valid.size else 0.0,
            }
            if array.size == 0:
                issues.append(f"{ifo}: empty series")
            if finite_fraction < 1.0:
                issues.append(
                    f"{ifo}: {1 - finite_fraction:.3%} of samples are not finite"
                )
            if std == 0.0:
                issues.append(f"{ifo}: strain is constant (zero variance)")

        warnings: list[str] = []
        if params.get("require_science_mode", True):
            try:
                backend = load_gwosc_backend()
            except AdapterError as exc:
                issues.append(f"science-segment check unavailable: {exc}")
            else:
                issues.extend(science_segment_issues(backend, data))
        else:
            warnings.append(
                f"{context.task.id}: science-segment check was disabled by request"
            )

        quality_passed = not issues
        diagnostics = {
            "strain_artifact": str(params["strain_artifact"]),
            "ifos": data.ifos,
            "gps_start": data.t0,
            "gps_end": data.gps_end,
            "duration_seconds": data.duration,
            "sample_rate": data.sample_rate,
            "event_time": data.event_time,
            "source": data.source,
            "per_ifo": per_ifo,
            "issues": issues,
            "quality_passed": quality_passed,
        }
        artifact = artifact_directory(context) / "quality_diagnostics.json"
        artifact.write_text(json.dumps(diagnostics, indent=2) + "\n", encoding="utf-8")

        outputs = {
            "quality_passed": quality_passed,
            "available_ifos": data.ifos,
            "diagnostics_artifact": relative_to_run(artifact, context.run_dir),
            "issues": issues,
            "duration_seconds": data.duration,
            "sample_rate": data.sample_rate,
            "simulated": False,
        }
        return AdapterOutcome(
            outputs=outputs,
            artifacts=[artifact],
            metadata={
                "adapter": self.name,
                "packages": package_versions("gwosc", "h5py", "numpy"),
            },
            warnings=warnings,
        )
