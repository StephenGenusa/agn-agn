"""Core provider types: columns, modes, and the provider contract."""

import abc
import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from callsigns.errors import ValidationError

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance
    from callsigns.cache import FileCache
    from callsigns.pacing import RateLimiter


class Mode(enum.StrEnum):
    """The canonical operating-mode vocabulary offered by the CLI."""

    ALL = "all"
    CW = "cw"
    PHONE = "phone"
    DATA = "data"


class ModeKind(enum.StrEnum):
    """How a provider implements a mode restriction."""

    ALL = "all"
    FILTER = "filter"
    FETCH = "fetch"


@dataclass(frozen=True, slots=True)
class Column:
    """One column of a provider's dataset."""

    key: str
    header: str
    type: type[object]


@dataclass(frozen=True, slots=True)
class ModeSpec:
    """How one mode token is realised for a given provider."""

    kind: ModeKind
    column: str | None = None
    value: str | None = None

    @classmethod
    def all_modes(cls) -> ModeSpec:
        """Return a spec that applies no restriction."""
        return cls(kind=ModeKind.ALL)

    @classmethod
    def filter_on(cls, column: str) -> ModeSpec:
        """Return a spec that keeps rows where ``column`` is greater than zero.

        Args:
            column: Column key holding the per-mode count.

        Returns:
            A filtering mode specification.
        """
        return cls(kind=ModeKind.FILTER, column=column)

    @classmethod
    def fetch_as(cls, value: str) -> ModeSpec:
        """Return a spec that passes ``value`` to the upstream request.

        Args:
            value: The provider-native mode token to send.

        Returns:
            A fetching mode specification.
        """
        return cls(kind=ModeKind.FETCH, value=value)


class Provider(abc.ABC):
    """One data source's dataset, and how to retrieve it."""

    key: ClassVar[str]
    label: ClassVar[str]
    store_name: ClassVar[str]
    export_prefix: ClassVar[str]
    calls_prefix: ClassVar[str]
    columns: ClassVar[tuple[Column, ...]]
    callsign_key: ClassVar[str]
    modes: ClassVar[Mapping[str, ModeSpec]]
    bulk: ClassVar[bool] = False

    #: Human description of the accepted period form, quoted in errors and in
    #: the ``providers`` listing when :meth:`periods` is empty because the
    #: provider accepts an unbounded set, such as any calendar date.
    period_syntax: ClassVar[str] = ""

    #: Raw bytes of the most recent :meth:`fetch`, when the provider can
    #: supply them. The CLI archives this verbatim so the store can be
    #: rebuilt or re-analysed without re-fetching. ``None`` means the
    #: provider has no single raw payload to offer.
    last_raw: bytes | None = None

    @abc.abstractmethod
    def periods(self) -> tuple[str, ...]:
        """Return every period token this provider accepts."""

    @abc.abstractmethod
    def default_periods(self) -> tuple[str, ...]:
        """Return the periods a refresh with no ``-y`` should fetch."""

    @abc.abstractmethod
    def period_label(self, period: str) -> str:
        """Return the workbook sheet name for a period.

        Args:
            period: A token from :meth:`periods`.
        """

    @abc.abstractmethod
    def fetch(self, period: str, mode: str) -> list[dict[str, object]]:
        """Retrieve one period and mode.

        Args:
            period: A token from :meth:`periods`.
            mode: A key of :attr:`modes`.

        Returns:
            Rows keyed by column key, containing only declared columns.

        Raises:
            UpstreamError: The source failed or returned unusable data.
        """

    def source_url(self, period: str) -> str:
        """Return the URL a period was fetched from, for the metadata sheet.

        Args:
            period: A token from :meth:`periods`.

        Returns:
            The URL, or the empty string when the provider has no single
            meaningful URL for a period.
        """
        del period
        return ""

    def resolve_mode(self, token: str) -> ModeSpec:
        """Look up a mode token in this provider's vocabulary.

        Args:
            token: The value given to ``-o``.

        Returns:
            The matching mode specification.

        Raises:
            ValidationError: The token is not supported by this provider.
        """
        try:
            return self.modes[token]
        except KeyError:
            valid = ", ".join(sorted(self.modes))
            raise ValidationError(
                f"{self.key} does not support mode {token!r}; valid modes: {valid}"
            ) from None

    def has_enumerable_periods(self) -> bool:
        """Return whether every accepted period can be listed.

        Returns:
            ``False`` for providers accepting an unbounded set, such as any
            calendar date.
        """
        return bool(self.periods())

    def uses_fetch_modes(self) -> bool:
        """Return whether any mode is applied when data is retrieved.

        Such providers need one stored sheet per period *and* mode, because a
        different mode is a different dataset rather than a subset of one.

        Returns:
            ``True`` if any declared mode is a ``FETCH`` mode.
        """
        return any(spec.kind is ModeKind.FETCH for spec in self.modes.values())

    def use_cache(self, cache: FileCache) -> None:
        """Attach a download cache.

        A no-op for single-request providers, which never read through a
        cache. Bulk providers override it so the CLI can honour ``--cache``
        without rebuilding the provider.

        Args:
            cache: The cache to use for subsequent fetches.
        """
        del cache

    def use_limiter(self, limiter: RateLimiter) -> None:
        """Pace this provider's requests.

        Applied to whatever client the provider already holds, rather than
        replacing it, so a caller-supplied client keeps its behaviour. Every
        provider needs this, not only the bulk ones: a club provider asked for
        two hundred periods issues two hundred requests.

        Args:
            limiter: The limiter to route requests through.
        """
        client = getattr(self, "_client", None)
        setter = getattr(client, "set_limiter", None)
        if setter is not None:
            setter(limiter)

    def sheet_name(self, period: str, mode: str) -> str:
        """Return the store sheet name for a period and mode.

        Args:
            period: A validated period token.
            mode: A key of :attr:`modes`.

        Returns:
            The period label, with the mode appended for ``FETCH``-mode
            providers so each retrieved dataset gets its own sheet.
        """
        label = self.period_label(period)
        if mode != "all" and self.resolve_mode(mode).kind is ModeKind.FETCH:
            return f"{label} {mode.upper()}"
        return label

    def validate_period(self, period: str) -> str:
        """Check that a period is accepted by this provider.

        Providers with an unbounded period space override this to check shape
        rather than membership.

        Args:
            period: The value given to ``-y``.

        Returns:
            The period unchanged.

        Raises:
            ValidationError: The provider does not accept this period.
        """
        if not self.has_enumerable_periods():
            syntax = f" of the form {self.period_syntax}" if self.period_syntax else ""
            raise ValidationError(
                f"{self.key} needs an explicit period{syntax}; got {period!r}"
            )
        if period not in self.periods():
            raise ValidationError(
                f"{self.key} has no period {period!r}; "
                f"valid periods: {', '.join(self.periods())}"
            )
        return period

    def column_for(self, key: str) -> Column:
        """Return the declared column with the given key.

        Args:
            key: Column key to look up.

        Returns:
            The matching column.

        Raises:
            ValidationError: No such column is declared.
        """
        for column in self.columns:
            if column.key == key:
                return column
        raise ValidationError(f"{self.key} declares no column {key!r}")
