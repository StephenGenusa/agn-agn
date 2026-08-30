"""Streaming parse and aggregation of Reverse Beacon Network spot files.

A single contest day is roughly six million rows and 400 MB uncompressed,
against Excel's limit of 1,048,576 rows per sheet. The file is therefore never
held in memory and never stored row-by-row: it is streamed once and reduced to
one row per callsign.
"""

import csv
import logging
import pathlib
import statistics
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field

from callsigns.errors import UpstreamError

SPOT_COLUMNS: tuple[str, ...] = (
    "callsign",
    "de_pfx",
    "de_cont",
    "freq",
    "band",
    "dx",
    "dx_pfx",
    "dx_cont",
    "mode",
    "db",
    "date",
    "speed",
    "tx_mode",
)

#: ``mode`` is the spot type, not the modulation. Only these represent a human
#: operator; BEACON and NCDXF B are unattended transmitters.
OPERATOR_SPOT_TYPES: frozenset[str] = frozenset({"CQ", "DX"})

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParseReport:
    """What a parse pass saw."""

    rows: int
    kept: int
    ragged: int
    wrong_mode: int

    def summary(self) -> str:
        """Summarise the pass in one line.

        Returns:
            Text naming the totals, for progress output.
        """
        return (
            f"{self.rows:,} rows, {self.kept:,} kept, "
            f"{self.wrong_mode:,} other modulation, {self.ragged:,} malformed"
        )


@dataclass(slots=True)
class CallsignStats:
    """Running totals for one spotted callsign."""

    callsign: str
    spots: int = 0
    skimmers: set[str] = field(default_factory=set)
    bands: set[str] = field(default_factory=set)
    continent: str = ""
    prefix: str = ""
    first_seen: str = ""
    last_seen: str = ""
    speeds: list[int] = field(default_factory=list)
    db_max: int = 0

    def add(
        self,
        *,
        skimmer: str,
        band: str,
        continent: str,
        prefix: str,
        when: str,
        speed: int | None,
        db: int | None,
    ) -> None:
        """Fold one spot into the running totals.

        Args:
            skimmer: Callsign of the station that heard the spot.
            band: Band label such as ``40m``.
            continent: Continent of the spotted station.
            prefix: DXCC prefix of the spotted station.
            when: Spot timestamp, ``YYYY-MM-DD HH:MM:SS``.
            speed: Transmit speed in WPM, or ``None`` if unparseable.
            db: Signal strength, or ``None`` if unparseable.
        """
        self.spots += 1
        self.skimmers.add(skimmer)
        self.bands.add(band)
        if continent and not self.continent:
            self.continent = continent
        if prefix and not self.prefix:
            self.prefix = prefix
        if when:
            if not self.first_seen or when < self.first_seen:
                self.first_seen = when
            if when > self.last_seen:
                self.last_seen = when
        if speed is not None:
            self.speeds.append(speed)
        if db is not None:
            self.db_max = max(self.db_max, db)

    def to_row(self) -> dict[str, object]:
        """Render the totals as a store row.

        Returns:
            One row keyed by the provider's column keys.
        """
        return {
            "Callsign": self.callsign,
            "Spots": self.spots,
            "Skimmers": len(self.skimmers),
            "Bands": len(self.bands),
            "Continent": self.continent,
            "Prefix": self.prefix,
            "FirstSeen": self.first_seen,
            "LastSeen": self.last_seen,
            "SpeedMin": min(self.speeds) if self.speeds else 0,
            "SpeedMedian": int(statistics.median(self.speeds)) if self.speeds else 0,
            "SpeedMax": max(self.speeds) if self.speeds else 0,
            "DbMax": self.db_max,
        }


