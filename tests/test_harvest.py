import pytest

from callsigns.cache import FileCache
from callsigns.harvest import HarvestPlan, format_duration, plan_for, total_seconds
from callsigns.pacing import HostPolicy, RateLimiter
from callsigns.providers.base import Column, ModeSpec, Provider
from callsigns.providers.contest.base import ContestLogProvider, LogRef


def limiter():
    return RateLimiter(
        HostPolicy(
            min_interval=4.0, jitter=0.0, burst=0, probe_interval=1.0, probe_jitter=0.0
        ),
        clock=lambda: 0.0,
        sleeper=lambda s: None,
        host_policies={},
    )


class Single(Provider):
    key = "single"
    label = "Single"
    store_name = "S.xlsx"
    export_prefix = "S"
    calls_prefix = "S"
    columns = (Column("Callsign", "Callsign", str),)
    callsign_key = "Callsign"
    modes = {"all": ModeSpec.all_modes()}

    def periods(self):
        return ("2025",)

    def default_periods(self):
        return ("2025",)

    def period_label(self, period):
        return period

    def source_url(self, period):
        return "https://single.test/api"

    def fetch(self, period, mode):
        return []


class Contest(ContestLogProvider):
    key = "contest"
    label = "Contest"
    store_name = "C.xlsx"
    export_prefix = "C"
    calls_prefix = "C"
    first_year = 2019

    def source_url(self, period):
        return "https://contest.test/publiclogs/"

    def list_entrants(self, period):
        return [
            LogRef(callsign=f"K{i}AA", url=f"https://contest.test/k{i}aa.log")
            for i in range(10)
        ]

    def probe_sizes(self, refs):
        return [LogRef(r.callsign, r.url, size=100) for r in refs]

    def list_logs(self, period):
        return self.probe_sizes(self.list_entrants(period))


def test_single_request_provider_costs_one_request(tmp_path):
    plan = plan_for(Single(), "2025", None, limiter())
    assert plan.total_items == 1
    assert plan.probe_items == 0
    assert plan.estimated_seconds == pytest.approx(4.0)


def test_single_request_plan_names_the_host():
    assert plan_for(Single(), "2025", None, limiter()).host == "single.test"


def test_contest_plan_counts_probes_and_downloads(tmp_path):
    provider = Contest(cache=FileCache(tmp_path), top_logs=4)
    plan = plan_for(provider, "2025", FileCache(tmp_path), limiter())
    assert plan.probe_items == 10
    assert plan.total_items == 4
    # ten probes at 1s, four downloads at 4s
    assert plan.estimated_seconds == pytest.approx(10 * 1.0 + 4 * 4.0)


def test_top_logs_zero_plans_the_whole_field(tmp_path):
    provider = Contest(cache=FileCache(tmp_path), top_logs=0)
    plan = plan_for(provider, "2025", FileCache(tmp_path), limiter())
    assert plan.total_items == 10


def test_cached_items_reduce_the_estimate(tmp_path):
    cache = FileCache(tmp_path)
    cache._write("2025/K0AA.log", b"x")
    cache._write("2025/K1AA.log", b"x")
    provider = Contest(cache=cache, top_logs=10)
    plan = plan_for(provider, "2025", cache, limiter())
    assert plan.cached_items == 2
    assert plan.pending_items == 8
    assert plan.estimated_seconds == pytest.approx(10 * 1.0 + 8 * 4.0)


def test_a_fully_cached_field_costs_only_the_probes(tmp_path):
    cache = FileCache(tmp_path)
    for i in range(10):
        cache._write(f"2025/K{i}AA.log", b"x")
    plan = plan_for(Contest(cache=cache, top_logs=10), "2025", cache, limiter())
    assert plan.pending_items == 0
    assert plan.estimated_seconds == pytest.approx(10 * 1.0)


def test_pending_never_goes_negative():
    plan = HarvestPlan(
        "p",
        "2025",
        "h",
        total_items=3,
        cached_items=9,
        probe_items=0,
        estimated_seconds=0.0,
    )
    assert plan.pending_items == 0


def test_total_sums_because_providers_run_in_sequence():
    plans = [
        HarvestPlan("a", "1", "h", 1, 0, 0, 100.0),
        HarvestPlan("b", "1", "h", 1, 0, 0, 50.0),
    ]
    assert total_seconds(plans) == pytest.approx(150.0)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (45, "45s"),
        (90, "2m"),
        (3600, "1h 0m"),
        (9600, "2h 40m"),
        (7200, "2h 0m"),
        (90000, "1d 1h"),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_format_duration_of_a_negative_is_zero():
    assert format_duration(-5) == "0s"


def test_slow_hosts_produce_much_larger_estimates(tmp_path):
    """A host on the slow policy should visibly cost more."""
    fast = RateLimiter(clock=lambda: 0.0, sleeper=lambda s: None, host_policies={})
    slow = RateLimiter(clock=lambda: 0.0, sleeper=lambda s: None)
    fast_plan = plan_for(Single(), "2025", None, fast)

    class SlowSingle(Single):
        key = "slow-single"

        def source_url(self, period):
            return "https://www.skccgroup.com/x"

    slow_plan = plan_for(SlowSingle(), "2025", None, slow)
    assert slow_plan.estimated_seconds > 3 * fast_plan.estimated_seconds


def test_total_is_the_longest_host_because_hosts_run_in_parallel():
    from callsigns.harvest import sequential_seconds

    plans = [
        HarvestPlan("a", "1", "host-a", 1, 0, 0, 100.0),
        HarvestPlan("b", "1", "host-b", 1, 0, 0, 50.0),
    ]
    assert total_seconds(plans) == pytest.approx(100.0)
    assert sequential_seconds(plans) == pytest.approx(150.0)


def test_same_host_tasks_add_up_because_they_stay_in_sequence():
    plans = [
        HarvestPlan("a", "1", "same", 1, 0, 0, 100.0),
        HarvestPlan("b", "1", "same", 1, 0, 0, 50.0),
    ]
    assert total_seconds(plans) == pytest.approx(150.0)


def test_total_of_nothing():
    assert total_seconds([]) == 0.0


def test_group_by_host_keeps_order_within_a_host():
    from callsigns.harvest import group_by_host

    provider = Single()
    a1 = (provider, "1", HarvestPlan("a", "1", "h1", 1, 0, 0, 1.0))
    b1 = (provider, "1", HarvestPlan("b", "1", "h2", 1, 0, 0, 1.0))
    a2 = (provider, "2", HarvestPlan("a", "2", "h1", 1, 0, 0, 1.0))
    grouped = group_by_host([a1, b1, a2])
    assert list(grouped) == ["h1", "h2"]
    assert grouped["h1"] == [a1, a2]
