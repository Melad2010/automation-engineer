#!/usr/bin/env python3
"""Turn a sales CSV into an Excel KPI dashboard.

    python3 make_sample_data.py           # writes sample-sales.csv
    python3 build.py --csv sample-sales.csv --out dist/dashboard.xlsx

    python3 build.py --csv sample-sales.csv --summary    # numbers, no Excel needed

Refreshing next month is: paste the new rows under the Data sheet, pick the
month on the Dashboard. Every KPI and chart is a formula, so nothing is rebuilt
by hand.
"""

import argparse
import json
import sys
from pathlib import Path

from dashkit import load_csv, summarise, by_month, by_dimension, top_n
from dashkit.model import RowError


def print_summary(dataset, month=None) -> None:
    report = dataset.report
    print(f"Loaded {report.rows_accepted} of {report.rows_read} rows from {report.path}")
    if report.rejected:
        print(f"\n{report.rows_rejected} row(s) quarantined — not in the dashboard:")
        for bad in report.rejected:
            print(f"  line {bad['line']}: {bad['reason']}")

    months = dataset.months
    target = month or (months[-1] if months else None)
    if target is None:
        print("\nNo usable rows.")
        return

    print(f"\nKPIs for {target}"
          f"{' (vs. ' + months[months.index(target) - 1] + ')' if months.index(target) else ''}")
    for kpi in summarise(dataset.sales, target):
        change = "" if kpi.delta_percent is None else f"{kpi.delta_percent:+.1f}%"
        print(f"  {kpi.label:<20}{kpi.value:>14,.2f}  {change:>9}")

    print("\nRevenue by month")
    trend = by_month(dataset.sales)
    for label, value in trend.as_pairs():
        bar = "#" * max(1, int(value / max(trend.values) * 40)) if max(trend.values) else ""
        print(f"  {label}  {value:>14,.0f}  {bar}")

    print("\nRevenue by region")
    for label, value in by_dimension(dataset.sales, "region").as_pairs():
        print(f"  {label:<16}{value:>14,.0f}")

    print("\nTop products")
    for label, value in top_n(dataset.sales, "product", count=5).as_pairs():
        print(f"  {label:<20}{value:>14,.0f}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default="sample-sales.csv")
    parser.add_argument("--out", default="dist/dashboard.xlsx")
    parser.add_argument("--month", help="KPI month, e.g. 2026-09 (default: the latest)")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--summary", action="store_true",
                        help="print the numbers instead of writing a workbook")
    parser.add_argument("--json", action="store_true", help="print the load report as JSON")
    parser.add_argument("--strict", action="store_true",
                        help="stop at the first unparseable row instead of quarantining it")
    args = parser.parse_args(argv)

    try:
        dataset = load_csv(args.csv, strict=args.strict)
    except (RowError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not dataset.sales:
        print("error: no usable rows — see the load report above", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(dataset.report.as_dict(), indent=2, default=str))
        return 0

    print_summary(dataset, args.month)

    if not args.summary:
        from dashkit.workbook import build

        layout = build(dataset, args.out, currency=args.currency)
        print(f"\nWrote {Path(args.out)} — "
              f"{len(dataset.sales)} rows, {len(layout.months)} months, 3 charts")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
