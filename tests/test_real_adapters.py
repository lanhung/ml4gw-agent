"""Tests for the Phase 1b real adapters using fake scientific backends.

No network, GPU, torch, gwpy, or Buoy is required: each adapter reaches its
upstream library through one loader function that the tests replace.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from ml4gw_agent.adapters.aframe import (
    AframeAdapter,
    TorchBackend,
    load_aframe_backend,
)
from ml4gw_agent.adapters.amplfi import (
    AmplfiAdapter,
    AmplfiBackend,
    credible_intervals,
    load_amplfi_backend,
)
from ml4gw_agent.adapters.base import ExecutionContext
from ml4gw_agent.adapters.gwosc import (
    GWOSCBackend,
    GWOSCFetchAdapter,
    load_gwosc_backend,
    window_bounds,
)
from ml4gw_agent.adapters.strain import StrainInspectAdapter
from ml4gw_agent.adapters.strain_io import (
    StrainData,
    read_strain,
    resolve_artifact,
    write_strain,
)
from ml4gw_agent.cli import main
from ml4gw_agent.errors import AdapterError, AdapterUnavailableError
from ml4gw_agent.models import RunStatus, TaskRecord, TaskSpec, TaskStatus
from ml4gw_agent.planning import BaselinePlanner, PlannerConfig
from ml4gw_agent.runtime import AgentRuntime

EVENT_TIME = 1126259462.4
SAMPLE_RATE = 2048.0
DURATION = 8.0


def _context(registry, run_dir, skill, task_id, parameters, mode="real"):
    return ExecutionContext(
        run_dir=run_dir,
        mode=mode,
        task=TaskSpec(id=task_id, skill=skill, parameters=parameters),
        skill=registry.get(skill),
        parameters=parameters,
        records={task_id: TaskRecord(task_id=task_id, skill=skill)},
        prompt="test",
    )


def _strain(run_dir: Path, ifos=("H1", "L1"), **overrides) -> Path:
    rng = np.random.default_rng(0)
    n = int(DURATION * SAMPLE_RATE)
    series = {ifo: rng.normal(size=n) * 1e-21 for ifo in ifos}
    series.update(overrides)
    data = StrainData(
        ifos=list(ifos),
        series=series,
        t0=EVENT_TIME - 6.4,
        sample_rate=SAMPLE_RATE,
        event_time=EVENT_TIME,
        source="test",
        event="GW150914",
    )
    return write_strain(run_dir / "artifacts" / "fetch_data" / "strain.hdf5", data)


# --------------------------------------------------------------------------- #
# strain_io
# --------------------------------------------------------------------------- #


def test_strain_roundtrip_and_ordering(tmp_path):
    path = _strain(tmp_path, ifos=("L1", "H1"))
    data = read_strain(path)
    assert data.ifos == ["H1", "L1"]
    assert data.duration == DURATION
    assert data.gps_end == pytest.approx(data.t0 + DURATION)
    assert data.stacked(["H1", "L1"]).shape == (1, 2, int(DURATION * SAMPLE_RATE))
    with pytest.raises(AdapterError, match="lacks detectors"):
        data.stacked(["H1", "V1"])


def test_strain_reader_rejects_bad_files(tmp_path):
    with pytest.raises(AdapterError, match="does not exist"):
        read_strain(tmp_path / "missing.hdf5")
    bad = tmp_path / "bad.hdf5"
    bad.write_bytes(b"not hdf5")
    with pytest.raises(AdapterError, match="not readable"):
        read_strain(bad)
    with h5py.File(tmp_path / "no_t0.hdf5", "w") as handle:
        handle.create_dataset("H1", data=np.zeros(4))
    with pytest.raises(AdapterError, match="t0"):
        read_strain(tmp_path / "no_t0.hdf5")
    with pytest.raises(AdapterError, match="escaped"):
        resolve_artifact("../outside.hdf5", tmp_path)


def test_write_strain_rejects_unequal_lengths(tmp_path):
    data = StrainData(
        ifos=["H1", "L1"],
        series={"H1": np.zeros(4), "L1": np.zeros(5)},
        t0=0.0,
        sample_rate=1.0,
    )
    with pytest.raises(AdapterError, match="unequal"):
        write_strain(tmp_path / "x.hdf5", data)


# --------------------------------------------------------------------------- #
# data.fetch (GWOSC)
# --------------------------------------------------------------------------- #


class FakeTimeSeries:
    def __init__(self, start, end, rate):
        self.span = (start, end)
        self.sample_rate = SimpleNamespace(value=rate)
        rng = np.random.default_rng(int(start) % 1000)
        self.value = rng.normal(size=int((end - start) * rate)) * 1e-21

    def resample(self, rate):
        return FakeTimeSeries(self.span[0], self.span[1], rate)


def _gwosc_backend(rate=4096.0, segments=None, fetch=None):
    def default_fetch(ifo, start, end):
        return FakeTimeSeries(start, end, rate)

    return GWOSCBackend(
        event_gps=lambda event: EVENT_TIME,
        event_detectors=lambda event: ["H1", "L1"],
        fetch_open_data=fetch or default_fetch,
        get_segments=segments or (lambda flag, start, end: [(start - 10, end + 10)]),
    )


def test_window_bounds_match_buoy_layout():
    start, end = window_bounds(EVENT_TIME, 128, 0.75)
    # Buoy: start = tc - 1.5 * psd_length - (tc % 1) with psd_length = 64.
    assert start == pytest.approx(EVENT_TIME - 96 - 0.4)
    assert end == pytest.approx(start + 128)
    assert start == int(start)


def test_gwosc_fetch_writes_buoy_compatible_artifact(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ml4gw_agent.adapters.gwosc.load_gwosc_backend", lambda: _gwosc_backend()
    )
    context = _context(
        registry,
        tmp_path,
        "data.fetch",
        "fetch_data",
        {
            "event": "GW150914",
            "gps_time": None,
            "ifos": ["H1", "L1"],
            "window_seconds": 16,
            "event_offset_fraction": 0.75,
            "sample_rate": 2048,
        },
    )
    outcome = GWOSCFetchAdapter().execute(context)
    assert outcome.outputs["simulated"] is False
    assert outcome.outputs["source"] == "gwosc"
    assert outcome.outputs["gps_end"] - outcome.outputs["gps_start"] == 16
    assert outcome.metadata["event_time_source"] == "gwosc.datasets.event_gps"
    assert any("resampled from 4096" in warning for warning in outcome.warnings)
    data = read_strain(tmp_path / outcome.outputs["strain_artifact"])
    assert data.ifos == ["H1", "L1"]
    assert data.sample_rate == 2048
    assert data.n_samples == 16 * 2048
    assert data.event_time == pytest.approx(EVENT_TIME)
    with h5py.File(tmp_path / outcome.outputs["strain_artifact"]) as handle:
        assert "t0" in handle.attrs and "tc" in handle.attrs


def test_gwosc_fetch_prefers_supplied_gps_time(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ml4gw_agent.adapters.gwosc.load_gwosc_backend",
        lambda: _gwosc_backend(rate=2048.0),
    )
    context = _context(
        registry,
        tmp_path,
        "data.fetch",
        "fetch_data",
        {"event": "1126259462.4", "gps_time": 1126259462.4, "ifos": ["H1"]},
    )
    outcome = GWOSCFetchAdapter().execute(context)
    assert outcome.metadata["event_time_source"] == "parameter"
    assert outcome.warnings == []


def test_gwosc_fetch_reports_upstream_failures(registry, tmp_path, monkeypatch):
    def failing(ifo, start, end):
        raise RuntimeError("HTTP 502")

    monkeypatch.setattr(
        "ml4gw_agent.adapters.gwosc.load_gwosc_backend",
        lambda: _gwosc_backend(fetch=failing),
    )
    context = _context(
        registry,
        tmp_path,
        "data.fetch",
        "fetch_data",
        {"event": "GW150914", "ifos": ["H1", "L1"], "window_seconds": 8},
    )
    with pytest.raises(AdapterError, match="HTTP 502"):
        GWOSCFetchAdapter().execute(context)

    def short(ifo, start, end):
        return FakeTimeSeries(start, end - 4, 2048.0)

    monkeypatch.setattr(
        "ml4gw_agent.adapters.gwosc.load_gwosc_backend",
        lambda: _gwosc_backend(fetch=short),
    )
    with pytest.raises(AdapterError, match="covers"):
        GWOSCFetchAdapter().execute(context)


def test_gwosc_preflight_rules(registry, tmp_path, monkeypatch):
    adapter = GWOSCFetchAdapter()
    base = {"ifos": ["H1", "L1"]}
    with pytest.raises(AdapterError, match="unsupported event"):
        adapter.preflight(
            _context(registry, tmp_path, "data.fetch", "f", {"event": "x;y", **base})
        )
    with pytest.raises(AdapterUnavailableError, match="GraceDB"):
        adapter.preflight(
            _context(
                registry, tmp_path, "data.fetch", "f", {"event": "S190521g", **base}
            )
        )
    monkeypatch.setattr(
        "ml4gw_agent.adapters.gwosc.missing_modules", lambda names: ["gwpy"]
    )
    with pytest.raises(AdapterUnavailableError, match="gwpy"):
        adapter.preflight(
            _context(
                registry, tmp_path, "data.fetch", "f", {"event": "GW150914", **base}
            )
        )
    assert adapter.probe().startswith("missing")
    with pytest.raises(AdapterUnavailableError):
        load_gwosc_backend()


# --------------------------------------------------------------------------- #
# data.inspect
# --------------------------------------------------------------------------- #


def _inspect(registry, tmp_path, parameters):
    context = _context(registry, tmp_path, "data.inspect", "inspect_data", parameters)
    return StrainInspectAdapter().execute(context)


def test_inspect_passes_clean_strain(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ml4gw_agent.adapters.strain.load_gwosc_backend", lambda: _gwosc_backend()
    )
    path = _strain(tmp_path)
    outcome = _inspect(
        registry,
        tmp_path,
        {
            "strain_artifact": str(path.relative_to(tmp_path)),
            "expected_ifos": ["H1", "L1"],
            "min_duration_seconds": DURATION,
            "require_science_mode": True,
        },
    )
    assert outcome.outputs["quality_passed"] is True
    assert outcome.outputs["issues"] == []
    assert outcome.outputs["available_ifos"] == ["H1", "L1"]
    diagnostics = json.loads(
        (tmp_path / outcome.outputs["diagnostics_artifact"]).read_text()
    )
    assert diagnostics["per_ifo"]["H1"]["finite_fraction"] == 1.0


def test_inspect_fails_closed_on_bad_data(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ml4gw_agent.adapters.strain.load_gwosc_backend",
        lambda: _gwosc_backend(segments=lambda flag, s, e: [(s + 1, e)]),
    )
    n = int(DURATION * SAMPLE_RATE)
    h1 = np.random.default_rng(1).normal(size=n)
    h1[10] = np.nan
    path = _strain(tmp_path, H1=h1, L1=np.zeros(n))
    outcome = _inspect(
        registry,
        tmp_path,
        {
            "strain_artifact": str(path.relative_to(tmp_path)),
            "expected_ifos": ["H1", "L1", "V1"],
            "min_duration_seconds": 64,
            "require_science_mode": True,
        },
    )
    issues = "\n".join(outcome.outputs["issues"])
    assert outcome.outputs["quality_passed"] is False
    assert "V1" in issues
    assert "not finite" in issues
    assert "constant" in issues
    assert "shorter" in issues
    assert "H1_DATA flag does not cover" in issues


def test_inspect_records_segment_service_problems(registry, tmp_path, monkeypatch):
    def raise_unavailable():
        raise AdapterUnavailableError("gwosc missing")

    monkeypatch.setattr(
        "ml4gw_agent.adapters.strain.load_gwosc_backend", raise_unavailable
    )
    path = _strain(tmp_path)
    outcome = _inspect(
        registry, tmp_path, {"strain_artifact": str(path.relative_to(tmp_path))}
    )
    assert outcome.outputs["quality_passed"] is False
    assert any("unavailable" in issue for issue in outcome.outputs["issues"])

    def broken(flag, start, end):
        raise ConnectionError("offline")

    monkeypatch.setattr(
        "ml4gw_agent.adapters.strain.load_gwosc_backend",
        lambda: _gwosc_backend(segments=broken),
    )
    outcome = _inspect(
        registry, tmp_path, {"strain_artifact": str(path.relative_to(tmp_path))}
    )
    assert any("query failed" in issue for issue in outcome.outputs["issues"])

    outcome = _inspect(
        registry,
        tmp_path,
        {
            "strain_artifact": str(path.relative_to(tmp_path)),
            "require_science_mode": False,
        },
    )
    assert outcome.outputs["quality_passed"] is True
    assert any("disabled" in warning for warning in outcome.warnings)
    monkeypatch.setattr(
        "ml4gw_agent.adapters.strain.missing_modules", lambda names: ["gwosc"]
    )
    assert "without science-segment" in StrainInspectAdapter().probe()


# --------------------------------------------------------------------------- #
# aframe.detect
# --------------------------------------------------------------------------- #


class FakeAframe:
    instances: list[FakeAframe] = []

    def __init__(
        self, device=None, revision=None, statistic=12.5, sample_rate=SAMPLE_RATE
    ):
        self.device = device
        self.revision = revision
        self.sample_rate = sample_rate
        self.kernel_length = 1.5
        self.psd_length = 4.0
        self.fduration = 1.0
        self.highpass = 32.0
        self.lowpass = None
        self.fftlength = 2.0
        self.inference_sampling_rate = 16.0
        self.offline_sampling_rate = 4.0
        self.batch_size = 32
        self.aframe_right_pad = 0.5
        self.integration_window_length = 1.0
        self.time_offset = -0.5
        self.minimum_data_size = 1024
        self.statistic = statistic
        FakeAframe.instances.append(self)

    def __call__(self, data, t0):
        assert data.shape[1] == 2
        steps = 64
        times = t0 + np.arange(steps) / self.inference_sampling_rate
        ys = np.linspace(-5, self.statistic, steps)
        timing = ys.copy()
        signif = ys[3::4].copy()
        return times, ys, timing, signif


def _torch_backend(**kwargs):
    seeds: list[int] = []

    def factory(device=None, revision=None):
        return FakeAframe(device=device, revision=revision, **kwargs)

    backend = TorchBackend(
        aframe_class=factory,
        to_tensor=lambda array: np.asarray(array),
        seed=seeds.append,
    )
    return backend, seeds


def _aframe_params(path, tmp_path, **overrides):
    params = {
        "strain_artifact": str(path.relative_to(tmp_path)),
        "ifos": ["H1", "L1"],
        "model_revision": "aframe-sha",
        "device": "cpu",
        "threshold": 0.0,
        "seed": 7,
    }
    params.update(overrides)
    return params


def test_aframe_adapter_detects_and_writes_buoy_layout(registry, tmp_path, monkeypatch):
    backend, seeds = _torch_backend()
    monkeypatch.setattr(
        "ml4gw_agent.adapters.aframe.load_aframe_backend", lambda: backend
    )
    path = _strain(tmp_path)
    context = _context(
        registry,
        tmp_path,
        "aframe.detect",
        "run_aframe",
        _aframe_params(path, tmp_path),
    )
    outcome = AframeAdapter().execute(context)
    assert seeds == [7]
    assert outcome.outputs["candidate_found"] is True
    assert outcome.outputs["detection_statistic"] == pytest.approx(12.5)
    assert outcome.outputs["threshold_calibrated"] is False
    assert outcome.outputs["model"]["revision"] == "aframe-sha"
    assert outcome.outputs["model"]["config"]["psd_length"] == 4.0
    expected_tc = EVENT_TIME - 6.4 + 63 / 16 - 0.5
    assert outcome.outputs["predicted_coalescence_time"] == pytest.approx(expected_tc)
    assert outcome.outputs["candidate_times"] == [pytest.approx(expected_tc)]
    with h5py.File(tmp_path / outcome.outputs["output_artifact"]) as handle:
        assert set(handle) == {"times", "ys", "timing_integrated", "signif_integrated"}
        assert handle.attrs["predicted_tc"] == pytest.approx(expected_tc)
        assert handle.attrs["model_revision"] == "aframe-sha"
    assert any("not a false-alarm-rate" in warning for warning in outcome.warnings)


def test_aframe_adapter_threshold_and_guards(registry, tmp_path, monkeypatch):
    backend, _ = _torch_backend(statistic=-1.0)
    monkeypatch.setattr(
        "ml4gw_agent.adapters.aframe.load_aframe_backend", lambda: backend
    )
    path = _strain(tmp_path)
    context = _context(
        registry,
        tmp_path,
        "aframe.detect",
        "run_aframe",
        _aframe_params(path, tmp_path, threshold=5.0, seed=None),
    )
    outcome = AframeAdapter().execute(context)
    assert outcome.outputs["candidate_found"] is False
    assert outcome.outputs["candidate_times"] == []

    wrong_ifos = _context(
        registry,
        tmp_path,
        "aframe.detect",
        "run_aframe",
        _aframe_params(path, tmp_path, ifos=["L1", "H1"]),
    )
    with pytest.raises(AdapterError, match="expects detectors"):
        AframeAdapter().execute(wrong_ifos)

    backend, _ = _torch_backend(sample_rate=4096.0)
    monkeypatch.setattr(
        "ml4gw_agent.adapters.aframe.load_aframe_backend", lambda: backend
    )
    with pytest.raises(AdapterError, match="sample rate"):
        AframeAdapter().execute(context)

    backend, _ = _torch_backend(statistic=float("nan"))
    monkeypatch.setattr(
        "ml4gw_agent.adapters.aframe.load_aframe_backend", lambda: backend
    )
    with pytest.raises(AdapterError, match="non-finite"):
        AframeAdapter().execute(context)

    def broken(device=None, revision=None):
        raise OSError("no such revision")

    backend = TorchBackend(
        aframe_class=broken, to_tensor=np.asarray, seed=lambda s: None
    )
    monkeypatch.setattr(
        "ml4gw_agent.adapters.aframe.load_aframe_backend", lambda: backend
    )
    with pytest.raises(AdapterError, match="could not load Aframe"):
        AframeAdapter().execute(context)


def test_aframe_preflight_and_probe(registry, tmp_path, monkeypatch):
    path = _strain(tmp_path)
    context = _context(
        registry,
        tmp_path,
        "aframe.detect",
        "run_aframe",
        _aframe_params(path, tmp_path, model_revision="UNPINNED", device="cuda"),
    )
    # Simulate an environment without the optional science stack so the test
    # passes both with and without ``uv sync --extra buoy``.
    monkeypatch.setattr("ml4gw_agent.adapters.aframe._missing", lambda: ["buoy"])
    with pytest.raises(AdapterUnavailableError, match="uv sync --extra buoy"):
        AframeAdapter().preflight(context)
    assert AframeAdapter().probe().startswith("missing")
    with pytest.raises(AdapterUnavailableError):
        load_aframe_backend()
    monkeypatch.setattr("ml4gw_agent.adapters.aframe._missing", lambda: [])
    monkeypatch.setattr("ml4gw_agent.adapters.aframe.shutil.which", lambda _: None)
    warnings = AframeAdapter().preflight(context)
    assert any("nvidia-smi" in warning for warning in warnings)
    assert any("not pinned" in warning for warning in warnings)
    assert AframeAdapter().probe() == "available"
    _, metadata = AframeAdapter().describe_invocation(context)
    assert metadata["python_call"] == "buoy.models.Aframe.__call__"


# --------------------------------------------------------------------------- #
# amplfi.pe
# --------------------------------------------------------------------------- #


class FakeResult:
    def __init__(self, n=200, skymap_ok=True):
        rng = np.random.default_rng(3)
        self.posterior = {
            "chirp_mass": rng.normal(30, 1, n),
            "mass_ratio": rng.uniform(0.5, 1, n),
            "distance": rng.normal(400, 50, n),
            "mass_1": rng.normal(36, 2, n),
            "mass_2": rng.normal(29, 2, n),
            "ra": rng.uniform(0, 6.28, n),
            "dec": rng.uniform(-1.5, 1.5, n),
        }
        self.skymap_ok = skymap_ok

    def __len__(self):
        return len(self.posterior["chirp_mass"])

    def save_posterior_samples(self, filename):
        Path(filename).write_text("chirp_mass mass_ratio\n30 0.8\n")

    def to_skymap(self, **kwargs):
        if not self.skymap_ok:
            raise ValueError("healpix failure")
        return {"metadata": kwargs["metadata"]}


class FakeAmplfi:
    loaded: list[dict] = []

    def __init__(
        self, model_weights, config, device, revision, sample_rate=SAMPLE_RATE
    ):
        self.sample_rate = sample_rate
        self.kernel_length = 3.0
        self.psd_length = 4.0
        self.inference_params = ["chirp_mass", "mass_ratio"]
        self.skymap_ok = True
        FakeAmplfi.loaded.append(
            {"weights": model_weights, "config": config, "revision": revision}
        )

    def __call__(self, data, t0, tc, samples_per_event):
        return FakeResult(n=samples_per_event, skymap_ok=self.skymap_ok)


def _amplfi_backend(sample_rate=SAMPLE_RATE, skymap_ok=True):
    seeds: list[int] = []

    def factory(model_weights, config, device, revision):
        model = FakeAmplfi(model_weights, config, device, revision, sample_rate)
        model.skymap_ok = skymap_ok
        return model

    def write_skymap(table, path):
        Path(path).write_bytes(b"SIMPLE  = T")

    return (
        AmplfiBackend(
            amplfi_class=factory,
            to_tensor=lambda array: np.asarray(array),
            seed=seeds.append,
            write_skymap=write_skymap,
        ),
        seeds,
    )


def _amplfi_params(path, tmp_path, **overrides):
    params = {
        "strain_artifact": str(path.relative_to(tmp_path)),
        "coalescence_time": EVENT_TIME,
        "ifos": ["H1", "L1"],
        "model_revision": "amplfi-sha",
        "samples": 200,
        "device": "cpu",
        "seed": 1,
        "nside": 64,
        "min_samples_per_pix": 5,
        "use_distance": True,
    }
    params.update(overrides)
    return params


def test_amplfi_adapter_selects_hl_model_and_summarizes(
    registry, tmp_path, monkeypatch
):
    FakeAmplfi.loaded.clear()
    backend, seeds = _amplfi_backend()
    monkeypatch.setattr(
        "ml4gw_agent.adapters.amplfi.load_amplfi_backend", lambda: backend
    )
    path = _strain(tmp_path)
    context = _context(
        registry, tmp_path, "amplfi.pe", "run_amplfi", _amplfi_params(path, tmp_path)
    )
    outcome = AmplfiAdapter().execute(context)
    assert seeds == [1]
    assert FakeAmplfi.loaded[-1]["weights"] == "amplfi-hl.ckpt"
    assert outcome.outputs["n_samples"] == 200
    assert outcome.outputs["credible_intervals"]["chirp_mass"][
        "median"
    ] == pytest.approx(30, abs=1)
    assert (
        (tmp_path / outcome.outputs["posterior_artifact"])
        .read_text()
        .startswith("chirp_mass")
    )
    assert outcome.outputs["skymap_artifact"].endswith("amplfi_HL.fits")
    summary = json.loads((tmp_path / outcome.outputs["summary_artifact"]).read_text())
    assert (
        summary["parameters"]["distance"]["p95"]
        > summary["parameters"]["distance"]["p5"]
    )
    assert outcome.outputs["model"]["inference_params"] == ["chirp_mass", "mass_ratio"]


def test_amplfi_adapter_selects_hlv_model(registry, tmp_path, monkeypatch):
    FakeAmplfi.loaded.clear()
    backend, _ = _amplfi_backend()
    monkeypatch.setattr(
        "ml4gw_agent.adapters.amplfi.load_amplfi_backend", lambda: backend
    )
    path = _strain(tmp_path, ifos=("H1", "L1", "V1"))
    context = _context(
        registry,
        tmp_path,
        "amplfi.pe",
        "run_amplfi",
        _amplfi_params(path, tmp_path, ifos=["H1", "L1", "V1"], seed=None),
    )
    outcome = AmplfiAdapter().execute(context)
    assert FakeAmplfi.loaded[-1]["config"] == "amplfi-hlv-config.yaml"
    assert outcome.outputs["skymap_artifact"].endswith("amplfi_HLV.fits")


def test_amplfi_adapter_guards(registry, tmp_path, monkeypatch):
    backend, _ = _amplfi_backend()
    monkeypatch.setattr(
        "ml4gw_agent.adapters.amplfi.load_amplfi_backend", lambda: backend
    )
    path = _strain(tmp_path)
    outside = _context(
        registry,
        tmp_path,
        "amplfi.pe",
        "run_amplfi",
        _amplfi_params(path, tmp_path, coalescence_time=EVENT_TIME + 100),
    )
    with pytest.raises(AdapterError, match="outside the strain interval"):
        AmplfiAdapter().execute(outside)

    unsupported = _context(
        registry,
        tmp_path,
        "amplfi.pe",
        "run_amplfi",
        _amplfi_params(path, tmp_path, ifos=["L1", "V1"]),
    )
    with pytest.raises(AdapterError, match="unsupported detector set"):
        AmplfiAdapter().execute(unsupported)

    context = _context(
        registry, tmp_path, "amplfi.pe", "run_amplfi", _amplfi_params(path, tmp_path)
    )
    backend, _ = _amplfi_backend(sample_rate=4096.0)
    monkeypatch.setattr(
        "ml4gw_agent.adapters.amplfi.load_amplfi_backend", lambda: backend
    )
    with pytest.raises(AdapterError, match="sample rate"):
        AmplfiAdapter().execute(context)

    backend, _ = _amplfi_backend(skymap_ok=False)
    monkeypatch.setattr(
        "ml4gw_agent.adapters.amplfi.load_amplfi_backend", lambda: backend
    )
    with pytest.raises(AdapterError, match="sky map"):
        AmplfiAdapter().execute(context)


def test_amplfi_preflight_probe_and_intervals(registry, tmp_path, monkeypatch):
    path = _strain(tmp_path)
    context = _context(
        registry,
        tmp_path,
        "amplfi.pe",
        "run_amplfi",
        _amplfi_params(path, tmp_path, model_revision="UNPINNED", device="cuda"),
    )
    monkeypatch.setattr("ml4gw_agent.adapters.amplfi._missing", lambda: ["buoy"])
    with pytest.raises(AdapterUnavailableError, match="uv sync --extra buoy"):
        AmplfiAdapter().preflight(context)
    assert AmplfiAdapter().probe().startswith("missing")
    with pytest.raises(AdapterUnavailableError):
        load_amplfi_backend()
    monkeypatch.setattr("ml4gw_agent.adapters.amplfi._missing", lambda: [])
    monkeypatch.setattr("ml4gw_agent.adapters.amplfi.shutil.which", lambda _: None)
    warnings = AmplfiAdapter().preflight(context)
    assert any("nvidia-smi" in warning for warning in warnings)
    assert any("not pinned" in warning for warning in warnings)
    bad = _context(
        registry,
        tmp_path,
        "amplfi.pe",
        "run_amplfi",
        _amplfi_params(path, tmp_path, ifos=["H1", "V1"]),
    )
    with pytest.raises(AdapterError, match="detector sets"):
        AmplfiAdapter().preflight(bad)
    _, metadata = AmplfiAdapter().describe_invocation(context)
    assert metadata["model_weights"] == "amplfi-hl.ckpt"
    assert credible_intervals({"chirp_mass": np.array([np.nan, np.nan])}) == {}
    assert "ra" in credible_intervals({"ra": np.array([1.0, 2.0, 3.0]), "x": [1]})


# --------------------------------------------------------------------------- #
# End-to-end decomposed plan in real mode with fake backends
# --------------------------------------------------------------------------- #


def test_decomposed_plan_runs_end_to_end_in_real_mode(registry, tmp_path, monkeypatch):
    def fetch(ifo, start, end):
        return FakeTimeSeries(start, end, 2048.0)

    gwosc_backend = _gwosc_backend(rate=2048.0, fetch=fetch)
    torch_backend, _ = _torch_backend()
    amplfi_backend, _ = _amplfi_backend()
    monkeypatch.setattr("ml4gw_agent.adapters.gwosc.missing_modules", lambda names: [])
    monkeypatch.setattr(
        "ml4gw_agent.adapters.gwosc.load_gwosc_backend", lambda: gwosc_backend
    )
    monkeypatch.setattr(
        "ml4gw_agent.adapters.strain.load_gwosc_backend", lambda: gwosc_backend
    )
    monkeypatch.setattr("ml4gw_agent.adapters.aframe._missing", lambda: [])
    monkeypatch.setattr(
        "ml4gw_agent.adapters.aframe.load_aframe_backend", lambda: torch_backend
    )
    monkeypatch.setattr("ml4gw_agent.adapters.amplfi._missing", lambda: [])
    monkeypatch.setattr(
        "ml4gw_agent.adapters.amplfi.load_amplfi_backend", lambda: amplfi_backend
    )

    planner = BaselinePlanner(
        registry,
        PlannerConfig(
            aframe_revision="aframe-sha",
            amplfi_revision="amplfi-sha",
            device="cpu",
            window_seconds=16,
            samples_per_event=200,
        ),
    )
    plan = planner.plan(
        "Fetch strain data for GW150914, check data quality, run Aframe detection "
        "and AMPLFI parameter estimation."
    )
    assert [task.skill for task in plan.tasks] == [
        "data.resolve_event",
        "data.fetch",
        "data.inspect",
        "aframe.detect",
        "amplfi.pe",
        "report.generate",
    ]
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="real")
    assert manifest.status == RunStatus.COMPLETED, manifest.warnings
    assert all(
        record.status == TaskStatus.COMPLETED for record in manifest.tasks.values()
    )
    fetch_record = manifest.tasks["fetch_data"]
    assert fetch_record.parameters["gps_time"] == pytest.approx(EVENT_TIME)
    assert manifest.tasks["inspect_data"].outputs["quality_passed"] is True
    aframe_record = manifest.tasks["run_aframe"]
    assert aframe_record.outputs["simulated"] is False
    amplfi_record = manifest.tasks["run_amplfi"]
    assert amplfi_record.parameters["coalescence_time"] == pytest.approx(
        aframe_record.outputs["predicted_coalescence_time"]
    )
    assert amplfi_record.adapter_metadata["model_weights"] == "amplfi-hl.ckpt"
    assert len(amplfi_record.artifacts) == 3
    report = (Path(manifest.run_directory) / "report.md").read_text()
    assert "SIMULATED" not in report


def test_decomposed_plan_skips_pe_when_no_candidate(registry, tmp_path, monkeypatch):
    gwosc_backend = _gwosc_backend(rate=2048.0)
    torch_backend, _ = _torch_backend(statistic=-3.0)
    monkeypatch.setattr("ml4gw_agent.adapters.gwosc.missing_modules", lambda names: [])
    monkeypatch.setattr(
        "ml4gw_agent.adapters.gwosc.load_gwosc_backend", lambda: gwosc_backend
    )
    monkeypatch.setattr(
        "ml4gw_agent.adapters.strain.load_gwosc_backend", lambda: gwosc_backend
    )
    monkeypatch.setattr("ml4gw_agent.adapters.aframe._missing", lambda: [])
    monkeypatch.setattr(
        "ml4gw_agent.adapters.aframe.load_aframe_backend", lambda: torch_backend
    )
    monkeypatch.setattr("ml4gw_agent.adapters.amplfi._missing", lambda: [])
    planner = BaselinePlanner(
        registry,
        PlannerConfig(
            aframe_revision="aframe-sha",
            amplfi_revision="amplfi-sha",
            device="cpu",
            window_seconds=16,
        ),
    )
    plan = planner.plan("Run Aframe and AMPLFI parameter estimation on GW150914.")
    manifest = AgentRuntime(registry).run(plan, runs_dir=tmp_path, mode="real")
    assert manifest.status == RunStatus.COMPLETED
    assert manifest.tasks["run_aframe"].outputs["candidate_found"] is False
    assert manifest.tasks["run_amplfi"].status == TaskStatus.SKIPPED
    assert manifest.tasks["generate_report"].status == TaskStatus.COMPLETED


def test_doctor_reports_python_adapter_probes(capsys, monkeypatch):
    # Force the "science stack not installed" picture regardless of the host.
    monkeypatch.setattr("ml4gw_agent.cli.shutil.which", lambda _: None)
    monkeypatch.setattr("ml4gw_agent.adapters.aframe._missing", lambda: ["buoy"])
    monkeypatch.setattr("ml4gw_agent.adapters.amplfi._missing", lambda: ["buoy"])
    assert main(["doctor", "--mode", "real"]) == 2
    payload = json.loads(capsys.readouterr().out)
    rows = {row["skill"]: row for row in payload["skills"]}
    assert rows["data.fetch"]["adapter"] == "python"
    assert rows["aframe.detect"]["availability"].startswith("missing")
    assert payload["phase1b_decomposed_ready"] is False
