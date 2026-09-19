import json
import unittest

from agentkit.tools import TOOLS, ToolError, check_website, lookup_company, run_tool, score_fit


class LookupTests(unittest.TestCase):
    def test_finds_a_known_organisation(self):
        record = lookup_company("nileyouth.example.org")
        self.assertTrue(record["found"])
        self.assertEqual(record["name"], "Nile Youth Foundation")

    def test_normalises_a_full_url_to_a_domain(self):
        self.assertTrue(lookup_company("https://www.nileyouth.example.org/about")["found"])

    def test_an_unknown_domain_says_so_and_tells_the_model_not_to_invent_one(self):
        record = lookup_company("nowhere.example.org")
        self.assertFalse(record["found"])
        self.assertIn("Do not invent", record["message"])
        self.assertIn("nileyouth.example.org", record["known_domains"])

    def test_an_empty_domain_is_an_error(self):
        with self.assertRaises(ToolError):
            lookup_company("   ")


class WebsiteTests(unittest.TestCase):
    def test_a_well_formed_reachable_url(self):
        result = check_website("https://nileyouth.example.org")
        self.assertTrue(result["well_formed"])
        self.assertTrue(result["reachable"])

    def test_a_known_failing_site_reports_its_status(self):
        result = check_website("https://sinaiclinic.example.org")
        self.assertEqual(result["status"], 503)
        self.assertFalse(result["reachable"])

    def test_a_malformed_url_is_rejected_not_repaired(self):
        result = check_website("www.nileyouth.example.org")
        self.assertFalse(result["well_formed"])
        self.assertIsNone(result["status"])

    def test_an_unknown_host_reports_an_unknown_status_rather_than_guessing(self):
        result = check_website("https://nowhere.example.org")
        self.assertTrue(result["well_formed"])
        self.assertIsNone(result["status"])


class ScoreTests(unittest.TestCase):
    def test_the_score_is_the_sum_of_three_capped_components(self):
        result = score_fit(100, 3_000_000, 20)
        self.assertEqual(result["score"], 100.0)
        self.assertEqual(result["band"], "strong")

    def test_components_are_capped_so_one_huge_input_cannot_dominate(self):
        result = score_fit(100_000, 0, 0)
        self.assertEqual(result["components"]["size"], 35.0)
        self.assertEqual(result["score"], 35.0)

    def test_a_tiny_lead_lands_in_the_lowest_band(self):
        self.assertEqual(score_fit(5, 50_000, 1)["band"], "too small for now")

    def test_the_bands_are_contiguous(self):
        self.assertEqual(score_fit(100, 3_000_000, 5)["band"], "strong")
        self.assertEqual(score_fit(60, 1_500_000, 5)["band"], "worth a conversation")

    def test_text_where_a_number_belongs_is_an_error(self):
        with self.assertRaises(ToolError):
            score_fit("many", 1, 1)

    def test_a_bool_is_not_accepted_as_a_number(self):
        with self.assertRaises(ToolError):
            score_fit(True, 1, 1)

    def test_negatives_are_rejected(self):
        with self.assertRaises(ToolError):
            score_fit(10, -1, 1)


class DispatchTests(unittest.TestCase):
    def test_run_tool_returns_json_text(self):
        payload = json.loads(run_tool("lookup_company", {"domain": "nileyouth.example.org"}))
        self.assertTrue(payload["found"])

    def test_an_unknown_tool_is_refused(self):
        with self.assertRaises(ToolError):
            run_tool("rm_rf", {})

    def test_a_missing_required_argument_is_named(self):
        with self.assertRaises(ToolError) as caught:
            run_tool("score_fit", {"employees": 10})
        self.assertIn("annual_budget_usd", str(caught.exception))

    def test_an_unexpected_argument_is_named(self):
        with self.assertRaises(ToolError) as caught:
            run_tool("lookup_company", {"domain": "x.org", "sudo": True})
        self.assertIn("sudo", str(caught.exception))


class DefinitionTests(unittest.TestCase):
    def test_every_tool_is_strict_with_a_closed_schema(self):
        for tool in TOOLS:
            definition = tool.definition()
            with self.subTest(tool=tool.name):
                self.assertTrue(definition["strict"])
                self.assertFalse(definition["input_schema"]["additionalProperties"])
                self.assertTrue(definition["input_schema"]["required"])

    def test_every_tool_has_a_description_worth_reading(self):
        for tool in TOOLS:
            with self.subTest(tool=tool.name):
                self.assertGreater(len(tool.description), 60)


if __name__ == "__main__":
    unittest.main()
