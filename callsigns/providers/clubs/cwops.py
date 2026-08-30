"""CWops CW Open entrant lists.

CWops publishes who submitted a log rather than the logs themselves, so this
provider yields entrants only. That is still a participation signal: everyone
listed operated CW in a contest that year.
"""

import datetime as dt
import html
import re
from types import MappingProxyType

from callsigns.http import HttpClient
from callsigns.providers import register
from callsigns.providers.base import Column, ModeSpec, Provider

BASE_URL: str = "https://cwops.contesting.com/cwopenlogsrcvd.php"

FIRST_YEAR: int = 2012

_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_CALL_RE = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]*(?:/[A-Z0-9]+)?$")

#: CW operators conventionally write zero as a slashed O, and this page
#: encodes it as ``&#216;`` — ``K&#216;TG`` is K0TG. Left unhandled, every
#: such callsign would be dropped as containing an invalid character.
_SLASHED_ZERO = str.maketrans({"\u00d8": "0", "\u00f8": "0"})


def normalise_callsign(text: str) -> str:
    """Clean one cell into a callsign.

    Resolves HTML entities, converts the slashed zero CW operators favour into
    a digit, and drops surrounding whitespace.

    Args:
        text: Raw cell text, entities included.

    Returns:
        The normalised, uppercased callsign.
    """
    unescaped = html.unescape(text)
    return unescaped.translate(_SLASHED_ZERO).replace("\xa0", " ").strip().upper()


def parse_entrant_list(markup: str) -> list[str]:
    """Extract entrant callsigns from the logs-received page.

    Args:
        markup: The page markup.

    Returns:
        Callsigns in page order, uppercased and deduplicated.
    """
    seen: dict[str, None] = {}
    for cell in _CELL_RE.findall(markup):
        text = normalise_callsign(_TAG_RE.sub("", cell))
        if text and _CALL_RE.match(text):
            seen.setdefault(text, None)
    return list(seen)


@register
class CwOpenProvider(Provider):
    """CWops CW Open entrants."""

    key = "cwops-cwopen"
    label = "CWops CW Open"
    store_name = "CWops-CWOpen.xlsx"
    export_prefix = "CWOPS-CWOPEN"
    calls_prefix = "CWOPS-CWOPEN"
    callsign_key = "Callsign"
    columns = (
        Column("Callsign", "Callsign", str),
        Column("Entrant", "Entrant", str),
    )
    modes = MappingProxyType({"all": ModeSpec.all_modes(), "cw": ModeSpec.all_modes()})

    def __init__(self, client: HttpClient | None = None) -> None:
        """Initialise the provider.

        Args:
            client: HTTP client to use.
        """
        self._client = client if client is not None else HttpClient()

    def periods(self) -> tuple[str, ...]:
        """Return each year CW Open has run through the current UTC year."""
        current = dt.datetime.now(dt.UTC).year
        return tuple(str(year) for year in range(FIRST_YEAR, current + 1))

    def default_periods(self) -> tuple[str, ...]:
        """Return the current UTC year."""
        return (str(dt.datetime.now(dt.UTC).year),)

    def period_label(self, period: str) -> str:
        """Return the year as the sheet label.

        Args:
            period: A validated year token.

        Returns:
            The token unchanged.
        """
        return period

    def source_url(self, period: str) -> str:
        """Return the logs-received URL.

        The page shows the most recent year; older years are not separately
        addressable, so the period selects which sheet the result lands in.

        Args:
            period: A validated year token.

        Returns:
            The page URL.
        """
        del period
        return BASE_URL

    def fetch(self, period: str, mode: str) -> list[dict[str, object]]:
        """Fetch the entrant list.

        Args:
            period: A validated year token.
            mode: Ignored; CW Open is CW only.

        Returns:
            One row per entrant.

        Raises:
            UpstreamError: The page could not be retrieved.
        """
        del mode, period
        raw = self._client.get_bytes(BASE_URL)
        self.last_raw = raw
        text = raw.decode("utf-8", errors="replace")
        return [
            {"Callsign": call, "Entrant": "yes"} for call in parse_entrant_list(text)
        ]
