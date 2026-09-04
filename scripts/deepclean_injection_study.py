#!/usr/bin/env python3
"""DeepClean signal preservation with injected binary-black-hole signals.

Signals are injected into the held-out part of the H1 training file (the
part after ``--train-seconds``), the raw and the injected strain are both
cleaned with the shipped model, and the recovered signal
``clean(strain + h) - clean(strain)`` is compared with the injected ``h``
through the noise-weighted match and the optimal-SNR ratio. The in-band ASD
ratio of the cleaning is recorded alongside.

    uv run python scripts/deepclean_injection_study.py data.hdf5 \
        --weights models/deepclean/H1_60Hz/deepclean.pt --output out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import h5py
import numpy as np


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("data", type=Path)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--strain", default="H1:GDS-CALIB_STRAIN")
    parser.add_argument("--witness", action="append", default=None)
    parser.add_argument("--train-seconds", type=float, default=4096.0)
    parser.add_argument("--window", type=float, default=128.0)
    parser.add_argument("--snr", type=float, nargs="+", default=[10, 15, 20, 30])
    parser.add_argument("--n-per-bin", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    from ml4gw_agent.adapters.deepclean_model import (
        clean_strain,
        load_weights,
        resample,
    )
    from ml4gw_agent.adapters.injection import (
        BBHInjection,
        inject_bbh,
        optimal_snr,
        welch_psd,
        whitened_inner_product,
    )
    from ml4gw_agent.adapters.strain_io import StrainData

    weights = load_weights(args.weights)
    config = weights["config"]
    rate = float(config["sample_rate"])
    witnesses = args.witness or list(config["witness_channels"])
    with h5py.File(args.data, "r") as handle:
        t0 = float(handle.attrs["t0"]) + args.train_seconds
        skip = int(args.train_seconds * float(handle[args.strain].attrs["sample_rate"]))
        strain = resample(
            handle[args.strain][skip:],
            float(handle[args.strain].attrs["sample_rate"]),
            rate,
        )
        wit = np.stack(
            [
                resample(
                    handle[c][
                        int(
                            args.train_seconds * float(handle[c].attrs["sample_rate"])
                        ) :
                    ],
                    float(handle[c].attrs["sample_rate"]),
                    rate,
                )
                for c in witnesses
            ]
        )
    n_win = int(args.window * rate)
    n_windows = strain.shape[0] // n_win
    rng = np.random.default_rng(args.seed)
    band = (config["freq_low"], config["freq_high"])
    records = []
    plan = [(s, i) for s in args.snr for i in range(args.n_per_bin)]
    for k, (snr, index) in enumerate(plan):
        w = (k * 3) % n_windows
        raw = strain[w * n_win : (w + 1) * n_win]
        wx = wit[:, w * n_win : (w + 1) * n_win]
        window_t0 = t0 + w * args.window
        tc = window_t0 + 0.75 * args.window
        base = StrainData(
            ifos=["H1"], series={"H1": raw}, t0=window_t0, sample_rate=rate
        )
        m1 = float(rng.uniform(10, 80))
        params = BBHInjection(
            mass_1=m1,
            mass_2=float(rng.uniform(10, m1)),
            tc=tc,
            chi1=float(rng.uniform(-0.5, 0.5)),
            chi2=float(rng.uniform(-0.5, 0.5)),
            inclination=float(np.arccos(rng.uniform(-1, 1))),
            phase=float(rng.uniform(0, 2 * np.pi)),
            psi=float(rng.uniform(0, np.pi)),
            ra=float(rng.uniform(0, 2 * np.pi)),
            dec=float(np.arcsin(rng.uniform(-1, 1))),
            target_snr=float(snr),
        )
        started = time.time()
        injected, params = inject_bbh(base, params, ifos=["H1"])
        h = injected.series["H1"] - raw
        cleaned_raw, metrics_raw = clean_strain(raw, wx, weights, device=args.device)
        cleaned_inj, metrics_inj = clean_strain(
            injected.series["H1"], wx, weights, device=args.device
        )
        h_after = cleaned_inj - cleaned_raw
        freqs, psd = welch_psd(raw, rate)
        hh = whitened_inner_product(h, h, freqs, psd, rate)
        aa = whitened_inner_product(h_after, h_after, freqs, psd, rate)
        ha = whitened_inner_product(h, h_after, freqs, psd, rate)
        match = ha / np.sqrt(hh * aa) if hh > 0 and aa > 0 else None
        # in-band content of the injected signal, before and after cleaning
        snr_band_before = optimal_snr(h, freqs, psd, rate, band[0], band[1])
        snr_band_after = optimal_snr(h_after, freqs, psd, rate, band[0], band[1])
        # matched-filter SNR of the injection in the data, before/after
        mf_before = whitened_inner_product(
            injected.series["H1"], h, freqs, psd, rate
        ) / np.sqrt(hh)
        mf_after = whitened_inner_product(cleaned_inj, h, freqs, psd, rate) / np.sqrt(
            hh
        )
        rec = {
            "target_snr": snr,
            "index": index,
            "window_t0": window_t0,
            "tc": tc,
            "injection": params.as_dict(),
            "optimal_snr_h1": params.snr,
            "match_after_vs_injected": match,
            "optimal_snr_ratio_after_over_before": float(np.sqrt(aa / hh))
            if hh > 0
            else None,
            "in_band_optimal_snr_before": snr_band_before,
            "in_band_optimal_snr_after": snr_band_after,
            "matched_filter_snr_before": float(mf_before),
            "matched_filter_snr_after": float(mf_after),
            "in_band_asd_ratio_raw": metrics_raw["in_band_asd_ratio"],
            "in_band_asd_ratio_injected": metrics_inj["in_band_asd_ratio"],
            "out_of_band_asd_ratio_injected": metrics_inj["out_of_band_asd_ratio"],
            "seconds": time.time() - started,
        }
        records.append(rec)
        ratio = rec["optimal_snr_ratio_after_over_before"]
        print(
            f"[{k + 1}/{len(plan)}] snr {snr} m1 {m1:.0f} match {match:.4f} "
            f"snr ratio {ratio:.4f} mf {mf_before:.2f}->{mf_after:.2f} "
            f"band asd {metrics_inj['in_band_asd_ratio']:.3f}",
            file=sys.stderr,
            flush=True,
        )
    summary = {}
    for snr in args.snr:
        rows = [r for r in records if r["target_snr"] == snr]
        summary[str(snr)] = {
            "n": len(rows),
            "match_median": float(
                np.median([r["match_after_vs_injected"] for r in rows])
            ),
            "match_min": float(np.min([r["match_after_vs_injected"] for r in rows])),
            "snr_ratio_median": float(
                np.median([r["optimal_snr_ratio_after_over_before"] for r in rows])
            ),
            "mf_snr_change_median": float(
                np.median(
                    [
                        r["matched_filter_snr_after"] - r["matched_filter_snr_before"]
                        for r in rows
                    ]
                )
            ),
            "in_band_asd_ratio_median": float(
                np.median([r["in_band_asd_ratio_injected"] for r in rows])
            ),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data_file": str(args.data),
                "held_out_start": t0,
                "weights": str(args.weights),
                "config": config,
                "summary": summary,
                "records": records,
            },
            indent=1,
        )
        + "\n"
    )
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
