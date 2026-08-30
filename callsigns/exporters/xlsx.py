"""A standalone filtered workbook, styled like the store."""

import datetime as dt
import pathlib
from collections.abc import Mapping, Sequence
from typing import ClassVar

from openpyxl import Workbook

from callsigns.exporters import register_exporter
from callsigns.exporters.base import Exporter, ExportOptions, xlsx_stem
from callsigns.providers.base import Provider
from callsigns.store import SheetData, SheetMeta, atomic_save, write_data_sheet

EXPORT_SHEET_NAME: str = "Hunters"


@register_exporter
class XlsxExporter(Exporter):
    """Writes the selected rows as a single-sheet workbook.

    Unlike the store, an export carries no ``_meta`` sheet: it is a snapshot
    for a person to read, not the workbook of record.
    """

    name: ClassVar[str] = "xlsx"
    extension: ClassVar[str] = "xlsx"
    default_limit: ClassVar[int] = 500

    def stem(self, provider: Provider, options: ExportOptions) -> str:
        """Return the dated workbook stem.

        Args:
            provider: The provider whose data is being exported.
            options: The export options.

        Returns:
            A stem such as ``POTA-500-CW-2026_2026-08-09``.
        """
        return xlsx_stem(provider, options)

    def write(
        self,
        rows: Sequence[Mapping[str, object]],
        provider: Provider,
        options: ExportOptions,
    ) -> list[pathlib.Path]:
        """Write the rows to a new single-sheet workbook.

        Args:
            rows: Already filtered and limited rows.
            provider: The provider whose data is being exported.
            options: The export options.

        Returns:
            A single-element list holding the path written.

        Raises:
            StoreError: The workbook could not be written.
        """
        data = SheetData(
            name=EXPORT_SHEET_NAME,
            columns=provider.columns,
            rows=[dict(row) for row in rows],
            meta=SheetMeta(
                sheet=EXPORT_SHEET_NAME,
                provider=provider.key,
                period=options.period,
                mode=options.mode,
                rows=len(rows),
                refreshed_utc=dt.datetime.now(dt.UTC).isoformat(),
                source_url=provider.source_url(options.period),
            ),
        )
        book = Workbook()
        default = book.active
        if default is not None:
            book.remove(default)
        write_data_sheet(book.create_sheet(title=EXPORT_SHEET_NAME), data)

        target = self.target_path(provider, options)
        atomic_save(book, target)
        return [target]
