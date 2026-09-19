import unittest
import urllib.error

from scrapekit.fetcher import Fetcher, FetchError


class _Server:
    """Scripted responses: each entry is a status or an exception to raise."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, url, timeout):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, f"<body>{url}</body>"


def _fetcher(script, **kwargs):
    slept = []
    server = _Server(script)
    fetcher = Fetcher(
        delay=0,
        backoff=0.5,
        opener=server,
        sleep=slept.append,
        clock=lambda: 0.0,
        **kwargs,
    )
    return fetcher, server, slept


class RetryTests(unittest.TestCase):
    def test_succeeds_first_time(self):
        fetcher, server, _ = _fetcher([200])
        result = fetcher.get("https://example.org/a")
        self.assertEqual(result.status, 200)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(server.calls, 1)

    def test_retries_a_503_then_succeeds(self):
        error = urllib.error.HTTPError("https://example.org/a", 503, "busy", {}, None)
        fetcher, server, slept = _fetcher([error, 200])
        result = fetcher.get("https://example.org/a")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(server.calls, 2)
        self.assertEqual(slept, [0.5])

    def test_backoff_is_exponential(self):
        error = urllib.error.HTTPError("https://example.org/a", 429, "slow down", {}, None)
        fetcher, _, slept = _fetcher([error, error, 200], max_attempts=3)
        fetcher.get("https://example.org/a")
        self.assertEqual(slept, [0.5, 1.0])

    def test_gives_up_after_max_attempts(self):
        error = urllib.error.HTTPError("https://example.org/a", 500, "boom", {}, None)
        fetcher, server, _ = _fetcher([error, error, error], max_attempts=3)
        with self.assertRaises(FetchError) as caught:
            fetcher.get("https://example.org/a")
        self.assertEqual(caught.exception.attempts, 3)
        self.assertEqual(server.calls, 3)

    def test_a_404_is_not_retried(self):
        error = urllib.error.HTTPError("https://example.org/a", 404, "gone", {}, None)
        fetcher, server, _ = _fetcher([error, 200], max_attempts=3)
        with self.assertRaises(FetchError):
            fetcher.get("https://example.org/a")
        self.assertEqual(server.calls, 1)

    def test_connection_errors_are_retried(self):
        fetcher, server, _ = _fetcher([urllib.error.URLError("dns"), 200])
        self.assertEqual(fetcher.get("https://example.org/a").attempts, 2)
        self.assertEqual(server.calls, 2)


class CacheTests(unittest.TestCase):
    def test_second_request_for_the_same_url_is_served_from_cache(self):
        fetcher, server, _ = _fetcher([200])
        fetcher.get("https://example.org/a")
        again = fetcher.get("https://example.org/a")
        self.assertTrue(again.from_cache)
        self.assertEqual(server.calls, 1)


class RateLimitTests(unittest.TestCase):
    def test_waits_the_delay_between_two_hits_on_one_host(self):
        slept = []
        fetcher = Fetcher(
            delay=2.0, opener=_Server([200, 200]), sleep=slept.append, clock=lambda: 0.0
        )
        fetcher.get("https://example.org/a")
        fetcher.get("https://example.org/b")
        self.assertEqual(slept, [2.0])

    def test_different_hosts_do_not_wait_on_each_other(self):
        slept = []
        fetcher = Fetcher(
            delay=2.0, opener=_Server([200, 200]), sleep=slept.append, clock=lambda: 0.0
        )
        fetcher.get("https://example.org/a")
        fetcher.get("https://other.org/a")
        self.assertEqual(slept, [])


if __name__ == "__main__":
    unittest.main()
