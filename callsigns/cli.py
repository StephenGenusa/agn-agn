"""Command-line interface.

This is the only module that catches :class:`CallsignsError`, and the only
module that writes to stdout or stderr.
"""

import argparse
import concurrent.futures
import datetime as dt
import logging
import pathlib
import sys
import threading
from collections.abc import Callable, Sequence

from callsigns.archive import archive_raw
from callsigns.cache import FileCache
from callsigns.errors import CallsignsError, ExitCode, ValidationError, exit_code_for

# The ``as _name  # noqa: F401`` imports exist for their import side effect:
# importing a module runs its @register decorator. They are kept in this one
# sorted block so ruff's import ordering stays satisfied.
from callsigns.exporters import dta as _dta  # noqa: F401
from callsigns.exporters import exporter_names, get_exporter
from callsigns.exporters import lst as _lst  # noqa: F401
from callsigns.exporters import scp as _scp  # noqa: F401
from callsigns.exporters import xlsx as _xlsx  # noqa: F401
from callsigns.exporters.base import ExportOptions
from callsigns.harvest import (
    HarvestPlan,
    format_duration,
    group_by_host,
    plan_for,
    sequential_seconds,
    total_seconds,
)
from callsigns.http import HttpClient
from callsigns.pacing import DEFAULT_POLICY, HostPolicy, RateLimiter
from callsigns.providers import all_providers, get_provider, provider_keys
from callsigns.providers import pota as _pota  # noqa: F401
from callsigns.providers import rbn as _rbn  # noqa: F401
from callsigns.providers import sota as _sota  # noqa: F401
from callsigns.providers.base import Column, Provider
from callsigns.providers.clubs import cwops as _cwops  # noqa: F401
from callsigns.providers.clubs import fists as _fists  # noqa: F401
from callsigns.providers.clubs import naqcc as _naqcc  # noqa: F401
from callsigns.providers.clubs import skcc as _skcc  # noqa: F401
from callsigns.providers.contest import arrl as _arrl  # noqa: F401
from callsigns.providers.contest import cq as _cq  # noqa: F401
from callsigns.providers.contest.base import ContestLogProvider
from callsigns.roster import (
    ROSTER_COLUMNS,
    RosterProvider,
    build_roster,
    overlap_matrix,
)
from callsigns.select import filter_rows, limit_rows
from callsigns.store import SheetData, SheetMeta, WorkbookStore

_LOGGER = logging.getLogger(__name__)

DATA_DIR: pathlib.Path = pathlib.Path("data")
RAW_DIR: pathlib.Path = DATA_DIR / "raw"


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser.

    Returns:
        A parser with the ``providers``, ``refresh`` and ``export``
        subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="callsigns",
        description="Mirror callsign-activity data and export it to other tools.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log progress to stderr"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("providers", help="list registered providers")

    refresh = sub.add_parser("refresh", help="fetch periods into the store")
    refresh.add_argument("provider")
    refresh.add_argument(
        "-y", "--year", default=None, help="comma-separated periods, or 'all'"
    )
    refresh.add_argument("-o", "--operating-mode", default=None)
    refresh.add_argument("--store", type=pathlib.Path, default=None)
    refresh.add_argument(
        "--raw-dir",
        type=pathlib.Path,
        default=None,
        help=f"where to archive raw payloads (default {RAW_DIR})",
    )
    refresh.add_argument(
        "--cache",
        type=pathlib.Path,
        default=None,
        help="download cache for bulk providers (default data/raw/<provider>)",
    )
    refresh.add_argument(
        "--top-logs",
        type=int,
        default=None,
        help="for contest providers, how many logs to download (0 = all)",
    )
    refresh.add_argument(
        "--jobs",
        type=int,
        default=None,
        help="maximum concurrent downloads for bulk providers",
    )

    export = sub.add_parser("export", help="write an export from the store")
    export.add_argument("provider")
    export.add_argument("format", choices=sorted(exporter_names()))
    export.add_argument("-y", "--year", default="all")
    export.add_argument("-o", "--operating-mode", default="all")
    export.add_argument("-d", "--download-rows", type=int, default=None)
    export.add_argument("--out", type=pathlib.Path, default=None)
    export.add_argument("--basename", default=None)
    export.add_argument("--store", type=pathlib.Path, default=None)

    harvest = sub.add_parser(
        "harvest", help="collect data at a polite pace, resumable across days"
    )
    harvest.add_argument(
        "provider", nargs="*", help="providers to harvest; omit for all of them"
    )
    harvest.add_argument("-y", "--year", default=None, help="comma-separated periods")
    harvest.add_argument("-o", "--operating-mode", default=None)
    harvest.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be fetched and how long it would take",
    )
    harvest.add_argument(
        "--pace",
        type=float,
        default=None,
        help=(
            "seconds between requests to one host "
            f"(default {DEFAULT_POLICY.min_interval:.0f})"
        ),
    )
    harvest.add_argument("--top-logs", type=int, default=None)
    harvest.add_argument("--store", type=pathlib.Path, default=None)
    harvest.add_argument("--cache", type=pathlib.Path, default=None)

    roster = sub.add_parser(
        "roster", help="rank callsigns by breadth of activity across every store"
    )
    roster.add_argument(
        "action", choices=("build", "query", "overlap"), help="what to do"
    )
    roster.add_argument(
        "--min-sources",
        type=int,
        default=0,
        help="keep callsigns confirmed in at least this many sources",
    )
    roster.add_argument("--mode", default=None, help="keep callsigns using this mode")
    roster.add_argument("-d", "--download-rows", type=int, default=0)
    roster.add_argument("--format", default=None, choices=sorted(exporter_names()))
    roster.add_argument("--out", type=pathlib.Path, default=None)
    roster.add_argument(
        "--basename",
        default=None,
        help="filename stem for an export; keeps a query from overwriting the "
        "workbook that `roster build` wrote",
    )
    roster.add_argument("--stores", type=pathlib.Path, default=None)
    return parser


