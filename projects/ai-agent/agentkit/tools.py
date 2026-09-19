"""The agent's tools.

They read a local dataset rather than the live web, so the demo is reproducible
and a test run costs nothing. Swapping `_DIRECTORY` for a real lookup is the
only change needed to point this at production data.

Every tool validates its own input. A tool that trusts what the model passed it
is a tool that will one day be handed a string where it expected a number.
"""

import json
import re
from dataclasses import dataclass
from typing import Callable

_URL_SHAPE = re.compile(r"^https?://[^\s/]+\.[^\s/]+", re.IGNORECASE)


class ToolError(ValueError):
    """Raised for input a tool cannot act on. Sent back as an error result."""


# A stand-in for whatever system actually holds the records.
_DIRECTORY = {
    "nileyouth.example.org": {
        "name": "Nile Youth Foundation",
        "sector": "Education",
        "country": "Egypt",
        "employees": 48,
        "annual_budget_usd": 1_200_000,
        "tech_stack": ["Google Workspace", "Airtable", "Zapier"],
        "website_status": 200,
        "public_email": "hello@nileyouth.example.org",
        "notes": "Runs monthly reporting by hand across 14 spreadsheets.",
    },
    "deltawater.example.org": {
        "name": "Delta Water Trust",
        "sector": "Environment",
        "country": "Egypt",
        "employees": 9,
        "annual_budget_usd": 180_000,
        "tech_stack": ["Excel"],
        "website_status": 200,
        "public_email": "info@deltawater.example.org",
        "notes": "Two staff, no budget line for software.",
    },
    "gizafoodbank.example.org": {
        "name": "Giza Food Bank",
        "sector": "Livelihoods",
        "country": "Egypt",
        "employees": 130,
        "annual_budget_usd": 4_500_000,
        "tech_stack": ["Salesforce", "Excel", "Power BI"],
        "website_status": 200,
        "public_email": "give@gizafoodbank.example.org",
        "notes": "Warehouse stock reconciled weekly from three CSV exports.",
    },
    "sinaiclinic.example.org": {
        "name": "Sinai Mobile Clinic",
        "sector": "Health",
        "country": "Egypt",
        "employees": 22,
        "annual_budget_usd": 640_000,
        "tech_stack": ["Google Sheets"],
        "website_status": 503,
        "public_email": "clinic@sinai.example.org",
        "notes": "Site has been returning 503 for a week.",
    },
}


def lookup_company(domain: str) -> dict:
    """Return the directory record for a domain, or say plainly that there is none."""
    if not isinstance(domain, str) or not domain.strip():
        raise ToolError("domain must be a non-empty string")
    key = domain.strip().lower().removeprefix("http://").removeprefix("https://")
    key = key.removeprefix("www.").split("/")[0]

    record = _DIRECTORY.get(key)
    if record is None:
        return {
            "found": False,
            "domain": key,
            "message": "No record for this domain. Do not invent one.",
            "known_domains": sorted(_DIRECTORY),
        }
    return {"found": True, "domain": key, **record}


def check_website(url: str) -> dict:
    """Check a URL's shape and its last known status. Never guesses a status."""
    if not isinstance(url, str) or not url.strip():
        raise ToolError("url must be a non-empty string")
    url = url.strip()
    if not _URL_SHAPE.match(url):
        return {
            "url": url,
            "well_formed": False,
            "reason": "not a http(s) URL with a dotted host",
            "status": None,
        }

    host = url.split("//", 1)[1].split("/")[0].removeprefix("www.").lower()
    record = _DIRECTORY.get(host)
    if record is None:
        return {"url": url, "well_formed": True, "status": None,
                "reason": "host is not in the directory, status unknown"}
    return {"url": url, "well_formed": True, "status": record["website_status"],
            "reachable": record["website_status"] < 400}


def score_fit(employees: int, annual_budget_usd: float, manual_hours_per_week: float) -> dict:
    """Score how well a lead fits the service, 0-100, with the reasoning shown.

    Deterministic on purpose. The model decides what to look up and what to
    conclude; it does not get to decide the arithmetic.
    """
    for name, value in (("employees", employees),
                        ("annual_budget_usd", annual_budget_usd),
                        ("manual_hours_per_week", manual_hours_per_week)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ToolError(f"{name} must be a number, got {value!r}")
        if value < 0:
            raise ToolError(f"{name} cannot be negative")

    size = min(35.0, employees / 100 * 35)
    budget = min(35.0, annual_budget_usd / 3_000_000 * 35)
    pain = min(30.0, manual_hours_per_week / 20 * 30)
    score = round(size + budget + pain, 1)

    if score >= 65:
        band = "strong"
    elif score >= 40:
        band = "worth a conversation"
    else:
        band = "too small for now"

    return {
        "score": score,
        "band": band,
        "components": {"size": round(size, 1), "budget": round(budget, 1),
                       "manual_effort": round(pain, 1)},
        "explanation": (
            "Score is size (max 35) + budget (max 35) + manual effort (max 30). "
            "It is computed, not estimated."
        ),
    }


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    run: Callable

    def definition(self) -> dict:
        """The tool as the Messages API wants it.

        `strict: true` with `additionalProperties: false` means the arguments
        that arrive are guaranteed to match the schema — one whole class of
        runtime checking that stops being necessary.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
            "strict": True,
        }


TOOLS = (
    Tool(
        name="lookup_company",
        description=(
            "Look up an organisation in the directory by its web domain. Returns the "
            "record, or found=false when the domain is not listed. Never returns a "
            "guess — if it is not found, say so."
        ),
        schema={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Web domain, e.g. nileyouth.example.org",
                }
            },
            "required": ["domain"],
            "additionalProperties": False,
        },
        run=lookup_company,
    ),
    Tool(
        name="check_website",
        description=(
            "Check that a URL is well formed and report its last known HTTP status. "
            "Returns status=null when the status is genuinely unknown."
        ),
        schema={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full http(s) URL"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        run=check_website,
    ),
    Tool(
        name="score_fit",
        description=(
            "Compute a 0-100 fit score from headcount, annual budget and estimated "
            "manual hours per week. The arithmetic is fixed; use this rather than "
            "estimating a score yourself."
        ),
        schema={
            "type": "object",
            "properties": {
                "employees": {"type": "integer", "minimum": 0},
                "annual_budget_usd": {"type": "number", "minimum": 0},
                "manual_hours_per_week": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Your estimate from the record's notes.",
                },
            },
            "required": ["employees", "annual_budget_usd", "manual_hours_per_week"],
            "additionalProperties": False,
        },
        run=score_fit,
    ),
)

TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}


def run_tool(name: str, arguments: dict) -> str:
    """Execute one tool and return its result as JSON text.

    Raises ToolError for bad input; the caller turns that into an error result
    so the model can correct itself rather than the run falling over.
    """
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        raise ToolError(f"unknown tool {name!r}")
    if not isinstance(arguments, dict):
        raise ToolError(f"{name} expects an object of arguments, got {type(arguments).__name__}")

    required = tool.schema.get("required", [])
    missing = [key for key in required if key not in arguments]
    if missing:
        raise ToolError(f"{name} is missing required argument(s): {', '.join(missing)}")
    unexpected = [key for key in arguments if key not in tool.schema.get("properties", {})]
    if unexpected:
        raise ToolError(f"{name} got unexpected argument(s): {', '.join(unexpected)}")

    return json.dumps(tool.run(**arguments), ensure_ascii=False)
