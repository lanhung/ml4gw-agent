from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import AdapterError
from .base import (
    AdapterOutcome,
    ExecutionContext,
    SkillAdapter,
    artifact_directory,
    relative_to_run,
)

MOCK_NOTICE = "SIMULATED FOR ORCHESTRATION TESTING; NOT A SCIENTIFIC RESULT"
MOCK_EVENT_TIMES = {
    "GW150914": 1126259462.4,
    "GW170817": 1187008882.4,
    "GW190521": 1242442967.4,
}


def _event_time(event: str) -> float:
    if event in MOCK_EVENT_TIMES:
        return MOCK_EVENT_TIMES[event]
    try:
        return float(event)
    except ValueError:
        return 1_000_000_000.0


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


class MockAdapter(SkillAdapter):
    """Deterministic fake backend used only to test orchestration mechanics."""

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        handlers = {
            "data.fetch": self._data_fetch,
            "data.inspect": self._data_inspect,
            "buoy.analyze": self._buoy_analyze,
            "aframe.detect": self._aframe_detect,
            "amplfi.pe": self._amplfi_pe,
            "gwak.scan": self._gwak_scan,
            "deepclean.check_applicability": self._deepclean_check,
            "deepclean.clean": self._deepclean_clean,
        }
        try:
            handler = handlers[context.skill.name]
        except KeyError as exc:
            raise AdapterError(f"no mock adapter for {context.skill.name}") from exc
        outcome = handler(context)
        outcome.metadata.update(
            {
                "adapter": "deterministic-mock-v0.1",
                "scientific_result": False,
                "notice": MOCK_NOTICE,
            }
        )
        return outcome

    @staticmethod
    def _data_fetch(context: ExecutionContext) -> AdapterOutcome:
        event = str(context.parameters["event"])
        center = _event_time(event)
        window = float(context.parameters.get("window_seconds", 64))
        artifact_dir = artifact_directory(context)
        strain = _write_json(
            artifact_dir / "mock_strain.json",
            {
                "notice": MOCK_NOTICE,
                "event": event,
                "ifos": context.parameters["ifos"],
                "sample_rate": context.parameters.get("sample_rate", 2048),
            },
        )
        output = {
            "strain_artifact": relative_to_run(strain, context.run_dir),
            "ifos": context.parameters["ifos"],
            "gps_start": center - window / 2,
            "gps_end": center + window / 2,
            "source": "deterministic-mock",
            "simulated": True,
        }
        return AdapterOutcome(outputs=output, artifacts=[strain])

    @staticmethod
    def _data_inspect(context: ExecutionContext) -> AdapterOutcome:
        artifact_dir = artifact_directory(context)
        diagnostics = _write_json(
            artifact_dir / "mock_quality_diagnostics.json",
            {
                "notice": MOCK_NOTICE,
                "quality_passed": True,
                "checks": ["finite", "duration", "detector-availability"],
            },
        )
        return AdapterOutcome(
            outputs={
                "quality_passed": True,
                "available_ifos": ["H1", "L1"],
                "diagnostics_artifact": relative_to_run(diagnostics, context.run_dir),
                "issues": [],
                "simulated": True,
            },
            artifacts=[diagnostics],
        )

    @staticmethod
    def _buoy_analyze(context: ExecutionContext) -> AdapterOutcome:
        event = str(context.parameters["event"])
        artifact_dir = artifact_directory(context) / "buoy" / event
        aframe = _write_json(
            artifact_dir / "data" / "mock_aframe_outputs.json",
            {
                "notice": MOCK_NOTICE,
                "detection_statistic": 0.98,
                "predicted_coalescence_time": _event_time(event),
            },
        )
        posterior = _write_json(
            artifact_dir / "data" / "mock_posterior_samples.json",
            {
                "notice": MOCK_NOTICE,
                "samples": context.parameters.get("samples_per_event", 20_000),
                "summary": {"chirp_mass": "simulated", "distance": "simulated"},
            },
        )
        summary = artifact_dir / "summary.html"
        summary.write_text(
            "<html><body><strong>SIMULATED — NOT A SCIENTIFIC "
            "RESULT</strong></body></html>\n",
            encoding="utf-8",
        )
        return AdapterOutcome(
            outputs={
                "event": event,
                "output_directory": relative_to_run(artifact_dir, context.run_dir),
                "aframe_output": relative_to_run(aframe, context.run_dir),
                "posterior_samples": relative_to_run(posterior, context.run_dir),
                "plots": [],
                "summary_html": relative_to_run(summary, context.run_dir),
                "detection_statistic": 0.98,
                "predicted_coalescence_time": _event_time(event),
                "simulated": True,
            },
            artifacts=[aframe, posterior, summary],
        )

    @staticmethod
    def _aframe_detect(context: ExecutionContext) -> AdapterOutcome:
        event = context.parameters.get("event", "event")
        center = _event_time(str(event))
        if "fetch_data" in context.records:
            fetch = context.records["fetch_data"].outputs
            center = (float(fetch["gps_start"]) + float(fetch["gps_end"])) / 2
        artifact_dir = artifact_directory(context)
        artifact = _write_json(
            artifact_dir / "mock_aframe_output.json",
            {
                "notice": MOCK_NOTICE,
                "candidate_found": True,
                "predicted_coalescence_time": center,
                "detection_statistic": 0.98,
            },
        )
        return AdapterOutcome(
            outputs={
                "candidate_found": True,
                "candidate_times": [center],
                "predicted_coalescence_time": center,
                "detection_statistic": 0.98,
                "output_artifact": relative_to_run(artifact, context.run_dir),
                "simulated": True,
            },
            artifacts=[artifact],
        )

    @staticmethod
    def _amplfi_pe(context: ExecutionContext) -> AdapterOutcome:
        artifact_dir = artifact_directory(context)
        posterior = _write_json(
            artifact_dir / "mock_posterior.json",
            {
                "notice": MOCK_NOTICE,
                "coalescence_time": context.parameters["coalescence_time"],
                "samples": context.parameters.get("samples", 20_000),
            },
        )
        skymap = _write_json(
            artifact_dir / "mock_skymap.json",
            {"notice": MOCK_NOTICE, "pixels": "not generated"},
        )
        return AdapterOutcome(
            outputs={
                "posterior_artifact": relative_to_run(posterior, context.run_dir),
                "credible_intervals": {
                    "notice": MOCK_NOTICE,
                    "chirp_mass": ["simulated-low", "simulated-high"],
                },
                "skymap_artifact": relative_to_run(skymap, context.run_dir),
                "simulated": True,
            },
            artifacts=[posterior, skymap],
        )

    @staticmethod
    def _gwak_scan(context: ExecutionContext) -> AdapterOutcome:
        artifact_dir = artifact_directory(context)
        artifact = _write_json(
            artifact_dir / "mock_gwak_output.json",
            {"notice": MOCK_NOTICE, "anomaly_found": False, "top_segments": []},
        )
        return AdapterOutcome(
            outputs={
                "anomaly_found": False,
                "top_segments": [],
                "anomaly_artifact": relative_to_run(artifact, context.run_dir),
                "simulated": True,
            },
            artifacts=[artifact],
        )

    @staticmethod
    def _deepclean_check(context: ExecutionContext) -> AdapterOutcome:
        return AdapterOutcome(
            outputs={
                "applicable": False,
                "reasons": [
                    "Mock public-data scenario has no verified witness channels.",
                    "No reviewed coupling configuration or immutable weights were "
                    "supplied.",
                ],
                "witness_artifact": None,
                "coupling_config": None,
                "model_revision": None,
                "simulated": True,
            }
        )

    @staticmethod
    def _deepclean_clean(context: ExecutionContext) -> AdapterOutcome:
        artifact_dir = artifact_directory(context)
        cleaned = _write_json(
            artifact_dir / "mock_cleaned_strain.json", {"notice": MOCK_NOTICE}
        )
        diagnostics = _write_json(
            artifact_dir / "mock_subtraction_diagnostics.json",
            {"notice": MOCK_NOTICE},
        )
        return AdapterOutcome(
            outputs={
                "cleaned_strain_artifact": relative_to_run(cleaned, context.run_dir),
                "subtraction_diagnostics": relative_to_run(
                    diagnostics, context.run_dir
                ),
                "applicable": True,
                "simulated": True,
            },
            artifacts=[cleaned, diagnostics],
        )
