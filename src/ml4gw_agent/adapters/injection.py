"""Injection of simulated binary-black-hole signals into strain artifacts.

The bookkeeping (PSD estimate, optimal SNR, amplitude scaling, placement in
the strain, provenance attributes) is plain NumPy and unit-tested locally.
Waveform generation and detector projection use ``ml4gw`` (torch) and run on
a GPU host; that path is excluded from local coverage.

Conventions: a projected waveform is an array whose ``merger_index`` sample
is the coalescence; ``inject`` places that sample at GPS ``tc`` inside the
strain and truncates whatever falls outside the artifact. The optimal SNR is
computed per detector with the one-sided PSD of the artifact itself
(median Welch estimate) above ``f_low`` and combined in quadrature.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from .strain_io import StrainData


@dataclass
class BBHInjection:
    mass_1: float
    mass_2: float
    tc: float
    chi1: float = 0.0
    chi2: float = 0.0
    inclination: float = 0.0
    phase: float = 0.0
    psi: float = 0.0
    ra: float = 0.0
    dec: float = 0.0
    distance_mpc: float = 1000.0
    target_snr: float | None = None
    snr: float | None = None
    ifo_snr: dict[str, float] = field(default_factory=dict)
    scale: float = 1.0
    approximant: str = "IMRPhenomD"

    @property
    def chirp_mass(self) -> float:
        m1, m2 = self.mass_1, self.mass_2
        return (m1 * m2) ** 0.6 / (m1 + m2) ** 0.2

    @property
    def mass_ratio(self) -> float:
        return self.mass_2 / self.mass_1

    def as_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["chirp_mass"] = self.chirp_mass
        record["mass_ratio"] = self.mass_ratio
        return record


def welch_psd(
    x: np.ndarray, sample_rate: float, fftlength: float = 4.0
) -> tuple[np.ndarray, np.ndarray]:
    """One-sided median Welch PSD (frequencies, psd)."""
    from scipy import signal

    nperseg = int(fftlength * sample_rate)
    freqs, psd = signal.welch(
        np.asarray(x, dtype="f8"),
        fs=sample_rate,
        nperseg=nperseg,
        noverlap=nperseg // 2,
        average="median",
    )
    return freqs, psd


def optimal_snr(
    signal: np.ndarray,
    psd_freqs: np.ndarray,
    psd: np.ndarray,
    sample_rate: float,
    f_low: float = 20.0,
    f_high: float | None = None,
) -> float:
    """Optimal SNR of ``signal`` against a one-sided PSD (4 int |h|^2/S df)."""
    n = len(signal)
    h = np.fft.rfft(np.asarray(signal, dtype="f8")) / sample_rate
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    s = np.interp(freqs, psd_freqs, psd, left=np.inf, right=np.inf)
    mask = (freqs >= f_low) & (s > 0) & np.isfinite(s)
    if f_high is not None:
        mask &= freqs <= f_high
    df = sample_rate / n
    return float(math.sqrt(4.0 * np.sum(np.abs(h[mask]) ** 2 / s[mask]) * df))


def whitened_inner_product(
    a: np.ndarray,
    b: np.ndarray,
    psd_freqs: np.ndarray,
    psd: np.ndarray,
    sample_rate: float,
    f_low: float = 20.0,
    f_high: float | None = None,
) -> float:
    """Noise-weighted inner product 4 Re int a(f) b*(f) / S(f) df."""
    n = len(a)
    fa = np.fft.rfft(np.asarray(a, dtype="f8")) / sample_rate
    fb = np.fft.rfft(np.asarray(b, dtype="f8")) / sample_rate
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    s = np.interp(freqs, psd_freqs, psd, left=np.inf, right=np.inf)
    mask = (freqs >= f_low) & (s > 0) & np.isfinite(s)
    if f_high is not None:
        mask &= freqs <= f_high
    df = sample_rate / n
    return float(4.0 * np.sum((fa[mask] * np.conj(fb[mask])).real / s[mask]) * df)


def network_snr(ifo_snrs: dict[str, float]) -> float:
    return float(math.sqrt(sum(v * v for v in ifo_snrs.values())))


def scale_to_snr(
    signals: dict[str, np.ndarray],
    psds: dict[str, tuple[np.ndarray, np.ndarray]],
    sample_rate: float,
    target_snr: float,
    f_low: float = 20.0,
) -> tuple[dict[str, np.ndarray], float, dict[str, float]]:
    """Rescale the projected signals so the network optimal SNR is ``target``.

    Returns (scaled signals, scale factor, per-detector SNRs after scaling).
    """
    ifo_snr = {
        ifo: optimal_snr(sig, *psds[ifo], sample_rate, f_low)
        for ifo, sig in signals.items()
    }
    current = network_snr(ifo_snr)
    if current <= 0:
        raise ValueError("projected signal has zero optimal SNR")
    factor = target_snr / current
    scaled = {ifo: sig * factor for ifo, sig in signals.items()}
    return scaled, factor, {ifo: v * factor for ifo, v in ifo_snr.items()}


def inject(
    strain: StrainData,
    signals: dict[str, np.ndarray],
    tc: float,
    merger_index: int,
    record: dict[str, Any] | None = None,
) -> StrainData:
    """Return a copy of ``strain`` with ``signals`` added, merger at ``tc``."""
    rate = strain.sample_rate
    n = strain.n_samples
    series = {
        ifo: np.array(x, dtype="f8", copy=True) for ifo, x in strain.series.items()
    }
    tc_index = int(round((tc - strain.t0) * rate))
    if not 0 <= tc_index < n:
        raise ValueError(
            f"tc {tc} lies outside the strain [{strain.t0}, {strain.gps_end})"
        )
    for ifo, sig in signals.items():
        if ifo not in series:
            raise ValueError(f"strain artifact lacks detector {ifo}")
        start = tc_index - merger_index
        lo, hi = max(start, 0), min(start + len(sig), n)
        if hi > lo:
            series[ifo][lo:hi] += np.asarray(sig[lo - start : hi - start], dtype="f8")
    attrs = dict(strain.extra_attrs)
    injections = json.loads(str(attrs.get("injections", "[]")))
    injections.append(record or {"tc": tc})
    attrs["injections"] = json.dumps(injections)
    return StrainData(
        ifos=list(strain.ifos),
        series=series,
        t0=strain.t0,
        sample_rate=rate,
        event_time=strain.event_time,
        source=strain.source,
        event=strain.event,
        extra_attrs=attrs,
    )


def gmst_radians(gps: float) -> float:
    """Greenwich mean sidereal time (radians) for a GPS time, via astropy."""
    from astropy.time import Time

    return float(Time(gps, format="gps").sidereal_time("mean", "greenwich").rad)


def project_bbh(  # pragma: no cover - torch/ml4gw path, exercised on the GPU node
    params: BBHInjection,
    sample_rate: float,
    ifos: list[str],
    duration: float = 8.0,
    right_pad: float = 0.5,
    f_min: float = 20.0,
    device: str = "cpu",
) -> tuple[dict[str, np.ndarray], int]:
    """Generate an IMRPhenomD waveform and project it onto ``ifos``.

    Returns (signals per detector, merger index). The generator places the
    coalescence ``right_pad`` seconds before the end of the ``duration``
    window, so the merger index is ``(duration - right_pad) * sample_rate``.
    """
    import torch
    from ml4gw import gw
    from ml4gw.waveforms import IMRPhenomD
    from ml4gw.waveforms.generator import TimeDomainCBCWaveformGenerator

    generator = TimeDomainCBCWaveformGenerator(
        approximant=IMRPhenomD(),
        sample_rate=sample_rate,
        duration=duration,
        f_min=f_min,
        f_ref=f_min,
        right_pad=right_pad,
    ).to(device)

    def tensor(value: float):
        return torch.as_tensor([float(value)], dtype=torch.float64, device=device)

    with torch.no_grad():
        hc, hp = generator(
            mass_1=tensor(params.mass_1),
            mass_2=tensor(params.mass_2),
            chirp_mass=tensor(params.chirp_mass),
            mass_ratio=tensor(params.mass_ratio),
            chi1=tensor(params.chi1),
            chi2=tensor(params.chi2),
            s1z=tensor(params.chi1),
            s2z=tensor(params.chi2),
            distance=tensor(params.distance_mpc),
            phic=tensor(params.phase),
            inclination=tensor(params.inclination),
        )
        tensors, vertices = gw.get_ifo_geometry(*ifos)
        phi = params.ra - gmst_radians(params.tc)
        responses = gw.compute_observed_strain(
            tensor(params.dec),
            tensor(params.psi),
            tensor(phi),
            tensors.to(device).to(hp.dtype),
            vertices.to(device).to(hp.dtype),
            sample_rate,
            plus=hp,
            cross=hc,
        )
    responses = responses[0].detach().cpu().numpy().astype("f8")
    merger_index = int(round((duration - right_pad) * sample_rate))
    return {ifo: responses[i] for i, ifo in enumerate(ifos)}, merger_index


def inject_bbh(
    strain: StrainData,
    params: BBHInjection,
    *,
    projector=project_bbh,
    f_low: float = 20.0,
    psd_fftlength: float = 4.0,
    ifos: list[str] | None = None,
) -> tuple[StrainData, BBHInjection]:
    """Project, scale to ``params.target_snr`` (if set) and inject.

    ``projector`` is the waveform/projection callable (seam for tests).
    """
    ifos = ifos or [ifo for ifo in strain.ifos if ifo in ("H1", "L1", "V1")]
    signals, merger_index = projector(params, strain.sample_rate, ifos)
    psds = {
        ifo: welch_psd(strain.series[ifo], strain.sample_rate, psd_fftlength)
        for ifo in ifos
    }
    if params.target_snr is not None:
        signals, factor, ifo_snr = scale_to_snr(
            signals, psds, strain.sample_rate, params.target_snr, f_low
        )
    else:
        factor = 1.0
        ifo_snr = {
            ifo: optimal_snr(sig, *psds[ifo], strain.sample_rate, f_low)
            for ifo, sig in signals.items()
        }
    params.scale = factor
    params.ifo_snr = ifo_snr
    params.snr = network_snr(ifo_snr)
    params.distance_mpc = params.distance_mpc / factor
    injected = inject(strain, signals, params.tc, merger_index, params.as_dict())
    return injected, params


def read_injections(path) -> list[dict[str, Any]]:
    import h5py

    with h5py.File(path, "r") as handle:
        return json.loads(str(handle.attrs.get("injections", "[]")))
