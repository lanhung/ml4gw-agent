# Upstream interface review

Reviewed on 2026-09-02.

## Buoy

- Repository: <https://github.com/ML4GW/buoy>
- Reviewed commit: `cea5b3b3f9b6e3b7a5c3d967491d90167617d300`
- Commit date: 2026-08-03
- Package name: `ml4gw-buoy`
- Reviewed package version: `0.6.1` (pinned by the optional dependency)
- Compatibility pins from the reviewed upstream lock: `jsonargparse==4.50.0`
  and `zuko==1.4.1`
- Python support declared upstream: 3.10–3.12
- CLI entrypoint: `buoy = buoy.cli:cli`

The reviewed README and source support exactly one event source: `--events`,
`--observing_runs`, or a `--gps_start`/`--gps_end` range. v0.1 deliberately
exposes only a single bounded event per skill call.

The real adapter maps the reviewed options:

- `events`, `outdir`, `samples_per_event`, `nside`, `min_samples_per_pix`
- `use_distance`, `use_true_tc_for_amplfi`, `ifos`, `device`, `seed`
- `aframe_revision`, `amplfi_revision`
- `run_aframe=true`, `run_amplfi=true`, `generate_plots=true`, `to_html=true`

Expected upstream outputs collected by the adapter include:

- `<event>/data/aframe_outputs.hdf5`
- `<event>/data/posterior_samples.dat`
- `<event>/plots/*`
- `<event>/summary.html`

The adapter does not import private Buoy internals or reproduce its data/model
logic. Interface changes should therefore be handled by updating the adapter
and its contract tests against a pinned upstream release.

Model registry HEAD revisions observed on 2026-09-02:

- ML4GW/Aframe: `3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4`
- ML4GW/AMPLFI: `8b97d2f8459d04924cb010dfee0262260bf3da80`

These are recorded as a reproducible starting point, not silently selected as
runtime defaults. A production operator should confirm the intended model
revisions with maintainers and pass them explicitly.

## Other initial repositories

Contracts identify the intended upstream source but do not yet claim a stable
real invocation for:

- <https://github.com/ML4GW/mldatafind>
- <https://github.com/ML4GW/aframe>
- <https://github.com/ML4GW/amplfi>
- <https://github.com/ML4GW/gwak>
- <https://github.com/ML4GW/DeepClean>

Their real adapters require a separate interface and scientific review in the
phases listed in `ROADMAP.md`.
