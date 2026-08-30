"""Exporter contract, options and filename construction."""

import abc
import datetime as dt
import pathlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from callsigns.providers.base import Provider

ALL_PERIOD: str = "all"
ALL_PERIOD_LABEL: str = "ALLTIME"


@dataclass(frozen=True, slots=True)
class ExportOptions:
    """Everything an exporter needs beyond the rows themselves."""

    period: str
    mode: str
    limit: int
    out_dir: pathlib.Path
    basename: str | None = None
    today: dt.date | None = None

    def date(self) -> dt.date:
        """Return the date to stamp into filenames.

        Returns:
            ``today`` if given, otherwise the current local date. Injectable
            so filename tests are deterministic.
        """
        return self.today if self.today is not None else dt.date.today()


def calls_stem(provider: Provider, options: ExportOptions) -> str:
    """Build the ON6ZQ-style stem for a call-list export.

    The mode is appended unless it is ``all``; the period is appended only
    when it is not ``all``, so exporting a single year cannot overwrite the
    all-time drop-in files.

    Args:
        provider: The provider whose data is being exported.
        options: The export options.

    Returns:
        A filename stem without extension, such as ``POTA_Calls_CW_2026``.
    """
    parts = [provider.calls_prefix, "Calls"]
    if options.mode != ALL_PERIOD:
        parts.append(options.mode.upper())
    if options.period != ALL_PERIOD:
        parts.append(options.period)
    return "_".join(parts)


def xlsx_stem(provider: Provider, options: ExportOptions) -> str:
    """Build the stem for a workbook export.

    Args:
        provider: The provider whose data is being exported.
        options: The export options.

    Returns:
        A stem such as ``POTA-500-CW-2026_2026-08-09``, using the requested
        row limit rather than the delivered row count.
    """
    period = ALL_PERIOD_LABEL if options.period == ALL_PERIOD else options.period
    return (
        f"{provider.export_prefix}-{options.limit}-{options.mode.upper()}"
        f"-{period}_{options.date().isoformat()}"
    )


class Exporter(abc.ABC):
    """Serialises selected rows into one output format."""

    name: ClassVar[str]
    extension: ClassVar[str]
    default_limit: ClassVar[int] = 0

    def stem(self, provider: Provider, options: ExportOptions) -> str:
        """Return the filename stem for this format.

        Args:
            provider: The provider whose data is being exported.
            options: The export options.

        Returns:
            The stem, defaulting to the call-list convention.
        """
        return calls_stem(provider, options)

    def target_path(self, provider: Provider, options: ExportOptions) -> pathlib.Path:
        """Return the full output path.

        Args:
            provider: The provider whose data is being exported.
            options: The export options; ``basename`` overrides the stem.

        Returns:
            The path this export will write.
        """
        stem = options.basename or self.stem(provider, options)
        return options.out_dir / f"{stem}.{self.extension}"

    @abc.abstractmethod
    def write(
        self,
        rows: Sequence[Mapping[str, object]],
        provider: Provider,
        options: ExportOptions,
    ) -> list[pathlib.Path]:
        """Write the export.

        Args:
            rows: Already filtered and limited rows, in stored order.
            provider: The provider whose data is being exported.
            options: The export options.

        Returns:
            The paths written.

        Raises:
            StoreError: The output could not be written.
        """
