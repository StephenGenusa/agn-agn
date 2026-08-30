import datetime as dt
import io
import pathlib
import zipfile

import pytest

from callsigns.cache import FileCache
from callsigns.errors import ValidationError
from callsigns.providers import get_provider
from callsigns.providers.rbn import BASE_URL, RbnCwProvider, parse_period

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "rbn_sample.csv"


class FakeClient:
    """Returns a zip of the sample spot file for any URL."""

    def __init__(self):
        self.urls = []

    def get_bytes(self, url, **kwargs):
        self.urls.append(url)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            name = url.rsplit("/", 1)[-1].replace(".zip", ".csv")
            zf.writestr(name, FIXTURE.read_text())
        return buffer.getvalue()


@pytest.fixture
def provider(tmp_path):
    client = FakeClient()
    return RbnCwProvider(cache=FileCache(tmp_path, client=client)), client


def test_identity(provider):
    p, _ = provider
    assert p.key == "rbn-cw"
    assert p.store_name == "RBN-CW.xlsx"
    assert p.callsign_key == "Callsign"
    assert p.bulk is True


def test_periods_are_unbounded(provider):
    p, _ = provider
    assert p.periods() == ()
    assert p.has_enumerable_periods() is False
    assert "YYYYMMDD" in p.period_syntax


def test_no_default_period(provider):
    p, _ = provider
    assert p.default_periods() == ()


def test_parse_single_date():
    assert parse_period("20251129") == (dt.date(2025, 11, 29), dt.date(2025, 11, 29))


def test_parse_inclusive_range():
    start, end = parse_period("20251129-20251201")
    assert start == dt.date(2025, 11, 29)
    assert end == dt.date(2025, 12, 1)


def test_parse_rejects_malformed():
    for bad in ("2025-11-29", "nonsense", "2025112", "20251129-", "-20251129"):
        with pytest.raises(ValidationError, match="YYYYMMDD"):
            parse_period(bad)


def test_parse_rejects_impossible_date():
    with pytest.raises(ValidationError, match="not a valid date"):
        parse_period("20251345")


def test_parse_rejects_backwards_range():
    with pytest.raises(ValidationError, match="starts after"):
        parse_period("20251201-20251129")


def test_validate_rejects_future_dates(provider):
    p, _ = provider
    future = (dt.datetime.now(dt.UTC).date() + dt.timedelta(days=2)).strftime("%Y%m%d")
    with pytest.raises(ValidationError, match="future"):
        p.validate_period(future)


def test_validate_rejects_prehistoric_dates(provider):
    p, _ = provider
    with pytest.raises(ValidationError, match="2009"):
        p.validate_period("20081231")


def test_validate_accepts_a_real_date(provider):
    p, _ = provider
    assert p.validate_period("20251129") == "20251129"


def test_period_label_is_the_token(provider):
    p, _ = provider
    assert p.period_label("20251129") == "20251129"
    assert p.period_label("20251129-20251130") == "20251129-20251130"


def test_sheet_name_appends_mode(provider):
    p, _ = provider
    assert p.sheet_name("20251129", "cw") == "20251129 CW"
    assert p.sheet_name("20251129", "all") == "20251129"


def test_source_url(provider):
    p, _ = provider
    assert p.source_url("20251129") == f"{BASE_URL}/20251129.zip"


def test_fetch_downloads_and_aggregates(provider):
    p, client = provider
    rows = p.fetch("20251129", "cw")
    assert client.urls == [f"{BASE_URL}/20251129.zip"]
    assert rows[0]["Callsign"] == "S59L"
    assert rows[0]["Spots"] == 4


def test_fetch_uses_the_cache_on_a_second_call(provider):
    p, client = provider
    p.fetch("20251129", "cw")
    p.fetch("20251129", "cw")
    assert len(client.urls) == 1


def test_range_fetches_each_day(provider):
    p, client = provider
    p.fetch("20251129-20251201", "cw")
    assert client.urls == [
        f"{BASE_URL}/20251129.zip",
        f"{BASE_URL}/20251130.zip",
        f"{BASE_URL}/20251201.zip",
    ]


def test_range_sums_spots_across_days(provider):
    p, _ = provider
    single = p.fetch("20251129", "cw")[0]["Spots"]
    ranged = p.fetch("20251129-20251130", "cw")[0]["Spots"]
    assert ranged == single * 2


def test_range_does_not_double_count_distinct_skimmers(provider):
    """Both fixture days carry the same two skimmers, so the count stays 2.

    This is what single-pass accumulation buys: combining per-day summaries
    would have summed the counts to 4.
    """
    p, _ = provider
    single = p.fetch("20251129", "cw")[0]
    ranged = p.fetch("20251129-20251130", "cw")[0]
    assert single["Skimmers"] == 2
    assert ranged["Skimmers"] == 2
    assert ranged["Bands"] == single["Bands"]


def test_range_median_is_computed_over_all_spots(provider):
    p, _ = provider
    single = p.fetch("20251129", "cw")[0]
    ranged = p.fetch("20251129-20251130", "cw")[0]
    assert ranged["SpeedMedian"] == single["SpeedMedian"]
    assert ranged["SpeedMin"] == single["SpeedMin"]
    assert ranged["SpeedMax"] == single["SpeedMax"]


def test_all_mode_keeps_every_modulation(provider):
    p, _ = provider
    calls = {r["Callsign"] for r in p.fetch("20251129", "all")}
    assert "K5ZZZ" in calls


def test_phone_is_not_supported(provider):
    p, _ = provider
    with pytest.raises(ValidationError, match="phone"):
        p.resolve_mode("phone")


def test_declared_columns_match_produced_rows(provider):
    p, _ = provider
    rows = p.fetch("20251129", "cw")
    assert set(rows[0]) == {c.key for c in p.columns}


def test_row_ceiling_is_enforced(provider, monkeypatch):
    p, _ = provider
    monkeypatch.setattr("callsigns.providers.rbn.MAX_STORE_ROWS", 2)
    with pytest.raises(ValidationError, match="too many callsigns"):
        p.fetch("20251129", "cw")


def test_use_cache_redirects_downloads(tmp_path):
    p = RbnCwProvider(cache=FileCache(tmp_path / "a", client=FakeClient()))
    client = FakeClient()
    p.use_cache(FileCache(tmp_path / "b", client=client))
    p.fetch("20251129", "cw")
    assert (tmp_path / "b" / "20251129.zip").is_file()
    assert not (tmp_path / "a").exists()


def test_registered():
    assert isinstance(get_provider("rbn-cw"), RbnCwProvider)
