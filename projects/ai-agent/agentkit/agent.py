"""The agent loop.

This is a hand-written `while stop_reason == "tool_use"` loop rather than the
SDK's tool runner, for one reason: every guardrail in this project lives between
two turns of that loop — the budget check before a request, the tool policy
before a call, the rate limiter, the truncation of a result that came back too
big. Owning the loop is what makes those visible and testable. Reach for
`client.beta.messages.tool_runner` when you want the loop and not the rules.

The model is Claude Opus 5 with adaptive thinking. Server-side refusal fallbacks
are enabled by default, so a refused request is routed by category instead of
returning nothing.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .budget import Budget, BudgetExceeded, Usage
from .guardrails import (
    GuardrailError,
    RateLimiter,
    Retry,
    ToolPolicy,
    TurnLimitReached,
)
from .tools import TOOLS, ToolError, run_tool

MODEL = "claude-opus-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You qualify inbound leads for an automation engineering practice.

Work from the tools, not from memory:
- Look the organisation up before saying anything about it.
- If lookup_company returns found=false, say the record does not exist. Never
  invent a headcount, a budget or a contact.
- Use score_fit for the score. Do not estimate one yourself.
- Check the website before describing it as working.

Then give a short recommendation: the score, the one automation you would
propose first, and the single biggest reason this might not be a fit. Be blunt
about the last one; a lead that wastes both parties' time is worth losing early.
"""

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "organisation": {"type": "string"},
        "found": {"type": "boolean"},
        "score": {"type": ["number", "null"]},
        "band": {"type": "string"},
        "first_automation": {"type": "string"},
        "biggest_risk": {"type": "string"},
        "contact_email": {"type": ["string", "null"]},
    },
    "required": [
        "organisation", "found", "score", "band", "first_automation", "biggest_risk",
        "contact_email",
    ],
    "additionalProperties": False,
}


@dataclass
class Transcript:
    """Everything the run did, in order. This is the audit trail."""

    events: list = field(default_factory=list)

    def add(self, kind: str, **detail) -> None:
        self.events.append({"kind": kind, **detail})

    def of_kind(self, kind: str) -> list:
        return [event for event in self.events if event["kind"] == kind]

    def tool_calls(self) -> list:
        return self.of_kind("tool_call")


@dataclass
class AgentResult:
    text: str = ""
    verdict: Optional[dict] = None
    stopped_because: str = "finished"
    turns: int = 0
    transcript: Transcript = field(default_factory=Transcript)
    budget: Optional[Budget] = None

    @property
    def complete(self) -> bool:
        return self.stopped_because == "finished"

    def as_dict(self) -> dict:
        return {
            "stopped_because": self.stopped_because,
            "complete": self.complete,
            "turns": self.turns,
            "text": self.text,
            "verdict": self.verdict,
            "budget": self.budget.as_dict() if self.budget else None,
            "tool_calls": [
                {"name": event["name"], "arguments": event["arguments"],
                 "ok": event["ok"]}
                for event in self.transcript.tool_calls()
            ],
        }


def _is_retryable(exc: Exception) -> bool:
    """Retry transport and server-side trouble; never retry a bad request.

    Matched by class name so this module imports with or without the SDK
    installed — the dry run has no anthropic dependency at all.
    """
    name = type(exc).__name__
    if name in ("BadRequestError", "NotFoundError", "PermissionDeniedError",
                "AuthenticationError", "UnprocessableEntityError"):
        return False
    if name in ("APIConnectionError", "APITimeoutError", "RateLimitError",
                "InternalServerError", "APIStatusError"):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


