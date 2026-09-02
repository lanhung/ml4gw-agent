import json

from ml4gw_agent.cli import main


def test_cli_lists_skills_as_json(capsys):
    assert main(["skills", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(item["name"] == "buoy.analyze" for item in payload)


def test_cli_plans_to_file(tmp_path):
    output = tmp_path / "plan.json"
    assert main(["plan", "Analyze GW150914", "--output", str(output)]) == 0
    payload = json.loads(output.read_text())
    assert payload["tasks"][1]["skill"] == "buoy.analyze"


def test_cli_runs_mock(tmp_path, capsys):
    assert (
        main(
            [
                "run",
                "Analyze GW150914",
                "--mode",
                "mock",
                "--runs-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["report"]


def test_cli_reports_planning_error(capsys):
    assert main(["plan", "Scan all O3"]) == 2
    assert "No supported event" in capsys.readouterr().err


def test_doctor_mock_is_ready(capsys):
    assert main(["doctor", "--mode", "mock"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["v0_buoy_ready"] is True


def test_cli_validates_and_runs_saved_plan(tmp_path, capsys):
    plan_file = tmp_path / "plan.json"
    assert main(["plan", "Analyze GW150914", "--output", str(plan_file)]) == 0
    capsys.readouterr()
    assert main(["validate-plan", str(plan_file)]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["valid"] is True
    assert (
        main(
            [
                "run-plan",
                str(plan_file),
                "--mode",
                "mock",
                "--runs-dir",
                str(tmp_path / "runs"),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "completed"
