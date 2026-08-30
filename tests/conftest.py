"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_working_directory(tmp_path, monkeypatch):
    """Run every test in its own directory.

    The CLI resolves its default store and raw-archive paths relative to the
    working directory, so without this a test that omits ``--store`` or
    ``--raw-dir`` would write into the developer's checkout.
    """
    monkeypatch.chdir(tmp_path)
