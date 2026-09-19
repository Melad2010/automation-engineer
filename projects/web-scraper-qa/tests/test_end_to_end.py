import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

import run
from scrapekit import Fetcher
from scrapekit.crawl import crawl

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class CrawlFixturesTests(unittest.TestCase):
    """The bundled fixtures carry every defect the QA report is meant to catch."""

    @classmethod
    def setUpClass(cls):
        cls.result = crawl(
            (FIXTURES / "page-1.html").as_uri(), fetcher=Fetcher(delay=0)
        )

    def test_follows_the_pager_to_the_last_page(self):
        self.assertEqual(self.result.report.pages_fetched, 3)

    def test_delivers_every_unique_row(self):
        self.assertEqual(self.result.report.rows_delivered, 12)
        self.assertEqual(self.result.report.duplicates_removed, 1)

    def test_reads_the_published_total_and_reports_the_variance(self):
        self.assertEqual(self.result.report.expected_rows, 13)
        self.assertEqual(self.result.report.variance, -1)

    def test_every_row_carries_a_source_url(self):
        self.assertTrue(all(r.source_url for r in self.result.records))

    def test_catches_the_planted_defects(self):
        report = self.result.report
        self.assertEqual(len(report.rows_missing_required), 1)
        self.assertEqual(len(report.invalid_emails), 1)
        self.assertFalse(report.clean)


class CliTests(unittest.TestCase):
    def test_cli_writes_dataset_and_report(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            code = run.main(
                ["--start", str(FIXTURES / "page-1.html"), "--out", tmp, "--delay", "0"]
            )
            self.assertEqual(code, 0)
            out = Path(tmp)
            with (out / "dataset.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 12)
            self.assertIn("source_url", rows[0])
            self.assertEqual(len(json.loads((out / "dataset.json").read_text())), 12)
            self.assertIn("# QA report", (out / "qa-report.md").read_text())
            self.assertIn("rows_delivered", (out / "qa-report.json").read_text())

    def test_fail_on_dirty_exits_non_zero_for_the_defective_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            code = run.main(
                ["--start", str(FIXTURES / "page-1.html"), "--out", tmp,
                 "--delay", "0", "--fail-on-dirty"]
            )
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
