import unittest

from scrapekit.parser import parse_listing, parse_next_page

PAGE = """
<body data-total-results="2">
  <article class="org">
    <h2 class="org-name">Nile &amp; Delta Trust</h2>
    <p><span class="org-category">Environment</span> · <span class="org-city">Tanta</span></p>
    <a class="org-site" href="/about">Website</a>
    <a class="org-mail" href="mailto:info@example.org">Email</a>
  </article>
  <article class="org">
    <h2 class="org-name">  Spaced   Name  </h2>
    <p><span class="org-category">Health</span></p>
  </article>
  <a class="next" href="page-2.html">Next</a>
</body>
"""


class ParseListingTests(unittest.TestCase):
    def setUp(self):
        self.records = parse_listing(PAGE, "https://example.org/dir/page-1.html")

    def test_finds_every_record(self):
        self.assertEqual(len(self.records), 2)

    def test_unescapes_entities(self):
        self.assertEqual(self.records[0].name, "Nile & Delta Trust")

    def test_collapses_whitespace(self):
        self.assertEqual(self.records[1].name, "Spaced Name")

    def test_resolves_relative_website_against_the_page(self):
        self.assertEqual(self.records[0].website, "https://example.org/about")

    def test_extracts_email_from_mailto(self):
        self.assertEqual(self.records[0].email, "info@example.org")

    def test_tags_every_row_with_its_source_url(self):
        for record in self.records:
            self.assertEqual(record.source_url, "https://example.org/dir/page-1.html")

    def test_absent_fields_stay_empty_rather_than_guessed(self):
        self.assertEqual(self.records[1].city, "")
        self.assertEqual(self.records[1].website, "")


class PagerTests(unittest.TestCase):
    def test_next_page_is_absolute(self):
        self.assertEqual(
            parse_next_page(PAGE, "https://example.org/dir/page-1.html"),
            "https://example.org/dir/page-2.html",
        )

    def test_last_page_has_no_next(self):
        self.assertIsNone(parse_next_page("<body><article class='org'></article></body>", "https://x.org/"))


if __name__ == "__main__":
    unittest.main()
