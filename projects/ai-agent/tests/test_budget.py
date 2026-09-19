import unittest

from agentkit.budget import Budget, BudgetExceeded, Pricing, Usage
from agentkit.transport import FakeResponse, FakeUsage


def response(input_tokens=0, output_tokens=0, cache_read=0, cache_write=0):
    return FakeResponse(usage=FakeUsage(input_tokens, output_tokens, cache_write, cache_read))


class UsageTests(unittest.TestCase):
    def test_reads_every_field_the_sdk_reports(self):
        usage = Usage.from_response(response(100, 50, cache_read=20, cache_write=10))
        self.assertEqual(
            (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
             usage.cache_write_tokens, usage.requests),
            (100, 50, 20, 10, 1),
        )

    def test_a_response_without_usage_still_counts_as_a_request(self):
        usage = Usage.from_response(object())
        self.assertEqual((usage.total_tokens, usage.requests), (0, 1))

    def test_totals_add_up(self):
        usage = Usage.from_response(response(100, 50, 20, 10))
        self.assertEqual(usage.total_tokens, 180)


class PricingTests(unittest.TestCase):
    def test_cost_uses_the_per_million_rates(self):
        pricing = Pricing(input_per_mtok=5.0, output_per_mtok=25.0)
        cost = pricing.cost(Usage(input_tokens=1_000_000, output_tokens=1_000_000))
        self.assertAlmostEqual(cost, 30.0, places=6)

    def test_cached_reads_are_cheaper_than_fresh_input(self):
        pricing = Pricing()
        fresh = pricing.cost(Usage(input_tokens=100_000))
        cached = pricing.cost(Usage(cache_read_tokens=100_000))
        self.assertLess(cached, fresh)


class BudgetStopTests(unittest.TestCase):
    def test_a_run_under_every_limit_is_allowed(self):
        budget = Budget(max_tokens=100_000, max_cost_usd=1.0, max_requests=5,
                        reserve_tokens=1_000)
        budget.record(response(1_000, 200))
        budget.check_before_request()  # must not raise

    def test_the_request_limit_stops_the_next_request(self):
        budget = Budget(max_requests=2, max_tokens=None, max_cost_usd=None)
        budget.record(response(10, 10))
        budget.record(response(10, 10))
        with self.assertRaises(BudgetExceeded) as caught:
            budget.check_before_request()
        self.assertIn("request limit", str(caught.exception))

    def test_the_reserve_stops_a_request_the_budget_cannot_pay_to_answer(self):
        # 9,000 spent of 10,000, with 5,000 reserved for the reply: refuse now,
        # rather than discovering the overrun after paying for it.
        budget = Budget(max_tokens=10_000, max_cost_usd=None, max_requests=None,
                        reserve_tokens=5_000)
        budget.record(response(9_000, 0))
        with self.assertRaises(BudgetExceeded) as caught:
            budget.check_before_request()
        self.assertIn("reserved", str(caught.exception))

    def test_without_a_reserve_the_same_spend_is_allowed(self):
        budget = Budget(max_tokens=10_000, max_cost_usd=None, max_requests=None,
                        reserve_tokens=0)
        budget.record(response(9_000, 0))
        budget.check_before_request()

    def test_exceeding_the_token_budget_stops_the_run_at_the_response(self):
        budget = Budget(max_tokens=1_000, max_cost_usd=None, max_requests=None)
        with self.assertRaises(BudgetExceeded):
            budget.record(response(900, 200))

    def test_exceeding_the_cost_budget_stops_the_run(self):
        budget = Budget(max_tokens=None, max_cost_usd=0.01, max_requests=None)
        with self.assertRaises(BudgetExceeded) as caught:
            budget.record(response(0, 1_000_000))
        self.assertIn("cost budget exceeded", str(caught.exception))

    def test_a_limit_of_none_is_not_enforced(self):
        budget = Budget(max_tokens=None, max_cost_usd=None, max_requests=None)
        for _ in range(50):
            budget.record(response(100_000, 100_000))
        budget.check_before_request()

    def test_remaining_never_goes_negative(self):
        budget = Budget(max_tokens=1_000, max_cost_usd=None, max_requests=None)
        try:
            budget.record(response(5_000, 0))
        except BudgetExceeded:
            pass
        self.assertEqual(budget.remaining_tokens, 0)


if __name__ == "__main__":
    unittest.main()
