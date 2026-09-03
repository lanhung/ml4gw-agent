"""Real ``deepclean.check_applicability`` and ``deepclean.clean`` adapters.

DeepClean subtracts narrow-band detector noise predicted from auxiliary
witness channels. Applicability is decided from evidence the agent already
holds, and the witnesses are fetched as part of that check:

1. the strain artifact must come from a source that can also serve witness
   channels (public GWOSC strain cannot; authenticated LDG/NDS2 data can);
2. a reviewed coupling configuration (detector, frequency band, witness
   channel list, sample rate, immutable weights) must exist for every
   detector in ``deepclean_support.json``;
3. that configuration's observing-run interval must cover the data;
4. the witness channels must actually be retrievable for the interval.

Any failed condition yields ``applicable: false`` with the reason, so the
plan skips cleaning rather than fabricating witness data or model support.

``deepclean.clean`` runs the shipped autoencoder (see ``deepclean_model``)
on the fetched witnesses, subtracts the band-limited noise prediction from
the strain at its native sample rate, and records in-band / out-of-band
ASD ratios. The prediction depends on witness channels only, and the
subtraction is confined to the configured band, so a gravitational-wave
signal in the strain cannot leak into the estimate; the out-of-band ratio
is checked to stay at unity as a guard.
"""

from __future__ import annotations

import hashlib
import json
import os
from importlib import resources
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
from .deepclean_model import clean_strain, load_weights, resample
from .strain_io import StrainData, read_strain, resolve_artifact, write_strain

PUBLIC_SOURCES = {"gwosc"}


def load_support_table() -> dict[str, Any]:
    path = resources.files("ml4gw_agent.calibration").joinpath("deepclean_support.json")
    return json.loads(path.read_text(encoding="utf-8"))


