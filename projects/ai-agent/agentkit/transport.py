"""Where the responses come from.

`live_client()` is the real Anthropic SDK. `ScriptedClient` replays a fixed
sequence of responses with the same shape, which is what makes the dry run and
the whole test suite work with no API key, no network and no cost.

The scripted client is not a mock of the agent's logic — the agent runs exactly
the same loop, the same guardrails and the same tool code either way. Only the
model's side of the conversation is canned.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .tools import _DIRECTORY


def live_client(**kwargs):
    """The real client. Credentials resolve from the environment or an `ant` profile."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - only without the SDK
        raise SystemExit(
            "Live mode needs the Anthropic SDK:\n"
            "    pip install anthropic\n"
            "Then set ANTHROPIC_API_KEY, or run `ant auth login`.\n"
            "Everything else in this project runs offline with --dry-run."
        ) from exc
    return anthropic.Anthropic(**kwargs)


# --------------------------------------------------------------------------
# Response objects shaped like the SDK's, so the agent cannot tell the
# difference and no production code has to know about tests.
# --------------------------------------------------------------------------


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class ThinkingBlock:
    thinking: str = ""
    type: str = "thinking"


@dataclass
class FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class StopDetails:
    type: str = "refusal"
    category: Optional[str] = None
    explanation: str = ""


@dataclass
class FakeResponse:
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)
    stop_details: Optional[StopDetails] = None


class ScriptedError(RuntimeError):
    """An error the script raises on purpose, to exercise the retry path."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class ScriptedClient:
    """Replays `script` — a list of FakeResponse or Exception — one per request."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.beta = _Beta(self)

    def _next(self, params):
        # Snapshot the messages list. The agent keeps appending to the same
        # list between turns, so storing the reference would mean every
        # recorded request appeared to contain the whole conversation.
        recorded = dict(params)
        if "messages" in recorded:
            recorded["messages"] = list(recorded["messages"])
        self.requests.append(recorded)
        if not self.script:
            raise AssertionError(
                f"the script ran out after {len(self.requests)} request(s); "
                "the agent asked for one more"
            )
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _Beta:
    def __init__(self, client):
        self.messages = _BetaMessages(client)


class _BetaMessages:
    def __init__(self, client):
        self._client = client

    def create(self, **params):
        return self._client._next(params)


# --------------------------------------------------------------------------
# The demo script: a plausible three-turn run for any domain in the directory.
# --------------------------------------------------------------------------

_DOMAIN = re.compile(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", re.IGNORECASE)


def _estimate_manual_hours(record) -> float:
    """Stand-in for the judgement the model makes from the record's notes."""
    notes = record.get("notes", "").lower()
    if "by hand" in notes or "reconcil" in notes:
        return min(24.0, max(4.0, record["employees"] / 6))
    return 3.0


def demo_script(task: str) -> list:
    """Build a canned but coherent run for whatever domain the task mentions."""
    match = _DOMAIN.search(task or "")
    domain = match.group(0).lower() if match else "unknown.example.org"
    record = _DIRECTORY.get(domain)

    if record is None:
        return [
            FakeResponse(
                content=[
                    ThinkingBlock(),
                    TextBlock("Looking this one up before saying anything about it."),
                    ToolUseBlock("call_1", "lookup_company", {"domain": domain}),
                ],
                stop_reason="tool_use",
                usage=FakeUsage(input_tokens=1_180, output_tokens=140),
            ),
            FakeResponse(
                content=[TextBlock(
                    f"There is no directory record for {domain}, so I have nothing to "
                    "qualify. I am not going to invent a headcount or a budget for it. "
                    "Ask the lead directly for size, budget and where the manual work "
                    "sits, and I will score it then."
                )],
                usage=FakeUsage(input_tokens=1_520, output_tokens=180),
            ),
            FakeResponse(
                content=[TextBlock(json.dumps({
                    "organisation": domain,
                    "found": False,
                    "score": None,
                    "band": "unknown",
                    "first_automation": "none proposed — no record to work from",
                    "biggest_risk": "the organisation is not in the directory at all",
                    "contact_email": None,
                }))],
                usage=FakeUsage(input_tokens=1_640, output_tokens=110),
            ),
        ]

    hours = _estimate_manual_hours(record)
    return [
        FakeResponse(
            content=[
                ThinkingBlock(),
                TextBlock("Pulling the record and checking the site is actually up."),
                ToolUseBlock("call_1", "lookup_company", {"domain": domain}),
                ToolUseBlock("call_2", "check_website", {"url": f"https://{domain}"}),
            ],
            stop_reason="tool_use",
            usage=FakeUsage(input_tokens=1_180, output_tokens=210),
        ),
        FakeResponse(
            content=[
                ToolUseBlock("call_3", "score_fit", {
                    "employees": record["employees"],
                    "annual_budget_usd": record["annual_budget_usd"],
                    "manual_hours_per_week": hours,
                }),
            ],
            stop_reason="tool_use",
            usage=FakeUsage(input_tokens=1_920, output_tokens=160),
        ),
        FakeResponse(
            content=[TextBlock(_summary(record, domain, hours))],
            usage=FakeUsage(input_tokens=2_310, output_tokens=420,
                            cache_read_input_tokens=1_100),
        ),
        FakeResponse(
            content=[TextBlock(json.dumps(_verdict(record, domain, hours)))],
            usage=FakeUsage(input_tokens=2_480, output_tokens=190,
                            cache_read_input_tokens=2_300),
        ),
    ]


def _scored(record, hours):
    from .tools import score_fit

    return score_fit(record["employees"], record["annual_budget_usd"], hours)


def _first_automation(record) -> str:
    notes = record.get("notes", "").lower()
    if "spreadsheet" in notes or "by hand" in notes:
        return "a single monthly report built from the existing sheets, refreshed in one click"
    if "csv" in notes or "reconcil" in notes:
        return "a reconciliation script over the three CSV exports, with a variance report"
    return "a quote or reporting tool, once the manual work is pinned down"


def _risk(record) -> str:
    if record["website_status"] >= 400:
        return (
            f"their own site is returning {record['website_status']} — whoever owns "
            "infrastructure there may already be stretched, or gone"
        )
    if record["annual_budget_usd"] < 250_000:
        return "the budget is small enough that any paid tooling is a real decision"
    if record["employees"] < 15:
        return "too few people for the saved hours to add up to much"
    return "no named owner for the workflow yet, which is how pilots quietly stall"


def _summary(record, domain, hours) -> str:
    scored = _scored(record, hours)
    return (
        f"{record['name']} ({domain}) scores {scored['score']} — {scored['band']}.\n\n"
        f"{record['employees']} staff, a {record['annual_budget_usd']:,.0f} USD annual "
        f"budget, running on {', '.join(record['tech_stack'])}. Their notes say: "
        f"{record['notes']}\n\n"
        f"First thing I would build: {_first_automation(record)}.\n\n"
        f"Biggest reason this might not work: {_risk(record)}."
    )


def _verdict(record, domain, hours) -> dict:
    scored = _scored(record, hours)
    return {
        "organisation": record["name"],
        "found": True,
        "score": scored["score"],
        "band": scored["band"],
        "first_automation": _first_automation(record),
        "biggest_risk": _risk(record),
        "contact_email": record["public_email"],
    }
