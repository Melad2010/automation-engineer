"""Turning a priced Quote into something a customer receives.

`render_text` needs nothing installed. `write_quote_xlsx` needs openpyxl and
says so plainly if it is missing, rather than failing on an import line.
"""

from pathlib import Path

INTERNAL_NOTE = "Internal columns (cost, margin) live on a separate sheet, not on the customer copy."


def _money(value: float, currency: str) -> str:
    return f"{currency} {value:,.2f}"


def render_text(quote) -> str:
    """The plain-text quote — also what gets pasted into an email body."""
    width = 78
    lines = [
        "=" * width,
        f"QUOTATION {quote.reference}",
        "=" * width,
        f"Customer      : {quote.customer}  ({quote.tier})",
        f"Date          : {quote.quote_date:%d %b %Y}",
        f"Valid until   : {quote.valid_until:%d %b %Y}",
        f"Lead time     : {quote.lead_time_days} days from order",
        "-" * width,
    ]

    for index, line in enumerate(quote.lines, start=1):
        lines.append(f"{index}. {line.description}  [{line.product_code}]")
        lines.append(
            f"   {line.quantity} x {_money(line.unit_list_price, quote.currency)}"
            f"  less {line.applied_discount_percent:.2f}%"
            f"  = {_money(line.line_total, quote.currency)}"
        )
        for note in line.notes:
            lines.append(f"   note: {note}")

    lines += [
        "-" * width,
        f"{'Subtotal':<22}{_money(quote.subtotal, quote.currency):>20}",
        f"{'VAT @ ' + format(quote.vat_percent, '.1f') + '%':<22}"
        f"{_money(quote.vat_amount, quote.currency):>20}",
        f"{'TOTAL':<22}{_money(quote.total, quote.currency):>20}",
        "=" * width,
    ]
    return "\n".join(lines)


def _require_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise SystemExit(
            "This step writes an .xlsx file and needs openpyxl:\n"
            "    pip install openpyxl\n"
            "Everything else in this project runs on the standard library."
        ) from exc
    return openpyxl


def write_quote_xlsx(quote, path) -> Path:
    """Write the customer quote plus an internal margin sheet."""
    openpyxl = _require_openpyxl()
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    navy = "0E2A47"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Quote"

    title = Font(bold=True, size=16, color="FFFFFF")
    header = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor=navy)
    thin = Side(style="thin", color="D5DEE8")
    money = f'"{quote.currency}" #,##0.00'

    sheet["A1"] = f"QUOTATION {quote.reference}"
    sheet["A1"].font = title
    sheet["A1"].fill = fill
    sheet.merge_cells("A1:F1")
    sheet.row_dimensions[1].height = 26

    meta = [
        ("Customer", f"{quote.customer} ({quote.tier})"),
        ("Date", quote.quote_date.strftime("%d %b %Y")),
        ("Valid until", quote.valid_until.strftime("%d %b %Y")),
        ("Lead time", f"{quote.lead_time_days} days from order"),
    ]
    for offset, (label, value) in enumerate(meta, start=3):
        sheet.cell(row=offset, column=1, value=label).font = Font(bold=True)
        sheet.cell(row=offset, column=2, value=value)

    head_row = 8
    headers = ["#", "Description", "Code", "Qty", "Unit price", "Discount", "Line total"]
    for column, label in enumerate(headers, start=1):
        cell = sheet.cell(row=head_row, column=column, value=label)
        cell.font = header
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")

    row = head_row
    for index, line in enumerate(quote.lines, start=1):
        row += 1
        values = [
            index,
            line.description,
            line.product_code,
            line.quantity,
            line.unit_list_price,
            line.applied_discount_percent / 100.0,
            line.line_total,
        ]
        for column, value in enumerate(values, start=1):
            cell = sheet.cell(row=row, column=column, value=value)
            cell.border = Border(bottom=thin)
            if column in (5, 7):
                cell.number_format = money
            if column == 6:
                cell.number_format = "0.00%"

    totals = [
        ("Subtotal", quote.subtotal),
        (f"VAT @ {quote.vat_percent:.1f}%", quote.vat_amount),
        ("TOTAL", quote.total),
    ]
    for label, value in totals:
        row += 1
        label_cell = sheet.cell(row=row, column=6, value=label)
        label_cell.font = Font(bold=True)
        label_cell.alignment = Alignment(horizontal="right")
        amount = sheet.cell(row=row, column=7, value=value)
        amount.number_format = money
        amount.font = Font(bold=True)

    notes = [note for line in quote.lines for note in line.notes]
    if notes:
        row += 2
        sheet.cell(row=row, column=1, value="Notes").font = Font(bold=True)
        for note in notes:
            row += 1
            sheet.cell(row=row, column=1, value=note)

    for column, width in enumerate([5, 46, 12, 8, 14, 11, 16], start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width

    internal = workbook.create_sheet("Internal")
    internal.append(["Code", "Qty", "Unit cost", "Unit net", "Line cost", "Line total", "Margin %"])
    for cell in internal[1]:
        cell.font = header
        cell.fill = fill
    for line in quote.lines:
        internal.append(
            [
                line.product_code,
                line.quantity,
                line.unit_cost,
                line.unit_net_price,
                round(line.unit_cost * line.quantity, 2),
                line.line_total,
                line.margin_percent / 100.0,
            ]
        )
    internal.append([])
    internal.append(["Quote margin", "", "", "", quote.total_cost, quote.subtotal,
                     quote.margin_percent / 100.0])
    for row_cells in internal.iter_rows(min_row=2, min_col=3):
        for cell in row_cells:
            cell.number_format = "0.00%" if cell.column == 7 else money
    internal["A12"] = INTERNAL_NOTE
    for column, width in enumerate([12, 8, 14, 14, 14, 14, 11], start=1):
        internal.column_dimensions[get_column_letter(column)].width = width

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path
