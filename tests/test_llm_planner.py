"""LLM planner: validation boundary, repair, fallback, replan, memory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ml4gw_agent.errors import PlanningError
from ml4gw_agent.llm_planner import (
    PLAN_JSON_SCHEMA,
    ExperimentMemory,
    LLMPlanner,
    ReplayClient,
    baseline_responder,
    observe,
    plan_hash,
    retrieve_skill_summaries,
)
from ml4gw_agent.models import RunStatus, TaskStatus
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig
from ml4gw_agent.runtime import AgentRuntime

CONFIG = PlannerConfig(
    aframe_revision="a" * 40, amplfi_revision="b" * 40, gwak_revision="c" * 40
)
PROMPT = "Run Aframe detection and AMPLFI parameter estimation on GW150914."


def _planner(registry, responder, **kwargs):
    return LLMPlanner(registry, ReplayClient(responder), CONFIG, **kwargs)


def _plan_json(**overrides):
    plan = {
        "goal": "test",
        "warnings": [],
        "tasks": [
            {
                "id": "resolve_event",
                "skill": "data.resolve_event",
                "parameters": {"event": "GW150914"},
                "depends_on": [],
            },
            {
                "id": "generate_report",
                "skill": "report.generate",
                "parameters": {"title": "t"},
                "depends_on": ["resolve_event"],
                "allow_failed_dependencies": True,
            },
        ],
    }
    plan.update(overrides)
    return json.dumps(plan)


def test_replay_of_baseline_reproduces_the_baseline_plan(registry):
    planner = _planner(registry, baseline_responder(registry, CONFIG))
    plan = planner.plan(PROMPT)
    baseline = BaselinePlanner(registry, CONFIG).plan(PROMPT)
    assert plan.planner == "llm-claude-v0.3"
    assert [t.skill for t in plan.tasks] == [t.skill for t in baseline.tasks]
    assert plan_hash(plan) == plan_hash(baseline)
    assert planner.last_diagnostics["attempts"][0]["error"] is None
    assert not planner.last_diagnostics.get("fallback")
    request = json.loads(planner.client.calls[0]["user"])
    names = {s["name"] for s in request["available_skills"]}
    assert {"data.resolve_event", "data.fetch", "aframe.detect", "amplfi.pe"} <= names
    assert request["configuration"]["aframe_revision"] == "a" * 40


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (
            {
                "tasks": [
                    {
                        "id": "x",
                        "skill": "shell.run",
                        "parameters": {"cmd": "rm -rf /"},
                        "depends_on": [],
                    }
                ]
            },
            "unknown",
        ),
        (
            {
                "tasks": [
                    {
                        "id": "resolve_event",
                        "skill": "data.resolve_event",
                        "parameters": {"event": "GW150914", "shell": "id"},
                        "depends_on": [],
                    }
                ]
            },
            "does not accept",
        ),
        (
            {
                "tasks": [
                    {
                        "id": "fetch_data",
                        "skill": "data.fetch",
                        "parameters": {
                            "event": "GW150914",
                            "ifos": ["H1", "L1"],
                            "gps_time": "${nowhere.outputs.catalog_time}",
                        },
                        "depends_on": [],
                    }
                ]
            },
            "unknown task",
        ),
        (
            {
                "tasks": [
                    {
                        "id": "resolve_event",
                        "skill": "data.resolve_event",
                        "parameters": {"event": "GW150914"},
                        "depends_on": [],
                    },
                    {
                        "id": "fetch_data",
                        "skill": "data.fetch",
                        "parameters": {
                            "event": "GW150914",
                            "ifos": ["H1", "L1"],
                            "gps_time": "${resolve_event.outputs.catalog_time}",
                        },
                        "depends_on": [],
                    },
                ]
            },
            "does not depend",
        ),
        (
            {
                "tasks": [
                    {
                        "id": "a",
                        "skill": "data.resolve_event",
                        "parameters": {"event": "GW150914"},
                        "depends_on": ["b"],
                    },
                    {
                        "id": "b",
                        "skill": "report.generate",
                        "parameters": {},
                        "depends_on": ["a"],
                    },
                ]
            },
            "PlanSpec",
        ),
        (
            {
                "tasks": [
                    {
                        "id": "run_gwak",
                        "skill": "gwak.scan",
                        "parameters": {
                            "strain_artifact": "artifacts/x.hdf5",
                            "model_revision": "UNPINNED",
                        },
                        "depends_on": [],
                    }
                ]
            },
            "policy",
        ),
    ],
)
def test_invalid_llm_plans_are_rejected_then_baseline_is_used(registry, bad, message):
    planner = _planner(registry, lambda s, u, sc: _plan_json(**bad))
    plan = planner.plan(PROMPT)
    attempts = planner.last_diagnostics["attempts"]
    assert len(attempts) == 2 and all(message in a["error"] for a in attempts)
    assert planner.last_diagnostics["fallback"] is True
    assert plan.planner == "baseline-deterministic-v0.1"
    assert any("LLM plan rejected" in w for w in plan.warnings)
    # the repair round received the validator's error
    assert "rejected by the validator" in planner.client.calls[1]["user"]


def test_repair_round_recovers_from_a_first_bad_answer(registry):
    good = baseline_responder(registry, CONFIG)
    state = {"n": 0}

    def flaky(system, user, schema):
        state["n"] += 1
        if state["n"] == 1:
            return "not json at all"
        return good(system, user, schema)

    planner = _planner(registry, flaky)
    plan = planner.plan(PROMPT)
    assert plan.planner == "llm-claude-v0.3"
    assert len(planner.last_diagnostics["attempts"]) == 2
    assert "not JSON" in planner.last_diagnostics["attempts"][0]["error"]


def test_unbounded_request_is_refused_before_the_model_is_called(registry):
    calls = []

    def responder(system, user, schema):
        calls.append(user)
        return _plan_json()

    planner = _planner(registry, responder)
    with pytest.raises(PlanningError, match="No supported event"):
        planner.plan("Scan all of O3.")
    assert calls == []


def test_mock_run_replan_and_memory(registry, tmp_path):
    memory = ExperimentMemory(tmp_path / "memory.jsonl")
    planner = _planner(
        registry, baseline_responder(registry, CONFIG), memory=memory, mode="mock"
    )
    plan = planner.plan(PROMPT)
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="mock")
    assert manifest.status == RunStatus.COMPLETED
    entry = memory.record(plan, manifest, CONFIG)
    assert entry["data"]["event"] == "GW150914"
    assert entry["models"]["aframe_revision"] == "a" * 40
    assert entry["result"]["failures"] == {}
    assert memory.recall("GW150914")[0]["run_id"] == manifest.run_id
    assert memory.recall("GW190521") == []
    # the next request for the same event carries the prior outcome
    planner.plan(PROMPT)
    request = json.loads(planner.client.calls[-1]["user"])
    assert request["prior_runs_for_this_event"][0]["status"] == "completed"

    observation = observe(manifest)
    assert observation["tasks"]["run_aframe"]["outputs"]["candidate_found"] is True
    # nothing failed: no replanning
    assert planner.replan(PROMPT, manifest) is None

    failed = manifest.model_copy(deep=True)
    failed.tasks["run_aframe"].status = TaskStatus.FAILED
    failed.tasks["run_aframe"].error = "AdapterError: boom"
    replanned = planner.replan(PROMPT, failed)
    assert replanned is not None
    assert any("replanned once" in w for w in replanned.warnings)
    assert "boom" in planner.client.calls[-1]["user"]


def test_retrieval_ranks_relevant_skills_and_keeps_the_core(registry):
    names = [s["name"] for s in retrieve_skill_summaries(registry, "参数估计 GW150914")]
    assert "amplfi.pe" in names
    core = {"data.resolve_event", "data.fetch", "data.inspect", "report.generate"}
    assert core <= set(names)
    names = [s["name"] for s in retrieve_skill_summaries(registry, "GWAK anomalies")]
    assert "gwak.scan" in names


def test_plan_schema_matches_planspec_fields():
    task_props = PLAN_JSON_SCHEMA["properties"]["tasks"]["items"]["properties"]
    assert set(task_props) == {
        "id",
        "skill",
        "parameters_json",
        "depends_on",
        "when",
        "allow_failed_dependencies",
    }

    def no_free_objects(schema):
        if isinstance(schema, dict):
            if schema.get("type") == "object" or (
                isinstance(schema.get("type"), list) and "object" in schema["type"]
            ):
                assert schema.get("additionalProperties") is False, schema
            for value in schema.values():
                no_free_objects(value)
        elif isinstance(schema, list):
            for value in schema:
                no_free_objects(value)

    no_free_objects(PLAN_JSON_SCHEMA)  # Anthropic structured-output rule


def test_v1_benchmark_against_baseline(registry):
    path = Path(__file__).parents[1] / "benchmarks" / "v1_prompts.yaml"
    cases = yaml.safe_load(path.read_text())["cases"]
    assert len(cases) >= 50
    planner = BaselinePlanner(registry, CONFIG)
    for case in cases:
        if "expected_error" in case:
            with pytest.raises(PlanningError, match=case["expected_error"]):
                planner.plan(case["prompt"])
            continue
        skills = [t.skill for t in planner.plan(case["prompt"]).tasks]
        assert skills == case["expected_skills"], case["id"]
        assert not set(skills) & set(case.get("forbidden_skills", [])), case["id"]


def test_output_config_drops_effort_for_haiku():
    from ml4gw_agent.llm_planner import output_config_for

    schema = {"type": "object"}
    assert "effort" in output_config_for("claude-opus-5", "high", schema)
    assert "effort" not in output_config_for(
        "claude-haiku-4-5-20251001", "high", schema
    )
    assert output_config_for("claude-opus-5", "", schema) == {
        "format": {"type": "json_schema", "schema": schema}
    }
