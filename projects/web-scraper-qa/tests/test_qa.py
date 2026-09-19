import unittest

from scrapekit.models import Record
from scrapekit.qa import build_report, dedupe


def _record(name="Org", category="Cat", city="City", website="", email="", source="https://x.org/1"):
    return Record(
        name=name, category=category, city=city, website=website, email=email, source_url=source
    )


class DedupeTests(unittest.TestCase):
    def test_keeps_the_first_occurrence(self):
        first = _record(name="Delta Trust", city="Tanta", email="a@x.org")
        second = _record(name="Delta Trust", city="Tanta", email="b@x.org")
        kept, duplicates = dedupe([first, second])
        self.assertEqual([r.email for r in kept], ["a@x.org"])
        self.assertEqual(len(duplicates), 1)

    def test_key_ignores_case_and_extra_spaces(self):
        kept, duplicates = dedupe([_record(name="Delta  Trust"), _record(name="delta trust")])
        self.assertEqual(len(kept), 1)
        self.assertEqual(duplicates[0][0], "delta trust city")

    def test_distinct_cities_are_not_duplicates(self):
        kept, duplicates = dedupe([_record(city="Cairo"), _record(city="Giza")])
        self.assertEqual(len(kept), 2)
        self.assertEqual(duplicates, [])


class ReportTests(unittest.TestCase):
    def test_variance_compares_delivered_against_the_published_total(self):
        report = build_report([_record()], [], 1, 1, expected_rows=3)
        self.assertEqual(report.variance, -2)
        self.assertFalse(report.clean)

    def test_variance_is_none_when_the_source_publishes_no_total(self):
        report = build_report([_record()], [], 1, 1)
        self.assertIsNone(report.variance)

    def test_a_missing_required_field_is_reported_not_filled(self):
        report = build_report([_record(category="")], [], 1, 1)
        self.assertEqual(report.rows_missing_required[0]["missing"], ["category"])
        self.assertFalse(report.clean)

    def test_malformed_website_is_flagged(self):
        report = build_report([_record(website="www.example.org")], [], 1, 1)
        self.assertEqual(len(report.invalid_websites), 1)

    def test_well_formed_website_passes(self):
        report = build_report([_record(website="https://example.org/a")], [], 1, 1)
        self.assertEqual(report.invalid_websites, [])

    def test_malformed_email_is_flagged(self):
        report = build_report([_record(email="a(at)example.org")], [], 1, 1)
        self.assertEqual(len(report.invalid_emails), 1)

    def test_failed_pages_make_the_report_dirty(self):
        report = build_report([_record()], [], 2, 1, failed_pages=[("https://x.org/2", "HTTP 500")])
        self.assertFalse(report.clean)
        self.assertEqual(report.failed_pages[0]["reason"], "HTTP 500")

    def test_a_complete_crawl_reports_clean(self):
        rows = [_record(name="A", website="https://a.org", email="a@a.org"),
                _record(name="B", website="https://b.org", email="b@b.org")]
        report = build_report(rows, [], 1, 1, expected_rows=2)
        self.assertTrue(report.clean)

    def test_completeness_counts_per_field(self):
        rows = [_record(website="https://a.org"), _record(website="")]
        report = build_report(rows, [], 1, 1)
        self.assertEqual(report.field_completeness["website"]["present"], 1)
        self.assertEqual(report.field_completeness["website"]["percent"], 50.0)

    def test_rows_found_includes_the_duplicates_that_were_removed(self):
        kept, duplicates = dedupe([_record(), _record()])
        report = build_report(kept, duplicates, 1, 1)
        self.assertEqual(report.rows_found, 2)
        self.assertEqual(report.rows_delivered, 1)
        self.assertEqual(report.duplicates_removed, 1)


if __name__ == "__main__":
    unittest.main()
