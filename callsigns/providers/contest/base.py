"""Shared behaviour for contest log providers.

Every contest works the same way once the logs are in hand: parse each one,
count how often each callsign was worked, and rank by that count. Only the
listing differs, so that is the single abstract method.
"""

import abc
import datetime as dt
import logging
import pathlib
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar

from callsigns.cache import DEFAULT_JOBS, FileCache
from callsigns.providers.base import Column, ModeSpec, Provider
from callsigns.providers.contest.cabrillo import parse_log

#: How many logs to download by default, largest first where size is known.
#: Far past the point where the ranking stabilises — 24 logs already gave a
#: 464/500 top-500 overlap against 16 — while costing about 2% of the field.
DEFAULT_TOP_LOGS: int = 200

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LogRef:
    """One published log: who submitted it, where it is, and how big."""

    callsign: str
    url: str
    size: int | None = None


@dataclass(slots=True)
class WorkedStats:
    """Running totals for one worked callsign."""

    callsign: str
    times_worked: int = 0
    logs: set[str] = field(default_factory=set)
    bands: set[str] = field(default_factory=set)
    first_seen: str = ""
    last_seen: str = ""
    entrant: bool = False

    def add(self, *, log: str, band: str, when: str) -> None:
        """Fold one contact into the totals.

        Args:
            log: Callsign of the entrant whose log recorded the contact.
            band: Band label, possibly empty.
            when: Contact timestamp.
        """
        self.times_worked += 1
        self.logs.add(log)
        if band:
            self.bands.add(band)
        if when:
            if not self.first_seen or when < self.first_seen:
                self.first_seen = when
            if when > self.last_seen:
                self.last_seen = when

    def to_row(self) -> dict[str, object]:
        """Render the totals as a store row.

        Returns:
            One row keyed by the provider's column keys.
        """
        return {
            "Callsign": self.callsign,
            "TimesWorked": self.times_worked,
            "LogsSeen": len(self.logs),
            "Bands": len(self.bands),
            "FirstSeen": self.first_seen,
            "LastSeen": self.last_seen,
            "Entrant": "yes" if self.entrant else "no",
        }


class ContestLogProvider(Provider):
    """Per-callsign QSO counts mined from one contest's published logs."""

    #: Earliest year this sponsor publishes logs for.
    first_year: ClassVar[int]

    callsign_key = "Callsign"
    bulk = True
    columns = (
        Column("Callsign", "Callsign", str),
        Column("TimesWorked", "Times Worked", int),
        Column("LogsSeen", "Logs Seen", int),
        Column("Bands", "Bands", int),
        Column("FirstSeen", "First Seen", str),
        Column("LastSeen", "Last Seen", str),
        Column("Entrant", "Entrant", str),
    )
    #: The contest fixes the mode, so ``cw`` and ``all`` are the same dataset.
    #: Declaring both means ``-o cw`` works rather than being rejected.
    modes = MappingProxyType({"all": ModeSpec.all_modes(), "cw": ModeSpec.all_modes()})

    def __init__(
        self,
        cache: FileCache | None = None,
        *,
        top_logs: int = DEFAULT_TOP_LOGS,
        jobs: int = DEFAULT_JOBS,
    ) -> None:
        """Initialise the provider.

        Args:
            cache: Download cache. Defaults to ``data/raw/<key>``.
            top_logs: Maximum logs to download; ``0`` means every one.
            jobs: Maximum concurrent downloads.
        """
        self._cache = (
            cache
            if cache is not None
            else FileCache(pathlib.Path("data") / "raw" / self.key)
        )
        self.top_logs = top_logs
        self.jobs = jobs

    def use_cache(self, cache: FileCache) -> None:
        """Attach a download cache chosen by the caller.

        Args:
            cache: The cache to use for subsequent fetches.
        """
        self._cache = cache

    def periods(self) -> tuple[str, ...]:
        """Return every contest year this sponsor publishes.

        Returns:
            Year tokens from :attr:`first_year` through the current UTC year.
            There is no ``all``: a contest is an event, not a running total.
        """
        current = dt.datetime.now(dt.UTC).year
        return tuple(str(year) for year in range(self.first_year, current + 1))

    def default_periods(self) -> tuple[str, ...]:
        """Return the current UTC year."""
        return (str(dt.datetime.now(dt.UTC).year),)

    def period_label(self, period: str) -> str:
        """Return the year itself as the sheet label.

        Args:
            period: A validated period token.

        Returns:
            The token unchanged.
        """
        return period

    @abc.abstractmethod
    def list_logs(self, period: str) -> list[LogRef]:
        """Return every published log for a contest year.

        The one thing that differs between sponsors, so the one abstract
        method. Declaring it abstract means a registration that forgets it
        fails at import time rather than mid-download.

        Args:
            period: A validated period token.

        Returns:
            One reference per entrant, with sizes where the sponsor exposes
            them.

        Raises:
            UpstreamError: The listing could not be retrieved or parsed.
        """

    def _selected(self, refs: list[LogRef]) -> list[LogRef]:
        """Choose which logs to download.

        Sorted largest first where sizes are known, because log size tracks QSO
        count and the biggest logs saturate the ranking fastest. Sponsors that
        expose no size are taken in listing order.

        Args:
            refs: Every published log.

        Returns:
            The subset to download.
        """
        if any(ref.size is not None for ref in refs):
            refs = sorted(refs, key=lambda r: -(r.size or 0))
        if self.top_logs > 0:
            return refs[: self.top_logs]
        return refs

    def fetch(self, period: str, mode: str) -> list[dict[str, object]]:
        """Download the selected logs and aggregate the callsigns worked.

        Args:
            period: A validated period token.
            mode: Accepted for interface compatibility; the contest fixes the
                mode, so it does not change the dataset.

        Returns:
            Rows ranked by times worked, descending.

        Raises:
            UpstreamError: A listing or log download failed.
        """
        del mode
        refs = self.list_logs(period)
        selected = self._selected(refs)
        _LOGGER.info(
            "%s %s: %d logs published, downloading %d",
            self.key,
            period,
            len(refs),
            len(selected),
        )

        results = self._cache.fetch_many(
            [(f"{period}/{ref.callsign}.log", ref.url) for ref in selected],
            jobs=self.jobs,
        )

        stats: dict[str, WorkedStats] = {}
        for (_key, path), ref in zip(results, selected, strict=True):
            text = path.read_text(encoding="utf-8", errors="replace")
            log_owner, qsos = parse_log(text)
            owner = log_owner or ref.callsign.upper()
            for qso in qsos:
                entry = stats.get(qso.callsign)
                if entry is None:
                    entry = WorkedStats(callsign=qso.callsign)
                    stats[qso.callsign] = entry
                entry.add(log=owner, band=qso.band, when=qso.when)

        for ref in refs:
            call = ref.callsign.upper()
            entry = stats.get(call)
            if entry is None:
                entry = WorkedStats(callsign=call)
                stats[call] = entry
            entry.entrant = True

        ordered = sorted(stats.values(), key=lambda s: (-s.times_worked, s.callsign))
        return [entry.to_row() for entry in ordered]
