import datetime as dt
import pathlib

import pytest

from callsigns.errors import ValidationError
from callsigns.exporters import exporter_names, get_exporter, register_exporter
from callsigns.exporters.base import Exporter, ExportOptions, calls_stem, xlsx_stem
from callsigns.providers.pota import PotaHuntersProvider

PROVIDER = PotaHuntersProvider()


def options(**kwargs):
    base = {
        "period": "all",
        "mode": "all",
        "limit": 500,
        "out_dir": pathlib.Path("/tmp"),
        "today": dt.date(2026, 8, 9),
    }
    base.update(kwargs)
    return ExportOptions(**base)


class Fake(Exporter):
    name = "fake"
    extension = "txt"
    default_limit = 0

    def write(self, rows, provider, options):
        return [self.target_path(provider, options)]


def test_calls_stem_all_mode_all_period():
    assert calls_stem(PROVIDER, options()) == "POTA_Calls"


def test_calls_stem_includes_mode():
    assert calls_stem(PROVIDER, options(mode="cw")) == "POTA_Calls_CW"


def test_calls_stem_includes_period_when_not_all():
    assert (
        calls_stem(PROVIDER, options(mode="cw", period="2026")) == "POTA_Calls_CW_2026"
    )


def test_calls_stem_period_without_mode():
    assert calls_stem(PROVIDER, options(period="2026")) == "POTA_Calls_2026"


def test_xlsx_stem_uses_requested_limit_and_date():
    assert xlsx_stem(PROVIDER, options(mode="cw", period="2026")) == (
        "POTA-500-CW-2026_2026-08-09"
    )


def test_xlsx_stem_all_period_is_alltime():
    assert xlsx_stem(PROVIDER, options()) == "POTA-500-ALL-ALLTIME_2026-08-09"


def test_date_defaults_to_today_when_not_injected():
    assert ExportOptions("all", "all", 0, pathlib.Path()).date() == dt.date.today()


def test_basename_overrides_stem():
    assert Fake().target_path(PROVIDER, options(basename="custom")).name == "custom.txt"


def test_target_path_uses_out_dir_and_extension(tmp_path):
    path = Fake().target_path(PROVIDER, options(out_dir=tmp_path, mode="cw"))
    assert path == tmp_path / "POTA_Calls_CW.txt"


def test_registry_round_trip():
    class Registered(Exporter):
        name = "registered"
        extension = "txt"
        default_limit = 0

        def write(self, rows, provider, options):
            return []

    register_exporter(Registered)
    assert "registered" in exporter_names()
    assert isinstance(get_exporter("registered"), Registered)


def test_unknown_exporter_lists_known():
    with pytest.raises(ValidationError, match="registered"):
        get_exporter("nope")


def test_abstract_write_is_enforced():
    class Incomplete(Exporter):
        name = "incomplete"
        extension = "txt"

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]
