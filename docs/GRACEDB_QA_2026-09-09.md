# GraceDB question-answering validation (2026-09-09)

Question: can a user point the agent at an important GraceDB superevent, by
any of the ways people refer to it, and get a correct, honest answer?

Set: `benchmarks/gracedb/qa_events.yaml`, 13 superevents chosen from the
public O4 alert list (heaviest BBH, loudest O4a event, a mass-gap NSBH seen
by one detector, the O4b high-profile BBH, three O4c HLV superevents whose
strain is not public, an H1+V1-only event, a HIGH_PROFILE candidate, a
retracted alert) times five prompt styles: superevent id in English,
superevent id in Chinese, GWTC name (when one exists), GPS time, UTC
timestamp. 59 prompts. Truth: the anonymous GraceDB API (`t_0`, FAR,
instruments, `ADVNO`) and the GWOSC catalogs (GWTC-4.x, GWTC-5.0, O4
discovery papers) folded into the shipped table
`calibration/gwtc_events.json` (393 events, 308 with GraceDB ids).
Scorer: `scripts/gracedb_qa.py`; evidence
`docs/acceptance/gracedb-qa-2026-09-09/` (stage1.json, stage2.json, QA.md,
one manifest per real run under `runs/`).

## Stage 1: understanding the question (local, no strain)

| check | result |
|---|---:|
| identifier extracted and a valid plan produced | 59 / 59 |
| event time resolved within 1 s of GraceDB `t_0` | 59 / 59 |
| detector set reported (superevent prompts) | 26 / 26 |
| retraction flagged (S251017di) / not flagged (others) | 26 / 26 |

Every prompt style resolves to the same time: S-ids and G-ids through
GraceDB, GW names through the shipped table, UTC strings through astropy,
GPS directly. The retracted alert is answered with `retracted: true` and
the note "retracted by the collaboration (ADVNO)".

## Stage 2: running the analysis (CIT HTCondor, public GWOSC strain)

All 59 runs behaved as the set expects (59 / 59):

| superevent | prompts | outcome | detail |
|---|---:|---|---|
| S231123cg (GW231123, 137+101 Msun) | 5 | completed, Aframe candidate 5/5 | statistic 8.85, tc offset −9 ms; AMPLFI chirp mass 66 (47–81) vs catalog 101 (71–114): the HL model under-estimates this extreme mass |
| S231226av (GW231226, SNR 34.7) | 5 | completed, candidate 5/5 | tc −17 ms; chirp mass 33.1 vs 32.5 (in 90 %) |
| S231028bg (GW231028, 94+59) | 5 | completed, candidate 5/5 | tc −18 ms; chirp 62.9 vs 63.0 (in 90 %) |
| S231224e (GW231224, 9.3+7.3) | 5 | completed, candidate 5/5 | tc +7 ms; chirp 8.9 vs 7.1 (outside 90 %) |
| S240104bl (GW240104) | 5 | completed, analysis skipped | data-quality gate: L1 samples not finite in the public file, `L1_DATA` flag does not cover the window |
| S230529ay (GW230529, NSBH, L1 only) | 5 | failed closed at fetch | no public H1 data: the agent refuses a two-detector analysis rather than fabricating one |
| S250114ax (GW250114, O4b) | 5 | completed, candidate 5/5 | tc −43 ms; chirp 28.8 vs 28.6 (in 90 %) |
| S250119cv | 4 | completed, candidate 4/4 | tc −82 ms (same as the NDS2 run of 2026-09-03); public strain now exists for it |
| S250727cl, S251108dn, S250810ck, S250206dm (O4c) | 16 | failed closed at fetch | no public strain; each manifest names the missing detector and interval |
| S251017di (retracted) | 4 | failed closed at fetch, retraction recorded | resolution says retracted; no public strain |

Identical answers across the five phrasings of the same event (same
resolved time, same plan, same results) is the property that matters for a
question-answering interface; it holds for every event in the set.

## What was fixed while building this

- `data.resolve_event` previously knew three GW names and delegated every
  GraceDB id; it now ships the GWTC table, queries GraceDB anonymously in
  real mode, parses UTC timestamps, and reports FAR, detectors, retraction
  and the resolution source. The public GWOSC adapter accepts GraceDB ids
  once a GPS time is resolved.
- One worker returned an empty `instruments` string from GraceDB; the
  resolver now falls back to the preferred event's detector list.

## Not covered

The agent answers analysis requests; it does not answer free-form
questions ("what is the mass of GW231123?") without running the analysis.
A retrieval-only route that answers such questions from the catalog table
and GraceDB without touching strain is a small addition and would remove
the GPU cost for lookup questions.
