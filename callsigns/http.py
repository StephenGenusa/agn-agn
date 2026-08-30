"""Shared HTTP access with uniform timeout, retry and error behaviour."""

import json
import logging
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import requests

from callsigns.errors import UpstreamError
from callsigns.headers import DEFAULT_USER_AGENT, RequestKind, headers_for, referer_for
from callsigns.pacing import RateLimiter

__all__ = [
    "DEFAULT_POOL_SIZE",
    "DEFAULT_USER_AGENT",
    "ConditionalResult",
    "HttpClient",
    "RequestKind",
    "parse_json",
]

DEFAULT_TIMEOUT: float = 120.0
DEFAULT_RETRIES: int = 2
DEFAULT_BACKOFF: float = 1.0

#: Connections kept alive per host. urllib3 defaults to 10 and discards the
#: surplus with a warning, which forces a new TCP handshake per discarded
#: connection. Sized above the highest concurrency this package uses.
DEFAULT_POOL_SIZE: int = 32

#: Statuses worth trying again. 5xx is transient by definition; 429 is the
#: server explicitly asking us to slow down, which is a reason to wait rather
#: than to give up. Every other 4xx is permanent — a 404 will not become a 200.
RETRYABLE_STATUSES: frozenset[int] = frozenset({429})

#: Longest we will honour a ``Retry-After`` before treating it as a refusal.
MAX_RETRY_AFTER: float = 300.0

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConditionalResult:
    """The outcome of a revalidation request."""

    status: int
    body: bytes | None
    etag: str | None
    last_modified: str | None

    @property
    def unchanged(self) -> bool:
        """Return whether the server said the cached copy is still current."""
        return self.status == 304


