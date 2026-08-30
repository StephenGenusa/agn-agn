"""Row filtering, row limiting, and callsign hygiene.

These are pure transformations shared by every exporter, so that ``-y``,
``-o`` and ``-d`` mean the same thing regardless of output format.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from callsigns.providers.base import ModeKind, ModeSpec

DTA_ALPHABET: frozenset[str] = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/")
MIN_CALLSIGN_LENGTH: int = 2


def filter_rows(
    rows: Sequence[Mapping[str, object]], spec: ModeSpec
) -> list[dict[str, object]]:
    """Apply a mode restriction to rows.

    Only ``FILTER`` specs restrict anything. ``ALL`` applies no restriction,
    and ``FETCH`` was already applied upstream when the data was requested.

    Args:
        rows: Rows in stored order.
        spec: The mode specification to apply.

    Returns:
        The surviving rows as fresh dictionaries, in their original order.
    """
    if spec.kind is not ModeKind.FILTER or spec.column is None:
        return [dict(row) for row in rows]
    column = spec.column
    kept: list[dict[str, object]] = []
    for row in rows:
        value = row.get(column)
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        if value > 0:
            kept.append(dict(row))
    return kept


def limit_rows(
    rows: Sequence[Mapping[str, object]], limit: int
) -> list[dict[str, object]]:
    """Truncate rows to at most ``limit`` entries.

    Args:
        rows: Rows in stored order.
        limit: Maximum number of rows; zero or negative means no limit.

    Returns:
        At most ``limit`` rows, in their original order.
    """
    materialised = [dict(row) for row in rows]
    if limit <= 0:
        return materialised
    return materialised[:limit]


@dataclass(frozen=True, slots=True)
class HygieneReport:
    """Counts of callsigns kept and dropped, by reason."""

    kept: int
    invalid_chars: int
    too_short: int
    duplicates: int

    @property
    def dropped(self) -> int:
        """Return the total number of callsigns dropped."""
        return self.invalid_chars + self.too_short + self.duplicates

    def summary(self) -> str:
        """Summarise the drops in one line.

        Returns:
            Text such as ``"dropped 3 callsigns: 1 invalid characters, ..."``,
            or the empty string when nothing was dropped.
        """
        if not self.dropped:
            return ""
        parts = []
        if self.invalid_chars:
            parts.append(f"{self.invalid_chars} invalid characters")
        if self.too_short:
            parts.append(f"{self.too_short} too short")
        if self.duplicates:
            parts.append(f"{self.duplicates} duplicates")
        return f"dropped {self.dropped} callsigns: {', '.join(parts)}"


def clean_callsigns(values: Iterable[object]) -> tuple[list[str], HygieneReport]:
    """Normalise callsigns for the callsign-only export formats.

    Uppercases, drops callsigns containing characters outside ``A-Z0-9/``,
    drops callsigns shorter than two characters (they contain no character
    pair and cannot be represented in MASTER.DTA), and deduplicates while
    preserving first occurrence.

    Args:
        values: Raw callsign values, which need not be strings.

    Returns:
        A tuple of the cleaned callsigns and a report of what was dropped.
    """
    kept: list[str] = []
    seen: set[str] = set()
    invalid_chars = 0
    too_short = 0
    duplicates = 0
    for value in values:
        call = str(value).strip().upper() if value is not None else ""
        if len(call) < MIN_CALLSIGN_LENGTH:
            too_short += 1
            continue
        if not set(call) <= DTA_ALPHABET:
            invalid_chars += 1
            continue
        if call in seen:
            duplicates += 1
            continue
        seen.add(call)
        kept.append(call)
    return kept, HygieneReport(
        kept=len(kept),
        invalid_chars=invalid_chars,
        too_short=too_short,
        duplicates=duplicates,
    )
