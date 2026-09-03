"""Partition long scans into segments and merge their outputs without gaps.

A segment list covers ``[start, end)`` exactly once: consecutive segments
abut, and each segment carries ``overlap_seconds`` of extra data on both
sides (clipped to the scan) so filters and PSD estimation have context. The
*analysis* interval of a segment is the abutting core; the *data* interval
is the padded one. Candidates are attributed to the segment whose core
contains them, which is what makes the merge free of duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Segment:
    index: int
    core_start: float
    core_end: float
    data_start: float
    data_end: float

    @property
    def core_duration(self) -> float:
        return self.core_end - self.core_start

    def contains(self, time: float) -> bool:
        return self.core_start <= time < self.core_end

    def as_dict(self) -> dict[str, float | int]:
        return {
            "index": self.index,
            "core_start": self.core_start,
            "core_end": self.core_end,
            "data_start": self.data_start,
            "data_end": self.data_end,
        }


def partition_scan(
    start: float,
    end: float,
    segment_seconds: float,
    overlap_seconds: float = 0.0,
) -> list[Segment]:
    """Split ``[start, end)`` into abutting cores with padded data windows."""
    if end <= start:
        raise ValueError("scan end must be after scan start")
    if segment_seconds <= 0:
        raise ValueError("segment length must be positive")
    if overlap_seconds < 0:
        raise ValueError("overlap must be non-negative")
    segments: list[Segment] = []
    cursor = float(start)
    index = 0
    while cursor < end:
        core_end = min(cursor + segment_seconds, float(end))
        segments.append(
            Segment(
                index=index,
                core_start=cursor,
                core_end=core_end,
                data_start=max(float(start), cursor - overlap_seconds),
                data_end=min(float(end), core_end + overlap_seconds),
            )
        )
        cursor = core_end
        index += 1
    return segments


def merge_segment_outputs(
    segments: list[Segment],
    outputs: dict[int, dict[str, Any]],
    *,
    time_key: str = "time",
    candidates_key: str = "candidates",
    proximity_seconds: float = 1.0,
) -> dict[str, Any]:
    """Aggregate per-segment candidate lists into one gap-free result.

    ``outputs`` maps segment index to a dict with ``candidates_key`` holding
    dicts that carry ``time_key``. A candidate is kept only if it falls in the
    core of the segment that reported it (so a signal seen twice in the
    overlap of neighbours is counted once); remaining near-duplicates closer
    than ``proximity_seconds`` keep the louder ``statistic`` if present.
    Missing segments are reported, never silently dropped.
    """
    by_index = {segment.index: segment for segment in segments}
    missing = sorted(set(by_index) - set(outputs))
    kept: list[dict[str, Any]] = []
    for index, payload in sorted(outputs.items()):
        segment = by_index.get(index)
        if segment is None:
            raise ValueError(f"output for unknown segment {index}")
        for candidate in payload.get(candidates_key, []):
            time = float(candidate[time_key])
            if segment.contains(time):
                kept.append({**candidate, "segment": index})
    kept.sort(key=lambda item: float(item[time_key]))
    merged: list[dict[str, Any]] = []
    for candidate in kept:
        if (
            merged
            and float(candidate[time_key]) - float(merged[-1][time_key])
            < proximity_seconds
        ):
            if float(candidate.get("statistic", 0.0)) > float(
                merged[-1].get("statistic", 0.0)
            ):
                merged[-1] = candidate
            continue
        merged.append(candidate)
    covered = sum(
        by_index[index].core_duration for index in outputs if index in by_index
    )
    total = sum(segment.core_duration for segment in segments)
    return {
        candidates_key: merged,
        "n_segments": len(segments),
        "n_reported": len(outputs),
        "missing_segments": missing,
        "coverage_fraction": covered / total if total else 0.0,
        "complete": not missing,
    }
