"""Summits On The Air honour-roll providers.

Two rolls share one endpoint shape, one period vocabulary and one mode
vocabulary, so a base class holds all of that and the subclasses declare only
their identity and their columns — which have nothing in common beyond the
callsign.

Personal data: these rolls return ``UserID`` and ``Username``, and ``Username``
holds real names and email addresses. Both are stored and exported as declared,
so the store workbooks and any ``xlsx`` export contain personal data. The
``scp``, ``dta`` and ``lst`` exports are callsign-only and carry none of it.
"""

import datetime as dt
from types import MappingProxyType
from typing import ClassVar

from callsigns.http import HttpClient, RequestKind, parse_json
from callsigns.providers import register
from callsigns.providers.base import Column, ModeSpec, Provider
from callsigns.providers.sota_rows import coerce_rows

BASE_URL: str = "https://api-db2.sota.org.uk/rolls"

#: 2002 is the earliest year the API accepts; 2001 answers HTTP 400 with the
#: plain-text body ``Invalid date``.
FIRST_YEAR: int = 2002

#: All associations, and no band restriction. Both are out of scope.
ALL_ASSOCIATIONS: str = "0"
ALL_BANDS: str = "all"

#: CLI mode token to the segment the API expects. ``phone`` maps to SSB alone
#: rather than the union of SSB, FM, AM and DV: those are separate downloads
#: whose point totals cannot be combined.
MODE_SEGMENTS: dict[str, str] = {
    "all": "all",
    "cw": "CW",
    "phone": "SSB",
    "data": "DATA",
    "AM": "AM",
    "DV": "DV",
    "FM": "FM",
    "OTHER": "OTHER",
    "SSB": "SSB",
}

_MODES = MappingProxyType(
    {
        token: (ModeSpec.all_modes() if token == "all" else ModeSpec.fetch_as(segment))
        for token, segment in MODE_SEGMENTS.items()
    }
)


class SotaRollProvider(Provider):
    """Shared behaviour for the activator and chaser honour rolls."""

    #: URL segment naming the roll: ``activator`` or ``chaser``.
    roll: ClassVar[str]

    callsign_key = "Callsign"
    modes = _MODES

    def __init__(self, client: HttpClient | None = None) -> None:
        """Initialise the provider.

        Args:
            client: HTTP client to use. Defaults to a new :class:`HttpClient`.
        """
        self._client = client if client is not None else HttpClient()

    def periods(self) -> tuple[str, ...]:
        """Return ``all`` followed by 2002 through the current UTC year.

        Bounding the range here is what makes the inherited
        :meth:`Provider.validate_period` sufficient: the API answers HTTP 400
        for years before 2002 and HTTP 200 with an empty list for years in the
        future, so both must be rejected locally rather than reaching it.

        Returns:
            Every accepted period token.
        """
        current = dt.datetime.now(dt.UTC).year
        return ("all", *(str(year) for year in range(FIRST_YEAR, current + 1)))

    def default_periods(self) -> tuple[str, ...]:
        """Return the current UTC year and ``all``."""
        return (str(dt.datetime.now(dt.UTC).year), "all")

    def period_label(self, period: str) -> str:
        """Return ``All-Time`` for ``all``, otherwise the year itself.

        Args:
            period: A token from :meth:`periods`.

        Returns:
            The worksheet label for the period.
        """
        return "All-Time" if period == "all" else period

    def url_for(self, period: str, mode: str) -> str:
        """Build the roll URL for a period and mode.

        Args:
            period: A token from :meth:`periods`.
            mode: A key of :attr:`modes`.

        Returns:
            The fully qualified request URL.

        Raises:
            ValidationError: The mode is not supported. Checked here because
                the API answers HTTP 200 with an empty list for an unknown
                mode, so a typo would otherwise produce an empty sheet.
        """
        self.resolve_mode(mode)
        year = "0" if period == "all" else period
        return (
            f"{BASE_URL}/{self.roll}/{ALL_ASSOCIATIONS}/{year}/"
            f"{ALL_BANDS}/{MODE_SEGMENTS[mode]}"
        )

    def source_url(self, period: str) -> str:
        """Return the all-mode URL for a period, for the metadata sheet.

        Args:
            period: A token from :meth:`periods`.

        Returns:
            The request URL with no mode restriction.
        """
        return self.url_for(period, "all")

    def fetch(self, period: str, mode: str) -> list[dict[str, object]]:
        """Fetch one period and mode.

        Args:
            period: A token from :meth:`periods`.
            mode: A key of :attr:`modes`; it becomes a URL segment, because a
                different mode is a different download rather than a subset.

        Returns:
            Rows containing only the declared columns, in upstream order.

        Raises:
            UpstreamError: The response was not a JSON list of well-formed
                rows.
            ValidationError: The mode is not supported.
        """
        url = self.url_for(period, mode)
        raw = self._client.get_bytes(url, kind=RequestKind.API)
        self.last_raw = raw
        rows, _dropped = coerce_rows(
            parse_json(url, raw), self.columns, self.callsign_key, url
        )
        return rows


@register
class SotaActivatorProvider(SotaRollProvider):
    """SOTA activator honour roll: points scored activating summits."""

    key = "sota-activator"
    label = "SOTA Activators"
    store_name = "SOTA-Activator.xlsx"
    export_prefix = "SOTA-Activator"
    calls_prefix = "SOTA-Activator"
    roll = "activator"
    columns = (
        Column("Callsign", "Callsign", str),
        Column("Position", "Position", str),
        Column("Summits", "Summits", int),
        Column("Points", "Points", int),
        Column("BonusPoints", "Bonus Points", int),
        Column("totalPoints", "Total Points", int),
        Column("Average", "Average", float),
        Column("UserID", "User ID", int),
        Column("Username", "Username", str),
    )


@register
class SotaChaserProvider(SotaRollProvider):
    """SOTA chaser honour roll: points scored working activators."""

    key = "sota-chaser"
    label = "SOTA Chasers"
    store_name = "SOTA-Chaser.xlsx"
    export_prefix = "SOTA-Chaser"
    calls_prefix = "SOTA-Chaser"
    roll = "chaser"
    columns = (
        Column("Callsign", "Callsign", str),
        Column("Position", "Position", str),
        Column("stationsWorked", "Stations Worked", int),
        Column("Points", "Points", int),
        Column("Average", "Average", float),
        Column("UserID", "User ID", int),
        Column("Username", "Username", str),
    )
