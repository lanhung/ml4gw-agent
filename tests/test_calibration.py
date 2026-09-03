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
