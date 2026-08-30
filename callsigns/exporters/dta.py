"""The K1EA MASTER.DTA super-check-partial format.

Consumed by MorseRunner (as ``master.dta``), CT, WriteLog, TRlog, N1MM,
Win-Test and CW Skimmer.

Layout, verified against ON6ZQ's ``SOTA_Calls_CW.dta``::

    offset 0      1370 x uint32 LE   1369 bucket offsets + EOF sentinel
    offset 5480   NUL-terminated ASCII callsigns, grouped by bucket

Bucket ``i`` holds every callsign containing the character pair
``(ALPHABET[i // 37], ALPHABET[i % 37])``. A callsign is written once per
*distinct* adjacent pair it contains, not once per position: re-encoding
ON6ZQ's 79,016 callsigns under that rule reproduces his 398,870 entries and
3,057,789 bytes exactly, where the per-position rule overshoots to 400,093.
"""

import itertools
import pathlib
import struct
from collections.abc import Mapping, Sequence
from typing import ClassVar

from callsigns.errors import StoreError
from callsigns.exporters import register_exporter
from callsigns.exporters.base import Exporter, ExportOptions
from callsigns.providers.base import Provider
from callsigns.select import clean_callsigns

ALPHABET: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/"
ALPHABET_SIZE: int = len(ALPHABET)
BUCKET_COUNT: int = ALPHABET_SIZE * ALPHABET_SIZE
HEADER_SLOTS: int = BUCKET_COUNT + 1
HEADER_BYTES: int = HEADER_SLOTS * 4
MIN_LENGTH: int = 2

_INDEX: dict[str, int] = {char: position for position, char in enumerate(ALPHABET)}


def _bucket_indices(callsign: str) -> list[int]:
    """Return the bucket indices for a callsign's distinct adjacent pairs.

    Args:
        callsign: An uppercase callsign drawn from :data:`ALPHABET`.

    Returns:
        Bucket indices, in first-occurrence order.

    Raises:
        ValueError: The callsign is too short or uses characters outside the
            format's alphabet.
    """
    if len(callsign) < MIN_LENGTH:
        raise ValueError(f"callsign {callsign!r} has no character pair")
    unknown = sorted(set(callsign) - set(ALPHABET))
    if unknown:
        raise ValueError(
            f"callsign {callsign!r} contains characters outside the "
            f"MASTER.DTA alphabet: {''.join(unknown)}"
        )
    seen: dict[int, None] = {}
    for first, second in itertools.pairwise(callsign):
        seen.setdefault(_INDEX[first] * ALPHABET_SIZE + _INDEX[second], None)
    return list(seen)


def encode_master_dta(calls: Sequence[str]) -> bytes:
    """Encode callsigns into MASTER.DTA bytes.

    Args:
        calls: Uppercase callsigns, already cleaned and deduplicated.

    Returns:
        A complete MASTER.DTA file.

    Raises:
        ValueError: A callsign is too short or contains invalid characters.
    """
    buckets: list[list[str]] = [[] for _ in range(BUCKET_COUNT)]
    for call in calls:
        for index in _bucket_indices(call):
            buckets[index].append(call)

    offsets: list[int] = []
    body = bytearray()
    position = HEADER_BYTES
    for bucket in buckets:
        offsets.append(position)
        for call in bucket:
            encoded = call.encode("ascii") + b"\x00"
            body += encoded
            position += len(encoded)
    offsets.append(position)
    return struct.pack(f"<{HEADER_SLOTS}I", *offsets) + bytes(body)


def decode_master_dta(data: bytes) -> list[str]:
    """Decode MASTER.DTA bytes back into a callsign list.

    Args:
        data: A complete MASTER.DTA file.

    Returns:
        The distinct callsigns, in first-occurrence order across buckets.

    Raises:
        ValueError: The header is truncated or internally inconsistent.
    """
    if len(data) < HEADER_BYTES:
        raise ValueError("MASTER.DTA is shorter than its header")
    offsets = list(struct.unpack_from(f"<{HEADER_SLOTS}I", data, 0))
    if offsets[-1] != len(data):
        raise ValueError(
            f"MASTER.DTA sentinel {offsets[-1]} does not match size {len(data)}"
        )
    seen: dict[str, None] = {}
    for index in range(BUCKET_COUNT):
        chunk = data[offsets[index] : offsets[index + 1]]
        for raw in chunk.split(b"\x00"):
            if raw:
                seen.setdefault(raw.decode("ascii"), None)
    return list(seen)


@register_exporter
class DtaExporter(Exporter):
    """Writes a MASTER.DTA file for MorseRunner and friends."""

    name: ClassVar[str] = "dta"
    extension: ClassVar[str] = "dta"
    default_limit: ClassVar[int] = 0

    def write(
        self,
        rows: Sequence[Mapping[str, object]],
        provider: Provider,
        options: ExportOptions,
    ) -> list[pathlib.Path]:
        """Write the callsigns as MASTER.DTA.

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
        target = self.target_path(provider, options)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(encode_master_dta(calls))
        except OSError as exc:
            raise StoreError(f"cannot write {target}: {exc}") from exc
        return [target]
