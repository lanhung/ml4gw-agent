"""DeepClean noise subtraction, ported from ML4GW/deepcleanv2 (2026-04).

The pieces are the ones the reference training config uses
(``myprojects/60Hz-O3-MDC/config.yaml`` and ``deepclean/couplings/sub_60Hz.py``):

- witnesses standardised per channel, target strain band-passed with an
  8th-order Butterworth filter to the coupling band and standardised;
- ``Autoencoder`` (input conv, four stride-2 conv blocks with hidden
  channels 8/16/32/64, mirrored transposed convs, Tanh, BatchNorm);
- ``PsdRatio`` loss: mean in-band ratio of the residual ASD to the strain
  ASD (``fftlength`` 2 s, ``asd=True``);
- 8 s training kernels at 0.25 s stride, batch 32, Adam with a one-cycle
  schedule peaking at 3.2e-2, early stopping on the validation ratio;
- cleaning: 1 s kernels at the inference rate, the prediction band-passed
  and subtracted from the raw strain, edges handled by overlap.

Everything is plain torch/numpy so the agent can train and clean without
the upstream containers; the resulting weights are pinned by SHA-256 in
``models/deepclean`` and referenced from ``calibration/deepclean_support.json``.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class DeepCleanConfig:
    ifo: str
    strain_channel: str
    witness_channels: list[str]
    freq_low: float
    freq_high: float
    sample_rate: float = 4096.0
    kernel_length: float = 8.0
    train_stride: float = 0.25
    clean_kernel_length: float = 1.0
    inference_sampling_rate: float = 4.0
    filter_order: int = 8
    fftlength: float = 2.0
    hidden_channels: list[int] = field(default_factory=lambda: [8, 16, 32, 64])
    batch_size: int = 32
    max_epochs: int = 100
    lr: float = 3.2e-2
    weight_decay: float = 1e-5
    patience: int = 20
    valid_frac: float = 0.1
    seed: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resample(x: np.ndarray, rate_in: float, rate_out: float) -> np.ndarray:
    """Polyphase resampling for integer ratios, Fourier resampling otherwise."""
    if abs(rate_in - rate_out) < 1e-9:
        return np.asarray(x, dtype="f8")
    from scipy import signal

    factor = rate_in / rate_out
    if abs(factor - round(factor)) < 1e-9:
        return signal.resample_poly(np.asarray(x, dtype="f8"), 1, int(round(factor)))
    inverse = rate_out / rate_in
    if abs(inverse - round(inverse)) < 1e-9:
        return signal.resample_poly(np.asarray(x, dtype="f8"), int(round(inverse)), 1)
    n_out = int(round(len(x) * rate_out / rate_in))
    return signal.resample(np.asarray(x, dtype="f8"), n_out)


def bandpass(x: np.ndarray, low: float, high: float, sample_rate: float, order: int):
    from scipy import signal

    sos = signal.butter(
        order, [low, high], btype="bandpass", fs=sample_rate, output="sos"
    )
    return signal.sosfiltfilt(sos, x, axis=-1)


class Scaler:
    """Per-channel standardisation with fitted mean and std (ChannelWiseScaler)."""

    def __init__(self) -> None:
        self.mean: np.ndarray | None = None
        self.std: np.ndarray | None = None

    def fit(self, x: np.ndarray) -> Scaler:
        self.mean = x.mean(axis=-1, keepdims=True)
        self.std = x.std(axis=-1, keepdims=True) + 1e-30
        return self

    def __call__(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.std

    def inverse(self, x: np.ndarray) -> np.ndarray:
        return x * self.std + self.mean

    def state(self) -> dict[str, list[float]]:
        return {"mean": self.mean.ravel().tolist(), "std": self.std.ravel().tolist()}

    @classmethod
    def from_state(cls, state: dict[str, list[float]]) -> Scaler:
        scaler = cls()
        scaler.mean = np.asarray(state["mean"], dtype="f8")[:, None]
        scaler.std = np.asarray(state["std"], dtype="f8")[:, None]
        return scaler


def build_autoencoder(  # pragma: no cover - torch path, tested on the GPU node
    num_witnesses: int, hidden_channels: list[int]
):
    import torch.nn as nn

    class ConvBlock(nn.Module):
        def __init__(self, cin, cout, transpose=False, stride=1, output_padding=None):
            super().__init__()
            kwargs = (
                {"output_padding": output_padding} if output_padding is not None else {}
            )
            op = nn.ConvTranspose1d if transpose else nn.Conv1d
            self.conv = op(cin, cout, kernel_size=7, stride=stride, padding=3, **kwargs)
            self.bn = nn.BatchNorm1d(cout)
            self.act = nn.Tanh()

        def forward(self, x):
            return self.act(self.bn(self.conv(x)))

    class Autoencoder(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.input_conv = ConvBlock(num_witnesses, num_witnesses)
            down = []
            cin = num_witnesses
            for cout in hidden_channels:
                down.append(ConvBlock(cin, cout, stride=2))
                cin = cout
            self.downsampler = nn.Sequential(*down)
            up = []
            for cout in hidden_channels[-2::-1] + [num_witnesses]:
                up.append(
                    ConvBlock(cin, cout, transpose=True, stride=2, output_padding=1)
                )
                cin = cout
            self.upsampler = nn.Sequential(*up)
            self.output_conv = nn.Conv1d(cin, 1, kernel_size=7, stride=1, padding=3)

        def forward(self, x):
            x = self.input_conv(x)
            x = self.downsampler(x)
            x = self.upsampler(x)
            return self.output_conv(x)[:, 0]

    return Autoencoder()


def psd_ratio_loss(  # pragma: no cover - torch path, tested on the GPU node
    pred, strain, spectral, mask, asd=True
):
    residual = spectral((strain - pred).double())
    target = spectral(strain.double())
    ratio = (residual / target)[:, mask]
    if asd:
        ratio = ratio**0.5
    return ratio.mean(dim=-1)


def _band_mask(  # pragma: no cover - torch path, tested on the GPU node
    sample_rate: float, fftlength: float, low: float, high: float
):
    import torch

    n = int(fftlength * sample_rate / 2) + 1
    mask = torch.zeros(n, dtype=torch.bool)
    mask[int(low * fftlength) : int(high * fftlength) + 1] = True
    return mask


def train_deepclean(  # pragma: no cover - torch path, tested on the GPU node
    strain: np.ndarray,
    witnesses: np.ndarray,
    config: DeepCleanConfig,
    *,
    device: str = "cuda",
    log=print,
) -> dict[str, Any]:
    """Train on (strain[n], witnesses[k, n]); return weights and scalers."""
    import torch
    from ml4gw.transforms import SpectralDensity

    torch.manual_seed(config.seed)
    rate = config.sample_rate
    n_valid = int(len(strain) * config.valid_frac)
    x_scaler = Scaler().fit(witnesses[:, :-n_valid] if n_valid else witnesses)
    target = bandpass(
        strain, config.freq_low, config.freq_high, rate, config.filter_order
    )
    y_scaler = Scaler().fit(target[None, :-n_valid] if n_valid else target[None])
    x = x_scaler(witnesses).astype("f4")
    y = y_scaler(target[None])[0].astype("f4")
    kernel = int(config.kernel_length * rate)
    stride = int(config.train_stride * rate)

    def windows(x_, y_):
        n = x_.shape[-1]
        starts = np.arange(0, n - kernel + 1, stride)
        return starts

    split = len(strain) - n_valid if n_valid else len(strain)
    train_starts = windows(x[:, :split], y[:split])
    valid_x, valid_y = x[:, split:], y[split:]
    model = build_autoencoder(x.shape[0], config.hidden_channels).to(device)
    spectral = SpectralDensity(rate, config.fftlength, average="mean", fast=False).to(
        device
    )
    mask = _band_mask(rate, config.fftlength, config.freq_low, config.freq_high).to(
        device
    )
    optimizer = torch.optim.Adam(
        model.parameters(), lr=config.lr, weight_decay=config.weight_decay
    )
    steps_per_epoch = max(1, math.ceil(len(train_starts) / config.batch_size))
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer,
        max_lr=config.lr,
        total_steps=config.max_epochs * steps_per_epoch,
        pct_start=0.33,
    )
    x_t = torch.as_tensor(x, device=device)
    y_t = torch.as_tensor(y, device=device)
    history = []
    best = (float("inf"), None, -1)
    bad_epochs = 0
    rng = np.random.default_rng(config.seed)
    for epoch in range(config.max_epochs):
        model.train()
        order = rng.permutation(train_starts)
        losses = []
        for i in range(0, len(order), config.batch_size):
            batch_starts = order[i : i + config.batch_size]
            idx = (
                torch.as_tensor(batch_starts, device=device)[:, None]
                + torch.arange(kernel, device=device)[None]
            )
            xb = x_t[:, idx].permute(1, 0, 2)
            yb = y_t[idx]
            pred = model(xb)
            loss = psd_ratio_loss(pred, yb, spectral, mask).mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            scheduler.step()
            losses.append(float(loss))
        val = evaluate_ratio(model, valid_x, valid_y, config, spectral, mask, device)
        history.append(
            {"epoch": epoch, "train_loss": float(np.mean(losses)), "val_ratio": val}
        )
        log(f"epoch {epoch:3d} train {np.mean(losses):.4f} valid {val:.4f}")
        if val < best[0] - 1e-4:
            best = (
                val,
                {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                epoch,
            )
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= config.patience:
                log(f"early stop at epoch {epoch}, best {best[0]:.4f} at {best[2]}")
                break
    model.load_state_dict(best[1])
    return {
        "state_dict": best[1],
        "x_scaler": x_scaler.state(),
        "y_scaler": y_scaler.state(),
        "config": config.as_dict(),
        "history": history,
        "best_val_ratio": best[0],
        "best_epoch": best[2],
    }


def evaluate_ratio(  # pragma: no cover - torch path, tested on the GPU node
    model, x, y, config, spectral, mask, device
) -> float:
    """In-band ASD ratio on a held-out stretch using the cleaning procedure."""
    import torch

    pred = predict_noise(model, x, config, device)
    n = min(len(pred), len(y))
    with torch.no_grad():
        p = torch.as_tensor(pred[:n], device=device)[None]
        t = torch.as_tensor(y[:n], device=device)[None]
        return float(psd_ratio_loss(p, t, spectral, mask).mean())


def predict_noise(  # pragma: no cover - torch path, tested on the GPU node
    model, x: np.ndarray, config: DeepCleanConfig, device: str
) -> np.ndarray:
    """Noise prediction for scaled witnesses x[k, n] via overlapping kernels.

    Each kernel of ``clean_kernel_length`` contributes only its central stride
    (the reference ``OnlinePsdRatio.clean`` behaviour); the first kernel fills
    the left edge and the last one the right edge.
    """
    import torch

    rate = config.sample_rate
    kernel = int(config.clean_kernel_length * rate)
    stride = int(rate / config.inference_sampling_rate)
    n = x.shape[-1]
    if n < kernel:
        raise ValueError("segment shorter than one cleaning kernel")
    starts = np.arange(0, n - kernel + 1, stride)
    offset = (kernel - stride) // 2
    out = np.zeros(n, dtype="f4")
    model.eval()
    xt = torch.as_tensor(x, device=device)
    with torch.no_grad():
        for i in range(0, len(starts), 256):
            batch = starts[i : i + 256]
            idx = (
                torch.as_tensor(batch, device=device)[:, None]
                + torch.arange(kernel, device=device)[None]
            )
            pred = model(xt[:, idx].permute(1, 0, 2)).cpu().numpy()
            for j, s in enumerate(batch):
                lo = s + offset
                out[lo : lo + stride] = pred[j, offset : offset + stride]
                if i == 0 and j == 0:
                    out[:lo] = pred[0, :offset]
            last_start, last_pred = batch[-1], pred[-1]
    tail_from = last_start + offset + stride
    tail_to = min(n, last_start + kernel)
    out[tail_from:tail_to] = last_pred[
        offset + stride : offset + stride + (tail_to - tail_from)
    ]
    return out


def clean_strain(  # pragma: no cover - torch path, tested on the GPU node
    strain: np.ndarray,
    witnesses: np.ndarray,
    weights: dict[str, Any],
    *,
    device: str = "cpu",
) -> tuple[np.ndarray, dict[str, float]]:
    """Return cleaned strain and in-band/out-of-band ASD ratios."""
    import torch
    from ml4gw.transforms import SpectralDensity

    config = DeepCleanConfig(**weights["config"])
    x_scaler = Scaler.from_state(weights["x_scaler"])
    y_scaler = Scaler.from_state(weights["y_scaler"])
    model = build_autoencoder(witnesses.shape[0], config.hidden_channels).to(device)
    model.load_state_dict(weights["state_dict"])
    x = x_scaler(witnesses).astype("f4")
    pred = predict_noise(model, x, config, device)
    noise = y_scaler.inverse(pred[None].astype("f8"))[0]
    noise = bandpass(
        noise,
        config.freq_low,
        config.freq_high,
        config.sample_rate,
        config.filter_order,
    )
    cleaned = strain - noise
    spectral = SpectralDensity(
        config.sample_rate, config.fftlength, average="mean", fast=False
    )
    with torch.no_grad():
        raw = spectral(torch.as_tensor(strain[None]).double())[0].numpy()
        res = spectral(torch.as_tensor(cleaned[None]).double())[0].numpy()
    freqs = np.arange(raw.size) / config.fftlength
    band = (freqs >= config.freq_low) & (freqs <= config.freq_high)
    outside = (freqs >= 20) & ~band & (freqs <= 500)
    ratio = np.sqrt(res / raw)
    return cleaned, {
        "in_band_asd_ratio": float(ratio[band].mean()),
        "in_band_asd_ratio_min": float(ratio[band].min()),
        "out_of_band_asd_ratio": float(ratio[outside].mean()),
        "freq_low": config.freq_low,
        "freq_high": config.freq_high,
    }


def save_weights(  # pragma: no cover - torch path, tested on the GPU node
    weights: dict[str, Any], path: Path
) -> str:
    import hashlib

    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in weights.items() if k != "history"}
    torch.save(payload, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_weights(  # pragma: no cover - torch path, tested on the GPU node
    path: Path,
) -> dict[str, Any]:
    import torch

    return torch.load(path, map_location="cpu", weights_only=False)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
