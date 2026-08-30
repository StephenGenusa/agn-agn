"""CQ contest log providers.

CQ serves public logs as a static directory of ``<call>.log`` files, so a
``HEAD`` gives each log's size before downloading. Size tracks QSO count at
roughly 90 bytes per line, which is what makes downloading only the largest
logs a sound way to saturate the ranking cheaply.
"""

import concurrent.futures
import logging
import re
from typing import ClassVar

from callsigns.cache import FileCache
from callsigns.http import HttpClient
from callsigns.providers import register
from callsigns.providers.contest.base import ContestLogProvider, LogRef

#: CQ's listing markup uses single-quoted attributes; ARRL uses double. Accept
#: either so the same parser serves both.
_LINK_RE = re.compile(r"""href=["']([^"']+\.log)["']""", re.IGNORECASE)

#: Size probes are ``HEAD`` requests returning no body, so they are far
#: cheaper for the server than downloads and run at higher concurrency.
#: Measured against CQ WW 2025's 8,109 logs: 102 s at 6, 44 s at 16.
DEFAULT_PROBE_JOBS: int = 16

_LOGGER = logging.getLogger(__name__)


def parse_log_links(html: str) -> list[str]:
    """Extract log filenames from a CQ public-logs index page.

    Args:
        html: The index page markup.

    Returns:
        Filenames in page order, deduplicated.
    """
    seen: dict[str, None] = {}
    for name in _LINK_RE.findall(html):
        seen.setdefault(name.rsplit("/", 1)[-1], None)
    return list(seen)


class CqLogProvider(ContestLogProvider):
    """A CQ contest whose logs live in a static, size-probeable directory."""

    #: Host serving the public logs, without scheme.
    host: ClassVar[str]

    #: Suffix identifying the mode directory, such as ``cw``.
    mode_suffix: ClassVar[str] = "cw"

    def __init__(
        self,
        cache: FileCache | None = None,
        *,
        client: HttpClient | None = None,
        top_logs: int | None = None,
        jobs: int | None = None,
        probe_jobs: int = DEFAULT_PROBE_JOBS,
    ) -> None:
        """Initialise the provider.

        Args:
            cache: Download cache for the logs themselves.
            client: HTTP client for listing and size probes.
            top_logs: Maximum logs to download; ``None`` keeps the default.
            jobs: Maximum concurrent downloads; ``None`` keeps the default.
            probe_jobs: Maximum concurrent ``HEAD`` size probes.
        """
        super().__init__(cache)
        if top_logs is not None:
            self.top_logs = top_logs
        if jobs is not None:
            self.jobs = jobs
        self.probe_jobs = probe_jobs
        self._client = client if client is not None else HttpClient()

    def listing_url(self, period: str) -> str:
        """Return the index page URL for a contest year.

        Args:
            period: A validated period token.

        Returns:
            The directory URL, with a trailing slash.
        """
        return f"https://{self.host}/publiclogs/{period}{self.mode_suffix}/"

    def source_url(self, period: str) -> str:
        """Return the listing URL, for the metadata sheet.

        Args:
            period: A validated period token.

        Returns:
            The index page URL.
        """
        return self.listing_url(period)

    def list_entrants(self, period: str) -> list[LogRef]:
        """List the published logs without probing their sizes.

        One request. Separate from :meth:`list_logs` because the listing is
        cheap and the probing is not, and callers that only need the entrant
        set should not pay for thousands of ``HEAD`` requests.

        Args:
            period: A validated period token.

        Returns:
            One reference per entrant, every ``size`` unset.

        Raises:
            UpstreamError: The index page could not be retrieved.
        """
        base = self.listing_url(period)
        return [
            LogRef(callsign=name.removesuffix(".log").upper(), url=base + name)
            for name in parse_log_links(self._client.get_text(base))
        ]

    def probe_sizes(self, refs: list[LogRef]) -> list[LogRef]:
        """Fill in each reference's size using concurrent ``HEAD`` requests.

        Probing one at a time is not viable: CQ WW 2025 publishes 8,109 logs,
        which takes about ten minutes sequentially against roughly 44 seconds
        at the default concurrency.

        Args:
            refs: References to probe.

        Returns:
            New references carrying sizes, in the order given.
        """
        if not refs:
            return []
        _LOGGER.info("%s: probing %d log sizes", self.key, len(refs))
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(self.probe_jobs, 1)
        ) as pool:
            sizes = list(pool.map(self._client.content_length, [r.url for r in refs]))
        return [
            LogRef(callsign=ref.callsign, url=ref.url, size=size)
            for ref, size in zip(refs, sizes, strict=True)
        ]

    def list_logs(self, period: str) -> list[LogRef]:
        """List the published logs and probe each for its size.

        Args:
            period: A validated period token.

        Returns:
            One reference per entrant, with sizes where the server reports
            them.

        Raises:
            UpstreamError: The index page could not be retrieved.
        """
        return self.probe_sizes(self.list_entrants(period))


@register
class CqWwCwProvider(CqLogProvider):
    """CQ World Wide DX Contest, CW."""

    key = "cqww-cw"
    label = "CQ WW DX CW"
    store_name = "CQWW-CW.xlsx"
    export_prefix = "CQWW-CW"
    calls_prefix = "CQWW-CW"
    host = "cqww.com"
    first_year = 2019


@register
class CqWpxCwProvider(CqLogProvider):
    """CQ WPX Contest, CW."""

    key = "cqwpx-cw"
    label = "CQ WPX CW"
    store_name = "CQWPX-CW.xlsx"
    export_prefix = "CQWPX-CW"
    calls_prefix = "CQWPX-CW"
    host = "cqwpx.com"
    first_year = 2023


@register
class Cq160CwProvider(CqLogProvider):
    """CQ 160 Meter Contest, CW."""

    key = "cq160-cw"
    label = "CQ 160 CW"
    store_name = "CQ160-CW.xlsx"
    export_prefix = "CQ160-CW"
    calls_prefix = "CQ160-CW"
    host = "cq160.com"
    first_year = 2022


@register
class CqWwRttyProvider(CqLogProvider):
    """CQ World Wide RTTY Contest.

    The RTTY and digital hosts publish a bare year directory with no mode
    suffix, since each host serves a single mode.
    """

    key = "cqww-rtty"
    label = "CQ WW RTTY"
    store_name = "CQWW-RTTY.xlsx"
    export_prefix = "CQWW-RTTY"
    calls_prefix = "CQWW-RTTY"
    host = "cqwwrtty.com"
    mode_suffix = ""
    first_year = 2019


@register
class CqWpxRttyProvider(CqLogProvider):
    """CQ WPX RTTY Contest."""

    key = "cqwpx-rtty"
    label = "CQ WPX RTTY"
    store_name = "CQWPX-RTTY.xlsx"
    export_prefix = "CQWPX-RTTY"
    calls_prefix = "CQWPX-RTTY"
    host = "cqwpxrtty.com"
    mode_suffix = ""
    first_year = 2019


@register
class WwDigiProvider(CqLogProvider):
    """World Wide Digi DX Contest."""

    key = "ww-digi"
    label = "WW Digi DX"
    store_name = "WW-DIGI.xlsx"
    export_prefix = "WW-DIGI"
    calls_prefix = "WW-DIGI"
    host = "ww-digi.com"
    mode_suffix = ""
    first_year = 2019
