"""NAQCC monthly sprint scoreboards.

The North American QRP CW Club publishes each sprint's results as a
fixed-width table inside a ``<pre>`` block, with category and division
headings interleaved as ``<span>`` lines. Both headings are carried onto every
row: they say how the operator was working, which is real activity metadata.
"""

import datetime as dt
import re
from types import MappingProxyType

from callsigns.errors import ValidationError
from callsigns.http import HttpClient
from callsigns.providers import register
from callsigns.providers.base import Column, ModeSpec, Provider

BASE_URL: str = "http://naqcc.info/scoreboard.php"

#: Lists every sprint the scoreboard still holds. Older sprints are dropped
#: from the site — asking for one answers "file ... doesn't exist" — so the
#: available months are discovered rather than generated.
INDEX_URL: str = "http://naqcc.info/sprint_dates.html"

_PRE_RE = re.compile(r"<pre>(.*?)</pre>", re.S | re.I)
_SPAN_RE = re.compile(r"<span[^>]*>(.*?)</span>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_PERIOD_RE = re.compile(r"^(\d{4})(\d{2})$")
_DIVISION_RE = re.compile(r"^[A-Z0-9]{1,3} Division$", re.I)
_INDEX_RE = re.compile(r"scoreboard\.php\?sprint_name=(\d{6})")

#: The header row of each category table, skipped rather than parsed.
_HEADER_FIRST_TOKEN = "call"

#: Data rows carry at least this many whitespace-separated fields before the
#: free-text antenna description.
_MIN_FIELDS = 8


def parse_sprint_index(html: str) -> list[str]:
    """Extract the sprint months the site still publishes.

    Args:
        html: The sprint-dates page markup.

    Returns:
        ``YYYYMM`` tokens in page order, deduplicated.
    """
    return list(dict.fromkeys(_INDEX_RE.findall(html)))


def parse_scoreboard(html: str) -> list[dict[str, object]]:
    """Parse one sprint scoreboard.

    Args:
        html: The scoreboard page markup.

    Returns:
        One row per entrant, ranked by final score descending.
    """
    block = _PRE_RE.search(html)
    if block is None:
        return []

    rows: list[dict[str, object]] = []
    category = ""
    division = ""
    for raw in block.group(1).splitlines():
        span = _SPAN_RE.search(raw)
        if span is not None:
            heading = _TAG_RE.sub("", span.group(1)).strip()
            if _DIVISION_RE.match(heading):
                division = heading
            else:
                category = heading
            continue
        line = _TAG_RE.sub("", raw).strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) < _MIN_FIELDS:
            continue
        if fields[0].lower() == _HEADER_FIRST_TOKEN:
            continue
        try:
            qsos = int(fields[1])
            members = int(fields[2])
            score = int(fields[7])
        except ValueError:
            continue
        rows.append(
            {
                "Callsign": fields[0].strip().upper(),
                "QSOs": qsos,
                "Members": members,
                "Score": score,
                "Category": category,
                "Division": division,
            }
        )
    rows.sort(key=lambda r: (-int(str(r["Score"])), str(r["Callsign"])))
    return rows


@register
class NaqccSprintProvider(Provider):
    """NAQCC monthly CW sprint results."""

    key = "naqcc-sprint"
    label = "NAQCC Sprint"
    store_name = "NAQCC-Sprint.xlsx"
    export_prefix = "NAQCC"
    calls_prefix = "NAQCC"
    callsign_key = "Callsign"
    period_syntax = "YYYYMM, for example 202511"
    columns = (
        Column("Callsign", "Callsign", str),
        Column("QSOs", "QSOs", int),
        Column("Members", "Members Worked", int),
        Column("Score", "Score", int),
        Column("Category", "Category", str),
        Column("Division", "Division", str),
    )
    modes = MappingProxyType({"all": ModeSpec.all_modes(), "cw": ModeSpec.all_modes()})

    def __init__(self, client: HttpClient | None = None) -> None:
        """Initialise the provider.

        Args:
            client: HTTP client to use.
        """
        self._client = client if client is not None else HttpClient()

    def periods(self) -> tuple[str, ...]:
        """Return an empty tuple: any month is accepted."""
        return ()

    def default_periods(self) -> tuple[str, ...]:
        """Return an empty tuple: a month must be given explicitly."""
        return ()

    def period_label(self, period: str) -> str:
        """Return the sprint month as the sheet label.

        Args:
            period: A validated ``YYYYMM`` token.

        Returns:
            The token unchanged.
        """
        return period

    def validate_period(self, period: str) -> str:
        """Check the period is a real month, not in the future.

        Args:
            period: The value given to ``-y``.

        Returns:
            The period unchanged.

        Raises:
            ValidationError: The token is malformed or in the future.
        """
        match = _PERIOD_RE.match(period)
        if match is None:
            raise ValidationError(
                f"{period!r} is not a sprint month; expected {self.period_syntax}"
            )
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise ValidationError(f"{period!r} has no month {month:02d}")
        now = dt.datetime.now(dt.UTC)
        if (year, month) > (now.year, now.month):
            raise ValidationError(f"sprint {period!r} is in the future")
        return period

    def available_periods(self) -> list[str]:
        """Discover which sprints the site currently holds.

        One request. Generating months instead would spend most of the
        harvest on sprints that were dropped years ago.

        Returns:
            ``YYYYMM`` tokens, newest first.

        Raises:
            UpstreamError: The index page could not be retrieved.
        """
        return parse_sprint_index(self._client.get_text(INDEX_URL))

    def source_url(self, period: str) -> str:
        """Return the scoreboard URL for a sprint month.

        Args:
            period: A validated period token.

        Returns:
            The scoreboard URL.
        """
        return f"{BASE_URL}?sprint_name={period}"

    def fetch(self, period: str, mode: str) -> list[dict[str, object]]:
        """Fetch and parse one sprint scoreboard.

        Args:
            period: A validated period token.
            mode: Ignored; NAQCC sprints are CW only.

        Returns:
            Rows ranked by score descending.

        Raises:
            UpstreamError: The page could not be retrieved.
        """
        del mode
        url = self.source_url(period)
        raw = self._client.get_bytes(url)
        self.last_raw = raw
        return parse_scoreboard(raw.decode("utf-8", errors="replace"))