def _store_for(provider: Provider, override: pathlib.Path | None) -> WorkbookStore:
    """Return the store for a provider, honouring a ``--store`` override.

    Args:
        provider: The provider whose store is wanted.
        override: An explicit path, or ``None`` for the default location.

    Returns:
        A store rooted at ``data/`` unless overridden.
    """
    return WorkbookStore(override or DATA_DIR / provider.store_name)


def _command_providers() -> int:
    """Print every registered provider with its periods and modes.

    Returns:
        ``ExitCode.OK``.
    """
    for provider in all_providers():
        print(f"{provider.key}  ({provider.label})")
        print(f"    store   {DATA_DIR / provider.store_name}")
        if provider.has_enumerable_periods():
            print(f"    periods {', '.join(provider.periods())}")
        else:
            print(f"    periods {provider.period_syntax}")
        print(f"    modes   {', '.join(sorted(provider.modes))}")
    return ExitCode.OK


def _periods_to_refresh(
    provider: Provider, requested: str | None, store: WorkbookStore
) -> list[str]:
    """Decide which periods a refresh should fetch.

    Args:
        provider: The provider being refreshed.
        requested: The raw ``-y`` value, or ``None``.
        store: The store, consulted to detect a first run.

    Returns:
        Validated period tokens.

    Raises:
        ValidationError: A requested period is rejected, or none was given and
            the provider has no default.
    """
    if requested:
        return [provider.validate_period(p) for p in requested.split(",") if p]
    defaults = provider.default_periods()
    if not defaults:
        syntax = provider.period_syntax or "a period"
        raise ValidationError(f"{provider.key} has no default period; pass -y {syntax}")
    if not store.exists() and provider.has_enumerable_periods():
        return list(provider.periods())
    return list(defaults)


def _command_refresh(args: argparse.Namespace) -> int:
    """Fetch the requested periods and write them into the store.

    Args:
        args: Parsed command-line arguments.

    Returns:
        ``ExitCode.OK``.

    Raises:
        ValidationError: The provider, period, or mode was rejected.
    """
    provider = get_provider(args.provider)
    store = _store_for(provider, args.store)
    raw_dir = args.raw_dir or RAW_DIR

    if args.cache is not None and not provider.bulk:
        raise ValidationError(f"{provider.key} does not use a cache; drop --cache")

    if args.jobs is not None and not provider.bulk:
        raise ValidationError(f"{provider.key} is not a bulk provider; drop --jobs")
    if args.top_logs is not None and not isinstance(provider, ContestLogProvider):
        raise ValidationError(f"{provider.key} does not download logs; drop --top-logs")

    if provider.bulk:
        provider.use_cache(FileCache(args.cache or (raw_dir / provider.key)))
    if isinstance(provider, ContestLogProvider):
        if args.top_logs is not None:
            provider.top_logs = args.top_logs
        if args.jobs is not None:
            provider.jobs = args.jobs

    if args.operating_mode is not None and not provider.uses_fetch_modes():
        raise ValidationError(
            f"{provider.key} applies modes at export time, not refresh; "
            f"drop -o here and pass it to the export command instead"
        )
    modes = [m for m in (args.operating_mode or "all").split(",") if m]
    for mode in modes:
        provider.resolve_mode(mode)

    sheets: list[SheetData] = []
    for period in _periods_to_refresh(provider, args.year, store):
        for mode in modes:
            rows = provider.fetch(period, mode)
            name = provider.sheet_name(period, mode)
            print(f"{provider.key} {name}: {len(rows)} rows", file=sys.stderr)
            if provider.last_raw is not None:
                archive_raw(raw_dir, provider.key, period, provider.last_raw)
            sheets.append(
                SheetData(
                    name=name,
                    columns=provider.columns,
                    rows=rows,
                    meta=SheetMeta(
                        sheet=name,
                        provider=provider.key,
                        period=period,
                        mode=mode,
                        rows=len(rows),
                        refreshed_utc=dt.datetime.now(dt.UTC).isoformat(),
                        source_url=provider.source_url(period),
                    ),
                )
            )
    store.replace_sheets(sheets)
    print(f"wrote {store.path}", file=sys.stderr)
    return ExitCode.OK


