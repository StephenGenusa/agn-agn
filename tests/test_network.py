"""Opt-in tests that hit live services. Run with: uv run pytest -m network"""

import io
import itertools
import struct
import zipfile

import pytest
import requests

from callsigns.exporters.dta import BUCKET_COUNT, HEADER_SLOTS
from callsigns.providers.pota import PotaHuntersProvider

SOTA_ZIP = "https://www.on6zq.be/f/misc/SOTA_users.zip"

pytestmark = pytest.mark.network


def test_pota_still_returns_declared_columns():
    rows = PotaHuntersProvider().fetch("2026", "all")
    assert rows
    assert set(rows[0]) == {c.key for c in PotaHuntersProvider.columns}
    assert len(rows) > 1000


def test_master_dta_structure_matches_a_real_third_party_file():
    payload = requests.get(SOTA_ZIP, timeout=180).content
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        data = archive.read("SOTA_Calls_CW.dta")

    offsets = list(struct.unpack_from(f"<{HEADER_SLOTS}I", data, 0))
    assert offsets[0] == HEADER_SLOTS * 4
    assert offsets[-1] == len(data)
    assert all(a <= b for a, b in itertools.pairwise(offsets))

    calls: set[str] = set()
    entries = 0
    for index in range(BUCKET_COUNT):
        for raw in data[offsets[index] : offsets[index + 1]].split(b"\x00"):
            if raw:
                entries += 1
                calls.add(raw.decode("ascii"))

    expected = sum(
        len({call[i : i + 2] for i in range(len(call) - 1)}) for call in calls
    )
    assert entries == expected, (
        "the distinct-adjacent-pair rule no longer reproduces the real file"
    )


def test_rbn_daily_file_still_has_the_expected_schema(tmp_path):
    from callsigns.cache import FileCache
    from callsigns.providers.rbn_spots import SPOT_COLUMNS, read_zip_member

    cache = FileCache(tmp_path)
    path = cache.fetch(
        "20251119.zip",
        "https://data.reversebeacon.net/rbn_history/20251119.zip",
    )
    header = next(iter(read_zip_member(path)))
    assert tuple(header.split(",")) == SPOT_COLUMNS


def test_rbn_quiet_day_aggregates_plausibly(tmp_path):
    from callsigns.cache import FileCache
    from callsigns.providers.rbn_spots import aggregate_spots, read_zip_member

    cache = FileCache(tmp_path)
    path = cache.fetch(
        "20251119.zip",
        "https://data.reversebeacon.net/rbn_history/20251119.zip",
    )
    rows, report = aggregate_spots(read_zip_member(path), "CW")
    assert report.rows > 100_000
    assert 5_000 < len(rows) < 30_000
    assert rows[0]["Spots"] > rows[-1]["Spots"]
    assert all(2 <= row["SpeedMax"] <= 80 for row in rows[:100])


def test_sota_rolls_still_return_declared_columns():
    from callsigns.providers.sota import SotaActivatorProvider, SotaChaserProvider

    for provider_cls in (SotaActivatorProvider, SotaChaserProvider):
        rows = provider_cls().fetch("all", "all")
        assert rows, f"{provider_cls.key} returned nothing"
        assert set(rows[0]) == {c.key for c in provider_cls.columns}


def test_sota_mode_is_a_real_restriction():
    from callsigns.providers.sota import SotaActivatorProvider

    provider = SotaActivatorProvider()
    everything = provider.fetch("all", "all")
    cw_only = provider.fetch("all", "cw")
    assert 0 < len(cw_only) < len(everything)


def test_sota_rejects_the_year_the_api_400s_on():
    from callsigns.errors import ValidationError
    from callsigns.providers.sota import SotaActivatorProvider

    with pytest.raises(ValidationError):
        SotaActivatorProvider().validate_period("2001")


def test_cq_listing_is_still_a_static_directory_with_sizes():
    """Listing is one request; only a sample is probed to keep this quick."""
    from callsigns.providers.contest.cq import CqWwCwProvider

    provider = CqWwCwProvider()
    refs = provider.list_entrants("2025")
    assert len(refs) > 5_000
    probed = provider.probe_sizes(refs[:100])
    assert sum(1 for r in probed if r.size) == 100


def test_arrl_listing_reports_entrants_without_sizes():
    from callsigns.providers.contest.arrl import ArrlDxCwProvider

    refs = ArrlDxCwProvider().list_logs("2026")
    assert len(refs) > 4_000
    assert all(r.size is None for r in refs)


def test_cabrillo_index_rule_holds_against_live_logs():
    """The worked-callsign position must stay derivable from the token count."""
    from callsigns.http import HttpClient
    from callsigns.providers.contest.cabrillo import parse_log
    from callsigns.providers.contest.cq import CqWwCwProvider

    provider = CqWwCwProvider()
    sample = provider.probe_sizes(provider.list_entrants("2025")[:300])
    ref = max(sample, key=lambda r: r.size or 0)
    _entrant, qsos = parse_log(HttpClient().get_text(ref.url))
    assert len(qsos) > 1_000
    assert all(any(c.isdigit() for c in q.callsign) for q in qsos[:500])
