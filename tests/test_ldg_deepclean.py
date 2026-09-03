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
    LDGBackend,
    credential_status,
    epoch_for,
    fetch_ldg_strain,
    ldg_preflight,
)
from ml4gw_agent.adapters.strain_io import StrainData, write_strain
from ml4gw_agent.errors import AdapterError, AdapterUnavailableError
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


def test_data_fetch_ldg_source_downloads_frames_with_token(
    registry, tmp_path, monkeypatch
):
    token = tmp_path / "token"
    token.write_text("eyJ.fake.token")
    monkeypatch.setenv("BEARER_TOKEN_FILE", str(token))
    calls = {"find": [], "download": [], "read": []}

    def find_urls(site, frametype, start, end, urltype="https"):
        if urltype == "file":
            return []  # not on an LDG node
        calls["find"].append((site, frametype, start, end, urltype))
        return [f"https://osdf-director.osg-htc.org/igwn/{frametype}-{start}.gwf"]

    def download(url, tok, target):
        assert tok == "eyJ.fake.token"
        calls["download"].append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"IGWD")
        return target

    def read(files, channel, start, end):
        calls["read"].append((tuple(files), channel))
        return _Series(start, end)

    monkeypatch.setattr(
        "ml4gw_agent.adapters.gwosc.load_ldg_backend",
        lambda: LDGBackend(
            find_urls=find_urls, download=download, read_timeseries=read
        ),
    )
    monkeypatch.setattr("ml4gw_agent.adapters.ldg.DEFAULT_CACHE", tmp_path / "cache")
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
    assert "OSDF" in metadata["data_source"]
    outcome = GWOSCFetchAdapter().execute(context)
    assert outcome.outputs["source"] == "ldg"
    # O1 epoch: HOFT_C02 frames and the DCS C02 channel
    assert [c[1] for c in calls["find"]] == ["H1_HOFT_C02", "L1_HOFT_C02"]
    assert [c[1] for c in calls["read"]] == [
        "H1:DCS-CALIB_STRAIN_C02",
        "L1:DCS-CALIB_STRAIN_C02",
    ]
    assert len(calls["download"]) == 2
    prov = outcome.metadata["ldg"]["H1"]
    assert prov["frametype"] == "H1_HOFT_C02" and prov["urls"][0].startswith("https")


def test_epoch_map_and_missing_token(monkeypatch):
    assert epoch_for("H1", 1126259462.4) == ("H1_HOFT_C02", "H1:DCS-CALIB_STRAIN_C02")
    assert epoch_for("L1", 1242442967.4) == ("L1_HOFT_C01", "L1:DCS-CALIB_STRAIN_C01")
    assert epoch_for("H1", 1400000000.0) == ("H1_HOFT_C00", "H1:GDS-CALIB_STRAIN_CLEAN")
    with pytest.raises(AdapterError, match="no reviewed frame type"):
        epoch_for("H1", 1150000000.0)
    for key in ("BEARER_TOKEN_FILE", "SCITOKEN_FILE", "BEARER_TOKEN", "SCITOKEN"):
        monkeypatch.delenv(key, raising=False)
    backend = LDGBackend(
        find_urls=lambda *a, **k: [], download=None, read_timeseries=None
    )
    with pytest.raises(AdapterUnavailableError, match="IGWN credential"):
        fetch_ldg_strain(backend, "H1", 1126259366.0, 1126259494.0)
    monkeypatch.setenv("BEARER_TOKEN", "abc")
    with pytest.raises(AdapterError, match="no H1_HOFT_C02 frames"):
        fetch_ldg_strain(backend, "H1", 1126259366.0, 1126259494.0)


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


def test_normalize_units_restores_seconds_and_hertz():
    pytest.importorskip("gwpy")
    from astropy import units as u
    from gwpy.timeseries import TimeSeries

    from ml4gw_agent.adapters.ldg import normalize_units

    raw = TimeSeries(np.arange(8.0), x0=100.0, dx=0.5)  # dimensionless axis
    fixed = normalize_units(raw, "H1:TEST")
    assert fixed.sample_rate == 2.0 * u.Hz
    assert float(fixed.t0.value) == 100.0
    assert fixed.channel.name == "H1:TEST"
    assert np.array_equal(fixed.value, raw.value)
    resampled = fixed.resample(1.0)
    assert resampled.sample_rate == 1.0 * u.Hz


def test_read_gwf_channel_prefers_framel(monkeypatch):
    pytest.importorskip("gwpy")
    import sys
    import types

    from ml4gw_agent.adapters.ldg import read_gwf_channel

    fake = types.ModuleType("framel")
    fake.frgetvect1d = lambda path, channel: (
        np.arange(16.0),
        1126259366.0,
        0.0,
        0.5,
        "s",
        "strain",
    )
    monkeypatch.setitem(sys.modules, "framel", fake)
    series = read_gwf_channel("/nonexistent.gwf", "H1:TEST")
    assert float(series.t0.value) == 1126259366.0
    assert float(series.sample_rate.value) == 2.0
    assert series.channel.name == "H1:TEST"
    cropped = series.crop(1126259368.0, 1126259370.0)
    assert cropped.shape == (4,)


def test_ldg_uses_local_frames_when_datafind_returns_files(tmp_path, monkeypatch):
    frame = tmp_path / "H-H1_HOFT_C02-1126256640-4096.gwf"
    frame.write_bytes(b"IGWD")
    monkeypatch.setenv("BEARER_TOKEN", "abc")
    calls = []

    def find_urls(site, frametype, start, end, urltype="https"):
        calls.append(urltype)
        return [f"file://{frame}"] if urltype == "file" else ["https://x/y.gwf"]

    backend = LDGBackend(
        find_urls=find_urls,
        download=lambda *a: pytest.fail("must not download"),
        read_timeseries=lambda files, channel, start, end: (files, channel),
    )
    series, prov = fetch_ldg_strain(backend, "H1", 1126259366.0, 1126259494.0)
    assert calls == ["file"]
    assert series == ([str(frame)], "H1:DCS-CALIB_STRAIN_C02")
    assert prov["files"] == [str(frame)]
