"""On-disk cache of raw upstream downloads.

Bulk sources publish files that are expensive to fetch and cheap to keep. The
cache holds the bytes exactly as received so aggregation can be re-run, or new
columns derived, without going back to the network. It is never a source of
truth: deleting it costs only a re-download.
"""

import concurrent.futures
import datetime as dt
import json
import logging
import os
import pathlib
import re
import tempfile
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from callsigns.errors import StoreError
from callsigns.http import HttpClient

MANIFEST_NAME: str = "index.json"

#: Default concurrent downloads. These sources publish for transparency, not
#: as bulk APIs, so the default stays modest.
DEFAULT_JOBS: int = 6

_LOGGER = logging.getLogger(__name__)


def _optional_str(value: object) -> str | None:
    """Return a manifest value as a string, or ``None`` when absent.

    Args:
        value: Raw value from the manifest.

    Returns:
        The string, or ``None``.
    """
    return None if value is None else str(value)


def _safe_name(key: str) -> str:
    """Reduce a cache key to a safe single-path-component filename.

    Args:
        key: Arbitrary cache key.

    Returns:
        The key with runs of unsafe characters replaced by underscores.
    """
    return re.sub(r"[^0-9A-Za-z._-]+", "_", key).strip("_") or "unnamed"


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """One recorded download."""

    key: str
    url: str
    size: int
    fetched_utc: str
    #: Validators the server supplied, used to revalidate cheaply later.
    #: ``None`` when the server sent none, which dynamic endpoints often
    #: do not.
    etag: str | None = None
    last_modified: str | None = None


