import json
import threading

import pytest

from callsigns.cache import DEFAULT_JOBS, MANIFEST_NAME, FileCache
from callsigns.errors import UpstreamError


class FakeClient:
    def __init__(self, payload=b"data", fail=False):
        self.payload = payload
        self.fail = fail
        self.urls = []

    def get_bytes(self, url, **kwargs):
        self.urls.append(url)
        if self.fail:
            raise UpstreamError(f"GET {url} failed: HTTP 404")
        return self.payload


def test_miss_fetches_and_stores(tmp_path):
    client = FakeClient(b"payload")
    cache = FileCache(tmp_path, client=client)
    path = cache.fetch("20251129.zip", "https://x.test/a.zip")
    assert path.read_bytes() == b"payload"
    assert client.urls == ["https://x.test/a.zip"]


def test_hit_does_not_touch_the_network(tmp_path):
    client = FakeClient(b"payload")
    cache = FileCache(tmp_path, client=client)
    cache.fetch("k", "https://x.test/a.zip")
    cache.fetch("k", "https://x.test/a.zip")
    assert len(client.urls) == 1


def test_has_reports_presence(tmp_path):
    cache = FileCache(tmp_path, client=FakeClient())
    assert not cache.has("k")
    cache.fetch("k", "https://x.test/a.zip")
    assert cache.has("k")


def test_refresh_forces_a_refetch(tmp_path):
    client = FakeClient(b"one")
    cache = FileCache(tmp_path, client=client)
    cache.fetch("k", "https://x.test/a.zip")
    client.payload = b"two"
    path = cache.fetch("k", "https://x.test/a.zip", refresh=True)
    assert path.read_bytes() == b"two"
    assert len(client.urls) == 2


def test_manifest_records_entries(tmp_path):
    cache = FileCache(tmp_path, client=FakeClient(b"12345"))
    cache.fetch("20251129.zip", "https://x.test/a.zip")
    manifest = json.loads((tmp_path / MANIFEST_NAME).read_text())
    assert manifest["20251129.zip"]["url"] == "https://x.test/a.zip"
    assert manifest["20251129.zip"]["size"] == 5
    assert manifest["20251129.zip"]["fetched_utc"].startswith("20")


def test_entries_round_trip(tmp_path):
    cache = FileCache(tmp_path, client=FakeClient(b"12345"))
    cache.fetch("a", "https://x.test/a")
    cache.fetch("b", "https://x.test/b")
    keys = sorted(entry.key for entry in cache.entries())
    assert keys == ["a", "b"]


def test_failed_fetch_leaves_no_partial_file(tmp_path):
    cache = FileCache(tmp_path, client=FakeClient(fail=True))
    with pytest.raises(UpstreamError):
        cache.fetch("k", "https://x.test/a.zip")
    assert not cache.has("k")
    assert not list(tmp_path.glob("*.tmp"))


def test_keys_are_sanitised_into_filenames(tmp_path):
    cache = FileCache(tmp_path, client=FakeClient())
    path = cache.fetch("a/b 20251129.zip", "https://x.test/a")
    assert path.parent == tmp_path
    assert "/" not in path.name


def test_corrupt_manifest_is_ignored_not_fatal(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / MANIFEST_NAME).write_text("{not json")
    cache = FileCache(tmp_path, client=FakeClient())
    assert cache.entries() == []
    cache.fetch("k", "https://x.test/a")
    assert cache.has("k")


def test_root_is_exposed(tmp_path):
    assert FileCache(tmp_path, client=FakeClient()).root == tmp_path


def test_path_for_does_not_create_anything(tmp_path):
    cache = FileCache(tmp_path, client=FakeClient())
    path = cache.path_for("k")
    assert path == tmp_path / "k"
    assert not path.exists()


class CountingClient:
    def __init__(self, fail_for=()):
        self.fail_for = set(fail_for)
        self.urls = []
        self.max_concurrent = 0
        self._active = 0
        self._lock = threading.Lock()

    def get_bytes(self, url, **kwargs):
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
            self.urls.append(url)
        try:
            if url in self.fail_for:
                raise UpstreamError(f"GET {url} failed: HTTP 404")
            return url.encode()
        finally:
            with self._lock:
                self._active -= 1


def test_fetch_many_returns_paths_in_input_order(tmp_path):
    cache = FileCache(tmp_path, client=CountingClient())
    items = [(f"k{i}", f"https://x.test/{i}") for i in range(5)]
    got = cache.fetch_many(items)
    assert [key for key, _ in got] == [key for key, _ in items]
    assert got[2][1].read_bytes() == b"https://x.test/2"


def test_fetch_many_skips_cached_items(tmp_path):
    client = CountingClient()
    cache = FileCache(tmp_path, client=client)
    cache.fetch("k0", "https://x.test/0")
    client.urls.clear()
    cache.fetch_many([("k0", "https://x.test/0"), ("k1", "https://x.test/1")])
    assert client.urls == ["https://x.test/1"]


def test_fetch_many_respects_the_job_limit(tmp_path):
    client = CountingClient()
    cache = FileCache(tmp_path, client=client)
    items = [(f"k{i}", f"https://x.test/{i}") for i in range(20)]
    cache.fetch_many(items, jobs=3)
    assert client.max_concurrent <= 3


def test_fetch_many_records_every_item_in_the_manifest(tmp_path):
    cache = FileCache(tmp_path, client=CountingClient())
    cache.fetch_many([(f"k{i}", f"https://x.test/{i}") for i in range(4)])
    assert {e.key for e in cache.entries()} == {"k0", "k1", "k2", "k3"}


