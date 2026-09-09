"""Event resolution: GWTC names, GraceDB identifiers, UTC strings, GPS.

Sources, in order of trust:

1. the shipped GWTC table (``calibration/gwtc_events.json``, built from the
   GWOSC event API by ``scripts/build_gwtc_table.py``): name, GPS, GraceDB
   superevent id, SNR, masses, distance, FAR;
2. the public GraceDB REST API (anonymous access to public superevents and
   events): ``t_0``, FAR, instruments, labels (``ADVNO`` marks a retraction);
3. a UTC timestamp converted to GPS with astropy.

Network access is only attempted in real mode; failures never invent a
time (``catalog_time`` stays ``None`` and the reason is recorded).
"""

from __future__ import annotations

import json
import re
import urllib.request
from importlib import resources
from typing import Any

GRACEDB_API = "https://gracedb.ligo.org/api"
UTC_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2}(?:\.\d+)?)(?:\s*(?:UTC|Z))?",
    re.IGNORECASE,
)


def load_gwtc_table() -> dict[str, Any]:
    path = resources.files("ml4gw_agent.calibration").joinpath("gwtc_events.json")
    return json.loads(path.read_text(encoding="utf-8"))


def gwtc_lookup(
    name: str, table: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    table = load_gwtc_table() if table is None else table
    events = table.get("events", {})
    if name in events:
        return {"name": name, **events[name]}
    # GW150914 style names without the time suffix
    for full, rec in events.items():
        if full.split("_")[0] == name:
            return {"name": full, **rec}
    return None


def gwtc_by_gracedb(superevent: str, table: dict[str, Any] | None = None):
    table = load_gwtc_table() if table is None else table
    for name, rec in table.get("events", {}).items():
        if rec.get("gracedb") == superevent:
            return {"name": name, **rec}
    return None


def fetch_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as handle:
        return json.loads(handle.read().decode("utf-8"))


def gracedb_lookup(identifier: str, fetch=fetch_json) -> dict[str, Any]:
    """Public GraceDB record for a superevent (S…) or event (G…) id."""
    if identifier.startswith("S"):
        data = fetch(f"{GRACEDB_API}/superevents/{identifier}/")
        labels = list(data.get("labels") or [])
        preferred = data.get("preferred_event_data") or {}
        instruments = data.get("instruments") or preferred.get("instruments") or ""
        return {
            "gracedb_id": identifier,
            "gps": float(data["t_0"]),
            "far": data.get("far")
            if data.get("far") is not None
            else preferred.get("far"),
            "instruments": sorted(i for i in str(instruments).split(",") if i),
            "labels": labels,
            "retracted": "ADVNO" in labels,
            "gw_name": data.get("gw_id"),
            "pipeline": preferred.get("pipeline"),
            "group": preferred.get("group"),
        }
    data = fetch(f"{GRACEDB_API}/events/{identifier}/")
    labels = list(data.get("labels") or [])
    return {
        "gracedb_id": identifier,
        "gps": float(data["gpstime"]),
        "far": data.get("far"),
        "instruments": sorted(
            i for i in str(data.get("instruments") or "").split(",") if i
        ),
        "labels": labels,
        "retracted": "ADVNO" in labels,
        "gw_name": None,
        "pipeline": data.get("pipeline"),
        "group": data.get("group"),
        "superevent": data.get("superevent"),
    }


def utc_to_gps(text: str) -> float | None:
    match = UTC_PATTERN.search(text)
    if not match:
        return None
    from astropy.time import Time

    return float(Time(f"{match.group(1)}T{match.group(2)}", scale="utc").gps)


def resolve(event: str, *, online: bool, fetch=fetch_json) -> dict[str, Any]:
    """Resolve any supported identifier; never guesses a time."""
    out: dict[str, Any] = {
        "event": event,
        "catalog_time": None,
        "gw_name": None,
        "gracedb_id": None,
        "far_per_year": None,
        "instruments": None,
        "retracted": None,
        "catalog": None,
        "resolution_source": None,
        "resolution_note": None,
    }
    if UTC_PATTERN.search(event):
        out.update(
            event_kind="gps", catalog_time=utc_to_gps(event), resolution_source="utc"
        )
        return out
    if event[:2].upper() == "GW":
        out["event_kind"] = "gwtc"
        rec = gwtc_lookup(event)
        if rec:
            out.update(
                catalog_time=rec.get("GPS"),
                gw_name=rec["name"],
                gracedb_id=rec.get("gracedb"),
                far_per_year=rec.get("far"),
                catalog=rec.get("catalog"),
                resolution_source="gwtc_table",
            )
        else:
            out["resolution_note"] = "not in the shipped GWTC table"
        return out
    if event[:1] == "S" or event[:1] == "G":
        out["event_kind"] = (
            "gracedb_superevent" if event[:1] == "S" else "gracedb_event"
        )
        rec = gwtc_by_gracedb(event) if event[:1] == "S" else None
        if rec:
            out.update(
                catalog_time=rec.get("GPS"),
                gw_name=rec["name"],
                gracedb_id=event,
                far_per_year=rec.get("far"),
                catalog=rec.get("catalog"),
                resolution_source="gwtc_table",
            )
        if online:
            try:
                g = gracedb_lookup(event, fetch=fetch)
            except Exception as exc:  # noqa: BLE001 - recorded, never invented
                out["resolution_note"] = f"GraceDB lookup failed: {exc}"[:200]
            else:
                far = g.get("far")
                out.update(
                    catalog_time=g["gps"],
                    gracedb_id=event,
                    instruments=g["instruments"],
                    retracted=g["retracted"],
                    resolution_source="gracedb",
                )
                if far is not None:
                    out["far_per_year"] = float(far) * 365.25 * 86400.0
                if g.get("gw_name"):
                    out["gw_name"] = g["gw_name"]
                if g["retracted"]:
                    out["resolution_note"] = "retracted by the collaboration (ADVNO)"
        elif not rec:
            out["resolution_note"] = "GraceDB lookup skipped (offline/mock mode)"
        return out
    out.update(event_kind="gps", catalog_time=float(event), resolution_source="gps")
    return out
