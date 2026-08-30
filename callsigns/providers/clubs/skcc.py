"""SKCC Weekend Sprintathon results.

The Straight Key Century Club publishes each WES as an HTML table of entrants
with QSO counts and scores. Results pages are addressed by an opaque
``results_id`` rather than by date, so the event date is captured from the page
and carried on every row.

Pacing: ``skccgroup.com`` names two ham-radio crawlers in its robots.txt block
list, so it has been troubled by exactly this sort of traffic before. It is
assigned the slow policy in :mod:`callsigns.pacing` — roughly one request every
twenty to forty seconds, slower than a person clicking through by hand.

Personal data: the results table carries operator first names, which are stored
and exported like any other column. The ``scp``, ``dta`` and ``lst`` exports
are callsign-only and carry none of it.
"""

import re
from types import MappingProxyType

from callsigns.errors import ValidationError
from callsigns.http import HttpClient
from callsigns.providers import register
from callsigns.providers.base import Column, ModeSpec, Provider

BASE_URL: str = (
    "https://www.skccgroup.com/operating_activities/weekend_sprintathon/"
    "submit-display.php"
)

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"Results for WES:\s*([^<]+)", re.I)
_ID_RE = re.compile(r"submit-display\.php\?results_id=(\d+)")
_PERIOD_RE = re.compile(r"^\d+$")

#: Rank, Callsign, Name, SKCC #, SPC, QSOs, SPCs, S/T/C, Bonus, Score.
_EXPECTED_CELLS = 10


def _as_int(text: str) -> int | None:
    """Parse an integer that may carry thousands separators.

    Args:
        text: Cell text such as ``"10,095"``.

    Returns:
        The integer, or ``None`` when it cannot be parsed.
    """
    try:
        return int(text.replace(",", "").strip())
    except TypeError, ValueError:
        return None


def parse_results_index(html: str) -> list[str]:
    """Extract the available ``results_id`` values from the portal index.

    Args:
        html: The portal page markup.

    Returns:
        Result ids in page order, deduplicated.
    """
    seen: dict[str, None] = {}
    for found in _ID_RE.findall(html):
        seen.setdefault(found, None)
    return list(seen)


def parse_wes_results(html: str) -> list[dict[str, object]]:
    """Parse one Weekend Sprintathon results table.

    Args:
        html: The results page markup.

    Returns:
        One row per entrant, in the page's own rank order.
    """
    date_match = _DATE_RE.search(html)
    wes_date = date_match.group(1).strip() if date_match else ""

    rows: list[dict[str, object]] = []
    for raw in _ROW_RE.findall(html):
        cells = [_TAG_RE.sub("", c).strip() for c in _CELL_RE.findall(raw)]
        if len(cells) < _EXPECTED_CELLS:
            continue
        callsign = cells[1].strip().upper()
        qsos = _as_int(cells[5])
        score = _as_int(cells[9])
        if not callsign or qsos is None or score is None:
            continue
        rows.append(
            {
                "Callsign": callsign,
                "QSOs": qsos,
                "Score": score,
                "SkccNumber": cells[3],
                "Spc": cells[4],
                "Name": cells[2],
                "WesDate": wes_date,
            }
        )
    return rows


@register
class SkccWesProvider(Provider):
    """SKCC Weekend Sprintathon entrant scores."""

    key = "skcc-wes"
    label = "SKCC Weekend Sprintathon"
    store_name = "SKCC-WES.xlsx"
    export_prefix = "SKCC-WES"
    calls_prefix = "SKCC-WES"
    callsign_key = "Callsign"
    period_syntax = "a WES results id, for example 105"
    columns = (
        Column("Callsign", "Callsign", str),
        Column("QSOs", "QSOs", int),
        Column("Score", "Score", int),
        Column("SkccNumber", "SKCC Number", str),
        Column("Spc", "State/Province/Country", str),
        Column("Name", "Name", str),
        Column("WesDate", "WES Date", str),
    )
    modes = MappingProxyType({"all": ModeSpec.all_modes(), "cw": ModeSpec.all_modes()})

    def __init__(self, client: HttpClient | None = None) -> None:
        """Initialise the provider.

        Args:
            client: HTTP client to use.
        """
        self._client = client if client is not None else HttpClient()

    def periods(self) -> tuple[str, ...]:
        """Return an empty tuple: result ids are discovered, not enumerated."""
        return ()

    def default_periods(self) -> tuple[str, ...]:
        """Return an empty tuple: a result id must be given explicitly."""
        return ()

    def period_label(self, period: str) -> str:
        """Return a sheet label for a result id.

        The event date is not known without fetching, so it travels on every
        row as ``WesDate`` instead of in the sheet name.

        Args:
            period: A validated result id.

        Returns:
            A label such as ``WES-105``.
        """
        return f"WES-{period}"

    def validate_period(self, period: str) -> str:
        """Check the period is a result id.

        Args:
            period: The value given to ``-y``.

        Returns:
            The period unchanged.

        Raises:
            ValidationError: The token is not a positive integer.
        """
        if not _PERIOD_RE.match(period):
            raise ValidationError(
                f"{period!r} is not a result id; expected {self.period_syntax}"
            )
        return period

    def source_url(self, period: str) -> str:
        """Return the results URL for a result id.

        Args:
            period: A validated result id.

        Returns:
            The results page URL.
        """
        return f"{BASE_URL}?results_id={period}"

    def available_periods(self) -> list[str]:
        """Discover which result ids the portal currently lists.

        One request. Used by the harvest command to enumerate work, since
        result ids cannot be guessed.

        Returns:
            Result ids in portal order.

        Raises:
            UpstreamError: The portal page could not be retrieved.
        """
        return parse_results_index(self._client.get_text(BASE_URL))

    def fetch(self, period: str, mode: str) -> list[dict[str, object]]:
        """Fetch and parse one Weekend Sprintathon.

        Args:
            period: A validated result id.
            mode: Ignored; the WES is CW only.

        Returns:
            Rows in the page's rank order.

        Raises:
            UpstreamError: The page could not be retrieved.
        """
        del mode
        url = self.source_url(period)
        raw = self._client.get_bytes(url)
        self.last_raw = raw
        return parse_wes_results(raw.decode("utf-8", errors="replace"))
