#!/usr/bin/env python3
"""Builds QuoteTool.xlsx — the working quote generator, from catalog.json.

    python3 build_tool.py --out dist/QuoteTool.xlsx

The workbook is the deliverable: a salesperson picks a product and options from
dropdowns, types a quantity, and the quote prices itself. The pricing logic sits
on protected sheets so a stray paste cannot break it, and it computes exactly
what quotekit/pricing.py computes — the tests assert that on every catalogue row.

Rebuild it whenever catalog.json changes; nothing is hand-edited in the file.
"""

import argparse
from pathlib import Path

from quotekit.catalog import Catalog

MAX_LINES = 12
MAX_OPTIONS = 3
# Sheets are protected with a password only to stop accidental edits. It is not
# a security control — Excel sheet protection never was one — and it is written
# down here on purpose so whoever maintains the file can get in.
SHEET_PASSWORD = "quote"

NAVY = "0E2A47"
GREEN = "1DBF73"


def _require_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise SystemExit(
            "Building the workbook needs openpyxl:\n    pip install openpyxl"
        ) from exc
    return openpyxl


def build(catalog: Catalog, path) -> Path:
    openpyxl = _require_openpyxl()
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    workbook = openpyxl.Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor=NAVY)
    input_fill = PatternFill("solid", fgColor="FFF6E0")
    money = f'"{catalog.currency}" #,##0.00'

    def style_header(sheet, row=1, last_column=None):
        for cell in sheet[row]:
            if last_column and cell.column > last_column:
                continue
            if cell.value is not None:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")

    # ---------------------------------------------------------------- Catalog
    products = sheet_catalog = workbook.active
    sheet_catalog.title = "Catalog"
    sheet_catalog.append(["Code", "Name", "List price", "Cost", "Lead time (days)"])
    ordered = sorted(catalog.products.values(), key=lambda p: p.code)
    for product in ordered:
        sheet_catalog.append(
            [product.code, product.name, product.list_price, product.cost, product.lead_time_days]
        )
    product_last = len(ordered) + 1

    sheet_catalog["G1"] = "Key"
    sheet_catalog["H1"] = "Product"
    sheet_catalog["I1"] = "Option"
    sheet_catalog["J1"] = "Option name"
    sheet_catalog["K1"] = "Price"
    sheet_catalog["L1"] = "Cost"
    row = 1
    for product in ordered:
        for option in sorted(product.options.values(), key=lambda o: o.code):
            row += 1
            sheet_catalog.cell(row=row, column=7, value=f"{product.code}|{option.code}")
            sheet_catalog.cell(row=row, column=8, value=product.code)
            sheet_catalog.cell(row=row, column=9, value=option.code)
            sheet_catalog.cell(row=row, column=10, value=option.name)
            sheet_catalog.cell(row=row, column=11, value=option.price)
            sheet_catalog.cell(row=row, column=12, value=option.cost)
    option_last = row

    for column in ("C", "D", "K", "L"):
        for cell in sheet_catalog[column][1:]:
            cell.number_format = money
    style_header(sheet_catalog)
    for column, width in zip("ABCDEFGHIJKL", [12, 40, 14, 12, 16, 3, 18, 12, 10, 34, 12, 12]):
        sheet_catalog.column_dimensions[column].width = width

    # ------------------------------------------------------------------ Rules
    rules = workbook.create_sheet("Rules")
    rules["A1"] = "Quantity breaks"
    rules["A1"].font = Font(bold=True)
    rules["A2"], rules["B2"] = "Min qty", "Discount"
    for index, item in enumerate(catalog.quantity_breaks, start=3):
        rules.cell(row=index, column=1, value=item.min_quantity)
        cell = rules.cell(row=index, column=2, value=item.discount_percent / 100.0)
        cell.number_format = "0.00%"
    breaks_last = len(catalog.quantity_breaks) + 2

    rules["D1"] = "Customer tiers"
    rules["D1"].font = Font(bold=True)
    rules["D2"], rules["E2"] = "Tier", "Discount"
    tiers = sorted(catalog.customer_tiers.items())
    for index, (name, percent) in enumerate(tiers, start=3):
        rules.cell(row=index, column=4, value=name)
        cell = rules.cell(row=index, column=5, value=percent / 100.0)
        cell.number_format = "0.00%"
    tiers_last = len(tiers) + 2

    rules["G1"] = "Settings"
    rules["G1"].font = Font(bold=True)
    settings = [
        ("VAT", catalog.vat_percent / 100.0, "0.00%"),
        ("Margin floor", catalog.margin_floor_percent / 100.0, "0.00%"),
        ("Quote valid (days)", catalog.quote_valid_days, "0"),
        ("Currency", catalog.currency, "General"),
    ]
    for index, (label, value, fmt) in enumerate(settings, start=2):
        rules.cell(row=index, column=7, value=label)
        cell = rules.cell(row=index, column=8, value=value)
        cell.number_format = fmt
    vat_ref, floor_ref, valid_ref = "Rules!$H$2", "Rules!$H$3", "Rules!$H$4"

    for cell in (rules["A2"], rules["B2"], rules["D2"], rules["E2"]):
        cell.font = header_font
        cell.fill = header_fill
    for column, width in zip("ABCDEFGH", [12, 12, 3, 14, 12, 3, 20, 12]):
        rules.column_dimensions[column].width = width

    # ------------------------------------------------------------------ Quote
    quote = workbook.create_sheet("Quote", 0)
    quote["A1"] = "QUOTATION"
    quote["A1"].font = Font(bold=True, size=16, color="FFFFFF")
    quote["A1"].fill = header_fill
    quote.merge_cells("A1:K1")
    quote.row_dimensions[1].height = 26

    quote["A3"], quote["A4"], quote["A5"], quote["A6"] = (
        "Customer", "Customer tier", "Quote date", "Valid until"
    )
    for row_index in range(3, 7):
        quote.cell(row=row_index, column=1).font = Font(bold=True)
    quote["B3"] = "Type the customer name here"
    quote["B4"] = tiers[0][0]
    quote["B5"] = "=TODAY()"
    quote["B5"].number_format = "dd mmm yyyy"
    quote["B6"] = f"=B5+{valid_ref}"
    quote["B6"].number_format = "dd mmm yyyy"
    for ref in ("B3", "B4", "B5"):
        quote[ref].fill = input_fill

    head = 8
    headers = [
        "#", "Product", "Description", "Option 1", "Option 2", "Option 3",
        "Qty", "Unit price", "Discount", "Unit net", "Line total",
    ]
    for column, label in enumerate(headers, start=1):
        quote.cell(row=head, column=column, value=label)
    style_header(quote, head, last_column=len(headers))

    first_line, last_line = head + 1, head + MAX_LINES
    product_range = f"Catalog!$A$2:$A${product_last}"
    name_range = f"Catalog!$B$2:$B${product_last}"
    price_range = f"Catalog!$C$2:$C${product_last}"
    cost_range = f"Catalog!$D$2:$D${product_last}"
    key_range = f"Catalog!$G$2:$G${option_last}"
    opt_price_range = f"Catalog!$K$2:$K${option_last}"
    opt_cost_range = f"Catalog!$L$2:$L${option_last}"

    def option_lookup(row_index, value_range):
        """Sum the chosen options' price (or cost) for one line."""
        parts = []
        for column in ("D", "E", "F"):
            parts.append(
                f'IFERROR(INDEX({value_range},MATCH($B{row_index}&"|"&${column}{row_index},'
                f"{key_range},0)),0)"
            )
        return "+".join(parts)

    for offset in range(MAX_LINES):
        row_index = first_line + offset
        blank = f'$B{row_index}=""'

        quote.cell(row=row_index, column=1, value=offset + 1)
        for column in ("B", "D", "E", "F", "G"):
            quote[f"{column}{row_index}"].fill = input_fill

        quote.cell(
            row=row_index,
            column=3,
            value=f'=IF({blank},"",INDEX({name_range},MATCH($B{row_index},{product_range},0)))',
        )
        # Unit list price: product + every selected option.
        unit_list = (
            f"INDEX({price_range},MATCH($B{row_index},{product_range},0))"
            f"+{option_lookup(row_index, opt_price_range)}"
        )
        unit_cost = (
            f"INDEX({cost_range},MATCH($B{row_index},{product_range},0))"
            f"+{option_lookup(row_index, opt_cost_range)}"
        )
        quote.cell(row=row_index, column=8, value=f'=IF({blank},"",{unit_list})')

        # Discount: quantity break + customer tier, capped by the margin floor.
        qty_break = f"LOOKUP($G{row_index},Rules!$A$3:$A${breaks_last},Rules!$B$3:$B${breaks_last})"
        tier = f"INDEX(Rules!$E$3:$E${tiers_last},MATCH($B$4,Rules!$D$3:$D${tiers_last},0))"
        ceiling = f"MAX(0,1-({unit_cost})/(1-{floor_ref})/{unit_list})"
        quote.cell(
            row=row_index,
            column=9,
            value=f'=IF({blank},"",MIN({qty_break}+{tier},{ceiling}))',
        )
        quote.cell(
            row=row_index,
            column=10,
            value=f'=IF({blank},"",ROUND($H{row_index}*(1-$I{row_index}),2))',
        )
        quote.cell(
            row=row_index,
            column=11,
            value=f'=IF({blank},"",ROUND($J{row_index}*$G{row_index},2))',
        )
        # Internal margin column, kept off the printed area.
        quote.cell(
            row=row_index,
            column=13,
            value=f'=IF({blank},"",({unit_cost})*$G{row_index})',
        )

        for column in (8, 10, 11, 13):
            quote.cell(row=row_index, column=column).number_format = money
        quote.cell(row=row_index, column=9).number_format = "0.00%"

    totals_row = last_line + 2
    quote.cell(row=totals_row, column=10, value="Subtotal").font = Font(bold=True)
    quote.cell(row=totals_row, column=11, value=f"=ROUND(SUM(K{first_line}:K{last_line}),2)")
    quote.cell(row=totals_row + 1, column=10, value="VAT").font = Font(bold=True)
    quote.cell(row=totals_row + 1, column=11, value=f"=ROUND(K{totals_row}*{vat_ref},2)")
    quote.cell(row=totals_row + 2, column=10, value="TOTAL").font = Font(bold=True, color=NAVY)
    quote.cell(
        row=totals_row + 2, column=11, value=f"=ROUND(K{totals_row}+K{totals_row + 1},2)"
    ).font = Font(bold=True, color=NAVY)
    for offset in range(3):
        quote.cell(row=totals_row + offset, column=11).number_format = money
        quote.cell(row=totals_row + offset, column=10).alignment = Alignment(horizontal="right")

    quote.cell(row=totals_row, column=13, value="Quote cost")
    quote.cell(row=totals_row, column=14, value=f"=SUM(M{first_line}:M{last_line})")
    quote.cell(row=totals_row + 1, column=13, value="Quote margin")
    quote.cell(
        row=totals_row + 1,
        column=14,
        value=f'=IF(K{totals_row}=0,0,(K{totals_row}-N{totals_row})/K{totals_row})',
    ).number_format = "0.00%"
    quote.cell(row=totals_row, column=14).number_format = money

    note_row = totals_row + 4
    quote.cell(row=note_row, column=1, value="Shaded cells are yours to fill in.")
    quote.cell(
        row=note_row + 1,
        column=1,
        value="Pricing sits on the Catalog and Rules sheets, which are protected on purpose. "
              f"Unlock with the password '{SHEET_PASSWORD}' to change the price list.",
    )
    quote.cell(
        row=note_row + 2,
        column=1,
        value="Discounts stop at the margin floor. A line that hits the floor stops discounting "
              "rather than selling below it.",
    )

    # Dropdowns: every input that has a fixed set of valid answers gets one.
    product_validation = DataValidation(
        type="list", formula1=f"={product_range}", allow_blank=True, showErrorMessage=True
    )
    product_validation.error = "Pick a product code from the list."
    quote.add_data_validation(product_validation)
    product_validation.add(f"B{first_line}:B{last_line}")

    option_validation = DataValidation(
        type="list", formula1=f"=Catalog!$I$2:$I${option_last}", allow_blank=True,
        showErrorMessage=True,
    )
    option_validation.error = "Pick an option code, or leave the cell empty."
    quote.add_data_validation(option_validation)
    option_validation.add(f"D{first_line}:F{last_line}")

    tier_validation = DataValidation(
        type="list", formula1=f"=Rules!$D$3:$D${tiers_last}", allow_blank=False,
        showErrorMessage=True,
    )
    quote.add_data_validation(tier_validation)
    tier_validation.add("B4")

    qty_validation = DataValidation(
        type="whole", operator="greaterThanOrEqual", formula1="1", allow_blank=True,
        showErrorMessage=True,
    )
    qty_validation.error = "Quantity must be a whole number of 1 or more."
    quote.add_data_validation(qty_validation)
    qty_validation.add(f"G{first_line}:G{last_line}")

    for column, width in zip("ABCDEFGHIJKLMN", [5, 12, 40, 10, 10, 10, 7, 14, 10, 14, 16, 3, 14, 14]):
        quote.column_dimensions[column].width = width
    quote.column_dimensions["M"].hidden = True
    quote.column_dimensions["N"].hidden = True
    quote.freeze_panes = f"A{first_line}"
    quote.print_area = f"A1:K{note_row + 2}"
    quote.page_setup.orientation = "portrait"
    quote.page_setup.fitToWidth = 1
    quote.sheet_properties.pageSetUpPr.fitToPage = True

    # Protect the formulas, leave the input cells editable.
    from openpyxl.styles import Protection

    for row_cells in quote.iter_rows():
        for cell in row_cells:
            cell.protection = Protection(locked=True)
    for ref in ("B3", "B4", "B5"):
        quote[ref].protection = Protection(locked=False)
    for offset in range(MAX_LINES):
        row_index = first_line + offset
        for column in ("B", "D", "E", "F", "G"):
            quote[f"{column}{row_index}"].protection = Protection(locked=False)
    quote.protection.password = SHEET_PASSWORD
    quote.protection.enable()
    sheet_catalog.protection.password = SHEET_PASSWORD
    sheet_catalog.protection.enable()
    rules.protection.password = SHEET_PASSWORD
    rules.protection.enable()

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default=None, help="path to catalog.json")
    parser.add_argument("--out", default="dist/QuoteTool.xlsx")
    args = parser.parse_args(argv)

    catalog = Catalog.load(args.catalog)
    written = build(catalog, args.out)
    print(f"Built {written} from {len(catalog.products)} products")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
