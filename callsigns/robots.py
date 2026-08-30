"""robots.txt awareness.

The tool reports rather than enforces: a disallowed path produces one warning
per host per run and the fetch proceeds. Whether to honour a site's stated
crawler preference is the operator's decision; surfacing it keeps that decision
informed rather than accidental, and gives the harvest summary something
concrete to show at the end of a long run.
"""

import logging
import urllib.parse
import urllib.robotparser
from typing import Protocol

_LOGGER = logging.getLogger(__name__)


class _TextFetcher(Protocol):
    """The slice of :class:`HttpClient` this module needs."""

    def get_text(self, url: str) -> str:
        """Return the decoded body of a URL."""
        ...


class RobotsCache:
    """Fetches and caches one ``robots.txt`` parser per host."""

    def __init__(
        self,
        client: _TextFetcher,
        user_agent: str = "*",
        *,
        enabled: bool = False,
    ) -> None:
        """Initialise the cache.

        Args:
            client: Fetcher used to retrieve ``robots.txt``.
            user_agent: Agent name to test rules against. The wildcard group is
                the conservative choice: it reports a restriction even where a
                narrower rule would not apply.
            enabled: Whether to consult ``robots.txt`` at all. Off by default,
                at the operator's direction — the paths this tool reads are
                documented in ``docs/research`` and the decision to fetch them
                has been made deliberately. When off, nothing is fetched and
                :meth:`allows` always answers ``True``, so no request is spent
                on a file whose answer would be ignored.
        """
        self._client = client
        self._user_agent = user_agent
        self._enabled = enabled
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._warned: set[str] = set()

    def _parser_for(
        self, host: str, scheme: str
    ) -> urllib.robotparser.RobotFileParser | None:
        """Return a parser for a host, fetching ``robots.txt`` on first use.

        Args:
            host: Hostname.
            scheme: URL scheme to use when fetching.

        Returns:
            The parser, or ``None`` when the host publishes no usable file.
        """
        if host in self._parsers:
            return self._parsers[host]
        parser: urllib.robotparser.RobotFileParser | None = None
        try:
            body = self._client.get_text(f"{scheme}://{host}/robots.txt")
        except Exception:
            body = None
        if body is not None:
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(body.splitlines())
        self._parsers[host] = parser
        return parser

    def allows(self, url: str) -> bool:
        """Return whether a URL is permitted by its host's ``robots.txt``.

        Args:
            url: Absolute URL.

        Returns:
            ``True`` when permitted, or when the host publishes no rules.
        """
        if not self._enabled:
            return True
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
        if not host:
            return True
        parser = self._parser_for(host, parts.scheme or "https")
        if parser is None:
            return True
        return bool(parser.can_fetch(self._user_agent, url))

    def report(self, url: str) -> None:
        """Warn once per host when a URL is disallowed.

        Args:
            url: Absolute URL about to be fetched.
        """
        if self.allows(url):
            return
        host = urllib.parse.urlsplit(url).hostname or ""
        if host in self._warned:
            return
        self._warned.add(host)
        _LOGGER.warning(
            "%s robots.txt asks crawlers not to fetch this path; continuing "
            "because this tool reports rather than enforces",
            host,
        )

    def disallowed_hosts(self) -> set[str]:
        """Return the hosts a disallowed path was reported for this run.

        Returns:
            Hostnames, for a summary at the end of a harvest.
        """
        return set(self._warned)
