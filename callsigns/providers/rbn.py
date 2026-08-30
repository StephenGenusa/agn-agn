"""Reverse Beacon Network daily spot provider.

RBN publishes one zip per UTC day of every callsign its skimmer network
decoded. Ranked by spot count it is the broadest and cheapest activity signal
available: a single contest day yields around 38,000 unique CW callsigns, four
times what a quiet weekday produces.
"""

import datetime as dt
import logging
import pathlib
import re
from types import MappingProxyType

from callsigns.cache import FileCache
from callsigns.errors import ValidationError
from callsigns.providers import register
from callsigns.providers.base import Column, ModeSpec, Provider
from callsigns.providers.rbn_spots import (
    CallsignStats,
    accumulate_spots,
    read_zip_member,
    rows_from,
)

BASE_URL: str = "https://data.reversebeacon.net/rbn_history"

#: RBN has no history before this date; 2009-01-01 returns HTTP 404 while
#: 2010-01-01 succeeds, so this is a conservative floor rather than an exact
#: start. Dates after it that RBN lacks surface as an upstream 404.
MIN_DATE: dt.date = dt.date(2009, 1, 1)

#: Excel allows 1,048,576 rows per sheet, one of which is the header.
MAX_STORE_ROWS: int = 1_048_575

_PERIOD_RE = re.compile(r"^(\d{8})(?:-(\d{8}))?$")

_LOGGER = logging.getLogger(__name__)


def _as_date(token: str) -> dt.date:
    """Parse a ``YYYYMMDD`` token.

    Args:
        token: Eight-digit date token.

    Returns:
        The parsed date.

    Raises:
        ValidationError: The token is not a real calendar date.
    """
    try:
        return dt.datetime.strptime(token, "%Y%m%d").replace(tzinfo=dt.UTC).date()
    except ValueError:
        raise ValidationError(f"{token!r} is not a valid date") from None


def parse_period(period: str) -> tuple[dt.date, dt.date]:
    """Parse a period token into an inclusive date range.

    Args:
        period: ``YYYYMMDD`` or ``YYYYMMDD-YYYYMMDD``.

    Returns:
        The first and last dates, inclusive; both are the same for a single
        date.

    Raises:
        ValidationError: The token is malformed, names an impossible date, or
            describes a backwards range.
    """
    match = _PERIOD_RE.match(period)
    if match is None:
        raise ValidationError(
            f"{period!r} is not a period; expected YYYYMMDD or "
            f"YYYYMMDD-YYYYMMDD, for example 20251129"
        )
    start = _as_date(match.group(1))
    end = _as_date(match.group(2)) if match.group(2) else start
    if end < start:
        raise ValidationError(f"period {period!r} starts after it ends")
    return start, end


@register
class RbnCwProvider(Provider):
    """Per-callsign activity aggregated from Reverse Beacon Network spots."""

    key = "rbn-cw"
    label = "Reverse Beacon Network"
    store_name = "RBN-CW.xlsx"
    export_prefix = "RBN"
    calls_prefix = "RBN"
    callsign_key = "Callsign"
    bulk = True
    period_syntax = "YYYYMMDD or YYYYMMDD-YYYYMMDD"
    columns = (
        Column("Callsign", "Callsign", str),
        Column("Spots", "Spots", int),
        Column("Skimmers", "Skimmers", int),
        Column("Bands", "Bands", int),
        Column("Continent", "Continent", str),
        Column("Prefix", "Prefix", str),
        Column("FirstSeen", "First Seen", str),
        Column("LastSeen", "Last Seen", str),
        Column("SpeedMin", "WPM Min", int),
        Column("SpeedMedian", "WPM Median", int),
        Column("SpeedMax", "WPM Max", int),
        Column("DbMax", "Max dB", int),
    )
    #: Skimmers decode CW and digital modes only, so ``phone`` is absent
    #: rather than mapped to something approximate.
    modes = MappingProxyType(
        {
            "all": ModeSpec.all_modes(),
            "cw": ModeSpec.fetch_as("CW"),
            "data": ModeSpec.fetch_as("RTTY"),
        }
    )

    def __init__(self, cache: FileCache | None = None) -> None:
        """Initialise the provider.

        Args:
            cache: Download cache. Defaults to one rooted at
                ``data/raw/rbn-cw``.
        """
        self._cache = (
            cache
            if cache is not None
            else FileCache(pathlib.Path("data") / "raw" / self.key)
        )

    def use_cache(self, cache: FileCache) -> None:
        """Attach a download cache chosen by the caller.

        Args:
            cache: The cache to use for subsequent fetches.
        """
        self._cache = cache

    def periods(self) -> tuple[str, ...]:
        """Return an empty tuple: any calendar date is accepted."""
        return ()

    def default_periods(self) -> tuple[str, ...]:
        """Return an empty tuple: a date must be given explicitly.

        Guessing would silently download the wrong day.
        """
        return ()

    def period_label(self, period: str) -> str:
        """Return the period token itself as the sheet label.

        Args:
            period: A validated period token.

        Returns:
            The token unchanged; it is already short and unambiguous.
        """
        return period

    def validate_period(self, period: str) -> str:
        """Check the period's shape and that it is within RBN's history.

        Args:
            period: The value given to ``-y``.

        Returns:
            The period unchanged.

        Raises:
            ValidationError: The token is malformed, before RBN existed, or in
                the future.
        """
        start, end = parse_period(period)
        if start < MIN_DATE:
            raise ValidationError(
                f"RBN has no data before {MIN_DATE.isoformat()}; got {period!r}"
            )
        today = dt.datetime.now(dt.UTC).date()
        if end > today:
            raise ValidationError(f"period {period!r} is in the future")
        return period

    def source_url(self, period: str) -> str:
        """Return the URL of the first day in a period.

        Args:
            period: A validated period token.

        Returns:
            The daily zip URL; for a range this is the first day, which is
            what the metadata sheet records.
        """
        start, _end = parse_period(period)
        return self._url_for(start)

    @staticmethod
    def _url_for(day: dt.date) -> str:
        """Return the daily archive URL for one date.

        Args:
            day: The UTC date wanted.

        Returns:
            The zip URL.
        """
        return f"{BASE_URL}/{day.strftime('%Y%m%d')}.zip"

    def fetch(self, period: str, mode: str) -> list[dict[str, object]]:
        """Download, parse and aggregate every day in the period.

        Each day is streamed once into a single shared accumulator, so a range
        is aggregated over its raw spots rather than by combining per-day
        summaries. That keeps distinct skimmer and band counts, and the speed
        median, exact across the whole range.

        Args:
            period: A validated period token.
            mode: A key of :attr:`modes`.

        Returns:
            Rows sorted by spot count descending.

        Raises:
            UpstreamError: A download failed or a file was unreadable.
            ValidationError: The aggregate exceeds Excel's row limit.
        """
        start, end = parse_period(period)
        tx_mode = self.resolve_mode(mode).value or None

        stats: dict[str, CallsignStats] = {}
        day = start
        while day <= end:
            token = day.strftime("%Y%m%d")
            path = self._cache.fetch(f"{token}.zip", self._url_for(day))
            report = accumulate_spots(read_zip_member(path), tx_mode, stats)
            _LOGGER.info("%s: %s", token, report.summary())
            day += dt.timedelta(days=1)

        if len(stats) > MAX_STORE_ROWS:
            raise ValidationError(
                f"period {period!r} produced too many callsigns "
                f"({len(stats):,}) for one sheet; use a shorter range"
            )
        return rows_from(stats)
