# Non-public data access with an IGWN credential — 2026-09-03

What the `fan.zhang@ligo.org` credential unlocked, what was verified, and
what it does not unlock. Evidence: `docs/acceptance/ldg-GW150914-2026-09-03/`
(manifest, report, quality diagnostics of the run below).

## Credential path that works from outside the LIGO Data Grid

| Step | Result |
|---|---|
| Kerberos `kinit fan.zhang@LIGO.ORG` | works from both hosts (KDC reachable) |
| `htgettoken -a vault.ligo.org -i igwn` with Kerberos | fails: the vault's Kerberos service principal is not in the LIGO KDC (`kvno HTTP/vault.ligo.org` not found) |
| `htgettoken` OIDC device flow (browser login once) | works from a host with a fast route to `vault.ligo.org`; token scopes `read:/frames gwdatafind.read dqsegdb.read gracedb.read read:/ligo read:/virgo read:/kagra`, 3 h lifetime, renewable from the stored vault token |
| SSH to LDG head nodes (CIT/LHO/LLO `ldas-pcdev*`) | no route from either host; needs an IGWN network or bastion |
| `datafind.igwn.org` with the token | lists 32 H1 frame types; resolves O1 `HOFT_C02`, O3 `HOFT_C01`, O3 DeepClean-cleaned `HOFT_CLEAN_SUB60HZ_C01`, O4 `HOFT_C00` to OSDF `https://osdf-director.osg-htc.org/...` URLs |
| OSDF download | HTTP 206/200 with the bearer token, 403 without; 10.8 MB/s from the fast host, 17 kB/s from the GPU node in China |
| NDS2 `nds.ligo.caltech.edu:31200` with the Kerberos ticket | connects from the GPU node; at an O4 time fetches `H1:GDS-CALIB_STRAIN_CLEAN` (16 kHz), the PEM magnetometer witness `H1:PEM-CS_MAG_LVEA_VERTEX_X_DQ` (8 kHz) and `H1:LSC-DARM_IN1_DQ`; at the GW150914 time the raw auxiliary channels are listed but report gaps (O1 raw data not online at CIT) |

## `data.fetch --data-source ldg` verified on GW150914

Run in the node's IGWN environment (`/root/autodl-tmp/envs/igwn`: gwpy,
gwdatafind, framel, frameCPP, nds2-client) with frames staged into the frame
cache from the fast host:

| Item | Value |
|---|---|
| frame type / channel | `H1_HOFT_C02` / `H1:DCS-CALIB_STRAIN_C02`, same for L1 (O1 epoch of the reviewed map) |
| native sample rate | 16384 Hz, resampled to 2048 Hz (warning recorded) |
| quality gate | passed, no issues |
| comparison with the public GWOSC strain of the same window | correlation 1.000000 (H1) / 0.999998 (L1); rms difference 1.2 % of the strain rms, from the two different resampling chains (16 kHz to 2 kHz here versus GWOSC's 16 kHz to 4 kHz then 2 kHz) |

Two library issues were found and worked around: gwpy 4.0.2 with the
frameCPP backend drops the time unit while merging frames and fails on
`sample_rate`; the adapter reads channels through `framel` and rebuilds the
series with explicit units, keeping gwpy as the fallback.

## What this does not unlock

- **DeepClean cleaning** still needs a reviewed coupling configuration and
  weights; witness channels are now reachable (NDS2, O4) so the
  applicability gate can be exercised on real non-public data once a
  configuration exists.
- **HTCondor** on the LDG needs shell access to a head node; the credential
  alone does not route there.
- **Bulk frame transfer to the GPU node** is impractical at 17 kB/s; stage
  frames from a well-connected host or run the LDG path on such a host.