class FileCache:
    """Stores raw downloads under a directory, with a JSON manifest."""

    def __init__(self, root: pathlib.Path, client: HttpClient | None = None) -> None:
        """Initialise the cache.

        Args:
            root: Directory holding cached files and the manifest. Created on
                first write.
            client: HTTP client used for misses. Defaults to a new
                :class:`HttpClient`.
        """
        self._root = root
        self._client = client if client is not None else HttpClient()

    @property
    def root(self) -> pathlib.Path:
        """Return the cache directory."""
        return self._root

    def path_for(self, key: str) -> pathlib.Path:
        """Return the path a key maps to, whether or not it exists.

        Args:
            key: Cache key.

        Returns:
            The file path for this key.
        """
        return self._root / _safe_name(key)

    def has(self, key: str) -> bool:
        """Return whether a key is already cached.

        Args:
            key: Cache key.

        Returns:
            ``True`` if the file is present.
        """
        return self.path_for(key).is_file()

    def fetch(self, key: str, url: str, *, refresh: bool = False) -> pathlib.Path:
        """Return the cached file for a key, downloading it if necessary.

        Args:
            key: Cache key, used as the filename.
            url: Where to download from on a miss.
            refresh: Re-download even when the key is already cached.

        Returns:
            Path to the cached file.

        Raises:
            UpstreamError: The download failed.
            StoreError: The cache directory could not be written.
        """
        target = self.path_for(key)
        if target.is_file() and not refresh:
            _LOGGER.debug("cache hit %s", target)
            return target

        _LOGGER.info("downloading %s", url)
        payload = self._client.get_bytes(url)
        self._write(key, payload)
        self._record_many([self._entry_for(key, url, payload)])
        return target

    def fetch_many(
        self,
        items: Sequence[tuple[str, str]],
        *,
        jobs: int = DEFAULT_JOBS,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[tuple[str, pathlib.Path]]:
        """Fetch many items, reusing whatever is already cached.

        Cache hits cost nothing; misses are downloaded through a bounded pool.
        The manifest is written once at the end, so worker threads never
        contend for it, and items that succeeded stay cached even when a later
        item fails — a re-run resumes rather than restarting.

        Args:
            items: ``(key, url)`` pairs, in the order results should return.
            jobs: Maximum concurrent downloads.
            on_progress: Called with ``(completed, to_download)`` after each
                download. Not called when everything was already cached.

        Returns:
            ``(key, path)`` pairs in the order given.

        Raises:
            UpstreamError: At least one download failed.
            StoreError: The cache could not be written.
        """
        misses = [(key, url) for key, url in items if not self.has(key)]
        _LOGGER.info(
            "%d items, %d cached, %d to fetch",
            len(items),
            len(items) - len(misses),
            len(misses),
        )

        completed = 0
        failures: list[BaseException] = []
        fetched: list[CacheEntry] = []
        lock = threading.Lock()

        def worker(key: str, url: str) -> None:
            payload = self._client.get_bytes(url)
            self._write(key, payload)
            with lock:
                fetched.append(self._entry_for(key, url, payload))

        if misses:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max(jobs, 1)
            ) as pool:
                futures = [pool.submit(worker, key, url) for key, url in misses]
                for future in concurrent.futures.as_completed(futures):
                    completed += 1
                    try:
                        future.result()
                    except BaseException as exc:  # collected, re-raised below
                        failures.append(exc)
                    if on_progress is not None:
                        on_progress(completed, len(misses))

        if fetched:
            self._record_many(fetched)
        if failures:
            if not fetched and misses:
                # Nothing at all worked: the source is down or the listing is
                # wrong, and continuing would just produce an empty sheet.
                raise failures[0]
            # Individual items fail for their own reasons — a withdrawn log, a
            # malformed entry in the listing. Losing thousands of good logs
            # over one bad one is far worse than skipping it.
            _LOGGER.warning(
                "%d of %d downloads failed and were skipped; first: %s",
                len(failures),
                len(misses),
                failures[0],
            )
        return [
            (key, self.path_for(key))
            for key, _url in items
            if self.path_for(key).is_file()
        ]

    @staticmethod
    def _entry_for(
        key: str,
        url: str,
        payload: bytes,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> CacheEntry:
        """Build a manifest entry for a just-downloaded payload.

        Args:
            key: Cache key.
            url: Where it came from.
            payload: The downloaded bytes.
            etag: ``ETag`` the server supplied, if any.
            last_modified: ``Last-Modified`` the server supplied, if any.

        Returns:
            The entry to record.
        """
        return CacheEntry(
            key=key,
            url=url,
            size=len(payload),
            fetched_utc=dt.datetime.now(dt.UTC).isoformat(),
            etag=etag,
            last_modified=last_modified,
        )

    def pending(self, items: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
        """Return the items not yet cached.

        Lets a paced harvest report how much work remains, and lets a run
        resumed on a later day skip everything already retrieved.

        Args:
            items: ``(key, url)`` pairs.

        Returns:
            The subset whose files are absent.
        """
        return [(key, url) for key, url in items if not self.has(key)]

    def revalidate(self, key: str, url: str) -> pathlib.Path:
        """Refresh one cached file, using validators where the server offers them.

        A server that supports ``ETag`` or ``Last-Modified`` answers 304 and
        sends no body, so re-checking a large archive costs almost nothing.

        Args:
            key: Cache key.
            url: Where to re-fetch from.

        Returns:
            Path to the cached file, unchanged when the server answers 304.

        Raises:
            UpstreamError: The request failed.
            StoreError: The cache could not be written.
        """
        known = {entry.key: entry for entry in self.entries()}.get(key)
        result = self._client.get_conditional(
            url,
            etag=known.etag if known else None,
            last_modified=known.last_modified if known else None,
        )
        if result.unchanged:
            _LOGGER.debug("unchanged %s", url)
            return self.path_for(key)
        body = result.body or b""
        self._write(key, body)
        self._record_many(
            [
                self._entry_for(
                    key,
                    url,
                    body,
                    etag=result.etag,
                    last_modified=result.last_modified,
                )
            ]
        )
        return self.path_for(key)

    def _write(self, key: str, payload: bytes) -> None:
        """Write one payload to its cache path atomically.

        Args:
            key: Cache key.
            payload: Bytes to store.

        Raises:
            StoreError: The cache file could not be written.
        """
        target = self.path_for(key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, raw_name = tempfile.mkstemp(
                dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
            )
            os.close(descriptor)
            temp_path = pathlib.Path(raw_name)
            try:
                temp_path.write_bytes(payload)
                os.replace(temp_path, target)
            except OSError:
                temp_path.unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise StoreError(f"cannot write cache file {target}: {exc}") from exc

    def entries(self) -> list[CacheEntry]:
        """Return every recorded download.

        A manifest that is missing or unreadable yields an empty list rather
        than an error: the cache is disposable, and losing its index must never
        block a run.

        Returns:
            Recorded entries, in manifest order.
        """
        return [
            CacheEntry(
                key=key,
                url=str(value.get("url", "")),
                size=int(str(value.get("size", 0))),
                fetched_utc=str(value.get("fetched_utc", "")),
                etag=_optional_str(value.get("etag")),
                last_modified=_optional_str(value.get("last_modified")),
            )
            for key, value in self._read_manifest().items()
        ]

    def _read_manifest(self) -> dict[str, dict[str, object]]:
        """Return the manifest, or an empty mapping if absent or corrupt.

        Returns:
            The parsed manifest.
        """
        path = self._root / MANIFEST_NAME
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}

    def _record_many(self, entries: Sequence[CacheEntry]) -> None:
        """Add or replace several manifest entries in one write.

        Args:
            entries: The entries to record.

        Raises:
            StoreError: The manifest could not be written.
        """
        manifest = self._read_manifest()
        for entry in entries:
            manifest[entry.key] = {
                "url": entry.url,
                "size": entry.size,
                "fetched_utc": entry.fetched_utc,
                "etag": entry.etag,
                "last_modified": entry.last_modified,
            }
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            (self._root / MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError as exc:
            raise StoreError(f"cannot write cache manifest: {exc}") from exc
