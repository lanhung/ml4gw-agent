"""Capability inspection shared by CLI and local service."""

from __future__ import annotations

import shutil
import subprocess

from .adapters import PYTHON_ADAPTERS
from .models import AdapterKind, SkillSpec


def skill_availability(skill: SkillSpec, mode: str) -> str:
    if mode == "mock":
        availability = (
            "builtin" if skill.adapter.kind == AdapterKind.BUILTIN else "mock"
        )
    elif skill.adapter.kind == AdapterKind.BUILTIN:
        availability = "available"
    elif skill.adapter.kind == AdapterKind.BUOY_CLI:
        executable = shutil.which(skill.adapter.entrypoint)
        if executable is None:
            availability = "missing"
        else:
            try:
                probe = subprocess.run(
                    [executable, "--help"],
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=60,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                availability = f"broken: {type(exc).__name__}"
            else:
                availability = (
                    "available"
                    if probe.returncode == 0
                    else f"broken: exit {probe.returncode}"
                )
    elif skill.adapter.kind == AdapterKind.PYTHON:
        adapter_class = PYTHON_ADAPTERS.get(skill.adapter.entrypoint)
        if adapter_class is None:
            availability = "broken: unregistered entrypoint"
        else:
            availability = adapter_class().probe()
    else:
        availability = "planned"
    return availability
