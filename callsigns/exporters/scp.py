"""The ``.scp`` super-check-partial text format, for N1MM and Morserino."""

import pathlib
from collections.abc import Mapping, Sequence
from typing import ClassVar

from callsigns.errors import StoreError
from callsigns.exporters import register_exporter
from callsigns.exporters.base import Exporter, ExportOptions
from callsigns.providers.base import Provider
from callsigns.select import clean_callsigns


@register_exporter
class ScpExporter(Exporter):
    """Writes sorted uppercase callsigns, one per line."""

    name: ClassVar[str] = "scp"
    extension: ClassVar[str] = "scp"
    default_limit: ClassVar[int] = 0

    def write(
        self,
        rows: Sequence[Mapping[str, object]],
        provider: Provider,
        options: ExportOptions,
    ) -> list[pathlib.Path]:
        """Write the callsigns as a ``.scp`` file.

        Args:
            rows: Already filtered and limited rows.
            provider: The provider whose data is being exported.
            options: The export options.

        Returns:
            A single-element list holding the path written.

        Raises:
            StoreError: The file could not be written.
        """
        calls, _report = clean_callsigns(row.get(provider.callsign_key) for row in rows)
        body = "".join(f"{call}\n" for call in sorted(calls))
        target = self.target_path(provider, options)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="ascii", newline="\n")
        except OSError as exc:
            raise StoreError(f"cannot write {target}: {exc}") from exc
        return [target]
