# Phase 1b acceptance suite — five cases — 2026-09-03

Follow-up to `PHASE1B_ACCEPTANCE_RUN_2026-09-03.md` (GW150914). The roadmap's
Phase 1b exit criterion asks for GW150914, GW170817 (where model support
permits), GW190521, one GPS-identified event, and one noise segment, each
with a reviewed expected outcome, plus agent-versus-Buoy equivalence within
tolerance. This record covers the four remaining cases. Same node, GPU,
environment, model revisions, and seed (0) as the GW150914 run; the
repository commits under test are `1f688c1` to `dc4dfc6`.

Evidence bundles live under `docs/acceptance/<run>/` (manifests, reports,
logs, `status.txt`, both comparison JSON files, quality diagnostics, credible
intervals). Large HDF5/FITS/PNG outputs stay on the node under
`/root/autodl-tmp/ml4gw-agent-runs/`.

## Summary

| Case | Run | Detectors | Agent Buoy slice | Agent decomposed | Direct Buoy | Slice vs Buoy | Decomposed vs Buoy |
|---|---|---|---|---|---|---|---|
| GW190521 | `phase1b-GW190521-20260903T032417Z` | H1 L1 V1 | completed | completed | completed (HLV) | 7/7 pass | 7/7 pass |
| GPS event 1126259462.4 (GW150914 by time) | `phase1b-1126259462.4-20260903T033728Z` | H1 L1 | completed | completed | completed (HL) | 7/7 pass | 7/7 pass |
| Noise segment GPS 1126260200 | `phase1b-1126260200-20260903T033909Z` | H1 L1 | completed | completed | completed (HL) | 7/7 pass | 7/7 pass |
| GW170817 by name | `phase1b-GW170817-20260903T034613Z` | H1 L1 | **failed** (Buoy exit 1) | completed, no candidate, AMPLFI skipped | **failed** (same Buoy error) | nothing to compare | nothing to compare |
| GW170817 by GPS 1187008882.4 | `phase1b-1187008882.4-20260903T034721Z` | H1 L1 | **failed** (Buoy exit 1 in AMPLFI) | completed, no candidate, AMPLFI skipped | Aframe done, **AMPLFI crashed** | nothing to compare | Aframe 1/1 pass, tc and PE not comparable |

Every agent run, including the failed ones, ended with a checkpointed
manifest, a report, captured Buoy logs, SHA-256 hashes on every artifact, and
no `simulated: true`.

## GW190521 (three-detector event)

First attempt (`phase1b-GW190521-20260903T031256Z`, kept on the node but not
in the record) used the default `H1 L1` request. The Buoy slice and the direct
Buoy run agreed with each other, but the decomposed run disagreed with Buoy on
distance (9.7 %) and mass ratio (7.8 %). The cause was not numerical: Buoy
0.6.1 ignores `--ifos` for catalog event names, fetched H1+L1+V1 from GWOSC,
and ran the **HLV** AMPLFI checkpoint, while the decomposed adapters ran the
HL checkpoint on H1+L1. The manifest of the Buoy slice nevertheless recorded
`ifos: [H1, L1]`. Three changes followed (`1f688c1`):

- `buoy.analyze` now records `detectors_used` and `amplfi_network` from
  Buoy's output files and warns when they differ from the request.
- The composed planner keeps Aframe on H1+L1 (the published model's detector
  set) and passes the requested detectors to `data.fetch`, `data.inspect`,
  and `amplfi.pe`, which is what Buoy does internally.
- `compare_with_buoy.py` refuses to compare posteriors from different
  networks, and `phase1b_acceptance.sh` takes `IFOS`.

Second attempt with `IFOS="H1 L1 V1"`:

| Quantity | Agent slice | Agent decomposed | Direct Buoy (HLV) |
|---|---:|---:|---:|
| peak detection statistic | 8.73328 | 8.73323 | 8.73327 |
| predicted coalescence time | 1242442967.4375 | 1242442967.4375 | 1242442967.4375 |
| offset from catalog time 1242442967.4 | +0.037 s | +0.037 s | +0.037 s |
| posterior samples | 19979 | 19979 | 19979 |
| median chirp mass (detector frame) | 87.70 | 87.70 | 87.70 M☉ |
| median chirp mass (source frame) | — | 64.10 [50.0, 75.5] | — |
| median mass 1 / mass 2 (detector frame) | 205.5 / 50.6 | 205.5 / 50.6 | 205.5 / 50.6 M☉ |
| median mass ratio | 0.238 | 0.238 | 0.238 |
| median luminosity distance | 1861 | 1861 [1080, 2701] | 1861 Mpc |
| 90 % / 50 % sky area | — | 1302 / 276 deg² | 1302 / 276 deg² |

Agent-versus-Buoy differences are at most 8e-5 relative (posterior medians)
and 4e-6 (Aframe statistic). Reference values for the reviewer: the
discovery paper (Abbott et al. 2020, PRL 125, 101102) gives source-frame
masses 85 (+21/−14) and 66 (+17/−18) M☉, luminosity distance 5.3 (+2.4/−2.6)
Gpc, redshift 0.82, and a 90 % sky area of about 770 deg²; GWTC-2.1 later
moved the distance to about 3.9 Gpc (z ≈ 0.64). Against these, AMPLFI's
source-frame chirp mass (64 M☉) is consistent, but its mass ratio (0.24, 90 %
interval 0.14–0.39) and distance (1.9 Gpc) are not. The agent reproduces
Buoy exactly here, so this is a property of the published HLV AMPLFI
checkpoint on a very massive event and must be judged by the domain
reviewer, not fixed in the orchestration layer.

