"""Injection bookkeeping with a fake projector (no torch locally)."""

from __future__ import annotations

import numpy as np
import pytest

from ml4gw_agent.adapters.injection import (
    BBHInjection,
    gmst_radians,
    inject,
    inject_bbh,
    network_snr,
    optimal_snr,
    read_injections,
    scale_to_snr,
    welch_psd,
    whitened_inner_product,
)
from ml4gw_agent.adapters.strain_io import StrainData, read_strain, write_strain

RATE = 2048.0
T0 = 1126259000.0


def _noise(seed=0, seconds=32.0, sigma=1e-21):
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    return StrainData(
        ifos=["H1", "L1"],
        series={"H1": rng.normal(size=n) * sigma, "L1": rng.normal(size=n) * sigma},
        t0=T0,
        sample_rate=RATE,
        source="test",
    )


def _chirp(sample_rate=RATE, duration=4.0, right_pad=0.5):
    t = np.arange(int(duration * sample_rate)) / sample_rate
    merger = duration - right_pad
    env = np.exp(-((t - merger) ** 2) / (2 * 0.3**2)) * (t <= merger)
    signal = 1e-21 * env * np.sin(2 * np.pi * (40 + 60 * (t / merger)) * t)
    return signal, int(merger * sample_rate)


def fake_projector(params, sample_rate, ifos):
    sig, merger = _chirp(sample_rate)
    return {ifo: sig * (1.0 if ifo == "H1" else 0.6) for ifo in ifos}, merger


def test_optimal_snr_of_white_noise_signal_matches_analytic():
    # white noise with variance sigma^2 has one-sided PSD 2 sigma^2 / fs
    sigma, fs = 1.0, 1024.0
    freqs = np.linspace(0, fs / 2, 513)
    psd = np.full_like(freqs, 2 * sigma**2 / fs)
    n = 4096
    sig = np.zeros(n)
    sig[:1024] = np.sin(2 * np.pi * 100 * np.arange(1024) / fs)
    expected = np.sqrt(np.sum(sig**2) / sigma**2)
    got = optimal_snr(sig, freqs, psd, fs, f_low=0.0)
    assert got == pytest.approx(expected, rel=0.02)
    inner = whitened_inner_product(sig, sig, freqs, psd, fs, f_low=0.0)
    assert inner == pytest.approx(got**2, rel=1e-9)
    assert whitened_inner_product(sig, np.zeros_like(sig), freqs, psd, fs) == 0.0
    assert network_snr({"H1": 3.0, "L1": 4.0}) == 5.0


def test_scale_to_snr_hits_the_target():
    strain = _noise()
    psds = {ifo: welch_psd(strain.series[ifo], RATE) for ifo in strain.ifos}
    sig, _ = _chirp()
    signals = {"H1": sig, "L1": 0.6 * sig}
    scaled, factor, ifo_snr = scale_to_snr(signals, psds, RATE, 12.0)
    assert network_snr(ifo_snr) == pytest.approx(12.0, rel=1e-6)
    assert scaled["H1"][1000] == pytest.approx(sig[1000] * factor)
    assert ifo_snr["H1"] > ifo_snr["L1"]
    with pytest.raises(ValueError, match="zero optimal SNR"):
        scale_to_snr({"H1": np.zeros(100)}, psds, RATE, 5.0)


def test_inject_places_merger_at_tc_and_records_provenance(tmp_path):
    strain = _noise()
    sig, merger = _chirp()
    tc = T0 + 20.0
    out = inject(strain, {"H1": sig}, tc, merger, {"tc": tc, "note": "x"})
    diff = out.series["H1"] - strain.series["H1"]
    peak = int(np.argmax(np.abs(diff)))
    assert abs(peak / RATE - 20.0) < 0.35
    assert np.array_equal(out.series["L1"], strain.series["L1"])
    path = write_strain(tmp_path / "inj.hdf5", out)
    back = read_strain(path)
    assert back.n_samples == strain.n_samples
    assert read_injections(path)[0]["note"] == "x"
    out2 = inject(out, {"L1": sig}, T0 + 5.0, merger)
    assert len(read_injections(write_strain(tmp_path / "inj2.hdf5", out2))) == 2
    with pytest.raises(ValueError, match="outside"):
        inject(strain, {"H1": sig}, T0 + 100.0, merger)
    with pytest.raises(ValueError, match="lacks detector"):
        inject(strain, {"V1": sig}, tc, merger)
    inject(strain, {"H1": sig}, T0 + 0.5, merger)
    inject(strain, {"H1": sig}, T0 + 31.9, merger)


def test_inject_bbh_scales_and_records(tmp_path):
    strain = _noise(seed=3)
    params = BBHInjection(mass_1=30, mass_2=25, tc=T0 + 24.0, target_snr=15.0)
    injected, rec = inject_bbh(strain, params, projector=fake_projector)
    assert rec.snr == pytest.approx(15.0, rel=1e-6)
    assert rec.scale > 0 and rec.distance_mpc == pytest.approx(1000.0 / rec.scale)
    assert set(rec.ifo_snr) == {"H1", "L1"}
    assert rec.chirp_mass == pytest.approx(23.9, abs=0.1)
    assert rec.mass_ratio == pytest.approx(25 / 30)
    path = write_strain(tmp_path / "bbh.hdf5", injected)
    record = read_injections(path)[0]
    assert record["target_snr"] == 15.0 and record["approximant"] == "IMRPhenomD"
    unscaled = BBHInjection(mass_1=30, mass_2=25, tc=T0 + 24.0)
    _, rec2 = inject_bbh(strain, unscaled, projector=fake_projector, ifos=["H1"])
    assert rec2.scale == 1.0 and list(rec2.ifo_snr) == ["H1"]


def test_gmst_is_in_range():
    value = gmst_radians(1126259462.4)
    assert 0 <= value < 2 * np.pi
