"""Row coercion and placeholder filtering for the SOTA honour rolls.

The rolls type two of their fields as strings — ``Average`` is ``"6.98"`` and
``Position`` is ``"1"`` — so values are converted to the type each column
declares rather than being stored as whatever JSON happened to carry.
"""

import logging
import re
from collections.abc import Mapping, Sequence

from callsigns.errors import UpstreamError
from callsigns.providers.base import Column

#: Anonymised entries appear as ``anon`` followed by digits. They are not
#: callsigns, but they satisfy every generic hygiene rule, so they have to be
#: recognised here where the source is known.
PLACEHOLDER_RE: re.Pattern[str] = re.compile(r"^ANON\d+$", re.IGNORECASE)

_LOGGER = logging.getLogger(__name__)


def is_placeholder(callsign: str) -> bool:
    """Return whether a callsign is an anonymisation placeholder.

    Args:
        callsign: The raw callsign field.

    Returns:
        ``True`` for values such as ``anon22082801``.
    """
    return PLACEHOLDER_RE.match(callsign.strip()) is not None


def coerce_row(
    raw: Mapping[str, object], columns: Sequence[Column], url: str
) -> dict[str, object]:
    """Convert one upstream row to the declared column types.

    Args:
        raw: One object from the upstream array.
        columns: The provider's declared columns.
        url: The request URL, quoted in errors.

    Returns:
        A row containing exactly the declared columns.

    Raises:
        UpstreamError: A declared column is absent, or its value cannot be
            converted to the declared type.
    """
    row: dict[str, object] = {}
    for column in columns:
        if column.key not in raw:
            raise UpstreamError(f"{url} row is missing declared column {column.key!r}")
        value = raw[column.key]
        if column.type is str:
            row[column.key] = str(value)
            continue
        try:
            row[column.key] = column.type(value)  # type: ignore[call-arg]
        except (TypeError, ValueError) as exc:
            raise UpstreamError(
                f"{url} column {column.key!r} has value {value!r}, "
                f"which is not a {column.type.__name__}: {exc}"
            ) from exc
    return row


def coerce_rows(
    payload: object,
    columns: Sequence[Column],
    callsign_key: str,
    url: str,
) -> tuple[list[dict[str, object]], int]:
    """Convert a whole upstream response, dropping placeholder entries.

    Args:
        payload: The parsed JSON document.
        columns: The provider's declared columns.
        callsign_key: Which column holds the callsign.
        url: The request URL, quoted in errors.

    Returns:
        A tuple of the surviving rows, in upstream order, and the number of
        placeholder rows dropped.

    Raises:
        UpstreamError: The payload is not a list of objects, or a row is
            malformed.
    """
    if not isinstance(payload, list):
        raise UpstreamError(f"{url} returned {type(payload).__name__}, expected a list")
    rows: list[dict[str, object]] = []
    dropped = 0
    for entry in payload:
        if not isinstance(entry, dict):
            raise UpstreamError(f"{url} returned a non-object row: {entry!r}")
        if is_placeholder(str(entry.get(callsign_key, ""))):
            dropped += 1
            continue
        rows.append(coerce_row(entry, columns, url))
    if dropped:
        _LOGGER.info("dropped %d anonymised placeholder rows", dropped)
    return rows, dropped
