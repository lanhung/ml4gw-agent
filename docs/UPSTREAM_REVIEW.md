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

Behaviour confirmed on the GPU node on 2026-09-03 (Buoy 0.6.1,
`buoy/utils/data.py::get_data`): for catalog event names (`GW...`) Buoy takes
the detector list from `gwosc.datasets.event_detectors` and **ignores
`--ifos`**; the option is only honoured for bare GPS times. It then picks the
HL or HLV AMPLFI checkpoint from the number of detectors it fetched. GW190521
therefore ran with H1+L1+V1 (`amplfi_HLV.fits`) although the agent asked for
H1+L1. The adapter now records `detectors_used` and `amplfi_network` from
Buoy's output files and attaches a warning when they differ from the request.
Events whose GWOSC detector list includes GEO (`G1`, for example GW170817)
make Buoy raise "does not have the required detectors".

Model registry HEAD revisions observed on 2026-09-02:

- ML4GW/Aframe: `3c947f6ded4a8b4b5a5dd7620d3e2e710e1716f4`
- ML4GW/AMPLFI: `8b97d2f8459d04924cb010dfee0262260bf3da80`

These are recorded as a reproducible starting point, not silently selected as
runtime defaults. A production operator should confirm the intended model
revisions with maintainers and pass them explicitly.

## GWAK (reviewed 2026-09-03)

- Repository: <https://github.com/ML4GW/gwak> (GWAK 2.0, with the GWAK 1
  configuration kept under `_gwak1` Snakefile targets).
- Interface: Snakemake targets only (`snakemake -c1 train_all`,
  `snakemake -c1 scan_all`, `build_containers`, `production_export`) on top of
  `data`, `train` (PyTorch Lightning), and `deploy` (Triton/hermes)
  sub-projects; Python 3.11; installed from a checkout with submodules.
- Not provided: a packaged release, a documented inference entry point, or
  pretrained weights at an immutable revision. The `gwak.scan` contract's
  `immutable_model` and `compatible_preprocessing` preconditions therefore
  cannot be met from public artifacts.
- Agent decision: `gwak.scan` is a fail-closed python adapter that reports
  this blocker in `doctor` and `preflight`; planner routing
  (`analysis.reconcile`) and the benchmark are exercised in mock mode.
  Re-review when GWAK publishes an inference package and weights.

## DeepClean (reviewed 2026-09-03)

- Repository: <https://github.com/ML4GW/DeepClean>; `libs` + `projects`
  layout run through `pinto`/Poetry with Luigi/Law tasks; Conda environment;
  git submodules required.
- Inputs are the calibrated strain plus auxiliary witness channels from LDG
  frames; no pretrained weights or coupling configurations are published.
- Agent decision: `deepclean.check_applicability` is real and decides from
  the strain source and the reviewed table
  `ml4gw_agent/calibration/deepclean_support.json` (empty until a
  configuration passes the signal-preservation review). Public GWOSC strain
  is inapplicable by construction. `deepclean.clean` stays planned.

## mldatafind (reviewed 2026-09-03)

- Repository: <https://github.com/ML4GW/mldatafind>; Law workflows
  (`law run mldatafind.law.tasks.Fetch`, `--workflow local|htcondor`) that
  query science segments and strain from LDG; configuration via
  `LAW_CONFIG_FILE`; Apptainer images for HTCondor.
- Agent decision: instead of wrapping the Law task, `data.fetch` with
  `source: ldg` mirrors Buoy's own non-public access
  (`gwpy.timeseries.TimeSeries.get` on `H1:GDS-CALIB_STRAIN_CLEAN`,
  `L1:GDS-CALIB_STRAIN_CLEAN`, `V1:Hrec_hoft_16384Hz`, discovered through
  `gwdatafind`) and fails closed without IGWN credentials. Cannot be
  exercised from the public GPU node; the fake-backend unit tests cover the
  contract.

## Other initial repositories

- <https://github.com/ML4GW/aframe> and <https://github.com/ML4GW/amplfi>
  are reached through Buoy's published model wrappers at the pinned Hugging
  Face revisions; direct upstream training or inference code is not used.