@dataclass
class Agent:
    """Runs one qualification task under a budget and a set of stop conditions."""

    client: Any
    budget: Budget = field(default_factory=Budget)
    policy: ToolPolicy = field(
        default_factory=lambda: ToolPolicy(allowed=tuple(t.name for t in TOOLS))
    )
    limiter: RateLimiter = field(default_factory=RateLimiter)
    retry: Retry = field(default_factory=Retry)
    max_turns: int = 10
    max_tokens: int = 16_000
    model: str = MODEL
    system: str = SYSTEM_PROMPT
    enable_fallbacks: bool = True

    def run(self, task: str) -> AgentResult:
        transcript = Transcript()
        result = AgentResult(transcript=transcript, budget=self.budget)
        messages = [{"role": "user", "content": task}]

        try:
            for turn in range(1, self.max_turns + 1):
                result.turns = turn
                self.budget.check_before_request()
                response = self._request(messages, transcript)

                messages.append({"role": "assistant", "content": response.content})
                tool_results = self._handle_tools(response, transcript)

                if not tool_results:
                    result.text = _text_of(response)
                    break

                messages.append({"role": "user", "content": tool_results})
            else:
                raise TurnLimitReached(
                    f"stopped after {self.max_turns} turns without a final answer"
                )

            result.verdict = self._verdict(messages, transcript)

        except BudgetExceeded as exc:
            result.stopped_because = f"budget: {exc}"
            transcript.add("stopped", reason=str(exc))
        except GuardrailError as exc:
            result.stopped_because = f"guardrail: {exc}"
            transcript.add("stopped", reason=str(exc))

        return result

    # -- one request --------------------------------------------------------
    def _request(self, messages, transcript, **overrides):
        waited = self.limiter.acquire()
        if waited:
            transcript.add("rate_limited", waited_seconds=round(waited, 3))

        params = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # Adaptive thinking: the model decides how much to think per turn.
            "thinking": {"type": "adaptive"},
            "system": self.system,
            "messages": messages,
            "tools": [tool.definition() for tool in TOOLS],
        }
        if self.enable_fallbacks:
            # Route a refusal by category rather than returning nothing.
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        params.update(overrides)

        response = self.retry.run(
            lambda: self.client.beta.messages.create(**params), _is_retryable
        )
        usage = self.budget.record(response)
        transcript.add(
            "request",
            stop_reason=getattr(response, "stop_reason", None),
            usage=usage.as_dict(),
            attempts=self.retry.attempts_made,
        )

        # A refusal arrives as HTTP 200 with stop_reason "refusal", so it has to
        # be checked before anything reads response.content.
        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise GuardrailError(f"the model declined this request (category: {category})")

        return response

    # -- tools --------------------------------------------------------------
    def _handle_tools(self, response, transcript) -> list:
        """Run every tool_use block in one response, return all results together.

        All of them go back in a single user message: splitting them across
        messages teaches the model to stop calling tools in parallel.
        """
        results = []
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) != "tool_use":
                continue

            name = block.name
            # Inputs are parsed as JSON by the SDK; never string-match them.
            arguments = block.input if isinstance(block.input, dict) else json.loads(block.input)

            try:
                self.policy.check(name)
            except GuardrailError as exc:
                # A policy stop is final: nothing about the next turn changes it.
                transcript.add("tool_call", name=name, arguments=arguments, ok=False,
                               error=str(exc))
                raise

            self.policy.record(name)
            try:
                output = self.policy.truncate(run_tool(name, arguments))
                is_error = False
            except ToolError as exc:
                # Recoverable: hand the model the error so it can fix its call.
                output = f"error: {exc}"
                is_error = True

            transcript.add("tool_call", name=name, arguments=arguments, ok=not is_error,
                           error=output if is_error else None)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                "is_error": is_error,
            })
        return results

    # -- structured verdict -------------------------------------------------
    def _verdict(self, messages, transcript) -> Optional[dict]:
        """Ask for the same answer again as validated JSON.

        Structured outputs constrain the response to the schema, so the caller
        gets a dict it can rely on instead of parsing prose.
        """
        self.budget.check_before_request()
        response = self._request(
            messages + [{"role": "user",
                         "content": "Summarise your verdict as JSON matching the schema."}],
            transcript,
            tools=[],
            output_config={"format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
        )
        text = _text_of(response)
        try:
            return json.loads(text) if text else None
        except json.JSONDecodeError:
            transcript.add("verdict_unparseable", text=text[:400])
            return None


def _text_of(response) -> str:
    """Join the text blocks, skipping thinking and tool_use blocks."""
    parts = [
        block.text
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(parts).strip()
