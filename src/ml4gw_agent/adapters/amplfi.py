"""Real ``amplfi.pe`` adapter over ``buoy.models.Amplfi``.

Given a validated coalescence time (normally a typed reference to the
Aframe output) the adapter selects the published HL or HLV AMPLFI model by
detector set, draws posterior samples, writes Buoy's ``posterior_samples.dat``
plus a FITS sky map, and summarizes credible intervals from the samples.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

REQUIRED_MODULES = ("buoy", "torch", "ml4gw", "amplfi")
AMPLFI_REPO_ID = "ML4GW/amplfi"
MODEL_FILES = {
    ("H1", "L1"): ("amplfi-hl.ckpt", "amplfi-hl-config.yaml"),
    ("H1", "L1", "V1"): ("amplfi-hlv.ckpt", "amplfi-hlv-config.yaml"),
}
SUMMARY_PARAMETERS = (
    "chirp_mass",
    "chirp_mass_source",
    "mass_ratio",
    "mass_1",
    "mass_2",
    "distance",
    "inclination",
    "ra",
    "dec",
)
CREDIBLE_PERCENTILES = (5.0, 50.0, 95.0)


@dataclass(frozen=True)
class AmplfiBackend:
    amplfi_class: Any
    to_tensor: Any
    seed: Any
    write_skymap: Any


def _missing() -> list[str]:
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def _write_fits(table: Any, path: Path) -> None:
    from astropy import io

    io.fits.table_to_hdu(table).writeto(str(path), overwrite=True)


def load_amplfi_backend() -> AmplfiBackend:
    missing = _missing()
    if missing:
        raise AdapterUnavailableError(
            f"the AMPLFI adapter requires {missing}; install with "
            "'uv sync --extra buoy'"
        )
    import torch
    from buoy.models import Amplfi

    return AmplfiBackend(
        amplfi_class=Amplfi,
        to_tensor=lambda array: torch.as_tensor(np.asarray(array)).double(),
        seed=torch.manual_seed,
        write_skymap=_write_fits,
    )


def credible_intervals(posterior: Any) -> dict[str, dict[str, float]]:
    columns = getattr(posterior, "columns", None)
    names = list(columns) if columns is not None else list(posterior.keys())
    summary: dict[str, dict[str, float]] = {}
    for name in SUMMARY_PARAMETERS:
        if name not in names:
            continue
        values = np.asarray(posterior[name], dtype="f8")
        values = values[np.isfinite(values)]
        if values.size == 0:
            continue
        low, median, high = np.percentile(values, CREDIBLE_PERCENTILES)
        summary[name] = {
            "p5": float(low),
            "median": float(median),
            "p95": float(high),
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
        }
    return summary


class AmplfiAdapter(SkillAdapter):
    name = "amplfi-buoy-v0.2"

    def probe(self) -> str:
        missing = _missing()
        return "available" if not missing else f"missing: {', '.join(missing)}"

    def preflight(self, context: ExecutionContext) -> list[str]:
        missing = _missing()
        if missing:
            raise AdapterUnavailableError(
                f"the AMPLFI adapter requires {missing}; install with "
                "'uv sync --extra buoy'"
            )
        ifos = tuple(str(ifo) for ifo in context.parameters.get("ifos", []))
        if ifos not in MODEL_FILES:
            raise AdapterError(
                f"published AMPLFI models support detector sets "
                f"{[list(key) for key in MODEL_FILES]}; got {list(ifos)}"
            )
        warnings: list[str] = []
        device = context.parameters.get("device", "cuda")
        if device == "cuda" and shutil.which("nvidia-smi") is None:
            warnings.append(
                "CUDA was requested for AMPLFI but nvidia-smi is not visible"
            )
        if context.parameters.get("model_revision") == "UNPINNED":
            warnings.append("AMPLFI model revision is not pinned")
        return warnings

    def describe_invocation(
        self, context: ExecutionContext
    ) -> tuple[list[str] | None, dict[str, Any]]:
        ifos = tuple(str(ifo) for ifo in context.parameters.get("ifos", []))
        weights, config = MODEL_FILES.get(ifos, ("unknown", "unknown"))
        return None, {
            "adapter": self.name,
            "python_call": "buoy.models.Amplfi.__call__",
            "repo_id": AMPLFI_REPO_ID,
            "revision": context.parameters.get("model_revision"),
            "model_weights": weights,
            "model_config": config,
            "device": context.parameters.get("device", "cuda"),
        }

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        params = context.parameters
        backend = load_amplfi_backend()
        strain = read_strain(
            resolve_artifact(str(params["strain_artifact"]), context.run_dir)
        )
        ifos = tuple(str(ifo) for ifo in params["ifos"])
        if ifos not in MODEL_FILES:
            raise AdapterError(f"unsupported detector set for AMPLFI: {list(ifos)}")
        weights, config = MODEL_FILES[ifos]
        revision = str(params["model_revision"])
        device = str(params.get("device", "cuda"))
        samples = int(params.get("samples", 20_000))
        coalescence_time = float(params["coalescence_time"])
        if not (strain.t0 < coalescence_time < strain.gps_end):
            raise AdapterError(
                f"coalescence time {coalescence_time} is outside the strain "
                f"interval [{strain.t0}, {strain.gps_end}]"
            )
        seed = params.get("seed")
        if seed is not None:
            backend.seed(int(seed))

        try:
            model = backend.amplfi_class(
                model_weights=weights, config=config, device=device, revision=revision
            )
        except Exception as exc:
            raise AdapterError(
                f"could not load AMPLFI {weights} at revision {revision}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if abs(float(model.sample_rate) - strain.sample_rate) > 1e-9:
            raise AdapterError(
                f"strain sample rate {strain.sample_rate:g} Hz does not match the "
                f"AMPLFI model's {float(model.sample_rate):g} Hz"
            )

        data = backend.to_tensor(strain.stacked(list(ifos)))
        try:
            result = model(
                data=data, t0=strain.t0, tc=coalescence_time, samples_per_event=samples
            )
        except Exception as exc:
            raise AdapterError(
                f"AMPLFI inference failed: {type(exc).__name__}: {exc}"
            ) from exc

        artifact_dir = artifact_directory(context)
        posterior_path = artifact_dir / "posterior_samples.dat"
        try:
            result.save_posterior_samples(filename=str(posterior_path))
        except Exception as exc:
            raise AdapterError(
                f"could not write posterior samples: {type(exc).__name__}: {exc}"
            ) from exc
        summary = credible_intervals(result.posterior)
        if not summary:
            raise AdapterError("AMPLFI posterior contains no summarizable parameters")
        first = next(iter(summary))
        n_samples = int(np.asarray(result.posterior[first]).shape[0])

        suffix = "".join(ifo[0] for ifo in ifos)
        skymap_path = artifact_dir / f"amplfi_{suffix}.fits"
        try:
            table = result.to_skymap(
                use_distance=bool(params.get("use_distance", True)),
                adaptive=True,
                min_samples_per_pix_dist=int(params.get("min_samples_per_pix", 5)),
                metadata={"INSTRUME": ",".join(ifos)},
            )
            backend.write_skymap(table, skymap_path)
        except Exception as exc:
            raise AdapterError(
                f"sky map generation failed: {type(exc).__name__}: {exc}"
            ) from exc

        summary_path = artifact_dir / "credible_intervals.json"
        summary_path.write_text(
            json.dumps(
                {
                    "coalescence_time": coalescence_time,
                    "ifos": list(ifos),
                    "n_samples": n_samples,
                    "percentiles": list(CREDIBLE_PERCENTILES),
                    "parameters": summary,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        outputs = {
            "posterior_artifact": relative_to_run(posterior_path, context.run_dir),
            "credible_intervals": summary,
            "skymap_artifact": relative_to_run(skymap_path, context.run_dir),
            "summary_artifact": relative_to_run(summary_path, context.run_dir),
            "n_samples": n_samples,
            "coalescence_time": coalescence_time,
            "ifos": list(ifos),
            "model": {
                "repo_id": AMPLFI_REPO_ID,
                "revision": revision,
                "weights": weights,
                "config": config,
                "device": device,
                "sample_rate": float(model.sample_rate),
                "kernel_length": getattr(model, "kernel_length", None),
                "psd_length": getattr(model, "psd_length", None),
                "inference_params": list(getattr(model, "inference_params", []) or []),
            },
            "simulated": False,
        }
        metadata = {
            "adapter": self.name,
            "packages": package_versions(
                "ml4gw-buoy", "amplfi", "ml4gw", "torch", "ligo.skymap"
            ),
        }
        return AdapterOutcome(
            outputs=outputs,
            artifacts=[posterior_path, skymap_path, summary_path],
            metadata=metadata,
        )