## GPS-identified event (1126259462.4)

Identical data window to the GW150914 name-based run. Buoy honours `--ifos`
for bare GPS times, so all three paths used HL. Results reproduce the
GW150914 record to the same precision (statistic 9.5059, tc
1126259462.4141, chirp mass 29.48 M☉, distance 461 Mpc); posterior medians of
the Buoy slice are bit-identical to the direct run, the decomposed run agrees
within 6e-5 relative.

The acceptance script's GWOSC reachability check called `event_gps` on the
GPS string and failed (HTTP 404); fixed in `5609543`, which also made the
script continue after a failed step and record each step's exit code in
`status.txt`.

## Noise segment (GPS 1126260200, no catalog event)

Window `[1126260104, 1126260232)` from the same O1 files, about 12 minutes
after GW150914, both detectors in science mode, quality gate passed.

| Quantity | Agent slice | Agent decomposed | Direct Buoy |
|---|---:|---:|---:|
| peak detection statistic | 0.51307 | 0.51301 | 0.51307 |
| `candidate_found` | (Buoy has no notion) | **true** | (Buoy has no notion) |
| predicted coalescence time | 1126260141.14 | 1126260141.14 | 1126260141.14 |
| AMPLFI ran | yes | yes | yes |
| median chirp mass | 36.98 | 36.98 [12.4, 86.7] | 36.98 M☉ |
| median distance | 2226 | 2226 [773, 3035] | 2226 Mpc |

All comparisons pass because the three paths compute the same thing. The
scientific reading is the important part: with the uncalibrated raw
threshold of 0.0, a segment with no known signal produces
`candidate_found: true` at statistic 0.51 (GW150914 gives 9.5, GW190521 8.7),
the reported "coalescence time" is simply the window maximum 59 s before the
requested time, and AMPLFI is spent on noise, returning a posterior whose
90 % intervals span most of the prior. This is exactly the roadmap item
"FAR-calibrated Aframe threshold from a background study", now with a
concrete negative example. Until that exists, `candidate_found` from
`aframe.detect` must not be read as a detection claim; the manifest warning
says so on every run. Two follow-ups are recorded in `ROADMAP.md`: the
background study for the threshold, and a candidate-time window relative to
the requested time so that a peak far from the target is not reported as the
target's coalescence time.

## GW170817 (binary neutron star)

By name, Buoy fails before any analysis: GWOSC lists `G1` (GEO600) for
GW170817, Buoy fetches all four detectors, and `get_data` raises
`ValueError: Event GW170817 does not have the required detectors ... got
['G1', 'H1', 'L1', 'V1']`. The agent's Buoy slice records this as an audited
adapter failure (exit 2, failure manifest and report, Buoy stderr captured).
This is the "where model support permits" clause of the roadmap: Buoy 0.6.1
cannot run this event by name at all.

By GPS time with `IFOS="H1 L1"`, Buoy fetches H1+L1, runs Aframe, then
crashes inside AMPLFI: `ValueError: The start of the AMPLFI window before the
start of the data`. The BBH-trained Aframe model has no response at the BNS
merger; its maximum integrated output sits in the first inference steps
(whitening start-up), and Buoy's fixed peak-to-merger offset (−1.99 s) maps
that to 1187008784.008, two seconds **before** the 128 s window starts. Buoy
uses that time unconditionally and fails.

The decomposed path handled the same data the way the contract intends:
`data.fetch` and `data.inspect` passed (both detectors, science mode, finite),
`aframe.detect` reported `detection_statistic −0.129` (identical to Buoy's
−0.129 to 8e-7 relative), `peak_in_window: false`, `raw_peak_time
1187008784.008` (identical to Buoy's value), `candidate_found: false`, and a
warning naming the start-up artefact; `amplfi.pe` was **skipped** by the
`candidate_found` condition and the run completed. Before `55b4a9a` the
adapter raised an error at this point; treating an out-of-window peak as "no
candidate" instead of a failure is the change made for this case, and the
raw value is kept for review.

Expected outcome for the reviewer: a BBH-only Aframe/AMPLFI stack should not
detect GW170817, and the agent must say so without crashing and without
spending AMPLFI on a bogus time. Both hold. A BNS-capable model is outside
Phase 1b.

## Roadmap status after this suite

- Five-event cross-check: **done** for GW150914, GW190521, GPS event, and
  noise segment (agent = Buoy within tolerance); GW170817 is documented as
  unsupported by Buoy with the decomposed path behaving correctly.
- Reruns from manifests: the GPS-event run reproduces the GW150914 numbers
  from the same pinned versions and seed.
- Still open: domain-reviewer sign-off (now including the GW190521 AMPLFI
  posterior and the noise-segment false candidate), the FAR-calibrated
  threshold, a candidate-time window, and `mldatafind`.

## Operational notes

- All strain files were pre-fetched into the astropy cache with
  `scripts/prefetch_gwosc.py --local-dir` after downloading them on a fast
  host (GW190521 H1/L1/V1, GW170817 H1/L1/V1/G1, each 4096 s at 4 kHz, sizes
  and SHA-256 printed by the script). Without the G1 and V1 files Buoy's
  GW170817 attempt spent 20 minutes downloading at 70 kB/s before it could
  even fail; the first such attempt was aborted and is not part of the record.
- GitHub was intermittently unreachable from the node; commits were carried
  over as git bundles and verified by commit hash before each launch.
