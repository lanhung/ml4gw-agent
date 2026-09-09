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
        if self.entrypoint == "catalog_lookup":
            return self._catalog_lookup(context)
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
        from .events import resolve

        raw_event = context.parameters["event"]
        event = str(raw_event)
        if not EVENT_PATTERN.fullmatch(event):
            raise AdapterError(f"unsupported event identifier: {event}")
        if event[:2].upper() == "GW":
            event = event.upper()
        elif event[:1].upper() in {"S", "G"} and not event[:2].upper() == "GW":
            event = event[0].upper() + event[1:]
        resolved = resolve(event, online=context.mode != "mock")
        if resolved["event_kind"] == "gwtc" and resolved["catalog_time"] is None:
            resolved["catalog_time"] = KNOWN_CATALOG_TIMES.get(event)
        output = {
            **resolved,
            "delegated_resolution": resolved["catalog_time"] is None,
            "simulated": context.mode == "mock",
        }
        artifact_dir = artifact_directory(context)
        artifact = artifact_dir / "event_info.json"
        artifact.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        return AdapterOutcome(outputs=output, artifacts=[artifact])

    @staticmethod
    def _catalog_lookup(context: ExecutionContext) -> AdapterOutcome:
        from .events import gwtc_lookup, resolve

        event = str(context.parameters["event"])
        if not EVENT_PATTERN.fullmatch(event):
            raise AdapterError(f"unsupported event identifier: {event}")
        if event[:2].upper() == "GW":
            event = event.upper()
        elif event[:1].upper() in {"S", "G"}:
            event = event[0].upper() + event[1:]
        # GraceDB is public and read-only, so the lookup is allowed in mock mode too
        res = resolve(event, online=True)
        rec = gwtc_lookup(res["gw_name"]) if res.get("gw_name") else None
        sources: list[str] = []
        if rec:
            sources.append(
                f"GWOSC catalog {rec.get('catalog')} via calibration/gwtc_events.json"
            )
        if res.get("resolution_source") == "gracedb":
            sources.append(f"GraceDB public API superevent {res.get('gracedb_id')}")
        utc = None
        if res.get("catalog_time") is not None:
            try:
                from astropy.time import Time

                utc = Time(res["catalog_time"], format="gps").utc.iso[:19] + " UTC"
            except Exception:  # noqa: BLE001 - astropy optional
                utc = None

        def fmt(value, unit="", digits=1):
            return "unknown" if value is None else f"{value:.{digits}f}{unit}"

        parts = []
        name = res.get("gw_name") or event
        if res.get("retracted"):
            parts.append(f"{event} was RETRACTED by the collaboration (ADVNO label).")
        tag = ""
        if res.get("gracedb_id") and res["gracedb_id"] != name:
            tag = f" (GraceDB {res['gracedb_id']})"
        when = f"merger time GPS {fmt(res.get('catalog_time'), digits=2)}"
        if utc:
            when += f" = {utc}"
        dets = (
            f", detectors {', '.join(res['instruments'])}"
            if res.get("instruments")
            else ""
        )
        far = res.get("far_per_year")
        far_text = f", FAR {far:.3g} per year" if far is not None else ""
        parts.append(f"{name}{tag}: {when}{dets}{far_text}.")
        if rec:
            m1 = fmt(rec.get("mass_1_source"), " Msun")
            m2 = fmt(rec.get("mass_2_source"), " Msun")
            mc = fmt(rec.get("chirp_mass_source"), " Msun")
            mt = fmt(rec.get("total_mass_source"), " Msun")
            dl = fmt(rec.get("luminosity_distance"), " Mpc", 0)
            snr = fmt(rec.get("network_matched_filter_snr"))
            pastro = rec.get("p_astro")
            ptxt = f", p_astro {pastro:.2f}" if pastro is not None else ""
            parts.append(
                f"Catalog {rec.get('catalog')}: source-frame masses {m1} and {m2}, "
                f"chirp mass {mc}, total mass {mt}, luminosity distance {dl}, "
                f"network SNR {snr}{ptxt}."
            )
        else:
            parts.append(
                "No GWTC catalog entry is shipped for this event; masses and distance "
                "come from parameter estimation, which this lookup does not run."
            )
        if res.get("resolution_note") and not res.get("retracted"):
            parts.append(f"Note: {res['resolution_note']}.")
        outputs = {
            "event": event,
            "gw_name": res.get("gw_name"),
            "gracedb_id": res.get("gracedb_id"),
            "catalog": rec.get("catalog") if rec else None,
            "catalog_time": res.get("catalog_time"),
            "utc": utc,
            "instruments": res.get("instruments"),
            "far_per_year": res.get("far_per_year"),
            "retracted": res.get("retracted"),
            "mass_1_source": rec.get("mass_1_source") if rec else None,
            "mass_2_source": rec.get("mass_2_source") if rec else None,
            "chirp_mass_source": rec.get("chirp_mass_source") if rec else None,
            "total_mass_source": rec.get("total_mass_source") if rec else None,
            "luminosity_distance": rec.get("luminosity_distance") if rec else None,
            "network_snr": rec.get("network_matched_filter_snr") if rec else None,
            "p_astro": rec.get("p_astro") if rec else None,
            "answer": " ".join(parts),
            "sources": sources,
            "simulated": False,
        }
        artifact_dir = artifact_directory(context)
        artifact = artifact_dir / "lookup.json"
        artifact.write_text(json.dumps(outputs, indent=2) + "\n", encoding="utf-8")
        return AdapterOutcome(
            outputs=outputs,
            artifacts=[artifact],
            metadata={
                "adapter": "builtin-catalog-lookup-v0.1",
                "question": context.parameters["question"],
            },
        )

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
        answers = [
            str(record.outputs["answer"])
            for record in context.records.values()
            if record.outputs and record.outputs.get("answer")
        ]
        lines.extend(["## Request", "", context.prompt, ""])
        if answers:
            lines.extend(["## Answer", ""] + answers + [""])
        lines.extend(
            [
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
