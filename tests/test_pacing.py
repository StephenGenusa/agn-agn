import random
import threading

import pytest

from callsigns.pacing import (
    DEFAULT_POLICY,
    HOST_POLICIES,
    SLOW_POLICY,
    HostPolicy,
    RateLimiter,
)


class FakeClock:
    """A monotonic clock that only advances when something sleeps."""

    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        assert seconds >= 0
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


def make(policy=None, seed=1):
    clock = FakeClock()
    limiter = RateLimiter(
        policy=policy or HostPolicy(min_interval=4.0, jitter=0.0, burst=1),
        clock=clock.time,
        sleeper=clock.sleep,
        rng=random.Random(seed),
    )
    return limiter, clock


def test_first_request_to_a_host_does_not_wait():
    limiter, clock = make()
    assert limiter.acquire("example.test") == 0.0
    assert clock.slept == []


def test_second_immediate_request_waits_the_minimum_interval():
    limiter, clock = make()
    limiter.acquire("example.test")
    waited = limiter.acquire("example.test")
    assert waited == pytest.approx(4.0)
    assert clock.slept == [pytest.approx(4.0)]


def test_no_wait_when_enough_time_already_passed():
    limiter, clock = make()
    limiter.acquire("example.test")
    clock.advance(10.0)
    assert limiter.acquire("example.test") == 0.0


def test_partial_wait_when_some_time_passed():
    limiter, clock = make()
    limiter.acquire("example.test")
    clock.advance(1.5)
    assert limiter.acquire("example.test") == pytest.approx(2.5)


def test_hosts_are_paced_independently():
    limiter, clock = make()
    limiter.acquire("a.test")
    assert limiter.acquire("b.test") == 0.0
    assert clock.slept == []


def test_jitter_varies_the_interval_within_bounds():
    limiter, clock = make(HostPolicy(min_interval=4.0, jitter=4.0, burst=1))
    waits = []
    for _ in range(20):
        limiter.acquire("example.test")
        waits.append(limiter.acquire("example.test"))
        clock.advance(100.0)
    assert all(4.0 <= w <= 8.0 for w in waits)
    assert len(set(waits)) > 1, "jitter should not produce a constant interval"


def test_jitter_is_deterministic_for_a_given_seed():
    a, _ = make(HostPolicy(4.0, 4.0, 1), seed=7)
    b, _ = make(HostPolicy(4.0, 4.0, 1), seed=7)
    a.acquire("x.test")
    b.acquire("x.test")
    assert a.acquire("x.test") == b.acquire("x.test")


def test_burst_allows_a_few_requests_before_pacing_starts():
    limiter, _ = make(HostPolicy(min_interval=4.0, jitter=0.0, burst=3))
    assert limiter.acquire("x.test") == 0.0
    assert limiter.acquire("x.test") == 0.0
    assert limiter.acquire("x.test") == 0.0
    assert limiter.acquire("x.test") == pytest.approx(4.0)


def test_per_host_policy_overrides_the_default():
    limiter, _ = make()
    limiter.set_policy("fast.test", HostPolicy(min_interval=0.0, jitter=0.0, burst=1))
    limiter.acquire("fast.test")
    assert limiter.acquire("fast.test") == 0.0


def test_policy_for_returns_the_default_for_unknown_hosts():
    limiter, _ = make()
    assert limiter.policy_for("unknown.test").min_interval == 4.0


def test_default_policy_is_unhurried():
    assert DEFAULT_POLICY.min_interval >= 4.0
    assert DEFAULT_POLICY.jitter > 0


def test_slow_policy_is_much_gentler_than_the_default():
    assert SLOW_POLICY.min_interval >= 3 * DEFAULT_POLICY.min_interval


def test_skcc_gets_the_slow_policy_by_default():
    """SKCC has named ham-radio crawlers in its block list, so tread lightly."""
    assert HOST_POLICIES["www.skccgroup.com"] is SLOW_POLICY


def test_built_in_host_policies_are_applied_without_configuration():
    limiter = RateLimiter(clock=lambda: 0.0, sleeper=lambda s: None)
    assert limiter.policy_for("www.skccgroup.com").min_interval >= 15.0


def test_acquire_is_thread_safe():
    limiter, _ = make(HostPolicy(min_interval=0.0, jitter=0.0, burst=1))
    errors = []

    def worker():
        try:
            for _ in range(50):
                limiter.acquire("x.test")
        except Exception as exc:  # pragma: no cover - only on a real bug
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_stats_report_what_was_spent():
    limiter, _ = make()
    limiter.acquire("x.test")
    limiter.acquire("x.test")
    stats = limiter.stats()
    assert stats["x.test"].requests == 2
    assert stats["x.test"].waited == pytest.approx(4.0)


def test_probes_are_paced_faster_than_downloads():
    limiter, _ = make(
        HostPolicy(
            min_interval=4.0, jitter=0.0, burst=1, probe_interval=1.0, probe_jitter=0.0
        )
    )
    limiter.acquire("x.test")
    assert limiter.acquire("x.test", probe=True) == pytest.approx(1.0)


def test_interval_for_reports_the_mean_gap():
    limiter, _ = make(
        HostPolicy(
            min_interval=4.0, jitter=4.0, burst=1, probe_interval=1.0, probe_jitter=1.0
        )
    )
    assert limiter.interval_for("x.test") == pytest.approx(6.0)
    assert limiter.interval_for("x.test", probe=True) == pytest.approx(1.5)


def test_slow_hosts_also_probe_slowly():
    limiter = RateLimiter(clock=lambda: 0.0, sleeper=lambda s: None)
    assert limiter.interval_for("www.skccgroup.com", probe=True) >= 10.0
