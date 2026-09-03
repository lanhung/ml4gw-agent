"""Non-public strain through the LIGO Data Grid (the ``mldatafind`` route).

``data.fetch`` with ``source: ldg`` reads authenticated frames the way Buoy
does for post-O4a times: ``gwpy.timeseries.TimeSeries.get`` on the
calibrated strain channel, which discovers frames through ``gwdatafind`` and
needs IGWN credentials (a SciToken or an X.509 proxy). Nothing here can run
on a machine without those credentials, so the adapter fails closed in
``preflight`` with the exact missing piece instead of attempting a fetch.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import AdapterUnavailableError

REQUIRED_MODULES = ("gwpy", "gwdatafind", "igwn_auth_utils")

# Channel map Buoy uses for non-public strain (buoy/utils/data.py).
STRAIN_CHANNELS = {
    "H1": "H1:GDS-CALIB_STRAIN_CLEAN",
    "L1": "L1:GDS-CALIB_STRAIN_CLEAN",
    "V1": "V1:Hrec_hoft_16384Hz",
}


@dataclass(frozen=True)
class LDGBackend:
    get_timeseries: Any  # TimeSeries.get(channel, start, end)


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
        "no IGWN credential found: set BEARER_TOKEN_FILE (SciToken) or "
        "X509_USER_PROXY, for example via htgettoken or ligo-proxy-init"
    )


def load_ldg_backend() -> LDGBackend:
    missing = missing_modules()
    if missing:
        raise AdapterUnavailableError(
            f"the LDG data path requires {missing}; install with 'uv sync --extra ldg'"
        )
    from gwpy.timeseries import TimeSeries

    return LDGBackend(get_timeseries=TimeSeries.get)


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
