"""Per-host request pacing.

The tool fetches thousands of files from a handful of volunteer-run servers.
Spread over days at a few seconds per request it is invisible; issued as fast
as the network allows it is a burden. This module enforces the former.

Pacing is per host, so a harvest spanning several sites proceeds in parallel
without any one site seeing more than its allowance. The clock, sleeper and
random source are injected so the behaviour can be tested without waiting.
"""

import logging
import random
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HostPolicy:
    """How gently to treat one host."""

    #: Seconds that must pass between requests, before jitter.
    min_interval: float
    #: Upper bound of a uniform random addition to the interval. Varying the
    #: gap keeps a long harvest from arriving as a perfectly regular pulse.
    jitter: float
    #: Requests allowed back to back before pacing applies, so a listing plus
    #: its first page are not slowed pointlessly.
    burst: int = 1
    #: Minimum gap between ``HEAD`` size probes. A probe returns no body and
    #: costs the server a stat call rather than a file read, so it is paced
    #: faster than a download. Size-ranking a large field would otherwise cost
    #: more than fetching it.
    probe_interval: float = 1.0
    #: Jitter added to :attr:`probe_interval`.
    probe_jitter: float = 1.0


@dataclass(slots=True)
class HostStats:
    """What a harvest has cost one host so far."""

    requests: int = 0
    waited: float = 0.0


#: Unhurried by default: roughly one request every four to eight seconds.
#: A 4,000-log contest takes about six hours, which is the intended pace.
DEFAULT_POLICY: HostPolicy = HostPolicy(min_interval=4.0, jitter=4.0, burst=2)

#: For hosts that have signalled they have had trouble with crawlers. Roughly
#: one request every twenty to forty seconds — slower than a person clicking
#: through the site by hand.
SLOW_POLICY: HostPolicy = HostPolicy(
    min_interval=20.0, jitter=20.0, burst=1, probe_interval=10.0, probe_jitter=10.0
)

#: Hosts that get something other than the default.
#:
#: skccgroup.com names two ham-radio crawlers in its robots.txt block list
#: (HamLogContestCrawler, OnlyHams), so it has been burned by exactly this kind
#: of traffic before and gets the slow policy.
HOST_POLICIES: Mapping[str, HostPolicy] = MappingProxyType(
    {
        "www.skccgroup.com": SLOW_POLICY,
        "skccgroup.com": SLOW_POLICY,
        "cwops.org": SLOW_POLICY,
        "cwops.contesting.com": SLOW_POLICY,
        "naqcc.info": SLOW_POLICY,
    }
)


class RateLimiter:
    """Enforces a per-host minimum gap between requests."""

    def __init__(
        self,
        policy: HostPolicy = DEFAULT_POLICY,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        host_policies: Mapping[str, HostPolicy] = HOST_POLICIES,
    ) -> None:
        """Initialise the limiter.

        Args:
            policy: Default policy for hosts with no specific one.
            clock: Monotonic time source, in seconds.
            sleeper: Blocking sleep function.
            rng: Random source for jitter. Defaults to a fresh ``Random``.
            host_policies: Built-in per-host overrides.
        """
        self._default = policy
        self._clock = clock
        self._sleeper = sleeper
        self._rng = rng if rng is not None else random.Random()
        self._policies: dict[str, HostPolicy] = dict(host_policies)
        self._last: dict[str, float] = {}
        self._budget: dict[str, int] = {}
        self._stats: dict[str, HostStats] = {}
        self._lock = threading.Lock()

    def set_policy(self, host: str, policy: HostPolicy) -> None:
        """Set a host-specific policy.

        Args:
            host: Hostname the policy applies to.
            policy: The policy to use.
        """
        with self._lock:
            self._policies[host] = policy

    def policy_for(self, host: str) -> HostPolicy:
        """Return the policy in force for a host.

        Args:
            host: Hostname to look up.

        Returns:
            The host-specific policy, or the default.
        """
        with self._lock:
            return self._policies.get(host, self._default)

    def stats(self) -> dict[str, HostStats]:
        """Return a snapshot of per-host request counts and time spent waiting.

        Returns:
            A copy, keyed by hostname.
        """
        with self._lock:
            return {
                host: HostStats(requests=s.requests, waited=s.waited)
                for host, s in self._stats.items()
            }

    def interval_for(self, host: str, *, probe: bool = False) -> float:
        """Return the average gap this host is paced at.

        Args:
            host: Hostname.
            probe: Whether the request is a ``HEAD`` size probe.

        Returns:
            Mean seconds between requests, for estimating a harvest's length.
        """
        policy = self.policy_for(host)
        if probe:
            return policy.probe_interval + policy.probe_jitter / 2
        return policy.min_interval + policy.jitter / 2

    def acquire(self, host: str, *, probe: bool = False) -> float:
        """Block until this host may be contacted again.

        Args:
            host: Hostname about to be contacted.
            probe: Whether this is a ``HEAD`` size probe, which is paced
                faster because it costs the server far less than a download.

        Returns:
            Seconds spent waiting; zero when no wait was needed.
        """
        with self._lock:
            policy = self._policies.get(host, self._default)
            entry = self._stats.setdefault(host, HostStats())
            entry.requests += 1
            now = self._clock()
            budget = self._budget.get(host, policy.burst)

            if budget > 0:
                self._budget[host] = budget - 1
                self._last[host] = now
                return 0.0

            if probe:
                interval = policy.probe_interval + self._rng.uniform(
                    0.0, policy.probe_jitter
                )
            else:
                interval = policy.min_interval + self._rng.uniform(0.0, policy.jitter)
            last = self._last.get(host)
            elapsed = now - last if last is not None else interval
            wait = max(0.0, interval - elapsed)
            self._last[host] = now + wait
            entry.waited += wait

        if wait > 0:
            _LOGGER.debug("pacing %s: sleeping %.1fs", host, wait)
            self._sleeper(wait)
        return wait
