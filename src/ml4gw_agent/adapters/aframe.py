"""Real ``aframe.detect`` adapter over ``buoy.models.Aframe``.

Buoy already wraps the published TorchScript Aframe model together with the
exact preprocessing it was trained with. This adapter reuses that wrapper on
an agent-managed strain artifact and writes the same ``aframe_outputs.hdf5``
layout Buoy writes, so the two can be compared directly.

The detection threshold is **not** a calibrated false-alarm-rate threshold.
It is recorded in the outputs and flagged as uncalibrated until a background
study supplies one.
"""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from typing import Any

import h5py
import numpy as np

from ..errors import AdapterError, AdapterUnavailableError
from .base import (
    AdapterOutcome,
    ExecutionContext,
    SkillAdapter,
    artifact_directory,
    relative_to_run,
)
from .strain_io import package_versions, read_strain, resolve_artifact

REQUIRED_MODULES = ("buoy", "torch", "ml4gw")
AFRAME_REPO_ID = "ML4GW/aframe"
DEFAULT_THRESHOLD = 0.0
UNCALIBRATED_THRESHOLD_WARNING = (
    "aframe.detect threshold is a raw integrated network output, not a "
    "false-alarm-rate calibrated threshold; treat candidate_found as "
    "provisional until a background study fixes the threshold"
)


@dataclass(frozen=True)
class TorchBackend:
    """Torch-specific operations kept behind one seam for testing."""

    aframe_class: Any
    to_tensor: Any
    seed: Any


def _missing() -> list[str]:
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def load_aframe_backend() -> TorchBackend:
    missing = _missing()
    if missing:
        raise AdapterUnavailableError(
            f"the Aframe adapter requires {missing}; install with "
            "'uv sync --extra buoy'"
        )
    import torch
    from buoy.models import Aframe

    return TorchBackend(
        aframe_class=Aframe,
        to_tensor=lambda array: torch.as_tensor(np.asarray(array)).double(),
        seed=torch.manual_seed,
    )


def model_metadata(model: Any, revision: str, device: str) -> dict[str, Any]:
    fields = (
        "sample_rate",
        "kernel_length",
        "psd_length",
        "fduration",
        "highpass",
        "lowpass",
        "fftlength",
        "inference_sampling_rate",
        "offline_sampling_rate",
        "batch_size",
        "aframe_right_pad",
        "integration_window_length",
    )
    return {
        "repo_id": AFRAME_REPO_ID,
        "revision": revision,
        "device": device,
        "config": {name: getattr(model, name, None) for name in fields},
    }


