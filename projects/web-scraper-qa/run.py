#!/usr/bin/env python3
"""Crawl a paginated listing and deliver CSV, JSON and a QA report.

    python3 run.py --start fixtures/page-1.html --out out/

The bundled fixtures run offline, so the demo works with no network and no
third-party packages installed.
"""

import argparse
import sys
from pathlib import Path

from scrapekit import Fetcher, write_csv, write_json, write_report
from scrapekit.crawl import crawl
from scrapekit.export import render_report


def _as_url(target: str) -> str:
    if target.startswith(("http://", "https://", "file://")):
        return target
    return Path(target).resolve().as_uri()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="fixtures/page-1.html", help="first listing page")
    parser.add_argument("--out", default="out", help="output directory")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument(
        "--fail-on-dirty",
        action="store_true",
        help="exit non-zero when the QA report is not clean (useful in CI)",
    )
    args = parser.parse_args(argv)

    start = _as_url(args.start)
    # Local fixtures need no politeness delay; live sources do.
    delay = 0.0 if start.startswith("file://") else args.delay

    result = crawl(start, fetcher=Fetcher(delay=delay), max_pages=args.max_pages)

    out = Path(args.out)
    write_csv(result.records, out / "dataset.csv")
    write_json(result.records, out / "dataset.json")
    write_report(result.report, out / "qa-report.md")

    print(render_report(result.report))
    print(f"Wrote {len(result.records)} rows to {out}/dataset.csv")

    if args.fail_on_dirty and not result.report.clean:
        print("QA report is not clean — review before delivery.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
