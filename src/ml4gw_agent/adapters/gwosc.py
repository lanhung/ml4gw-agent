"""Real ``data.fetch`` adapter over public GWOSC strain.

The adapter retrieves open data with ``gwpy.timeseries.TimeSeries
.fetch_open_data`` and writes a Buoy-compatible strain HDF5 artifact inside
the run directory. The window is positioned exactly as Buoy positions it
(three quarters of the window before the event, integer-aligned start) so
that a decomposed agent run and a direct Buoy run see identical samples.

GraceDB identifiers are refused here: they require LIGO credentials and
non-public frames, which is ``buoy.analyze`` or a future mldatafind
adapter's responsibility.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..errors import AdapterError, AdapterUnavailableError
from ..planning import EVENT_PATTERN
from .base import (
    AdapterOutcome,
    ExecutionContext,
    SkillAdapter,
    artifact_directory,
    relative_to_run,
)
from .ldg import STRAIN_CHANNELS, ldg_preflight, load_ldg_backend
from .strain_io import StrainData, package_versions, write_strain

REQUIRED_MODULES = ("gwosc", "gwpy", "h5py", "numpy")


@dataclass(frozen=True)
class GWOSCBackend:
    """The handful of upstream callables the adapter depends on."""

    event_gps: Any
    event_detectors: Any
    fetch_open_data: Any
    get_segments: Any


def missing_modules(names: tuple[str, ...]) -> list[str]:
    return [name for name in names if importlib.util.find_spec(name) is None]


def load_gwosc_backend() -> GWOSCBackend:
    missing = missing_modules(REQUIRED_MODULES)
    if missing:
        raise AdapterUnavailableError(
            f"the GWOSC data adapter requires {missing}; install with "
            "'uv sync --extra data'"
        )
    import gwosc.datasets
    import gwosc.timeline
    from gwpy.timeseries import TimeSeries

    return GWOSCBackend(
        event_gps=gwosc.datasets.event_gps,
        event_detectors=gwosc.datasets.event_detectors,
        fetch_open_data=TimeSeries.fetch_open_data,
        get_segments=gwosc.timeline.get_segments,
    )


def window_bounds(
    event_time: float, window_seconds: float, event_offset_fraction: float
) -> tuple[float, float]:
    """Integer-aligned window with the event ``event_offset_fraction`` in."""
    offset = event_time % 1
    start = event_time - event_offset_fraction * window_seconds - offset
    return start, start + window_seconds


class GWOSCFetchAdapter(SkillAdapter):
    name = "gwosc-fetch-v0.2"

    def probe(self) -> str:
        missing = missing_modules(REQUIRED_MODULES)
        return "available" if not missing else f"missing: {', '.join(missing)}"

    def preflight(self, context: ExecutionContext) -> list[str]:
        event = str(context.parameters.get("event", ""))
        if not EVENT_PATTERN.fullmatch(event):
            raise AdapterError(f"unsupported event identifier: {event}")
        source = str(context.parameters.get("source", "gwosc"))
        if source == "ldg":
            ldg_preflight([str(ifo) for ifo in context.parameters.get("ifos", [])])
            if event[:1] in {"G", "S"} and not event.startswith("GW"):
                raise AdapterUnavailableError(
                    "GraceDB identifiers must be resolved to a GPS time first; "
                    "pass gps_time or use buoy.analyze"
                )
            return []
        if event[:1] in {"G", "S"} and not event.startswith("GW"):
            raise AdapterUnavailableError(
                "the public GWOSC adapter cannot fetch GraceDB events; use "
                "buoy.analyze with LIGO credentials or data.fetch with "
                "source: ldg"
            )
        missing = missing_modules(REQUIRED_MODULES)
        if missing:
            raise AdapterUnavailableError(
                f"the GWOSC data adapter requires {missing}; install with "
                "'uv sync --extra data'"
            )
        return []

    def describe_invocation(
        self, context: ExecutionContext
    ) -> tuple[list[str] | None, dict[str, Any]]:
        if str(context.parameters.get("source", "gwosc")) == "ldg":
            return None, {
                "adapter": self.name,
                "python_call": "gwpy.timeseries.TimeSeries.get",
                "data_source": "LIGO Data Grid frames via gwdatafind",
                "channels": STRAIN_CHANNELS,
            }
        return None, {
            "adapter": self.name,
            "python_call": "gwpy.timeseries.TimeSeries.fetch_open_data",
            "data_source": "GWOSC public strain",
        }

    @staticmethod
    def _resolve_event_time(
        backend: GWOSCBackend, event: str, gps_time: Any
    ) -> tuple[float, str]:
        if gps_time is not None:
            return float(gps_time), "parameter"
        if event.startswith("GW"):
            try:
                return float(backend.event_gps(event)), "gwosc.datasets.event_gps"
            except Exception as exc:  # upstream raises ValueError or HTTP errors
                raise AdapterError(
                    f"GWOSC could not resolve {event}: {type(exc).__name__}: {exc}"
                ) from exc
        return float(event), "gps"

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        params = context.parameters
        source = str(params.get("source", "gwosc"))
        backend = load_gwosc_backend()
        if source == "ldg":
            ldg = load_ldg_backend()

            def fetch(ifo: str, start: float, end: float):
                return ldg.get_timeseries(STRAIN_CHANNELS[ifo], start, end)

            backend = GWOSCBackend(
                event_gps=backend.event_gps,
                event_detectors=backend.event_detectors,
                fetch_open_data=fetch,
                get_segments=backend.get_segments,
            )
        event = str(params["event"])
        ifos = [str(ifo) for ifo in params["ifos"]]
        window = float(params.get("window_seconds", 128))
        fraction = float(params.get("event_offset_fraction", 0.75))
        sample_rate = int(params.get("sample_rate", 2048))

        event_time, time_source = self._resolve_event_time(
            backend, event, params.get("gps_time")
        )
        start, end = window_bounds(event_time, window, fraction)

        series: dict[str, np.ndarray] = {}
        warnings: list[str] = []
        native_rates: dict[str, float] = {}
        for ifo in ifos:
            try:
                timeseries = backend.fetch_open_data(ifo, start, end)
            except Exception as exc:
                raise AdapterError(
                    f"{source} fetch failed for {ifo} over [{start}, {end}]: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            span_start, span_end = timeseries.span
            if span_start > start + 1e-6 or span_end < end - 1e-6:
                raise AdapterError(
                    f"{ifo} open data covers [{span_start}, {span_end}] but "
                    f"[{start}, {end}] was requested"
                )
            native = float(getattr(timeseries.sample_rate, "value", 0) or 0)
            native_rates[ifo] = native
            if native and abs(native - sample_rate) > 1e-9:
                timeseries = timeseries.resample(sample_rate)
                warnings.append(
                    f"{ifo} strain resampled from {native:g} Hz to {sample_rate} Hz"
                )
            values = np.asarray(timeseries.value, dtype="f8")
            expected = int(round(window * sample_rate))
            if values.shape[0] < expected:
                raise AdapterError(
                    f"{ifo} returned {values.shape[0]} samples; expected {expected}"
                )
            series[ifo] = values[:expected]

        data = StrainData(
            ifos=ifos,
            series=series,
            t0=start,
            sample_rate=float(sample_rate),
            event_time=event_time,
            source=source,
            event=event,
            extra_attrs={"event_time_source": time_source},
        )
        artifact = write_strain(
            artifact_directory(context) / f"strain_{event}.hdf5", data
        )
        outputs = {
            "strain_artifact": relative_to_run(artifact, context.run_dir),
            "ifos": ifos,
            "gps_start": start,
            "gps_end": end,
            "source": source,
            "sample_rate": sample_rate,
            "event_time": event_time,
            "simulated": False,
        }
        metadata = {
            "adapter": self.name,
            "event_time_source": time_source,
            "native_sample_rates_hz": native_rates,
            "packages": package_versions(
                "gwpy", "gwosc", "gwdatafind", "igwn-auth-utils", "h5py", "numpy"
            ),
            "channels": (
                {ifo: STRAIN_CHANNELS[ifo] for ifo in ifos} if source == "ldg" else None
            ),
        }
        return AdapterOutcome(
            outputs=outputs, artifacts=[artifact], metadata=metadata, warnings=warnings
        )
