"""The PileupRunner ``.lst`` format: callsign and continent per line."""

import logging
import pathlib
from collections.abc import Mapping, Sequence
from typing import ClassVar

from callsigns.continents import ContinentLookup
from callsigns.errors import StoreError
from callsigns.exporters import register_exporter
from callsigns.exporters.base import Exporter, ExportOptions
from callsigns.providers.base import Provider
from callsigns.select import clean_callsigns

_LOGGER = logging.getLogger(__name__)


@register_exporter
class LstExporter(Exporter):
    """Writes ``CALLSIGN CONTINENT`` lines for PileupRunner."""

    name: ClassVar[str] = "lst"
    extension: ClassVar[str] = "lst"
    default_limit: ClassVar[int] = 0

    def __init__(self, lookup: ContinentLookup | None = None) -> None:
        """Initialise the exporter.

        Args:
            lookup: Continent resolver. Defaults to the vendored table.
        """
        self._lookup = lookup if lookup is not None else ContinentLookup.load()

    def write(
        self,
        rows: Sequence[Mapping[str, object]],
        provider: Provider,
        options: ExportOptions,
    ) -> list[pathlib.Path]:
        """Write the callsigns and their continents.

        Callsigns whose continent cannot be resolved are omitted and counted
        in a warning rather than written with a placeholder.

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
        lines: list[str] = []
        unresolved = 0
        for call in calls:
            continent = self._lookup.lookup(call)
            if continent is None:
                unresolved += 1
                continue
            lines.append(f"{call} {continent}\n")
        if unresolved:
            _LOGGER.warning("dropped %d callsigns with no continent", unresolved)
        target = self.target_path(provider, options)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("".join(lines), encoding="ascii", newline="\n")
        except OSError as exc:
            raise StoreError(f"cannot write {target}: {exc}") from exc
        return [target]
