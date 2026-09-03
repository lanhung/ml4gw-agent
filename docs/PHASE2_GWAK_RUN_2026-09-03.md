# Phase 2 — GWAK route on real data — 2026-09-03

Evidence: `docs/acceptance/gwak-route-2026-09-03/<case>/run_manifest.json`
(runs on the GPU node, prompt "Run Aframe and GWAK on <event> and reconcile
the two results.", `--gwak-revision gwak2-7b9f58a-S4SimCLR-f775aed5-NFonlyBkg-a0c755ad`).

## Models

Upstream ML4GW/gwak publishes no inference package or weights. The models
used here are the user's own GWAK 2.0 training on the CIT LDG cluster
(repository commit `7b9f58a`, home-directory checkout), exported as
TorchScript and pinned by SHA-256 in `models/gwak/MANIFEST.json`:

| Role | File | Input | Output |
|---|---|---|---|
| embedder | `embedder_S4_SimCLR_multiSignalAndBkg.pt` (`f775aed5…`) | (batch, 2, 2048) whitened H1+L1 at 4096 Hz | (batch, 8) |
| metric | `metric_NF_onlyBkg.pt` (`a0c755ad…`) | (batch, 8) | log probability under the background flow |

Anomaly score = −log p. Preprocessing follows the training configuration
(4096 Hz, 0.5 s kernels, PSD from the first 64 s, 1 s whitening filter, 2 s
FFT); highpass 30 Hz and the 1/16 s stride are adapter parameters recorded
in every manifest. Two implementation findings: the exported flow hard-codes
CPU float64 inside its graph (it runs on the CPU on the embeddings), and
strain must be normalised before whitening because its PSD (~1e-42)
underflows float32.

## Results (1001 kernels per 62.5 s analysis segment)

| Case | Aframe statistic / candidate | GWAK max | GWAK median | score at target | z at target | rank of target kernel | reconcile route |
|---|---|---:|---:|---:|---:|---:|---|
| GW150914 | 9.506 / yes | 15.35 | 12.93 | 15.35 | 10.5 | 0 of 1001 | consistent_candidate |
| GW190521 | 8.733 / yes | 14.30 | 12.83 | 14.30 | 11.8 | 0 of 1001 | consistent_candidate |
| noise GPS 1126260200 | 0.513 / no | 14.04 | 12.90 | 13.25 | 1.5 | 153 of 1001 | gwak_only (see below) |
| GW170817 (GPS 1187008882.4) | −0.129 / no | 13.99 | 12.83 | 13.30 | 4.3 | 47 of 1001 | gwak_only |

The two binary black hole events are the loudest kernel of their windows at
exactly the catalog time; the noise segment's loudest kernel (14.04) sits
between the two events' peaks, so the separation is real but small with
these checkpoints. GW170817 gets a mild response (z 4.3) but is not the
loudest kernel.

`anomaly_found` is still the raw `threshold: 0.0` cut, so it is true for
every window and the reconcile route reports `gwak_only` on the noise
segment. As for Aframe, the threshold needs a time-shifted background
study before the flag means anything; until then `target_score`,
`target_zscore` and `target_rank` are the quantities to read.

## Stride matters

With the first default stride of 0.25 s the score was flat (12.685) because
the strain PSD underflowed, and after that fix the 0.25 s grid still missed
the 0.2 s chirp: max 14.13 at 2.6 s before the merger. At 1/16 s the peak
aligns with the merger on both events. The GWAK deploy pipeline's own
inference sampling rate is not in the exported configuration; this is one
of the questions for the GWAK team.

## Open

- Threshold calibration (time-shifted background, same method as Aframe).
- Confirmation from the GWAK authors of the embedder/metric pairing (the CIT
  checkout also holds `linear_metric/SimCLR_multiSignal_all` linear and MLP
  metrics and an `FM_multiSignalAndBkg` classifier trained on another
  embedder), the highpass, and the inference stride.
- Injection and glitch sets for the acceptance suite.
