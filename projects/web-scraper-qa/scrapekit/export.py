"""Delivery formats: CSV and JSON for the data, Markdown for the QA report."""

import csv
import json
from dataclasses import asdict
from pathlib import Path

from .models import DATASET_FIELDS

COLUMNS = [spec.name for spec in DATASET_FIELDS] + ["notes"]


def write_csv(records, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record.as_row())
    return path


def write_json(records, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{k: v for k, v in asdict(r).items()} for r in records]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _table(rows, headers) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_report(report) -> str:
    """Render the QA report as Markdown, the version a client actually reads."""
    verdict = "clean" if report.clean else "needs a look before delivery"
    lines = [
        "# QA report",
        "",
        f"Generated: {report.generated_at}",
        f"Verdict: **{verdict}**",
        "",
        "## Coverage",
        "",
        _table(
            [
                ("Pages requested", report.pages_requested),
                ("Pages fetched", report.pages_fetched),
                ("Pages failed", len(report.failed_pages)),
                ("Retries spent", report.retries),
                ("Rows found", report.rows_found),
                ("Duplicates removed", report.duplicates_removed),
                ("Rows delivered", report.rows_delivered),
                ("Rows expected", "not published" if report.expected_rows is None else report.expected_rows),
                ("Variance", "n/a" if report.variance is None else f"{report.variance:+d}"),
            ],
            ["Check", "Value"],
        ),
        "",
        "## Field completeness",
        "",
        _table(
            [
                (
                    name,
                    "yes" if stats["required"] else "no",
                    stats["present"],
                    stats["missing"],
                    f"{stats['percent']}%",
                )
                for name, stats in report.field_completeness.items()
            ],
            ["Field", "Required", "Present", "Missing", "Complete"],
        ),
        "",
    ]

    if report.failed_pages:
        lines += ["## Pages that could not be read", ""]
        lines += [f"- {page['url']} — {page['reason']}" for page in report.failed_pages]
        lines.append("")

    if report.duplicate_keys:
        lines += ["## Duplicate keys removed", ""]
        lines += [f"- {key}" for key in report.duplicate_keys]
        lines.append("")

    if report.rows_missing_required:
        lines += ["## Rows missing a required field", ""]
        lines += [
            f"- {row['name']} — missing {', '.join(row['missing'])} ({row['source_url']})"
            for row in report.rows_missing_required
        ]
        lines.append("")

    if report.invalid_websites or report.invalid_emails:
        lines += ["## Values that failed a shape check", ""]
        lines += [f"- website: {row['name']} — {row['website']}" for row in report.invalid_websites]
        lines += [f"- email: {row['name']} — {row['email']}" for row in report.invalid_emails]
        lines.append("")

    lines += [
        "## What this report does not claim",
        "",
        "- Gaps are reported, never filled with a guess.",
        "- Shape checks confirm a value looks like a URL or an email; they do not visit it.",
        "- Rows are de-duplicated on name plus city; two genuinely distinct",
        "  organisations sharing both will collide, and the key is listed above",
        "  so you can overrule the decision.",
        "",
    ]
    return "\n".join(lines)


def write_report(report, path) -> Path:
    """Write both the Markdown report and a machine-readable JSON sibling."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(report), encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(report.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path
