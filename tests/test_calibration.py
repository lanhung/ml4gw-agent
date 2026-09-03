from ml4gw_agent.calibration import aframe_threshold, load_aframe_table

YEAR = 365.25 * 86400


def test_shipped_table_loads():
    table = load_aframe_table()
    assert "revisions" in table


def test_threshold_lookup_rules():
    table = {
        "revisions": {
            "rev": {
                "livetime_seconds": 2 * YEAR,
                "thresholds_by_far_per_year": {"12": 3.0, "1": 4.5, "0.1": 6.0},
            }
        }
    }
    assert aframe_threshold(None, 1.0, table) is None
    assert aframe_threshold("missing", 1.0, table) is None
    assert aframe_threshold("rev", 1.0, table).threshold == 4.5
    assert aframe_threshold("rev", 5.0, table).far_per_year == 1.0
    assert aframe_threshold("rev", 12.0, table).threshold == 3.0
    # 0.1 per year needs 10 years of livetime; only 2 are available
    assert aframe_threshold("rev", 0.1, table) is None
    assert aframe_threshold("rev", 0.05, table) is None
    table["revisions"]["rev"]["allow_extrapolation"] = True
    assert aframe_threshold("rev", 0.1, table).threshold == 6.0


def test_update_script_only_writes_measurable_rates(tmp_path):
    import json
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[1] / "scripts"))
    import update_aframe_calibration as upd

    result = {
        "model": {"revision": "rev"},
        "livetime_seconds": 5 * 86400.0,  # five days: 1/day measurable, 1/month not
        "n_peaks": 10,
        "loudest_background_peaks": [3.5, 2.7],
        "stretches": [{"start": 1, "end": 2, "duration": 1, "analysed": True}],
        "lags": [{}, {}],
        "thresholds": {
            "far_1_per_day": 2.9,
            "far_1_per_month": 3.5,
            "far_1_per_year": 3.5,
            "far_1_per_100_years": 3.5,
        },
    }
    assert upd.measurable_thresholds(result) == {"365.25": 2.9}
    table = tmp_path / "table.json"
    table.write_text(json.dumps({"revisions": {}}))
    src = tmp_path / "bg.json"
    src.write_text(json.dumps(result))
    assert upd.main([str(src), "--table", str(table)]) == 0
    written = json.loads(table.read_text())["revisions"]["rev"]
    assert written["thresholds_by_far_per_year"] == {"365.25": 2.9}
    assert written["n_lags"] == 2
    loaded = json.loads(table.read_text())
    assert aframe_threshold("rev", 365.25, loaded).threshold == 2.9
    assert aframe_threshold("rev", 12.0, loaded) is None
