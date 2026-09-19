import unittest

from agentkit.guardrails import (
    RateLimiter,
    Retry,
    ToolNotAllowed,
    ToolPolicy,
    TooManyToolCalls,
)


class _Clock:
    """A clock the test moves by hand, so nothing waits on real time."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class RateLimiterTests(unittest.TestCase):
    def test_calls_under_the_limit_never_wait(self):
        clock = _Clock()
        limiter = RateLimiter(max_calls=3, window=60, sleep=clock.sleep, clock=clock)
        for _ in range(3):
            self.assertEqual(limiter.acquire(), 0.0)
        self.assertEqual(clock.slept, [])

    def test_the_call_over_the_limit_waits_for_the_window_to_slide(self):
        clock = _Clock()
        limiter = RateLimiter(max_calls=2, window=60, sleep=clock.sleep, clock=clock)
        limiter.acquire()
        clock.now = 10
        limiter.acquire()
        # The oldest call was at t=0 and it is now t=10, so only the
        # remaining 50s of its window is left to wait — not a fresh 60.
        waited = limiter.acquire()
        self.assertEqual(waited, 50.0)
        self.assertEqual(clock.slept, [50.0])

    def test_the_window_slides_rather_than_resetting(self):
        clock = _Clock()
        limiter = RateLimiter(max_calls=2, window=60, sleep=clock.sleep, clock=clock)
        limiter.acquire()
        clock.now = 61          # the first call has aged out
        limiter.acquire()
        self.assertEqual(limiter.acquire(), 0.0)
        self.assertEqual(clock.slept, [])


class ToolPolicyTests(unittest.TestCase):
    def test_a_tool_outside_the_allowlist_is_refused_by_name(self):
        policy = ToolPolicy(allowed=("lookup_company",))
        with self.assertRaises(ToolNotAllowed) as caught:
            policy.check("delete_everything")
        self.assertIn("lookup_company", str(caught.exception))

    def test_an_empty_allowlist_allows_anything(self):
        ToolPolicy().check("whatever")

    def test_one_tool_cannot_be_called_forever(self):
        policy = ToolPolicy(max_calls_per_tool=2, max_calls_total=99)
        for _ in range(2):
            policy.check("lookup_company")
            policy.record("lookup_company")
        with self.assertRaises(TooManyToolCalls):
            policy.check("lookup_company")

    def test_the_total_call_budget_is_separate_from_the_per_tool_one(self):
        policy = ToolPolicy(max_calls_per_tool=10, max_calls_total=3)
        for name in ("a", "b", "c"):
            policy.check(name)
            policy.record(name)
        with self.assertRaises(TooManyToolCalls) as caught:
            policy.check("d")
        self.assertIn("limit reached", str(caught.exception))

    def test_a_short_result_is_left_alone(self):
        policy = ToolPolicy(max_result_chars=100)
        self.assertEqual(policy.truncate("short"), "short")

    def test_an_oversized_result_is_truncated_and_says_so(self):
        policy = ToolPolicy(max_result_chars=50)
        truncated = policy.truncate("x" * 500)
        self.assertLess(len(truncated), 500)
        self.assertIn("truncated", truncated)
        self.assertIn("450 more characters", truncated)


class _Boom(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class RetryTests(unittest.TestCase):
    def test_a_successful_call_is_not_retried(self):
        slept = []
        retry = Retry(sleep=slept.append)
        calls = []
        self.assertEqual(retry.run(lambda: calls.append(1) or "ok", lambda e: True), "ok")
        self.assertEqual(len(calls), 1)
        self.assertEqual(slept, [])

    def test_a_retryable_failure_is_retried_with_exponential_backoff(self):
        slept = []
        retry = Retry(max_attempts=3, backoff=0.5, sleep=slept.append)
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise _Boom(503)
            return "ok"

        self.assertEqual(retry.run(flaky, lambda e: True), "ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(slept, [0.5, 1.0])

    def test_a_non_retryable_failure_is_raised_immediately(self):
        slept = []
        retry = Retry(sleep=slept.append)
        attempts = []

        def bad_request():
            attempts.append(1)
            raise _Boom(400)

        with self.assertRaises(_Boom):
            retry.run(bad_request, lambda e: False)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(slept, [])

    def test_it_gives_up_after_max_attempts(self):
        retry = Retry(max_attempts=2, sleep=lambda s: None)
        attempts = []

        def always_fails():
            attempts.append(1)
            raise _Boom(500)

        with self.assertRaises(_Boom):
            retry.run(always_fails, lambda e: True)
        self.assertEqual(len(attempts), 2)


if __name__ == "__main__":
    unittest.main()
