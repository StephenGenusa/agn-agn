import pytest

from callsigns.errors import UpstreamError
from callsigns.providers.base import Column
from callsigns.providers.sota_rows import coerce_row, coerce_rows, is_placeholder

COLUMNS = (
    Column("Callsign", "Callsign", str),
    Column("Position", "Position", str),
    Column("Points", "Points", int),
    Column("Average", "Average", float),
)
URL = "https://x.test/rolls"


def test_placeholder_detection():
    assert is_placeholder("anon22082801") is True
    assert is_placeholder("ANON22082801") is True
    assert is_placeholder("G4YSS") is False
    assert is_placeholder("ANON") is False
    assert is_placeholder("2E0XIS") is False


def test_placeholder_detection_ignores_surrounding_space():
    assert is_placeholder(" anon22082801 ") is True


def test_coerce_leaves_strings_alone():
    row = coerce_row(
        {"Callsign": "G4YSS", "Position": "1", "Points": 10, "Average": "6.98"},
        COLUMNS,
        URL,
    )
    assert row["Callsign"] == "G4YSS"
    assert row["Position"] == "1"


def test_coerce_converts_average_to_float():
    row = coerce_row(
        {"Callsign": "G4YSS", "Position": "1", "Points": 10, "Average": "6.98"},
        COLUMNS,
        URL,
    )
    assert row["Average"] == pytest.approx(6.98)
    assert isinstance(row["Average"], float)


def test_coerce_accepts_numeric_strings_for_ints():
    row = coerce_row(
        {"Callsign": "G", "Position": "1", "Points": "10", "Average": "1.0"},
        COLUMNS,
        URL,
    )
    assert row["Points"] == 10


def test_coerce_keeps_only_declared_columns():
    row = coerce_row(
        {
            "Callsign": "G4YSS",
            "Position": "1",
            "Points": 10,
            "Average": "6.98",
            "UserID": 77,
        },
        COLUMNS,
        URL,
    )
    assert set(row) == {"Callsign", "Position", "Points", "Average"}


def test_missing_column_is_an_upstream_error_naming_it():
    with pytest.raises(UpstreamError, match="Average"):
        coerce_row({"Callsign": "G", "Position": "1", "Points": 1}, COLUMNS, URL)


def test_uncoercible_value_is_an_upstream_error_naming_column_and_value():
    with pytest.raises(UpstreamError, match="Points"):
        coerce_row(
            {"Callsign": "G", "Position": "1", "Points": "many", "Average": "1.0"},
            COLUMNS,
            URL,
        )


def test_error_names_the_url():
    with pytest.raises(UpstreamError, match=r"x\.test"):
        coerce_row({"Callsign": "G"}, COLUMNS, URL)


def test_coerce_rows_drops_placeholders_and_counts_them():
    payload = [
        {"Callsign": "G4YSS", "Position": "1", "Points": 10, "Average": "6.98"},
        {"Callsign": "anon22082801", "Position": "2", "Points": 5, "Average": "1.0"},
    ]
    rows, dropped = coerce_rows(payload, COLUMNS, "Callsign", URL)
    assert [r["Callsign"] for r in rows] == ["G4YSS"]
    assert dropped == 1


def test_coerce_rows_preserves_upstream_order():
    payload = [
        {"Callsign": "B", "Position": "1", "Points": 9, "Average": "1.0"},
        {"Callsign": "A", "Position": "2", "Points": 1, "Average": "1.0"},
    ]
    rows, _ = coerce_rows(payload, COLUMNS, "Callsign", URL)
    assert [r["Callsign"] for r in rows] == ["B", "A"]


def test_coerce_rows_rejects_a_non_list_payload():
    with pytest.raises(UpstreamError, match="list"):
        coerce_rows({"message": "Invalid date"}, COLUMNS, "Callsign", URL)


def test_coerce_rows_rejects_a_non_object_row():
    with pytest.raises(UpstreamError, match="non-object"):
        coerce_rows(["nope"], COLUMNS, "Callsign", URL)


def test_coerce_rows_accepts_an_empty_list():
    rows, dropped = coerce_rows([], COLUMNS, "Callsign", URL)
    assert rows == [] and dropped == 0
