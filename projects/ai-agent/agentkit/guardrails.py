"""The rules that decide when the agent stops.

Everything here is deliberately boring and deliberately enforced in code rather
than asked for in the system prompt. A prompt is a request; a rate limiter is a
rule.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence


class GuardrailError(RuntimeError):
    """Base class for every stop condition that is not a budget."""


class ToolNotAllowed(GuardrailError):
    pass


class TooManyToolCalls(GuardrailError):
    pass


class TurnLimitReached(GuardrailError):
    pass


@dataclass
class RateLimiter:
    """At most `max_calls` in any `window` seconds, sliding.

    `sleep` and `clock` are injected so tests exercise the waiting logic without
    waiting. Nothing here spins.
    """

    max_calls: int = 8
    window: float = 60.0
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    _calls: deque = field(default_factory=deque, init=False, repr=False)
    waits: list = field(default_factory=list, init=False, repr=False)

    def acquire(self) -> float:
        """Block until a slot is free. Returns how long it waited."""
        waited = 0.0
        while True:
            now = self.clock()
            while self._calls and now - self._calls[0] >= self.window:
                self._calls.popleft()
            if len(self._calls) < self.max_calls:
                self._calls.append(now)
                if waited:
                    self.waits.append(waited)
                return waited
            pause = self.window - (now - self._calls[0])
            waited += pause
            self.sleep(pause)


@dataclass
class ToolPolicy:
    """Which tools may run, how often, and how big an answer they may return.

    A tool the model invents is refused by name, and the refusal goes back as a
    tool result so the model can correct itself instead of the run dying.
    """

    allowed: Sequence = ()
    max_calls_per_tool: int = 6
    max_calls_total: int = 20
    max_result_chars: int = 8_000
    counts: dict = field(default_factory=dict)

    @property
    def total_calls(self) -> int:
        return sum(self.counts.values())

    def check(self, name: str) -> None:
        if self.allowed and name not in self.allowed:
            raise ToolNotAllowed(
                f"{name!r} is not an allowed tool. Allowed: {', '.join(sorted(self.allowed))}"
            )
        if self.total_calls >= self.max_calls_total:
            raise TooManyToolCalls(
                f"tool call limit reached: {self.total_calls} of {self.max_calls_total}"
            )
        if self.counts.get(name, 0) >= self.max_calls_per_tool:
            raise TooManyToolCalls(
                f"{name!r} was called {self.counts[name]} times, the limit is "
                f"{self.max_calls_per_tool}"
            )

    def record(self, name: str) -> None:
        self.counts[name] = self.counts.get(name, 0) + 1

    def truncate(self, text: str) -> str:
        """Keep one enormous tool result from eating the context window."""
        if len(text) <= self.max_result_chars:
            return text
        kept = self.max_result_chars
        return (
            text[:kept]
            + f"\n\n[truncated: {len(text) - kept:,} more characters. "
            "Narrow the query rather than asking for everything again.]"
        )


@dataclass
class Retry:
    """Retry policy for the calls the SDK does not already retry for us.

    The SDK retries connection errors, 408/409/429 and 5xx on its own. This sits
    on top for the cases it gives up on, and it never retries a 400: a malformed
    request is malformed the second time too.
    """

    max_attempts: int = 3
    backoff: float = 1.0
    sleep: Callable[[float], None] = time.sleep
    attempts_made: int = field(default=0, init=False)

    def run(self, call: Callable, is_retryable: Callable[[Exception], bool]):
        last = None
        for attempt in range(1, self.max_attempts + 1):
            self.attempts_made = attempt
            try:
                return call()
            except Exception as exc:  # re-raised below unless retryable
                if not is_retryable(exc) or attempt == self.max_attempts:
                    raise
                last = exc
                self.sleep(self.backoff * (2 ** (attempt - 1)))
        raise last  # pragma: no cover - unreachable, the loop always returns or raises
