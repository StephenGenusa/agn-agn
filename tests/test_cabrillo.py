import pathlib

from callsigns.providers.contest.cabrillo import (
    band_for,
    parse_log,
    parse_qso_line,
    worked_index,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CQWW = (FIXTURES / "cabrillo_cqww.log").read_text()
SSCW = (FIXTURES / "cabrillo_sscw.log").read_text()


def test_worked_index_for_a_two_field_exchange():
    tokens = "QSO: 14012 CW 2026-02-21 0251 3B8HK 599 KW KH6TU 599 HI".split()
    assert worked_index(tokens) == 8
    assert tokens[worked_index(tokens)] == "KH6TU"


def test_worked_index_for_a_four_field_exchange():
    tokens = (
        "QSO: 28048 CW 2025-11-01 2100 AA0AW 0001 U 86 MN K7MOA 0001 A 60 STX".split()
    )
    assert worked_index(tokens) == 10
    assert tokens[worked_index(tokens)] == "K7MOA"


def test_worked_index_survives_the_cq_trailing_transmitter_field():
    tokens = "QSO: 3549 CW 2025-11-29 0000 3B8M 599 39 YT6X 599 15 0".split()
    assert worked_index(tokens) == 8
    assert tokens[worked_index(tokens)] == "YT6X"


def test_band_mapping():
    assert band_for("3549") == "80m"
    assert band_for("7030") == "40m"
    assert band_for("14025") == "20m"
    assert band_for("21005") == "15m"
    assert band_for("28048") == "10m"
    assert band_for("1816") == "160m"


def test_band_mapping_accepts_fractional_frequencies():
    assert band_for("7037.2") == "40m"


def test_band_mapping_handles_unknown_and_junk():
    assert band_for("99999") == ""
    assert band_for("not-a-number") == ""


def test_parse_qso_line_extracts_callsign_band_and_time():
    qso = parse_qso_line("QSO: 14025 CW 2025-11-29 1200 3B8M 599 39 YT6X 599 15 0")
    assert qso is not None
    assert qso.callsign == "YT6X"
    assert qso.band == "20m"
    assert qso.when == "2025-11-29 1200"


def test_parse_qso_line_uppercases():
    qso = parse_qso_line("QSO: 14025 CW 2025-11-29 1200 3b8m 599 39 yt6x 599 15 0")
    assert qso is not None and qso.callsign == "YT6X"


def test_parse_qso_line_rejects_non_qso_lines():
    assert parse_qso_line("CALLSIGN: 3B8M") is None
    assert parse_qso_line("") is None


def test_parse_qso_line_rejects_x_qso_lines():
    """X-QSO marks a QSO the entrant excluded; it is not a contact."""
    assert (
        parse_qso_line("X-QSO: 7005 CW 2025-11-29 1400 3B8M 599 39 IGNORED 599 15 0")
        is None
    )


def test_parse_qso_line_rejects_short_lines():
    assert parse_qso_line("QSO: garbage") is None


def test_parse_log_returns_the_entrant_callsign():
    entrant, _ = parse_log(CQWW)
    assert entrant == "3B8M"


def test_parse_log_skips_malformed_lines_without_losing_the_log():
    _, qsos = parse_log(CQWW)
    assert len(qsos) == 5


def test_parse_log_keeps_duplicates_so_they_can_be_counted():
    _, qsos = parse_log(CQWW)
    assert [q.callsign for q in qsos].count("YT6X") == 2


def test_parse_log_handles_the_sweepstakes_exchange():
    entrant, qsos = parse_log(SSCW)
    assert entrant == "AA0AW"
    assert [q.callsign for q in qsos] == ["K7MOA", "K7JQ", "W1AW"]


def test_parse_log_never_returns_the_sweepstakes_check_field():
    _, qsos = parse_log(SSCW)
    assert "86" not in [q.callsign for q in qsos]


def test_parse_log_of_an_empty_string():
    entrant, qsos = parse_log("")
    assert entrant == "" and qsos == []


def test_parse_log_without_a_callsign_header():
    entrant, qsos = parse_log("QSO: 14025 CW 2025-11-29 1200 A 599 39 B4XY 599 15")
    assert entrant == ""
    assert len(qsos) == 1
