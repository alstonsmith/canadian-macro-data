"""HTTP fetch client shared by every source: throttled, disk-cached, retries with backoff.

Policy comes from ``docs/sources.md`` (T0): at most 1 request per second by default, back off on
409 (StatCan table locked during updates), 429 and 5xx, and cache so repeat calls cost nothing.
Bytes are returned untouched. Parsing and trust decisions belong to the callers.

This cache is an HTTP-level convenience, separate from the unchanged raw files that T5 saves.
"""

import hashlib
import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import httpx

USER_AGENT = "canadian-macro-data/0.1 (+https://github.com/alstonsmith/canadian-macro-data)"
RETRYABLE_STATUSES = frozenset({409, 429, 500, 502, 503, 504})
DEFAULT_MAX_BYTES = 256 * 1024 * 1024


class FetchError(Exception):
    """A fetch failed for good. Carries the URL, last HTTP status (if any) and attempt count."""

    def __init__(
        self, message: str, *, url: str, status_code: int | None = None, attempts: int = 0
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.attempts = attempts


@dataclass(frozen=True)
class FetchResult:
    content: bytes
    url: str  # the full request URL, including sorted query parameters
    from_cache: bool
    fetched_at: float  # epoch seconds when the bytes were downloaded


class FetchClient:
    def __init__(
        self,
        cache_dir: Path | str,
        *,
        transport: httpx.BaseTransport | None = None,
        min_interval: float = 1.0,
        cache_ttl: float | None = 24 * 3600.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_max: float = 60.0,
        timeout: float = 30.0,
        max_bytes: int = DEFAULT_MAX_BYTES,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.min_interval = min_interval
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.max_bytes = max_bytes
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- public ---------------------------------------------------------------------------

    def get(
        self, url: str, *, params: Mapping[str, str] | None = None, refresh: bool = False
    ) -> FetchResult:
        """GET ``url``. Serves a fresh cache entry without touching the network unless ``refresh``."""
        full_url = self._build_url(url, params)
        key = hashlib.sha256(full_url.encode()).hexdigest()
        if not refresh:
            cached = self._read_cache(key, full_url)
            if cached is not None:
                return cached
        content = self._download(full_url)
        fetched_at = self._wall_clock()
        self._write_cache(key, full_url, content, fetched_at)
        return FetchResult(content, full_url, from_cache=False, fetched_at=fetched_at)

    # --- request --------------------------------------------------------------------------

    @staticmethod
    def _build_url(url: str, params: Mapping[str, str] | None) -> str:
        try:
            parsed = httpx.URL(url)
        except httpx.InvalidURL as exc:
            raise FetchError(f"invalid URL {url!r}: {exc}", url=url) from exc
        if parsed.scheme not in ("http", "https") or not parsed.host:
            raise FetchError(f"only http(s) URLs are fetched, got {url!r}", url=url)
        if params:
            parsed = parsed.copy_merge_params(sorted(params.items()))
        return str(parsed)

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait = self._last_request_at + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()

    def _backoff_delay(self, attempt: int, retry_after: float | None) -> float:
        delay = retry_after if retry_after is not None else self.backoff_base * 2**attempt
        return min(delay, self.backoff_max)

    def _download(self, url: str) -> bytes:
        status: int | None = None
        detail = ""
        for attempt in range(self.max_retries + 1):
            retry_after: float | None = None
            self._throttle()
            try:
                with self._http.stream("GET", url) as response:
                    status = response.status_code
                    if status == 200:
                        return self._read_body(response, url)
                    if status not in RETRYABLE_STATUSES:
                        raise FetchError(
                            f"GET {url} failed: HTTP {status}",
                            url=url,
                            status_code=status,
                            attempts=attempt + 1,
                        )
                    detail = f"HTTP {status}"
                    retry_after = _parse_retry_after(response.headers.get("retry-after"))
            except httpx.TransportError as exc:
                status, detail = None, f"{type(exc).__name__}: {exc}"
            except httpx.HTTPError as exc:  # not transient (e.g. undecodable body)
                raise FetchError(
                    f"GET {url} failed: {type(exc).__name__}: {exc}",
                    url=url,
                    attempts=attempt + 1,
                ) from exc
            if attempt < self.max_retries:
                self._sleep(self._backoff_delay(attempt, retry_after))
        attempts = self.max_retries + 1
        plural = "attempt" if attempts == 1 else "attempts"
        raise FetchError(
            f"GET {url} failed after {attempts} {plural}: {detail}",
            url=url,
            status_code=status,
            attempts=attempts,
        )

    def _read_body(self, response: httpx.Response, url: str) -> bytes:
        too_big = FetchError(
            f"GET {url} response is larger than the {self.max_bytes} byte limit", url=url
        )
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self.max_bytes:
            raise too_big
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > self.max_bytes:
                raise too_big
        return bytes(body)

    # --- cache ----------------------------------------------------------------------------

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self.cache_dir / f"{key}.body", self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str, url: str) -> FetchResult | None:
        """Return a fresh, intact entry, or ``None`` (missing, expired, corrupt or tampered)."""
        body_path, meta_path = self._paths(key)
        try:
            meta = json.loads(meta_path.read_text())
            content = body_path.read_bytes()
            fetched_at = meta["fetched_at"]
            digest = meta["sha256"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not isinstance(fetched_at, int | float) or isinstance(fetched_at, bool):
            return None
        if hashlib.sha256(content).hexdigest() != digest:
            return None
        age = self._wall_clock() - fetched_at
        if age < 0 or (self.cache_ttl is not None and age > self.cache_ttl):
            return None
        return FetchResult(content, url, from_cache=True, fetched_at=float(fetched_at))

    def _write_cache(self, key: str, url: str, content: bytes, fetched_at: float) -> None:
        """Write body then meta (the commit marker), each atomically."""
        body_path, meta_path = self._paths(key)
        meta = {
            "url": url,
            "fetched_at": fetched_at,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(body_path, content)
        self._atomic_write(meta_path, json.dumps(meta).encode())

    def _atomic_write(self, path: Path, data: bytes) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


def _parse_retry_after(value: str | None) -> float | None:
    """Seconds form of Retry-After only; the HTTP-date form falls back to normal backoff."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None
