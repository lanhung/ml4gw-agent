from pathlib import Path

import pytest
import yaml

from ml4gw_agent.errors import PlanningError
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig


def test_generic_event_analysis_uses_buoy_vertical_slice(registry):
    plan = BaselinePlanner(registry).plan("Analyze GW150914")
    assert [task.skill for task in plan.tasks] == [
        "data.resolve_event",
        "buoy.analyze",
        "report.generate",
    ]
    assert plan.tasks[1].parameters["event"] == "GW150914"
    assert any("not fully pinned" in warning for warning in plan.warnings)


def test_chinese_generic_prompt_is_supported(registry):
    plan = BaselinePlanner(registry).plan("请分析 GW150914")
    assert plan.tasks[1].skill == "buoy.analyze"


def test_explicit_composition_builds_conditional_dag(registry):
    planner = BaselinePlanner(
        registry,
        PlannerConfig(
            aframe_revision="aframe-sha",
            amplfi_revision="amplfi-sha",
            gwak_revision="gwak-sha",
        ),
    )
    plan = planner.plan(
        "Analyze GW150914: check data quality, use DeepClean if appropriate, "
        "run Aframe detection and AMPLFI parameter estimation, and scan with GWAK."
    )
    by_id = {task.id: task for task in plan.tasks}
    assert by_id["fetch_data"].skill == "data.fetch"
    assert by_id["check_deepclean"].skill == "deepclean.check_applicability"
    assert "deepclean.clean" not in {task.skill for task in plan.tasks}
    assert by_id["run_aframe"].when.reference.endswith("quality_passed}")
    assert by_id["run_amplfi"].depends_on == ["run_aframe"]
    assert by_id["run_amplfi"].when.reference.endswith("candidate_found}")
    assert by_id["run_gwak"].depends_on == ["inspect_data", "fetch_data_4k"]
    assert by_id["generate_report"].allow_failed_dependencies


def test_parameter_estimation_schedules_aframe_for_tc(registry):
    plan = BaselinePlanner(registry).plan("Perform parameter estimation for GW190521")
    skills = [task.skill for task in plan.tasks]
    assert "aframe.detect" in skills
    assert "amplfi.pe" in skills


def test_gps_event_is_extracted(registry):
    plan = BaselinePlanner(registry).plan("Analyze GPS 1187008882.4")
    assert plan.tasks[0].parameters["event"] == "1187008882.4"


def test_prompt_without_event_fails_closed(registry):
    with pytest.raises(PlanningError, match="No supported event"):
        BaselinePlanner(registry).plan("Scan all of O3")


def test_v0_prompt_benchmark(registry):
    benchmark_path = Path(__file__).parents[1] / "benchmarks" / "v0_prompts.yaml"
    benchmark = yaml.safe_load(benchmark_path.read_text())
    planner = BaselinePlanner(registry)
    for case in benchmark["cases"]:
        if "expected_error" in case:
            with pytest.raises(PlanningError, match=case["expected_error"]):
                planner.plan(case["prompt"])
            continue
        plan = planner.plan(case["prompt"])
        actual = [task.skill for task in plan.tasks]
        assert actual == case["expected_skills"], case["id"]
        for forbidden in case.get("forbidden_skills", []):
            assert forbidden not in actual, case["id"]


def test_three_detector_request_keeps_aframe_on_h1_l1(registry):
    planner = BaselinePlanner(
        registry,
        PlannerConfig(
            ifos=("H1", "L1", "V1"),
            aframe_revision="aframe-sha",
            amplfi_revision="amplfi-sha",
        ),
    )
    plan = planner.plan(
        "Fetch strain data for GW190521, check data quality, run Aframe detection "
        "and AMPLFI parameter estimation."
    )
    by_id = {task.id: task for task in plan.tasks}
    assert by_id["fetch_data"].parameters["ifos"] == ["H1", "L1", "V1"]
    assert by_id["inspect_data"].parameters["expected_ifos"] == ["H1", "L1", "V1"]
    assert by_id["run_aframe"].parameters["ifos"] == ["H1", "L1"]
    assert by_id["run_amplfi"].parameters["ifos"] == ["H1", "L1", "V1"]
    assert any("Aframe runs on ['H1', 'L1'] only" in w for w in plan.warnings)

    default_plan = BaselinePlanner(registry).plan("Run Aframe detection on GW150914.")
    assert not any("Aframe runs on" in w for w in default_plan.warnings)


def test_aframe_threshold_comes_from_calibration_when_available(registry, monkeypatch):
    from ml4gw_agent import calibration

    table = {
        "revisions": {
            "aframe-sha": {
                "livetime_seconds": 10 * 365.25 * 86400,
                "source": "unit-test",
                "thresholds_by_far_per_year": {"12": 3.0, "1": 4.5, "0.1": 6.0},
            }
        }
    }
    monkeypatch.setattr(calibration, "load_aframe_table", lambda: table)

    calibrated = BaselinePlanner(
        registry,
        PlannerConfig(aframe_revision="aframe-sha", amplfi_revision="amplfi-sha"),
    ).plan("Run Aframe detection on GW150914.")
    task = {t.id: t for t in calibrated.tasks}["run_aframe"]
    assert task.parameters["threshold"] == 4.5
    assert task.parameters["threshold_calibration"]["far_per_year"] == 1.0
    assert task.parameters["target_time"] == "${resolve_event.outputs.catalog_time}"
    assert task.parameters["candidate_window_seconds"] == 2.0
    assert not any("raw 0.0 cut" in w for w in calibrated.warnings)

    monthly = BaselinePlanner(
        registry,
        PlannerConfig(
            aframe_revision="aframe-sha",
            amplfi_revision="amplfi-sha",
            aframe_far_per_year=12.0,
        ),
    ).plan("Run Aframe detection on GW150914.")
    assert {t.id: t for t in monthly.tasks}["run_aframe"].parameters["threshold"] == 3.0

    # a rate the livetime cannot measure is refused, not extrapolated
    unmeasured = BaselinePlanner(
        registry,
        PlannerConfig(
            aframe_revision="aframe-sha",
            amplfi_revision="amplfi-sha",
            aframe_far_per_year=0.01,
        ),
    ).plan("Run Aframe detection on GW150914.")
    assert {t.id: t for t in unmeasured.tasks}["run_aframe"].parameters[
        "threshold"
    ] == 0.0
    assert any("raw 0.0 cut" in w for w in unmeasured.warnings)

    explicit = BaselinePlanner(
        registry,
        PlannerConfig(
            aframe_revision="aframe-sha",
            amplfi_revision="amplfi-sha",
            aframe_threshold=7.0,
        ),
    ).plan("Run Aframe detection on GW150914.")
    task = {t.id: t for t in explicit.tasks}["run_aframe"]
    assert task.parameters["threshold"] == 7.0
    assert task.parameters["threshold_calibration"] is None


def test_unknown_revision_falls_back_to_raw_cut_with_warning(registry):
    plan = BaselinePlanner(
        registry,
        PlannerConfig(aframe_revision="no-such-sha", amplfi_revision="amplfi-sha"),
    ).plan("Run Aframe detection on GW150914.")
    task = {t.id: t for t in plan.tasks}["run_aframe"]
    assert task.parameters["threshold"] == 0.0
    assert task.parameters["threshold_calibration"] is None
    assert any("raw 0.0 cut" in w for w in plan.warnings)
