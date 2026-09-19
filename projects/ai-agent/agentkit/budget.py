"""Token and money budgets.

A loop that can call a model until it decides to stop is a loop that can spend
until someone notices. The budget is checked before every request and after
every response, and it stops the run rather than warning about it.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional


class BudgetExceeded(RuntimeError):
    """Raised when a run has spent what it was allowed to spend."""

    def __init__(self, message: str, usage: "Usage"):
        super().__init__(message)
        self.usage = usage


@dataclass(frozen=True)
class Pricing:
    """Dollars per million tokens.

    Defaults are Claude Opus 5's published first-party rates. `cache_read` uses
    the standard 0.1x multiplier on input; confirm both against current pricing
    for the model you actually run, and pass your own numbers if they differ.
    """

    model: str = "claude-opus-5"
    input_per_mtok: float = 5.00
    output_per_mtok: float = 25.00
    cache_write_per_mtok: float = 6.25
    cache_read_per_mtok: float = 0.50

    def cost(self, usage: "Usage") -> float:
        return round(
            usage.input_tokens / 1_000_000 * self.input_per_mtok
            + usage.output_tokens / 1_000_000 * self.output_per_mtok
            + usage.cache_write_tokens / 1_000_000 * self.cache_write_per_mtok
            + usage.cache_read_tokens / 1_000_000 * self.cache_read_per_mtok,
            6,
        )


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    requests: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_write_tokens
            + self.cache_read_tokens
        )

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.requests += other.requests

    @classmethod
    def from_response(cls, response) -> "Usage":
        """Read usage off an SDK response, tolerating fields a model omits."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return cls(requests=1)

        def field_value(*names):
            for name in names:
                value = getattr(usage, name, None)
                if value is None and isinstance(usage, dict):
                    value = usage.get(name)
                if value is not None:
                    return int(value)
            return 0

        return cls(
            input_tokens=field_value("input_tokens"),
            output_tokens=field_value("output_tokens"),
            cache_write_tokens=field_value("cache_creation_input_tokens"),
            cache_read_tokens=field_value("cache_read_input_tokens"),
            requests=1,
        )

    def as_dict(self) -> dict:
        data = asdict(self)
        data["total_tokens"] = self.total_tokens
        return data


@dataclass
class Budget:
    """What one run is allowed to spend.

    Any limit left as None is not enforced. `reserve` is the headroom kept for
    the reply the model has not produced yet: checking only what has already
    been spent lets the last request blow straight past the ceiling.
    """

    max_tokens: Optional[int] = 400_000
    max_cost_usd: Optional[float] = 1.00
    max_requests: Optional[int] = 24
    reserve_tokens: int = 16_000
    pricing: Pricing = field(default_factory=Pricing)
    usage: Usage = field(default_factory=Usage)

    @property
    def spent_usd(self) -> float:
        return self.pricing.cost(self.usage)

    @property
    def remaining_tokens(self) -> Optional[int]:
        if self.max_tokens is None:
            return None
        return max(0, self.max_tokens - self.usage.total_tokens)

    @property
    def remaining_usd(self) -> Optional[float]:
        if self.max_cost_usd is None:
            return None
        return round(max(0.0, self.max_cost_usd - self.spent_usd), 6)

    def check_before_request(self) -> None:
        """Refuse a request the budget cannot afford to receive an answer to."""
        if self.max_requests is not None and self.usage.requests >= self.max_requests:
            raise BudgetExceeded(
                f"request limit reached: {self.usage.requests} of {self.max_requests}",
                self.usage,
            )
        if self.max_tokens is not None:
            if self.usage.total_tokens + self.reserve_tokens > self.max_tokens:
                raise BudgetExceeded(
                    f"token budget would be exceeded by the next reply: "
                    f"{self.usage.total_tokens:,} spent + {self.reserve_tokens:,} reserved "
                    f"> {self.max_tokens:,}",
                    self.usage,
                )
        if self.max_cost_usd is not None and self.spent_usd >= self.max_cost_usd:
            raise BudgetExceeded(
                f"cost limit reached: ${self.spent_usd:.4f} of ${self.max_cost_usd:.2f}",
                self.usage,
            )

    def record(self, response) -> Usage:
        """Add one response's usage, then stop the run if that crossed a line."""
        usage = Usage.from_response(response)
        self.usage.add(usage)
        if self.max_tokens is not None and self.usage.total_tokens > self.max_tokens:
            raise BudgetExceeded(
                f"token budget exceeded: {self.usage.total_tokens:,} > {self.max_tokens:,}",
                self.usage,
            )
        if self.max_cost_usd is not None and self.spent_usd > self.max_cost_usd:
            raise BudgetExceeded(
                f"cost budget exceeded: ${self.spent_usd:.4f} > ${self.max_cost_usd:.2f}",
                self.usage,
            )
        return usage

    def as_dict(self) -> dict:
        return {
            "model": self.pricing.model,
            "usage": self.usage.as_dict(),
            "spent_usd": self.spent_usd,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "max_requests": self.max_requests,
            "remaining_tokens": self.remaining_tokens,
            "remaining_usd": self.remaining_usd,
        }
