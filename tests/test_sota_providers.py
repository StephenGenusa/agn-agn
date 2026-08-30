import datetime as dt
import json
import pathlib

import pytest

from callsigns.errors import UpstreamError, ValidationError
from callsigns.providers import get_provider
from callsigns.providers.sota import BASE_URL, SotaActivatorProvider, SotaChaserProvider

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class RecordingClient:
    def __init__(self, path):
        self.raw = (FIXTURES / path).read_bytes()
        self.urls = []

    def get_bytes(self, url, **kwargs):
        self.urls.append(url)
        return self.raw


def activator():
    client = RecordingClient("sota_activator.json")
    return SotaActivatorProvider(client=client), client


def chaser():
    client = RecordingClient("sota_chaser.json")
    return SotaChaserProvider(client=client), client


def test_activator_identity():
    p, _ = activator()
    assert p.key == "sota-activator"
    assert p.store_name == "SOTA-Activator.xlsx"
    assert p.export_prefix == "SOTA-Activator"
    assert p.callsign_key == "Callsign"
    assert p.bulk is False


def test_chaser_identity():
    p, _ = chaser()
    assert p.key == "sota-chaser"
    assert p.store_name == "SOTA-Chaser.xlsx"
    assert p.export_prefix == "SOTA-Chaser"


def test_the_two_providers_have_different_columns():
    a = {c.key for c in SotaActivatorProvider.columns}
    c = {c.key for c in SotaChaserProvider.columns}
    assert "Summits" in a and "Summits" not in c
    assert "stationsWorked" in c and "stationsWorked" not in a


def test_periods_span_2002_to_current_year_plus_all():
    periods = activator()[0].periods()
    current = dt.datetime.now(dt.UTC).year
    assert periods[0] == "all"
    assert "2002" in periods
    assert str(current) in periods
    assert "2001" not in periods


def test_default_periods_are_current_year_and_all():
    current = str(dt.datetime.now(dt.UTC).year)
    assert set(activator()[0].default_periods()) == {"all", current}


def test_period_labels():
    p, _ = activator()
    assert p.period_label("all") == "All-Time"
    assert p.period_label("2026") == "2026"


def test_rejects_a_year_the_api_would_400_on():
    with pytest.raises(ValidationError, match="2001"):
        activator()[0].validate_period("2001")


def test_rejects_a_future_year_the_api_would_silently_empty():
    future = str(dt.datetime.now(dt.UTC).year + 1)
    with pytest.raises(ValidationError, match=future):
        activator()[0].validate_period(future)


def test_all_period_uses_year_zero():
    p, client = activator()
    p.fetch("all", "all")
    assert client.urls == [f"{BASE_URL}/activator/0/0/all/all"]


def test_year_period_is_in_the_url():
    p, client = activator()
    p.fetch("2026", "all")
    assert client.urls == [f"{BASE_URL}/activator/0/2026/all/all"]


def test_chaser_uses_its_own_roll_segment():
    p, client = chaser()
    p.fetch("all", "all")
    assert client.urls == [f"{BASE_URL}/chaser/0/0/all/all"]


def test_mode_is_a_url_segment_not_a_filter():
    p, client = activator()
    p.fetch("2026", "cw")
    assert client.urls == [f"{BASE_URL}/activator/0/2026/all/CW"]


def test_canonical_mode_mapping():
    p, client = activator()
    for token, segment in (("cw", "CW"), ("phone", "SSB"), ("data", "DATA")):
        client.urls.clear()
        p.fetch("all", token)
        assert client.urls[0].endswith(f"/{segment}")


def test_native_mode_tokens_are_accepted():
    p, client = activator()
    for token in ("AM", "DV", "FM", "OTHER", "SSB"):
        client.urls.clear()
        p.fetch("all", token)
        assert client.urls[0].endswith(f"/{token}")


def test_unknown_mode_is_rejected_locally():
    """The API answers 200 with an empty list for a bogus mode.

    A typo would silently produce an empty sheet unless caught here.
    """
    with pytest.raises(ValidationError, match="nonsense"):
        activator()[0].resolve_mode("nonsense")


def test_unknown_mode_is_rejected_before_any_request():
    p, client = activator()
    with pytest.raises(ValidationError):
        p.fetch("all", "nonsense")
    assert client.urls == []


def test_uses_fetch_modes_so_sheets_carry_the_mode():
    p, _ = activator()
    assert p.uses_fetch_modes() is True
    assert p.sheet_name("all", "cw") == "All-Time CW"
    assert p.sheet_name("2026", "all") == "2026"


def test_source_url_matches_the_fetch_url():
    p, client = activator()
    p.fetch("2026", "cw")
    assert p.source_url("2026") == f"{BASE_URL}/activator/0/2026/all/all"
    assert client.urls[0] == f"{BASE_URL}/activator/0/2026/all/CW"


def test_fetch_keeps_only_declared_columns():
    p, _ = activator()
    rows = p.fetch("all", "all")
    assert set(rows[0]) == {c.key for c in SotaActivatorProvider.columns}


def test_average_is_coerced_to_float():
    rows = activator()[0].fetch("all", "all")
    assert rows[0]["Average"] == pytest.approx(6.98)


def test_position_stays_a_string():
    rows = activator()[0].fetch("all", "all")
    assert rows[0]["Position"] == "1"


def test_placeholder_rows_are_dropped():
    rows = activator()[0].fetch("all", "all")
    assert all("ANON" not in str(r["Callsign"]).upper() for r in rows)
    assert len(rows) == 5


def test_chaser_placeholder_rows_are_dropped():
    rows = chaser()[0].fetch("all", "all")
    assert len(rows) == 3


def test_personal_data_is_retained_as_specified():
    rows = activator()[0].fetch("all", "all")
    assert rows[0]["Username"] == "g4yss"
    assert rows[0]["UserID"] == 77


def test_fetch_preserves_upstream_order():
    rows = activator()[0].fetch("all", "all")
    assert [r["Callsign"] for r in rows][:2] == ["G4YSS", "G4OBK"]


def test_raw_payload_is_retained_for_archiving():
    p, _ = activator()
    assert p.last_raw is None
    p.fetch("all", "all")
    assert p.last_raw is not None
    assert json.loads(p.last_raw)[0]["Callsign"] == "G4YSS"


def test_invalid_date_body_is_an_upstream_error():
    class Plain:
        def get_bytes(self, url, **kwargs):
            return b"Invalid date"

    with pytest.raises(UpstreamError, match="JSON"):
        SotaActivatorProvider(client=Plain()).fetch("all", "all")


def test_both_registered():
    assert isinstance(get_provider("sota-activator"), SotaActivatorProvider)
    assert isinstance(get_provider("sota-chaser"), SotaChaserProvider)
