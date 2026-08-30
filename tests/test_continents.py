import json
import pathlib

import pytest

from callsigns.continents import DEFAULT_TABLE_PATH, ContinentLookup
from callsigns.errors import StoreError


@pytest.fixture
def lookup():
    return ContinentLookup.load()


def test_resolves_plain_callsigns(lookup):
    assert lookup.lookup("K1ABC") == "NA"
    assert lookup.lookup("G3XYZ") == "EU"
    assert lookup.lookup("JA1ABC") == "AS"
    assert lookup.lookup("VK2ABC") == "OC"


def test_is_case_insensitive(lookup):
    assert lookup.lookup("k1abc") == lookup.lookup("K1ABC")


def test_resolves_portable_with_location_prefix(lookup):
    assert lookup.lookup("LA/G4YBU/P") == "EU"


def test_resolves_portable_with_trailing_region(lookup):
    assert lookup.lookup("WB0KFC/VE3") == "NA"


def test_strips_common_suffixes(lookup):
    assert lookup.lookup("K1ABC/P") == "NA"
    assert lookup.lookup("K1ABC/QRP") == "NA"
    assert lookup.lookup("K1ABC/MM") == "NA"


def test_unresolvable_returns_none(lookup):
    assert lookup.lookup("P0TA") is None


def test_empty_returns_none(lookup):
    assert lookup.lookup("") is None
    assert lookup.lookup("///") is None


def test_missing_table_raises_store_error(tmp_path):
    with pytest.raises(StoreError, match="continent table"):
        ContinentLookup.load(tmp_path / "absent.json")


def test_corrupt_table_raises_store_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(StoreError, match="continent table"):
        ContinentLookup.load(bad)


def test_non_object_table_raises_store_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2, 3]")
    with pytest.raises(StoreError, match="not a JSON object"):
        ContinentLookup.load(bad)


def test_table_is_pruned_but_complete():
    raw = json.loads(pathlib.Path(DEFAULT_TABLE_PATH).read_text())
    assert 1000 < len(raw) < 3000
    assert set(raw.values()) <= {"AF", "AS", "EU", "NA", "OC", "SA", "AN"}
