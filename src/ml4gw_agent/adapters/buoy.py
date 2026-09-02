from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import logging
import shutil
import subprocess
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from ..errors import AdapterError, AdapterUnavailableError
from ..planning import EVENT_PATTERN
from .base import (
    AdapterOutcome,
    ExecutionContext,
    SkillAdapter,
    artifact_directory,
    relative_to_run,
)


class BuoyCLIAdapter(SkillAdapter):
    """Constrained adapter for the documented ml4gw-buoy CLI."""

    def __init__(self, executable: str = "buoy"):
        self.executable = executable

    def preflight(self, context: ExecutionContext) -> list[str]:
        warnings: list[str] = []
        event = str(context.parameters.get("event", ""))
        if not EVENT_PATTERN.fullmatch(event):
            raise AdapterError(
                f"Buoy received an unsupported event identifier: {event}"
            )

        runner = context.parameters.get("runner", "cli")
        if runner == "python":
            if importlib.util.find_spec("buoy") is None:
                raise AdapterUnavailableError(
                    "The Buoy Python runner requires the 'ml4gw-buoy' package. "
                    "Install it with 'uv sync --extra buoy'."
                )
            warnings.append(
                "Buoy is running through its Python API without subprocess "
                "isolation or a hard timeout. Use the CLI runner in production."
            )
        else:
            executable = shutil.which(self.executable)
            if executable is None:
                raise AdapterUnavailableError(
                    "The real Buoy adapter requires the 'buoy' executable. Install "
                    "the optional dependency with 'uv sync --extra buoy'."
                )

        device = context.parameters.get("device", "cuda")
        if device == "cuda" and shutil.which("nvidia-smi") is None:
            warnings.append(
                "CUDA was requested but nvidia-smi is not visible. Buoy will perform "
                "its own torch CUDA check and may refuse execution."
            )
        if device == "cpu":
            warnings.append(
                "Buoy documents roughly 15 minutes for default CPU execution; a GPU "
                "is preferred."
            )

        if not context.parameters.get("aframe_revision"):
            warnings.append("Aframe model revision is unpinned.")
        if not context.parameters.get("amplfi_revision"):
            warnings.append("AMPLFI model revision is unpinned.")
        if event.startswith(("G", "S")) and not event.startswith("GW"):
            warnings.append(
                "GraceDB identifiers require LIGO credentials; Buoy will validate "
                "the configured authentication at data access time."
            )
        return warnings

    def build_command(self, context: ExecutionContext, output_root: Path) -> list[str]:
        params = context.parameters
        command = [
            self.executable,
            "--events",
            str(params["event"]),
            "--outdir",
            str(output_root),
            "--samples_per_event",
            str(params.get("samples_per_event", 20_000)),
            "--nside",
            str(params.get("nside", 64)),
            "--min_samples_per_pix",
            str(params.get("min_samples_per_pix", 5)),
            "--use_distance",
            str(params.get("use_distance", True)).lower(),
            "--use_true_tc_for_amplfi",
            str(params.get("use_true_tc_for_amplfi", False)).lower(),
            "--device",
            str(params.get("device", "cuda")),
            "--run_aframe",
            "true",
            "--run_amplfi",
            "true",
            "--generate_plots",
            "true",
            "--to_html",
            "true",
        ]
        if ifos := params.get("ifos"):
            command.extend(["--ifos", json.dumps(ifos)])
        if params.get("seed") is not None:
            command.extend(["--seed", str(params["seed"])])
        if revision := params.get("aframe_revision"):
            command.extend(["--aframe_revision", str(revision)])
        if revision := params.get("amplfi_revision"):
            command.extend(["--amplfi_revision", str(revision)])
        return command

    def describe_invocation(
        self, context: ExecutionContext
    ) -> tuple[list[str] | None, dict[str, Any]]:
        runner = context.parameters.get("runner", "cli")
        if runner == "python":
            return None, {
                "adapter": "buoy-python-api-v0.1",
                "python_call": "buoy.main.main",
                "subprocess_isolation": False,
                "hard_timeout_enforced": False,
            }
        output_root = context.run_dir / "artifacts" / context.task.id / "buoy-output"
        return self.build_command(context, output_root), {"adapter": "buoy-cli-v0.1"}

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        if context.parameters.get("runner", "cli") == "python":
            return self._execute_python(context)
        return self._execute_cli(context)

    def _execute_cli(self, context: ExecutionContext) -> AdapterOutcome:
        artifact_dir = artifact_directory(context)
        output_root = artifact_dir / "buoy-output"
        output_root.mkdir(parents=True, exist_ok=True)
        logs_dir = context.run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = logs_dir / f"{context.task.id}.stdout.log"
        stderr_log = logs_dir / f"{context.task.id}.stderr.log"
        command = self.build_command(context, output_root)

        try:
            with (
                stdout_log.open("w", encoding="utf-8") as stdout_handle,
                stderr_log.open("w", encoding="utf-8") as stderr_handle,
            ):
                completed = subprocess.run(
                    command,
                    cwd=context.run_dir,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    text=True,
                    shell=False,
                    timeout=context.skill.adapter.timeout_seconds,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(
                f"Buoy timed out after {context.skill.adapter.timeout_seconds} seconds"
            ) from exc
        if completed.returncode != 0:
            raise AdapterError(
                f"Buoy exited with code {completed.returncode}; see "
                f"{relative_to_run(stderr_log, context.run_dir)}"
            )

        return self._collect_outcome(
            context,
            output_root,
            stdout_log,
            stderr_log,
            command=command,
            metadata={"adapter": "buoy-cli-v0.1", "return_code": 0},
        )

    def _execute_python(self, context: ExecutionContext) -> AdapterOutcome:
        artifact_dir = artifact_directory(context)
        output_root = artifact_dir / "buoy-output"
        output_root.mkdir(parents=True, exist_ok=True)
        logs_dir = context.run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = logs_dir / f"{context.task.id}.stdout.log"
        stderr_log = logs_dir / f"{context.task.id}.stderr.log"
        params = context.parameters
        root_logger = logging.getLogger()
        original_handlers = list(root_logger.handlers)
        original_level = root_logger.level

        try:
            with (
                stdout_log.open("w", encoding="utf-8") as stdout_handle,
                stderr_log.open("w", encoding="utf-8") as stderr_handle,
                redirect_stdout(stdout_handle),
                redirect_stderr(stderr_handle),
            ):
                try:
                    from buoy.main import main as buoy_main

                    buoy_main(
                        outdir=output_root,
                        events=str(params["event"]),
                        samples_per_event=params.get("samples_per_event", 20_000),
                        nside=params.get("nside", 64),
                        min_samples_per_pix=params.get("min_samples_per_pix", 5),
                        use_distance=params.get("use_distance", True),
                        aframe_revision=params.get("aframe_revision"),
                        amplfi_revision=params.get("amplfi_revision"),
                        use_true_tc_for_amplfi=params.get(
                            "use_true_tc_for_amplfi", False
                        ),
                        ifos=params.get("ifos"),
                        device=params.get("device", "cuda"),
                        to_html=True,
                        seed=params.get("seed"),
                        verbose=False,
                        run_aframe=True,
                        run_amplfi=True,
                        generate_plots=True,
                        force=False,
                        max_workers=1,
                    )
                except SystemExit as exc:
                    traceback.print_exc(file=stderr_handle)
                    raise AdapterError(
                        f"Buoy Python API exited during configuration with code "
                        f"{exc.code}; see "
                        f"{relative_to_run(stderr_log, context.run_dir)}"
                    ) from exc
                except Exception as exc:
                    traceback.print_exc(file=stderr_handle)
                    raise AdapterError(
                        f"Buoy Python API failed with {type(exc).__name__}: {exc}; "
                        f"see {relative_to_run(stderr_log, context.run_dir)}"
                    ) from exc
        finally:
            for handler in list(root_logger.handlers):
                if handler not in original_handlers:
                    root_logger.removeHandler(handler)
                    handler.close()
            root_logger.setLevel(original_level)

        return self._collect_outcome(
            context,
            output_root,
            stdout_log,
            stderr_log,
            command=None,
            metadata={
                "adapter": "buoy-python-api-v0.1",
                "python_call": "buoy.main.main",
                "subprocess_isolation": False,
                "hard_timeout_enforced": False,
            },
        )

    def _collect_outcome(
        self,
        context: ExecutionContext,
        output_root: Path,
        stdout_log: Path,
        stderr_log: Path,
        *,
        command: list[str] | None,
        metadata: dict[str, Any],
    ) -> AdapterOutcome:
        event = str(context.parameters["event"])
        event_dir = output_root / event
        data_dir = event_dir / "data"
        aframe_output = data_dir / "aframe_outputs.hdf5"
        posterior = data_dir / "posterior_samples.dat"
        summary = event_dir / "summary.html"
        plots = sorted((event_dir / "plots").glob("*"))

        detection_statistic, predicted_tc = self._read_aframe_summary(aframe_output)
        artifacts = [
            path
            for path in event_dir.rglob("*")
            if path.is_file() and not path.is_symlink()
        ]
        artifacts.extend([stdout_log, stderr_log])

        try:
            package_version = importlib.metadata.version("ml4gw-buoy")
        except importlib.metadata.PackageNotFoundError:
            package_version = "unknown"

        outputs: dict[str, Any] = {
            "event": event,
            "output_directory": relative_to_run(event_dir, context.run_dir),
            "aframe_output": relative_to_run(aframe_output, context.run_dir),
            "posterior_samples": relative_to_run(posterior, context.run_dir),
            "plots": [relative_to_run(path, context.run_dir) for path in plots],
            "summary_html": (
                relative_to_run(summary, context.run_dir) if summary.exists() else None
            ),
            "detection_statistic": detection_statistic,
            "predicted_coalescence_time": predicted_tc,
            "simulated": False,
        }
        metadata["buoy_package_version"] = package_version
        return AdapterOutcome(
            outputs=outputs,
            artifacts=artifacts,
            command=command,
            metadata=metadata,
        )

    @staticmethod
    def _read_aframe_summary(path: Path) -> tuple[float | None, float | None]:
        if not path.exists():
            return None, None
        try:
            import h5py

            with h5py.File(path, "r") as handle:
                values = handle["signif_integrated"][:].reshape(-1)
                statistic = float(max(values)) if len(values) else None
                predicted = handle.attrs.get("predicted_tc")
                predicted_tc = float(predicted) if predicted is not None else None
            return statistic, predicted_tc
        except (ImportError, KeyError, OSError, TypeError, ValueError):
            return None, None
