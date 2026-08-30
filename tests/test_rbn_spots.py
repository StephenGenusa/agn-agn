import pathlib
import zipfile

import pytest

from callsigns.errors import UpstreamError
from callsigns.providers.rbn_spots import (
    CallsignStats,
    accumulate_spots,
    aggregate_spots,
    read_zip_member,
    rows_from,
)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "rbn_sample.csv"


def lines():
    return FIXTURE.read_text().splitlines()


def rows_by_call(tx_mode="CW"):
    rows, report = aggregate_spots(lines(), tx_mode)
    return {r["Callsign"]: r for r in rows}, report


def test_ranks_by_spot_count_descending():
    rows, _ = aggregate_spots(lines(), "CW")
    counts = [r["Spots"] for r in rows]
    assert counts == sorted(counts, reverse=True)
    assert rows[0]["Callsign"] == "S59L"


def test_counts_spots_per_callsign():
    rows, _ = rows_by_call()
    assert rows["S59L"]["Spots"] == 4
    assert rows["M6T"]["Spots"] == 2


def test_counts_distinct_skimmers_not_spots():
    rows, _ = rows_by_call()
    assert rows["S59L"]["Skimmers"] == 2


def test_counts_distinct_bands():
    rows, _ = rows_by_call()
    assert rows["S59L"]["Bands"] == 3


def test_speed_statistics():
    rows, _ = rows_by_call()
    assert rows["S59L"]["SpeedMin"] == 30
    assert rows["S59L"]["SpeedMax"] == 38
    assert rows["S59L"]["SpeedMedian"] == 33


def test_first_and_last_seen():
    rows, _ = rows_by_call()
    assert rows["S59L"]["FirstSeen"] == "2025-11-29 00:00:00"
    assert rows["S59L"]["LastSeen"] == "2025-11-29 05:00:00"


def test_keeps_continent_and_prefix():
    rows, _ = rows_by_call()
    assert rows["S59L"]["Continent"] == "EU"
    assert rows["S59L"]["Prefix"] == "S5"


def test_max_signal_strength():
    rows, _ = rows_by_call()
    assert rows["S59L"]["DbMax"] == 20


def test_uppercases_callsigns_and_merges_them():
    rows, _ = rows_by_call()
    assert "m6t" not in rows
    assert rows["M6T"]["Spots"] == 2


def test_excludes_beacons():
    rows, _ = rows_by_call()
    assert "W6WX/B" not in rows
    assert "4U1UN/B" not in rows


def test_excludes_other_modulations():
    rows, _ = rows_by_call()
    assert "K5ZZZ" not in rows


def test_rtty_mode_selects_only_rtty():
    rows, _ = aggregate_spots(lines(), "RTTY")
    assert [r["Callsign"] for r in rows] == ["K5ZZZ"]


def test_no_mode_filter_keeps_every_modulation():
    rows, _ = aggregate_spots(lines(), None)
    calls = {r["Callsign"] for r in rows}
    assert "K5ZZZ" in calls and "S59L" in calls


def test_ragged_rows_are_skipped_and_counted():
    _, report = aggregate_spots(lines(), "CW")
    assert report.ragged == 1


def test_report_totals():
    _, report = aggregate_spots(lines(), "CW")
    assert report.rows == 11
    assert report.kept == 7
    assert report.wrong_mode == 1


def test_report_summary_mentions_totals():
    _, report = aggregate_spots(lines(), "CW")
    text = report.summary()
    assert "11 rows" in text and "7 kept" in text


def test_missing_header_is_an_upstream_error():
    with pytest.raises(UpstreamError, match="header"):
        aggregate_spots(["not,a,valid,header"], "CW")


def test_empty_input_is_an_upstream_error():
    with pytest.raises(UpstreamError, match="header"):
        aggregate_spots([], "CW")


def test_accumulate_folds_two_passes_into_one_accumulator():
    stats: dict[str, CallsignStats] = {}
    accumulate_spots(lines(), "CW", stats)
    accumulate_spots(lines(), "CW", stats)
    rows = {r["Callsign"]: r for r in rows_from(stats)}
    assert rows["S59L"]["Spots"] == 8
    assert rows["S59L"]["Skimmers"] == 2
    assert rows["S59L"]["Bands"] == 3


def test_rows_from_ranks_by_spots():
    stats = {
        "A": CallsignStats(callsign="A", spots=1),
        "B": CallsignStats(callsign="B", spots=9),
    }
    assert [r["Callsign"] for r in rows_from(stats)] == ["B", "A"]


def test_rows_from_handles_a_callsign_with_no_speeds():
    stats = {"A": CallsignStats(callsign="A", spots=1)}
    row = rows_from(stats)[0]
    assert row["SpeedMin"] == 0 and row["SpeedMedian"] == 0 and row["SpeedMax"] == 0


def test_read_zip_member_streams_the_single_csv(tmp_path):
    archive = tmp_path / "20251129.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("20251129.csv", FIXTURE.read_text())
    assert next(iter(read_zip_member(archive))).startswith("callsign,")


def test_read_zip_member_rejects_an_empty_archive(tmp_path):
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w"):
        pass
    with pytest.raises(UpstreamError, match="no files"):
        list(read_zip_member(archive))


def test_read_zip_member_rejects_a_non_zip(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_text("this is not a zip")
    with pytest.raises(UpstreamError, match="not a valid zip"):
        list(read_zip_member(bad))
