#!/usr/bin/env python3
"""Build the shipped GWTC event table from the GWOSC event API.

    python scripts/build_gwtc_table.py --output calibration/gwtc_events.json

One record per commonName (latest catalog wins): GPS, GraceDB superevent id
when GWOSC lists one, network SNR, source-frame masses, chirp mass, distance,
FAR, p_astro, catalog. Used by ``data.resolve_event`` for offline name and
superevent resolution; the network lookup remains the fallback.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

CATALOGS = [
    "GWTC-1-confident",
    "GWTC-2.1-confident",
    "GWTC-3-confident",
    "O3_Discovery_Papers",
    "GWTC-4.0",
    "GWTC-4.1",
    "GWTC-5.0",
    "O4_Discovery_Papers",
]
FIELDS = (
    "GPS",
    "network_matched_filter_snr",
    "mass_1_source",
    "mass_2_source",
    "chirp_mass_source",
    "total_mass_source",
    "luminosity_distance",
    "far",
    "p_astro",
)


def fetch(url: str) -> dict:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as handle:
                return json.loads(handle.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 - retried
            time.sleep(2**attempt)
    raise SystemExit(f"could not fetch {url}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--detail", action="store_true", help="also fetch per-event GraceDB ids"
    )
    args = parser.parse_args(argv)
    events: dict[str, dict] = {}
    for catalog in CATALOGS:
        data = fetch(f"https://gwosc.org/eventapi/json/{catalog}/")
        for rec in data.get("events", {}).values():
            name = rec["commonName"]
            row = {f: rec.get(f) for f in FIELDS}
            row["catalog"] = catalog
            row["version"] = rec.get("version")
            row["jsonurl"] = rec.get("jsonurl")
            events[name] = row  # later catalogs override earlier ones
        print(catalog, len(data.get("events", {})), "events")
    if args.detail:
        for row in events.values():
            if not row.get("jsonurl") or row["catalog"] in (
                "GWTC-1-confident",
                "GWTC-2.1-confident",
                "GWTC-3-confident",
            ):
                continue
            detail = fetch(row["jsonurl"])
            rec = next(iter(detail.get("events", {}).values()), {})
            for key in ("gracedb", "GraceDB", "gracedb_id", "superevent"):
                if rec.get(key):
                    row["gracedb"] = rec[key]
                    break
            time.sleep(0.2)
    table = {
        "schema_version": "1.0",
        "source": "GWOSC event API (https://gwosc.org/eventapi/json/), catalogs "
        + ", ".join(CATALOGS),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "events": dict(sorted(events.items(), key=lambda kv: kv[1]["GPS"] or 0)),
    }
    args.output.write_text(json.dumps(table, indent=1) + "\n")
    print(
        len(events),
        "events ->",
        args.output,
        "with gracedb ids:",
        sum(1 for r in events.values() if r.get("gracedb")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
