"""LDG data path and DeepClean applicability (no credentials, fake backends)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from ml4gw_agent.adapters import PYTHON_ADAPTERS
from ml4gw_agent.adapters.base import ExecutionContext
from ml4gw_agent.adapters.deepclean import (
    DeepCleanApplicabilityAdapter,
    applicability,
    load_support_table,
)
from ml4gw_agent.adapters.gwosc import GWOSCBackend, GWOSCFetchAdapter
from ml4gw_agent.adapters.ldg import (
    STRAIN_CHANNELS,
    LDGBackend,
    credential_status,
    ldg_preflight,
)
from ml4gw_agent.adapters.strain_io import StrainData, write_strain
from ml4gw_agent.errors import AdapterUnavailableError
from ml4gw_agent.models import TaskSpec
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig

EVENT_TIME = 1126259462.4


def _context(registry, run_dir, skill, task_id, params, records=None):
    return ExecutionContext(
        skill=registry.get(skill),
        task=TaskSpec(id=task_id, skill=skill, parameters=params),
        parameters=params,
        run_dir=run_dir,
        mode="real",
        records=records or {},
        prompt="test",
    )


class _Series:
    def __init__(self, start, end, rate=2048.0):
        self.span = (start, end)
        self.sample_rate = type("Q", (), {"value": rate})()
        self.value = np.random.default_rng(1).normal(size=int((end - start) * rate))


def test_credential_status_rules(tmp_path):
    assert credential_status({})[0] is False
    token = tmp_path / "token"
    token.write_text("x")
    ok, why = credential_status({"BEARER_TOKEN_FILE": str(token)})
    assert ok and "SciToken" in why
    ok, why = credential_status({"X509_USER_PROXY": str(token)})
    assert ok and "X.509" in why
    assert credential_status({"X509_USER_PROXY": str(tmp_path / "nope")})[0] is False
    assert credential_status({"BEARER_TOKEN": "abc"})[0] is True


def test_ldg_preflight_fails_closed_without_credentials(monkeypatch):
    monkeypatch.setattr("ml4gw_agent.adapters.ldg.missing_modules", lambda: [])
    monkeypatch.setattr(
        "ml4gw_agent.adapters.ldg.credential_status",
        lambda: (False, "no IGWN credential found"),
    )
    with pytest.raises(AdapterUnavailableError, match="IGWN credential"):
        ldg_preflight(["H1", "L1"])
    with pytest.raises(AdapterUnavailableError, match="strain channel"):
        ldg_preflight(["H1", "K1"])
    monkeypatch.setattr(
        "ml4gw_agent.adapters.ldg.missing_modules", lambda: ["gwdatafind"]
    )
    with pytest.raises(AdapterUnavailableError, match="uv sync --extra ldg"):
        ldg_preflight(["H1"])


def test_data_fetch_ldg_source_uses_strain_channels(registry, tmp_path, monkeypatch):
    calls = []

    def get_timeseries(channel, start, end):
        calls.append((channel, start, end))
        return _Series(start, end)

    monkeypatch.setattr(
        "ml4gw_agent.adapters.gwosc.load_ldg_backend",
        lambda: LDGBackend(get_timeseries=get_timeseries),
    )
    monkeypatch.setattr(
        "ml4gw_agent.adapters.gwosc.load_gwosc_backend",
        lambda: GWOSCBackend(
            event_gps=lambda e: EVENT_TIME,
            event_detectors=lambda e: ["H1", "L1"],
            fetch_open_data=lambda *a: pytest.fail("public path must not run"),
            get_segments=lambda *a: [],
        ),
    )
    monkeypatch.setattr("ml4gw_agent.adapters.gwosc.ldg_preflight", lambda ifos: None)
    params = {
        "event": "GW150914",
        "source": "ldg",
        "gps_time": EVENT_TIME,
        "ifos": ["H1", "L1"],
        "window_seconds": 8,
        "sample_rate": 2048,
    }
    context = _context(registry, tmp_path, "data.fetch", "fetch_data", params)
    assert GWOSCFetchAdapter().preflight(context) == []
    _, metadata = GWOSCFetchAdapter().describe_invocation(context)
    assert metadata["python_call"] == "gwpy.timeseries.TimeSeries.get"
    outcome = GWOSCFetchAdapter().execute(context)
    assert outcome.outputs["source"] == "ldg"
    assert [c[0] for c in calls] == [STRAIN_CHANNELS["H1"], STRAIN_CHANNELS["L1"]]
    assert outcome.metadata["channels"]["H1"] == "H1:GDS-CALIB_STRAIN_CLEAN"


def test_planner_passes_data_source(registry):
    plan = BaselinePlanner(
        registry, PlannerConfig(data_source="ldg", aframe_revision="a")
    ).plan("Fetch strain data for GW150914 and run Aframe detection.")
    assert {t.id: t for t in plan.tasks}["fetch_data"].parameters["source"] == "ldg"


def _strain(run_dir, source, ifos=("H1", "L1")):
    rng = np.random.default_rng(0)
    data = StrainData(
        ifos=list(ifos),
        series={ifo: rng.normal(size=2048 * 8) * 1e-21 for ifo in ifos},
        t0=EVENT_TIME - 6.4,
        sample_rate=2048.0,
        event_time=EVENT_TIME,
        source=source,
        event="GW150914",
    )
    return write_strain(run_dir / "artifacts" / "fetch_data" / "strain.hdf5", data)


def test_applicability_rules():
    table = {
        "configurations": [
            {
                "ifo": "H1",
                "gps_start": 1e9,
                "gps_end": 2e9,
                "witness_channels": ["H1:PEM-CS_MAG_LVEA_VERTEX_X_DQ"],
                "model_revision": "deadbeef",
                "coupling_config": "h1-60hz.yaml",
            }
        ]
    }
    ok, reasons, cfg = applicability(
        source="gwosc", ifos=["H1"], t0=1.1e9, gps_end=1.1e9 + 128, table=table
    )
    assert ok is False and any("public" in r for r in reasons) and cfg is None
    ok, reasons, cfg = applicability(
        source="ldg", ifos=["H1"], t0=1.1e9, gps_end=1.1e9 + 128, table=table
    )
    assert ok is True and reasons == [] and cfg["model_revision"] == "deadbeef"
    ok, reasons, _ = applicability(
        source="ldg", ifos=["H1", "L1"], t0=1.1e9, gps_end=1.1e9 + 128, table=table
    )
    assert ok is False and any("covers L1" in r for r in reasons)
    ok, reasons, _ = applicability(
        source="ldg", ifos=["H1"], t0=3e9, gps_end=3e9 + 128, table=table
    )
    assert ok is False and any("covers H1" in r for r in reasons)


def test_shipped_support_table_is_empty_and_public_data_is_inapplicable(
    registry, tmp_path
):
    assert load_support_table()["configurations"] == []
    assert PYTHON_ADAPTERS["deepclean_applicability"] is DeepCleanApplicabilityAdapter
    path = _strain(tmp_path, "gwosc")
    params = {
        "event": "GW150914",
        "strain_artifact": str(path.relative_to(tmp_path)),
        "ifos": ["H1", "L1"],
    }
    context = _context(
        registry, tmp_path, "deepclean.check_applicability", "check_deepclean", params
    )
    adapter = DeepCleanApplicabilityAdapter()
    assert adapter.probe() == "available"
    outcome = adapter.execute(context)
    assert outcome.outputs["applicable"] is False
    assert outcome.outputs["simulated"] is False
    assert outcome.outputs["model_revision"] is None
    assert any("public" in r for r in outcome.outputs["reasons"])
    assert any("covers H1" in r for r in outcome.outputs["reasons"])
    record = json.loads(outcome.artifacts[0].read_text())
    assert record["strain_source"] == "gwosc"
    assert outcome.metadata["configurations_reviewed"] == 0
