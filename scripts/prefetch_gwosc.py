#!/usr/bin/env python3
"""Pre-populate the astropy download cache with GWOSC strain files.

Buoy and the agent's ``data.fetch`` adapter both read public strain through
``gwpy.timeseries.TimeSeries.fetch_open_data``. With ``GWPY_CACHE=1`` gwpy
serves the frame files from the astropy download cache, keyed by their
original URL. On nodes with slow or unreliable routes to ``gwosc.org`` the
in-run download can fail part-way (the archive does not support resuming),
so this script fetches the files up front with retries, verifies the
declared ``Content-Length``, and imports them into the cache.

Examples::

    # download from GWOSC with up to 10 attempts per file
    python scripts/prefetch_gwosc.py GW150914

    # a custom window (GPS start/end) and detector set
    python scripts/prefetch_gwosc.py 1126259462.4 --start 1126259366 \
        --end 1126259494 --ifos H1 L1

    # files downloaded elsewhere and copied to this node
    python scripts/prefetch_gwosc.py GW150914 --local-dir /data/gwosc

Only the 4 kHz HDF5 files that gwpy would select for the window are
cached; they are identified by URL, so a later ``fetch_open_data`` call for
the same span uses them without any change to the science code.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_WINDOW = 128.0
DEFAULT_OFFSET_FRACTION = 0.75


def window_for_event(event: str, window: float, fraction: float):
    import gwosc.datasets

    if event.startswith("GW"):
        event_time = float(gwosc.datasets.event_gps(event))
        ifos = sorted(gwosc.datasets.event_detectors(event))
    else:
        event_time = float(event)
        ifos = ["H1", "L1"]
    offset = event_time % 1
    start = event_time - fraction * window - offset
    return start, start + window, ifos


def urls_for(ifo: str, start: float, end: float) -> list[str]:
    from gwosc.locate import get_urls

    return list(get_urls(ifo, start, end, sample_rate=4096, format="hdf5"))


def content_length(url: str) -> int | None:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        value = response.headers.get("Content-Length")
    return int(value) if value else None


def download(url: str, target: Path, attempts: int) -> Path:
    expected = content_length(url)
    for attempt in range(1, attempts + 1):
        if target.exists() and (expected is None or target.stat().st_size == expected):
            return target
        part = target.with_suffix(target.suffix + ".part")
        print(f"[{attempt}/{attempts}] downloading {url}", file=sys.stderr)
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                with part.open("wb") as handle:
                    while True:
                        chunk = response.read(1 << 20)
                        if not chunk:
                            break
                        handle.write(chunk)
        except OSError as exc:
            print(f"    failed: {exc}", file=sys.stderr)
            continue
        if expected is not None and part.stat().st_size != expected:
            print(
                f"    short file: {part.stat().st_size} of {expected} bytes",
                file=sys.stderr,
            )
            continue
        part.replace(target)
    if target.exists() and (expected is None or target.stat().st_size == expected):
        return target
    raise SystemExit(f"could not download {url} after {attempts} attempts")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("event", help="GWTC event name (GW150914) or GPS time")
    parser.add_argument("--start", type=float, help="override GPS start")
    parser.add_argument("--end", type=float, help="override GPS end")
    parser.add_argument("--ifos", nargs="+", help="override detector list")
    parser.add_argument("--window-seconds", type=float, default=DEFAULT_WINDOW)
    parser.add_argument(
        "--event-offset-fraction", type=float, default=DEFAULT_OFFSET_FRACTION
    )
    parser.add_argument(
        "--local-dir",
        type=Path,
        help="directory holding already-downloaded files named as on GWOSC",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("gwosc-prefetch"),
        help="where downloaded files are kept (default: ./gwosc-prefetch)",
    )
    parser.add_argument("--attempts", type=int, default=10)
    args = parser.parse_args(argv)

    from astropy.utils.data import import_file_to_cache, is_url_in_cache

    if args.start is None or args.end is None:
        start, end, ifos = window_for_event(
            args.event, args.window_seconds, args.event_offset_fraction
        )
    else:
        start, end, ifos = args.start, args.end, args.ifos or ["H1", "L1"]
    ifos = args.ifos or ifos
    print(f"window [{start}, {end}) for {ifos}", file=sys.stderr)

    args.download_dir.mkdir(parents=True, exist_ok=True)
    for ifo in ifos:
        for url in urls_for(ifo, start, end):
            name = Path(urlparse(url).path).name
            if is_url_in_cache(url):
                print(f"cached already: {url}", file=sys.stderr)
                continue
            if args.local_dir is not None and (args.local_dir / name).is_file():
                source = args.local_dir / name
                expected = content_length(url)
                if expected is not None and source.stat().st_size != expected:
                    raise SystemExit(
                        f"{source} has {source.stat().st_size} bytes, GWOSC "
                        f"reports {expected}"
                    )
            else:
                source = download(url, args.download_dir / name, args.attempts)
            cached = import_file_to_cache(url, str(source), remove_original=False)
            print(f"{name}\t{source.stat().st_size} bytes\tsha256 {sha256(source)}")
            print(f"  -> {cached}", file=sys.stderr)
    print("set GWPY_CACHE=1 so gwpy reads these files from the cache", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
