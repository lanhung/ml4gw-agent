# Every "failed" record in the acceptance panel, explained (2026-09-10)

Short version: none of these are crashes or bugs. Each one is an adapter or a
plan condition refusing to produce a number it cannot justify, with the reason
written into the run manifest. There are four distinct categories, plus two
kinds of "completed but empty" that look similar in a table.

| Category | What the panel shows | How many | Meaning |
|---|---|---:|---|
| A. No public strain for the requested detectors | run `failed`, blank statistic | 25 QA runs (6 superevents), 7 population events | the data does not exist publicly; the fetch refuses rather than substituting another detector or a shifted window |
| B. Data-quality gate | run `completed`, blank statistic | 5 QA runs (1 superevent), 7 population events | the strain exists but is unusable; the analysis tasks are skipped by the plan's condition |
| C. Upstream tool cannot handle the event | run `failed` on `analyze_event` | 2 phase-1b runs | Buoy refuses GW170817; the decomposed route still completes |
| D. Comparison not possible | comparison row `failed` | 2 phase-1b comparisons | one side of the comparison produced no file, so nothing could be compared |
| E. Analysed, below threshold | run `completed`, statistic present, no candidate | 16 population events | a real, honest negative from the model |

---

## A. No public strain for the requested detectors

The error text is always of the form

```
AdapterError: gwosc fetch failed for H1 over [1444770412.0, 1444770540.0]:
GetExceptionGroup: failed to get data from any source
```

and it names the detector and the exact 128 s interval. Everything downstream
is marked `failed or blocked dependencies: fetch_data`, so no partial analysis
is reported.

### In the GraceDB question-answering block (25 runs, 6 superevents)

| Superevent | Detectors | Why there is no public two-detector data |
|---|---|---|
| **S230529ay** = GW230529_181500 | L1 only | The mass-gap neutron-star black-hole event of O4a. It was observed while Hanford was not operating, so a public H1+L1 analysis is impossible. This is the most instructive failure in the set: the event is real, famous and in the catalog, and the agent still refuses, because the analysis the user asked for cannot be done with public data. A system that quietly analysed L1 alone, or silently substituted Virgo, would have returned a plausible number with no meaning. |
| **S250206dm** | H1, L1 | An O4b candidate that is still proprietary. Public strain is released on the collaboration's own schedule, typically well after the observing run; the alert exists in GraceDB but the data does not exist on GWOSC. |
| **S250727cl** | H1, L1, V1 | O4c candidate, same reason. FAR 4e-20 Hz, so scientifically interesting, but the data is embargoed. |
| **S250810ck** | H1, V1 | O4c candidate seen by Hanford and Virgo, with no Livingston data at all. Two independent reasons to refuse: embargoed data and a detector set the requested Aframe model does not support. |
| **S251108dn** | H1, L1, V1 | O4c candidate, embargoed. |
| **S251017di** | H1, L1 | A **retracted** alert. This one is worth showing on a slide: the resolver reports `retracted: true` with the note "retracted by the collaboration (ADVNO)" *before* any data access is attempted, and then the fetch fails closed because the strain is not public either. The user is told the candidate was withdrawn rather than being handed an analysis of a non-event. |

The same six events fail identically in all four or five phrasings (superevent
id in English, superevent id in Chinese, GPS time, UTC timestamp, and the GWTC
name where one exists). That consistency is the point: the refusal is a
property of the data, not of how the question was worded.

### In the 90-event population run (7 events)

GW190620_030421, GW190630_185205, GW190708_232457, GW190925_232845,
GW191216_213338, GW200112_155838, GW200302_015811.

All seven are **single-LIGO events**: only one of Hanford or Livingston was
observing at the time, and the catalog entry comes from that detector plus
Virgo or from a single-detector search. The run asked for an H1+L1 analysis,
which is what the Aframe model is trained for, so the fetch of the missing
detector fails and the plan stops. Four of them are missing H1, three are
missing L1; the manifest says which.

---

## B. Data-quality gate: strain exists but is unusable

These runs are marked **completed**, because the plan ran to completion and
produced a report; the Aframe, AMPLFI and GWAK tasks are marked `skipped`
because their condition `${inspect_data.outputs.quality_passed}` evaluated
false. The blank statistic in the table means "never computed", not "computed
and low".

### S240104bl = GW240104_164932 (5 QA runs)

```
L1: 100.000% of samples are not finite
L1: strain is constant (zero variance)
L1: L1_DATA flag does not cover [1388422094.0, 1388422222.0]; segments []
```

The public file for this window contains no valid Livingston data at all. The
detector was not in observing mode over that interval, and GWOSC serves the
file with placeholder values. Feeding that to a whitening filter would produce
either numerical garbage or, worse, a confident-looking statistic.

### Seven events in the population run