def _as_int(value: str) -> int | None:
    """Parse an integer field, tolerating blanks and junk.

    Args:
        value: Raw field text.

    Returns:
        The integer, or ``None`` if it could not be parsed.
    """
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def read_zip_member(path: pathlib.Path) -> Iterator[str]:
    """Yield decoded lines from the single CSV inside an RBN daily zip.

    Args:
        path: Path to the downloaded zip.

    Yields:
        Lines of the contained CSV, newline stripped.

    Raises:
        UpstreamError: The file is not a zip, or contains no members.
    """
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpstreamError(f"{path} is not a valid zip: {exc}") from exc
    with archive:
        names = archive.namelist()
        if not names:
            raise UpstreamError(f"{path} contains no files")
        with archive.open(names[0]) as handle:
            for raw in handle:
                yield raw.decode("utf-8", errors="replace").rstrip("\r\n")


def accumulate_spots(
    lines: Iterable[str],
    tx_mode: str | None,
    stats: dict[str, CallsignStats],
) -> ParseReport:
    """Fold a stream of spot rows into a per-callsign accumulator.

    Beacon spots are excluded: ``mode`` carries the spot type, and only ``CQ``
    and ``DX`` represent a human operator.

    Taking the accumulator as an argument is what makes multi-day ranges exact.
    Every day's raw spots land in the same :class:`CallsignStats`, so distinct
    skimmer and band counts and the speed median are computed over the whole
    range rather than being re-derived from per-day summaries, which would have
    thrown away the identities needed to deduplicate.

    Args:
        lines: Spot file lines, starting with the header row.
        tx_mode: Modulation to keep, such as ``CW``; ``None`` keeps every
            modulation.
        stats: Accumulator keyed by callsign, updated in place.

    Returns:
        A report of what this pass saw.

    Raises:
        UpstreamError: The header row is missing or does not match the
            expected columns.
    """
    reader = csv.reader(lines)
    try:
        header = next(reader)
    except StopIteration:
        raise UpstreamError("spot file is empty: no header row") from None
    if tuple(header) != SPOT_COLUMNS:
        raise UpstreamError(
            f"unexpected spot file header: {','.join(header)}; "
            f"expected {','.join(SPOT_COLUMNS)}"
        )

    width = len(SPOT_COLUMNS)
    rows = ragged = wrong_mode = kept = 0

    for record in reader:
        rows += 1
        if len(record) != width:
            ragged += 1
            continue
        row = dict(zip(SPOT_COLUMNS, record, strict=True))
        if tx_mode is not None and row["tx_mode"] != tx_mode:
            wrong_mode += 1
            continue
        if row["mode"] not in OPERATOR_SPOT_TYPES:
            continue
        call = row["dx"].strip().upper()
        if not call:
            continue
        kept += 1
        entry = stats.get(call)
        if entry is None:
            entry = CallsignStats(callsign=call)
            stats[call] = entry
        entry.add(
            skimmer=row["callsign"].strip().upper(),
            band=row["band"],
            continent=row["dx_cont"],
            prefix=row["dx_pfx"],
            when=row["date"],
            speed=_as_int(row["speed"]),
            db=_as_int(row["db"]),
        )

    report = ParseReport(rows=rows, kept=kept, ragged=ragged, wrong_mode=wrong_mode)
    _LOGGER.info("parsed spots: %s", report.summary())
    return report


def rows_from(stats: Mapping[str, CallsignStats]) -> list[dict[str, object]]:
    """Render an accumulator as store rows, ranked by activity.

    Args:
        stats: Accumulator keyed by callsign.

    Returns:
        Rows sorted by spot count descending, ties broken by callsign.
    """
    ordered = sorted(stats.values(), key=lambda s: (-s.spots, s.callsign))
    return [entry.to_row() for entry in ordered]


def aggregate_spots(
    lines: Iterable[str], tx_mode: str | None
) -> tuple[list[dict[str, object]], ParseReport]:
    """Reduce one spot file to one row per callsign.

    Convenience wrapper over :func:`accumulate_spots` for the single-file case.

    Args:
        lines: Spot file lines, starting with the header row.
        tx_mode: Modulation to keep, such as ``CW``; ``None`` keeps every
            modulation.

    Returns:
        A tuple of the ranked rows and a report of what the pass saw.

    Raises:
        UpstreamError: The header row is missing or does not match the
            expected columns.
    """
    stats: dict[str, CallsignStats] = {}
    report = accumulate_spots(lines, tx_mode, stats)
    return rows_from(stats), report
