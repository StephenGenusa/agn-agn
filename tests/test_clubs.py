import pathlib

import pytest

import callsigns.cli  # noqa: F401 - registers providers
from callsigns.errors import ValidationError
from callsigns.pacing import SLOW_POLICY, RateLimiter
from callsigns.providers import get_provider
from callsigns.providers.clubs.cwops import CwOpenProvider, parse_entrant_list
from callsigns.providers.clubs.naqcc import NaqccSprintProvider, parse_scoreboard
from callsigns.providers.clubs.skcc import (
    SkccWesProvider,
    parse_results_index,
    parse_wes_results,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
NAQCC = (FIXTURES / "naqcc_scoreboard.html").read_text()
SKCC_WES = (FIXTURES / "skcc_wes.html").read_text()
SKCC_INDEX = (FIXTURES / "skcc_index.html").read_text()
CWOPS = (FIXTURES / "cwops_logsrcvd.html").read_text()


class FakeClient:
    def __init__(self, body):
        self.body = body
        self.urls = []

    def get_text(self, url, **kwargs):
        self.urls.append(url)
        return self.body

    def get_bytes(self, url, **kwargs):
        self.urls.append(url)
        return self.body.encode()


# --------------------------------------------------------------- NAQCC


def test_naqcc_parses_every_entrant():
    """Rows come back ranked by score, not in page order."""
    rows = parse_scoreboard(NAQCC)
    assert {r["Callsign"] for r in rows} == {"NX1K", "KN1H", "KB2GKC", "K6XYZ"}
    assert [r["Callsign"] for r in rows] == ["NX1K", "KB2GKC", "KN1H", "K6XYZ"]


def test_naqcc_parses_counts_and_score():
    rows = {r["Callsign"]: r for r in parse_scoreboard(NAQCC)}
    assert rows["NX1K"]["QSOs"] == 34
    assert rows["NX1K"]["Members"] == 34
    assert rows["NX1K"]["Score"] == 2448


def test_naqcc_carries_category_and_division():
    rows = {r["Callsign"]: r for r in parse_scoreboard(NAQCC)}
    assert rows["NX1K"]["Category"] == "SWA - STRAIGHT KEY CATEGORY"
    assert rows["K6XYZ"]["Category"] == "GAIN ANTENNA CATEGORY"
    assert rows["NX1K"]["Division"] == "W1 Division"
    assert rows["KB2GKC"]["Division"] == "W2 Division"


def test_naqcc_skips_the_column_header():
    assert all(r["Callsign"] != "Call" for r in parse_scoreboard(NAQCC))


def test_naqcc_ranks_by_score():
    scores = [r["Score"] for r in parse_scoreboard(NAQCC)]
    assert scores == sorted(scores, reverse=True)


def test_naqcc_empty_markup():
    assert parse_scoreboard("<html><body>nothing</body></html>") == []


def test_naqcc_period_validation():
    provider = NaqccSprintProvider(client=FakeClient(NAQCC))
    assert provider.validate_period("202511") == "202511"
    for bad in ("2025", "20251", "202513", "202500", "nonsense"):
        with pytest.raises(ValidationError):
            provider.validate_period(bad)


def test_naqcc_url_and_fetch():
    client = FakeClient(NAQCC)
    rows = NaqccSprintProvider(client=client).fetch("202511", "all")
    assert client.urls == ["http://naqcc.info/scoreboard.php?sprint_name=202511"]
    assert rows[0]["Callsign"] == "NX1K"


def test_naqcc_registered():
    assert isinstance(get_provider("naqcc-sprint"), NaqccSprintProvider)


# ---------------------------------------------------------------- SKCC


def test_skcc_parses_the_results_table():
    rows = parse_wes_results(SKCC_WES)
    assert [r["Callsign"] for r in rows] == ["W7GVE", "W9DLN", "AF4K"]


def test_skcc_uppercases_callsigns():
    assert parse_wes_results(SKCC_WES)[2]["Callsign"] == "AF4K"


def test_skcc_parses_numbers_with_thousands_separators():
    rows = {r["Callsign"]: r for r in parse_wes_results(SKCC_WES)}
    assert rows["W7GVE"]["Score"] == 10095
    assert rows["W7GVE"]["QSOs"] == 150


def test_skcc_keeps_member_metadata():
    rows = {r["Callsign"]: r for r in parse_wes_results(SKCC_WES)}
    assert rows["W7GVE"]["SkccNumber"] == "729T"
    assert rows["W7GVE"]["Spc"] == "AZ"
    assert rows["W7GVE"]["Name"] == "ED"


def test_skcc_captures_the_event_date():
    rows = parse_wes_results(SKCC_WES)
    assert all(r["WesDate"] == "10-11 Oct 2015" for r in rows)


def test_skcc_skips_the_header_row():
    assert all(r["Callsign"] != "Callsign" for r in parse_wes_results(SKCC_WES))


def test_skcc_index_lists_result_ids():
    assert parse_results_index(SKCC_INDEX) == ["105", "106"]


def test_skcc_period_validation():
    provider = SkccWesProvider(client=FakeClient(SKCC_WES))
    assert provider.validate_period("105") == "105"
    for bad in ("", "abc", "-1"):
        with pytest.raises(ValidationError):
            provider.validate_period(bad)


def test_skcc_url_and_fetch():
    client = FakeClient(SKCC_WES)
    rows = SkccWesProvider(client=client).fetch("105", "all")
    assert client.urls[0].endswith("submit-display.php?results_id=105")
    assert rows[0]["Callsign"] == "W7GVE"


def test_skcc_is_paced_slowly_by_default():
    """SKCC names ham-radio crawlers in its robots block list."""
    limiter = RateLimiter(clock=lambda: 0.0, sleeper=lambda s: None)
    assert limiter.policy_for("www.skccgroup.com") is SLOW_POLICY


def test_skcc_registered():
    assert isinstance(get_provider("skcc-wes"), SkccWesProvider)


# --------------------------------------------------------------- CWops


def test_cwops_parses_entrants():
    assert parse_entrant_list(CWOPS) == ["K1ABC", "W1AW", "G3XYZ", "JA1ABC"]


def test_cwops_deduplicates_and_uppercases():
    entrants = parse_entrant_list(CWOPS)
    assert entrants.count("K1ABC") == 1
    assert "ja1abc" not in entrants


def test_cwops_rows_carry_entrant_marker():
    rows = CwOpenProvider(client=FakeClient(CWOPS)).fetch("2025", "all")
    assert all(r["Entrant"] == "yes" for r in rows)


def test_cwops_url():
    client = FakeClient(CWOPS)
    CwOpenProvider(client=client).fetch("2025", "all")
    assert "cwopenlogsrcvd" in client.urls[0]


def test_cwops_registered():
    assert isinstance(get_provider("cwops-cwopen"), CwOpenProvider)


def test_all_three_clubs_declare_a_callsign_column():
    for key in ("naqcc-sprint", "skcc-wes", "cwops-cwopen"):
        provider = get_provider(key)
        assert provider.callsign_key == "Callsign"
        assert any(c.key == "Callsign" for c in provider.columns)


def test_cwops_resolves_html_entities_and_nbsp():
    from callsigns.providers.clubs.cwops import normalise_callsign

    assert normalise_callsign("K1DJ&nbsp; ") == "K1DJ"


def test_cwops_converts_the_slashed_zero_cw_ops_use():
    """K&#216;TG is KOTG with a slashed O, meaning K0TG."""
    from callsigns.providers.clubs.cwops import normalise_callsign

    assert normalise_callsign("K&#216;TG&nbsp; ") == "K0TG"
    assert normalise_callsign("k&#248;vw") == "K0VW"


def test_cwops_parses_slashed_zero_callsigns_end_to_end():
    markup = "<tr><td>K&#216;TG&nbsp; </td><td>0000Z-0359Z</td></tr>"
    assert parse_entrant_list(markup) == ["K0TG"]


# --------------------------------------------------------------- FISTS

FISTS_SPRINT = (FIXTURES / "fists_sprint.html").read_text()
FISTS_ARCHIVE = (FIXTURES / "fists_archive.html").read_text()


def test_fists_parses_every_entrant():
    from callsigns.providers.clubs.fists import parse_sprint

    rows = parse_sprint(FISTS_SPRINT)
    assert {r["Callsign"] for r in rows} == {
        "WB9HFK",
        "WB0CJB",
        "N5TML",
        "K6DF",
        "K1ABC",
    }


def test_fists_ranks_by_score():
    from callsigns.providers.clubs.fists import parse_sprint

    scores = [r["Score"] for r in parse_sprint(FISTS_SPRINT)]
    assert scores == sorted(scores, reverse=True)


def test_fists_sums_member_and_non_member_qsos():
    from callsigns.providers.clubs.fists import parse_sprint

    rows = {r["Callsign"]: r for r in parse_sprint(FISTS_SPRINT)}
    assert rows["WB9HFK"]["MemberQsos"] == 16
    assert rows["WB9HFK"]["NonMemberQsos"] == 19
    assert rows["WB9HFK"]["QSOs"] == 35


def test_fists_reads_points_and_score():
    from callsigns.providers.clubs.fists import parse_sprint

    rows = {r["Callsign"]: r for r in parse_sprint(FISTS_SPRINT)}
    assert rows["WB9HFK"]["Points"] == 118
    assert rows["WB9HFK"]["Score"] == 2846


def test_fists_handles_a_category_with_fewer_columns():
    """The QRP table has no Bonus column; Score is still the last field."""
    from callsigns.providers.clubs.fists import parse_sprint

    rows = {r["Callsign"]: r for r in parse_sprint(FISTS_SPRINT)}
    assert rows["K1ABC"]["Score"] == 76
    assert rows["K1ABC"]["Category"] == "QRP Category"


def test_fists_handles_space_separated_and_tab_separated_rows():
    from callsigns.providers.clubs.fists import parse_sprint

    rows = {r["Callsign"]: r for r in parse_sprint(FISTS_SPRINT)}
    assert rows["N5TML"]["QSOs"] == 5  # space separated
    assert rows["K6DF"]["QSOs"] == 6  # tab separated


def test_fists_handles_a_name_containing_a_space():
    from callsigns.providers.clubs.fists import parse_sprint

    rows = {r["Callsign"]: r for r in parse_sprint(FISTS_SPRINT)}
    assert rows["K1ABC"]["Name"] == "Mary Jo"
    assert rows["K1ABC"]["State"] == "MA"


def test_fists_uppercases_callsigns():
    from callsigns.providers.clubs.fists import parse_sprint

    assert "K1ABC" in {r["Callsign"] for r in parse_sprint(FISTS_SPRINT)}


def test_fists_carries_category_and_date():
    from callsigns.providers.clubs.fists import parse_sprint

    rows = {r["Callsign"]: r for r in parse_sprint(FISTS_SPRINT)}
    assert rows["WB9HFK"]["Category"] == "QRO Category"
    assert rows["WB9HFK"]["SprintDate"] == "Feb 08, 2025"


def test_fists_skips_headers_rules_and_no_logs_received():
    from callsigns.providers.clubs.fists import parse_sprint

    calls = {r["Callsign"] for r in parse_sprint(FISTS_SPRINT)}
    assert "CALL" not in calls
    assert not any("LOGS" in c for c in calls)


def test_fists_empty_markup():
    from callsigns.providers.clubs.fists import parse_sprint

    assert parse_sprint("<html>nothing</html>") == []


def test_fists_archive_lists_sprint_tokens():
    from callsigns.providers.clubs.fists import parse_archive

    assert parse_archive(FISTS_ARCHIVE) == [
        "febsat25",
        "febsun25",
        "maysat25",
        "maysun25",
        "febsat24",
        "febsun24",
    ]


def test_fists_period_validation():
    from callsigns.providers.clubs.fists import FistsSprintProvider

    provider = FistsSprintProvider(client=FakeClient(FISTS_SPRINT))
    assert provider.validate_period("FEBSAT25") == "febsat25"
    for bad in ("feb25", "janSat25", "febsat2025", "nonsense"):
        with pytest.raises(ValidationError):
            provider.validate_period(bad)


def test_fists_url_and_fetch():
    from callsigns.providers.clubs.fists import FistsSprintProvider

    client = FakeClient(FISTS_SPRINT)
    rows = FistsSprintProvider(client=client).fetch("febsat25", "all")
    assert client.urls == ["https://fistsna.org/spdata/febsat25.html"]
    assert rows[0]["Callsign"] == "WB9HFK"


def test_fists_registered():
    from callsigns.providers.clubs.fists import FistsSprintProvider

    assert isinstance(get_provider("fists-sprint"), FistsSprintProvider)


def test_naqcc_index_lists_available_sprints():
    from callsigns.providers.clubs.naqcc import parse_sprint_index

    markup = (
        '<a href="http://naqcc.info/scoreboard.php?sprint_name=202607">Jul</a>'
        '<a href="http://naqcc.info/scoreboard.php?sprint_name=202606">Jun</a>'
        '<a href="http://naqcc.info/scoreboard.php?sprint_name=202607">dup</a>'
    )
    assert parse_sprint_index(markup) == ["202607", "202606"]


def test_naqcc_index_of_empty_markup():
    from callsigns.providers.clubs.naqcc import parse_sprint_index

    assert parse_sprint_index("<html></html>") == []


def test_naqcc_available_periods_uses_the_index():
    from callsigns.providers.clubs.naqcc import INDEX_URL, NaqccSprintProvider

    markup = '<a href="scoreboard.php?sprint_name=202501">Jan</a>'
    client = FakeClient(markup)
    assert NaqccSprintProvider(client=client).available_periods() == ["202501"]
    assert client.urls == [INDEX_URL]