def _command_export(args: argparse.Namespace) -> int:
    """Read one sheet, apply the selection pipeline, and write the export.

    Args:
        args: Parsed command-line arguments.

    Returns:
        ``ExitCode.OK``.

    Raises:
        ValidationError: The provider, format, period, or mode was rejected,
            or the requested sheet has not been refreshed.
        StoreError: The store is missing or unreadable.
    """
    provider = get_provider(args.provider)
    exporter = get_exporter(args.format)
    period = provider.validate_period(args.year)
    spec = provider.resolve_mode(args.operating_mode)
    store = _store_for(provider, args.store)

    sheet_name = provider.sheet_name(period, args.operating_mode)
    if store.exists() and sheet_name not in store.sheet_names():
        suffix = (
            f" -o {args.operating_mode}"
            if provider.uses_fetch_modes() and args.operating_mode != "all"
            else ""
        )
        raise ValidationError(
            f"store has no sheet {sheet_name!r}; run: "
            f"callsigns refresh {provider.key} -y {period}{suffix}"
        )
    rows = store.read_sheet(sheet_name, provider.columns)

    limit = exporter.default_limit if args.download_rows is None else args.download_rows
    selected = limit_rows(filter_rows(rows, spec), limit)
    if limit > 0 and len(selected) < limit:
        print(f"only {len(selected)} rows matched; requested {limit}", file=sys.stderr)

    options = ExportOptions(
        period=period,
        mode=args.operating_mode,
        limit=limit,
        out_dir=args.out or DATA_DIR,
        basename=args.basename,
    )
    for path in exporter.write(selected, provider, options):
        print(path)
    return ExitCode.OK


def _harvest_targets(args: argparse.Namespace) -> list[tuple[Provider, str]]:
    """Expand the command line into provider and period pairs.

    Args:
        args: Parsed command-line arguments.

    Returns:
        Each provider paired with each period it should collect.

    Raises:
        ValidationError: A provider or period was rejected, or a provider with
            no default period was named without ``-y``.
    """
    keys = args.provider or list(provider_keys())
    targets: list[tuple[Provider, str]] = []
    for key in keys:
        provider = get_provider(key)
        if args.year:
            periods = [provider.validate_period(p) for p in args.year.split(",") if p]
        else:
            periods = list(provider.default_periods())
            if not periods:
                if args.provider:
                    syntax = provider.period_syntax or "a period"
                    raise ValidationError(
                        f"{provider.key} has no default period; pass -y {syntax}"
                    )
                _LOGGER.info("skipping %s: it needs an explicit period", provider.key)
                continue
        targets.extend((provider, period) for period in periods)
    return targets


