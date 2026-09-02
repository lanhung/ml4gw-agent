from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .models import SkillSpec, ValidationRecord


def _format_errors(errors: list[Any]) -> str:
    if not errors:
        return "schema validation passed"
    pieces = []
    for error in errors[:5]:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        pieces.append(f"{location}: {error.message}")
    if len(errors) > 5:
        pieces.append(f"and {len(errors) - 5} more error(s)")
    return "; ".join(pieces)


def validate_inputs(skill: SkillSpec, inputs: dict[str, Any]) -> ValidationRecord:
    errors = sorted(
        Draft202012Validator(skill.input_schema).iter_errors(inputs),
        key=lambda error: list(error.absolute_path),
    )
    return ValidationRecord(
        check="input_json_schema",
        passed=not errors,
        message=_format_errors(errors),
    )


def validate_outputs(
    skill: SkillSpec, outputs: dict[str, Any], run_dir: Path
) -> list[ValidationRecord]:
    errors = sorted(
        Draft202012Validator(skill.output_schema).iter_errors(outputs),
        key=lambda error: list(error.absolute_path),
    )
    records = [
        ValidationRecord(
            check="output_json_schema",
            passed=not errors,
            message=_format_errors(errors),
        )
    ]

    root = run_dir.resolve()
    for rule in skill.validations:
        value = outputs.get(rule.target)
        if rule.kind == "output_field":
            passed = rule.target in outputs and value is not None
            message = (
                f"output field '{rule.target}' is present"
                if passed
                else f"output field '{rule.target}' is missing or null"
            )
        else:
            passed = isinstance(value, str)
            message = f"output '{rule.target}' is not a path string"
            if passed:
                candidate = Path(value)
                candidate = candidate if candidate.is_absolute() else root / candidate
                resolved = candidate.resolve()
                try:
                    resolved.relative_to(root)
                except ValueError:
                    passed = False
                    message = f"artifact path for '{rule.target}' escaped run directory"
                else:
                    if rule.kind == "artifact_exists":
                        passed = resolved.is_file() and not candidate.is_symlink()
                        message = (
                            f"artifact '{rule.target}' exists"
                            if passed
                            else f"artifact '{rule.target}' is missing or unsafe"
                        )
                    elif rule.kind == "artifact_nonempty":
                        passed = (
                            resolved.is_file()
                            and not candidate.is_symlink()
                            and resolved.stat().st_size > 0
                        )
                        message = (
                            f"artifact '{rule.target}' is non-empty"
                            if passed
                            else (
                                f"artifact '{rule.target}' is missing, empty, or unsafe"
                            )
                        )
        records.append(
            ValidationRecord(
                check=f"{rule.kind}:{rule.target}", passed=passed, message=message
            )
        )
    return records
