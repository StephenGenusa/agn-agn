"""Exception hierarchy and process exit codes."""

import enum


class ExitCode(enum.IntEnum):
    """Process exit codes.

    Integer-valued because these are passed to ``sys.exit``.
    """

    OK = 0
    VALIDATION = 1
    UPSTREAM = 2
    STORE = 3


class CallsignsError(Exception):
    """Base class for every error this package raises deliberately."""


class ValidationError(CallsignsError):
    """The user asked for something impossible, before any I/O happened."""


class UpstreamError(CallsignsError):
    """A remote source failed, timed out, or returned unusable data."""


class StoreError(CallsignsError):
    """A local file could not be read or written."""


def exit_code_for(exc: BaseException) -> ExitCode:
    """Map an exception to the process exit code it should produce.

    Args:
        exc: The exception that terminated the command.

    Returns:
        The matching exit code. Unrecognised exceptions map to
        ``ExitCode.VALIDATION`` so that no failure ever exits zero.
    """
    match exc:
        case UpstreamError():
            return ExitCode.UPSTREAM
        case StoreError():
            return ExitCode.STORE
        case _:
            return ExitCode.VALIDATION
