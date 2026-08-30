import json

import pytest
import requests

from callsigns.errors import UpstreamError
from callsigns.http import DEFAULT_USER_AGENT, HttpClient


class FakeResponse:
    def __init__(self, status_code=200, payload=b"{}"):
        self.status_code = status_code
        self.content = payload
        self.headers = {}

    def json(self):
        return json.loads(self.content)


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.headers = {}

    def get(self, url, timeout=None, headers=None):
        self.calls.append((url, timeout))
        self.sent_headers = headers
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_get_json_returns_parsed_payload():
    session = FakeSession([FakeResponse(payload=b'[{"a": 1}]')])
    client = HttpClient(session=session)
    assert client.get_json("https://example.test/x") == [{"a": 1}]


def test_sets_user_agent_header():
    session = FakeSession([FakeResponse()])
    HttpClient(session=session).get_json("https://example.test/x")
    assert session.headers["User-Agent"] == DEFAULT_USER_AGENT


def test_passes_timeout():
    session = FakeSession([FakeResponse()])
    HttpClient(session=session, timeout=42.0).get_json("https://example.test/x")
    assert session.calls[0][1] == 42.0


def test_get_text_decodes_body():
    session = FakeSession([FakeResponse(payload=b"START-OF-LOG: 3.0")])
    assert (
        HttpClient(session=session).get_text("https://x.test/a") == "START-OF-LOG: 3.0"
    )


def test_retries_on_connection_error_then_succeeds():
    session = FakeSession(
        [requests.ConnectionError("boom"), FakeResponse(payload=b'{"ok": true}')]
    )
    client = HttpClient(session=session, retries=2, backoff=0.0)
    assert client.get_json("https://example.test/x") == {"ok": True}
    assert len(session.calls) == 2


def test_retries_on_500_then_gives_up():
    session = FakeSession([FakeResponse(status_code=500)] * 3)
    client = HttpClient(session=session, retries=2, backoff=0.0)
    with pytest.raises(UpstreamError, match="500"):
        client.get_json("https://example.test/x")
    assert len(session.calls) == 3


def test_does_not_retry_on_404():
    session = FakeSession([FakeResponse(status_code=404)])
    client = HttpClient(session=session, retries=2, backoff=0.0)
    with pytest.raises(UpstreamError, match="404"):
        client.get_json("https://example.test/x")
    assert len(session.calls) == 1


def test_unparseable_json_is_an_upstream_error():
    session = FakeSession([FakeResponse(payload=b"not json")])
    client = HttpClient(session=session, backoff=0.0)
    with pytest.raises(UpstreamError, match="JSON"):
        client.get_json("https://example.test/x")


def test_error_message_names_the_url():
    session = FakeSession([FakeResponse(status_code=404)])
    with pytest.raises(UpstreamError, match=r"https://example\.test/missing"):
        HttpClient(session=session, backoff=0.0).get_bytes(
            "https://example.test/missing"
        )


class HeadSession(FakeSession):
    def __init__(self, headers):
        super().__init__([])
        self.headers_to_return = headers
        self.head_calls = []

    def head(self, url, timeout=None, headers=None):
        self.head_calls.append((url, timeout))
        return type("R", (), {"headers": self.headers_to_return})()


def test_content_length_returns_the_header():
    session = HeadSession({"Content-Length": "1234"})
    assert HttpClient(session=session).content_length("https://x.test/a") == 1234


def test_content_length_is_none_when_absent():
    session = HeadSession({})
    assert HttpClient(session=session).content_length("https://x.test/a") is None


def test_content_length_is_none_when_unparseable():
    session = HeadSession({"Content-Length": "many"})
    assert HttpClient(session=session).content_length("https://x.test/a") is None


def test_content_length_is_none_when_head_raises():
    class Boom(FakeSession):
        def head(self, url, timeout=None, headers=None):
            raise requests.ConnectionError("no")

    assert HttpClient(session=Boom([])).content_length("https://x.test/a") is None


def test_real_session_pool_is_sized_for_our_concurrency():
    """urllib3 defaults to 10 and warns while discarding the surplus."""
    from callsigns.http import DEFAULT_POOL_SIZE

    client = HttpClient()
    adapter = client._session.get_adapter("https://example.test/")
    assert adapter._pool_maxsize >= DEFAULT_POOL_SIZE


def test_get_bytes_sends_the_full_header_set():
    session = FakeSession([FakeResponse()])
    HttpClient(session=session).get_bytes("https://x.test/publiclogs/2025cw/a.log")
    sent = session.sent_headers
    assert sent["User-Agent"] == DEFAULT_USER_AGENT
    assert "text/plain" in sent["Accept"]
    assert sent["Accept-Language"].startswith("en")
    assert "gzip" in sent["Accept-Encoding"]


def test_get_bytes_derives_an_accurate_referer():
    session = FakeSession([FakeResponse()])
    HttpClient(session=session).get_bytes("https://x.test/publiclogs/2025cw/a.log")
    assert session.sent_headers["Referer"] == "https://x.test/publiclogs/2025cw/"


def test_an_explicit_referer_wins():
    session = FakeSession([FakeResponse()])
    HttpClient(session=session).get_bytes(
        "https://x.test/a.log", referer="https://x.test/index.html"
    )
    assert session.sent_headers["Referer"] == "https://x.test/index.html"


def test_get_text_asks_for_html_by_default():
    session = FakeSession([FakeResponse()])
    HttpClient(session=session).get_text("https://x.test/index.html")
    assert "text/html" in session.sent_headers["Accept"]


def test_api_kind_asks_for_json():
    from callsigns.http import RequestKind

    session = FakeSession([FakeResponse()])
    HttpClient(session=session).get_bytes("https://x.test/api", kind=RequestKind.API)
    assert session.sent_headers["Accept"].startswith("application/json")


