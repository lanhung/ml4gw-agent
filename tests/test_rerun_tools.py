"""Leak check and rate-limit retry helpers used by rerun_mcp_matrices.sh."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_no_secrets as leaks  # noqa: E402
import retry_rate_limited as retry  # noqa: E402


def test_leak_check_finds_raw_and_escaped_credentials(tmp_path):
    key_file = tmp_path / "glm.md"
    key_file.write_text("abc123.secret/XYZ\n")
    proxy = tmp_path / "config.yaml"
    proxy.write_text("api-keys:\n  - proxy-key-0001\n")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "clean.json").write_text(json.dumps({"ok": True}))
    (evidence / "raw.log").write_text("Authorization: Bearer proxy-key-0001")
    (evidence / "escaped.json").write_text(json.dumps({"k": "abc123.secret/XYZ"}))

    secrets = leaks.collect_secrets(
        ["UNSET_VAR", "SET_VAR"], [key_file], [proxy], environ={"SET_VAR": "env-9"}
    )
    assert secrets == ["env-9", "abc123.secret/XYZ", "proxy-key-0001"]
    found = leaks.leaking_files(leaks.files_under([evidence]), secrets)
    assert sorted(p.name for p in found) == ["escaped.json", "raw.log"]

    assert leaks.main(["--key-file", str(key_file), str(evidence / "clean.json")]) == 0
    assert leaks.main(["--proxy-config", str(proxy), str(evidence)]) == 1
    assert leaks.main(["--env", "NOT_SET_ANYWHERE", str(evidence)]) == 2


def _row(model, errors, passed):
    return {
        "model": model,
        "passed": passed,
        "total": len(errors),
        "assertions_passed": passed * 7,
        "assertions_total": len(errors) * 7,
        "cases": [{"id": f"c{i}", "error": e} for i, e in enumerate(errors)],
    }


def test_only_rate_limited_models_are_retried_and_merged():
    summary = {
        "models": [
            _row("glm-a", [None, None], 2),
            _row("glm-b", ["LLM HTTP 429 (code 1302)", None], 1),
            _row("glm-c", ["LLM HTTP 408", None], 1),
        ]
    }
    summary["models"].append({"model": "glm-d", "error": "LLM HTTP 429", "passed": 0})
    assert retry.rate_limited_models(summary) == ["glm-b", "glm-d"]

    replacement = _row("glm-b", [None, None], 2) | {"retry": {"wait_seconds": 5}}
    merged = retry.effective_summary(summary, {"glm-b": replacement}, "summary.json", 5)
    assert merged["replaced_models"] == ["glm-b"]
    assert [r["model"] for r in merged["models"]] == [
        "glm-a",
        "glm-b",
        "glm-c",
        "glm-d",
    ]
    assert merged["models"][1]["retry"]["wait_seconds"] == 5
    assert merged["models"][2]["cases"][0]["error"] == "LLM HTTP 408"
    assert merged["passed"] == 2 + 2 + 1 + 0
    assert summary["models"][1]["passed"] == 1  # the matrix summary is untouched