def test_fetch_many_reports_progress(tmp_path):
    seen = []
    cache = FileCache(tmp_path, client=CountingClient())
    cache.fetch_many(
        [(f"k{i}", f"https://x.test/{i}") for i in range(3)],
        on_progress=lambda done, total: seen.append((done, total)),
    )
    assert seen[-1] == (3, 3)


def test_fetch_many_keeps_what_succeeded_around_a_failure(tmp_path):
    """A partial failure is survivable; the good items stay cached."""
    client = CountingClient(fail_for={"https://x.test/1"})
    cache = FileCache(tmp_path, client=client)
    items = [(f"k{i}", f"https://x.test/{i}") for i in range(3)]
    cache.fetch_many(items, jobs=1)
    assert cache.has("k0")
    assert cache.has("k2")
    assert not cache.has("k1")


def test_fetch_many_resumes_after_a_failure(tmp_path):
    client = CountingClient(fail_for={"https://x.test/1"})
    cache = FileCache(tmp_path, client=client)
    items = [(f"k{i}", f"https://x.test/{i}") for i in range(3)]
    cache.fetch_many(items, jobs=1)
    client.fail_for.clear()
    client.urls.clear()
    cache.fetch_many(items, jobs=1)
    assert client.urls == ["https://x.test/1"], "only the failed item is retried"


def test_fetch_many_with_no_items(tmp_path):
    assert FileCache(tmp_path, client=CountingClient()).fetch_many([]) == []


def test_default_jobs_is_polite():
    assert DEFAULT_JOBS == 6


from callsigns.http import ConditionalResult  # noqa: E402


class ValidatorClient(CountingClient):
    """Serves conditional responses and records the validators it was given."""

    def __init__(self, status=200, body=b"updated"):
        super().__init__()
        self.status = status
        self.body = body
        self.seen = []

    def get_conditional(self, url, *, etag=None, last_modified=None, **kwargs):
        self.seen.append((etag, last_modified))
        if self.status == 304:
            return ConditionalResult(304, None, etag, last_modified)
        return ConditionalResult(
            200, self.body, '"v2"', "Fri, 13 Feb 2026 00:00:00 GMT"
        )


def test_pending_lists_only_uncached_items(tmp_path):
    cache = FileCache(tmp_path, client=CountingClient())
    cache.fetch("k0", "https://x.test/0")
    items = [("k0", "https://x.test/0"), ("k1", "https://x.test/1")]
    assert cache.pending(items) == [("k1", "https://x.test/1")]


def test_pending_of_an_empty_cache_is_everything(tmp_path):
    cache = FileCache(tmp_path, client=CountingClient())
    items = [("k0", "https://x.test/0"), ("k1", "https://x.test/1")]
    assert cache.pending(items) == items


def test_revalidate_records_validators(tmp_path):
    cache = FileCache(tmp_path, client=ValidatorClient())
    cache.revalidate("k", "https://x.test/a")
    entry = next(e for e in cache.entries() if e.key == "k")
    assert entry.etag == '"v2"'
    assert entry.last_modified == "Fri, 13 Feb 2026 00:00:00 GMT"


def test_revalidate_keeps_the_cached_copy_on_304(tmp_path):
    client = ValidatorClient(status=304)
    cache = FileCache(tmp_path, client=client)
    cache._write("k", b"original")
    cache._record_many([cache._entry_for("k", "https://x.test/a", b"original")])
    path = cache.revalidate("k", "https://x.test/a")
    assert path.read_bytes() == b"original"


def test_revalidate_replaces_the_copy_on_200(tmp_path):
    cache = FileCache(tmp_path, client=ValidatorClient())
    cache._write("k", b"original")
    assert cache.revalidate("k", "https://x.test/a").read_bytes() == b"updated"


def test_revalidate_sends_the_stored_validators(tmp_path):
    client = ValidatorClient()
    cache = FileCache(tmp_path, client=client)
    cache.revalidate("k", "https://x.test/a")
    client.seen.clear()
    cache.revalidate("k", "https://x.test/a")
    assert client.seen == [('"v2"', "Fri, 13 Feb 2026 00:00:00 GMT")]


def test_entries_default_validators_to_none(tmp_path):
    cache = FileCache(tmp_path, client=CountingClient())
    cache.fetch("k", "https://x.test/a")
    entry = next(e for e in cache.entries() if e.key == "k")
    assert entry.etag is None


def test_fetch_many_skips_a_single_bad_item_and_keeps_the_rest(tmp_path):
    """One withdrawn log must not cost a contest its other four thousand."""
    client = CountingClient(fail_for={"https://x.test/1"})
    cache = FileCache(tmp_path, client=client)
    items = [(f"k{i}", f"https://x.test/{i}") for i in range(4)]
    got = cache.fetch_many(items, jobs=1)
    assert [key for key, _ in got] == ["k0", "k2", "k3"]
    assert not cache.has("k1")


def test_fetch_many_still_raises_when_everything_fails(tmp_path):
    client = CountingClient(fail_for={f"https://x.test/{i}" for i in range(3)})
    cache = FileCache(tmp_path, client=client)
    items = [(f"k{i}", f"https://x.test/{i}") for i in range(3)]
    with pytest.raises(UpstreamError):
        cache.fetch_many(items, jobs=1)


def test_fetch_many_warns_about_skipped_items(tmp_path, caplog):
    import logging

    client = CountingClient(fail_for={"https://x.test/1"})
    cache = FileCache(tmp_path, client=client)
    with caplog.at_level(logging.WARNING):
        cache.fetch_many([(f"k{i}", f"https://x.test/{i}") for i in range(3)], jobs=1)
    assert "1 of 3 downloads failed" in caplog.text
