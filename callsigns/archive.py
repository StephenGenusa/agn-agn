"""Verbatim storage of upstream payloads.

Keeping the bytes exactly as received means the store can be rebuilt, or new
columns derived, without going back to the network. The archive is a
convenience, never a source of truth: deleting it costs only a re-fetch.
"""

import logging
import pathlib
import re

from callsigns.errors import StoreError

_LOGGER = logging.getLogger(__name__)


def safe_component(text: str) -> str:
    """Reduce a string to something safe to use as a filename component.

    Args:
        text: Arbitrary text, such as a provider key or period token.

    Returns:
        The text with runs of unsafe characters replaced by underscores.
    """
    return re.sub(r"[^0-9A-Za-z._-]+", "_", text).strip("_") or "unnamed"


def suffix_for(data: bytes) -> str:
    """Guess a sensible file extension from a payload's first bytes.

    Args:
        data: The raw payload.

    Returns:
        ``.json``, ``.html``, ``.csv`` or ``.txt``.
    """
    head = data[:200].lstrip().lower()
    if head.startswith((b"{", b"[")):
        return ".json"
    if head.startswith((b"<!doctype", b"<html", b"<?xml")) or b"<html" in head:
        return ".html"
    if head.startswith(b"callsign,"):
        return ".csv"
    return ".txt"


def archive_raw(
    root: pathlib.Path,
    provider_key: str,
    period: str,
    data: bytes,
    suffix: str | None = None,
) -> pathlib.Path:
    """Write one upstream payload to the raw archive.

    Args:
        root: Archive root directory, created if absent.
        provider_key: Provider identifier, used as a subdirectory.
        period: Period token, used as the filename stem.
        data: The bytes exactly as received.
        suffix: File extension to give the archived payload. Inferred from
            the payload when omitted, so an HTML scoreboard is not filed as
            ``.json``.

    Returns:
        The path written.

    Raises:
        StoreError: The archive could not be written.
    """
    chosen = suffix if suffix is not None else suffix_for(data)
    target = root / safe_component(provider_key) / f"{safe_component(period)}{chosen}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as exc:
        raise StoreError(f"cannot write raw archive {target}: {exc}") from exc
    _LOGGER.debug("archived %d bytes to %s", len(data), target)
    return target
