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


def load_aframe_table() -> dict[str, Any]:
    path = resources.files(__name__).joinpath("aframe_thresholds.json")
    return json.loads(path.read_text(encoding="utf-8"))


def aframe_threshold(
    revision: str | None, far_per_year: float, table: dict[str, Any] | None = None
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
        source=str(entry.get("source", "aframe_background.py")),
    )
