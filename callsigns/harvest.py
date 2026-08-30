"""Harvest planning and execution.

A full collection spans days, so it has to be predictable before it starts and
resumable after it stops. Planning answers "how many requests, and how long"
without doing the work; running works through what is left, and anything
already cached is skipped.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from callsigns.cache import FileCache
from callsigns.pacing import RateLimiter
from callsigns.providers.base import Provider
from callsigns.providers.contest.base import ContestLogProvider

_LOGGER = logging.getLogger(__name__)

#: Providers that fetch one document per period rather than a field of files.
_SINGLE_REQUEST_ITEMS: int = 1


@dataclass(frozen=True, slots=True)
class HarvestPlan:
    """What one provider and period will cost."""

    provider: str
    period: str
    host: str
    #: Documents that make up the dataset: logs for a contest, one page
    #: otherwise.
    total_items: int
    #: Of those, how many are already on disk.
    cached_items: int
    #: ``HEAD`` requests needed to rank the field before downloading.
    probe_items: int
    #: Seconds the remaining work is expected to take at the current pace.
    estimated_seconds: float

    @property
    def pending_items(self) -> int:
        """Return how many documents still need fetching."""
        return max(0, self.total_items - self.cached_items)


def _host_of(provider: Provider, period: str) -> str:
    """Return the hostname a provider fetches from.

    Args:
        provider: The provider.
        period: A validated period token.

    Returns:
        The hostname, or the empty string when it cannot be derived.
    """
    import urllib.parse

    return urllib.parse.urlsplit(provider.source_url(period)).hostname or ""


def plan_for(
    provider: Provider,
    period: str,
    cache: FileCache | None,
    limiter: RateLimiter,
) -> HarvestPlan:
    """Work out what one provider and period will cost.

    Listing is cheap and unavoidable — a contest field cannot be counted
    without asking — so this issues the listing request and no more.

    Args:
        provider: The provider to plan for.
        period: A validated period token.
        cache: The download cache, when the provider uses one.
        limiter: Pacing, consulted for its intervals.

    Returns:
        The plan.

    Raises:
        UpstreamError: A listing could not be retrieved.
    """
    host = _host_of(provider, period)

    if not isinstance(provider, ContestLogProvider):
        seconds = limiter.interval_for(host) * _SINGLE_REQUEST_ITEMS
        return HarvestPlan(
            provider=provider.key,
            period=period,
            host=host,
            total_items=_SINGLE_REQUEST_ITEMS,
            cached_items=0,
            probe_items=0,
            estimated_seconds=seconds,
        )

    refs = (
        provider.list_entrants(period)
        if hasattr(provider, "list_entrants")
        else provider.list_logs(period)
    )
    probes = len(refs) if hasattr(provider, "probe_sizes") else 0
    selected = (
        len(refs) if provider.top_logs <= 0 else min(provider.top_logs, len(refs))
    )

    cached = 0
    if cache is not None:
        keys = [(f"{period}/{ref.callsign}.log", ref.url) for ref in refs]
        cached = len(keys) - len(cache.pending(keys))

    remaining = max(0, selected - cached)
    seconds = probes * limiter.interval_for(
        host, probe=True
    ) + remaining * limiter.interval_for(host)
    return HarvestPlan(
        provider=provider.key,
        period=period,
        host=host,
        total_items=selected,
        cached_items=min(cached, selected),
        probe_items=probes,
        estimated_seconds=seconds,
    )


def format_duration(seconds: float) -> str:
    """Render a duration in units a person can act on.

    Args:
        seconds: Duration in seconds.

    Returns:
        Text such as ``"3m"``, ``"2h 40m"`` or ``"1d 6h"``.
    """
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f}m"
    # Truncate the larger unit rather than rounding it: 9,600 seconds is
    # "2h 40m", and rounding the hours would render it "3h 40m".
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h {minutes - hours * 60:.0f}m"
    days = hours // 24
    return f"{days}d {hours - days * 24}h"


def group_by_host(
    tasks: Sequence[tuple[Provider, str, HarvestPlan]],
) -> dict[str, list[tuple[Provider, str, HarvestPlan]]]:
    """Group harvest tasks by the host they contact.

    Work for different hosts can proceed at the same time without any server
    seeing more than its own allowance, because pacing is per host. Work for
    the same host must stay in sequence.

    Args:
        tasks: Provider, period and plan triples.

    Returns:
        Tasks keyed by hostname, each list in its original order.
    """
    grouped: dict[str, list[tuple[Provider, str, HarvestPlan]]] = {}
    for task in tasks:
        grouped.setdefault(task[2].host, []).append(task)
    return grouped


def total_seconds(plans: Sequence[HarvestPlan]) -> float:
    """Return the wall time a set of plans will take.

    Hosts are worked in parallel and each host's own tasks in sequence, so the
    total is the longest host rather than the sum of everything.

    Args:
        plans: The plans to total.

    Returns:
        Seconds.
    """
    if not plans:
        return 0.0
    per_host: dict[str, float] = {}
    for plan in plans:
        per_host[plan.host] = per_host.get(plan.host, 0.0) + plan.estimated_seconds
    return max(per_host.values())


def sequential_seconds(plans: Sequence[HarvestPlan]) -> float:
    """Return what the same work would cost one host at a time.

    Args:
        plans: The plans to total.

    Returns:
        Seconds.
    """
    return sum(plan.estimated_seconds for plan in plans)
