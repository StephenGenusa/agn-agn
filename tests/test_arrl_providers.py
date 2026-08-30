import pathlib

import pytest

from callsigns.cache import FileCache
from callsigns.errors import UpstreamError
from callsigns.providers import get_provider
from callsigns.providers.contest.arrl import (
    ArrlDxCwProvider,
    ArrlSsCwProvider,
    parse_entrants,
    parse_year_map,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
YEARS = (FIXTURES / "arrl_years.html").read_text()
LISTING = (FIXTURES / "arrl_listing.html").read_text()
CQWW_LOG = (FIXTURES / "cabrillo_cqww.log").read_text()
SSCW_LOG = (FIXTURES / "cabrillo_sscw.log").read_text()


class FakeClient:
    def __init__(self, log_body=CQWW_LOG):
        self.urls = []
        self.log_body = log_body

    def get_text(self, url, **kwargs):
        self.urls.append(url)
        if "cn=" in url and "iid=" not in url:
            return YEARS
        return LISTING

    def get_bytes(self, url, **kwargs):
        self.urls.append(url)
        return self.log_body.encode()

    def content_length(self, url, **kwargs):
        return None


@pytest.fixture
def provider(tmp_path):
    client = FakeClient()
    return (
        ArrlDxCwProvider(cache=FileCache(tmp_path, client=client), client=client),
        client,
    )


def test_parse_year_map():
    assert parse_year_map(YEARS) == {
        "2026": ("13", "1113"),
        "2025": ("13", "1096"),
        "2024": ("13", "1059"),
    }


def test_parse_year_map_handles_escaped_ampersands():
    html = '<a href="publiclogs.php?eid=13&amp;iid=999">2027</a>'
    assert parse_year_map(html) == {"2027": ("13", "999")}


def test_parse_year_map_of_empty_markup():
    assert parse_year_map("<html></html>") == {}


def test_parse_entrants():
    assert parse_entrants(LISTING) == ["3B8HK", "AA0AW", "K1ABC"]


def test_parse_entrants_deduplicates():
    assert parse_entrants(LISTING + LISTING) == ["3B8HK", "AA0AW", "K1ABC"]


def test_identity(provider):
    p, _ = provider
    assert p.key == "arrl-dxcw"
    assert p.store_name == "ARRL-DXCW.xlsx"
    assert p.contest == "dxcw"
    assert p.bulk is True


def test_each_contest_has_its_own_store():
    assert ArrlSsCwProvider().store_name == "ARRL-SSCW.xlsx"
    assert ArrlSsCwProvider().contest == "sscw"


def test_discovery_then_listing(provider):
    p, client = provider
    refs = p.list_logs("2026")
    assert client.urls[0] == "https://contests.arrl.org/publiclogs.php?cn=dxcw"
    assert client.urls[1] == "https://contests.arrl.org/publiclogs.php?eid=13&iid=1113"
    assert [r.callsign for r in refs] == ["3B8HK", "AA0AW", "K1ABC"]


def test_log_urls(provider):
    p, _ = provider
    assert p.list_logs("2026")[0].url == (
        "https://contests.arrl.org/showpubliclog.php?cn=dxcw&yr=2026&call=3B8HK"
    )


def test_sizes_are_unknown_because_head_reports_none(provider):
    p, _ = provider
    assert all(r.size is None for r in p.list_logs("2026"))


def test_a_year_with_no_published_logs_is_an_upstream_error(provider):
    p, _ = provider
    with pytest.raises(UpstreamError, match="2020"):
        p.list_logs("2020")


def test_error_lists_the_years_that_are_available(provider):
    p, _ = provider
    with pytest.raises(UpstreamError, match="2026"):
        p.list_logs("2020")


def test_fetch_aggregates_in_listing_order(provider):
    p, client = provider
    p.top_logs = 2
    p.fetch("2026", "all")
    logs = [u for u in client.urls if "showpubliclog" in u]
    assert [u.rsplit("=", 1)[-1] for u in logs] == ["3B8HK", "AA0AW"]


def test_sweepstakes_log_parses_with_its_wider_exchange(tmp_path):
    client = FakeClient(log_body=SSCW_LOG)
    p = ArrlSsCwProvider(cache=FileCache(tmp_path, client=client), client=client)
    p.top_logs = 1
    calls = {r["Callsign"] for r in p.fetch("2026", "all")}
    assert "K7MOA" in calls
    assert "86" not in calls


def test_all_five_registered():
    for key in ("arrl-dxcw", "arrl-sscw", "arrl-10m", "arrl-160m", "arrl-iaruhf"):
        assert get_provider(key).key == key


def test_compound_callsigns_keep_their_hyphen_in_the_url():
    """ARRL spells 6Y/AI5IN as 6Y-AI5IN in the query string."""
    markup = '<a href="showpubliclog.php?cn=dxcw&yr=2025&call=6Y-AI5IN">6Y/AI5IN</a>'
    assert parse_entrants(markup) == ["6Y-AI5IN"]


def test_compound_callsigns_are_stored_with_a_slash(tmp_path):
    from callsigns.providers.contest.arrl import display_callsign

    assert display_callsign("6Y-AI5IN") == "6Y/AI5IN"
    assert display_callsign("K1ABC") == "K1ABC"


def test_list_logs_uses_the_hyphen_url_and_the_slash_name(tmp_path):
    class Compound(FakeClient):
        def get_text(self, url, **kwargs):
            self.urls.append(url)
            if "cn=" in url and "iid=" not in url:
                return YEARS
            return '<a href="showpubliclog.php?cn=dxcw&yr=2026&call=6Y-AI5IN">x</a>'

    client = Compound()
    p = ArrlDxCwProvider(cache=FileCache(tmp_path, client=client), client=client)
    ref = p.list_logs("2026")[0]
    assert ref.callsign == "6Y/AI5IN"
    assert ref.url.endswith("call=6Y-AI5IN")