| Event | Problem |
|---|---|
| GW170608 | `H1_DATA` flag does not cover the window, segments empty. Hanford was in a special state during this event (the well-known case where H1 data required custom handling), so the public data-quality flag does not certify the window. |
| GW190425 | 100 % of H1 samples not finite, zero variance. This is the binary neutron star seen essentially by L1 alone. |
| GW190513_205428 | 8.6 % of H1 samples not finite; the flag covers only part of the window. |
| GW190725_174728 | 60.2 % of H1 samples not finite; the flag covers 52 s of the requested 128 s. |
| GW190814 | `H1_DATA` flag does not cover the window, segments empty. |
| GW190910_112807 | 100 % of H1 samples not finite, zero variance; Hanford was not observing. |
| GW200316_215756 | 35.9 % of L1 samples not finite; partial flag coverage. |

The gate checks three things independently: are the samples finite, does the
strain have non-zero variance, and does the official data-quality flag cover
the full requested interval. Any one of them failing stops the analysis. Note
that several of these events *are* in the catalog with good parameters, because
the collaboration analysed them with a different detector combination or a
different window than the one the agent requested.

---

## C. Buoy cannot handle GW170817 (2 runs)

In the phase-1b records for GW170817 and for its GPS time 1187008882.4, the
task `analyze_event` fails with:

```
AdapterError: Buoy exited with code 1
ValueError: Event GW170817 does not have the required detectors.
Expected ['H1','L1'] or ['H1','L1','V1'], got ['G1','H1','L1','V1']
```

GWOSC lists GEO600 (G1) alongside the three main detectors for this event, and
Buoy 0.6.1 matches the detector list exactly rather than selecting a supported
subset. This is a limitation of the upstream vertical pipeline, not of the
data. The interesting part is what happens next: the agent's **decomposed**
route, which fetches H1 and L1 itself and calls the Aframe and AMPLFI adapters
directly, completes normally and returns a detection statistic of **-0.129**,
far below the one-per-day threshold. That is the scientifically correct answer,
because GW170817 is a binary neutron star and the Aframe model shipped here is
trained on binary black holes with component masses above 5 solar masses. So
the same event produces a tool failure on one route and a correct negative on
the other, and the manifests distinguish the two.

---

## D. Comparisons that could not be made (2 rows)

The phase-1b acceptance script compares the agent against a direct Buoy run on
the same data. For GW170817 the comparison rows read
`failed · AMPLFI: not compared (missing file)` with the recorded reason
`no quantity could be compared`. Because Buoy refused the event (category C),
there is no reference output to compare against. The script does not invent a
baseline or silently pass; it records that the comparison was impossible. For
the GPS-time variant of the same event, the decomposed comparison did succeed
on the detection statistic (agreement to 8e-7) and only the AMPLFI part was
skipped, again because the Buoy side produced no posterior file.

---

## E. Analysed but no candidate: 16 real negatives

These are not failures at all, but they are worth separating in a talk because
a reader scanning the panel may lump them together. In the population run, 16
of the 76 analysed events produced a statistic below the calibrated
one-per-day threshold:

- **Five are neutron-star events outside the model's training range**:
  GW170817 (-0.13), GW200115_042309 (-0.06), GW191219_163120 (-0.13),
  GW200210_092254 (0.95), GW190917_114630 (-0.13). Component masses of 1.2 to
  2.8 solar masses are simply not what this network was trained to see. A
  statistic pinned near -0.13 means the network output never rose above its
  floor anywhere in the window.
- **Eleven are binary black holes with low catalog SNR**, from 4.7 to 12.0
  with a median of 7.9. Examples: GW190924_021846 (SNR 12.0, statistic 1.19),
  GW190720_000836 (10.9, 2.70), GW200202_154313 (10.8, 2.17), GW151012 (9.3,
  1.09). Aframe's own published O3 search shows the same behaviour, missing
  events below roughly SNR 12; our injection study puts 50 % efficiency at
  network SNR 8.2 and 90 % at 11.8, which brackets these numbers exactly.

So the misses are consistent with the model's documented sensitivity, and the
agent reports them as measured statistics with the threshold and its provenance
attached, not as a bare "not found".

---

## Why this matters for the talk

The published failure literature on scientific agents says the dangerous mode
is not the crash but the confident wrong answer. Our adversarial benchmark
measures exactly that: with the same language model, taking its first plan at
face value would have executed a plausible but wrong analysis for about a third
of adversarial requests, while the contract path executed none. The records
above are that principle in production, on real events that people care about:

- a famous catalog event (GW230529) refused because the requested analysis is
  impossible with public data,
- a retracted alert flagged as retracted before anything is downloaded,
- seven events whose public files are unusable, stopped by an automatic gate
  rather than by a person noticing later,
- an upstream tool's limitation isolated to one route while the other route
  returns the scientifically correct negative,
- and a comparison that declines to report agreement when there is nothing to
  compare.

Every one of those decisions is in a manifest with the detector, the interval,
the reason and the artifact hashes, so a reviewer can check it without rerunning
anything.
