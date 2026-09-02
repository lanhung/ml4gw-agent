from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import platform
import sys
from collections.abc import Iterable
from pathlib import Path

from ._version import __version__
from .errors import ValidationError
from .models import ArtifactRecord, RunManifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_artifacts(paths: Iterable[Path], run_dir: Path) -> list[ArtifactRecord]:
    root = run_dir.resolve()
    records: list[ArtifactRecord] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise ValidationError(f"artifact escaped run directory: {path}") from exc
        if path.is_symlink():
            raise ValidationError(
                f"symbolic-link artifacts are not accepted: {relative}"
            )
        if not resolved.is_file():
            raise ValidationError(f"artifact is not a regular file: {relative}")
        media_type = (
            mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        )
        records.append(
            ArtifactRecord(
                relative_path=relative.as_posix(),
                sha256=sha256_file(resolved),
                size_bytes=resolved.stat().st_size,
                media_type=media_type,
            )
        )
    return sorted(records, key=lambda item: item.relative_path)


def runtime_environment() -> dict[str, object]:
    return {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "process_id": os.getpid(),
        "agent_version": __version__,
    }


def write_manifest(manifest: RunManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = manifest.model_dump(mode="json")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
