"""Cross-source roster: who is active, where, and how broadly.

Every provider ranks callsigns by something, but the somethings are not
comparable — spot counts, QSO counts, summit points and sprint scores measure
different things on different scales. Adding them would be meaningless. So each
source is ranked within itself, converted to a percentile, and only then
combined.

Breadth is the signal no single source carries. A callsign appearing in four
contests is a different kind of operator from one topping a single scoreboard,
and that difference is what this module surfaces.

Two kinds of evidence are kept apart. A contest entry or a club score is
*confirmed participation*: the operator took part. An RBN spot is *observed
activity*: a skimmer heard them. During a large contest the two nearly
coincide, but during a small club event the band is mostly people not in it, so
a spot cannot stand in for having entered. Ranking is on confirmed breadth
first, with observed activity contributing to the score but not to the count.
"""

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from callsigns.providers.base import Column, ModeSpec, Provider

#: Column holding the per-mode QSO counts POTA reports.
_POTA_MODE_COLUMNS: Mapping[str, str] = MappingProxyType(
    {"CW": "Total CW", "PHONE": "Total Phone", "DATA": "Total Data"}
)


class Evidence(enum.StrEnum):
    """How strongly a source shows that an operator took part."""

    #: The operator entered: a contest log, a club score, an award roll.
    CONFIRMED = "confirmed"
    #: A receiver heard them. True of anyone on the band, entered or not.
    OBSERVED = "observed"


@dataclass(frozen=True, slots=True)
class SourceMetric:
    """Which column ranks a source, and what its presence proves."""

    column: str
    evidence: Evidence = Evidence.CONFIRMED
    #: Mode this source implies, when it implies one.
    mode: str | None = None


#: How to rank each source. Contest providers all share a column name, so they
#: are matched by prefix rather than listed one by one.
_METRICS: Mapping[str, SourceMetric] = MappingProxyType(
    {
        "pota-hunters": SourceMetric("Total QSOs"),
        "rbn-cw": SourceMetric("Spots", Evidence.OBSERVED, mode="CW"),
        "sota-activator": SourceMetric("Points"),
        "sota-chaser": SourceMetric("Points"),
        "naqcc-sprint": SourceMetric("Score", mode="CW"),
        "skcc-wes": SourceMetric("Score", mode="CW"),
        "fists-sprint": SourceMetric("Score", mode="CW"),
        "cwops-cwopen": SourceMetric("Callsign", mode="CW"),
    }
)

#: Contest providers, keyed by prefix, all report times worked.
_CONTEST_METRIC = SourceMetric("Times Worked")
_CONTEST_PREFIXES: tuple[str, ...] = ("cqww", "cqwpx", "cq160", "ww-digi", "arrl-")

#: Contest keys whose mode is implied by the contest itself.
_CW_CONTEST_SUFFIXES: tuple[str, ...] = ("-cw", "-sscw", "-dxcw", "-10m", "-160m")


def metric_for(provider_key: str) -> SourceMetric:
    """Return how to rank one source.

    Args:
        provider_key: The provider's registry key.

    Returns:
        Its metric. Unknown sources fall back to a score column and count as
        confirmed participation, which is the common case.
    """
    known = _METRICS.get(provider_key)
    if known is not None:
        return known
    if provider_key.startswith(_CONTEST_PREFIXES):
        mode = "CW" if provider_key.endswith(_CW_CONTEST_SUFFIXES) else None
        return SourceMetric(_CONTEST_METRIC.column, Evidence.CONFIRMED, mode=mode)
    return SourceMetric("Score")


def percentiles(values: Sequence[float]) -> list[float]:
    """Rank values within their own distribution.

    Args:
        values: The values to rank.

    Returns:
        One percentile per value in ``[0, 1]``, where the largest scores 1.0.
        Tied values share a percentile.
    """
    if not values:
        return []
    if len(values) == 1:
        return [1.0]
    ordered = sorted(set(values))
    if len(ordered) == 1:
        return [1.0] * len(values)
    position = {value: index for index, value in enumerate(ordered)}
    span = len(ordered) - 1
    return [position[value] / span for value in values]


def _numeric(row: Mapping[str, object], column: str) -> float | None:
    """Return a row's metric as a number, when it has one.

    Args:
        row: The stored row.
        column: Column holding the metric.

    Returns:
        The value, or ``None`` when absent or not numeric.
    """
    value = row.get(column)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _modes_of(provider_key: str, row: Mapping[str, object]) -> set[str]:
    """Work out which modes a row evidences.

    Args:
        provider_key: The source the row came from.
        row: The stored row.

    Returns:
        Mode names, possibly empty.
    """
    metric = metric_for(provider_key)
    if provider_key == "pota-hunters":
        return {
            mode
            for mode, column in _POTA_MODE_COLUMNS.items()
            if (_numeric(row, column) or 0) > 0
        }
    return {metric.mode} if metric.mode else set()