def default_model_dir() -> Path:
    env = os.environ.get("ML4GW_DEEPCLEAN_MODEL_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "models" / "deepclean"


def applicability(
    *,
    source: str,
    ifos: list[str],
    t0: float,
    gps_end: float,
    table: dict[str, Any],
) -> tuple[bool, list[str], dict[str, Any] | None]:
    """Evaluate the three static conditions; returns (applicable, reasons, config)."""
    reasons: list[str] = []
    if source in PUBLIC_SOURCES:
        reasons.append(
            f"strain source '{source}' is public h(t) only; DeepClean needs "
            "auxiliary witness channels, which are available solely through "
            "authenticated LDG frames"
        )
    configs = table.get("configurations", [])
    chosen: dict[str, Any] | None = None
    for ifo in ifos:
        matches = [
            cfg
            for cfg in configs
            if cfg.get("ifo") == ifo
            and float(cfg.get("gps_start", 0)) <= t0
            and gps_end <= float(cfg.get("gps_end", float("inf")))
            and cfg.get("model_revision")
            and cfg.get("witness_channels")
        ]
        if not matches:
            reasons.append(
                f"no reviewed DeepClean coupling configuration covers {ifo} for "
                f"[{t0}, {gps_end}] (witness channels, frequency band, sample "
                "rate, and immutable weights must all be recorded)"
            )
        elif chosen is None:
            chosen = matches[0]
    return (not reasons, reasons, chosen if not reasons else None)


# --- witness artifacts ------------------------------------------------------


def fetch_witness(ifo: str, channel: str, start: float, end: float):
    """Return (data, t0, sample_rate) for one witness channel via NDS2."""
    from .ldg import fetch_nds2_strain

    series, _ = fetch_nds2_strain(ifo, start, end, channel=channel)
    return (
        np.asarray(series.value, dtype="f8"),
        float(series.t0.value),
        float(series.sample_rate.value),
    )


def write_witnesses(path: Path, channels: dict[str, tuple[np.ndarray, float, float]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as handle:
        for name, (data, t0, rate) in channels.items():
            dataset = handle.create_dataset(name, data=np.asarray(data, dtype="f8"))
            dataset.attrs["t0"] = float(t0)
            dataset.attrs["sample_rate"] = float(rate)
    return path


def read_witnesses(path: Path) -> dict[str, tuple[np.ndarray, float, float]]:
    if not path.is_file():
        raise AdapterError(f"witness artifact does not exist: {path}")
    with h5py.File(path, "r") as handle:
        return {
            name: (
                np.asarray(handle[name][:], dtype="f8"),
                float(handle[name].attrs["t0"]),
                float(handle[name].attrs["sample_rate"]),
            )
            for name in handle.keys()
        }


class DeepCleanApplicabilityAdapter(SkillAdapter):
    name = "deepclean-applicability-v0.4"

    def probe(self) -> str:
        return "available"

    def describe_invocation(
        self, context: ExecutionContext
    ) -> tuple[list[str] | None, dict[str, Any]]:
        return None, {
            "adapter": self.name,
            "support_table": "ml4gw_agent/calibration/deepclean_support.json",
        }

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        params = context.parameters
        strain = read_strain(
            resolve_artifact(str(params["strain_artifact"]), context.run_dir)
        )
        ifos = [str(ifo) for ifo in params["ifos"]]
        table = load_support_table()
        applicable, reasons, config = applicability(
            source=strain.source,
            ifos=ifos,
            t0=strain.t0,
            gps_end=strain.gps_end,
            table=table,
        )
        artifact_dir = artifact_directory(context)
        witness_path: Path | None = None
        if applicable and config is not None:
            witness_path = artifact_dir / "witnesses.hdf5"
            try:
                channels = {
                    channel: fetch_witness(
                        str(config["ifo"]),
                        channel,
                        np.floor(strain.t0),
                        np.ceil(strain.gps_end),
                    )
                    for channel in config["witness_channels"]
                }
                write_witnesses(witness_path, channels)
            except Exception as exc:  # noqa: BLE001 - any fetch failure is a reason
                applicable = False
                witness_path = None
                reasons.append(
                    f"witness channels {config['witness_channels']} could not be "
                    f"fetched for [{strain.t0}, {strain.gps_end}]: {exc}"
                )
        artifact = artifact_dir / "deepclean_applicability.json"
        payload = {
            "event": str(params["event"]),
            "strain_source": strain.source,
            "ifos": ifos,
            "gps_start": strain.t0,
            "gps_end": strain.gps_end,
            "applicable": applicable,
            "reasons": reasons,
            "configuration": config if applicable else None,
            "witness_artifact": (
                relative_to_run(witness_path, context.run_dir) if witness_path else None
            ),
        }
        artifact.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        outputs = {
            "applicable": applicable,
            "reasons": reasons,
            "witness_artifact": payload["witness_artifact"],
            "coupling_config": (
                str(config.get("coupling_config")) if applicable and config else None
            ),
            "model_revision": (
                str(config["model_revision"]) if applicable and config else None
            ),
            "ifo": str(config["ifo"]) if applicable and config else None,
            "simulated": False,
        }
        artifacts = [artifact] + ([witness_path] if witness_path else [])
        return AdapterOutcome(
            outputs=outputs,
            artifacts=artifacts,
            metadata={
                "adapter": self.name,
                "configurations_reviewed": len(table.get("configurations", [])),
            },
        )


# --- cleaning ---------------------------------------------------------------


def load_coupling(model_dir: Path, coupling_config: str, model_revision: str):
    """Return (record, weights_path) after verifying the immutable revision."""
    record_path = (model_dir / coupling_config).resolve()
    if not record_path.is_file():
        raise AdapterUnavailableError(
            f"DeepClean coupling configuration not found: {record_path} (set "
            "ML4GW_DEEPCLEAN_MODEL_DIR to the directory holding the trained models)"
        )
    record = json.loads(record_path.read_text(encoding="utf-8"))
    weights_path = record_path.parent / str(record["weights_file"])
    if not weights_path.is_file():
        raise AdapterUnavailableError(f"DeepClean weights missing: {weights_path}")
    digest = hashlib.sha256(weights_path.read_bytes()).hexdigest()
    if digest != model_revision or digest != record.get("weights_sha256"):
        raise AdapterError(
            "DeepClean weights do not match the pinned revision: "
            f"file {digest[:12]}, requested {str(model_revision)[:12]}, "
            f"record {str(record.get('weights_sha256'))[:12]}"
        )
    return record, weights_path


def align_witnesses(
    witnesses: dict[str, tuple[np.ndarray, float, float]],
    channels: list[str],
    t0: float,
    n_samples: int,
    rate: float,
) -> np.ndarray:
    """Stack the named channels resampled to ``rate`` and cropped to the strain."""
    rows = []
    for channel in channels:
        if channel not in witnesses:
            raise AdapterError(f"witness artifact lacks channel {channel}")
        data, w_t0, w_rate = witnesses[channel]
        resampled = resample(data, w_rate, rate)
        offset = int(round((t0 - w_t0) * rate))
        if offset < 0 or offset + n_samples > resampled.shape[0]:
            raise AdapterError(
                f"witness {channel} covers [{w_t0}, {w_t0 + len(data) / w_rate}] "
                f"but the strain needs [{t0}, {t0 + n_samples / rate}]"
            )
        rows.append(resampled[offset : offset + n_samples])
    return np.stack(rows)


class DeepCleanCleanAdapter(SkillAdapter):
    name = "deepclean-clean-v0.1"

    def probe(self) -> str:
        return "available"

    def describe_invocation(
        self, context: ExecutionContext
    ) -> tuple[list[str] | None, dict[str, Any]]:
        return None, {"adapter": self.name, "model_dir": str(default_model_dir())}

    @staticmethod
    def _device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:  # pragma: no cover - exercised only without torch
            return "cpu"

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        params = context.parameters
        run_dir = context.run_dir
        strain = read_strain(resolve_artifact(str(params["strain_artifact"]), run_dir))
        witnesses = read_witnesses(
            resolve_artifact(str(params["witness_artifact"]), run_dir)
        )
        record, weights_path = load_coupling(
            default_model_dir(),
            str(params["coupling_config"]),
            str(params["model_revision"]),
        )
        ifo = str(params.get("ifo") or record["ifo"])
        if ifo != record["ifo"]:
            raise AdapterError(
                f"coupling configuration is for {record['ifo']}, not {ifo}"
            )
        if ifo not in strain.series:
            raise AdapterError(f"strain artifact lacks detector {ifo}: {strain.ifos}")
        weights = load_weights(weights_path)
        model_rate = float(weights["config"]["sample_rate"])
        native = strain.series[ifo]
        strain_model = resample(native, strain.sample_rate, model_rate)
        witness_stack = align_witnesses(
            witnesses,
            list(record["witness_channels"]),
            strain.t0,
            strain_model.shape[0],
            model_rate,
        )
        cleaned_model, metrics = clean_strain(
            strain_model, witness_stack, weights, device=self._device()
        )
        noise = resample(strain_model - cleaned_model, model_rate, strain.sample_rate)
        n = min(noise.shape[0], native.shape[0])
        cleaned = native.copy()
        cleaned[:n] = native[:n] - noise[:n]
        improved = metrics["in_band_asd_ratio"] < 1.0
        preserved = abs(metrics["out_of_band_asd_ratio"] - 1.0) < 0.05
        applicable = bool(improved and preserved)

        artifact_dir = artifact_directory(context)
        series = dict(strain.series)
        series[ifo] = cleaned
        cleaned_path = write_strain(
            artifact_dir / "cleaned_strain.hdf5",
            StrainData(
                ifos=list(strain.ifos),
                series=series,
                t0=strain.t0,
                sample_rate=strain.sample_rate,
                event_time=strain.event_time,
                source=strain.source,
                event=strain.event,
                extra_attrs={
                    "deepclean_ifo": ifo,
                    "deepclean_model_revision": str(params["model_revision"]),
                    "deepclean_band_hz": [record["freq_low"], record["freq_high"]],
                },
            ),
        )
        diagnostics = {
            "ifo": ifo,
            "strain_source": strain.source,
            "gps_start": strain.t0,
            "gps_end": strain.gps_end,
            "sample_rate": strain.sample_rate,
            "model_sample_rate": model_rate,
            "witness_channels": list(record["witness_channels"]),
            "coupling_config": str(params["coupling_config"]),
            "model_revision": str(params["model_revision"]),
            "training_record": {
                key: record.get(key)
                for key in (
                    "gps_start",
                    "gps_end",
                    "train_seconds",
                    "best_val_asd_ratio",
                    "held_out_metrics",
                    "reference",
                )
            },
            "asd_ratios": metrics,
            "improved_in_band": improved,
            "out_of_band_preserved": preserved,
            "applicable": applicable,
            "signal_preservation": (
                "the noise estimate is a function of the witness channels only "
                "and is band-limited before subtraction; strain content outside "
                f"[{record['freq_low']}, {record['freq_high']}] Hz is untouched "
                "(out-of-band ASD ratio checked to be unity)"
            ),
        }
        diagnostics_path = artifact_dir / "subtraction_diagnostics.json"
        diagnostics_path.write_text(
            json.dumps(diagnostics, indent=2) + "\n", encoding="utf-8"
        )
        return AdapterOutcome(
            outputs={
                "cleaned_strain_artifact": relative_to_run(cleaned_path, run_dir),
                "subtraction_diagnostics": relative_to_run(diagnostics_path, run_dir),
                "applicable": applicable,
                "simulated": False,
            },
            artifacts=[cleaned_path, diagnostics_path],
            metadata={
                "adapter": self.name,
                "in_band_asd_ratio": metrics["in_band_asd_ratio"],
                "out_of_band_asd_ratio": metrics["out_of_band_asd_ratio"],
            },
        )
