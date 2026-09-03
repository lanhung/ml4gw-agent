"""Non-public strain through IGWN data discovery and the Open Science Data
Federation (the ``mldatafind`` route).

``data.fetch`` with ``source: ldg`` does what an LDG job does, from any
host with network access and an IGWN SciToken:

1. ``gwdatafind`` (``datafind.igwn.org``) resolves the frame type covering
   the window to ``https://osdf-director.osg-htc.org/...`` URLs;
2. the frame files are downloaded with the bearer token into a cache
   directory (the director returns 403 without the token, which is the
   authorization check);
3. ``gwpy`` reads the calibrated strain channel from the local files.

Frame types and channel names differ by observing run; the map below is the
reviewed default and every choice is recorded in the run manifest. Without
a token the adapter fails closed in ``preflight`` naming the missing piece.
Verified on 2026-09-03 with a fan.zhang@ligo.org token: O1 ``HOFT_C02``,
O3 ``HOFT_C01`` (plus the DeepClean-cleaned ``HOFT_CLEAN_SUB60HZ_C01``) and
O4 ``HOFT_C00`` frames were readable with the token and refused without it.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import AdapterError, AdapterUnavailableError

REQUIRED_MODULES = ("gwpy", "gwdatafind", "igwn_auth_utils")
DEFAULT_DATAFIND_SERVER = "datafind.igwn.org"
DEFAULT_CACHE = Path(
    os.environ.get("ML4GW_AGENT_FRAME_CACHE", "~/.cache/ml4gw-agent/frames")
)

# Channel map Buoy uses for non-public strain (buoy/utils/data.py); used for
# O4 and later, where the low-latency GDS channel is the calibrated product.
STRAIN_CHANNELS = {
    "H1": "H1:GDS-CALIB_STRAIN_CLEAN",
    "L1": "L1:GDS-CALIB_STRAIN_CLEAN",
    "V1": "V1:Hrec_hoft_16384Hz",
}

# (gps_start, gps_end, frametype template, channel template) per epoch; the
# first row whose interval contains the request start is used.
EPOCHS: tuple[tuple[float, float, str, str], ...] = (
    (1123856384.0, 1137254400.0, "{ifo}_HOFT_C02", "{ifo}:DCS-CALIB_STRAIN_C02"),  # O1
    (1164556817.0, 1187733618.0, "{ifo}_HOFT_C02", "{ifo}:DCS-CALIB_STRAIN_C02"),  # O2
    (1238112018.0, 1269363618.0, "{ifo}_HOFT_C01", "{ifo}:DCS-CALIB_STRAIN_C01"),  # O3
    (
        1368975618.0,
        9999999999.0,
        "{ifo}_HOFT_C00",
        "{ifo}:GDS-CALIB_STRAIN_CLEAN",
    ),  # O4+
)


def missing_modules() -> list[str]:
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def credential_status(environ: dict[str, str] | None = None) -> tuple[bool, str]:
    """Return (available, description) for IGWN data-access credentials."""
    env = os.environ if environ is None else environ
    token = env.get("BEARER_TOKEN_FILE") or env.get("SCITOKEN_FILE")
    if token and Path(token).is_file():
        return True, f"SciToken file {token}"
    if env.get("BEARER_TOKEN") or env.get("SCITOKEN"):
        return True, "SciToken from environment"
    proxy = env.get("X509_USER_PROXY")
    if proxy and Path(proxy).is_file():
        return True, f"X.509 proxy {proxy}"
    cert, key = env.get("X509_USER_CERT"), env.get("X509_USER_KEY")
    if cert and key and Path(cert).is_file() and Path(key).is_file():
        return True, "X.509 certificate and key"
    return False, (
        "no IGWN credential found: set BEARER_TOKEN_FILE (SciToken from "
        "'htgettoken -a vault.ligo.org -i igwn') or X509_USER_PROXY"
    )


def bearer_token(environ: dict[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    for key in ("BEARER_TOKEN_FILE", "SCITOKEN_FILE"):
        path = env.get(key)
        if path and Path(path).is_file():
            return Path(path).read_text(encoding="utf-8").strip()
    return env.get("BEARER_TOKEN") or env.get("SCITOKEN") or None


def epoch_for(ifo: str, start: float) -> tuple[str, str]:
    """Frame type and channel for ``ifo`` at GPS ``start`` from the map."""
    for gps_start, gps_end, frametype, channel in EPOCHS:
        if gps_start <= start < gps_end:
            return frametype.format(ifo=ifo), channel.format(ifo=ifo)
    raise AdapterError(
        f"no reviewed frame type for {ifo} at GPS {start}; add the observing "
        "run to ml4gw_agent.adapters.ldg.EPOCHS"
    )


@dataclass(frozen=True)
class LDGBackend:
    """The upstream callables the adapter depends on (seam for tests)."""

    find_urls: Any  # find_urls(site, frametype, start, end, urltype="https")
    download: Any  # download(url, token, target) -> Path
    read_timeseries: Any  # read(files, channel, start, end) -> TimeSeries


def _download(url: str, token: str, target: Path) -> Path:
    import requests

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        return target
    part = target.with_suffix(target.suffix + ".part")
    with requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        stream=True,
        timeout=600,
        allow_redirects=True,
    ) as response:
        if response.status_code in (401, 403):
            raise AdapterUnavailableError(
                f"OSDF refused {url} with HTTP {response.status_code}: the token "
                "lacks read:/frames or has expired"
            )
        response.raise_for_status()
        expected = int(response.headers.get("Content-Length") or 0)
        with part.open("wb") as handle:
            for chunk in response.iter_content(1 << 20):
                handle.write(chunk)
    if expected and part.stat().st_size != expected:
        raise AdapterError(
            f"short download for {url}: {part.stat().st_size} of {expected} bytes"
        )
    part.replace(target)
    return target


def normalize_units(series: Any, channel: str) -> Any:
    """Rebuild a series read from GWF with explicit time units.

    Frame readers can return a ``TimeSeries`` whose ``dx`` carries no unit;
    gwpy then refuses ``resample`` with a dimensionless/Hz conversion error.
    Reconstructing the series with an explicit ``t0`` in seconds and a
    sample rate in hertz keeps the samples untouched and makes the rest of
    the adapter (span check, resampling) unit-safe.
    """
    from gwpy.timeseries import TimeSeries

    t0 = float(getattr(series.t0, "value", series.t0))
    dx = float(getattr(series.dx, "value", series.dx))
    return TimeSeries(
        series.value,
        t0=t0,
        sample_rate=1.0 / dx,
        channel=channel,
        name=channel,
    )


def read_gwf_channel(path: str, channel: str) -> Any:
    """Read one channel of one GWF file into a unit-safe ``TimeSeries``.

    ``framel.frgetvect1d`` is used first because it returns plain arrays
    with the frame start time and sample spacing, which are then given
    explicit units; gwpy's own GWF readers are the fallback. (gwpy 4.0.2
    with the frameCPP backend drops the time unit during its internal merge
    and fails on ``sample_rate``, observed 2026-09-03.)
    """
    from gwpy.timeseries import TimeSeries

    try:
        import framel
    except ImportError:
        framel = None
    if framel is not None:
        data, t0, x0, dx, *_ = framel.frgetvect1d(str(path), channel)
        return TimeSeries(
            data,
            t0=float(t0) + float(x0),
            sample_rate=1.0 / float(dx),
            channel=channel,
            name=channel,
        )
    return normalize_units(TimeSeries.read(str(path), channel), channel)


def load_ldg_backend() -> LDGBackend:
    missing = missing_modules()
    if missing:
        raise AdapterUnavailableError(
            f"the LDG data path requires {missing}; install with 'uv sync --extra ldg'"
        )
    os.environ.setdefault("GWDATAFIND_SERVER", DEFAULT_DATAFIND_SERVER)
    from gwdatafind import find_urls

    def read(files: list[str], channel: str, start: float, end: float):
        pieces = [read_gwf_channel(path, channel) for path in files]
        series = pieces[0]
        for piece in pieces[1:]:
            series = series.append(piece, inplace=False)
        return series.crop(start, end)

    return LDGBackend(find_urls=find_urls, download=_download, read_timeseries=read)


def fetch_ldg_strain(
    backend: LDGBackend,
    ifo: str,
    start: float,
    end: float,
    *,
    cache_dir: Path | None = None,
    frametype: str | None = None,
    channel: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Return (TimeSeries, provenance) for ``ifo`` over ``[start, end)``."""
    default_type, default_channel = epoch_for(ifo, start)
    frametype = frametype or default_type
    channel = channel or default_channel
    token = bearer_token()
    if token is None:
        raise AdapterUnavailableError(credential_status()[1])
    urls = list(
        backend.find_urls(ifo[0], frametype, int(start), int(end) + 1, urltype="file")
    )
    local = [u for u in urls if u.startswith("file://") and Path(u[7:]).is_file()]
    if local:
        # On an LDG node the frames are on a shared filesystem: no download.
        files = sorted(u[7:] for u in local)
        series = backend.read_timeseries(files, channel, start, end)
        return series, {
            "frametype": frametype,
            "channel": channel,
            "urls": local,
            "files": files,
            "datafind_server": os.environ.get(
                "GWDATAFIND_SERVER", DEFAULT_DATAFIND_SERVER
            ),
        }
    urls = list(
        backend.find_urls(ifo[0], frametype, int(start), int(end) + 1, urltype="https")
    )
    if not urls:
        raise AdapterError(
            f"gwdatafind has no {frametype} frames covering [{start}, {end}); "
            "check the frame type for this observing run"
        )
    cache = (cache_dir or DEFAULT_CACHE).expanduser()
    files = [
        str(backend.download(url, token, cache / frametype / Path(url).name))
        for url in sorted(urls)
    ]
    series = backend.read_timeseries(files, channel, start, end)
    provenance = {
        "frametype": frametype,
        "channel": channel,
        "urls": urls,
        "files": files,
        "datafind_server": os.environ.get("GWDATAFIND_SERVER", DEFAULT_DATAFIND_SERVER),
    }
    return series, provenance


def ldg_preflight(ifos: list[str]) -> None:
    missing = missing_modules()
    if missing:
        raise AdapterUnavailableError(
            f"the LDG data path requires {missing}; install with 'uv sync --extra ldg'"
        )
    unknown = [ifo for ifo in ifos if ifo not in STRAIN_CHANNELS]
    if unknown:
        raise AdapterUnavailableError(
            f"no reviewed strain channel for detectors {unknown}; known: "
            f"{sorted(STRAIN_CHANNELS)}"
        )
    available, description = credential_status()
    if not available:
        raise AdapterUnavailableError(description)
