"""POTA hunter leaderboard provider."""

import datetime as dt
from types import MappingProxyType

from callsigns.errors import UpstreamError
from callsigns.http import HttpClient, RequestKind, parse_json
from callsigns.providers import register
from callsigns.providers.base import Column, ModeSpec, Provider

BASE_URL: str = "https://api.pota.app/leaderboard/hunter"
FIRST_YEAR: int = 2016


@register
class PotaHuntersProvider(Provider):
    """Parks On The Air hunter leaderboard.

    One request returns the whole leaderboard, pre-sorted by park count
    descending. The site pages the table client-side, so there is no
    pagination to follow.
    """

    key = "pota-hunters"
    label = "POTA Hunters"
    store_name = "POTA-Hunters.xlsx"
    export_prefix = "POTA"
    calls_prefix = "POTA"
    callsign_key = "activeCallsign"
    columns = (
        Column("activeCallsign", "Callsign", str),
        Column("numParks", "Parks", int),
        Column("numQSOs", "Total QSOs", int),
        Column("qsosCW", "Total CW", int),
        Column("qsosDATA", "Total Data", int),
        Column("qsosPHONE", "Total Phone", int),
    )
    modes = MappingProxyType(
        {
            "all": ModeSpec.all_modes(),
            "cw": ModeSpec.filter_on("qsosCW"),
            "phone": ModeSpec.filter_on("qsosPHONE"),
            "data": ModeSpec.filter_on("qsosDATA"),
        }
    )

    def __init__(self, client: HttpClient | None = None) -> None:
        """Initialise the provider.

        Args:
            client: HTTP client to use. Defaults to a new :class:`HttpClient`.
        """
        self._client = client if client is not None else HttpClient()

    def periods(self) -> tuple[str, ...]:
        """Return ``all`` followed by 2016 through the current UTC year."""
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
            The worksheet name for the period.
        """
        return "All-Time" if period == "all" else period

    def source_url(self, period: str) -> str:
        """Return the endpoint URL for a period.

        Args:
            period: A token from :meth:`periods`.

        Returns:
            The bare endpoint for ``all``, otherwise the endpoint with a
            ``year`` query parameter.
        """
        return BASE_URL if period == "all" else f"{BASE_URL}?year={period}"

    def fetch(self, period: str, mode: str) -> list[dict[str, object]]:
        """Fetch one period.

        The ``mode`` argument is accepted for interface compatibility and
        ignored: POTA returns per-mode counts as columns, so mode is applied
        later as a row filter rather than as a request parameter.

        Args:
            period: A token from :meth:`periods`.
            mode: Ignored.

        Returns:
            Rows containing only the declared columns, in upstream order.

        Raises:
            UpstreamError: The payload was not a list, or a row was missing
                declared columns.
        """
        del mode
        url = self.source_url(period)
        raw = self._client.get_bytes(url, kind=RequestKind.API)
        self.last_raw = raw
        payload = parse_json(url, raw)
        if not isinstance(payload, list):
            raise UpstreamError(
                f"{url} returned {type(payload).__name__}, expected a list"
            )
        keys = [column.key for column in self.columns]
        rows: list[dict[str, object]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                raise UpstreamError(f"{url} returned a non-object row: {entry!r}")
            missing = [key for key in keys if key not in entry]
            if missing:
                raise UpstreamError(
                    f"{url} row is missing declared columns: {', '.join(missing)}"
                )
            rows.append({key: entry[key] for key in keys})
        return rows
