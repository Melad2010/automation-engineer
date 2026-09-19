"""Polite HTTP fetching: rate limit, retries with backoff, and a cache.

The failure cases are the point here. A scraper that only works on the happy
path produces a dataset nobody can trust, because a silently dropped page looks
exactly like a source that had nothing to publish.
"""

import gzip
import time
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Optional

DEFAULT_USER_AGENT = (
    "source-tracked-scraper/1.0 (+https://melad2010.github.io/automation-engineer/)"
)

# Statuses worth trying again: the server is rate limiting or briefly unwell.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """Raised when a URL could not be retrieved after every allowed attempt."""

    def __init__(self, url: str, attempts: int, reason: str):
        super().__init__(f"{url} failed after {attempts} attempt(s): {reason}")
        self.url = url
        self.attempts = attempts
        self.reason = reason


@dataclass
class FetchResult:
    url: str
    status: int
    body: str
    attempts: int = 1
    from_cache: bool = False


@dataclass
class Fetcher:
    """Fetches pages one at a time, no faster than `delay` seconds apart.

    Args:
        delay: minimum seconds between two requests to the same host.
        max_attempts: total tries per URL, including the first.
        backoff: base seconds for exponential backoff between retries.
        timeout: per-request socket timeout in seconds.
        opener: injection point for tests; defaults to urllib.
        sleep: injection point for tests, so retries do not cost real time.
    """

    delay: float = 1.0
    max_attempts: int = 3
    backoff: float = 1.0
    timeout: float = 20.0
    user_agent: str = DEFAULT_USER_AGENT
    opener: Optional[Callable[[urllib.request.Request, float], "object"]] = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    _last_request_at: dict = field(default_factory=dict, init=False, repr=False)
    _cache: dict = field(default_factory=dict, init=False, repr=False)
    log: list = field(default_factory=list, init=False, repr=False)

    def get(self, url: str) -> FetchResult:
        if url in self._cache:
            cached = self._cache[url]
            return FetchResult(url, cached.status, cached.body, cached.attempts, from_cache=True)

        last_reason = "no attempt was made"
        for attempt in range(1, self.max_attempts + 1):
            self._wait_turn(url)
            try:
                status, body = self._open(url)
            except urllib.error.HTTPError as exc:
                status, body = exc.code, ""
                last_reason = f"HTTP {exc.code}"
                if status not in RETRYABLE_STATUS:
                    self.log.append((url, attempt, last_reason))
                    raise FetchError(url, attempt, last_reason) from exc
            except (urllib.error.URLError, OSError) as exc:
                last_reason = f"{type(exc).__name__}: {exc}"
            else:
                result = FetchResult(url, status, body, attempt)
                self._cache[url] = result
                return result

            self.log.append((url, attempt, last_reason))
            if attempt < self.max_attempts:
                self.sleep(self.backoff * (2 ** (attempt - 1)))

        raise FetchError(url, self.max_attempts, last_reason)

    def _wait_turn(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).netloc
        previous = self._last_request_at.get(host)
        now = self.clock()
        if previous is not None:
            remaining = self.delay - (now - previous)
            if remaining > 0:
                self.sleep(remaining)
        self._last_request_at[host] = self.clock()

    def _open(self, url: str):
        if self.opener is not None:
            return self.opener(url, self.timeout)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, raw.decode(charset, errors="replace")
