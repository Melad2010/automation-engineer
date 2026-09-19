"""The loop, mostly through its failure paths — that is where agents actually go wrong."""

import json
import unittest

from agentkit import Agent, Budget, RateLimiter, ToolPolicy
from agentkit.guardrails import Retry
from agentkit.tools import TOOLS
from agentkit.transport import (
    FakeResponse,
    FakeUsage,
    ScriptedClient,
    ScriptedError,
    StopDetails,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    demo_script,
)

ALL_TOOLS = tuple(tool.name for tool in TOOLS)


def agent(script, **kwargs):
    kwargs.setdefault("budget", Budget(max_tokens=None, max_cost_usd=None, max_requests=None))
    kwargs.setdefault("policy", ToolPolicy(allowed=ALL_TOOLS))
    kwargs.setdefault("limiter", RateLimiter(sleep=lambda s: None, clock=lambda: 0.0))
    kwargs.setdefault("retry", Retry(sleep=lambda s: None))
    return Agent(client=ScriptedClient(script), **kwargs)


def tool_turn(name, arguments, call_id="c1"):
    return FakeResponse(
        content=[ThinkingBlock(), ToolUseBlock(call_id, name, arguments)],
        stop_reason="tool_use",
        usage=FakeUsage(100, 20),
    )


def text_turn(text="done"):
    return FakeResponse(content=[TextBlock(text)], usage=FakeUsage(100, 20))


def verdict_turn(payload=None):
    return FakeResponse(
        content=[TextBlock(json.dumps(payload or {"organisation": "X", "found": True}))],
        usage=FakeUsage(100, 20),
    )


class HappyPathTests(unittest.TestCase):
    def test_a_full_run_finishes_with_text_and_a_verdict(self):
        task = "Qualify nileyouth.example.org"
        result = agent(demo_script(task)).run(task)
        self.assertTrue(result.complete)
        self.assertIn("Nile Youth Foundation", result.text)
        self.assertEqual(result.verdict["contact_email"], "hello@nileyouth.example.org")

    def test_the_transcript_records_every_tool_call(self):
        task = "Qualify gizafoodbank.example.org"
        result = agent(demo_script(task)).run(task)
        self.assertEqual(
            [call["name"] for call in result.transcript.tool_calls()],
            ["lookup_company", "check_website", "score_fit"],
        )

    def test_parallel_tool_calls_come_back_in_one_user_message(self):
        # Splitting them across messages teaches the model to stop parallelising.
        script = [
            FakeResponse(
                content=[ToolUseBlock("a", "lookup_company", {"domain": "nileyouth.example.org"}),
                         ToolUseBlock("b", "check_website",
                                      {"url": "https://nileyouth.example.org"})],
                stop_reason="tool_use", usage=FakeUsage(100, 20),
            ),
            text_turn(), verdict_turn(),
        ]
        runner = agent(script)
        runner.run("Qualify nileyouth.example.org")
        second_request = runner.client.requests[1]
        results = [block for block in second_request["messages"][-1]["content"]
                   if block["type"] == "tool_result"]
        self.assertEqual(len(results), 2)

    def test_an_unknown_domain_produces_a_found_false_verdict_not_an_invention(self):
        task = "Qualify nowhere.example.org"
        result = agent(demo_script(task)).run(task)
        self.assertFalse(result.verdict["found"])
        self.assertIsNone(result.verdict["score"])


