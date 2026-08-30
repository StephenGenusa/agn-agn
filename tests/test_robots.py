import logging

from callsigns.robots import RobotsCache

DISALLOW_LOGS = """
User-agent: *
Disallow: /publiclogs/
"""

DISALLOW_QUERIES = """
User-agent: *
Disallow: /*?
Disallow: /membership_data/
"""


class FakeClient:
    def __init__(self, bodies):
        self.bodies = bodies
        self.urls = []

    def get_text(self, url, **kwargs):
        self.urls.append(url)
        if url not in self.bodies:
            raise RuntimeError("404")
        return self.bodies[url]


def cache_for(body, host="x.test"):
    return RobotsCache(FakeClient({f"https://{host}/robots.txt": body}), enabled=True)


def test_allows_a_path_not_disallowed():
    assert cache_for(DISALLOW_LOGS).allows("https://x.test/index.html") is True


def test_rejects_a_disallowed_path():
    assert cache_for(DISALLOW_LOGS).allows("https://x.test/publiclogs/2025cw/") is False


def test_missing_robots_means_no_restriction():
    cache = RobotsCache(FakeClient({}), enabled=True)
    assert cache.allows("https://x.test/anything") is True


def test_robots_is_fetched_once_per_host():
    client = FakeClient({"https://x.test/robots.txt": DISALLOW_LOGS})
    cache = RobotsCache(client, enabled=True)
    cache.allows("https://x.test/a")
    cache.allows("https://x.test/b")
    assert client.urls.count("https://x.test/robots.txt") == 1


def test_report_warns_once_per_host(caplog):
    cache = cache_for(DISALLOW_LOGS)
    with caplog.at_level(logging.WARNING):
        cache.report("https://x.test/publiclogs/a.log")
        cache.report("https://x.test/publiclogs/b.log")
    assert caplog.text.lower().count("robots.txt") == 1


def test_report_is_silent_for_allowed_paths(caplog):
    cache = cache_for(DISALLOW_LOGS)
    with caplog.at_level(logging.WARNING):
        cache.report("https://x.test/index.html")
    assert caplog.text == ""


def test_report_never_blocks(caplog):
    """Reporting is advisory: it returns, it does not raise."""
    cache = cache_for(DISALLOW_LOGS)
    with caplog.at_level(logging.WARNING):
        assert cache.report("https://x.test/publiclogs/a.log") is None


def test_query_string_disallow_is_honoured_in_reporting():
    """SKCC disallows any URL carrying a query string."""
    cache = cache_for(DISALLOW_QUERIES)
    assert cache.allows("https://x.test/submit-display.php") is True
    assert cache.allows("https://x.test/submit-display.php?submit_id=235") is False


def test_disallowed_hosts_are_listed_for_a_summary():
    cache = cache_for(DISALLOW_LOGS)
    cache.report("https://x.test/publiclogs/a.log")
    assert cache.disallowed_hosts() == {"x.test"}


def test_a_url_with_no_host_is_allowed():
    cache = RobotsCache(FakeClient({}), enabled=True)
    assert cache.allows("not-a-url") is True


def test_checking_is_off_by_default():
    """The operator has decided which paths to fetch; see docs/research."""
    client = FakeClient({"https://x.test/robots.txt": DISALLOW_LOGS})
    cache = RobotsCache(client)
    assert cache.allows("https://x.test/publiclogs/a.log") is True


def test_disabled_checking_spends_no_request():
    client = FakeClient({"https://x.test/robots.txt": DISALLOW_LOGS})
    cache = RobotsCache(client)
    cache.allows("https://x.test/publiclogs/a.log")
    cache.report("https://x.test/publiclogs/a.log")
    assert client.urls == []
