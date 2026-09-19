"""Source-tracked scraping toolkit: fetch, parse, QA, export.

Standard library only, so the demo runs anywhere Python 3.9+ is installed.
"""

from .models import Record, FieldSpec, DATASET_FIELDS
from .fetcher import Fetcher, FetchError, FetchResult
from .parser import parse_listing, parse_next_page
from .qa import QAReport, build_report, dedupe
from .export import write_csv, write_json, write_report

__all__ = [
    "Record",
    "FieldSpec",
    "DATASET_FIELDS",
    "Fetcher",
    "FetchError",
    "FetchResult",
    "parse_listing",
    "parse_next_page",
    "QAReport",
    "build_report",
    "dedupe",
    "write_csv",
    "write_json",
    "write_report",
]
