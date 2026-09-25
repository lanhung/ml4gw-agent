#!/usr/bin/env python3
"""Fail if any evidence file contains a credential used for the run.

Credentials are read from the environment variables named with ``--env``,
single-token files given with ``--key-file``, and CLIProxy configs given with
``--proxy-config`` (their ``api-keys`` list). Every file under the given paths
is searched for each credential, raw and JSON-escaped. Only file paths are
printed, never a credential or the line it appears on.

    uv run --no-sync python scripts/check_no_secrets.py \\
        --env GLM_API_KEY --proxy-config /abs/cli-proxy/config.yaml \\
        docs/test/gpt-matrix-<date> docs/test/glm-matrix-<date>

Exit codes: 0 clean, 1 a credential was found, 2 no credential was supplied.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path

import yaml


def collect_secrets(
    env_names: Iterable[str],
    key_files: Iterable[Path],
    proxy_configs: Iterable[Path],
    environ: dict[str, str] | None = None,
) -> list[str]:
    environ = os.environ if environ is None else environ
    secrets: list[str] = []
    for name in env_names:
        value = environ.get(name, "").strip()
        if value:
            secrets.append(value)
    for path in key_files:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                secrets.append(value)
    for path in proxy_configs:
        if path.is_file():
            config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            secrets.extend(str(k) for k in config.get("api-keys") or [] if k)
    return list(dict.fromkeys(secrets))


def files_under(paths: Iterable[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(p for p in sorted(path.rglob("*")) if p.is_file())
    return found


def leaking_files(files: Iterable[Path], secrets: list[str]) -> list[Path]:
    needles = set()
    for secret in secrets:
        needles.add(secret.encode())
        needles.add(json.dumps(secret)[1:-1].encode())
    return [p for p in files if any(n in p.read_bytes() for n in needles)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--env", action="append", default=[], metavar="NAME")
    parser.add_argument("--key-file", action="append", default=[], type=Path)
    parser.add_argument("--proxy-config", action="append", default=[], type=Path)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)

    secrets = collect_secrets(args.env, args.key_file, args.proxy_config)
    if not secrets:
        print("no credential supplied; nothing to check", file=sys.stderr)
        return 2
    files = files_under(args.paths)
    leaks = leaking_files(files, secrets)
    for path in leaks:
        print(f"LEAK: {path}")
    if leaks:
        return 1
    print(f"checked {len(files)} files against {len(secrets)} credential(s): clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
