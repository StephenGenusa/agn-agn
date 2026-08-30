from callsigns.providers.base import ModeSpec
from callsigns.select import clean_callsigns, filter_rows, limit_rows

ROWS = [
    {"activeCallsign": "A", "qsosCW": 5, "qsosPHONE": 0},
    {"activeCallsign": "B", "qsosCW": 0, "qsosPHONE": 7},
    {"activeCallsign": "C", "qsosCW": 3, "qsosPHONE": 2},
]


def test_all_mode_keeps_everything():
    assert filter_rows(ROWS, ModeSpec.all_modes()) == list(ROWS)


def test_filter_mode_keeps_positive_rows_only():
    kept = filter_rows(ROWS, ModeSpec.filter_on("qsosCW"))
    assert [r["activeCallsign"] for r in kept] == ["A", "C"]


def test_filter_mode_preserves_order():
    kept = filter_rows(ROWS, ModeSpec.filter_on("qsosPHONE"))
    assert [r["activeCallsign"] for r in kept] == ["B", "C"]


def test_filter_mode_treats_missing_or_non_numeric_as_zero():
    rows = [{"activeCallsign": "X"}, {"activeCallsign": "Y", "qsosCW": "n/a"}]
    assert filter_rows(rows, ModeSpec.filter_on("qsosCW")) == []


def test_filter_mode_ignores_booleans():
    rows = [{"activeCallsign": "X", "qsosCW": True}]
    assert filter_rows(rows, ModeSpec.filter_on("qsosCW")) == []


def test_fetch_mode_does_not_filter():
    assert filter_rows(ROWS, ModeSpec.fetch_as("CW")) == list(ROWS)


def test_filter_returns_copies_not_aliases():
    kept = filter_rows(ROWS, ModeSpec.all_modes())
    kept[0]["activeCallsign"] = "MUTATED"
    assert ROWS[0]["activeCallsign"] == "A"


def test_limit_truncates():
    assert len(limit_rows(ROWS, 2)) == 2


def test_limit_zero_or_negative_means_no_limit():
    assert len(limit_rows(ROWS, 0)) == 3
    assert len(limit_rows(ROWS, -1)) == 3


def test_limit_larger_than_input_returns_everything():
    assert len(limit_rows(ROWS, 99)) == 3


def test_clean_uppercases():
    calls, report = clean_callsigns(["k5hip", "w9com"])
    assert calls == ["K5HIP", "W9COM"]
    assert report.kept == 2
    assert report.dropped == 0


def test_clean_keeps_slashes():
    calls, _ = clean_callsigns(["LA/G4YBU/P", "WB0KFC/VE3"])
    assert calls == ["LA/G4YBU/P", "WB0KFC/VE3"]


def test_clean_drops_invalid_characters():
    calls, report = clean_callsigns(["K1ABC", "BAD-CALL", "SPA CE", "K2X.Y"])
    assert calls == ["K1ABC"]
    assert report.invalid_chars == 3


def test_clean_drops_calls_shorter_than_two_characters():
    calls, report = clean_callsigns(["K1ABC", "X", ""])
    assert calls == ["K1ABC"]
    assert report.too_short == 2


def test_clean_deduplicates_preserving_first_occurrence():
    calls, report = clean_callsigns(["K1ABC", "W1AW", "k1abc"])
    assert calls == ["K1ABC", "W1AW"]
    assert report.duplicates == 1


def test_clean_ignores_none_values():
    calls, report = clean_callsigns(["K1ABC", None])
    assert calls == ["K1ABC"]
    assert report.too_short == 1


def test_clean_strips_whitespace():
    calls, _ = clean_callsigns(["  K1ABC  "])
    assert calls == ["K1ABC"]


def test_summary_mentions_each_drop_reason():
    _, report = clean_callsigns(["K1ABC", "BAD-CALL", "X", "k1abc"])
    text = report.summary()
    assert "1 invalid" in text and "1 too short" in text and "1 duplicate" in text


def test_summary_is_empty_when_nothing_dropped():
    _, report = clean_callsigns(["K1ABC"])
    assert report.summary() == ""
