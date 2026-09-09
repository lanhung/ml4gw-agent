"""Event resolution: GWTC table, GraceDB, UTC strings."""

from __future__ import annotations

import pytest

from ml4gw_agent.adapters.events import (
    gracedb_lookup,
    gwtc_by_gracedb,
    gwtc_lookup,
    resolve,
    utc_to_gps,
)
from ml4gw_agent.planning import EVENT_PATTERN, BaselinePlanner


def test_gwtc_table_lookups():
    rec = gwtc_lookup("GW231123_135430")
    assert rec and rec["gracedb"] == "S231123cg" and abs(rec["GPS"] - 1384782888.6) < 1
    assert gwtc_lookup("GW150914")["name"] == "GW150914"
    assert gwtc_by_gracedb("S231123cg")["name"] == "GW231123_135430"
    assert gwtc_lookup("GW999999") is None


def test_utc_and_pattern():
    assert abs(utc_to_gps("2023-11-23 13:54:30 UTC") - 1384782888) < 1
    assert EVENT_PATTERN.search("Analyse the event at 2023-11-23T13:54:30Z please")
    event = BaselinePlanner.extract_event("Run Aframe on 2023-11-23 13:54:30 UTC.")
    assert event.startswith("2023-11-23")
    out = resolve("2023-11-23 13:54:30", online=False)
    assert out["event_kind"] == "gps" and abs(out["catalog_time"] - 1384782888) < 1


def test_gracedb_lookup_with_fake_fetch():
    def fetch(url):
        assert url.endswith("/superevents/S251017di/")
        return {
            "t_0": 1444770508.1,
            "far": 7.04e-8,
            "instruments": "H1,L1",
            "labels": ["ADVNO", "PE_READY"],
            "gw_id": None,
            "preferred_event_data": {"pipeline": "gstlal", "group": "CBC"},
        }

    rec = gracedb_lookup("S251017di", fetch=fetch)
    assert rec["retracted"] and rec["instruments"] == ["H1", "L1"]
    out = resolve("S251017di", online=True, fetch=fetch)
    assert out["retracted"] is True and out["resolution_source"] == "gracedb"
    assert abs(out["far_per_year"] - 7.04e-8 * 365.25 * 86400) < 1e-3
    assert "retracted" in out["resolution_note"]


def test_resolve_offline_and_failures():
    off = resolve("S231123cg", online=False)
    assert off["catalog_time"] and off["resolution_source"] == "gwtc_table"
    unknown = resolve("S999999zz", online=False)
    assert unknown["catalog_time"] is None and "offline" in unknown["resolution_note"]

    def broken(url):
        raise OSError("no network")

    out = resolve("S999999zz", online=True, fetch=broken)
    assert (
        out["catalog_time"] is None
        and "GraceDB lookup failed" in out["resolution_note"]
    )
    assert resolve("1126259462.4", online=False)["catalog_time"] == pytest.approx(
        1126259462.4
    )


def test_gracedb_instruments_fallback_to_preferred_event():
    def fetch(url):
        return {
            "t_0": 1.0,
            "far": None,
            "instruments": "",
            "labels": [],
            "preferred_event_data": {
                "instruments": "H1,L1",
                "far": 1e-9,
                "pipeline": "x",
            },
        }

    rec = gracedb_lookup("S000000a", fetch=fetch)
    assert rec["instruments"] == ["H1", "L1"] and rec["far"] == 1e-9


def test_lookup_route_and_adapter(registry, tmp_path):
    from ml4gw_agent.planning import BaselinePlanner, PlannerConfig

    planner = BaselinePlanner(registry, PlannerConfig())
    plan = planner.plan("What is the mass of GW231123_135430 and how far away is it?")
    assert [t.skill for t in plan.tasks] == [
        "data.resolve_event",
        "catalog.lookup",
        "report.generate",
    ]
    zh = planner.plan("查一下 S231123cg 的质量是多少？")
    assert zh.tasks[1].skill == "catalog.lookup"
    # analysis words win over lookup words
    mixed = planner.plan("Tell me about GW150914 and run Aframe detection.")
    assert "aframe.detect" in [t.skill for t in mixed.tasks]
    assert "catalog.lookup" not in [t.skill for t in mixed.tasks]


def test_catalog_lookup_adapter_offline_table(registry, tmp_path, monkeypatch):
    from ml4gw_agent.adapters.base import ExecutionContext
    from ml4gw_agent.adapters.builtin import BuiltinAdapter
    from ml4gw_agent.models import TaskSpec

    def broken(url):
        raise OSError("offline")

    monkeypatch.setattr("ml4gw_agent.adapters.events.fetch_json", broken)
    params = {"event": "GW231123_135430", "question": "mass?"}
    context = ExecutionContext(
        skill=registry.get("catalog.lookup"),
        task=TaskSpec(id="lookup", skill="catalog.lookup", parameters=params),
        parameters=params,
        run_dir=tmp_path,
        mode="mock",
        records={},
        prompt="mass?",
    )
    out = BuiltinAdapter("catalog_lookup").execute(context).outputs
    assert out["mass_1_source"] == 137.0 and out["gracedb_id"] == "S231123cg"
    assert "137.0 Msun" in out["answer"] and out["simulated"] is False
    assert any("GWOSC catalog" in s for s in out["sources"])
