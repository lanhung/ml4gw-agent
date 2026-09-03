"""DeepClean port: a synthetic 60 Hz coupling is learned and subtracted."""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("ml4gw")

from ml4gw_agent.adapters.deepclean_model import (  # noqa: E402
    DeepCleanConfig,
    Scaler,
    bandpass,
    clean_strain,
    load_weights,
    predict_noise,
    save_weights,
    train_deepclean,
)


def _synthetic(rate=1024.0, seconds=96.0, seed=0):
    rng = np.random.default_rng(seed)
    n = int(rate * seconds)
    t = np.arange(n) / rate
    witness = np.sin(2 * np.pi * 60.0 * t + 0.3) + 0.1 * rng.normal(size=n)
    coupling = 0.8 * np.sin(2 * np.pi * 60.0 * t + 0.3)  # linear, in phase
    strain = 1e-21 * (rng.normal(size=n) + 5.0 * coupling)
    return strain, witness[None]


def test_scaler_roundtrip():
    x = np.random.default_rng(1).normal(3.0, 2.0, size=(2, 100))
    scaler = Scaler().fit(x)
    z = scaler(x)
    assert abs(z.mean()) < 1e-6 and abs(z.std() - 1) < 0.05
    assert np.allclose(scaler.inverse(z), x)
    assert np.allclose(Scaler.from_state(scaler.state())(x), z)


def test_train_and_clean_reduce_the_60hz_line(tmp_path):
    strain, witnesses = _synthetic()
    config = DeepCleanConfig(
        ifo="H1",
        strain_channel="H1:TEST",
        witness_channels=["H1:W"],
        freq_low=55,
        freq_high=65,
        sample_rate=1024.0,
        kernel_length=4.0,
        max_epochs=6,
        batch_size=16,
        patience=6,
        hidden_channels=[8, 16],
    )
    weights = train_deepclean(
        strain, witnesses, config, device="cpu", log=lambda *a: None
    )
    assert weights["best_val_ratio"] < 0.9, weights["history"]
    digest = save_weights(weights, tmp_path / "dc.pt")
    reloaded = load_weights(tmp_path / "dc.pt")
    assert len(digest) == 64 and reloaded["config"]["freq_low"] == 55
    cleaned, metrics = clean_strain(strain, witnesses, reloaded, device="cpu")
    assert cleaned.shape == strain.shape
    assert metrics["in_band_asd_ratio"] < 0.95  # six epochs: a smoke test
    assert 0.8 < metrics["out_of_band_asd_ratio"] < 1.2
    # the band-passed residual power dropped
    band = lambda x: bandpass(x, 55, 65, 1024.0, 8)  # noqa: E731
    assert band(cleaned)[2048:-2048].std() < band(strain)[2048:-2048].std()


def test_predict_noise_covers_every_sample():
    config = DeepCleanConfig(
        ifo="H1",
        strain_channel="s",
        witness_channels=["w"],
        freq_low=55,
        freq_high=65,
        sample_rate=256.0,
        clean_kernel_length=1.0,
        inference_sampling_rate=4.0,
        hidden_channels=[4, 8],
    )
    from ml4gw_agent.adapters.deepclean_model import build_autoencoder

    model = build_autoencoder(1, [4, 8])
    x = np.random.default_rng(0).normal(size=(1, 256 * 5 + 37)).astype("f4")
    out = predict_noise(model, x, config, "cpu")
    assert out.shape == (x.shape[-1],) and np.isfinite(out).all()
