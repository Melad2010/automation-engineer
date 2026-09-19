#!/usr/bin/env python3
"""Qualify a lead, with the guardrails on.

    python3 run.py --dry-run                       # offline, no key, no cost
    python3 run.py --dry-run --domain gizafoodbank.example.org
    python3 run.py --domain nileyouth.example.org  # live: needs the SDK and a key

    python3 run.py --dry-run --budget-usd 0.001    # watch the budget stop it

--dry-run replays a canned model transcript through the real agent loop: the
same guardrails, the same tools, the same budget accounting. Only the model's
side of the conversation is scripted.
"""

import argparse
import json
import sys

from agentkit import Agent, Budget, Pricing, RateLimiter, ToolPolicy
from agentkit.guardrails import Retry
from agentkit.tools import TOOLS, _DIRECTORY
from agentkit.transport import ScriptedClient, demo_script, live_client


def render(result) -> str:
    lines = [
        "=" * 72,
        f"Run {'completed' if result.complete else 'stopped early'}"
        f"  ({result.turns} turn{'s' if result.turns != 1 else ''})",
        "=" * 72,
    ]
    if not result.complete:
        lines.append(f"Reason: {result.stopped_because}")
        lines.append("")

    if result.text:
        lines += [result.text, ""]

    calls = result.transcript.tool_calls()
    if calls:
        lines.append("Tool calls")
        for call in calls:
            mark = "ok " if call["ok"] else "ERR"
            arguments = ", ".join(f"{k}={v!r}" for k, v in call["arguments"].items())
            lines.append(f"  [{mark}] {call['name']}({arguments})")
            if not call["ok"]:
                lines.append(f"         {call['error']}")
        lines.append("")

    waits = result.transcript.of_kind("rate_limited")
    if waits:
        lines.append(f"Rate limiter paused {len(waits)} time(s), "
                     f"{sum(w['waited_seconds'] for w in waits):.1f}s total")
        lines.append("")

    if result.verdict:
        lines += ["Verdict (schema-validated)", json.dumps(result.verdict, indent=2), ""]

    budget = result.budget
    if budget:
        usage = budget.usage
        lines += [
            "-" * 72,
            f"{usage.requests} request(s)  "
            f"in {usage.input_tokens:,} / out {usage.output_tokens:,} / "
            f"cached {usage.cache_read_tokens:,} tokens",
            f"Spent ${budget.spent_usd:.4f}"
            + (f" of ${budget.max_cost_usd:.2f}" if budget.max_cost_usd else ""),
        ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--domain", default="nileyouth.example.org")
    parser.add_argument("--dry-run", action="store_true",
                        help="replay a canned transcript: no key, no network, no cost")
    parser.add_argument("--model", default=None, help="override the model id")
    parser.add_argument("--budget-usd", type=float, default=1.00)
    parser.add_argument("--budget-tokens", type=int, default=400_000)
    parser.add_argument("--max-requests", type=int, default=24)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--rate", type=int, default=8, help="requests per minute")
    parser.add_argument("--json", action="store_true", help="print the run as JSON")
    parser.add_argument("--list-leads", action="store_true", help="show the demo directory")
    args = parser.parse_args(argv)

    if args.list_leads:
        for domain, record in sorted(_DIRECTORY.items()):
            print(f"{domain:<32}{record['name']:<28}{record['employees']:>4} staff")
        return 0

    task = (
        f"Qualify {args.domain} as a lead for automation work. "
        "Look it up, check the site, score the fit, and tell me the one thing "
        "you would build first."
    )

    budget = Budget(
        max_tokens=args.budget_tokens,
        max_cost_usd=args.budget_usd,
        max_requests=args.max_requests,
        pricing=Pricing(model=args.model) if args.model else Pricing(),
    )
    agent = Agent(
        client=ScriptedClient(demo_script(task)) if args.dry_run else live_client(),
        budget=budget,
        policy=ToolPolicy(allowed=tuple(tool.name for tool in TOOLS)),
        limiter=RateLimiter(max_calls=args.rate, window=60.0),
        retry=Retry(),
        max_turns=args.max_turns,
        model=args.model or Agent.model,
    )

    result = agent.run(task)
    print(json.dumps(result.as_dict(), indent=2) if args.json else render(result))
    return 0 if result.complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