def build_roster(
    stores: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[dict[str, object]]:
    """Merge every store into one per-callsign view.

    Args:
        stores: Rows keyed by provider key.

    Returns:
        One row per callsign, ranked by confirmed breadth, then by mean
        percentile across the sources it appears in.
    """
    merged: dict[str, dict[str, object]] = {}
    sources: dict[str, set[str]] = {}
    confirmed: dict[str, set[str]] = {}
    modes: dict[str, set[str]] = {}
    ranks: dict[str, list[float]] = {}

    for provider_key, rows in stores.items():
        metric = metric_for(provider_key)
        values = [(_numeric(row, metric.column) or 0.0) for row in rows]
        pcts = percentiles(values)
        for row, raw, pct in zip(rows, values, pcts, strict=True):
            call = str(row.get("Callsign", "")).strip().upper()
            if not call:
                continue
            entry = merged.setdefault(call, {"Callsign": call})
            sources.setdefault(call, set()).add(provider_key)
            if metric.evidence is Evidence.CONFIRMED:
                confirmed.setdefault(call, set()).add(provider_key)
            modes.setdefault(call, set()).update(_modes_of(provider_key, row))
            ranks.setdefault(call, []).append(pct)
            entry[f"{provider_key}_metric"] = (
                None if _numeric(row, metric.column) is None else raw
            )
            entry[f"{provider_key}_pct"] = round(pct, 4)
            speed = _numeric(row, "WPM Median")
            if speed is not None:
                entry["WpmMedian"] = speed

    columns = [f"{key}_{suffix}" for key in stores for suffix in ("metric", "pct")]
    result: list[dict[str, object]] = []
    for call, entry in merged.items():
        present = ranks[call]
        entry["Sources"] = ",".join(sorted(sources[call]))
        entry["SourceCount"] = len(sources[call])
        entry["ConfirmedCount"] = len(confirmed.get(call, set()))
        # Empty rather than absent: a blank cell reads back from the
        # workbook as None, which then renders as the string "None".
        entry["Modes"] = ",".join(sorted(modes[call])) or ""
        entry["MeanPercentile"] = round(sum(present) / len(present), 4)
        entry.setdefault("WpmMedian", None)
        for column in columns:
            entry.setdefault(column, None)
        result.append(entry)

    result.sort(
        key=lambda r: (
            -int(str(r["ConfirmedCount"])),
            -float(str(r["MeanPercentile"])),
            str(r["Callsign"]),
        )
    )
    return result


def overlap_matrix(
    stores: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[tuple[str, str], int]:
    """Count callsigns shared between every pair of sources.

    Args:
        stores: Rows keyed by provider key.

    Returns:
        Shared counts for each ordered pair of distinct sources.
    """
    calls = {
        key: {str(row.get("Callsign", "")).strip().upper() for row in rows} - {""}
        for key, rows in stores.items()
    }
    return {(a, b): len(calls[a] & calls[b]) for a in calls for b in calls if a != b}


#: Columns every roster row carries, whatever sources went into it.
ROSTER_COLUMNS: tuple[Column, ...] = (
    Column("Callsign", "Callsign", str),
    Column("ConfirmedCount", "Confirmed Sources", int),
    Column("SourceCount", "Sources Seen", int),
    Column("Sources", "Sources", str),
    Column("Modes", "Modes", str),
    Column("MeanPercentile", "Mean Percentile", float),
    Column("WpmMedian", "WPM Median", int),
)


class RosterProvider(Provider):
    """A stand-in provider so the roster can use the exporter registry.

    Not registered: the roster is derived from other providers rather than
    fetched, so it has nothing to refresh. It exists because every exporter
    needs a provider to tell it which column holds the callsign, and borrowing
    another provider's would name the wrong one — which silently produces an
    empty file rather than an error.
    """

    key = "roster"
    label = "Cross-source roster"
    store_name = "Roster.xlsx"
    export_prefix = "Roster"
    calls_prefix = "Roster"
    callsign_key = "Callsign"
    columns = ROSTER_COLUMNS
    modes = MappingProxyType({"all": ModeSpec.all_modes(), "cw": ModeSpec.all_modes()})

    def periods(self) -> tuple[str, ...]:
        """Return the single pseudo-period the roster covers."""
        return ("all",)

    def default_periods(self) -> tuple[str, ...]:
        """Return the single pseudo-period the roster covers."""
        return ("all",)

    def period_label(self, period: str) -> str:
        """Return the sheet name the roster is stored under.

        Args:
            period: Ignored; the roster has one period.

        Returns:
            ``Roster``.
        """
        del period
        return "Roster"

    def fetch(self, period: str, mode: str) -> list[dict[str, object]]:
        """Not fetchable: the roster is built from other stores.

        Args:
            period: Ignored.
            mode: Ignored.

        Raises:
            NotImplementedError: Always. Use :func:`build_roster`.
        """
        del period, mode
        raise NotImplementedError("the roster is built with build_roster()")
