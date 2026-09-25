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
    assert by_id["clean_deepclean"].skill == "deepclean.clean"
    assert by_id["clean_deepclean"].when.reference.endswith("applicable}")
    assert by_id["clean_deepclean"].depends_on == ["check_deepclean"]
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


# --------------------------------------------------------------------------- #
# Negation, structured exclusions and explicit pipeline choice
# --------------------------------------------------------------------------- #

AFRAME_GWAK = [
    "data.resolve_event",
    "data.fetch",
    "data.inspect",
    "aframe.detect",
    "data.fetch",
    "gwak.scan",
    "analysis.reconcile",
    "report.generate",
]


@pytest.mark.parametrize(
    "suffix",
    [
        " Do not run AMPLFI.",
        " Don't run AMPLFI parameter estimation.",
        " Without AMPLFI.",
        " Skip parameter estimation.",
        " 不要运行 AMPLFI 参数估计。",
        "，不需要 AMPLFI 参数估计。",
        "；无需参数估计。",
    ],
)
def test_negated_amplfi_mention_is_an_exclusion(registry, suffix):
    prompt = "Run Aframe and GWAK on GW150914 and reconcile the two results." + suffix
    plan = BaselinePlanner(registry).plan(prompt)
    assert [task.skill for task in plan.tasks] == AFRAME_GWAK
    assert plan.route == "decomposed"
    assert plan.excluded_skills == ["amplfi.pe"]
    assert any("Excluded by request: amplfi.pe" in w for w in plan.warnings)


def test_negation_is_clause_local_and_respects_contrast(registry):
    from ml4gw_agent.planning import mentions

    found = mentions("do not run gwak, run aframe and amplfi")
    assert found.excluded == {"gwak"}
    assert found.requested == {"aframe", "amplfi"}

    found = mentions("run aframe but not amplfi")
    assert found.excluded == {"amplfi"} and found.requested == {"aframe"}

    # a contrast marker after the cue cancels it for the later tool
    found = mentions("not gwak but aframe")
    assert found.excluded == {"gwak"} and found.requested == {"aframe"}

    # a cue in an earlier clause never reaches a later clause
    found = mentions("do not use cuda; run amplfi")
    assert found.requested == {"amplfi"} and not found.excluded

    # a continuation marker ends the scope; a bare conjunction extends it
    found = mentions("skip detection and go straight to amplfi parameter estimation")
    assert found.requested == {"amplfi"} and not found.excluded
    found = mentions("do not run amplfi or gwak on gw150914")
    assert found.excluded == {"amplfi", "gwak"} and not found.requested
    found = mentions("skip gwak and run amplfi")
    assert found.excluded == {"gwak"} and found.requested == {"amplfi"}


def test_generic_request_with_exclusion_leaves_buoy(registry):
    plan = BaselinePlanner(registry).plan("Analyze GW150914 without AMPLFI.")
    assert plan.route == "decomposed"
    assert [task.skill for task in plan.tasks] == [
        "data.resolve_event",
        "data.fetch",
        "data.inspect",
        "aframe.detect",
        "report.generate",
    ]

    plan = BaselinePlanner(registry).plan("Don't use Buoy: analyze GW150914.")
    assert plan.route == "decomposed"
    assert plan.excluded_skills == ["buoy.analyze"]
    assert "amplfi.pe" in [task.skill for task in plan.tasks]


def test_contradictory_and_impossible_requests_fail_closed(registry):
    with pytest.raises(PlanningError, match="both asks for and rules out"):
        BaselinePlanner(registry).plan(
            "Run AMPLFI parameter estimation on GW150914 and do not run AMPLFI."
        )
    # a worded exclusion of a prerequisite is overridden with a warning ...
    plan = BaselinePlanner(registry).plan("Run AMPLFI on GW150914, not Aframe.")
    skills = [task.skill for task in plan.tasks]
    assert "aframe.detect" in skills and "amplfi.pe" in skills
    assert plan.excluded_skills == []
    assert any("scheduled anyway" in w for w in plan.warnings)
    # ... but a structured exclusion of it cannot be satisfied
    with pytest.raises(PlanningError, match="cannot run with aframe.detect excluded"):
        BaselinePlanner(
            registry, PlannerConfig(exclude_skills=("aframe.detect",))
        ).plan("Run AMPLFI parameter estimation on GW150914.")


def test_structured_exclusions_and_route_field(registry):
    planner = BaselinePlanner(registry, PlannerConfig(exclude_skills=("amplfi.pe",)))
    plan = planner.plan("Analyze GW150914.")
    assert plan.route == "decomposed"
    assert "amplfi.pe" not in [task.skill for task in plan.tasks]
    assert plan.excluded_skills == ["amplfi.pe"]

    planner = BaselinePlanner(registry, PlannerConfig(exclude_skills=("gwak.scan",)))
    plan = planner.plan("Run Aframe detection on GW150914.")
    skills = [task.skill for task in plan.tasks]
    assert "gwak.scan" not in skills and "analysis.reconcile" not in skills
    assert plan.excluded_skills == ["analysis.reconcile", "gwak.scan"]
    # a structured exclusion that contradicts the prompt is refused, not ignored
    with pytest.raises(PlanningError, match="both asks for and rules out"):
        planner.plan("Run Aframe and GWAK on GW150914.")

    with pytest.raises(PlanningError, match="unknown skill.*Valid skill names:.*"):
        BaselinePlanner(registry, PlannerConfig(exclude_skills=("nope.skill",))).plan(
            "Analyze GW150914."
        )

    assert BaselinePlanner(registry).plan("Analyze GW150914.").route == "buoy"
    assert (
        BaselinePlanner(registry).plan("What is the mass of GW150914?").route
        == "lookup"
    )


def test_explicit_pipeline_choice(registry):
    decomposed = BaselinePlanner(registry, PlannerConfig(pipeline="decomposed"))
    plan = decomposed.plan("Analyze GW150914.")
    assert plan.route == "decomposed"
    assert [task.skill for task in plan.tasks] == [
        "data.resolve_event",
        "data.fetch",
        "data.inspect",
        "aframe.detect",
        "amplfi.pe",
        "report.generate",
    ]
    # the Buoy wording that misrouted the gpt-6-luna case is now forced apart
    plan = decomposed.plan(
        "Run the Buoy event analysis pipeline for GW150914, using Aframe "
        "detection followed by AMPLFI parameter estimation."
    )
    assert plan.route == "decomposed" and "buoy.analyze" not in [
        task.skill for task in plan.tasks
    ]

    buoy = BaselinePlanner(registry, PlannerConfig(pipeline="buoy"))
    assert buoy.plan("Run Aframe and AMPLFI on GW150914.").route == "buoy"
    with pytest.raises(PlanningError, match="covers Aframe and AMPLFI only"):
        buoy.plan("Run GWAK on GW150914.")
    with pytest.raises(PlanningError, match="conflicts with excluding"):
        BaselinePlanner(
            registry, PlannerConfig(pipeline="buoy", exclude_skills=("amplfi.pe",))
        ).plan("Analyze GW150914.")


def test_plan_spec_rejects_scheduled_excluded_skill():
    from ml4gw_agent.models import PlanSpec, TaskSpec

    with pytest.raises(ValueError, match="excluded skills"):
        PlanSpec(
            prompt="test GW150914",
            goal="test",
            excluded_skills=["data.fetch"],
            tasks=[TaskSpec(id="fetch", skill="data.fetch")],
        )
