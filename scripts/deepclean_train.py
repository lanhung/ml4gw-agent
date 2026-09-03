#!/usr/bin/env python3
"""Train DeepClean for one coupling from an NDS2-fetched HDF5 file.

Input file layout (as written by the NDS2 fetch helper): one dataset per
channel with a ``sample_rate`` attribute, ``t0`` and ``duration`` in the
file attributes. Witnesses and strain are resampled to the configured
rate, the first ``--train-seconds`` are used for training (with the
configured validation fraction at the end of that stretch) and the
remainder is held out for the reported cleaning metrics.

    uv run python scripts/deepclean_train.py data.hdf5 --ifo H1 \
        --strain H1:GDS-CALIB_STRAIN --witness H1:PEM-CS_MAINSMON_EBAY_1_DQ \
        --freq-low 55 --freq-high 65 --output models/deepclean/H1_60Hz
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import h5py
import numpy as np


def resample(x: np.ndarray, rate_in: float, rate_out: float) -> np.ndarray:
    if abs(rate_in - rate_out) < 1e-9:
        return x
    from scipy import signal

    factor = rate_in / rate_out
    if abs(factor - round(factor)) < 1e-9:
        return signal.resample_poly(x, 1, int(round(factor)))
    n_out = int(round(len(x) * rate_out / rate_in))
    return signal.resample(x, n_out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("data", type=Path)
    parser.add_argument("--ifo", required=True)
    parser.add_argument("--strain", required=True)
    parser.add_argument("--witness", action="append", required=True)
    parser.add_argument("--freq-low", type=float, required=True)
    parser.add_argument("--freq-high", type=float, required=True)
    parser.add_argument("--sample-rate", type=float, default=4096.0)
    parser.add_argument("--train-seconds", type=float, default=4096.0)
    parser.add_argument("--max-epochs", type=int, default=100)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    from ml4gw_agent.adapters.deepclean_model import (
        DeepCleanConfig,
        clean_strain,
        save_weights,
        train_deepclean,
    )

    with h5py.File(args.data, "r") as handle:
        t0 = float(handle.attrs["t0"])
        strain_raw = handle[args.strain][:]
        strain = resample(
            strain_raw,
            float(handle[args.strain].attrs["sample_rate"]),
            args.sample_rate,
        )
        witnesses = np.stack(
            [
                resample(
                    handle[c][:],
                    float(handle[c].attrs["sample_rate"]),
                    args.sample_rate,
                )
                for c in args.witness
            ]
        )
    n_train = int(args.train_seconds * args.sample_rate)
    config = DeepCleanConfig(
        ifo=args.ifo,
        strain_channel=args.strain,
        witness_channels=list(args.witness),
        freq_low=args.freq_low,
        freq_high=args.freq_high,
        sample_rate=args.sample_rate,
        max_epochs=args.max_epochs,
    )
    started = time.time()
    weights = train_deepclean(
        strain[:n_train],
        witnesses[:, :n_train],
        config,
        device=args.device,
        log=lambda m: print(m, file=sys.stderr, flush=True),
    )
    train_seconds = time.time() - started
    args.output.mkdir(parents=True, exist_ok=True)
    weights_path = args.output / "deepclean.pt"
    digest = save_weights(weights, weights_path)
    metrics = None
    if len(strain) > n_train + int(64 * args.sample_rate):
        _, metrics = clean_strain(
            strain[n_train:], witnesses[:, n_train:], weights, device=args.device
        )
    record = {
        "ifo": args.ifo,
        "strain_channel": args.strain,
        "witness_channels": list(args.witness),
        "freq_low": args.freq_low,
        "freq_high": args.freq_high,
        "sample_rate": args.sample_rate,
        "gps_start": t0,
        "gps_end": t0 + len(strain) / args.sample_rate,
        "train_seconds": args.train_seconds,
        "data_file": str(args.data),
        "data_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
        "weights_file": weights_path.name,
        "weights_sha256": digest,
        "best_val_asd_ratio": weights["best_val_ratio"],
        "best_epoch": weights["best_epoch"],
        "epochs_run": len(weights["history"]),
        "training_seconds": train_seconds,
        "held_out_metrics": metrics,
        "config": config.as_dict(),
        "reference": "ML4GW/deepcleanv2 myprojects/60Hz-O3-MDC config and couplings/sub_60Hz.py",
    }
    (args.output / "training_record.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )
    (args.output / "history.json").write_text(
        json.dumps(weights["history"], indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: record[k]
                for k in (
                    "best_val_asd_ratio",
                    "best_epoch",
                    "held_out_metrics",
                    "weights_sha256",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
