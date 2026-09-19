"""HTML parsing built on html.parser, so there is no dependency to install.

The selectors live in one place (SELECTORS) because retargeting a scraper at a
new source is nearly always a selector change, not a logic change.
"""

import html
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Optional

from .models import Record

# class name on the source page -> field on the record
SELECTORS = {
    "record": "org",
    "fields": {
        "org-name": "name",
        "org-category": "category",
        "org-city": "city",
    },
    "website": "org-site",
    "email": "org-mail",
    "next_page": "next",
}

_WHITESPACE = re.compile(r"\s+")
_EMAIL_IN_HREF = re.compile(r"^mailto:(.+)$", re.IGNORECASE)


def _clean(value: str) -> str:
    return _WHITESPACE.sub(" ", html.unescape(value)).strip()


def _classes(attrs) -> set:
    for key, value in attrs:
        if key == "class" and value:
            return set(value.split())
    return set()


def _attr(attrs, name) -> str:
    for key, value in attrs:
        if key == name:
            return value or ""
    return ""


class _ListingParser(HTMLParser):
    """Collects one Record per element carrying the record class."""

    def __init__(self, source_url: str):
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.records: list = []
        self.next_page: Optional[str] = None
        self._depth = 0
        self._current: Optional[Record] = None
        self._capture_field: Optional[str] = None
        self._buffer: list = []

    def handle_starttag(self, tag, attrs):
        classes = _classes(attrs)

        if self._current is not None:
            self._depth += 1

        if SELECTORS["record"] in classes and self._current is None:
            self._current = Record(source_url=self.source_url)
            self._depth = 1
            return

        if SELECTORS["next_page"] in classes and tag == "a":
            href = _attr(attrs, "href")
            if href:
                self.next_page = urllib.parse.urljoin(self.source_url, href)

        if self._current is None:
            return

        for css_class, field_name in SELECTORS["fields"].items():
            if css_class in classes:
                self._capture_field = field_name
                self._buffer = []
                return

        href = _attr(attrs, "href")
        if SELECTORS["website"] in classes and href:
            self._current.website = urllib.parse.urljoin(self.source_url, href)
        elif SELECTORS["email"] in classes and href:
            match = _EMAIL_IN_HREF.match(href.strip())
            if match:
                self._current.email = _clean(match.group(1))

    def handle_data(self, data):
        if self._capture_field is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if self._current is None:
            return

        if self._capture_field is not None:
            setattr(self._current, self._capture_field, _clean("".join(self._buffer)))
            self._capture_field = None
            self._buffer = []

        self._depth -= 1
        if self._depth <= 0:
            self.records.append(self._current)
            self._current = None
            self._depth = 0


def parse_listing(body: str, source_url: str) -> list:
    """Return every record found on one listing page, each tagged with its URL."""
    parser = _ListingParser(source_url)
    parser.feed(body)
    parser.close()
    return parser.records


def parse_next_page(body: str, source_url: str) -> Optional[str]:
    """Return the absolute URL of the next listing page, or None on the last one."""
    parser = _ListingParser(source_url)
    parser.feed(body)
    parser.close()
    return parser.next_page
