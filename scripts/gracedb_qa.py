#!/usr/bin/env python3
"""GraceDB question-answering validation.

Stage 1 (this script, network to GraceDB and the shipped GWTC table, no
strain): for every event and prompt template, plan with the deterministic
planner, resolve the identifier the way ``data.resolve_event`` does in real
mode, and score: identifier extracted, time within 1 s of GraceDB ``t_0``,
instruments and retraction reported, expected skills in the plan.

    python scripts/gracedb_qa.py benchmarks/gracedb/qa_events.yaml \
        --outdir docs/acceptance/gracedb-qa-2026-09-09

It also writes ``qa_prompts.json`` (case id -> prompt) for stage 2, the real
runs on the cluster (``scripts/cit/qa_run.sh``), which are scored afterwards
with ``--manifests <dir>``.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import yaml

from ml4gw_agent.adapters.events import gracedb_lookup, gwtc_lookup, resolve
from ml4gw_agent.errors import PlanningError
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig
from ml4gw_agent.registry import load_default_registry

EXPECTED_SKILLS = {
    "data.resolve_event",
    "data.fetch",
    "data.inspect",
    "aframe.detect",
    "amplfi.pe",
    "report.generate",
}


def gps_to_utc(gps: float) -> str:
    from astropy.time import Time

    return Time(gps, format="gps").utc.iso[:19]


def stage1(spec: dict, outdir: Path) -> list[dict]:
    registry = load_default_registry()
    planner = BaselinePlanner(registry, PlannerConfig())
    rows: list[dict] = []
    prompts: dict[str, str] = {}
    for ev in spec["events"]:
        truth = gracedb_lookup(ev["id"])
        cat = gwtc_lookup(ev["gw_name"]) if ev.get("gw_name") else None
        for tpl in spec["prompt_templates"]:
            if tpl.get("requires") and not ev.get(tpl["requires"]):
                continue
            prompt = tpl["text"].format(
                id=ev["id"],
                gw_name=ev.get("gw_name"),
                gps=round(truth["gps"], 2),
                utc=gps_to_utc(truth["gps"]),
            )
            case_id = f"{ev['id']}__{tpl['key']}"
            prompts[case_id] = prompt
            row = {
                "case": case_id,
                "event": ev["id"],
                "template": tpl["key"],
                "prompt": prompt,
                "truth_gps": truth["gps"],
                "truth_instruments": truth["instruments"],
                "truth_retracted": truth["retracted"],
                "truth_far_hz": truth["far"],
                "catalog": (
                    {
                        k: cat.get(k)
                        for k in (
                            "name",
                            "GPS",
                            "mass_1_source",
                            "mass_2_source",
                            "chirp_mass_source",
                            "luminosity_distance",
                            "network_matched_filter_snr",
                        )
                    }
                    if cat
                    else None
                ),
            }
            try:
                plan = planner.plan(prompt)
                event = BaselinePlanner.extract_event(prompt)
                row["extracted_event"] = event
                row["plan_skills"] = [t.skill for t in plan.tasks]
                row["plan_ok"] = EXPECTED_SKILLS <= set(row["plan_skills"])
                res = resolve(event, online=True)
                row["resolved"] = {
                    k: res.get(k)
                    for k in (
                        "catalog_time",
                        "gw_name",
                        "gracedb_id",
                        "instruments",
                        "retracted",
                        "far_per_year",
                        "resolution_source",
                        "resolution_note",
                    )
                }
                t = res.get("catalog_time")
                row["time_ok"] = t is not None and abs(t - truth["gps"]) <= 1.0
                row["time_error_s"] = None if t is None else t - truth["gps"]
                row["instruments_ok"] = (
                    res.get("instruments") == truth["instruments"]
                    if tpl["key"].startswith("superevent")
                    else None
                )
                row["retraction_ok"] = (
                    bool(res.get("retracted")) == bool(truth["retracted"])
                    if tpl["key"].startswith("superevent")
                    else None
                )
            except PlanningError as exc:
                row.update(plan_ok=False, time_ok=False, error=str(exc)[:200])
            rows.append(row)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "qa_prompts.json").write_text(json.dumps(prompts, indent=1) + "\n")
    (outdir / "stage1.json").write_text(json.dumps(rows, indent=1) + "\n")
    return rows


def stage2(spec: dict, rows: list[dict], manifests: Path) -> list[dict]:
    expect = {ev["id"]: ev for ev in spec["events"]}
    for row in rows:
        found = sorted(
            glob.glob(
                str(manifests / row["case"] / "**" / "run_manifest.json"),
                recursive=True,
            )
        )
        if not found:
            row["run"] = None
            continue
        m = json.loads(Path(found[-1]).read_text())
        tasks = m["tasks"]
        fetch = tasks.get("fetch_data", {})
        aframe = (tasks.get("run_aframe") or {}).get("outputs") or {}
        amplfi = (tasks.get("run_amplfi") or {}).get("outputs") or {}
        ci = (amplfi.get("credible_intervals") or {}).get("chirp_mass_source") or {}
        cat = row.get("catalog") or {}
        run = {
            "status": m.get("status"),
            "fetch_status": fetch.get("status"),
            "fetch_error": (fetch.get("error") or "")[:160],
            "aframe_candidate": aframe.get("candidate_found"),
            "aframe_statistic": aframe.get("detection_statistic"),
            "tc_offset_s": aframe.get("target_offset_seconds"),
            "amplfi_chirp_median": ci.get("median"),
            "catalog_chirp": cat.get("chirp_mass_source"),
            "chirp_in_90": (
                ci.get("p5") <= cat["chirp_mass_source"] <= ci.get("p95")
                if ci and cat.get("chirp_mass_source")
                else None
            ),
        }
        exp = expect[row["event"]]["expect_run"]
        if exp == "completed":
            run["as_expected"] = m.get("status") == "completed"
        elif exp == "fail_closed_fetch":
            run["as_expected"] = (
                fetch.get("status") == "failed" and m.get("status") != "completed"
            )
        else:
            run["as_expected"] = (
                m.get("status") == "completed" or fetch.get("status") == "failed"
            )
        row["run"] = run
    return rows


def markdown(rows: list[dict]) -> str:
    lines = [
        "# GraceDB QA validation (generated by scripts/gracedb_qa.py)",
        "",
        "| case | extracted | time err [s] | time ok | instruments ok | "
        "retraction ok | plan ok | run | as expected | Aframe cand. | tc off [s] | "
        "chirp AMPLFI/cat (in 90%) |",
        "|---|---|---:|---|---|---|---|---|---|---|---:|---|",
    ]
    for r in rows:
        run = r.get("run") or {}
        te = r.get("time_error_s")
        tc = run.get("tc_offset_s")
        chirp = run.get("amplfi_chirp_median")
        cells = [
            r["case"],
            str(r.get("extracted_event", "—")),
            "—" if te is None else f"{te:+.2f}",
            str(r.get("time_ok")),
            str(r.get("instruments_ok", "—")),
            str(r.get("retraction_ok", "—")),
            str(r.get("plan_ok")),
            str(run.get("status", "—")),
            str(run.get("as_expected", "—")),
            str(run.get("aframe_candidate", "—")),
            "—" if tc is None else f"{tc:+.3f}",
            f"{'—' if chirp is None else round(chirp, 1)} / {run.get('catalog_chirp')} "
            f"({run.get('chirp_in_90', '—')})",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    n = len(rows)
    time_ok = sum(bool(r.get("time_ok")) for r in rows)
    plan_ok = sum(bool(r.get("plan_ok")) for r in rows)
    inst = [r for r in rows if r.get("instruments_ok") is not None]
    retr = [r for r in rows if r.get("retraction_ok") is not None]
    runs = [r for r in rows if r.get("run")]
    lines += [
        "",
        f"- cases: {n}; time resolved within 1 s: {time_ok}; plan ok: {plan_ok}; "
        f"instruments ok: {sum(1 for r in inst if r['instruments_ok'])} "
        f"of {len(inst)}; "
        f"retraction ok: {sum(1 for r in retr if r['retraction_ok'])} of {len(retr)}",
        f"- real runs scored: {len(runs)}; as expected: "
        f"{sum(1 for r in runs if r['run'].get('as_expected'))}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("spec", type=Path)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--manifests", type=Path, default=None)
    args = parser.parse_args(argv)
    spec = yaml.safe_load(args.spec.read_text())
    stage1_path = args.outdir / "stage1.json"
    if args.manifests and stage1_path.is_file():
        rows = json.loads(stage1_path.read_text())
    else:
        rows = stage1(spec, args.outdir)
    if args.manifests:
        rows = stage2(spec, rows, args.manifests)
        (args.outdir / "stage2.json").write_text(json.dumps(rows, indent=1) + "\n")
    (args.outdir / "QA.md").write_text(markdown(rows))
    print(markdown(rows).splitlines()[-2:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