class AframeAdapter(SkillAdapter):
    name = "aframe-buoy-v0.2"

    def probe(self) -> str:
        missing = _missing()
        return "available" if not missing else f"missing: {', '.join(missing)}"

    def preflight(self, context: ExecutionContext) -> list[str]:
        missing = _missing()
        if missing:
            raise AdapterUnavailableError(
                f"the Aframe adapter requires {missing}; install with "
                "'uv sync --extra buoy'"
            )
        warnings = [UNCALIBRATED_THRESHOLD_WARNING]
        device = context.parameters.get("device", "cuda")
        if device == "cuda" and shutil.which("nvidia-smi") is None:
            warnings.append(
                "CUDA was requested for Aframe but nvidia-smi is not visible"
            )
        if context.parameters.get("model_revision") == "UNPINNED":
            warnings.append("Aframe model revision is not pinned")
        return warnings

    def describe_invocation(
        self, context: ExecutionContext
    ) -> tuple[list[str] | None, dict[str, Any]]:
        return None, {
            "adapter": self.name,
            "python_call": "buoy.models.Aframe.__call__",
            "repo_id": AFRAME_REPO_ID,
            "revision": context.parameters.get("model_revision"),
            "device": context.parameters.get("device", "cuda"),
        }

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        params = context.parameters
        backend = load_aframe_backend()
        strain = read_strain(
            resolve_artifact(str(params["strain_artifact"]), context.run_dir)
        )
        ifos = [str(ifo) for ifo in params["ifos"]]
        if ifos != ["H1", "L1"]:
            raise AdapterError(
                f"the published Aframe model expects detectors ['H1', 'L1']; got {ifos}"
            )
        revision = str(params["model_revision"])
        device = str(params.get("device", "cuda"))
        threshold = float(params.get("threshold", DEFAULT_THRESHOLD))
        calibration = params.get("threshold_calibration") or None
        if calibration and str(calibration.get("revision")) != revision:
            raise AdapterError(
                "threshold_calibration was derived for Aframe revision "
                f"{calibration.get('revision')}, not {revision}"
            )
        target_time = params.get("target_time")
        target_time = float(target_time) if target_time is not None else None
        window = float(params.get("candidate_window_seconds", 2.0))
        seed = params.get("seed")
        if seed is not None:
            backend.seed(int(seed))

        try:
            model = backend.aframe_class(device=device, revision=revision)
        except Exception as exc:
            raise AdapterError(
                f"could not load Aframe revision {revision}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if abs(float(model.sample_rate) - strain.sample_rate) > 1e-9:
            raise AdapterError(
                f"strain sample rate {strain.sample_rate:g} Hz does not match the "
                f"Aframe model's {float(model.sample_rate):g} Hz; refusing to "
                "resample silently"
            )
        data = backend.to_tensor(strain.stacked(ifos))
        minimum = int(getattr(model, "minimum_data_size", 0))
        if minimum and strain.n_samples < minimum:
            raise AdapterError(
                f"strain has {strain.n_samples} samples; the Aframe configuration "
                f"needs at least {minimum} (about {minimum / strain.sample_rate:g} s)"
            )

        try:
            times, ys, timing_integrated, signif_integrated = model(data, strain.t0)
        except Exception as exc:
            raise AdapterError(
                f"Aframe inference failed: {type(exc).__name__}: {exc}"
            ) from exc

        times = np.asarray(times, dtype="f8")
        timing_integrated = np.asarray(timing_integrated, dtype="f8")
        signif_integrated = np.asarray(signif_integrated, dtype="f8")
        finite = np.isfinite(timing_integrated).all()
        finite = finite and np.isfinite(signif_integrated).all()
        if not finite:
            raise AdapterError("Aframe produced non-finite integrated outputs")
        if signif_integrated.size == 0 or timing_integrated.size == 0:
            raise AdapterError("Aframe produced empty outputs")

        peak_index = int(np.argmax(timing_integrated))
        raw_peak_time = float(times[peak_index] + float(model.time_offset))
        detection_statistic = float(np.max(signif_integrated))
        warnings = [] if calibration else [UNCALIBRATED_THRESHOLD_WARNING]
        peak_in_window = bool(strain.t0 <= raw_peak_time <= strain.gps_end)
        target_offset: float | None = None
        peak_near_target: bool | None = None
        if target_time is not None:
            target_offset = raw_peak_time - target_time
            peak_near_target = abs(target_offset) <= window
        if peak_in_window:
            predicted_tc: float | None = raw_peak_time
            candidate_found = detection_statistic >= threshold
            if candidate_found and peak_near_target is False:
                candidate_found = False
                warnings.append(
                    f"Aframe's loudest peak ({detection_statistic:.3f}) lies "
                    f"{target_offset:+.3f} s from the requested time {target_time}, "
                    f"outside the {window:g} s candidate window; it is not "
                    "reported as this target's candidate"
                )
        else:
            # Buoy maps the integrated-output peak to a merger time with a
            # fixed negative offset, so a peak in the first samples (where the
            # whitening state is still warming up) lands before the strain
            # starts. That is a start-up artefact, not a candidate: report no
            # candidate so AMPLFI is skipped, and keep the raw value for review.
            predicted_tc = None
            candidate_found = False
            warnings.append(
                f"Aframe's maximum integrated output maps to {raw_peak_time}, "
                f"outside the strain interval [{strain.t0}, {strain.gps_end}]; "
                "treated as a filter start-up artefact, no candidate reported"
            )

        artifact = artifact_directory(context) / "aframe_outputs.hdf5"
        with h5py.File(artifact, "w") as handle:
            handle.create_dataset("times", data=times)
            handle.create_dataset("ys", data=np.asarray(ys, dtype="f8"))
            handle.create_dataset("timing_integrated", data=timing_integrated)
            handle.create_dataset("signif_integrated", data=signif_integrated)
            if predicted_tc is not None:
                handle.attrs["predicted_tc"] = predicted_tc
            handle.attrs["raw_peak_time"] = raw_peak_time
            handle.attrs["peak_in_window"] = peak_in_window
            handle.attrs["detection_statistic"] = detection_statistic
            handle.attrs["threshold"] = threshold
            handle.attrs["model_revision"] = revision
            handle.attrs["strain_artifact"] = str(params["strain_artifact"])

        outputs = {
            "candidate_found": candidate_found,
            "candidate_times": [predicted_tc] if candidate_found else [],
            "predicted_coalescence_time": predicted_tc,
            "raw_peak_time": raw_peak_time,
            "peak_in_window": peak_in_window,
            "detection_statistic": detection_statistic,
            "threshold": threshold,
            "threshold_calibrated": bool(calibration),
            "threshold_far_per_year": (
                float(calibration["far_per_year"]) if calibration else None
            ),
            "target_time": target_time,
            "target_offset_seconds": target_offset,
            "peak_near_target": peak_near_target,
            "output_artifact": relative_to_run(artifact, context.run_dir),
            "model": model_metadata(model, revision, device),
            "simulated": False,
        }
        metadata = {
            "adapter": self.name,
            "packages": package_versions("ml4gw-buoy", "ml4gw", "torch", "h5py"),
            "n_inference_steps": int(times.size),
        }
        return AdapterOutcome(
            outputs=outputs,
            artifacts=[artifact],
            metadata=metadata,
            warnings=warnings,
        )
