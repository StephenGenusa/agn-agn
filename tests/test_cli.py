import datetime as dt
import io
import json
import pathlib
import zipfile

import pytest

from callsigns.cli import main
from callsigns.errors import ExitCode, UpstreamError
from callsigns.exporters.dta import decode_master_dta
from callsigns.pacing import HostPolicy, RateLimiter
from callsigns.providers.pota import PotaHuntersProvider
from callsigns.store import WorkbookStore

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "pota_hunters.json"


@pytest.fixture
def fake_api(monkeypatch):
    raw = FIXTURE.read_bytes()
    calls = []

    class FakeClient:
        def get_bytes(self, url, **kwargs):
            calls.append(url)
            return raw

    monkeypatch.setattr("callsigns.providers.pota.HttpClient", lambda: FakeClient())
    return calls


def test_providers_lists_pota(capsys):
    assert main(["providers"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "pota-hunters" in out
    assert "cw" in out


def test_refresh_creates_store(tmp_path, fake_api):
    store = tmp_path / "S.xlsx"
    assert main(["refresh", "pota-hunters", "-y", "all", "--store", str(store)]) == 0
    assert store.is_file()


def test_refresh_archives_raw_payload(tmp_path, fake_api):
    store = tmp_path / "S.xlsx"
    raw = tmp_path / "raw"
    main(
        [
            "refresh",
            "pota-hunters",
            "-y",
            "all",
            "--store",
            str(store),
            "--raw-dir",
            str(raw),
        ]
    )
    archived = raw / "pota-hunters" / "all.json"
    assert archived.is_file()
    assert json.loads(archived.read_text())[0]["activeCallsign"] == "SM3NRY"


def test_empty_store_backfills_every_period(tmp_path, fake_api):
    store = tmp_path / "S.xlsx"
    assert main(["refresh", "pota-hunters", "--store", str(store)]) == 0
    expected = len(PotaHuntersProvider().periods())
    assert len(WorkbookStore(store).sheet_names()) == expected


def test_populated_store_refreshes_only_default_periods(tmp_path, fake_api):
    store = tmp_path / "S.xlsx"
    main(["refresh", "pota-hunters", "-y", "all", "--store", str(store)])
    main(["refresh", "pota-hunters", "--store", str(store)])
    names = WorkbookStore(store).sheet_names()
    assert "All-Time" in names
    assert len(names) == 2


def test_refresh_rejects_unknown_period(tmp_path, fake_api, capsys):
    store = tmp_path / "S.xlsx"
    code = main(["refresh", "pota-hunters", "-y", "1999", "--store", str(store)])
    assert code == ExitCode.VALIDATION
    assert "1999" in capsys.readouterr().err
    assert not store.exists()


def test_refresh_rejects_mode_on_filter_provider(tmp_path, fake_api, capsys):
    store = tmp_path / "S.xlsx"
    code = main(
        ["refresh", "pota-hunters", "-y", "all", "-o", "cw", "--store", str(store)]
    )
    assert code == ExitCode.VALIDATION
    assert "export" in capsys.readouterr().err


def test_export_dta_after_refresh(tmp_path, fake_api):
    store = tmp_path / "S.xlsx"
    main(["refresh", "pota-hunters", "-y", "all", "--store", str(store)])
    code = main(
        [
            "export",
            "pota-hunters",
            "dta",
            "-y",
            "all",
            "-o",
            "cw",
            "--store",
            str(store),
            "--out",
            str(tmp_path),
        ]
    )
    assert code == ExitCode.OK
    assert (tmp_path / "POTA_Calls_CW.dta").is_file()


def test_export_applies_mode_filter(tmp_path, fake_api):
    store = tmp_path / "S.xlsx"
    main(["refresh", "pota-hunters", "-y", "all", "--store", str(store)])
    main(
        [
            "export",
            "pota-hunters",
            "dta",
            "-o",
            "cw",
            "--store",
            str(store),
            "--out",
            str(tmp_path),
        ]
    )
    calls = decode_master_dta((tmp_path / "POTA_Calls_CW.dta").read_bytes())
    assert set(calls) == {"SM3NRY", "F5PYI", "K2UPD", "W1AW"}


def test_export_respects_limit(tmp_path, fake_api):
    store = tmp_path / "S.xlsx"
    main(["refresh", "pota-hunters", "-y", "all", "--store", str(store)])
    main(
        [
            "export",
            "pota-hunters",
            "dta",
            "-d",
            "2",
            "--store",
            str(store),
            "--out",
            str(tmp_path),
        ]
    )
    assert len(decode_master_dta((tmp_path / "POTA_Calls.dta").read_bytes())) == 2


def test_export_warns_when_fewer_rows_than_requested(tmp_path, fake_api, capsys):
    store = tmp_path / "S.xlsx"
    main(["refresh", "pota-hunters", "-y", "all", "--store", str(store)])
    main(
        [
            "export",
            "pota-hunters",
            "scp",
            "-d",
            "999",
            "--store",
            str(store),
            "--out",
            str(tmp_path),
        ]
    )
    assert "only 5 rows" in capsys.readouterr().err


def test_export_missing_sheet_names_the_refresh_command(tmp_path, fake_api, capsys):
    store = tmp_path / "S.xlsx"
    main(["refresh", "pota-hunters", "-y", "all", "--store", str(store)])
    code = main(
        [
            "export",
            "pota-hunters",
            "scp",
            "-y",
            "2026",
            "--store",
            str(store),
            "--out",
            str(tmp_path),
        ]
    )
    assert code == ExitCode.VALIDATION
    assert "refresh pota-hunters -y 2026" in capsys.readouterr().err


def test_export_without_store_is_a_store_error(tmp_path):
    code = main(
        [
            "export",
            "pota-hunters",
            "scp",
            "--store",
            str(tmp_path / "absent.xlsx"),
            "--out",
            str(tmp_path),
        ]
    )
    assert code == ExitCode.STORE


def test_upstream_failure_exits_two(tmp_path, monkeypatch, capsys):
    class Boom:
        def get_bytes(self, url, **kwargs):
            raise UpstreamError("timeout")

    monkeypatch.setattr("callsigns.providers.pota.HttpClient", lambda: Boom())
    code = main(
        ["refresh", "pota-hunters", "-y", "all", "--store", str(tmp_path / "S.xlsx")]
    )
    assert code == ExitCode.UPSTREAM
    assert "timeout" in capsys.readouterr().err


def test_no_traceback_on_error(tmp_path, capsys):
    main(["export", "pota-hunters", "scp", "--store", str(tmp_path / "absent.xlsx")])
    assert "Traceback" not in capsys.readouterr().err


def test_unknown_provider_is_a_validation_error(tmp_path, capsys):
    assert main(["refresh", "nope", "--store", str(tmp_path / "S.xlsx")]) == (
        ExitCode.VALIDATION
    )
    assert "unknown provider" in capsys.readouterr().err


def test_default_paths_live_under_data(tmp_path, fake_api, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["refresh", "pota-hunters", "-y", "all"]) == 0
    assert (tmp_path / "data" / "POTA-Hunters.xlsx").is_file()
    assert (tmp_path / "data" / "raw" / "pota-hunters" / "all.json").is_file()
    assert main(["export", "pota-hunters", "scp", "-o", "cw"]) == 0
    assert (tmp_path / "data" / "POTA_Calls_CW.scp").is_file()


@pytest.fixture
def fake_rbn(monkeypatch):
    """Point rbn-cw's cache at a client serving the sample spot file."""
    sample = pathlib.Path(__file__).parent / "fixtures" / "rbn_sample.csv"

    class FakeClient:
        def __init__(self):
            self.urls = []

        def get_bytes(self, url, **kwargs):
            self.urls.append(url)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as zf:
                zf.writestr("spots.csv", sample.read_text())
            return buffer.getvalue()

    client = FakeClient()
    monkeypatch.setattr("callsigns.cache.HttpClient", lambda: client)
    return client


def test_rbn_refresh_writes_a_mode_suffixed_sheet(tmp_path, fake_rbn):
    store = tmp_path / "R.xlsx"
    code = main(
        ["refresh", "rbn-cw", "-y", "20251129", "-o", "cw", "--store", str(store)]
    )
    assert code == ExitCode.OK
    assert WorkbookStore(store).sheet_names() == ["20251129 CW"]


def test_rbn_bare_refresh_demands_a_period(tmp_path, fake_rbn, capsys):
    code = main(["refresh", "rbn-cw", "--store", str(tmp_path / "R.xlsx")])
    assert code == ExitCode.VALIDATION
    assert "YYYYMMDD" in capsys.readouterr().err


def test_rbn_rejects_a_future_period(tmp_path, fake_rbn, capsys):
    future = (dt.datetime.now(dt.UTC).date() + dt.timedelta(days=3)).strftime("%Y%m%d")
    code = main(
        ["refresh", "rbn-cw", "-y", future, "--store", str(tmp_path / "R.xlsx")]
    )
    assert code == ExitCode.VALIDATION
    assert "future" in capsys.readouterr().err


def test_rbn_export_reads_the_mode_sheet(tmp_path, fake_rbn):
    store = tmp_path / "R.xlsx"
    main(["refresh", "rbn-cw", "-y", "20251129", "-o", "cw", "--store", str(store)])
    code = main(
        [
            "export",
            "rbn-cw",
            "scp",
            "-y",
            "20251129",
            "-o",
            "cw",
            "--store",
            str(store),
            "--out",
            str(tmp_path),
        ]
    )
    assert code == ExitCode.OK
    assert "S59L" in (tmp_path / "RBN_Calls_CW_20251129.scp").read_text()


def test_rbn_export_missing_sheet_names_the_mode(tmp_path, fake_rbn, capsys):
    store = tmp_path / "R.xlsx"
    main(["refresh", "rbn-cw", "-y", "20251129", "-o", "all", "--store", str(store)])
    code = main(
        [
            "export",
            "rbn-cw",
            "scp",
            "-y",
            "20251129",
            "-o",
            "cw",
            "--store",
            str(store),
            "--out",
            str(tmp_path),
        ]
    )
    assert code == ExitCode.VALIDATION
    assert "-o cw" in capsys.readouterr().err


def test_rbn_cache_flag_is_honoured(tmp_path, fake_rbn):
    cache = tmp_path / "mycache"
    main(
        [
            "refresh",
            "rbn-cw",
            "-y",
            "20251129",
            "-o",
            "cw",
            "--store",
            str(tmp_path / "R.xlsx"),
            "--cache",
            str(cache),
        ]
    )
    assert (cache / "20251129.zip").is_file()


def test_second_refresh_reuses_the_cache(tmp_path, fake_rbn):
    args = [
        "refresh",
        "rbn-cw",
        "-y",
        "20251129",
        "-o",
        "cw",
        "--store",
        str(tmp_path / "R.xlsx"),
        "--cache",
        str(tmp_path / "c"),
    ]
    main(args)
    main(args)
    assert len(fake_rbn.urls) == 1


def test_refresh_accepts_multiple_modes(tmp_path, fake_rbn):
    store = tmp_path / "R.xlsx"
    main(["refresh", "rbn-cw", "-y", "20251129", "-o", "all,cw", "--store", str(store)])
    assert sorted(WorkbookStore(store).sheet_names()) == ["20251129", "20251129 CW"]


def test_cache_flag_rejected_on_a_single_request_provider(tmp_path, fake_api, capsys):
    code = main(
        [
            "refresh",
            "pota-hunters",
            "-y",
            "all",
            "--store",
            str(tmp_path / "S.xlsx"),
            "--cache",
            str(tmp_path / "c"),
        ]
    )
    assert code == ExitCode.VALIDATION
    assert "does not use a cache" in capsys.readouterr().err


def test_providers_shows_period_syntax_for_unbounded(capsys):
    main(["providers"])
    out = capsys.readouterr().out
    assert "rbn-cw" in out
    assert "YYYYMMDD" in out


def test_cli_registers_every_provider_without_help_from_test_imports():
    """The CLI module alone must register all providers.

    Importing `callsigns.cli` in a fresh interpreter has to be enough: test
    modules that import a provider directly would otherwise mask a missing
    registration import here.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from callsigns.providers import provider_keys\n"
            "import callsigns.cli\n"
            "print(','.join(provider_keys()))",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    registered = set(result.stdout.strip().split(","))
    expected = {
        # leaderboards and spots
        "pota-hunters",
        "rbn-cw",
        "sota-activator",
        "sota-chaser",
        # CQ contests
        "cqww-cw",
        "cqwpx-cw",
        "cq160-cw",
        "cqww-rtty",
        "cqwpx-rtty",
        "ww-digi",
        # ARRL contests
        "arrl-dxcw",
        "arrl-dxph",
        "arrl-sscw",
        "arrl-ssph",
        "arrl-10m",
        "arrl-160m",
        "arrl-iaruhf",
        "arrl-rttyru",
        "arrl-dig",
        "arrl-eme",
        "arrl-janvhf",
        "arrl-junvhf",
        "arrl-sepvhf",
        "arrl-222",
        "arrl-10g",
        # CW clubs
        "naqcc-sprint",
        "skcc-wes",
        "cwops-cwopen",
        "fists-sprint",
    }
    assert registered == expected


@pytest.fixture
def fake_contest(monkeypatch):
    base = pathlib.Path(__file__).parent / "fixtures"
    listing = (base / "cq_listing.html").read_text()
    log = (base / "cabrillo_cqww.log").read_text()

    class FakeClient:
        def __init__(self):
            self.urls = []

        def get_text(self, url, **kwargs):
            self.urls.append(url)
            return listing

        def get_bytes(self, url, **kwargs):
            self.urls.append(url)
            return log.encode()

        def content_length(self, url, **kwargs):
            return 100

    client = FakeClient()
    monkeypatch.setattr("callsigns.providers.contest.cq.HttpClient", lambda: client)
    monkeypatch.setattr("callsigns.cache.HttpClient", lambda: client)
    return client


def test_contest_refresh_and_export(tmp_path, fake_contest):
    store = tmp_path / "C.xlsx"
    assert (
        main(
            [
                "refresh",
                "cqww-cw",
                "-y",
                "2025",
                "--store",
                str(store),
                "--top-logs",
                "1",
            ]
        )
        == 0
    )
    assert WorkbookStore(store).sheet_names() == ["2025"]
    assert (
        main(
            [
                "export",
                "cqww-cw",
                "scp",
                "-y",
                "2025",
                "--store",
                str(store),
                "--out",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert "YT6X" in (tmp_path / "CQWW-CW_Calls_2025.scp").read_text()


def test_top_logs_flag_limits_downloads(tmp_path, fake_contest):
    main(
        [
            "refresh",
            "cqww-cw",
            "-y",
            "2025",
            "--store",
            str(tmp_path / "C.xlsx"),
            "--top-logs",
            "1",
        ]
    )
    assert len([u for u in fake_contest.urls if u.endswith(".log")]) == 1


def test_jobs_flag_is_accepted(tmp_path, fake_contest):
    assert (
        main(
            [
                "refresh",
                "cqww-cw",
                "-y",
                "2025",
                "--store",
                str(tmp_path / "C.xlsx"),
                "--jobs",
                "2",
                "--top-logs",
                "1",
            ]
        )
        == 0
    )


def test_top_logs_rejected_on_a_single_request_provider(tmp_path, fake_api, capsys):
    code = main(
        [
            "refresh",
            "pota-hunters",
            "-y",
            "all",
            "--store",
            str(tmp_path / "S.xlsx"),
            "--top-logs",
            "5",
        ]
    )
    assert code == ExitCode.VALIDATION
    assert "--top-logs" in capsys.readouterr().err


def test_top_logs_rejected_on_rbn_which_downloads_days_not_logs(
    tmp_path, fake_rbn, capsys
):
    code = main(
        [
            "refresh",
            "rbn-cw",
            "-y",
            "20251129",
            "-o",
            "cw",
            "--store",
            str(tmp_path / "R.xlsx"),
            "--top-logs",
            "5",
        ]
    )
    assert code == ExitCode.VALIDATION
    assert "--top-logs" in capsys.readouterr().err


def test_harvest_dry_run_reports_without_fetching(tmp_path, fake_api, capsys):
    code = main(["harvest", "pota-hunters", "-y", "all", "--dry-run"])
    assert code == ExitCode.OK
    out = capsys.readouterr()
    assert "pota-hunters" in out.out
    assert "estimated" in out.out
    assert "dry run" in out.err


def test_harvest_one_failure_does_not_abandon_the_rest(tmp_path, monkeypatch, capsys):
    from callsigns.errors import UpstreamError

    calls = []

    class Boom:
        def get_bytes(self, url, **kwargs):
            calls.append(url)
            raise UpstreamError("unreachable")

    monkeypatch.setattr("callsigns.providers.pota.HttpClient", lambda **kw: Boom())
    monkeypatch.setattr("callsigns.providers.sota.HttpClient", lambda **kw: Boom())
    code = main(
        [
            "harvest",
            "pota-hunters",
            "sota-activator",
            "-y",
            "all",
            "--store",
            str(tmp_path / "S.xlsx"),
        ]
    )
    err = capsys.readouterr().err
    assert code == ExitCode.UPSTREAM
    assert err.count("FAILED") == 2, "both providers should be attempted"
    assert "re-run to retry" in err


def test_roster_needs_stores(tmp_path, capsys):
    code = main(["roster", "build", "--stores", str(tmp_path)])
    assert code == ExitCode.VALIDATION
    assert "no provider stores" in capsys.readouterr().err


def test_roster_build_writes_a_workbook(tmp_path, fake_api):
    main(
        [
            "refresh",
            "pota-hunters",
            "-y",
            "all",
            "--store",
            str(tmp_path / "POTA-Hunters.xlsx"),
        ]
    )
    code = main(["roster", "build", "--stores", str(tmp_path), "--out", str(tmp_path)])
    assert code == ExitCode.OK
    assert (tmp_path / "Roster.xlsx").is_file()


def test_roster_query_filters_by_mode(tmp_path, fake_api, capsys):
    main(
        [
            "refresh",
            "pota-hunters",
            "-y",
            "all",
            "--store",
            str(tmp_path / "POTA-Hunters.xlsx"),
        ]
    )
    main(["roster", "query", "--stores", str(tmp_path), "--mode", "cw"])
    out = capsys.readouterr().out
    assert "K2UPD" in out
    assert "callsigns matched" in out


def test_roster_exports_through_the_exporter_registry(tmp_path, fake_api):
    main(
        [
            "refresh",
            "pota-hunters",
            "-y",
            "all",
            "--store",
            str(tmp_path / "POTA-Hunters.xlsx"),
        ]
    )
    code = main(
        [
            "roster",
            "query",
            "--stores",
            str(tmp_path),
            "--format",
            "scp",
            "--out",
            str(tmp_path),
        ]
    )
    assert code == ExitCode.OK
    assert (tmp_path / "Roster-Query.scp").is_file()


def test_roster_overlap_prints_a_matrix(tmp_path, fake_api, capsys):
    main(
        [
            "refresh",
            "pota-hunters",
            "-y",
            "all",
            "--store",
            str(tmp_path / "POTA-Hunters.xlsx"),
        ]
    )
    main(["roster", "overlap", "--stores", str(tmp_path)])
    assert "pota-hunters" in capsys.readouterr().out


def test_harvest_reports_parallel_and_sequential_estimates(tmp_path, fake_api, capsys):
    main(["harvest", "pota-hunters", "sota-activator", "-y", "all", "--dry-run"])
    out = capsys.readouterr().out
    assert "host(s)" in out
    assert "one host at a time" in out, "should show what serialising would cost"


def test_harvest_paces_every_provider_not_just_bulk_ones(tmp_path, monkeypatch):
    """A club provider asked for many periods must be paced like any other.

    Non-bulk providers build their own HttpClient in __init__, so unless the
    harvest replaces it their requests escape the limiter entirely.
    """
    seen = []

    class SpyLimiter(RateLimiter):
        def acquire(self, host, *, probe=False):
            seen.append(host)
            return 0.0

    monkeypatch.setattr(
        "callsigns.cli.RateLimiter",
        lambda *a, **k: SpyLimiter(
            HostPolicy(0.0, 0.0, 99), sleeper=lambda s: None, host_policies={}
        ),
    )

    sample = pathlib.Path(__file__).parent / "fixtures" / "naqcc_scoreboard.html"
    body = sample.read_bytes()

    class FakeSession:
        headers: dict[str, str] = {}

        def mount(self, prefix, adapter):
            pass

        def get(self, url, timeout=None, headers=None):
            return type("R", (), {"status_code": 200, "content": body, "headers": {}})()

    monkeypatch.setattr("callsigns.http.requests.Session", lambda: FakeSession())
    code = main(
        [
            "harvest",
            "naqcc-sprint",
            "-y",
            "202501,202502,202503",
            "--store",
            str(tmp_path / "N.xlsx"),
        ]
    )
    assert code == ExitCode.OK
    assert seen.count("naqcc.info") == 3, f"expected 3 paced requests, saw {seen}"


def test_harvest_archives_raw_payloads(tmp_path, fake_api):
    """The harvest path must keep the bytes, not only the parsed rows."""
    raw = tmp_path / "raw"
    main(
        [
            "harvest",
            "pota-hunters",
            "-y",
            "all",
            "--store",
            str(tmp_path / "S.xlsx"),
            "--cache",
            str(raw),
        ]
    )
    archived = raw / "pota-hunters" / "all.json"
    assert archived.is_file()
    assert json.loads(archived.read_text())[0]["activeCallsign"] == "SM3NRY"


def test_roster_query_does_not_overwrite_the_built_workbook(tmp_path, fake_api):
    """`roster build` and `roster query --format xlsx` must not collide."""
    main(
        [
            "refresh",
            "pota-hunters",
            "-y",
            "all",
            "--store",
            str(tmp_path / "POTA-Hunters.xlsx"),
        ]
    )
    main(["roster", "build", "--stores", str(tmp_path), "--out", str(tmp_path)])
    built = (tmp_path / "Roster.xlsx").read_bytes()
    main(
        [
            "roster",
            "query",
            "--stores",
            str(tmp_path),
            "--out",
            str(tmp_path),
            "--format",
            "xlsx",
            "-d",
            "1",
        ]
    )
    assert (tmp_path / "Roster.xlsx").read_bytes() == built
    assert (tmp_path / "Roster-Query.xlsx").is_file()


def test_roster_query_honours_an_explicit_basename(tmp_path, fake_api):
    main(
        [
            "refresh",
            "pota-hunters",
            "-y",
            "all",
            "--store",
            str(tmp_path / "POTA-Hunters.xlsx"),
        ]
    )
    main(
        [
            "roster",
            "query",
            "--stores",
            str(tmp_path),
            "--out",
            str(tmp_path),
            "--format",
            "scp",
            "--basename",
            "Top500",
        ]
    )
    assert (tmp_path / "Top500.scp").is_file()
