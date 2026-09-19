"""An agent with the guardrails switched on by default.

The interesting part of this project is not that it calls a model. It is the
budget, the rate limit, the tool policy and the retry rules that decide when it
stops — the things that separate a demo from something you leave running.
"""

from .budget import Budget, BudgetExceeded, Pricing, Usage
from .guardrails import (
    GuardrailError,
    RateLimiter,
    ToolPolicy,
    ToolNotAllowed,
    TooManyToolCalls,
    TurnLimitReached,
)
from .tools import TOOLS, ToolError, run_tool
from .agent import Agent, AgentResult, Transcript

__all__ = [
    "Budget",
    "BudgetExceeded",
    "Pricing",
    "Usage",
    "GuardrailError",
    "RateLimiter",
    "ToolPolicy",
    "ToolNotAllowed",
    "TooManyToolCalls",
    "TurnLimitReached",
    "TOOLS",
    "ToolError",
    "run_tool",
    "Agent",
    "AgentResult",
    "Transcript",
]
