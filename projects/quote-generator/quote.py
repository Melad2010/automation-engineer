#!/usr/bin/env python3
"""Price a quote from the command line, or from a JSON request file.

    python3 quote.py --demo
    python3 quote.py --customer "Acme Industrial" --tier partner \
        --line PMP-100:6:STN,VFD --line SRV-INS:1 --xlsx dist/quote.xlsx
    python3 quote.py --request request.json --json

A line is PRODUCT:QUANTITY[:OPTION,OPTION][:MANUAL_DISCOUNT_PERCENT].
"""

import argparse
import json
import sys
from pathlib import Path

from quotekit import Catalog, LineRequest, PricingError, price_quote
from quotekit.catalog import CatalogError
from quotekit.documents import render_text, write_quote_xlsx

DEMO = {
    "customer": "Acme Industrial",
    "tier": "partner",
    "lines": [
        {"product": "CMP-220", "quantity": 3, "options": ["DRY", "REM"]},
        {"product": "PNL-040", "quantity": 3, "options": ["HMI"]},
        {"product": "SRV-INS", "quantity": 1, "options": ["TRN"], "manual_discount_percent": 40},
    ],
}


def parse_line(text: str) -> LineRequest:
    parts = text.split(":")
    if not parts[0]:
        raise PricingError(f"Bad line {text!r}: expected PRODUCT:QUANTITY[:OPTIONS][:DISCOUNT]")
    product = parts[0]
    quantity = int(parts[1]) if len(parts) > 1 and parts[1] else 1
    options = [code for code in parts[2].split(",") if code] if len(parts) > 2 else []
    discount = float(parts[3]) if len(parts) > 3 and parts[3] else 0.0
    return LineRequest(product, quantity, options, discount)


def requests_from(payload: dict):
    return [
        LineRequest(
            entry["product"],
            int(entry.get("quantity", 1)),
            list(entry.get("options", [])),
            float(entry.get("manual_discount_percent", 0.0)),
        )
        for entry in payload["lines"]
    ]


def quote_as_dict(quote) -> dict:
    return {
        "reference": quote.reference,
        "customer": quote.customer,
        "tier": quote.tier,
        "currency": quote.currency,
        "quote_date": quote.quote_date.isoformat(),
        "valid_until": quote.valid_until.isoformat(),
        "lead_time_days": quote.lead_time_days,
        "lines": [
            {
                "product_code": line.product_code,
                "description": line.description,
                "quantity": line.quantity,
                "options": list(line.options),
                "unit_list_price": line.unit_list_price,
                "discount_percent": round(line.applied_discount_percent, 4),
                "unit_net_price": line.unit_net_price,
                "line_total": line.line_total,
                "margin_percent": line.margin_percent,
                "notes": list(line.notes),
            }
            for line in quote.lines
        ],
        "subtotal": quote.subtotal,
        "vat_percent": quote.vat_percent,
        "vat_amount": quote.vat_amount,
        "total": quote.total,
        "margin_percent": quote.margin_percent,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", default=None)
    parser.add_argument("--customer", default="")
    parser.add_argument("--tier", default="standard")
    parser.add_argument("--line", action="append", default=[], metavar="PRODUCT:QTY[:OPTS][:DISC]")
    parser.add_argument("--request", help="JSON file with customer, tier and lines")
    parser.add_argument("--demo", action="store_true", help="price the bundled example")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--xlsx", help="also write the quote as an .xlsx file")
    args = parser.parse_args(argv)

    catalog = Catalog.load(args.catalog)

    if args.demo:
        payload = DEMO
    elif args.request:
        payload = json.loads(Path(args.request).read_text(encoding="utf-8"))
    elif args.line:
        payload = {"customer": args.customer or "Customer", "tier": args.tier,
                   "lines": []}
    else:
        parser.error("give --demo, --request, or at least one --line")

    try:
        if args.line and not args.demo and not args.request:
            requests = [parse_line(text) for text in args.line]
        else:
            requests = requests_from(payload)
        quote = price_quote(
            catalog,
            requests,
            payload.get("customer", args.customer) or "Customer",
            payload.get("tier", args.tier),
        )
    except (PricingError, CatalogError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(quote_as_dict(quote), indent=2))
    else:
        print(render_text(quote))

    if args.xlsx:
        print(f"\nWrote {write_quote_xlsx(quote, args.xlsx)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
