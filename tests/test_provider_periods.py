import pytest

from callsigns.cache import FileCache
from callsigns.errors import ValidationError
from callsigns.providers.base import Column, ModeSpec, Provider
from callsigns.providers.pota import PotaHuntersProvider


class Enumerable(Provider):
    key = "enumerable"
    label = "Enumerable"
    store_name = "E.xlsx"
    export_prefix = "E"
    calls_prefix = "E"
    columns = (Column("call", "Callsign", str),)
    callsign_key = "call"
    modes = {"all": ModeSpec.all_modes(), "cw": ModeSpec.filter_on("n")}

    def periods(self):
        return ("all", "2026")

    def default_periods(self):
        return ("all",)

    def period_label(self, period):
        return period

    def fetch(self, period, mode):
        return []


class Unbounded(Provider):
    key = "unbounded"
    label = "Unbounded"
    store_name = "U.xlsx"
    export_prefix = "U"
    calls_prefix = "U"
    period_syntax = "YYYYMMDD"
    columns = (Column("call", "Callsign", str),)
    callsign_key = "call"
    modes = {"all": ModeSpec.all_modes(), "cw": ModeSpec.fetch_as("CW")}

    def periods(self):
        return ()

    def default_periods(self):
        return ()

    def period_label(self, period):
        return period

    def fetch(self, period, mode):
        return []


def test_enumerable_provider_reports_itself_as_such():
    assert Enumerable().has_enumerable_periods() is True
    assert Unbounded().has_enumerable_periods() is False


def test_pota_is_still_enumerable():
    assert PotaHuntersProvider().has_enumerable_periods() is True


def test_unbounded_default_validate_quotes_the_syntax():
    with pytest.raises(ValidationError, match="YYYYMMDD"):
        Unbounded().validate_period("nonsense")


def test_enumerable_validate_is_unchanged():
    assert Enumerable().validate_period("2026") == "2026"
    with pytest.raises(ValidationError, match="1999"):
        Enumerable().validate_period("1999")


def test_filter_mode_provider_sheet_name_ignores_mode():
    provider = Enumerable()
    assert provider.sheet_name("2026", "all") == "2026"
    assert provider.sheet_name("2026", "cw") == "2026"


def test_fetch_mode_provider_sheet_name_appends_mode():
    provider = Unbounded()
    assert provider.sheet_name("20251129", "all") == "20251129"
    assert provider.sheet_name("20251129", "cw") == "20251129 CW"


def test_pota_sheet_names_are_unchanged():
    provider = PotaHuntersProvider()
    assert provider.sheet_name("all", "cw") == "All-Time"
    assert provider.sheet_name("2026", "cw") == "2026"


def test_uses_fetch_modes():
    assert Unbounded().uses_fetch_modes() is True
    assert Enumerable().uses_fetch_modes() is False
    assert PotaHuntersProvider().uses_fetch_modes() is False


def test_use_cache_is_a_harmless_no_op_by_default(tmp_path):
    PotaHuntersProvider().use_cache(FileCache(tmp_path))


def test_sheet_names_stay_within_excel_limit():
    assert len(Unbounded().sheet_name("20251129-20251130", "cw")) <= 31
