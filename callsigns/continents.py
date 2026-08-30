"""Prefix-to-continent resolution for the PileupRunner ``.lst`` format."""

import json
import pathlib
from collections.abc import Mapping

from callsigns.errors import StoreError

DEFAULT_TABLE_PATH: pathlib.Path = (
    pathlib.Path(__file__).resolve().parent.parent / "data" / "continents.json"
)

SUFFIXES: frozenset[str] = frozenset({"P", "M", "MM", "AM", "QRP", "A", "B"})
MAX_LOCATION_PREFIX: int = 3


class ContinentLookup:
    """Resolve a callsign to a continent by longest-prefix match."""

    def __init__(self, table: Mapping[str, str]) -> None:
        """Initialise the lookup.

        Args:
            table: Prefix-to-continent mapping.
        """
        self._table = dict(table)
        self._max_length = max((len(key) for key in self._table), default=0)

    @classmethod
    def load(cls, path: pathlib.Path | None = None) -> ContinentLookup:
        """Load the vendored table from disk.

        Args:
            path: Table location. Defaults to :data:`DEFAULT_TABLE_PATH`.

        Returns:
            A ready lookup.

        Raises:
            StoreError: The table is missing, unreadable, or malformed.
        """
        target = path if path is not None else DEFAULT_TABLE_PATH
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StoreError(f"cannot read continent table {target}: {exc}") from exc
        if not isinstance(raw, dict):
            raise StoreError(f"continent table {target} is not a JSON object")
        return cls({str(key): str(value) for key, value in raw.items()})

    def _match(self, text: str) -> str | None:
        """Return the continent for the longest matching prefix of ``text``.

        Args:
            text: An uppercase callsign or prefix.

        Returns:
            The continent code, or ``None`` if nothing matches.
        """
        for length in range(min(len(text), self._max_length), 0, -1):
            found = self._table.get(text[:length])
            if found is not None:
                return found
        return None

    def lookup(self, callsign: str) -> str | None:
        """Resolve a callsign to a continent code.

        Handles portable callsigns by discarding common activity suffixes and
        preferring a short leading location prefix when one resolves.

        Args:
            callsign: The callsign, with or without portable designators.

        Returns:
            A two-letter continent code, or ``None`` if unresolvable.
        """
        text = callsign.strip().upper()
        if not text:
            return None
        parts = [part for part in text.split("/") if part]
        if not parts:
            return None
        if len(parts) > 1:
            meaningful = [part for part in parts if part not in SUFFIXES] or [parts[0]]
            shortest = min(meaningful, key=len)
            if len(shortest) <= MAX_LOCATION_PREFIX:
                found = self._match(shortest)
                if found is not None:
                    return found
            return self._match(meaningful[0])
        return self._match(parts[0])
