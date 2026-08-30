import pytest

from callsigns.errors import (
    CallsignsError,
    ExitCode,
    StoreError,
    UpstreamError,
    ValidationError,
    exit_code_for,
)


def test_all_errors_share_a_base():
    for cls in (ValidationError, UpstreamError, StoreError):
        assert issubclass(cls, CallsignsError)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ValidationError("bad year"), ExitCode.VALIDATION),
        (UpstreamError("timeout"), ExitCode.UPSTREAM),
        (StoreError("unwritable"), ExitCode.STORE),
        (RuntimeError("unknown"), ExitCode.VALIDATION),
    ],
)
def test_exit_code_for_maps_each_error(exc, expected):
    assert exit_code_for(exc) is expected


def test_exit_codes_are_ints_for_sys_exit():
    assert int(ExitCode.OK) == 0
    assert int(ExitCode.STORE) == 3
