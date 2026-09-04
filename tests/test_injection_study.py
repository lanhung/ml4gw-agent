"""Pure bookkeeping of scripts/injection_study.py (no data, no GPU)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from injection_study import (  # noqa: E402
    STRETCHES,
    WINDOW,
    efficiency,
    snr_at,
    summarise,
    windows,
)


def test_windows_avoid_the_real_events_and_stretch_edges():
    wins = windows()
    assert len(wins) > 60
    for run, t0 in wins:
        _, start, end, (ex_lo, ex_hi) = next(s for s in STRETCHES if s[0] == run)
        assert start + 32 <= t0 and t0 + WINDOW <= end - 32
        assert t0 + WINDOW < ex_lo or t0 > ex_hi


def _rec(snr, aframe_found, rank, z, anomaly=False):
    return {
        "target_snr": snr,
        "index": 0,
        "aframe": {"candidate_found": aframe_found, "detection_statistic": 1.0},
        "gwak": {"anomaly_found": anomaly, "target_rank": rank, "target_zscore": z},
    }


def test_efficiency_and_interpolated_snr_levels():
    records = (
        [_rec(6.0, False, 5, 1.0)] * 4
        + [_rec(10.0, True, 0, 6.0)] * 2
        + [_rec(10.0, False, 3, 2.0)] * 2
        + [_rec(20.0, True, 0, 12.0)] * 4
        + [dict(_rec(20.0, True, 0, 12.0), error="boom")]
        + [_rec(None, False, 7, 1.0)] * 3
    )
    table = efficiency(records, lambda r: r["aframe"]["candidate_found"], [6, 10, 20])
    assert [row["efficiency"] for row in table] == [0.0, 0.5, 1.0]
    assert table[2]["n"] == 4  # the errored record is excluded
    assert snr_at(table, 0.5) == 10.0
    assert snr_at(table, 0.9) == 18.0
    assert snr_at(table, 0.99) == 19.8
    assert snr_at([], 0.5) is None
    assert snr_at([{"target_snr": 6.0, "efficiency": 1.0}], 0.5) == 6.0
    summary = summarise(records, [6, 10, 20])
    assert summary["aframe_candidate_1_per_day"]["snr_50"] == 10.0
    assert summary["gwak_target_is_loudest_kernel"]["table"][1]["efficiency"] == 0.5
    assert summary["gwak_target_zscore_ge_5"]["snr_90"] == 18.0
    assert summary["controls"]["n"] == 3
    assert summary["controls"]["aframe_false_candidates"] == 0
