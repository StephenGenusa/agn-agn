import pytest

from callsigns.headers import (
    DEFAULT_USER_AGENT,
    RequestKind,
    headers_for,
    referer_for,
)


def test_user_agent_is_a_single_well_formed_line():
    assert DEFAULT_USER_AGENT.strip() == DEFAULT_USER_AGENT
    assert "\n" not in DEFAULT_USER_AGENT
    assert len(DEFAULT_USER_AGENT) < 256


def test_page_requests_accept_html():
    accept = headers_for(RequestKind.PAGE)["Accept"]
    assert "text/html" in accept


def test_data_requests_accept_text_and_octet_stream():
    accept = headers_for(RequestKind.DATA)["Accept"]
    assert "text/plain" in accept
    assert "application/octet-stream" in accept


def test_api_requests_prefer_json():
    accept = headers_for(RequestKind.API)["Accept"]
    assert accept.startswith("application/json")


def test_every_kind_sends_the_common_headers():
    for kind in RequestKind:
        sent = headers_for(kind)
        assert sent["Accept-Language"].startswith("en")
        assert "gzip" in sent["Accept-Encoding"]
        assert sent["User-Agent"] == DEFAULT_USER_AGENT
        assert sent["Connection"] == "keep-alive"


def test_no_browser_fingerprint_headers_are_sent():
    for kind in RequestKind:
        for name in headers_for(kind):
            lowered = name.lower()
            assert not lowered.startswith("sec-ch-ua")
            assert lowered != "sec-fetch-user"


def test_referer_can_be_supplied():
    sent = headers_for(RequestKind.DATA, referer="https://x.test/publiclogs/2025cw/")
    assert sent["Referer"] == "https://x.test/publiclogs/2025cw/"


def test_referer_is_omitted_when_not_supplied():
    assert "Referer" not in headers_for(RequestKind.DATA)


def test_headers_are_a_fresh_mapping_each_call():
    first = headers_for(RequestKind.PAGE)
    first["Accept"] = "mutated"
    assert headers_for(RequestKind.PAGE)["Accept"] != "mutated"


def test_referer_for_derives_the_parent_directory():
    got = referer_for("https://cqww.com/publiclogs/2025cw/3b8m.log")
    assert got == "https://cqww.com/publiclogs/2025cw/"


def test_referer_for_a_query_url_drops_the_query():
    got = referer_for("https://contests.arrl.org/showpubliclog.php?cn=dxcw&call=X")
    assert got == "https://contests.arrl.org/"


def test_referer_for_a_bare_host():
    assert referer_for("https://x.test/") == "https://x.test/"


def test_referer_for_rejects_nonsense():
    assert referer_for("not a url") is None


@pytest.mark.parametrize("kind", list(RequestKind))
def test_kinds_are_string_valued(kind):
    assert isinstance(kind.value, str)
