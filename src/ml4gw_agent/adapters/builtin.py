from __future__ import annotations

import json

from ..errors import AdapterError
from ..models import TaskStatus
from ..planning import EVENT_PATTERN
from .base import (
    AdapterOutcome,
    ExecutionContext,
    SkillAdapter,
    artifact_directory,
    relative_to_run,
)

KNOWN_CATALOG_TIMES = {
    "GW150914": 1126259462.4,
    "GW170817": 1187008882.4,
    "GW190521": 1242442967.4,
}


class BuiltinAdapter(SkillAdapter):
    def __init__(self, entrypoint: str):
        self.entrypoint = entrypoint

    def execute(self, context: ExecutionContext) -> AdapterOutcome:
        if self.entrypoint == "resolve_event":
            return self._resolve_event(context)
        if self.entrypoint == "generate_report":
            return self._generate_report(context)
        if self.entrypoint == "reconcile_detections":
            return self._reconcile_detections(context)
        raise AdapterError(f"unknown builtin entrypoint: {self.entrypoint}")

    @staticmethod
    def _reconcile_detections(context: ExecutionContext) -> AdapterOutcome:
        """Route on the Aframe/GWAK outcome pair; never promote GWAK-only to PE."""
        aframe_id = str(context.parameters.get("aframe_task", "run_aframe"))
        gwak_id = str(context.parameters.get("gwak_task", "run_gwak"))

        def flag(task_id: str, key: str) -> bool | None:
            record = context.records.get(task_id)
            if record is None or record.status != TaskStatus.COMPLETED:
                return None
            value = record.outputs.get(key)
            return bool(value) if value is not None else None

        aframe = flag(aframe_id, "candidate_found")
        gwak = flag(gwak_id, "anomaly_found")
        if aframe is None or gwak is None:
            route, follow_up = (
                "undetermined",
                (
                    "one detection route did not complete; rerun or inspect the "
                    "failed task before drawing conclusions"
                ),
            )
        elif aframe and gwak:
            route, follow_up = (
                "consistent_candidate",
                (
                    "both routes fired: AMPLFI parameter estimation on the Aframe "
                    "candidate and GWAK morphology review of the same time"
                ),
            )
        elif aframe:
            route, follow_up = (
                "aframe_only",
                (
                    "modelled search fired without an unmodeled anomaly: proceed "
                    "with AMPLFI, note that GWAK did not flag the segment"
                ),
            )
        elif gwak:
            route, follow_up = (
                "gwak_only",
                (
                    "unmodeled anomaly without a modelled candidate: morphology "
                    "diagnostics (time-frequency, glitch classification) are the "
                    "next step; AMPLFI is not run because there is no CBC "
                    "coalescence time to condition on"
                ),
            )
        else:
            route, follow_up = (
                "consistent_null",
                ("neither route fired within the analysed window"),
            )
        simulated = any(
            bool(context.records[task_id].outputs.get("simulated"))
            for task_id in (aframe_id, gwak_id)
            if task_id in context.records
        )
        return AdapterOutcome(
            outputs={
                "route": route,
                "aframe_candidate": aframe,
                "gwak_anomaly": gwak,
                "follow_up": follow_up,
                "parameter_estimation_recommended": bool(aframe),
                "simulated": simulated,
            },
            metadata={"adapter": "builtin-reconcile-v0.3"},
        )

    @staticmethod
    def _resolve_event(context: ExecutionContext) -> AdapterOutcome:
        raw_event = context.parameters["event"]
        event = str(raw_event)
        if not EVENT_PATTERN.fullmatch(event):
            raise AdapterError(f"unsupported event identifier: {event}")

        if event[:2].upper() == "GW":
            event = event.upper()
            kind = "gwtc"
            catalog_time = KNOWN_CATALOG_TIMES.get(event)
        elif event[:1].upper() == "S":
            event = "S" + event[1:]
            kind = "gracedb_superevent"
            catalog_time = None
        elif event[:1].upper() == "G":
            event = "G" + event[1:]
            kind = "gracedb_event"
            catalog_time = None
        else:
            kind = "gps"
            catalog_time = float(event)

        output = {
            "event": event,
            "event_kind": kind,
            "catalog_time": catalog_time,
            "delegated_resolution": catalog_time is None,
            "simulated": context.mode == "mock",
        }
        artifact_dir = artifact_directory(context)
        artifact = artifact_dir / "event_info.json"
        artifact.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        return AdapterOutcome(outputs=output, artifacts=[artifact])

    @staticmethod
    def _generate_report(context: ExecutionContext) -> AdapterOutcome:
        title = context.parameters.get("title", "ML4GW Agent run report")
        is_mock = context.mode == "mock"
        lines = [f"# {title}", ""]
        if is_mock:
            lines.extend(
                [
                    "> **SIMULATED ORCHESTRATION OUTPUT — NOT A SCIENTIFIC RESULT.**",
                    "> Values below exercise planning, execution, validation, and "
                    "provenance only.",
                    "",
                ]
            )
        lines.extend(
            [
                "## Request",
                "",
                context.prompt,
                "",
                "## Workflow status",
                "",
                "| Task | Skill | Status |",
                "|---|---|---|",
            ]
        )
        for record in context.records.values():
            status = record.status.value
            if record.task_id == context.task.id:
                # The report can only exist if this adapter reached its final write.
                # Present the expected terminal state; the manifest remains the
                # authoritative checkpoint during the write itself.
                status = TaskStatus.COMPLETED.value
            lines.append(f"| `{record.task_id}` | `{record.skill}` | {status} |")

        lines.extend(["", "## Recorded outputs", ""])
        for record in context.records.values():
            if not record.outputs:
                continue
            lines.extend(
                [
                    f"### {record.task_id}",
                    "",
                    "```json",
                    json.dumps(record.outputs, indent=2, sort_keys=True),
                    "```",
                    "",
                ]
            )

        lines.extend(
            [
                "## Interpretation boundary",
                "",
                "The report summarizes adapter outputs and validation state. It does "
                "not replace detector-characterization review, independent pipeline "
                "checks, "
                "or collaboration publication policy.",
                "",
            ]
        )
        report_path = context.run_dir / "report.md"
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return AdapterOutcome(
            outputs={
                "report_path": relative_to_run(report_path, context.run_dir),
                "simulated": is_mock,
            },
            artifacts=[report_path],
        )
