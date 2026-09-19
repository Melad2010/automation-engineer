"""Walks a paginated listing and returns the records plus the crawl's QA report."""

import re
from dataclasses import dataclass, field
from typing import Optional

from .fetcher import Fetcher, FetchError
from .parser import parse_listing, parse_next_page
from .qa import build_report, dedupe

_DECLARED_TOTAL = re.compile(r"data-total-results=\"(\d+)\"")


@dataclass
class CrawlResult:
    records: list = field(default_factory=list)
    report: object = None


def crawl(start_url: str, fetcher: Optional[Fetcher] = None, max_pages: int = 50) -> CrawlResult:
    """Follow "next page" links from start_url until they run out.

    max_pages is a hard stop: a source with a circular pager should cost a
    bounded number of requests, not an afternoon.
    """
    fetcher = fetcher or Fetcher()
    url = start_url
    seen_urls = set()
    records, failed = [], []
    requested = fetched = 0
    expected_rows = None

    while url and len(seen_urls) < max_pages:
        if url in seen_urls:
            break
        seen_urls.add(url)
        requested += 1
        try:
            result = fetcher.get(url)
        except FetchError as exc:
            failed.append((url, exc.reason))
            break

        fetched += 1
        if expected_rows is None:
            declared = _DECLARED_TOTAL.search(result.body)
            if declared:
                expected_rows = int(declared.group(1))

        records.extend(parse_listing(result.body, url))
        url = parse_next_page(result.body, url)

    kept, duplicates = dedupe(records)
    retries = sum(1 for _ in fetcher.log)
    report = build_report(
        kept,
        duplicates,
        pages_requested=requested,
        pages_fetched=fetched,
        failed_pages=failed,
        expected_rows=expected_rows,
        retries=retries,
    )
    return CrawlResult(records=kept, report=report)
