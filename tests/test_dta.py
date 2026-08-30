import datetime as dt
import itertools
import struct

import pytest

from callsigns.exporters.base import ExportOptions
from callsigns.exporters.dta import (
    ALPHABET,
    BUCKET_COUNT,
    HEADER_BYTES,
    HEADER_SLOTS,
    DtaExporter,
    decode_master_dta,
    encode_master_dta,
)
from callsigns.providers.pota import PotaHuntersProvider


def offsets(data):
    return list(struct.unpack_from(f"<{HEADER_SLOTS}I", data, 0))


def test_alphabet_is_37_characters():
    assert len(ALPHABET) == 37
    assert ALPHABET.startswith("ABC")
    assert ALPHABET.endswith("789/")
    assert BUCKET_COUNT == 37 * 37


def test_header_is_1370_slots():
    data = encode_master_dta(["K1ABC"])
    assert len(offsets(data)) == HEADER_SLOTS
    assert offsets(data)[0] == HEADER_SLOTS * 4


def test_offsets_are_non_decreasing_and_end_at_file_size():
    data = encode_master_dta(["K1ABC", "W1AW", "LA/G4YBU/P"])
    values = offsets(data)
    assert all(a <= b for a, b in itertools.pairwise(values))
    assert values[-1] == len(data)


def test_round_trip_preserves_the_callsign_set():
    calls = ["K1ABC", "W1AW", "LA/G4YBU/P", "3B8M", "WB0KFC/VE3"]
    decoded = decode_master_dta(encode_master_dta(calls))
    assert sorted(decoded) == sorted(calls)


def test_round_trip_order_is_bucket_order_not_input_order():
    # Decoding walks buckets in index order, so it returns a permutation of
    # the input. Consumers scan whole buckets, so order carries no meaning.
    decoded = decode_master_dta(encode_master_dta(["W1AW", "K1ABC"]))
    assert decoded == ["K1ABC", "W1AW"]


def test_entry_count_equals_sum_of_distinct_adjacent_pairs():
    calls = ["AAA", "K1ABC", "W1AW"]
    data = encode_master_dta(calls)
    expected = sum(len({c[i : i + 2] for i in range(len(c) - 1)}) for c in calls)
    # Count only body terminators: the offset header is full of zero bytes.
    assert data[HEADER_BYTES:].count(b"\x00") == expected


def test_repeated_pair_is_written_once_not_twice():
    data = encode_master_dta(["AAA"])
    assert data.count(b"AAA\x00") == 1


def test_every_callsign_in_a_bucket_contains_that_pair():
    calls = ["K1ABC", "W1AW", "LA/G4YBU/P"]
    data = encode_master_dta(calls)
    values = offsets(data)
    for index in range(BUCKET_COUNT):
        pair = ALPHABET[index // 37] + ALPHABET[index % 37]
        for raw in data[values[index] : values[index + 1]].split(b"\x00"):
            if raw:
                assert pair in raw.decode("ascii")


def test_callsign_appears_in_every_bucket_for_its_pairs():
    data = encode_master_dta(["K1ABC"])
    values = offsets(data)
    positions = {
        ALPHABET.index(a) * 37 + ALPHABET.index(b)
        for a, b in itertools.pairwise("K1ABC")
    }
    for index in positions:
        assert b"K1ABC" in data[values[index] : values[index + 1]]


def test_empty_input_produces_header_only():
    data = encode_master_dta([])
    assert len(data) == HEADER_SLOTS * 4
    assert decode_master_dta(data) == []


def test_single_character_callsign_is_rejected():
    with pytest.raises(ValueError, match="X"):
        encode_master_dta(["X"])


def test_out_of_alphabet_callsign_is_rejected():
    with pytest.raises(ValueError, match="K1-BC"):
        encode_master_dta(["K1-BC"])


def test_decode_rejects_truncated_header():
    with pytest.raises(ValueError, match="shorter than its header"):
        decode_master_dta(b"\x00" * 16)


def test_decode_rejects_bad_sentinel():
    data = bytearray(encode_master_dta(["K1ABC"]))
    struct.pack_into("<I", data, (HEADER_SLOTS - 1) * 4, 999999)
    with pytest.raises(ValueError, match="sentinel"):
        decode_master_dta(bytes(data))


def test_exporter_writes_file_and_cleans_input(tmp_path):
    rows = [
        {"activeCallsign": "k1abc"},
        {"activeCallsign": "BAD-CALL"},
        {"activeCallsign": "K1ABC"},
        {"activeCallsign": "W1AW"},
    ]
    options = ExportOptions(
        period="all",
        mode="cw",
        limit=0,
        out_dir=tmp_path,
        today=dt.date(2026, 8, 9),
    )
    written = DtaExporter().write(rows, PotaHuntersProvider(), options)
    assert written == [tmp_path / "POTA_Calls_CW.dta"]
    assert decode_master_dta(written[0].read_bytes()) == ["K1ABC", "W1AW"]


def test_exporter_default_limit_is_unlimited():
    assert DtaExporter.default_limit == 0


def test_exporter_creates_missing_directories(tmp_path):
    options = ExportOptions("all", "all", 0, tmp_path / "nested", today=dt.date.today())
    written = DtaExporter().write(
        [{"activeCallsign": "K1ABC"}], PotaHuntersProvider(), options
    )
    assert written[0].is_file()
