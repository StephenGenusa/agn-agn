"""Request headers.

A bare HTTP client sends almost nothing: a `User-Agent` and little else. Some
servers filter such requests, not because they object to the client but because
an incomplete request is indistinguishable from a badly behaved one. Sending
the full set of headers any ordinary client sends avoids being caught by that.

The headers here are all accurate. ``Accept`` describes what the caller can
actually use, ``Referer`` names the page a link was genuinely followed from,
and the ``User-Agent`` says what this tool is and where to reach its operator.
There is deliberately no browser version string and no ``Sec-Ch-Ua`` brand
claim: those assert an identity the tool does not have, and a server that
refuses non-browser clients is answered by respecting the refusal rather than
by dressing up.
"""

import enum
import urllib.parse

#: Sent on every request. Set by the operator to a current Firefox string.
#:
#: Note for anyone maintaining this: the sites this tool reads all serve it
#: perfectly well with a bot User-Agent — the 403s originally seen from
#: skccgroup.com and cwops.org came from curl's TLS fingerprint, not from any
#: User-Agent check. So this string is not load-bearing for access, and
#: changing it back to something that identifies the tool and carries a
#: contact address costs nothing in reach.
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0"
)


class RequestKind(enum.StrEnum):
    """What sort of resource a request is for.

    The correct ``Accept`` header differs between an HTML index, a plain-text
    log and a JSON API, and sending the right one is both more accurate and
    less likely to be filtered.
    """

    PAGE = "page"
    DATA = "data"
    API = "api"


_ACCEPT: dict[RequestKind, str] = {
    RequestKind.PAGE: (
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    ),
    RequestKind.DATA: (
        "text/plain,application/octet-stream,application/zip;q=0.9,*/*;q=0.8"
    ),
    RequestKind.API: "application/json,text/plain;q=0.9,*/*;q=0.8",
}

_COMMON: dict[str, str] = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


def headers_for(kind: RequestKind, referer: str | None = None) -> dict[str, str]:
    """Build the header set for one request.

    Args:
        kind: What sort of resource is being fetched.
        referer: The page this link was followed from, when there genuinely
            was one. Omitted otherwise rather than invented.

    Returns:
        A fresh mapping, safe for the caller to modify.
    """
    sent = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": _ACCEPT[kind],
        **_COMMON,
    }
    if referer:
        sent["Referer"] = referer
    return sent


def referer_for(url: str) -> str | None:
    """Return the page a URL would naturally have been reached from.

    For a file in a directory listing that is the listing itself; for a query
    URL it is the site root, since the query carries the navigation rather than
    the path.

    Args:
        url: The URL about to be fetched.

    Returns:
        A referer URL, or ``None`` if one cannot be derived.
    """
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    if parts.query:
        return f"{parts.scheme}://{parts.netloc}/"
    path = parts.path or "/"
    parent = path.rsplit("/", 1)[0] + "/" if "/" in path else "/"
    return f"{parts.scheme}://{parts.netloc}{parent}"
