import datetime as dt
import json
import pathlib

import pytest

from callsigns.errors import UpstreamError, ValidationError
from callsigns.providers.pota import BASE_URL, PotaHuntersProvider

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "pota_hunters.json"


class RecordingClient:
    """Stands in for HttpClient, returning encoded JSON bytes."""

    def __init__(self, payload, raw=None):
        self.raw = raw if raw is not None else json.dumps(payload).encode()
        self.urls = []

    def get_bytes(self, url, **kwargs):
        self.urls.append(url)
        return self.raw


def make_provider():
    return PotaHuntersProvider(client=RecordingClient(json.loads(FIXTURE.read_text())))


def test_identity_fields():
    p = make_provider()
    assert p.key == "pota-hunters"
    assert p.store_name == "POTA-Hunters.xlsx"
    assert p.export_prefix == "POTA"
    assert p.calls_prefix == "POTA"
    assert p.callsign_key == "activeCallsign"
    assert p.bulk is False


def test_periods_span_2016_to_current_year_plus_all():
    periods = make_provider().periods()
    current = dt.datetime.now(dt.UTC).year
    assert periods[0] == "all"
    assert "2016" in periods
    assert str(current) in periods
    assert "2015" not in periods


def test_default_periods_are_current_year_and_all():
    current = str(dt.datetime.now(dt.UTC).year)
    assert set(make_provider().default_periods()) == {"all", current}


def test_period_labels():
    p = make_provider()
    assert p.period_label("all") == "All-Time"
    assert p.period_label("2026") == "2026"


def test_all_period_omits_query_parameter():
    client = RecordingClient(json.loads(FIXTURE.read_text()))
    PotaHuntersProvider(client=client).fetch("all", "all")
    assert client.urls == [BASE_URL]


def test_year_period_appends_query_parameter():
    client = RecordingClient(json.loads(FIXTURE.read_text()))
    PotaHuntersProvider(client=client).fetch("2026", "all")
    assert client.urls == [f"{BASE_URL}?year=2026"]


def test_source_url_matches_fetch_url():
    p = make_provider()
    assert p.source_url("all") == BASE_URL
    assert p.source_url("2026") == f"{BASE_URL}?year=2026"


def test_fetch_keeps_only_declared_columns():
    rows = make_provider().fetch("all", "all")
    assert set(rows[0]) == {
        "activeCallsign",
        "numParks",
        "numQSOs",
        "qsosCW",
        "qsosDATA",
        "qsosPHONE",
    }
    assert "unexpectedField" not in rows[-1]


def test_fetch_preserves_upstream_order():
    rows = make_provider().fetch("all", "all")
    assert [r["activeCallsign"] for r in rows][:3] == ["SM3NRY", "F5PYI", "K2UPD"]


def test_modes_are_filters_on_the_right_columns():
    p = make_provider()
    assert p.resolve_mode("cw").column == "qsosCW"
    assert p.resolve_mode("phone").column == "qsosPHONE"
    assert p.resolve_mode("data").column == "qsosDATA"
    with pytest.raises(ValidationError):
        p.resolve_mode("ssb")


def test_missing_columns_are_an_upstream_error_naming_the_keys():
    client = RecordingClient([{"activeCallsign": "K1ABC"}])
    with pytest.raises(UpstreamError, match="numParks"):
        PotaHuntersProvider(client=client).fetch("all", "all")


def test_non_list_payload_is_an_upstream_error():
    client = RecordingClient({"message": "Missing Authentication Token"})
    with pytest.raises(UpstreamError, match="list"):
        PotaHuntersProvider(client=client).fetch("all", "all")


def test_non_object_row_is_an_upstream_error():
    client = RecordingClient(["not-a-dict"])
    with pytest.raises(UpstreamError, match="non-object"):
        PotaHuntersProvider(client=client).fetch("all", "all")


def test_fetch_retains_the_raw_payload():
    provider = make_provider()
    assert provider.last_raw is None
    provider.fetch("all", "all")
    assert provider.last_raw is not None
    assert json.loads(provider.last_raw)[0]["activeCallsign"] == "SM3NRY"


def test_invalid_json_is_an_upstream_error():
    client = RecordingClient(None, raw=b"not json")
    with pytest.raises(UpstreamError, match="invalid JSON"):
        PotaHuntersProvider(client=client).fetch("all", "all")


def test_registered_under_its_key():
    from callsigns.providers import get_provider

    assert isinstance(get_provider("pota-hunters"), PotaHuntersProvider)