def test_no_fingerprint_headers_reach_the_wire():
    session = FakeSession([FakeResponse()])
    HttpClient(session=session).get_bytes("https://x.test/a")
    for name in session.sent_headers:
        assert not name.lower().startswith("sec-ch-ua")


from callsigns.pacing import HostPolicy, RateLimiter  # noqa: E402


class RecordingLimiter(RateLimiter):
    def __init__(self):
        super().__init__(
            HostPolicy(0.0, 0.0, 99), sleeper=lambda s: None, host_policies={}
        )
        self.hosts = []

    def acquire(self, host, *, probe=False):
        self.hosts.append(host)
        return super().acquire(host, probe=probe)


def test_every_get_passes_through_the_limiter():
    limiter = RecordingLimiter()
    session = FakeSession([FakeResponse(), FakeResponse()])
    client = HttpClient(session=session, limiter=limiter)
    client.get_bytes("https://a.test/one")
    client.get_bytes("https://b.test/two")
    assert limiter.hosts == ["a.test", "b.test"]


def test_head_passes_through_the_limiter():
    limiter = RecordingLimiter()
    session = HeadSession({"Content-Length": "5"})
    HttpClient(session=session, limiter=limiter).content_length("https://a.test/x")
    assert limiter.hosts == ["a.test"]


def test_retries_do_not_re_enter_the_limiter():
    """One acquire per logical request, not per attempt."""
    limiter = RecordingLimiter()
    session = FakeSession([FakeResponse(status_code=500), FakeResponse()])
    HttpClient(session=session, limiter=limiter, retries=1, backoff=0.0).get_bytes(
        "https://a.test/x"
    )
    assert limiter.hosts == ["a.test"]


def test_no_limiter_means_no_pacing():
    session = FakeSession([FakeResponse()])
    assert HttpClient(session=session).get_bytes("https://a.test/x") == b"{}"


class ConditionalSession(FakeSession):
    def __init__(self, status, headers=None):
        super().__init__([])
        self.status = status
        self.sent = {}
        self.response_headers = headers or {}

    def get(self, url, timeout=None, headers=None):
        self.sent = headers or {}
        return type(
            "R",
            (),
            {
                "status_code": self.status,
                "content": b"body",
                "headers": self.response_headers,
            },
        )()


def test_conditional_request_sends_the_validators():
    session = ConditionalSession(200)
    HttpClient(session=session).get_conditional(
        "https://x.test/a", etag='"abc"', last_modified="Thu, 12 Feb 2026 16:45:21 GMT"
    )
    assert session.sent["If-None-Match"] == '"abc"'
    assert session.sent["If-Modified-Since"] == "Thu, 12 Feb 2026 16:45:21 GMT"


def test_conditional_request_still_sends_the_normal_headers():
    session = ConditionalSession(200)
    HttpClient(session=session).get_conditional("https://x.test/a")
    assert session.sent["User-Agent"] == DEFAULT_USER_AGENT
    assert "Accept" in session.sent


def test_304_reports_unchanged_with_no_body():
    session = ConditionalSession(304)
    result = HttpClient(session=session).get_conditional("https://x.test/a", etag='"a"')
    assert result.status == 304
    assert result.body is None
    assert result.unchanged is True


def test_200_returns_the_body_and_new_validators():
    session = ConditionalSession(
        200, {"ETag": '"new"', "Last-Modified": "Fri, 13 Feb 2026 00:00:00 GMT"}
    )
    result = HttpClient(session=session).get_conditional("https://x.test/a")
    assert result.body == b"body"
    assert result.etag == '"new"'
    assert result.unchanged is False


def test_conditional_error_status_is_an_upstream_error():
    session = ConditionalSession(500)
    with pytest.raises(UpstreamError, match="500"):
        HttpClient(session=session).get_conditional("https://x.test/a")


def test_conditional_request_is_paced():
    limiter = RecordingLimiter()
    session = ConditionalSession(304)
    HttpClient(session=session, limiter=limiter).get_conditional("https://a.test/x")
    assert limiter.hosts == ["a.test"]


def test_429_is_retried_because_it_means_slow_down():
    session = FakeSession([FakeResponse(status_code=429), FakeResponse()])
    client = HttpClient(session=session, retries=2, backoff=0.0)
    assert client.get_bytes("https://x.test/a") == b"{}"
    assert len(session.calls) == 2


def test_429_honours_retry_after(monkeypatch):
    slept = []
    monkeypatch.setattr("callsigns.http.time.sleep", lambda s: slept.append(s))

    class WithRetryAfter(FakeResponse):
        def __init__(self):
            super().__init__(status_code=429)
            self.headers = {"Retry-After": "7"}

    session = FakeSession([WithRetryAfter(), FakeResponse()])
    HttpClient(session=session, retries=2, backoff=1.0).get_bytes("https://x.test/a")
    assert slept == [7.0]


def test_retry_after_is_capped():
    from callsigns.http import MAX_RETRY_AFTER, _retry_after

    class R:
        headers = {"Retry-After": "99999"}

    assert _retry_after(R()) == MAX_RETRY_AFTER


def test_retry_after_ignores_http_date_form():
    class R:
        headers = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}

    from callsigns.http import _retry_after

    assert _retry_after(R()) is None


def test_404_is_still_not_retried():
    session = FakeSession([FakeResponse(status_code=404)])
    with pytest.raises(UpstreamError, match="404"):
        HttpClient(session=session, retries=2, backoff=0.0).get_bytes(
            "https://x.test/a"
        )
    assert len(session.calls) == 1
