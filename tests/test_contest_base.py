import pathlib

import pytest

from callsigns.cache import FileCache
from callsigns.errors import ValidationError
from callsigns.providers.base import Column
from callsigns.providers.contest.base import (
    DEFAULT_TOP_LOGS,
    ContestLogProvider,
    LogRef,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
CQWW = (FIXTURES / "cabrillo_cqww.log").read_text()
SSCW = (FIXTURES / "cabrillo_sscw.log").read_text()


class FakeClient:
    def __init__(self, bodies):
        self.bodies = bodies
        self.urls = []

    def get_bytes(self, url, **kwargs):
        self.urls.append(url)
        return self.bodies[url].encode()


class Fake(ContestLogProvider):
    key = "fake-contest"
    label = "Fake Contest"
    store_name = "Fake.xlsx"
    export_prefix = "FAKE"
    calls_prefix = "FAKE"
    first_year = 2019

    def list_logs(self, period):
        return [
            LogRef(callsign="3B8M", url="https://x.test/3b8m.log", size=900),
            LogRef(callsign="AA0AW", url="https://x.test/aa0aw.log", size=100),
        ]


@pytest.fixture
def provider(tmp_path):
    client = FakeClient(
        {"https://x.test/3b8m.log": CQWW, "https://x.test/aa0aw.log": SSCW}
    )
    return Fake(cache=FileCache(tmp_path, client=client)), client


def test_identity_and_bulkness(provider):
    p, _ = provider
    assert p.bulk is True
    assert p.callsign_key == "Callsign"


def test_columns(provider):
    p, _ = provider
    assert [c.key for c in p.columns] == [
        "Callsign",
        "TimesWorked",
        "LogsSeen",
        "Bands",
        "FirstSeen",
        "LastSeen",
        "Entrant",
    ]


def test_mode_is_fixed_by_the_contest(provider):
    p, _ = provider
    assert set(p.modes) == {"all", "cw"}
    assert p.uses_fetch_modes() is False
    assert p.sheet_name("2025", "cw") == "2025"


def test_periods_run_from_first_year(provider):
    p, _ = provider
    periods = p.periods()
    assert "2019" in periods and "2018" not in periods
    assert "all" not in periods


def test_abstract_list_logs_is_enforced():
    class NoListing(ContestLogProvider):
        key = "no-listing"
        label = "x"
        store_name = "x.xlsx"
        export_prefix = "X"
        calls_prefix = "X"
        first_year = 2019

    with pytest.raises(TypeError):
        NoListing()  # type: ignore[abstract]


def test_counts_times_worked_across_logs(provider):
    p, _ = provider
    rows = {r["Callsign"]: r for r in p.fetch("2025", "all")}
    assert rows["YT6X"]["TimesWorked"] == 2
    assert rows["K7MOA"]["TimesWorked"] == 1


def test_counts_distinct_logs_a_callsign_appears_in(provider):
    p, _ = provider
    rows = {r["Callsign"]: r for r in p.fetch("2025", "all")}
    assert rows["YT6X"]["LogsSeen"] == 1


def test_counts_distinct_bands(provider):
    p, _ = provider
    rows = {r["Callsign"]: r for r in p.fetch("2025", "all")}
    assert rows["YT6X"]["Bands"] == 2


def test_first_and_last_seen(provider):
    p, _ = provider
    rows = {r["Callsign"]: r for r in p.fetch("2025", "all")}
    assert rows["YT6X"]["FirstSeen"] == "2025-11-29 0000"
    assert rows["YT6X"]["LastSeen"] == "2025-11-29 1200"


def test_entrant_flag_marks_callsigns_that_submitted(provider):
    p, _ = provider
    rows = {r["Callsign"]: r for r in p.fetch("2025", "all")}
    assert rows["YT6X"]["Entrant"] == "no"
    assert rows["AA0AW"]["Entrant"] == "yes"
    assert rows["AA0AW"]["TimesWorked"] == 0


def test_ranked_by_times_worked(provider):
    p, _ = provider
    rows = p.fetch("2025", "all")
    counts = [r["TimesWorked"] for r in rows]
    assert counts == sorted(counts, reverse=True)


def test_sweepstakes_exchange_parsed_correctly(provider):
    p, _ = provider
    calls = {r["Callsign"] for r in p.fetch("2025", "all")}
    assert "K7MOA" in calls
    assert "86" not in calls


def test_top_logs_limits_downloads(provider):
    p, client = provider
    p.top_logs = 1
    p.fetch("2025", "all")
    assert client.urls == ["https://x.test/3b8m.log"]


def test_top_logs_zero_means_everything(provider):
    p, client = provider
    p.top_logs = 0
    p.fetch("2025", "all")
    assert len(client.urls) == 2


def test_default_top_logs_is_bounded():
    assert DEFAULT_TOP_LOGS == 200


def test_second_fetch_uses_the_cache(provider):
    p, client = provider
    p.fetch("2025", "all")
    client.urls.clear()
    p.fetch("2025", "all")
    assert client.urls == []


def test_unknown_period_is_rejected(provider):
    p, _ = provider
    with pytest.raises(ValidationError, match="1999"):
        p.validate_period("1999")


def test_columns_are_declared_consistently(provider):
    p, _ = provider
    rows = p.fetch("2025", "all")
    assert set(rows[0]) == {c.key for c in p.columns}
    assert isinstance(p.columns[0], Column)
