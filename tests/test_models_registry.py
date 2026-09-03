import copy

import pytest

from ml4gw_agent.errors import RegistryError
from ml4gw_agent.models import PlanSpec, TaskSpec
from ml4gw_agent.registry import SkillRegistry


def test_default_registry_loads_all_initial_contracts(registry):
    names = {skill.name for skill in registry.all()}
    assert len(registry) == 11
    assert {
        "data.resolve_event",
        "data.fetch",
        "data.inspect",
        "buoy.analyze",
        "aframe.detect",
        "amplfi.pe",
        "gwak.scan",
        "deepclean.check_applicability",
        "deepclean.clean",
        "analysis.reconcile",
        "report.generate",
    } == names


def test_registry_rejects_duplicate_skill(registry):
    skill = registry.get("buoy.analyze")
    with pytest.raises(RegistryError, match="duplicate"):
        SkillRegistry([skill, skill])


def test_registry_rejects_invalid_json_schema(registry):
    skill = copy.deepcopy(registry.get("buoy.analyze"))
    skill.input_schema = {"type": "not-a-json-schema-type"}
    with pytest.raises(RegistryError, match="invalid input_schema"):
        SkillRegistry([skill])


def test_registry_rejects_unknown_plan_skill(registry):
    plan = PlanSpec(
        prompt="test GW150914",
        goal="test",
        tasks=[TaskSpec(id="unknown", skill="missing.skill")],
    )
    with pytest.raises(RegistryError, match="unknown skills"):
        registry.validate_plan_skills(plan)


def test_plan_rejects_dependency_cycle():
    with pytest.raises(ValueError, match="cycle"):
        PlanSpec(
            prompt="test GW150914",
            goal="test",
            tasks=[
                TaskSpec(id="one", skill="data.fetch", depends_on=["two"]),
                TaskSpec(id="two", skill="data.inspect", depends_on=["one"]),
            ],
        )


def test_topological_order_is_stable():
    plan = PlanSpec(
        prompt="test GW150914",
        goal="test",
        tasks=[
            TaskSpec(id="root", skill="data.resolve_event"),
            TaskSpec(id="left", skill="data.fetch", depends_on=["root"]),
            TaskSpec(id="right", skill="data.inspect", depends_on=["root"]),
            TaskSpec(
                id="last",
                skill="report.generate",
                depends_on=["left", "right"],
            ),
        ],
    )
    assert [task.id for task in plan.topological_order()] == [
        "root",
        "left",
        "right",
        "last",
    ]
