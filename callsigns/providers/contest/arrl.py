"""ARRL contest log providers.

ARRL serves logs from a dynamic endpoint, which needs two requests before any
log can be fetched: one to map a contest year to its internal ``iid``, and one
to list the entrants for that year. ``HEAD`` returns 200 with no
``Content-Length``, so unlike CQ the logs cannot be size-ranked and are taken
in listing order.
"""

import re
from typing import ClassVar

from callsigns.cache import FileCache
from callsigns.errors import UpstreamError
from callsigns.http import HttpClient
from callsigns.providers import register
from callsigns.providers.contest.base import ContestLogProvider, LogRef

BASE_URL: str = "https://contests.arrl.org"

_YEAR_RE = re.compile(
    r"""href=["']publiclogs\.php\?eid=(\d+)&(?:amp;)?iid=(\d+)["']>\s*(\d{4})\s*<""",
    re.IGNORECASE,
)
#: ARRL encodes the slash of a compound callsign as a hyphen in the query
#: string — ``call=6Y-AI5IN`` is displayed as ``6Y/AI5IN``. The hyphen must be
#: captured or the URL is truncated to a bare prefix, which answers HTTP 400.
_ENTRANT_RE = re.compile(
    r"""showpubliclog\.php\?[^"']*call=([A-Z0-9/-]+)""", re.IGNORECASE
)


def parse_year_map(html: str) -> dict[str, tuple[str, str]]:
    """Map each published year to its ``eid`` and ``iid``.

    Args:
        html: The contest's public-logs landing page.

    Returns:
        Year to ``(eid, iid)``.
    """
    return {year: (eid, iid) for eid, iid, year in _YEAR_RE.findall(html)}


def parse_entrants(html: str) -> list[str]:
    """Extract entrant callsigns from a year's listing page.

    Args:
        html: The listing page markup.

    Returns:
        Callsigns exactly as the query string spells them, in page order and
        deduplicated. Compound callsigns keep their hyphen, because that is
        what the log endpoint expects; :func:`display_callsign` converts it
        back to a slash for storage.
    """
    seen: dict[str, None] = {}
    for call in _ENTRANT_RE.findall(html):
        seen.setdefault(call.upper(), None)
    return list(seen)


def display_callsign(url_callsign: str) -> str:
    """Convert a URL-form callsign back to how it is normally written.

    Args:
        url_callsign: The callsign as it appears in the query string.

    Returns:
        The callsign with hyphens restored to slashes.
    """
    return url_callsign.replace("-", "/")


class ArrlContestProvider(ContestLogProvider):
    """One ARRL contest's published logs."""

    #: The ``cn`` query value identifying the contest.
    contest: ClassVar[str]

    first_year = 2018

    def __init__(
        self,
        cache: FileCache | None = None,
        *,
        client: HttpClient | None = None,
        top_logs: int | None = None,
        jobs: int | None = None,
    ) -> None:
        """Initialise the provider.

        Args:
            cache: Download cache for the logs themselves.
            client: HTTP client for discovery and listing.
            top_logs: Maximum logs to download; ``None`` keeps the default.
            jobs: Maximum concurrent downloads; ``None`` keeps the default.
        """
        super().__init__(cache)
        if top_logs is not None:
            self.top_logs = top_logs
        if jobs is not None:
            self.jobs = jobs
        self._client = client if client is not None else HttpClient()

    def source_url(self, period: str) -> str:
        """Return the contest's landing page, for the metadata sheet.

        Args:
            period: A validated period token.

        Returns:
            The landing page URL.
        """
        del period
        return f"{BASE_URL}/publiclogs.php?cn={self.contest}"

    def list_logs(self, period: str) -> list[LogRef]:
        """Discover the year's listing and read its entrants.

        Args:
            period: A validated period token.

        Returns:
            One reference per entrant, with unknown sizes.

        Raises:
            UpstreamError: The landing page has no logs for this year, or a
                page could not be retrieved.
        """
        landing = self._client.get_text(self.source_url(period))
        years = parse_year_map(landing)
        if period not in years:
            available = ", ".join(sorted(years, reverse=True)) or "none"
            raise UpstreamError(
                f"{self.key} has no published logs for {period}; "
                f"available years: {available}"
            )
        eid, iid = years[period]
        listing = self._client.get_text(
            f"{BASE_URL}/publiclogs.php?eid={eid}&iid={iid}"
        )
        return [
            LogRef(
                callsign=display_callsign(call),
                url=(
                    f"{BASE_URL}/showpubliclog.php?"
                    f"cn={self.contest}&yr={period}&call={call}"
                ),
                size=None,
            )
            for call in parse_entrants(listing)
        ]


@register
class ArrlDxCwProvider(ArrlContestProvider):
    """ARRL International DX Contest, CW."""

    key = "arrl-dxcw"
    label = "ARRL DX CW"
    store_name = "ARRL-DXCW.xlsx"
    export_prefix = "ARRL-DXCW"
    calls_prefix = "ARRL-DXCW"
    contest = "dxcw"