class HttpClient:
    """An HTTP client with retries, a long timeout, and mapped errors.

    Providers use this rather than calling ``requests`` directly so that
    retry, timeout and error behaviour are identical across every source.
    """

    def __init__(
        self,
        *,
        session: Any | None = None,  # noqa: ANN401 - any object with .get/.headers
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
        user_agent: str = DEFAULT_USER_AGENT,
        limiter: RateLimiter | None = None,
    ) -> None:
        """Initialise the client.

        Args:
            session: Transport with a ``get(url, timeout=...)`` method and a
                ``headers`` mapping. Defaults to a new ``requests.Session``.
                Injectable so tests need no network.
            timeout: Per-request timeout in seconds.
            retries: Additional attempts after the first failure.
            backoff: Base seconds for exponential backoff between attempts.
            user_agent: Value sent as the ``User-Agent`` header.
            limiter: Per-host pacing. When omitted, requests are not paced;
                the harvest path always supplies one.
        """
        self._limiter = limiter
        if session is not None:
            self._session = session
        else:
            self._session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=DEFAULT_POOL_SIZE,
                pool_maxsize=DEFAULT_POOL_SIZE,
            )
            self._session.mount("https://", adapter)
            self._session.mount("http://", adapter)
        self._session.headers["User-Agent"] = user_agent
        self._timeout = timeout
        self._retries = retries
        self._backoff = backoff

    def set_limiter(self, limiter: RateLimiter) -> None:
        """Attach per-host pacing to this client.

        Args:
            limiter: The limiter every subsequent request must pass through.
        """
        self._limiter = limiter

    def get_bytes(
        self,
        url: str,
        *,
        kind: RequestKind = RequestKind.DATA,
        referer: str | None = None,
    ) -> bytes:
        """Fetch a URL and return its raw body.

        Retries transport failures and 5xx responses with exponential
        backoff. A 4xx is never retried: it will not become a 200.

        Args:
            url: Absolute URL to fetch.
            kind: What sort of resource this is, which selects the ``Accept``
                header.
            referer: The page this link was followed from. When omitted, one
                is derived from the URL, which is accurate for the directory
                listings and query endpoints this tool reads.

        Returns:
            The response body.

        Raises:
            UpstreamError: The request failed after all retries, or the
                server returned a non-2xx status.
        """
        sent = headers_for(kind, referer if referer is not None else referer_for(url))
        self._pace(url)
        last_error = "no attempt made"
        retry_after: float | None = None
        for attempt in range(self._retries + 1):
            try:
                response = self._session.get(url, timeout=self._timeout, headers=sent)
            except Exception as exc:  # transport failure of any kind is retryable
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                status = int(response.status_code)
                if 200 <= status < 300:
                    return bytes(response.content)
                last_error = f"HTTP {status}"
                if status < 500 and status not in RETRYABLE_STATUSES:
                    break
                retry_after = _retry_after(response)
            if attempt < self._retries:
                delay = retry_after or self._backoff * (2**attempt)
                _LOGGER.info("retrying %s after %s (%.1fs)", url, last_error, delay)
                if delay:
                    time.sleep(delay)
            retry_after = None
        raise UpstreamError(f"GET {url} failed: {last_error}")

    def _pace(self, url: str, *, probe: bool = False) -> None:
        """Wait until this URL's host may be contacted again.

        Called once per logical request, not once per retry attempt: a retry
        already backs off on its own, and pacing it twice would double the
        delay for no benefit.

        Args:
            url: The URL about to be requested.
            probe: Whether this is a ``HEAD`` size probe.
        """
        if self._limiter is not None:
            self._limiter.acquire(
                urllib.parse.urlsplit(url).hostname or "", probe=probe
            )

    def get_conditional(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        kind: RequestKind = RequestKind.DATA,
    ) -> ConditionalResult:
        """Fetch a URL only if it changed since it was last retrieved.

        Args:
            url: Absolute URL to fetch.
            etag: ``ETag`` recorded when the file was last fetched.
            last_modified: ``Last-Modified`` recorded when last fetched.
            kind: What sort of resource this is.

        Returns:
            The result; ``unchanged`` is true when the server answered 304 and
            the cached copy is still current.

        Raises:
            UpstreamError: The request failed or returned an error status.
        """
        sent = headers_for(kind, referer_for(url))
        if etag:
            sent["If-None-Match"] = etag
        if last_modified:
            sent["If-Modified-Since"] = last_modified
        self._pace(url)
        try:
            response = self._session.get(url, timeout=self._timeout, headers=sent)
        except Exception as exc:
            raise UpstreamError(
                f"GET {url} failed: {type(exc).__name__}: {exc}"
            ) from exc
        status = int(response.status_code)
        if status == 304:
            return ConditionalResult(304, None, etag, last_modified)
        if not 200 <= status < 300:
            raise UpstreamError(f"GET {url} failed: HTTP {status}")
        return ConditionalResult(
            status,
            bytes(response.content),
            response.headers.get("ETag"),
            response.headers.get("Last-Modified"),
        )

    def content_length(self, url: str) -> int | None:
        """Return a URL's size without downloading it.

        Args:
            url: Absolute URL to probe.

        Returns:
            The ``Content-Length`` in bytes, or ``None`` when the server does
            not report one — dynamic endpoints often do not.
        """
        self._pace(url, probe=True)
        try:
            response = self._session.head(
                url,
                timeout=self._timeout,
                headers=headers_for(RequestKind.DATA, referer_for(url)),
            )
        except Exception as exc:
            _LOGGER.debug("HEAD %s failed: %s", url, exc)
            return None
        raw = response.headers.get("Content-Length")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def get_text(
        self,
        url: str,
        *,
        kind: RequestKind = RequestKind.PAGE,
        referer: str | None = None,
    ) -> str:
        """Fetch a URL and decode its body as UTF-8.

        Args:
            url: Absolute URL to fetch.
            kind: What sort of resource this is. Text fetches are usually HTML
                pages, so this defaults to ``PAGE``.
            referer: The page this link was followed from.

        Returns:
            The decoded body, with undecodable bytes replaced.

        Raises:
            UpstreamError: The request failed.
        """
        return self.get_bytes(url, kind=kind, referer=referer).decode(
            "utf-8", errors="replace"
        )

    def get_json(self, url: str) -> object:
        """Fetch a URL and parse its body as JSON.

        Args:
            url: Absolute URL to fetch.

        Returns:
            The parsed JSON document.

        Raises:
            UpstreamError: The request failed or the body was not valid JSON.
        """
        return parse_json(url, self.get_bytes(url))


def _retry_after(response: Any) -> float | None:  # noqa: ANN401 - duck-typed
    """Return how long a server asked us to wait, if it said.

    A ``429`` or ``503`` may carry ``Retry-After``. Honouring it is the whole
    point of treating those statuses as retryable rather than fatal.

    Args:
        response: The HTTP response.

    Returns:
        Seconds to wait, capped at :data:`MAX_RETRY_AFTER`, or ``None``.
    """
    raw = getattr(response, "headers", {}).get("Retry-After")
    if raw is None:
        return None
    try:
        return min(float(raw), MAX_RETRY_AFTER)
    except TypeError, ValueError:
        return None


def parse_json(url: str, raw: bytes) -> object:
    """Parse a response body as JSON, reporting failures as upstream errors.

    Separate from :meth:`HttpClient.get_json` so a provider that needs the
    raw bytes as well can fetch once and parse with identical error handling.

    Args:
        url: The URL the body came from, used in the error message.
        raw: The response body.

    Returns:
        The parsed JSON document.

    Raises:
        UpstreamError: The body was not valid JSON.
    """
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise UpstreamError(f"GET {url} returned invalid JSON: {exc}") from exc
