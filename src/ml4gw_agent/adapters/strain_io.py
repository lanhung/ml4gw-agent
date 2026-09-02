"""Buoy-compatible strain HDF5 helpers shared by the real data adapters.

Layout (identical to the cache file written by ``buoy.utils.data.get_data``
so that a direct Buoy run and an agent run can be compared file for file):

- one float64 dataset per interferometer, keyed by its name (``H1``, ...)
- ``attrs["t0"]``: GPS start time of every dataset
- ``attrs["tc"]``: event time the window was built around
- ``attrs["sample_rate"]``: samples per second

The agent adds ``ifos``, ``gps_end``, ``source``, and ``event`` attributes.
"""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass, field
from pathlib import Path

import h5py
import numpy as np

from ..errors import AdapterError

IFO_ORDER = ("H1", "L1", "V1", "K1")


@dataclass
class StrainData:
    ifos: list[str]
    series: dict[str, np.ndarray]
    t0: float
    sample_rate: float
    event_time: float | None = None
    source: str = "unknown"
    event: str | None = None
    extra_attrs: dict[str, object] = field(default_factory=dict)

    @property
    def n_samples(self) -> int:
        return int(next(iter(self.series.values())).shape[0])

    @property
    def duration(self) -> float:
        return self.n_samples / self.sample_rate

    @property
    def gps_end(self) -> float:
        return self.t0 + self.duration

    def stacked(self, ifos: list[str]) -> np.ndarray:
        """Return an array shaped ``(1, len(ifos), n_samples)`` in the given order."""
        missing = [ifo for ifo in ifos if ifo not in self.series]
        if missing:
            raise AdapterError(
                f"strain artifact lacks detectors {missing}; has {self.ifos}"
            )
        return np.stack([self.series[ifo] for ifo in ifos])[None]


def write_strain(path: Path, data: StrainData) -> Path:
    lengths = {ifo: int(array.shape[0]) for ifo, array in data.series.items()}
    if len(set(lengths.values())) != 1:
        raise AdapterError(f"detector series have unequal lengths: {lengths}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as handle:
        handle.attrs["t0"] = float(data.t0)
        handle.attrs["sample_rate"] = float(data.sample_rate)
        handle.attrs["gps_end"] = float(data.gps_end)
        handle.attrs["ifos"] = list(data.ifos)
        handle.attrs["source"] = data.source
        if data.event_time is not None:
            handle.attrs["tc"] = float(data.event_time)
        if data.event is not None:
            handle.attrs["event"] = str(data.event)
        for key, value in data.extra_attrs.items():
            handle.attrs[key] = value
        for ifo in data.ifos:
            handle.create_dataset(ifo, data=np.asarray(data.series[ifo], dtype="f8"))
    return path


def read_strain(path: Path) -> StrainData:
    if not path.is_file():
        raise AdapterError(f"strain artifact does not exist: {path}")
    try:
        with h5py.File(path, "r") as handle:
            ifos = [key for key in IFO_ORDER if key in handle]
            ifos += sorted(key for key in handle.keys() if key not in ifos)
            if not ifos:
                raise AdapterError(f"strain artifact has no detector datasets: {path}")
            series = {ifo: np.asarray(handle[ifo][:], dtype="f8") for ifo in ifos}
            attrs = handle.attrs
            if "t0" not in attrs:
                raise AdapterError(f"strain artifact lacks a t0 attribute: {path}")
            t0 = float(attrs["t0"])
            if "sample_rate" in attrs:
                sample_rate = float(attrs["sample_rate"])
            else:
                raise AdapterError(
                    f"strain artifact lacks a sample_rate attribute: {path}"
                )
            event_time = float(attrs["tc"]) if "tc" in attrs else None
            source = str(attrs.get("source", "unknown"))
            event = str(attrs["event"]) if "event" in attrs else None
    except OSError as exc:
        raise AdapterError(f"strain artifact is not readable HDF5: {path}") from exc
    return StrainData(
        ifos=ifos,
        series=series,
        t0=t0,
        sample_rate=sample_rate,
        event_time=event_time,
        source=source,
        event=event,
    )


def resolve_artifact(reference: str, run_dir: Path) -> Path:
    """Resolve a run-relative artifact path and refuse escapes."""
    candidate = Path(reference)
    candidate = candidate if candidate.is_absolute() else run_dir / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise AdapterError(
            f"input artifact escaped the run directory: {reference}"
        ) from exc
    return resolved


def package_versions(*names: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions
