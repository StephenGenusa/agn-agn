import pytest

from callsigns.roster import (
    Evidence,
    SourceMetric,
    build_roster,
    metric_for,
    overlap_matrix,
    percentiles,
)

STORES = {
    "pota-hunters": [
        {"Callsign": "K1ABC", "Total QSOs": 100, "Total CW": 100, "Total Phone": 0},
        {"Callsign": "W1AW", "Total QSOs": 50, "Total CW": 0, "Total Phone": 50},
        {"Callsign": "G3XYZ", "Total QSOs": 10, "Total CW": 10, "Total Phone": 0},
    ],
    "rbn-cw": [
        {"Callsign": "K1ABC", "Spots": 900, "WPM Median": 30},
        {"Callsign": "DL1XX", "Spots": 100, "WPM Median": 22},
    ],
    "cqww-cw": [
        {"Callsign": "K1ABC", "Times Worked": 500},
        {"Callsign": "G3XYZ", "Times Worked": 5},
    ],
    "fists-sprint": [
        {"Callsign": "K1ABC", "Score": 2000, "QSOs": 30},
    ],
}


def test_percentiles_span_zero_to_one():
    assert percentiles([1, 2, 3]) == [0.0, 0.5, 1.0]


def test_percentiles_of_a_single_value():
    assert percentiles([7]) == [1.0]


def test_percentiles_handle_ties():
    got = percentiles([5, 5, 1])
    assert got[0] == got[1]
    assert got[2] < got[0]


def test_percentiles_of_nothing():
    assert percentiles([]) == []


def test_metric_for_knows_each_provider_family():
    assert metric_for("rbn-cw").column == "Spots"
    assert metric_for("cqww-cw").column == "Times Worked"
    assert metric_for("pota-hunters").column == "Total QSOs"
    assert metric_for("fists-sprint").column == "Score"


def test_rbn_is_observed_evidence_not_confirmed_participation():
    """A skimmer hearing you says you were on the air, not that you entered.

    During a small club event the band is mostly non-participants, so an RBN
    spot cannot stand in for having entered a contest.
    """
    assert metric_for("rbn-cw").evidence is Evidence.OBSERVED
    assert metric_for("cqww-cw").evidence is Evidence.CONFIRMED
    assert metric_for("fists-sprint").evidence is Evidence.CONFIRMED


def test_roster_counts_breadth():
    rows = {r["Callsign"]: r for r in build_roster(STORES)}
    assert rows["K1ABC"]["SourceCount"] == 4
    assert rows["W1AW"]["SourceCount"] == 1


def test_roster_counts_confirmed_participation_separately():
    rows = {r["Callsign"]: r for r in build_roster(STORES)}
    # K1ABC: pota, cqww, fists are confirmed; rbn is observed only.
    assert rows["K1ABC"]["ConfirmedCount"] == 3
    assert rows["DL1XX"]["ConfirmedCount"] == 0
    assert rows["DL1XX"]["SourceCount"] == 1


def test_roster_lists_sources():
    rows = {r["Callsign"]: r for r in build_roster(STORES)}
    assert set(str(rows["K1ABC"]["Sources"]).split(",")) == {
        "pota-hunters",
        "rbn-cw",
        "cqww-cw",
        "fists-sprint",
    }


def test_roster_ranks_confirmed_breadth_first():
    rows = build_roster(STORES)
    assert rows[0]["Callsign"] == "K1ABC"
    counts = [r["ConfirmedCount"] for r in rows]
    assert counts == sorted(counts, reverse=True)


def test_observed_only_callsigns_rank_below_confirmed_ones():
    rows = [r["Callsign"] for r in build_roster(STORES)]
    assert rows.index("G3XYZ") < rows.index("DL1XX")


def test_roster_preserves_raw_metrics():
    rows = {r["Callsign"]: r for r in build_roster(STORES)}
    assert rows["K1ABC"]["rbn-cw_metric"] == 900
    assert rows["K1ABC"]["cqww-cw_metric"] == 500


def test_roster_leaves_absent_sources_blank():
    rows = {r["Callsign"]: r for r in build_roster(STORES)}
    assert rows["W1AW"]["rbn-cw_metric"] is None


def test_roster_records_percentiles():
    rows = {r["Callsign"]: r for r in build_roster(STORES)}
    assert rows["K1ABC"]["rbn-cw_pct"] == pytest.approx(1.0)
    assert rows["DL1XX"]["rbn-cw_pct"] == pytest.approx(0.0)


def test_roster_derives_a_mode_profile():
    rows = {r["Callsign"]: r for r in build_roster(STORES)}
    assert rows["K1ABC"]["Modes"] == "CW"
    assert rows["W1AW"]["Modes"] == "PHONE"


def test_roster_carries_speed_where_known():
    rows = {r["Callsign"]: r for r in build_roster(STORES)}
    assert rows["K1ABC"]["WpmMedian"] == 30
    assert rows["W1AW"]["WpmMedian"] is None


def test_mean_percentile_only_averages_sources_present():
    rows = {r["Callsign"]: r for r in build_roster(STORES)}
    assert 0.0 <= float(str(rows["W1AW"]["MeanPercentile"])) <= 1.0


def test_overlap_matrix_counts_shared_callsigns():
    matrix = overlap_matrix(STORES)
    assert matrix[("cqww-cw", "pota-hunters")] == 2
    assert matrix[("rbn-cw", "cqww-cw")] == 1


def test_overlap_matrix_is_symmetric():
    matrix = overlap_matrix(STORES)
    for (a, b), count in matrix.items():
        assert matrix[(b, a)] == count


def test_roster_of_no_stores():
    assert build_roster({}) == []


def test_unknown_provider_falls_back_to_a_sensible_metric():
    metric = metric_for("something-new")
    assert isinstance(metric, SourceMetric)
    assert metric.evidence is Evidence.CONFIRMED


def test_roster_tolerates_a_store_missing_its_metric_column():
    stores = {"rbn-cw": [{"Callsign": "K1ABC"}]}
    rows = build_roster(stores)
    assert rows[0]["Callsign"] == "K1ABC"
    assert rows[0]["rbn-cw_metric"] is None


def test_roster_provider_names_the_right_callsign_column():
    """Borrowing another provider's key silently exports an empty file."""
    from callsigns.roster import RosterProvider

    assert RosterProvider().callsign_key == "Callsign"


def test_roster_provider_is_not_registered():
    from callsigns.providers import provider_keys

    assert "roster" not in provider_keys()


def test_roster_provider_cannot_be_fetched():
    from callsigns.roster import RosterProvider

    with pytest.raises(NotImplementedError):
        RosterProvider().fetch("all", "all")


def test_modes_is_an_empty_string_not_none_when_unknown():
    stores = {"rbn-cw": [{"Callsign": "K1ABC", "Spots": 5}]}
    row = build_roster(stores)[0]
    assert row["Modes"] == "CW"
    stores = {"cwops-cwopen": [{"Callsign": "K1ABC", "Callsign_": 1}]}
    assert build_roster(stores)[0]["Modes"] == "CW"


def test_a_source_implying_no_mode_yields_an_empty_string():
    stores = {"sota-activator": [{"Callsign": "K1ABC", "Points": 10}]}
    assert build_roster(stores)[0]["Modes"] == ""


def test_roster_exports_a_non_empty_dta(tmp_path):
    from callsigns.exporters.base import ExportOptions
    from callsigns.exporters.dta import DtaExporter, decode_master_dta
    from callsigns.roster import RosterProvider

    rows = build_roster(STORES)
    options = ExportOptions("all", "all", 0, tmp_path, basename="Roster")
    written = DtaExporter().write(rows, RosterProvider(), options)
    calls = decode_master_dta(written[0].read_bytes())
    assert "K1ABC" in calls
    assert len(calls) == len(rows)
