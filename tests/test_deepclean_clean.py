"""deepclean.clean adapter and witness handling with a fake model backend."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from ml4gw_agent.adapters import PYTHON_ADAPTERS
from ml4gw_agent.adapters import deepclean as dc
from ml4gw_agent.adapters.base import ExecutionContext
from ml4gw_agent.adapters.deepclean import (
    DeepCleanApplicabilityAdapter,
    DeepCleanCleanAdapter,
    align_witnesses,
    load_coupling,
    read_witnesses,
    write_witnesses,
)
from ml4gw_agent.adapters.strain_io import StrainData, read_strain, write_strain
from ml4gw_agent.errors import AdapterError, AdapterUnavailableError
from ml4gw_agent.models import TaskSpec

T0 = 1421344000.0
RATE = 2048.0
WITNESS = "H1:PEM-CS_MAINSMON_EBAY_1_DQ"


def _context(registry, run_dir, skill, task_id, params):
    return ExecutionContext(
        skill=registry.get(skill),
        task=TaskSpec(id=task_id, skill=skill, parameters=params),
        parameters=params,
        run_dir=run_dir,
        mode="real",
        records={},
        prompt="test",
    )


def _strain(run_dir, source="nds2", seconds=16):
    rng = np.random.default_rng(1)
    t = np.arange(int(seconds * RATE)) / RATE
    series = {
        ifo: rng.normal(size=t.size) * 1e-21 + 5e-21 * np.sin(2 * np.pi * 60 * t)
        for ifo in ("H1", "L1")
    }
    data = StrainData(
        ifos=["H1", "L1"],
        series=series,
        t0=T0,
        sample_rate=RATE,
        event_time=T0 + 8,
        source=source,
        event="S250119cv",
    )
    return write_strain(run_dir / "artifacts" / "fetch_data" / "strain.hdf5", data)


def _model_dir(tmp_path, **overrides):
    model_dir = tmp_path / "models"
    (model_dir / "H1_60Hz").mkdir(parents=True)
    weights = model_dir / "H1_60Hz" / "deepclean.pt"
    weights.write_bytes(b"fake-weights")
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    record = {
        "ifo": "H1",
        "witness_channels": [WITNESS],
        "freq_low": 55.0,
        "freq_high": 65.0,
        "weights_file": "deepclean.pt",
        "weights_sha256": digest,
        "gps_start": T0,
        "gps_end": T0 + 5120,
        "train_seconds": 4096,
        "best_val_asd_ratio": 0.3,
        "held_out_metrics": {"in_band_asd_ratio": 0.31},
        "reference": "test",
    }
    record.update(overrides)
    (model_dir / "H1_60Hz" / "training_record.json").write_text(json.dumps(record))
    return model_dir, digest


def _fake_backend(monkeypatch, *, ratio=0.4, outside=1.0):
    def fake_load(path):
        return {"config": {"sample_rate": 4096.0}, "path": str(path)}

    def fake_clean(strain, witnesses, weights, *, device="cpu"):
        assert witnesses.shape == (1, strain.shape[0])
        assert weights["config"]["sample_rate"] == 4096.0
        return strain * ratio, {
            "in_band_asd_ratio": ratio,
            "in_band_asd_ratio_min": ratio / 2,
            "out_of_band_asd_ratio": outside,
            "freq_low": 55.0,
            "freq_high": 65.0,
        }

    monkeypatch.setattr(dc, "load_weights", fake_load)
    monkeypatch.setattr(dc, "clean_strain", fake_clean)


def test_witness_artifact_roundtrip_and_alignment(tmp_path):
    data = np.arange(8192 * 20, dtype="f8")
    path = write_witnesses(tmp_path / "w.hdf5", {WITNESS: (data, T0 - 2, 8192.0)})
    back = read_witnesses(path)
    assert back[WITNESS][1] == T0 - 2 and back[WITNESS][2] == 8192.0
    stacked = align_witnesses(back, [WITNESS], T0, 4096 * 16, 4096.0)
    assert stacked.shape == (1, 4096 * 16)
    # the first aligned sample sits two seconds into the witness series
    assert abs(stacked[0, 0] - data[2 * 8192]) < 8
    with pytest.raises(AdapterError, match="lacks channel"):
        align_witnesses(back, ["H1:OTHER"], T0, 10, 4096.0)
    with pytest.raises(AdapterError, match="covers"):
        align_witnesses(back, [WITNESS], T0 - 10, 10, 4096.0)
    with pytest.raises(AdapterError, match="does not exist"):
        read_witnesses(tmp_path / "missing.hdf5")


def test_load_coupling_verifies_the_pinned_revision(tmp_path):
    model_dir, digest = _model_dir(tmp_path)
    record, weights = load_coupling(model_dir, "H1_60Hz/training_record.json", digest)
    assert record["ifo"] == "H1" and weights.name == "deepclean.pt"
    with pytest.raises(AdapterError, match="do not match"):
        load_coupling(model_dir, "H1_60Hz/training_record.json", "0" * 64)
    with pytest.raises(AdapterUnavailableError, match="not found"):
        load_coupling(model_dir, "nope/training_record.json", digest)
    (model_dir / "H1_60Hz" / "deepclean.pt").unlink()
    with pytest.raises(AdapterUnavailableError, match="weights missing"):
        load_coupling(model_dir, "H1_60Hz/training_record.json", digest)


def test_clean_adapter_subtracts_only_the_named_detector(
    registry, tmp_path, monkeypatch
):
    model_dir, digest = _model_dir(tmp_path)
    monkeypatch.setenv("ML4GW_DEEPCLEAN_MODEL_DIR", str(model_dir))
    _fake_backend(monkeypatch, ratio=0.4)
    strain_path = _strain(tmp_path)
    witness = write_witnesses(
        tmp_path / "artifacts" / "check_deepclean" / "witnesses.hdf5",
        {WITNESS: (np.zeros(8192 * 20), T0 - 2, 8192.0)},
    )
    params = {
        "strain_artifact": "artifacts/fetch_data/strain.hdf5",
        "witness_artifact": str(witness.relative_to(tmp_path)),
        "coupling_config": "H1_60Hz/training_record.json",
        "model_revision": digest,
        "ifo": "H1",
    }
    context = _context(registry, tmp_path, "deepclean.clean", "clean_deepclean", params)
    adapter = PYTHON_ADAPTERS["deepclean_clean"]()
    assert isinstance(adapter, DeepCleanCleanAdapter)
    assert adapter.probe() == "available"
    assert adapter.describe_invocation(context)[1]["model_dir"] == str(model_dir)
    outcome = adapter.execute(context)
    assert outcome.outputs["applicable"] is True
    assert outcome.outputs["simulated"] is False
    original = read_strain(strain_path)
    cleaned = read_strain(tmp_path / outcome.outputs["cleaned_strain_artifact"])
    assert cleaned.ifos == ["H1", "L1"] and cleaned.sample_rate == RATE
    assert cleaned.t0 == T0 and cleaned.event == "S250119cv"
    assert np.array_equal(cleaned.series["L1"], original.series["L1"])
    assert not np.array_equal(cleaned.series["H1"], original.series["H1"])
    # fake backend keeps 40% of the strain, so the residual is scaled down
    assert np.isclose(
        cleaned.series["H1"].std(), 0.4 * original.series["H1"].std(), rtol=0.2
    )
    diagnostics = json.loads(
        (tmp_path / outcome.outputs["subtraction_diagnostics"]).read_text()
    )
    assert diagnostics["asd_ratios"]["in_band_asd_ratio"] == 0.4
    assert diagnostics["improved_in_band"] and diagnostics["out_of_band_preserved"]
    assert diagnostics["model_revision"] == digest
    assert "witness channels only" in diagnostics["signal_preservation"]
    assert outcome.metadata["in_band_asd_ratio"] == 0.4


def test_clean_adapter_reports_inapplicable_when_nothing_improves(
    registry, tmp_path, monkeypatch
):
    model_dir, digest = _model_dir(tmp_path)
    monkeypatch.setenv("ML4GW_DEEPCLEAN_MODEL_DIR", str(model_dir))
    _fake_backend(monkeypatch, ratio=1.05, outside=1.2)
    _strain(tmp_path)
    witness = write_witnesses(
        tmp_path / "artifacts" / "check_deepclean" / "witnesses.hdf5",
        {WITNESS: (np.zeros(8192 * 20), T0 - 2, 8192.0)},
    )
    params = {
        "strain_artifact": "artifacts/fetch_data/strain.hdf5",
        "witness_artifact": str(witness.relative_to(tmp_path)),
        "coupling_config": "H1_60Hz/training_record.json",
        "model_revision": digest,
    }
    context = _context(registry, tmp_path, "deepclean.clean", "clean_deepclean", params)
    outcome = DeepCleanCleanAdapter().execute(context)
    assert outcome.outputs["applicable"] is False
    with pytest.raises(AdapterError, match="is for H1, not L1"):
        DeepCleanCleanAdapter().execute(
            _context(
                registry,
                tmp_path,
                "deepclean.clean",
                "clean_deepclean",
                {**params, "ifo": "L1"},
            )
        )


def test_applicability_fetches_witnesses_and_fails_closed(
    registry, tmp_path, monkeypatch
):
    table = {
        "configurations": [
            {
                "ifo": "H1",
                "gps_start": T0 - 100,
                "gps_end": T0 + 5000,
                "witness_channels": [WITNESS],
                "freq_low": 55.0,
                "freq_high": 65.0,
                "sample_rate": 4096.0,
                "coupling_config": "H1_60Hz/training_record.json",
                "model_revision": "abc123",
            }
        ]
    }
    monkeypatch.setattr(dc, "load_support_table", lambda: table)
    calls = []

    def fake_fetch(ifo, channel, start, end):
        calls.append((ifo, channel, start, end))
        n = int((end - start) * 8192)
        return np.ones(n), float(start), 8192.0

    monkeypatch.setattr(dc, "fetch_witness", fake_fetch)
    _strain(tmp_path)
    params = {
        "event": "S250119cv",
        "strain_artifact": "artifacts/fetch_data/strain.hdf5",
        "ifos": ["H1"],
    }
    context = _context(
        registry, tmp_path, "deepclean.check_applicability", "check_deepclean", params
    )
    outcome = DeepCleanApplicabilityAdapter().execute(context)
    assert outcome.outputs["applicable"] is True
    assert outcome.outputs["ifo"] == "H1"
    assert outcome.outputs["model_revision"] == "abc123"
    assert (
        outcome.outputs["witness_artifact"]
        == "artifacts/check_deepclean/witnesses.hdf5"
    )
    assert calls == [("H1", WITNESS, T0, T0 + 16)]
    assert (
        read_witnesses(tmp_path / outcome.outputs["witness_artifact"])[WITNESS][2]
        == 8192.0
    )
    assert len(outcome.artifacts) == 2

    def broken_fetch(ifo, channel, start, end):
        raise RuntimeError("NDS2 unreachable")

    monkeypatch.setattr(dc, "fetch_witness", broken_fetch)
    outcome = DeepCleanApplicabilityAdapter().execute(context)
    assert outcome.outputs["applicable"] is False
    assert outcome.outputs["witness_artifact"] is None
    assert outcome.outputs["model_revision"] is None
    assert any("NDS2 unreachable" in r for r in outcome.outputs["reasons"])


def test_gwak_threshold_lookup_mirrors_aframe(registry, monkeypatch):
    from ml4gw_agent.calibration import gwak_threshold, load_gwak_table
    from ml4gw_agent.planning import BaselinePlanner, PlannerConfig

    assert load_gwak_table()["revisions"] == {} or load_gwak_table()["revisions"]
    table = {
        "revisions": {
            "rev1": {
                "livetime_seconds": 5 * 86400.0,
                "thresholds_by_far_per_year": {"365.25": 12.5, "12": 14.0},
                "source": "test study",
            }
        }
    }
    found = gwak_threshold("rev1", 365.25, table)
    assert found is not None and found.threshold == 12.5
    assert found.source == "test study"
    assert gwak_threshold("rev1", 1.0, table) is None  # livetime cannot resolve
    assert gwak_threshold(None, 365.25, table) is None

    config = PlannerConfig(gwak_revision="rev1", gwak_far_per_year=365.25)
    monkeypatch.setattr(
        "ml4gw_agent.planning.gwak_threshold",
        lambda revision, far: gwak_threshold(revision, far, table),
    )
    plan = BaselinePlanner(registry, config).plan("Scan GW150914 with GWAK")
    run_gwak = next(t for t in plan.tasks if t.id == "run_gwak")
    assert run_gwak.parameters["threshold"] == 12.5
    assert run_gwak.parameters["threshold_calibration"]["revision"] == "rev1"
    assert not any("No background calibration" in w for w in plan.warnings)

    explicit = PlannerConfig(gwak_revision="rev1", gwak_threshold=3.0)
    plan = BaselinePlanner(registry, explicit).plan("Scan GW150914 with GWAK")
    run_gwak = next(t for t in plan.tasks if t.id == "run_gwak")
    assert run_gwak.parameters["threshold"] == 3.0
    assert run_gwak.parameters["threshold_calibration"] is None

    plan = BaselinePlanner(registry, PlannerConfig(gwak_revision="other")).plan(
        "Scan GW150914 with GWAK"
    )
    assert any("No background calibration" in w for w in plan.warnings)


def test_far_at_score_reads_the_curve():
    from ml4gw_agent.calibration import far_at_score, load_gwak_table

    table = {
        "revisions": {
            "rev1": {"far_curve": [[10.0, 1000.0], [15.0, 100.0], [25.0, 1.0]]}
        }
    }
    assert far_at_score("gwak", "rev1", 9.0, table) is None
    assert far_at_score("gwak", "rev1", 10.0, table) == 1000.0
    assert far_at_score("gwak", "rev1", 14.9, table) == 1000.0
    assert far_at_score("gwak", "rev1", 15.35, table) == 100.0
    assert far_at_score("gwak", "rev1", 30.0, table) == 1.0
    assert far_at_score("gwak", "nope", 30.0, table) is None
    assert far_at_score("gwak", None, 30.0, table) is None
    shipped = load_gwak_table()["revisions"]
    for entry in shipped.values():
        curve = entry["far_curve"]
        assert all(
            a[0] < b[0] and a[1] >= b[1] for a, b in zip(curve, curve[1:], strict=False)
        )
