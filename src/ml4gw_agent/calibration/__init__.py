"""Calibration tables shipped with the agent.

``aframe_thresholds.json`` maps an immutable Aframe revision to thresholds
on Buoy's offline integrated statistic derived from a time-shifted
background study (``scripts/aframe_background.py``). The planner uses it to
turn a requested false-alarm rate into a threshold; if no entry exists for
the pinned revision the plan falls back to the raw ``0.0`` cut and says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

SECONDS_PER_YEAR = 365.25 * 86400.0


@dataclass(frozen=True)
class AframeThreshold:
    revision: str
    far_per_year: float
    threshold: float
    livetime_seconds: float
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "far_per_year": self.far_per_year,
            "threshold": self.threshold,
            "livetime_seconds": self.livetime_seconds,
            "source": self.source,
        }


TABLE_FILES = {
    "aframe": "aframe_thresholds.json",
    "gwak": "gwak_thresholds.json",
}


def load_table(kind: str) -> dict[str, Any]:
    path = resources.files(__name__).joinpath(TABLE_FILES[kind])
    return json.loads(path.read_text(encoding="utf-8"))


def load_aframe_table() -> dict[str, Any]:
    return load_table("aframe")


def load_gwak_table() -> dict[str, Any]:
    return load_table("gwak")


def gwak_threshold(
    revision: str | None, far_per_year: float, table: dict[str, Any] | None = None
) -> AframeThreshold | None:
    """GWAK counterpart of :func:`aframe_threshold` (same table layout)."""
    table = load_gwak_table() if table is None else table
    return aframe_threshold(
        revision, far_per_year, table=table, default_source="gwak_background.py"
    )


def aframe_threshold(
    revision: str | None,
    far_per_year: float,
    table: dict[str, Any] | None = None,
    *,
    default_source: str = "aframe_background.py",
) -> AframeThreshold | None:
    """Threshold for ``revision`` at the tightest FAR not above ``far_per_year``.

    Returns ``None`` when the revision has no calibration or when the study's
    livetime cannot resolve the requested rate (fewer than one expected
    background event above the loudest peak means the rate is unconstrained).
    """
    if not revision:
        return None
    table = load_aframe_table() if table is None else table
    entry = table.get("revisions", {}).get(revision)
    if not entry:
        return None
    livetime = float(entry["livetime_seconds"])
    if livetime <= 0:
        return None
    candidates = [
        (float(far), float(value))
        for far, value in entry["thresholds_by_far_per_year"].items()
        if float(far) <= far_per_year + 1e-12
    ]
    if not candidates:
        return None
    far, value = max(candidates)  # loosest FAR that still meets the request
    # A rate below one event per livetime is not measured, only bounded.
    if far * livetime / SECONDS_PER_YEAR < 1.0 and not entry.get("allow_extrapolation"):
        return None
    return AframeThreshold(
        revision=revision,
        far_per_year=far,
        threshold=value,
        livetime_seconds=livetime,
        source=str(entry.get("source", default_source)),
    )


def far_at_score(
    kind: str, revision: str | None, score: float, table: dict[str, Any] | None = None
) -> float | None:
    """Measured false-alarm rate (per year) of background peaks at or above
    ``score`` for ``revision``, from the study's ``far_curve``.

    Returns ``None`` when no curve exists or the score lies below the first
    tabulated threshold (the rate there exceeds what the table records). A
    score above the loudest background peak returns the rate of one event
    per livetime, an upper bound rather than a measurement.
    """
    if not revision:
        return None
    table = load_table(kind) if table is None else table
    entry = table.get("revisions", {}).get(revision) or {}
    curve = entry.get("far_curve") or []
    if not curve:
        return None
    below = [far for threshold, far in curve if threshold <= score]
    if not below:
        return None
    return float(below[-1])
