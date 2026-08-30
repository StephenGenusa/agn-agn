import pytest

from callsigns.errors import ValidationError
from callsigns.providers import get_provider, provider_keys, register
from callsigns.providers.base import Column, Mode, ModeKind, ModeSpec, Provider


class _Dummy(Provider):
    key = "dummy"
    label = "Dummy"
    store_name = "Dummy.xlsx"
    export_prefix = "DUMMY"
    calls_prefix = "DUMMY"
    columns = (Column("call", "Callsign", str), Column("n", "Count", int))
    callsign_key = "call"
    modes = {"all": ModeSpec.all_modes(), "cw": ModeSpec.filter_on("n")}

    def periods(self):
        return ("all", "2026")

    def default_periods(self):
        return ("all",)

    def period_label(self, period):
        return "All-Time" if period == "all" else period

    def fetch(self, period, mode):
        return [{"call": "K1ABC", "n": 3}]


def test_mode_spec_constructors():
    assert ModeSpec.all_modes().kind is ModeKind.ALL
    assert ModeSpec.filter_on("n").column == "n"
    assert ModeSpec.fetch_as("CW").value == "CW"


def test_resolve_mode_returns_declared_spec():
    assert _Dummy().resolve_mode("cw").column == "n"


def test_resolve_mode_rejects_unsupported_and_lists_valid():
    with pytest.raises(ValidationError) as info:
        _Dummy().resolve_mode("phone")
    assert "all" in str(info.value) and "cw" in str(info.value)


def test_validate_period_accepts_and_rejects():
    assert _Dummy().validate_period("2026") == "2026"
    with pytest.raises(ValidationError, match="1999"):
        _Dummy().validate_period("1999")


def test_source_url_defaults_to_empty():
    assert _Dummy().source_url("2026") == ""


def test_column_for_finds_and_rejects():
    assert _Dummy().column_for("n").header == "Count"
    with pytest.raises(ValidationError, match="nope"):
        _Dummy().column_for("nope")


def test_mode_vocabulary_values():
    assert Mode.ALL == "all"
    assert Mode.DATA == "data"


def test_abstract_methods_are_enforced():
    class Incomplete(Provider):
        key = "incomplete"

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def _make_registrable(key: str) -> type[Provider]:
    """Return a fresh Provider subclass so registry tests stay independent."""
    return type(_Dummy)(f"_{key}", (_Dummy,), {"key": key})


def test_registration_round_trip():
    cls = _make_registrable("round-trip")
    register(cls)
    assert "round-trip" in provider_keys()
    assert isinstance(get_provider("round-trip"), cls)


def test_unknown_provider_lists_known_keys():
    register(_make_registrable("known-one"))
    with pytest.raises(ValidationError, match="known-one"):
        get_provider("nope")


def test_duplicate_registration_is_rejected():
    cls = _make_registrable("dupe")
    register(cls)
    with pytest.raises(ValueError, match="dupe"):
        register(cls)
