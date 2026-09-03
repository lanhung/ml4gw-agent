"""Real ``deepclean.check_applicability`` adapter.

DeepClean subtracts low-frequency noise using auxiliary witness channels. Its
applicability is decided from evidence the agent already holds, without
touching DeepClean itself:

1. the strain artifact must come from a source that can also serve witness
   channels (public GWOSC strain cannot; only authenticated LDG frames can);
2. a reviewed coupling configuration (detector, frequency band, witness
   channel list, sample rate, immutable weights) must exist for every
   detector in ``deepclean_support.json``;
3. that configuration's observing-run interval must cover the data.

Any failed condition yields ``applicable: false`` with the reason, so the
plan skips cleaning rather than fabricating witness data or model support.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from .base import (
    AdapterOutcome,
    ExecutionContext,
    SkillAdapter,
    artifact_directory,
)
from .strain_io import read_strain, resolve_artifact

PUBLIC_SOURCES = {"gwosc"}


def load_support_table() -> dict[str, Any]:
    path = resources.files("ml4gw_agent.calibration").joinpath("deepclean_support.json")
    return json.loads(path.read_text(encoding="utf-8"))


def applicability(
    *,
    source: str,
    ifos: list[str],
    t0: float,
    gps_end: float,
    table: dict[str, Any],
) -> tuple[bool, list[str], dict[str, Any] | None]:
    """Evaluate the three conditions; returns (applicable, reasons, config)."""
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


class DeepCleanApplicabilityAdapter(SkillAdapter):
    name = "deepclean-applicability-v0.3"

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
        artifact = artifact_directory(context) / "deepclean_applicability.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "event": str(params["event"]),
            "strain_source": strain.source,
            "ifos": ifos,
            "gps_start": strain.t0,
            "gps_end": strain.gps_end,
            "applicable": applicable,
            "reasons": reasons,
            "configuration": config,
        }
        artifact.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        outputs = {
            "applicable": applicable,
            "reasons": reasons,
            "witness_artifact": None,
            "coupling_config": (str(config.get("coupling_config")) if config else None),
            "model_revision": str(config["model_revision"]) if config else None,
            "simulated": False,
        }
        return AdapterOutcome(
            outputs=outputs,
            artifacts=[artifact],
            metadata={
                "adapter": self.name,
                "configurations_reviewed": len(table.get("configurations", [])),
            },
        )
