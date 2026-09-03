"""Real ``gwak.scan`` adapter over exported GWAK 2.0 TorchScript models.

Upstream ML4GW/gwak publishes no inference package or weights, so this
adapter runs the user's own exported models (``models/gwak``): a SimCLR
embedder that maps whitened H1+L1 kernels to an 8-dimensional embedding and
a background-only normalizing flow whose log probability of that embedding
is the (negative) anomaly score. Preprocessing follows the training
configuration: 4096 Hz, 0.5 s kernels, PSD from the first 64 s of the
window, 1 s whitening filter, 2 s FFT length.

Everything that is not fixed by the training configuration (highpass,
stride, threshold) is a recorded parameter, and the threshold is flagged as
uncalibrated until a time-shifted background study supplies one, exactly as
for Aframe.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from dataclasses import dataclass
from pathlib import Path
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

REQUIRED_MODULES = ("torch", "ml4gw")
REQUIRED_IFOS = ["H1", "L1"]
UNCALIBRATED_WARNING = (
    "gwak.scan threshold is a raw negative log-probability cut, not a "
    "false-alarm-rate calibrated threshold; treat anomaly_found as "
    "provisional until a background study fixes the threshold"
)


def default_model_dir() -> Path:
    env = os.environ.get("ML4GW_GWAK_MODEL_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "models" / "gwak"


def load_manifest(model_dir: Path) -> dict[str, Any]:
    path = model_dir / "MANIFEST.json"
    if not path.is_file():
        raise AdapterUnavailableError(
            f"no GWAK model manifest at {path}; set ML4GW_GWAK_MODEL_DIR to a "
            "directory holding MANIFEST.json and the TorchScript files"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def verify_models(model_dir: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    """Check every file's SHA-256 against the manifest; return the paths."""
    paths: dict[str, Path] = {}
    for role, spec in manifest["files"].items():
        path = model_dir / spec["path"]
        if not path.is_file():
            raise AdapterUnavailableError(f"GWAK {role} model missing: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != spec["sha256"]:
            raise AdapterError(
                f"GWAK {role} model {path.name} has sha256 {digest[:12]}, manifest "
                f"expects {spec['sha256'][:12]}"
            )
        paths[role] = path
    return paths


def _missing() -> list[str]:
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


@dataclass(frozen=True)
class GWAKBackend:
    """Torch operations behind one seam so the tests can fake them."""

    load_jit: Any  # (path, device) -> callable model
    # (strain (2, n), sample_rate, psd_length, fduration, fftlength, highpass)
    # -> whitened (2, m) numpy array covering the post-PSD segment
    whiten: Any
    to_tensor: Any  # (numpy, device) -> tensor
    to_numpy: Any  # tensor -> numpy
    seed: Any


def load_gwak_backend() -> GWAKBackend:
    missing = _missing()
    if missing:
        raise AdapterUnavailableError(
            f"the GWAK adapter requires {missing}; install with 'uv sync --extra buoy'"
        )
    import torch
    from ml4gw.transforms import SpectralDensity, Whiten

    def load_jit(path: Path, device: str):
        model = torch.jit.load(str(path), map_location=device)
        model.eval()
        return model

    def whiten(strain, sample_rate, psd_length, fduration, fftlength, highpass):
        # Strain is ~1e-21 and its PSD ~1e-42, below float32 range; whitening
        # is scale-invariant, so normalise to unit scale first.
        raw = np.asarray(strain, dtype="f8")
        scale = float(np.std(raw)) or 1.0
        x = torch.as_tensor(raw / scale, dtype=torch.float64)
        n_psd = int(psd_length * sample_rate)
        spectral = SpectralDensity(sample_rate, fftlength, average="median", fast=True)
        psd = spectral(x[:, :n_psd])
        whitener = Whiten(fduration, sample_rate, highpass)
        with torch.no_grad():
            out = whitener(x[None, :, n_psd:].float(), psd.float())
        return out[0].cpu().numpy()

    def to_tensor(array, device):
        return torch.as_tensor(np.asarray(array, dtype="f4"), device=device)

    def to_numpy(tensor):
        return tensor.detach().cpu().numpy()

    return GWAKBackend(
        load_jit=load_jit,
        whiten=whiten,
        to_tensor=to_tensor,
        to_numpy=to_numpy,
        seed=torch.manual_seed,
    )


def unfold(whitened: np.ndarray, kernel: int, stride: int) -> np.ndarray:
    n = whitened.shape[-1]
    starts = np.arange(0, n - kernel + 1, stride)
    return np.stack([whitened[:, s : s + kernel] for s in starts]), starts


class GWAKAdapter(SkillAdapter):
    name = "gwak2-torchscript-v0.4"

    def probe(self) -> str:
        missing = _missing()
        if missing:
            return f"missing: {', '.join(missing)}"
        try:
            manifest = load_manifest(default_model_dir())
            verify_models(default_model_dir(), manifest)
        except (AdapterError, AdapterUnavailableError) as exc:
            return f"missing: {exc}"
        return "available"

    def preflight(self, context: ExecutionContext) -> list[str]:
        missing = _missing()
        if missing:
            raise AdapterUnavailableError(
                f"the GWAK adapter requires {missing}; install with "
                "'uv sync --extra buoy'"
            )
        model_dir = Path(context.parameters.get("model_dir") or default_model_dir())
        manifest = load_manifest(model_dir)
        revision = str(context.parameters.get("model_revision", ""))
        if revision != manifest["revision"]:
            raise AdapterError(
                f"gwak.scan model_revision {revision!r} does not match the shipped "
                f"models ({manifest['revision']!r})"
            )
        verify_models(model_dir, manifest)
        warnings = (
            []
            if context.parameters.get("threshold_calibration")
            else [UNCALIBRATED_WARNING]
        )
        if context.parameters.get("device", "cuda") == "cuda":
            import shutil

            if shutil.which("nvidia-smi") is None:
                warnings.append("cuda requested but nvidia-smi is not on PATH")
        return warnings

    def describe_invocation(
        self, context: ExecutionContext
    ) -> tuple[list[str] | None, dict[str, Any]]:
        return None, {
            "adapter": self.name,
            "python_call": "torch.jit.load(embedder) -> torch.jit.load(metric)",
            "model_dir": str(
                context.parameters.get("model_dir") or default_model_dir()
            ),
            "revision": context.parameters.get("model_revision"),
        }

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        params = context.parameters
        backend = load_gwak_backend()
        model_dir = Path(params.get("model_dir") or default_model_dir())
        manifest = load_manifest(model_dir)
        revision = str(params["model_revision"])
        if revision != manifest["revision"]:
            raise AdapterError("model_revision does not match the shipped GWAK models")
        paths = verify_models(model_dir, manifest)
        pre = manifest["preprocessing"]
        sample_rate = float(pre["sample_rate"])
        kernel_s = float(pre["kernel_length_seconds"])
        psd_length = float(params.get("psd_length_seconds", pre["psd_length_seconds"]))
        fduration = float(pre["fduration_seconds"])
        fftlength = float(pre["fftlength_seconds"])
        highpass = params.get("highpass_hz", pre.get("highpass_hz"))
        highpass = float(highpass) if highpass is not None else None
        stride_s = float(
            params.get("stride_seconds", pre.get("stride_seconds", 0.0625))
        )
        target_time = params.get("target_time")
        target_time = float(target_time) if target_time is not None else None
        window = float(params.get("candidate_window_seconds", 0.6))
        threshold = float(params.get("threshold", 0.0))
        calibration = params.get("threshold_calibration") or None
        if calibration and str(calibration.get("revision")) != revision:
            raise AdapterError(
                "threshold_calibration was derived for GWAK revision "
                f"{calibration.get('revision')}, not {revision}"
            )
        top_k = int(params.get("top_k", 10))
        device = str(params.get("device", "cuda"))
        seed = params.get("seed")
        if seed is not None:
            backend.seed(int(seed))

        strain = read_strain(
            resolve_artifact(str(params["strain_artifact"]), context.run_dir)
        )
        if abs(strain.sample_rate - sample_rate) > 1e-9:
            raise AdapterError(
                f"GWAK models expect {sample_rate:g} Hz strain; the artifact is "
                f"{strain.sample_rate:g} Hz (the planner fetches a 4096 Hz copy "
                "for gwak.scan)"
            )
        missing_ifos = [ifo for ifo in REQUIRED_IFOS if ifo not in strain.series]
        if missing_ifos:
            raise AdapterError(
                f"GWAK needs {REQUIRED_IFOS}; artifact lacks {missing_ifos}"
            )
        needed = (psd_length + fduration + kernel_s) * sample_rate
        if strain.n_samples < needed:
            raise AdapterError(
                f"strain has {strain.duration:g} s; GWAK needs at least "
                f"{needed / sample_rate:g} s (PSD + filter + one kernel)"
            )

        data = np.stack([strain.series[ifo] for ifo in REQUIRED_IFOS])
        whitened = backend.whiten(
            data, sample_rate, psd_length, fduration, fftlength, highpass
        )
        kernel = int(round(kernel_s * sample_rate))
        stride = max(1, int(round(stride_s * sample_rate)))
        kernels, starts = unfold(np.asarray(whitened, dtype="f4"), kernel, stride)
        if kernels.shape[0] == 0:
            raise AdapterError("no complete GWAK kernel fits in the analysed segment")
        # Whiten crops fduration/2 from each side of the analysed segment.
        analysis_t0 = strain.t0 + psd_length + fduration / 2
        times = analysis_t0 + (starts + kernel / 2) / sample_rate

        try:
            embedder = backend.load_jit(paths["embedder"], device)
            # The exported flow hard-codes CPU float64 inside its TorchScript
            # graph, so it always runs on the CPU on the (tiny) embeddings.
            metric = backend.load_jit(paths["metric"], "cpu")
        except Exception as exc:
            raise AdapterError(
                f"could not load GWAK models: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            import contextlib

            no_grad = contextlib.nullcontext()
            try:
                import torch

                no_grad = torch.no_grad()
            except ImportError:  # fake backends in tests
                pass
            with no_grad:
                embeddings = embedder(backend.to_tensor(kernels, device))
                log_prob = metric(
                    backend.to_tensor(backend.to_numpy(embeddings), "cpu")
                )
            embeddings = np.asarray(backend.to_numpy(embeddings), dtype="f8")
            log_prob = np.asarray(backend.to_numpy(log_prob), dtype="f8").reshape(-1)
        except Exception as exc:
            raise AdapterError(
                f"GWAK inference failed: {type(exc).__name__}: {exc}"
            ) from exc
        if not np.isfinite(log_prob).all():
            raise AdapterError("GWAK produced non-finite log probabilities")
        scores = -log_prob
        order = np.argsort(scores)[::-1][:top_k]
        top_segments = [
            {
                "time": float(times[i]),
                "score": float(scores[i]),
                "log_prob": float(log_prob[i]),
            }
            for i in order
        ]
        max_score = float(scores.max())
        anomaly_found = bool(max_score >= threshold)
        target_score = target_zscore = None
        target_rank = None
        if target_time is not None:
            near = np.abs(times - target_time) <= window
            if near.any():
                target_score = float(scores[near].max())
                spread = (
                    float(np.percentile(scores, 84) - np.percentile(scores, 16)) / 2
                )
                target_zscore = (
                    float((target_score - np.median(scores)) / spread)
                    if spread
                    else None
                )
                target_rank = int((scores > target_score).sum())

        artifact = artifact_directory(context) / "gwak_scores.hdf5"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(artifact, "w") as handle:
            handle.create_dataset("times", data=times)
            handle.create_dataset("scores", data=scores)
            handle.create_dataset("log_prob", data=log_prob)
            handle.create_dataset("embeddings", data=embeddings)
            handle.attrs["model_revision"] = revision
            handle.attrs["threshold"] = threshold
            handle.attrs["stride_seconds"] = stride_s
            handle.attrs["kernel_seconds"] = kernel_s
            handle.attrs["analysis_t0"] = analysis_t0
        outputs = {
            "anomaly_found": anomaly_found,
            "top_segments": top_segments,
            "anomaly_artifact": relative_to_run(artifact, context.run_dir),
            "max_score": max_score,
            "median_score": float(np.median(scores)),
            "threshold": threshold,
            "threshold_calibrated": bool(calibration),
            "n_kernels": int(scores.size),
            "analysis_start": float(analysis_t0),
            "analysis_end": float(times[-1] + kernel_s / 2),
            "target_time": target_time,
            "target_score": target_score,
            "target_zscore": target_zscore,
            "target_rank": target_rank,
            "model": {
                "revision": revision,
                "source_commit": manifest.get("source_commit"),
                "embedder_sha256": manifest["files"]["embedder"]["sha256"],
                "metric_sha256": manifest["files"]["metric"]["sha256"],
                "device": device,
                "preprocessing": {
                    "sample_rate": sample_rate,
                    "kernel_length_seconds": kernel_s,
                    "psd_length_seconds": psd_length,
                    "fduration_seconds": fduration,
                    "fftlength_seconds": fftlength,
                    "highpass_hz": highpass,
                    "stride_seconds": stride_s,
                },
            },
            "simulated": False,
        }
        return AdapterOutcome(
            outputs=outputs,
            artifacts=[artifact],
            metadata={
                "adapter": self.name,
                "packages": package_versions("torch", "ml4gw", "h5py"),
                "model_dir": str(model_dir),
            },
            warnings=[] if calibration else [UNCALIBRATED_WARNING],
        )