def _command_harvest(args: argparse.Namespace) -> int:
    """Plan, report and optionally run a paced collection.

    Args:
        args: Parsed command-line arguments.

    Returns:
        ``ExitCode.OK``.

    Raises:
        ValidationError: A provider or period was rejected.
        UpstreamError: A listing or download failed.
    """
    policy = (
        DEFAULT_POLICY
        if args.pace is None
        else HostPolicy(
            min_interval=args.pace,
            jitter=args.pace,
            burst=DEFAULT_POLICY.burst,
            probe_interval=max(args.pace / 4, 0.25),
            probe_jitter=max(args.pace / 4, 0.25),
        )
    )
    limiter = RateLimiter(policy)
    raw_dir = args.cache or RAW_DIR

    plans = []
    for provider, period in _harvest_targets(args):
        # Every provider is paced, not only the bulk ones: a club provider
        # asked for 235 periods issues 235 requests, which needs pacing every
        # bit as much as a contest field does.
        provider.use_limiter(limiter)
        if provider.bulk:
            provider.use_cache(
                FileCache(raw_dir / provider.key, client=HttpClient(limiter=limiter))
            )
        if isinstance(provider, ContestLogProvider) and args.top_logs is not None:
            provider.top_logs = args.top_logs
        cache = getattr(provider, "_cache", None)
        plans.append((provider, period, plan_for(provider, period, cache, limiter)))

    print(
        f"{'provider':16} {'period':10} {'host':22} "
        f"{'probes':>7} {'pending':>8} {'cached':>7} {'estimate':>10}"
    )
    for _provider, _period, plan in plans:
        print(
            f"{plan.provider:16} {plan.period:10} {plan.host:22} "
            f"{plan.probe_items:>7} {plan.pending_items:>8} "
            f"{plan.cached_items:>7} {format_duration(plan.estimated_seconds):>10}"
        )
    every_plan = [plan for _p, _y, plan in plans]
    grand = total_seconds(every_plan)
    one_at_a_time = sequential_seconds(every_plan)
    hosts = len({plan.host for plan in every_plan})
    print(
        f"\n{len(plans)} tasks across {hosts} host(s), "
        f"estimated {format_duration(grand)}"
        + (
            f" (one host at a time would be {format_duration(one_at_a_time)})"
            if one_at_a_time > grand
            else ""
        )
    )

    if args.dry_run:
        print("dry run: nothing fetched", file=sys.stderr)
        return ExitCode.OK

    failed: list[tuple[str, str, str]] = []
    failures_lock = threading.Lock()

    def run_one(provider: Provider, period: str, plan: HarvestPlan) -> None:
        """Fetch and store one provider and period.

        Args:
            provider: The provider to run.
            period: The period to collect.
            plan: Its plan, for progress reporting.
        """
        if plan.pending_items == 0 and plan.probe_items == 0:
            print(f"{plan.provider} {plan.period}: already complete", file=sys.stderr)
            return
        print(
            f"{plan.provider} {plan.period}: fetching {plan.pending_items} "
            f"(estimate {format_duration(plan.estimated_seconds)})",
            file=sys.stderr,
        )
        try:
            rows = provider.fetch(period, args.operating_mode or "all")
        except CallsignsError as exc:
            # One unreachable source must not abandon a multi-day run. What
            # succeeded stays cached, so re-running resumes from here.
            with failures_lock:
                failed.append((plan.provider, plan.period, str(exc)))
            print(f"{plan.provider} {plan.period}: FAILED - {exc}", file=sys.stderr)
            return
        # Keep the bytes exactly as received. Bulk providers already have
        # theirs in the download cache; everything else would otherwise leave
        # nothing behind but the parsed rows.
        if provider.last_raw is not None:
            archive_raw(raw_dir, provider.key, period, provider.last_raw)
        store = _store_for(provider, args.store)
        name = provider.sheet_name(period, args.operating_mode or "all")
        store.replace_sheets(
            [
                SheetData(
                    name=name,
                    columns=provider.columns,
                    rows=rows,
                    meta=SheetMeta(
                        sheet=name,
                        provider=provider.key,
                        period=period,
                        mode=args.operating_mode or "all",
                        rows=len(rows),
                        refreshed_utc=dt.datetime.now(dt.UTC).isoformat(),
                        source_url=provider.source_url(period),
                    ),
                )
            ]
        )
        print(
            f"{plan.provider} {name}: {len(rows)} rows -> {store.path}", file=sys.stderr
        )

    # One worker per host. Pacing is per host, so hosts proceed together while
    # each host's own work stays strictly in sequence and within its budget.
    grouped = group_by_host(plans)
    if len(grouped) > 1:
        print(f"working {len(grouped)} hosts in parallel", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(grouped)) as pool:
        futures = [pool.submit(_drain, tasks, run_one) for tasks in grouped.values()]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    for host, stat in sorted(limiter.stats().items()):
        print(
            f"  {host}: {stat.requests} requests, "
            f"{format_duration(stat.waited)} spent pacing",
            file=sys.stderr,
        )
    if failed:
        print(f"\n{len(failed)} task(s) failed; re-run to retry:", file=sys.stderr)
        for key, period, reason in failed:
            print(f"  {key} {period}: {reason}", file=sys.stderr)
        return ExitCode.UPSTREAM
    return ExitCode.OK


def _drain(
    tasks: Sequence[tuple[Provider, str, HarvestPlan]],
    run_one: Callable[[Provider, str, HarvestPlan], None],
) -> None:
    """Run one host's tasks in order.

    Args:
        tasks: Provider, period and plan triples for a single host.
        run_one: Callable that performs one task.
    """
    for provider, period, plan in tasks:
        run_one(provider, period, plan)