@register
class ArrlSsCwProvider(ArrlContestProvider):
    """ARRL November Sweepstakes, CW. US and VE domestic."""

    key = "arrl-sscw"
    label = "ARRL Sweepstakes CW"
    store_name = "ARRL-SSCW.xlsx"
    export_prefix = "ARRL-SSCW"
    calls_prefix = "ARRL-SSCW"
    contest = "sscw"


@register
class Arrl10mProvider(ArrlContestProvider):
    """ARRL 10-Meter Contest."""

    key = "arrl-10m"
    label = "ARRL 10 Meter"
    store_name = "ARRL-10M.xlsx"
    export_prefix = "ARRL-10M"
    calls_prefix = "ARRL-10M"
    contest = "10m"


@register
class Arrl160mProvider(ArrlContestProvider):
    """ARRL 160-Meter Contest."""

    key = "arrl-160m"
    label = "ARRL 160 Meter"
    store_name = "ARRL-160M.xlsx"
    export_prefix = "ARRL-160M"
    calls_prefix = "ARRL-160M"
    contest = "160m"


@register
class ArrlIaruHfProvider(ArrlContestProvider):
    """IARU HF World Championship."""

    key = "arrl-iaruhf"
    label = "IARU HF Championship"
    store_name = "ARRL-IARUHF.xlsx"
    export_prefix = "ARRL-IARUHF"
    calls_prefix = "ARRL-IARUHF"
    contest = "iaruhf"


@register
class ArrlDxPhProvider(ArrlContestProvider):
    """ARRL International DX Contest, Phone."""

    key = "arrl-dxph"
    label = "ARRL DX Phone"
    store_name = "ARRL-DXPH.xlsx"
    export_prefix = "ARRL-DXPH"
    calls_prefix = "ARRL-DXPH"
    contest = "dxph"


@register
class ArrlSsPhProvider(ArrlContestProvider):
    """ARRL November Sweepstakes, Phone."""

    key = "arrl-ssph"
    label = "ARRL Sweepstakes Phone"
    store_name = "ARRL-SSPH.xlsx"
    export_prefix = "ARRL-SSPH"
    calls_prefix = "ARRL-SSPH"
    contest = "ssph"


@register
class ArrlRttyRuProvider(ArrlContestProvider):
    """ARRL RTTY Roundup."""

    key = "arrl-rttyru"
    label = "ARRL RTTY Roundup"
    store_name = "ARRL-RTTYRU.xlsx"
    export_prefix = "ARRL-RTTYRU"
    calls_prefix = "ARRL-RTTYRU"
    contest = "rttyru"


@register
class ArrlDigitalProvider(ArrlContestProvider):
    """ARRL International Digital Contest."""

    key = "arrl-dig"
    label = "ARRL Digital"
    store_name = "ARRL-DIG.xlsx"
    export_prefix = "ARRL-DIG"
    calls_prefix = "ARRL-DIG"
    contest = "dig"


@register
class ArrlEmeProvider(ArrlContestProvider):
    """ARRL International EME Contest."""

    key = "arrl-eme"
    label = "ARRL EME"
    store_name = "ARRL-EME.xlsx"
    export_prefix = "ARRL-EME"
    calls_prefix = "ARRL-EME"
    contest = "eme"


@register
class ArrlJanVhfProvider(ArrlContestProvider):
    """ARRL January VHF Contest."""

    key = "arrl-janvhf"
    label = "ARRL January VHF"
    store_name = "ARRL-JANVHF.xlsx"
    export_prefix = "ARRL-JANVHF"
    calls_prefix = "ARRL-JANVHF"
    contest = "janvhf"


@register
class ArrlJunVhfProvider(ArrlContestProvider):
    """ARRL June VHF Contest."""

    key = "arrl-junvhf"
    label = "ARRL June VHF"
    store_name = "ARRL-JUNVHF.xlsx"
    export_prefix = "ARRL-JUNVHF"
    calls_prefix = "ARRL-JUNVHF"
    contest = "junvhf"


@register
class ArrlSepVhfProvider(ArrlContestProvider):
    """ARRL September VHF Contest."""

    key = "arrl-sepvhf"
    label = "ARRL September VHF"
    store_name = "ARRL-SEPVHF.xlsx"
    export_prefix = "ARRL-SEPVHF"
    calls_prefix = "ARRL-SEPVHF"
    contest = "sepvhf"


@register
class Arrl222Provider(ArrlContestProvider):
    """ARRL 222 MHz and Up Distance Contest."""

    key = "arrl-222"
    label = "ARRL 222 MHz and Up"
    store_name = "ARRL-222.xlsx"
    export_prefix = "ARRL-222"
    calls_prefix = "ARRL-222"
    contest = "222"


@register
class Arrl10GhzProvider(ArrlContestProvider):
    """ARRL 10 GHz and Up Contest."""

    key = "arrl-10g"
    label = "ARRL 10 GHz and Up"
    store_name = "ARRL-10G.xlsx"
    export_prefix = "ARRL-10G"
    calls_prefix = "ARRL-10G"
    contest = "10g"
