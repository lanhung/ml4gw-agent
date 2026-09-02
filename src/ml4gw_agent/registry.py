from __future__ import annotations

from collections.abc import Iterable
from importlib import resources
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError as PydanticValidationError

from .errors import RegistryError
from .models import PlanSpec, SkillSpec


class SkillRegistry:
    """Validated, immutable-by-convention map of scientific capabilities."""

    def __init__(self, skills: Iterable[SkillSpec]):
        self._skills: dict[str, SkillSpec] = {}
        for skill in skills:
            if skill.name in self._skills:
                raise RegistryError(f"duplicate skill name: {skill.name}")
            self._validate_json_schemas(skill)
            self._skills[skill.name] = skill

    @classmethod
    def from_directory(cls, directory: Path) -> SkillRegistry:
        if not directory.is_dir():
            raise RegistryError(f"skill directory does not exist: {directory}")

        skills: list[SkillSpec] = []
        paths = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])
        if not paths:
            raise RegistryError(f"no skill manifests found in {directory}")

        for path in paths:
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8"))
                skills.append(SkillSpec.model_validate(payload))
            except (OSError, yaml.YAMLError, PydanticValidationError) as exc:
                raise RegistryError(f"invalid skill manifest {path}: {exc}") from exc
        return cls(skills)

    @staticmethod
    def _validate_json_schemas(skill: SkillSpec) -> None:
        for label, schema in (
            ("input_schema", skill.input_schema),
            ("output_schema", skill.output_schema),
        ):
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                raise RegistryError(
                    f"{skill.name} has invalid {label}: {exc.message}"
                ) from exc

    def get(self, name: str) -> SkillSpec:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise RegistryError(f"unknown skill: {name}") from exc

    def all(self) -> list[SkillSpec]:
        return [self._skills[name] for name in sorted(self._skills)]

    def __contains__(self, name: str) -> bool:
        return name in self._skills

    def __len__(self) -> int:
        return len(self._skills)

    def validate_plan_skills(self, plan: PlanSpec) -> None:
        unknown = sorted({task.skill for task in plan.tasks if task.skill not in self})
        if unknown:
            raise RegistryError(f"plan contains unknown skills: {unknown}")


def load_default_registry() -> SkillRegistry:
    root = resources.files("ml4gw_agent.skill_manifests")
    with resources.as_file(root) as path:
        return SkillRegistry.from_directory(Path(path))