class RequestShapeTests(unittest.TestCase):
    def setUp(self):
        self.runner = agent([text_turn(), verdict_turn()])
        self.runner.run("Qualify nileyouth.example.org")
        self.first = self.runner.client.requests[0]

    def test_it_asks_for_opus_5_with_adaptive_thinking(self):
        self.assertEqual(self.first["model"], "claude-opus-5")
        self.assertEqual(self.first["thinking"], {"type": "adaptive"})

    def test_refusal_fallbacks_are_on_by_default(self):
        self.assertEqual(self.first["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", self.first["betas"])

    def test_every_tool_is_offered_with_a_strict_schema(self):
        names = [tool["name"] for tool in self.first["tools"]]
        self.assertEqual(sorted(names), sorted(ALL_TOOLS))
        self.assertTrue(all(tool["strict"] for tool in self.first["tools"]))

    def test_the_verdict_request_asks_for_schema_constrained_json(self):
        verdict_request = self.runner.client.requests[-1]
        self.assertEqual(verdict_request["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(verdict_request["tools"], [])

    def test_fallbacks_can_be_turned_off(self):
        runner = agent([text_turn(), verdict_turn()], enable_fallbacks=False)
        runner.run("Qualify nileyouth.example.org")
        self.assertNotIn("fallbacks", runner.client.requests[0])


class StopConditionTests(unittest.TestCase):
    def test_the_cost_budget_stops_the_run_mid_way(self):
        script = [tool_turn("lookup_company", {"domain": "nileyouth.example.org"})] * 6
        runner = agent(
            script,
            budget=Budget(max_tokens=None, max_cost_usd=0.0005, max_requests=None),
        )
        result = runner.run("Qualify nileyouth.example.org")
        self.assertFalse(result.complete)
        self.assertIn("cost", result.stopped_because)
        self.assertLess(len(runner.client.requests), 6)

    def test_the_request_budget_stops_the_run(self):
        script = [tool_turn("lookup_company", {"domain": "nileyouth.example.org"})] * 8
        runner = agent(
            script, budget=Budget(max_tokens=None, max_cost_usd=None, max_requests=3)
        )
        result = runner.run("Qualify nileyouth.example.org")
        self.assertIn("request limit", result.stopped_because)
        self.assertEqual(len(runner.client.requests), 3)

    def test_the_turn_limit_stops_a_model_that_never_concludes(self):
        script = [tool_turn("lookup_company", {"domain": "nileyouth.example.org"})] * 10
        result = agent(script, max_turns=4).run("Qualify nileyouth.example.org")
        self.assertIn("4 turns", result.stopped_because)

    def test_calling_one_tool_forever_is_stopped_by_the_policy(self):
        script = [tool_turn("lookup_company", {"domain": "nileyouth.example.org"})] * 10
        result = agent(
            script, policy=ToolPolicy(allowed=ALL_TOOLS, max_calls_per_tool=3)
        ).run("Qualify nileyouth.example.org")
        self.assertIn("guardrail", result.stopped_because)
        self.assertEqual(len(result.transcript.tool_calls()), 4)

    def test_a_tool_outside_the_allowlist_stops_the_run(self):
        script = [tool_turn("lookup_company", {"domain": "nileyouth.example.org"})]
        result = agent(
            script, policy=ToolPolicy(allowed=("check_website",))
        ).run("Qualify nileyouth.example.org")
        self.assertIn("not an allowed tool", result.stopped_because)

    def test_a_refusal_is_detected_before_any_content_is_read(self):
        script = [FakeResponse(content=[], stop_reason="refusal",
                               stop_details=StopDetails(category="cyber"),
                               usage=FakeUsage(50, 0))]
        result = agent(script).run("do something questionable")
        self.assertIn("declined", result.stopped_because)
        self.assertIn("cyber", result.stopped_because)

    def test_a_stopped_run_still_reports_what_it_spent(self):
        script = [tool_turn("lookup_company", {"domain": "nileyouth.example.org"})] * 5
        runner = agent(
            script, budget=Budget(max_tokens=None, max_cost_usd=None, max_requests=2)
        )
        result = runner.run("Qualify nileyouth.example.org")
        self.assertEqual(result.budget.usage.requests, 2)
        self.assertGreater(result.budget.spent_usd, 0)


class ToolFailureTests(unittest.TestCase):
    def test_a_bad_tool_argument_goes_back_to_the_model_instead_of_ending_the_run(self):
        script = [
            tool_turn("score_fit", {"employees": 10, "annual_budget_usd": -5,
                                    "manual_hours_per_week": 2}),
            text_turn("I passed a negative budget; corrected."),
            verdict_turn(),
        ]
        runner = agent(script)
        result = runner.run("Qualify nileyouth.example.org")

        self.assertTrue(result.complete)
        call = result.transcript.tool_calls()[0]
        self.assertFalse(call["ok"])

        sent_back = runner.client.requests[1]["messages"][-1]["content"][0]
        self.assertTrue(sent_back["is_error"])
        self.assertIn("cannot be negative", sent_back["content"])

    def test_an_enormous_tool_result_is_truncated_before_it_reaches_the_model(self):
        runner = agent(
            [tool_turn("lookup_company", {"domain": "nileyouth.example.org"}),
             text_turn(), verdict_turn()],
            policy=ToolPolicy(allowed=ALL_TOOLS, max_result_chars=40),
        )
        runner.run("Qualify nileyouth.example.org")
        sent_back = runner.client.requests[1]["messages"][-1]["content"][0]
        self.assertIn("truncated", sent_back["content"])


class RetryAndRateLimitTests(unittest.TestCase):
    def test_a_503_is_retried_and_the_run_continues(self):
        script = [ScriptedError("upstream busy", 503), text_turn("recovered"), verdict_turn()]
        result = agent(script).run("Qualify nileyouth.example.org")
        self.assertTrue(result.complete)
        self.assertEqual(result.text, "recovered")

    def test_a_400_is_not_retried(self):
        error = ScriptedError("bad request", 400)
        error.__class__.__name__  # status-based classification, not class name
        script = [error, text_turn()]
        with self.assertRaises(ScriptedError):
            agent(script).run("Qualify nileyouth.example.org")

    def test_repeated_failures_give_up_rather_than_looping(self):
        script = [ScriptedError("busy", 503)] * 3
        runner = agent(script, retry=Retry(max_attempts=3, sleep=lambda s: None))
        with self.assertRaises(ScriptedError):
            runner.run("Qualify nileyouth.example.org")
        self.assertEqual(len(runner.client.requests), 3)

    def test_the_rate_limiter_paces_the_requests_and_says_so(self):
        clock = {"now": 0.0}
        script = [tool_turn("lookup_company", {"domain": "nileyouth.example.org"}),
                  tool_turn("check_website", {"url": "https://nileyouth.example.org"}, "c2"),
                  text_turn(), verdict_turn()]
        runner = agent(
            script,
            limiter=RateLimiter(max_calls=1, window=30,
                                sleep=lambda s: clock.__setitem__("now", clock["now"] + s),
                                clock=lambda: clock["now"]),
        )
        result = runner.run("Qualify nileyouth.example.org")
        self.assertTrue(result.complete)
        self.assertEqual(len(result.transcript.of_kind("rate_limited")), 3)


class ResultTests(unittest.TestCase):
    def test_as_dict_is_json_serialisable(self):
        task = "Qualify nileyouth.example.org"
        payload = agent(demo_script(task)).run(task).as_dict()
        json.dumps(payload)  # must not raise
        self.assertTrue(payload["complete"])
        self.assertEqual(len(payload["tool_calls"]), 3)

    def test_an_unparseable_verdict_is_recorded_rather_than_crashing(self):
        script = [text_turn("all done"),
                  FakeResponse(content=[TextBlock("not json at all")],
                               usage=FakeUsage(10, 10))]
        result = agent(script).run("Qualify nileyouth.example.org")
        self.assertIsNone(result.verdict)
        self.assertTrue(result.transcript.of_kind("verdict_unparseable"))


if __name__ == "__main__":
    unittest.main()
