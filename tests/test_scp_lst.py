import datetime as dt

from callsigns.exporters.base import ExportOptions
from callsigns.exporters.lst import LstExporter
from callsigns.exporters.scp import ScpExporter
from callsigns.providers.pota import PotaHuntersProvider

PROVIDER = PotaHuntersProvider()


def options(tmp_path, **kwargs):
    base = {
        "period": "all",
        "mode": "all",
        "limit": 0,
        "out_dir": tmp_path,
        "today": dt.date(2026, 8, 9),
    }
    base.update(kwargs)
    return ExportOptions(**base)


def rows(*calls):
    return [{"activeCallsign": c} for c in calls]


def test_scp_is_sorted_uppercase_one_per_line(tmp_path):
    written = ScpExporter().write(
        rows("W1AW", "k1abc", "3B8M"), PROVIDER, options(tmp_path)
    )
    assert written[0].name == "POTA_Calls.scp"
    assert written[0].read_text() == "3B8M\nK1ABC\nW1AW\n"


def test_scp_uses_lf_endings_only(tmp_path):
    written = ScpExporter().write(rows("W1AW", "K1ABC"), PROVIDER, options(tmp_path))
    assert b"\r\n" not in written[0].read_bytes()


def test_scp_drops_invalid_and_deduplicates(tmp_path):
    written = ScpExporter().write(
        rows("K1ABC", "BAD-CALL", "k1abc", "X"), PROVIDER, options(tmp_path)
    )
    assert written[0].read_text() == "K1ABC\n"


def test_scp_mode_and_period_in_filename(tmp_path):
    written = ScpExporter().write(
        rows("K1ABC"), PROVIDER, options(tmp_path, mode="cw", period="2026")
    )
    assert written[0].name == "POTA_Calls_CW_2026.scp"


def test_scp_empty_input_writes_empty_file(tmp_path):
    written = ScpExporter().write([], PROVIDER, options(tmp_path))
    assert written[0].read_text() == ""


def test_lst_writes_call_and_continent(tmp_path):
    written = LstExporter().write(rows("K1ABC", "G3XYZ"), PROVIDER, options(tmp_path))
    assert written[0].name == "POTA_Calls.lst"
    assert written[0].read_text() == "K1ABC NA\nG3XYZ EU\n"


def test_lst_preserves_input_order(tmp_path):
    written = LstExporter().write(rows("G3XYZ", "K1ABC"), PROVIDER, options(tmp_path))
    assert written[0].read_text().splitlines()[0].startswith("G3XYZ")


def test_lst_drops_unresolvable_callsigns(tmp_path):
    written = LstExporter().write(rows("K1ABC", "P0TA"), PROVIDER, options(tmp_path))
    assert written[0].read_text() == "K1ABC NA\n"


def test_lst_resolves_portable_callsigns(tmp_path):
    written = LstExporter().write(rows("LA/G4YBU/P"), PROVIDER, options(tmp_path))
    assert written[0].read_text() == "LA/G4YBU/P EU\n"


def test_lst_warns_about_dropped_callsigns(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        LstExporter().write(rows("K1ABC", "P0TA"), PROVIDER, options(tmp_path))
    assert "1 callsigns with no continent" in caplog.text


def test_default_limits_are_unlimited():
    assert ScpExporter.default_limit == 0
    assert LstExporter.default_limit == 0
