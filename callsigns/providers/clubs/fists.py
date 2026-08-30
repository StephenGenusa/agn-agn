"""FISTS CW Club sprint results.

FISTS runs four sprints a year, each on a Saturday and a Sunday, and publishes
each as a plain-text table inside a ``<pre>`` block with ``<strong>`` category
headings.

Column counts differ between categories — the QRO table carries Bonus and
Multi where the Club table carries only Mults — so rows are parsed by locating
the run of integers rather than by fixed position. Within that run the layout
is stable: FISTS number, members worked, non-members worked, points, then
whatever the category adds, and the score last.
"""

import re
from types import MappingProxyType

from callsigns.errors import ValidationError
from callsigns.http import HttpClient
from callsigns.providers import register
from callsigns.providers.base import Column, ModeSpec, Provider

BASE_URL: str = "https://fistsna.org"

_PRE_RE = re.compile(r"<pre>(.*?)</pre>", re.S | re.I)
_STRONG_RE = re.compile(r"<strong>(.*?)</strong>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_LINK_RE = re.compile(r"spdata/((?:feb|may|aug|nov)(?:sat|sun)\d{2})\.html", re.I)
_PERIOD_RE = re.compile(r"^(feb|may|aug|nov)(sat|sun)(\d{2})$", re.I)
_DATE_RE = re.compile(r"Results\s+(\w+ \d{1,2},\s*\d{4})", re.I)

#: Call, name, state, then at least FISTS number, members, non-members,
#: points and score.
_MIN_INTS = 5


def _leading_ints(fields: list[str]) -> tuple[int, list[int]]:
    """Find where the numeric run starts and return it.

    Args:
        fields: Whitespace-split row fields.

    Returns:
        The index of the first integer field, and every integer from there on.
        The index is ``-1`` when the row carries no usable numeric run.
    """
    for start, field in enumerate(fields):
        if not field.lstrip("-").isdigit():
            continue
        values: list[int] = []
        for rest in fields[start:]:
            if not rest.lstrip("-").isdigit():
                return -1, []
            values.append(int(rest))
        return start, values
    return -1, []


def parse_sprint(html: str) -> list[dict[str, object]]:
    """Parse one FISTS sprint results page.

    Args:
        html: The results page markup.

    Returns:
        One row per entrant, ranked by score descending.
    """
    block = _PRE_RE.search(html)
    if block is None:
        return []
    date_match = _DATE_RE.search(_TAG_RE.sub(" ", html))
    sprint_date = date_match.group(1).strip() if date_match else ""

    rows: list[dict[str, object]] = []
    category = ""
    for raw in block.group(1).splitlines():
        strong = _STRONG_RE.search(raw)
        if strong is not None:
            category = _TAG_RE.sub("", strong.group(1)).strip()
            continue
        line = _TAG_RE.sub("", raw).strip()
        if not line or set(line) <= {"-"}:
            continue
        fields = line.split()
        if fields[0].lower() == "call":
            continue
        start, values = _leading_ints(fields)
        if start < 2 or len(values) < _MIN_INTS:
            continue
        member_qsos, non_member_qsos, points = values[1], values[2], values[3]
        rows.append(
            {
                "Callsign": fields[0].strip().upper(),
                "QSOs": member_qsos + non_member_qsos,
                "MemberQsos": member_qsos,
                "NonMemberQsos": non_member_qsos,
                "Points": points,
                "Score": values[-1],
                "FistsNumber": str(values[0]),
                "Name": " ".join(fields[1 : start - 1]),
                "State": fields[start - 1],
                "Category": category,
                "SprintDate": sprint_date,
            }
        )
    rows.sort(key=lambda r: (-int(str(r["Score"])), str(r["Callsign"])))
    return rows


def parse_archive(html: str) -> list[str]:
    """Extract available sprint tokens from the archive page.

    Args:
        html: The archive page markup.

    Returns:
        Tokens such as ``febsat25``, in page order, deduplicated.
    """
    seen: dict[str, None] = {}
    for token in _LINK_RE.findall(html):
        seen.setdefault(token.lower(), None)
    return list(seen)


@register
class FistsSprintProvider(Provider):
    """FISTS sprint entrant scores."""

    key = "fists-sprint"
    label = "FISTS Sprint"
    store_name = "FISTS-Sprint.xlsx"
    export_prefix = "FISTS"
    calls_prefix = "FISTS"
    callsign_key = "Callsign"
    period_syntax = "month, day and year, for example febsat25"
    columns = (
        Column("Callsign", "Callsign", str),
        Column("QSOs", "QSOs", int),
        Column("MemberQsos", "Member QSOs", int),
        Column("NonMemberQsos", "Non-Member QSOs", int),
        Column("Points", "Points", int),
        Column("Score", "Score", int),
        Column("FistsNumber", "FISTS Number", str),
        Column("Name", "Name", str),
        Column("State", "State", str),
        Column("Category", "Category", str),
        Column("SprintDate", "Sprint Date", str),
    )
    modes = MappingProxyType({"all": ModeSpec.all_modes(), "cw": ModeSpec.all_modes()})

    def __init__(self, client: HttpClient | None = None) -> None:
        """Initialise the provider.

        Args:
            client: HTTP client to use.
        """
        self._client = client if client is not None else HttpClient()

    def periods(self) -> tuple[str, ...]:
        """Return an empty tuple: sprint tokens are discovered, not enumerated."""
        return ()

    def default_periods(self) -> tuple[str, ...]:
        """Return an empty tuple: a sprint must be named explicitly."""
        return ()

    def period_label(self, period: str) -> str:
        """Return the sprint token as the sheet label.

        Args:
            period: A validated sprint token.

        Returns:
            The token, uppercased for readability.
        """
        return period.upper()

    def validate_period(self, period: str) -> str:
        """Check the period names a real sprint slot.

        Args:
            period: The value given to ``-y``.

        Returns:
            The period, lowercased to match the URL.

        Raises:
            ValidationError: The token does not name a sprint.
        """
        if not _PERIOD_RE.match(period):
            raise ValidationError(
                f"{period!r} is not a sprint; expected {self.period_syntax}"
            )
        return period.lower()

    def source_url(self, period: str) -> str:
        """Return the results URL for a sprint.

        Args:
            period: A validated sprint token.

        Returns:
            The results page URL.
        """
        return f"{BASE_URL}/spdata/{period.lower()}.html"

    def available_periods(self) -> list[str]:
        """Discover which sprints the archive currently lists.

        One request. Used to enumerate work, since sprint tokens span years.

        Returns:
            Sprint tokens in archive order.

        Raises:
            UpstreamError: The archive page could not be retrieved.
        """
        return parse_archive(self._client.get_text(f"{BASE_URL}/archives.php"))

    def fetch(self, period: str, mode: str) -> list[dict[str, object]]:
        """Fetch and parse one sprint.

        Args:
            period: A validated sprint token.
            mode: Ignored; FISTS sprints are CW only.

        Returns:
            Rows ranked by score descending.

        Raises:
            UpstreamError: The page could not be retrieved.
        """
        del mode
        raw = self._client.get_bytes(self.source_url(period))
        self.last_raw = raw
        return parse_sprint(raw.decode("utf-8", errors="replace"))
