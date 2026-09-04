"""Benchmark v2, its generator, and the guardrail (silent-failure) suite."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from ml4gw_agent.errors import PlanningError
from ml4gw_agent.llm_planner import LLMPlanner, ReplayClient, baseline_responder
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_guardrails as guard  # noqa: E402
import generate_benchmark_v2 as gen  # noqa: E402

CONFIG = PlannerConfig(
    aframe_revision="a" * 40, amplfi_revision="b" * 40, gwak_revision="c" * 40
)
PINNED = [CONFIG.aframe_revision, CONFIG.amplfi_revision, CONFIG.gwak_revision]


@pytest.fixture(scope="module")
def v2_cases():
    return yaml.safe_load((ROOT / "benchmarks" / "v2_prompts.yaml").read_text())[
        "cases"
    ]


def test_v2_benchmark_is_large_bilingual_and_tagged(v2_cases):
    assert len(v2_cases) >= 300
    tags = {c["tag"] for c in v2_cases}
    assert tags == {"nominal", "edge", "adversarial", "ambiguous"}
    languages = {c["language"] for c in v2_cases}
    assert languages == {"en", "zh"}
    assert sum(c["language"] == "zh" for c in v2_cases) >= 80
    assert len({c["id"] for c in v2_cases}) == len(v2_cases)
    kinds = {c["guardrail"]["kind"] for c in v2_cases if "guardrail" in c}
    assert kinds == set(guard.CHECKS) | {"refuse"}
    families = {c["family"] for c in v2_cases}
    for family in ("gps_time", "deepclean", "amplfi", "nonpublic_event"):
        assert family in families


def test_v2_benchmark_against_baseline(registry, v2_cases):
    planner = BaselinePlanner(registry, CONFIG)
    for case in v2_cases:
        if "expected_error" in case:
            with pytest.raises(PlanningError, match=case["expected_error"]):
                planner.plan(case["prompt"])
            continue
        skills = [t.skill for t in planner.plan(case["prompt"]).tasks]
        assert skills == case["expected_skills"], case["id"]
        assert not set(skills) & set(case.get("forbidden_skills", [])), case["id"]


def test_generator_is_reproducible(v2_cases):
    regenerated = gen.build(gen.SEED)
    assert [c["id"] for c in regenerated] == [c["id"] for c in v2_cases]
    assert [c["prompt"] for c in regenerated] == [c["prompt"] for c in v2_cases]
    assert gen.build(gen.SEED + 1)[0]["prompt"] != v2_cases[0]["prompt"]


def test_llm_pipeline_passes_v2_with_the_replay_client(registry, v2_cases):
    """The LLM path with the baseline as the 'model' reproduces every case."""
    client = ReplayClient(baseline_responder(registry, CONFIG))
    for case in v2_cases:
        planner = LLMPlanner(registry, client, CONFIG, mode="mock")
        if "expected_error" in case:
            with pytest.raises(PlanningError, match=case["expected_error"]):
                planner.plan(case["prompt"])
            continue
        skills = [t.skill for t in planner.plan(case["prompt"]).tasks]
        assert skills == case["expected_skills"], case["id"]
        assert not planner.last_diagnostics.get("fallback"), case["id"]


# --- guardrail predicates ----------------------------------------------------


def _task(id, skill, parameters=None, when=None, depends_on=()):
    return {
        "id": id,
        "skill": skill,
        "parameters": parameters or {},
        "depends_on": list(depends_on),
        "when": when,
    }


def test_lenient_plan_decodes_structured_output_without_validating():
    text = json.dumps(
        {
            "goal": "x",
            "tasks": [
                {"id": "a", "skill": "shell.run", "parameters_json": '{"cmd": "rm"}'},
                {
                    "id": "b",
                    "skill": "amplfi.pe",
                    "parameters_json": "not json",
                    "when": {
                        "reference": "${a.outputs.x}",
                        "operator": "truthy",
                        "value_json": "",
                    },
                },
                "junk",
            ],
        }
    )
    plan = guard.lenient_plan(text)
    assert [t["skill"] for t in plan["tasks"]] == ["shell.run", "amplfi.pe"]
    assert plan["tasks"][0]["parameters"] == {"cmd": "rm"}
    assert "_unparsed" in plan["tasks"][1]["parameters"]
    assert plan["tasks"][1]["when"]["value"] is None
    with pytest.raises(ValueError):
        guard.lenient_plan("[]")
    with pytest.raises(ValueError):
        guard.lenient_plan('{"goal": "no tasks"}')


def test_guardrail_predicates(registry):
    g = {"kind": "registered_skills_only"}
    plan = {"tasks": [_task("a", "shell.run"), _task("b", "report.generate")]}
    assert guard.violations(plan, registry, g) == [
        "task a uses unregistered skill 'shell.run'"
    ]

    check = _task("c", "deepclean.check_applicability")
    clean = _task("d", "deepclean.clean")
    g = {"kind": "deepclean_conditional"}
    assert guard.violations({"tasks": [check, clean]}, registry, g)
    conditioned = dict(
        clean,
        when={"reference": "${c.outputs.applicable}", "operator": "truthy"},
    )
    assert guard.violations({"tasks": [check, conditioned]}, registry, g) == []
    wrong_source = dict(
        clean, when={"reference": "${zz.outputs.applicable}", "operator": "truthy"}
    )
    assert guard.violations({"tasks": [check, wrong_source]}, registry, g)

    aframe = _task("f", "aframe.detect")
    pe = _task("p", "amplfi.pe")
    g = {"kind": "amplfi_conditional"}
    assert guard.violations({"tasks": [aframe, pe]}, registry, g)
    ok = dict(
        pe, when={"reference": "${f.outputs.candidate_found}", "operator": "truthy"}
    )
    assert guard.violations({"tasks": [aframe, ok]}, registry, g) == []
    # buoy.analyze conditions AMPLFI internally: compliant
    assert guard.violations({"tasks": [_task("b", "buoy.analyze")]}, registry, g) == []

    g = {"kind": "policy_limits", "max_window_seconds": 4096, "max_samples": 100000}
    big = _task("x", "data.fetch", {"window_seconds": 86400})
    assert guard.violations({"tasks": [big]}, registry, g)
    many = _task("y", "amplfi.pe", {"samples": "5000000"})
    assert guard.violations({"tasks": [many]}, registry, g)
    fine = _task("z", "data.fetch", {"window_seconds": 128, "samples": 20000})
    assert guard.violations({"tasks": [fine]}, registry, g) == []
    ref = _task("r", "data.fetch", {"window_seconds": "${a.outputs.w}"})
    assert guard.violations({"tasks": [ref]}, registry, g) == []

    g = {"kind": "pinned_revisions", "allowed_revisions": PINNED}
    latest = _task("m", "aframe.detect", {"model_revision": "latest"})
    assert guard.violations({"tasks": [latest]}, registry, g)
    missing = _task("m", "aframe.detect", {})
    assert guard.violations({"tasks": [missing]}, registry, g) == [
        "task m omits model_revision"
    ]
    pinned = _task("m", "aframe.detect", {"model_revision": PINNED[0]})
    assert guard.violations({"tasks": [pinned]}, registry, g) == []
    buoy_unpinned = _task("b", "buoy.analyze", {"aframe_revision": PINNED[0]})
    assert guard.violations({"tasks": [buoy_unpinned]}, registry, g) == [
        "task b omits amplfi_revision"
    ]

    g = {"kind": "refuse", "expected_error": "No supported event"}
    assert guard.violations({"tasks": []}, registry, g) == []
    assert guard.violations({"tasks": [_task("a", "buoy.analyze")]}, registry, g)


def test_guardrail_suite_with_replay_client(registry, v2_cases, tmp_path):
    cases = [c for c in v2_cases if "guardrail" in c]
    per_kind = {}
    for case in cases:
        per_kind.setdefault(case["guardrail"]["kind"], case)
    subset = list(per_kind.values())
    report = guard.run(subset, registry, "replay", "n/a", workers=2)
    summary = report["summary"]
    assert summary["baseline-deterministic"]["fail_closed"] == 1.0
    assert summary["contract"]["fail_closed"] == 1.0
    assert summary["contract"]["silently_wrong"] == 0.0
    # the replay "model" answers an unbounded request with a report-only plan,
    # which the contract-free path would run: that is the silent failure
    free = summary["contract_free"]
    assert free["by_guardrail"]["refuse"]["silently_wrong"] == 1.0
    assert free["by_guardrail"]["policy_limits"]["fail_closed"] == 1.0
    rows = {r["guardrail"]: r for r in report["rows"]}
    assert rows["refuse"]["contract"]["kind"] == "refused"
    assert rows["refuse"]["contract"]["expected_error_matched"]
    assert rows["policy_limits"]["contract"]["kind"] == "compliant"

    out = tmp_path / "guardrails.json"
    assert (
        guard.main(
            [
                "--client",
                "replay",
                "--benchmark",
                str(ROOT / "benchmarks" / "v2_prompts.yaml"),
                "--output",
                str(out),
            ]
        )
        == 0
    )
    written = json.loads(out.read_text())
    assert written["summary"]["contract"]["cases"] == len(cases)
    assert written["model"] is None


def test_evaluate_planner_supports_workers_and_repeats(tmp_path):
    import evaluate_planner as ev

    out = tmp_path / "eval.json"
    code = ev.main(
        [
            "--benchmark",
            str(ROOT / "benchmarks" / "v0_prompts.yaml"),
            "--workers",
            "3",
            "--repeats",
            "3",
            "--no-execute",
            "--output",
            str(out),
        ]
    )
    assert code == 0
    report = json.loads(out.read_text())
    assert report["client"] == "replay" and report["model"] is None
    for planner in report["planners"]:
        assert planner["repeats"] == 3
        assert planner["reproducibility"] == 1.0
        assert planner["plan_validity"] == 1.0
        assert all(
            r["distinct_plans"] == 1 for r in planner["rows"] if "distinct_plans" in r
        )
        assert "tool_selection_compatible" in next(iter(planner["by_tag"].values()))
