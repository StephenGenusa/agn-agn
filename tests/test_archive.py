import pytest

from callsigns.archive import archive_raw, safe_component
from callsigns.errors import StoreError


def test_safe_component_passes_clean_text():
    assert safe_component("pota-hunters") == "pota-hunters"
    assert safe_component("2026") == "2026"


def test_safe_component_replaces_separators():
    assert safe_component("a/b c") == "a_b_c"


def test_safe_component_never_returns_empty():
    assert safe_component("///") == "unnamed"


def test_archive_writes_under_provider_and_period(tmp_path):
    path = archive_raw(tmp_path, "pota-hunters", "all", b'[{"a": 1}]')
    assert path == tmp_path / "pota-hunters" / "all.json"
    assert path.read_bytes() == b'[{"a": 1}]'


def test_archive_creates_directories(tmp_path):
    path = archive_raw(tmp_path / "deep" / "nested", "p", "2026", b"{}")
    assert path.is_file()


def test_archive_overwrites_previous_payload(tmp_path):
    archive_raw(tmp_path, "p", "all", b"old")
    path = archive_raw(tmp_path, "p", "all", b"new")
    assert path.read_bytes() == b"new"


def test_archive_honours_suffix(tmp_path):
    path = archive_raw(tmp_path, "p", "2026", b"x", suffix=".csv")
    assert path.name == "2026.csv"


def test_unwritable_archive_raises_store_error(tmp_path):
    blocker = tmp_path / "p"
    blocker.write_text("not a directory")
    with pytest.raises(StoreError, match="raw archive"):
        archive_raw(tmp_path, "p", "all", b"x")


def test_suffix_is_inferred_from_the_payload(tmp_path):
    from callsigns.archive import suffix_for

    assert suffix_for(b'[{"a": 1}]') == ".json"
    assert suffix_for(b'  {"a": 1}') == ".json"
    assert suffix_for(b"<!DOCTYPE html><html>") == ".html"
    assert suffix_for(b"<html><body>x</body></html>") == ".html"
    assert suffix_for(b"callsign,de_pfx,de_cont") == ".csv"
    assert suffix_for(b"START-OF-LOG: 3.0") == ".txt"


def test_html_payloads_are_not_filed_as_json(tmp_path):
    path = archive_raw(tmp_path, "skcc-wes", "105", b"<html><body>x</body></html>")
    assert path.name == "105.html"


def test_json_payloads_keep_the_json_suffix(tmp_path):
    path = archive_raw(tmp_path, "pota-hunters", "all", b'[{"a":1}]')
    assert path.name == "all.json"


def test_an_explicit_suffix_still_wins(tmp_path):
    path = archive_raw(tmp_path, "p", "2026", b"<html>", suffix=".dat")
    assert path.name == "2026.dat"
