"""Web layer: same planner and runtime as the CLI, mock runs end to end."""

from __future__ import annotations

import time

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from ml4gw_agent.web import app as web  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(web, "PASSCODE", "secret")
    monkeypatch.setattr(web.NODE, "host", None)
    return TestClient(web.app)


def test_index_and_health(client):
    assert client.get("/").status_code == 200
    health = client.get("/api/health").json()
    assert health["ok"] is True and health["real_runs"] is False


def test_plan_estimate_and_mock_run(client):
    body = {
        "prompt": "Run Aframe and GWAK on GW150914 and reconcile the two results.",
        "mode": "mock",
    }
    plan = client.post("/api/plan", json=body).json()
    assert [t["id"] for t in plan["plan"]["tasks"]][-1] == "generate_report"
    assert plan["budget"]["allowed"] is True
    job = client.post("/api/run", json=body).json()
    for _ in range(100):
        view = client.get(f"/api/jobs/{job['job_id']}").json()
        if view["status"] in {"completed", "failed"}:
            break
        time.sleep(0.1)
    assert view["status"] == "completed", view.get("error")
    statuses = {t["id"]: t["status"] for t in view["tasks"]}
    assert statuses["reconcile_detections"] == "completed"
    assert "simulated" in view["report"].lower() or view["report"]


def test_guards(client):
    unbounded = client.post("/api/plan", json={"prompt": "Scan all of O3."})
    assert unbounded.status_code == 422
    real = {"prompt": "Analyze GW150914", "mode": "real", "passcode": "secret"}
    assert client.post("/api/run", json=real).status_code == 400  # node not configured
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/records/../../x").status_code in (404, 422)


def test_llm_provider_without_key_is_a_clear_400(client, monkeypatch):
    for var in ("OPENROUTER_API_KEY", "ML4GW_LLM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    response = client.post(
        "/api/plan",
        json={
            "prompt": "Run Aframe detection on GW150914.",
            "mode": "mock",
            "planner": "llm",
            "llm_provider": "openrouter",
        },
    )
    assert response.status_code == 400
    assert "OPENROUTER_API_KEY" in response.json()["detail"]
    health = client.get("/api/health").json()
    assert "llm_providers" in health and health["llm_providers"]["ollama"] is True