ROSTER_SHEET: str = "Roster"


def _load_stores(root: pathlib.Path) -> dict[str, list[dict[str, object]]]:
    """Read every provider store found under a directory.

    Args:
        root: Directory holding the store workbooks.

    Returns:
        Rows keyed by provider key, for providers whose store exists and has
        content. Every sheet in a store is concatenated: a callsign active in
        several periods is one operator.
    """
    stores: dict[str, list[dict[str, object]]] = {}
    for key in provider_keys():
        provider = get_provider(key)
        path = root / provider.store_name
        if not path.is_file():
            continue
        store = WorkbookStore(path)
        rows: list[dict[str, object]] = []
        for sheet in store.sheet_names():
            rows.extend(store.read_sheet(sheet))
        if rows:
            stores[key] = rows
    return stores


def _command_roster(args: argparse.Namespace) -> int:
    """Build, query or summarise the cross-source roster.

    Args:
        args: Parsed command-line arguments.

    Returns:
        ``ExitCode.OK``.

    Raises:
        ValidationError: No stores were found to read.
    """
    root = args.stores or DATA_DIR
    stores = _load_stores(root)
    if not stores:
        raise ValidationError(
            f"no provider stores found under {root}; run a refresh or harvest first"
        )
    print(
        f"read {len(stores)} sources: " + ", ".join(sorted(stores)),
        file=sys.stderr,
    )

    if args.action == "overlap":
        matrix = overlap_matrix(stores)
        keys = sorted(stores)
        print(f"{'':16}" + "".join(f"{k[:11]:>12}" for k in keys))
        for a in keys:
            cells = "".join(f"{matrix.get((a, b), 0):>12,}" for b in keys)
            print(f"{a:16}{cells}")
        return ExitCode.OK

    roster = build_roster(stores)
    kept = [r for r in roster if int(str(r["ConfirmedCount"])) >= args.min_sources]
    if args.mode:
        wanted = args.mode.upper()
        kept = [r for r in kept if wanted in str(r["Modes"]).split(",")]
    if args.download_rows > 0:
        kept = kept[: args.download_rows]

    if args.action == "build" and args.format is None:
        # Per-source metric and percentile columns vary with what was
        # harvested, so they are derived; the shared ones are declared.
        extra = [
            key
            for key in (kept[0].keys() if kept else [])
            if key not in {c.key for c in ROSTER_COLUMNS}
        ]
        columns = ROSTER_COLUMNS + tuple(Column(k, k, str) for k in extra)
        target = (args.out or DATA_DIR) / "Roster.xlsx"
        WorkbookStore(target).replace_sheets(
            [
                SheetData(
                    name=ROSTER_SHEET,
                    columns=columns,
                    rows=kept,
                    meta=SheetMeta(
                        sheet=ROSTER_SHEET,
                        provider="roster",
                        period="all",
                        mode=args.mode or "all",
                        rows=len(kept),
                        refreshed_utc=dt.datetime.now(dt.UTC).isoformat(),
                        source_url=",".join(sorted(stores)),
                    ),
                )
            ]
        )
        print(f"{len(kept):,} callsigns -> {target}")
        return ExitCode.OK

    if args.format:
        exporter = get_exporter(args.format)
        options = ExportOptions(
            period="all",
            mode=args.mode or "all",
            limit=args.download_rows,
            out_dir=args.out or DATA_DIR,
            basename=args.basename or "Roster-Query",
        )
        for path in exporter.write(kept, RosterProvider(), options):
            print(path)
        return ExitCode.OK

    print(f"{'callsign':10} {'conf':>4} {'src':>4} {'mean%':>6}  modes")
    for row in kept[:50]:
        print(
            f"{row['Callsign']:10} {row['ConfirmedCount']:>4} "
            f"{row['SourceCount']:>4} {float(str(row['MeanPercentile'])):>6.3f}  "
            f"{row['Modes']}"
        )
    print(f"\n{len(kept):,} callsigns matched")
    return ExitCode.OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line.

    Args:
        argv: Arguments excluding the program name. Defaults to ``sys.argv``.

    Returns:
        A process exit code.
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        match args.command:
            case "providers":
                return _command_providers()
            case "refresh":
                return _command_refresh(args)
            case "export":
                return _command_export(args)
            case "harvest":
                return _command_harvest(args)
            case "roster":
                return _command_roster(args)
            case _:  # pragma: no cover - argparse rejects this first
                raise ValidationError(f"unknown command {args.command!r}")
    except CallsignsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exit_code_for(exc)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
