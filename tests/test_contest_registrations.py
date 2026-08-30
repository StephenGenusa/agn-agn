import pytest

from callsigns.providers import get_provider, provider_keys
from callsigns.providers.contest.base import ContestLogProvider

CQ_EXPECTED = {
    "cqww-cw": ("cqww.com", "cw"),
    "cqwpx-cw": ("cqwpx.com", "cw"),
    "cq160-cw": ("cq160.com", "cw"),
    "cqww-rtty": ("cqwwrtty.com", ""),
    "cqwpx-rtty": ("cqwpxrtty.com", ""),
    "ww-digi": ("ww-digi.com", ""),
}

ARRL_EXPECTED = {
    "arrl-dxcw": "dxcw",
    "arrl-dxph": "dxph",
    "arrl-sscw": "sscw",
    "arrl-ssph": "ssph",
    "arrl-10m": "10m",
    "arrl-160m": "160m",
    "arrl-iaruhf": "iaruhf",
    "arrl-rttyru": "rttyru",
    "arrl-dig": "dig",
    "arrl-eme": "eme",
    "arrl-janvhf": "janvhf",
    "arrl-junvhf": "junvhf",
    "arrl-sepvhf": "sepvhf",
    "arrl-222": "222",
    "arrl-10g": "10g",
}


@pytest.mark.parametrize(("key", "expected"), sorted(CQ_EXPECTED.items()))
def test_cq_registration(key, expected):
    host, suffix = expected
    provider = get_provider(key)
    assert provider.host == host
    assert provider.mode_suffix == suffix
    assert provider.listing_url("2025") == f"https://{host}/publiclogs/2025{suffix}/"


@pytest.mark.parametrize(("key", "contest"), sorted(ARRL_EXPECTED.items()))
def test_arrl_registration(key, contest):
    provider = get_provider(key)
    assert provider.contest == contest
    assert provider.source_url("2025").endswith(f"cn={contest}")


def test_every_contest_provider_shares_the_base_contract():
    for key in provider_keys():
        provider = get_provider(key)
        if isinstance(provider, ContestLogProvider):
            assert next(c.key for c in provider.columns) == "Callsign"
            assert provider.bulk is True
            assert provider.callsign_key == "Callsign"


def test_store_names_are_unique():
    names = [get_provider(k).store_name for k in provider_keys()]
    assert len(names) == len(set(names))


def test_export_prefixes_are_unique():
    prefixes = [get_provider(k).export_prefix for k in provider_keys()]
    assert len(prefixes) == len(set(prefixes))


def test_labels_are_unique():
    labels = [get_provider(k).label for k in provider_keys()]
    assert len(labels) == len(set(labels))


def test_cq_first_years_reflect_what_each_host_publishes():
    assert get_provider("cqww-cw").first_year == 2019
    assert get_provider("cqwpx-cw").first_year == 2023
    assert get_provider("cq160-cw").first_year == 2022


def test_rtty_hosts_use_a_bare_year_directory():
    assert get_provider("cqww-rtty").listing_url("2025").endswith("/2025/")
