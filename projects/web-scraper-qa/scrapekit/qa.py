"""The QA report: what was asked for, what came back, and what is missing.

Every delivery gets one of these. It is the difference between "here is a CSV"
and "here is a CSV and here is exactly how far you can trust it".
"""

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from .models import Record, DATASET_FIELDS

_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")
_URL_SHAPE = re.compile(r"^https?://[^\s/]+\.[^\s/]+", re.IGNORECASE)


def dedupe(records) -> tuple:
    """Split records into (kept, duplicates), first occurrence wins.

    Duplicates are returned rather than dropped silently so the report can say
    how many there were and which key collided.
    """
    seen = {}
    kept, duplicates = [], []
    for record in records:
        key = record.key()
        if not key.strip():
            kept.append(record)
            continue
        if key in seen:
            duplicates.append((key, record))
        else:
            seen[key] = record
            kept.append(record)
    return kept, duplicates


@dataclass
class QAReport:
    generated_at: str = ""
    expected_rows: Optional[int] = None
    pages_requested: int = 0
    pages_fetched: int = 0
    failed_pages: list = field(default_factory=list)
    rows_found: int = 0
    rows_delivered: int = 0
    duplicates_removed: int = 0
    duplicate_keys: list = field(default_factory=list)
    field_completeness: dict = field(default_factory=dict)
    rows_missing_required: list = field(default_factory=list)
    invalid_websites: list = field(default_factory=list)
    invalid_emails: list = field(default_factory=list)
    retries: int = 0

    @property
    def variance(self) -> Optional[int]:
        """Delivered rows minus expected rows, or None when no total was published."""
        if self.expected_rows is None:
            return None
        return self.rows_delivered - self.expected_rows

    @property
    def clean(self) -> bool:
        """True when nothing needs a human decision before delivery."""
        return (
            not self.failed_pages
            and not self.rows_missing_required
            and not self.invalid_websites
            and not self.invalid_emails
            and (self.variance in (None, 0))
        )

    def as_dict(self) -> dict:
        data = asdict(self)
        data["variance"] = self.variance
        data["clean"] = self.clean
        return data


def build_report(
    records,
    duplicates,
    pages_requested: int,
    pages_fetched: int,
    failed_pages=(),
    expected_rows: Optional[int] = None,
    retries: int = 0,
    now=None,
) -> QAReport:
    """Turn a finished crawl into the report that ships beside the data."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S UTC")
    report = QAReport(
        generated_at=stamp,
        expected_rows=expected_rows,
        pages_requested=pages_requested,
        pages_fetched=pages_fetched,
        failed_pages=[dict(url=u, reason=r) for u, r in failed_pages],
        rows_found=len(records) + len(duplicates),
        rows_delivered=len(records),
        duplicates_removed=len(duplicates),
        duplicate_keys=sorted({key for key, _ in duplicates}),
        retries=retries,
    )

    total = len(records) or 1
    for spec in DATASET_FIELDS:
        present = sum(1 for r in records if getattr(r, spec.name, ""))
        report.field_completeness[spec.name] = {
            "present": present,
            "missing": len(records) - present,
            "percent": round(present * 100.0 / total, 1),
            "required": spec.required,
        }

    for record in records:
        missing = record.missing_required()
        if missing:
            report.rows_missing_required.append(
                {"name": record.name or "(unnamed)", "missing": missing, "source_url": record.source_url}
            )
        if record.website and not _URL_SHAPE.match(record.website):
            report.invalid_websites.append({"name": record.name, "website": record.website})
        if record.email and not _EMAIL_SHAPE.match(record.email):
            report.invalid_emails.append({"name": record.name, "email": record.email})

    return report
