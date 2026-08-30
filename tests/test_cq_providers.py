import pathlib

import pytest

from callsigns.cache import FileCache
from callsigns.errors import ValidationError
from callsigns.providers import get_provider
from callsigns.providers.contest.cq import (
    CqWpxCwProvider,
    CqWwCwProvider,
    parse_log_links,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "cq_listing.html").read_text()
CQWW_LOG = (FIXTURES / "cabrillo_cqww.log").read_text()


class FakeClient:
    def __init__(self):
        self.urls = []
        self.heads = []

    def get_text(self, url, **kwargs):
        self.urls.append(url)
        return LISTING

    def get_bytes(self, url, **kwargs):
        self.urls.append(url)
        return CQWW_LOG.encode()

    def content_length(self, url, **kwargs):
        self.heads.append(url)
        return {"3b8m.log": 900, "aa0aw.log": 100, "2e0cey.log": 50}[
            url.rsplit("/", 1)[-1]
        ]


@pytest.fixture
def provider(tmp_path):
    client = FakeClient()
    return (
        CqWwCwProvider(cache=FileCache(tmp_path, client=client), client=client),
        client,
    )


def test_parse_log_links_accepts_single_quotes():
    assert parse_log_links(LISTING) == ["3b8m.log", "aa0aw.log", "2e0cey.log"]


def test_parse_log_links_accepts_double_quotes():
    assert parse_log_links('<a href="k1abc.log">x</a>') == ["k1abc.log"]


def test_parse_log_links_ignores_other_files():
    assert parse_log_links("<a href='style.css'>x</a>") == []


def test_parse_log_links_deduplicates_preserving_order():
    html = "<a href='b.log'>b</a><a href='a.log'>a</a><a href='b.log'>b</a>"
    assert parse_log_links(html) == ["b.log", "a.log"]


def test_identity(provider):
    p, _ = provider
    assert p.key == "cqww-cw"
    assert p.store_name == "CQWW-CW.xlsx"
    assert p.bulk is True


def test_wpx_identity():
    p = CqWpxCwProvider()
    assert p.key == "cqwpx-cw"
    assert p.store_name == "CQWPX-CW.xlsx"
    assert "cqwpx.com" in p.listing_url("2026")


def test_listing_url(provider):
    p, _ = provider
    assert p.listing_url("2025") == "https://cqww.com/publiclogs/2025cw/"


def test_periods_start_at_first_year(provider):
    p, _ = provider
    assert "2019" in p.periods() and "2018" not in p.periods()


def test_rejects_a_year_before_publication(provider):
    p, _ = provider
    with pytest.raises(ValidationError, match="2018"):
        p.validate_period("2018")


def test_list_logs_uses_head_for_sizes(provider):
    p, client = provider
    refs = p.list_logs("2025")
    assert [r.callsign for r in refs] == ["3B8M", "AA0AW", "2E0CEY"]
    assert refs[0].size == 900
    assert len(client.heads) == 3


def test_list_logs_builds_absolute_urls(provider):
    p, _ = provider
    assert p.list_logs("2025")[0].url == "https://cqww.com/publiclogs/2025cw/3b8m.log"


def test_fetch_downloads_largest_first(provider):
    p, client = provider
    p.top_logs = 2
    p.fetch("2025", "all")
    downloaded = [u for u in client.urls if u.endswith(".log")]
    assert downloaded == [
        "https://cqww.com/publiclogs/2025cw/3b8m.log",
        "https://cqww.com/publiclogs/2025cw/aa0aw.log",
    ]


def test_fetch_aggregates(provider):
    p, _ = provider
    p.top_logs = 1
    rows = {r["Callsign"]: r for r in p.fetch("2025", "all")}
    assert rows["YT6X"]["TimesWorked"] == 2


def test_head_failure_leaves_size_unknown(tmp_path):
    class NoHead(FakeClient):
        def content_length(self, url, **kwargs):
            self.heads.append(url)
            return None

    client = NoHead()
    p = CqWwCwProvider(cache=FileCache(tmp_path, client=client), client=client)
    assert all(r.size is None for r in p.list_logs("2025"))


def test_source_url_is_the_listing(provider):
    p, _ = provider
    assert p.source_url("2025") == "https://cqww.com/publiclogs/2025cw/"


def test_both_registered():
    assert isinstance(get_provider("cqww-cw"), CqWwCwProvider)
    assert isinstance(get_provider("cqwpx-cw"), CqWpxCwProvider)


def test_size_probes_are_concurrent(tmp_path):
    """8,109 sequential HEADs would take over half an hour on a real field."""
    import threading

    class TrackingClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.max_concurrent = 0
            self._active = 0
            self._lock = threading.Lock()

        def content_length(self, url, **kwargs):
            with self._lock:
                self._active += 1
                self.max_concurrent = max(self.max_concurrent, self._active)
            try:
                import time

                time.sleep(0.02)
                return 100
            finally:
                with self._lock:
                    self._active -= 1

    client = TrackingClient()
    p = CqWwCwProvider(
        cache=FileCache(tmp_path, client=client), client=client, probe_jobs=3
    )
    p.list_logs("2025")
    assert client.max_concurrent > 1


def test_size_probes_respect_the_job_limit(tmp_path):
    import threading
    import time

    class TrackingClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.max_concurrent = 0
            self._active = 0
            self._lock = threading.Lock()

        def content_length(self, url, **kwargs):
            with self._lock:
                self._active += 1
                self.max_concurrent = max(self.max_concurrent, self._active)
            try:
                time.sleep(0.02)
                return 100
            finally:
                with self._lock:
                    self._active -= 1

    client = TrackingClient()
    p = CqWwCwProvider(
        cache=FileCache(tmp_path, client=client), client=client, probe_jobs=2
    )
    p.list_logs("2025")
    assert client.max_concurrent <= 2


def test_sizes_stay_aligned_with_their_callsigns(tmp_path):
    client = FakeClient()
    p = CqWwCwProvider(cache=FileCache(tmp_path, client=client), client=client)
    refs = {r.callsign: r.size for r in p.list_logs("2025")}
    assert refs == {"3B8M": 900, "AA0AW": 100, "2E0CEY": 50}


def test_list_entrants_makes_one_request_and_no_probes(tmp_path):
    client = FakeClient()
    p = CqWwCwProvider(cache=FileCache(tmp_path, client=client), client=client)
    refs = p.list_entrants("2025")
    assert [r.callsign for r in refs] == ["3B8M", "AA0AW", "2E0CEY"]
    assert all(r.size is None for r in refs)
    assert client.heads == []


def test_probe_sizes_fills_in_sizes(tmp_path):
    client = FakeClient()
    p = CqWwCwProvider(cache=FileCache(tmp_path, client=client), client=client)
    refs = p.probe_sizes(p.list_entrants("2025"))
    assert [r.size for r in refs] == [900, 100, 50]


def test_probe_sizes_of_nothing(tmp_path):
    client = FakeClient()
    p = CqWwCwProvider(cache=FileCache(tmp_path, client=client), client=client)
    assert p.probe_sizes([]) == []
