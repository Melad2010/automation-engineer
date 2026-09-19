"""Builds the dashboard workbook.

The rule the whole file follows: the dashboard reads the data, it does not store
it. Every KPI and every chart point is a formula over the Data sheet, so pasting
next month's rows and pressing the month dropdown is the entire refresh. Nothing
here writes a computed number as a literal — that is what "a clean data model,
not pasted values" has to mean if it means anything.
"""

from dataclasses import dataclass
from pathlib import Path

# Rows are reserved past the end of the data so appended rows are picked up by
# the existing formulas without anyone editing a range.
SPARE_ROWS = 2000

NAVY = "0E2A47"
GREEN = "1DBF73"
AMBER = "F5A623"
RED = "C0392B"
LIGHT = "F5F8FB"
LINE = "E3E9F0"

DATA_COLUMNS = [
    ("Date", 12, "dd mmm yyyy"),
    ("Month", 10, "@"),
    ("Region", 14, None),
    ("Product", 20, None),
    ("Channel", 13, None),
    ("Units", 8, "#,##0"),
    ("Unit price", 12, "#,##0.00"),
    ("Unit cost", 12, "#,##0.00"),
    ("Revenue", 14, "#,##0.00"),
    ("Cost", 14, "#,##0.00"),
    ("Margin", 14, "#,##0.00"),
]


def _require_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise SystemExit(
            "Building the dashboard needs openpyxl:\n    pip install openpyxl"
        ) from exc
    return openpyxl


@dataclass
class Layout:
    """Where everything landed, so the tests can find it without guessing."""

    data_first: int
    data_last: int
    data_limit: int
    months: list
    summary_last: int
    regions: list
    region_last: int
    products: list
    product_last: int


def build(dataset, path, currency: str = "USD") -> Path:
    openpyxl = _require_openpyxl()
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    money = f'"{currency}" #,##0'
    money_exact = f'"{currency}" #,##0.00'
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor=NAVY)
    thin = Side(style="thin", color=LINE)

    workbook = openpyxl.Workbook()

    # ------------------------------------------------------------------- Data
    data = workbook.active
    data.title = "Data"
    for index, (label, width, _) in enumerate(DATA_COLUMNS, start=1):
        cell = data.cell(row=1, column=index, value=label)
        cell.font = header_font
        cell.fill = header_fill
        data.column_dimensions[get_column_letter(index)].width = width

    first = 2
    for offset, sale in enumerate(sorted(dataset.sales, key=lambda s: (s.date, s.region))):
        row = first + offset
        data.cell(row=row, column=1, value=sale.date).number_format = "dd mmm yyyy"
        data.cell(row=row, column=2, value=sale.month)
        data.cell(row=row, column=3, value=sale.region)
        data.cell(row=row, column=4, value=sale.product)
        data.cell(row=row, column=5, value=sale.channel)
        data.cell(row=row, column=6, value=sale.units).number_format = "#,##0"
        data.cell(row=row, column=7, value=sale.unit_price).number_format = "#,##0.00"
        data.cell(row=row, column=8, value=sale.unit_cost).number_format = "#,##0.00"
        # Revenue, cost and margin are formulas: correct a unit price and every
        # number downstream of it moves.
        data.cell(row=row, column=9, value=f"=ROUND(F{row}*G{row},2)").number_format = money_exact
        data.cell(row=row, column=10, value=f"=ROUND(F{row}*H{row},2)").number_format = money_exact
        data.cell(row=row, column=11, value=f"=I{row}-J{row}").number_format = money_exact

    last = first + len(dataset.sales) - 1
    limit = last + SPARE_ROWS
    data.freeze_panes = "A2"
    data.auto_filter.ref = f"A1:K{max(last, first)}"

    # --------------------------------------------------------------- Rejected
    rejected = workbook.create_sheet("Rejected rows")
    rejected["A1"] = "Rows the loader refused, and why"
    rejected["A1"].font = Font(bold=True, size=13)
    rejected["A2"] = (
        "These never reach the dashboard. A row that cannot be parsed is quarantined "
        "here with its line number — it is not coerced to zero and not silently dropped."
    )
    for index, label in enumerate(["Line", "Reason", "Row as it appeared"], start=1):
        cell = rejected.cell(row=4, column=index, value=label)
        cell.font = header_font
        cell.fill = header_fill
    for offset, bad in enumerate(dataset.report.rejected, start=5):
        rejected.cell(row=offset, column=1, value=bad["line"])
        rejected.cell(row=offset, column=2, value=bad["reason"])
        rejected.cell(row=offset, column=3, value=", ".join(
            f"{key}={value}" for key, value in bad["row"].items() if value
        ))
    if not dataset.report.rejected:
        rejected.cell(row=5, column=1, value="None — every row parsed.")
    for column, width in zip("ABC", [8, 56, 80]):
        rejected.column_dimensions[column].width = width

    # ---------------------------------------------------------------- Summary
    summary = workbook.create_sheet("Summary")
    months = sorted({sale.month for sale in dataset.sales})
    regions = sorted({sale.region for sale in dataset.sales})
    products = sorted({sale.product for sale in dataset.sales})

    month_range = f"Data!$B$2:$B${limit}"
    region_range = f"Data!$C$2:$C${limit}"
    product_range = f"Data!$D$2:$D${limit}"
    revenue_range = f"Data!$I$2:$I${limit}"
    cost_range = f"Data!$J$2:$J${limit}"
    margin_range = f"Data!$K$2:$K${limit}"
    units_range = f"Data!$F$2:$F${limit}"

    headers = ["Month", "Revenue", "Cost", "Margin", "Margin %", "Units", "Orders", "Avg order"]
    for index, label in enumerate(headers, start=1):
        cell = summary.cell(row=1, column=index, value=label)
        cell.font = header_font
        cell.fill = header_fill
    for offset, month in enumerate(months, start=2):
        summary.cell(row=offset, column=1, value=month)
        summary.cell(row=offset, column=2,
                     value=f"=SUMIFS({revenue_range},{month_range},$A{offset})")
        summary.cell(row=offset, column=3,
                     value=f"=SUMIFS({cost_range},{month_range},$A{offset})")
        summary.cell(row=offset, column=4, value=f"=B{offset}-C{offset}")
        summary.cell(row=offset, column=5,
                     value=f"=IF($B{offset}=0,0,$D{offset}/$B{offset})")
        summary.cell(row=offset, column=6,
                     value=f"=SUMIFS({units_range},{month_range},$A{offset})")
        summary.cell(row=offset, column=7,
                     value=f"=COUNTIFS({month_range},$A{offset})")
        summary.cell(row=offset, column=8,
                     value=f"=IF($G{offset}=0,0,ROUND($B{offset}/$G{offset},2))")
        for column in (2, 3, 4, 8):
            summary.cell(row=offset, column=column).number_format = money_exact
        summary.cell(row=offset, column=5).number_format = "0.0%"
        summary.cell(row=offset, column=6).number_format = "#,##0"
    summary_last = len(months) + 1

    def block(start_column: int, title: str, keys, key_range: str):
        for index, label in enumerate([title, "Revenue", "Margin"], start=start_column):
            cell = summary.cell(row=1, column=index, value=label)
            cell.font = header_font
            cell.fill = header_fill
        letter = get_column_letter(start_column)
        for offset, key in enumerate(keys, start=2):
            summary.cell(row=offset, column=start_column, value=key)
            summary.cell(
                row=offset, column=start_column + 1,
                value=f"=SUMIFS({revenue_range},{key_range},${letter}{offset})",
            ).number_format = money_exact
            summary.cell(
                row=offset, column=start_column + 2,
                value=f"=SUMIFS({margin_range},{key_range},${letter}{offset})",
            ).number_format = money_exact
        return len(keys) + 1

    region_last = block(10, "Region", regions, region_range)      # J, K, L
    product_last = block(14, "Product", products, product_range)  # N, O, P

    for column, width in zip("ABCDEFGHIJKLMNOP",
                             [10, 15, 15, 15, 10, 10, 9, 14, 3, 14, 15, 15, 3, 20, 15, 15]):
        summary.column_dimensions[column].width = width
    summary.freeze_panes = "A2"

    # -------------------------------------------------------------- Dashboard
    board = workbook.create_sheet("Dashboard", 0)
    board.sheet_view.showGridLines = False
    board["A1"] = "Sales performance"
    board["A1"].font = Font(bold=True, size=20, color=NAVY)
    board["A2"] = "Every figure is a formula over the Data sheet. Paste new rows and pick a month."
    board["A2"].font = Font(size=10, color="606E80")

    board["A4"] = "Month"
    board["A4"].font = Font(bold=True)
    board["B4"] = months[-1] if months else ""
    board["B4"].fill = PatternFill("solid", fgColor="FFF6E0")
    board["B4"].font = Font(bold=True, size=12)
    board["B4"].alignment = Alignment(horizontal="center")

    month_lookup = f"Summary!$A$2:$A${summary_last}"

    def card_formula(column_letter: str, offset: int = 0) -> str:
        """Pull one Summary column for the selected month (offset -1 = previous)."""
        shift = f"{offset:+d}" if offset else ""
        return (
            f"IFERROR(INDEX(Summary!${column_letter}$2:${column_letter}${summary_last},"
            f"MATCH($B$4,{month_lookup},0){shift}),\"\")"
        )

    cards = [
        ("Revenue", "B", money),
        ("Margin", "D", money),
        ("Margin %", "E", "0.0%"),
        ("Units", "F", "#,##0"),
        ("Orders", "G", "#,##0"),
        ("Avg order", "H", money),
    ]
    card_row, value_row, delta_row = 6, 7, 8
    for index, (label, column_letter, number_format) in enumerate(cards):
        column = 1 + index * 2
        letter = get_column_letter(column)

        title = board.cell(row=card_row, column=column, value=label)
        title.font = Font(bold=True, size=10, color="FFFFFF")
        title.fill = header_fill
        title.alignment = Alignment(horizontal="center")
        board.merge_cells(start_row=card_row, start_column=column,
                          end_row=card_row, end_column=column + 1)

        value = board.cell(row=value_row, column=column, value=f"={card_formula(column_letter)}")
        value.font = Font(bold=True, size=15, color=NAVY)
        value.number_format = number_format
        value.alignment = Alignment(horizontal="center")
        value.border = Border(left=Side(style="thin", color=LINE),
                              right=Side(style="thin", color=LINE))
        board.merge_cells(start_row=value_row, start_column=column,
                          end_row=value_row, end_column=column + 1)

        # Change against the previous month. A previous month of zero, or no
        # previous month at all, shows nothing rather than a fake percentage.
        previous = card_formula(column_letter, -1)
        delta = board.cell(
            row=delta_row,
            column=column,
            value=(
                f'=IF(OR({previous}="",{previous}=0),"",'
                f"({card_formula(column_letter)}-{previous})/ABS({previous}))"
            ),
        )
        delta.number_format = '[Color10]+0.0%;[Red]-0.0%;0.0%'
        delta.font = Font(size=10)
        delta.alignment = Alignment(horizontal="center")
        board.merge_cells(start_row=delta_row, start_column=column,
                          end_row=delta_row, end_column=column + 1)

        board.column_dimensions[letter].width = 13
        board.column_dimensions[get_column_letter(column + 1)].width = 6

    board.cell(row=delta_row + 1, column=1,
               value="Change vs. the previous month. Blank where there is no previous month.")
    board.cell(row=delta_row + 1, column=1).font = Font(size=9, italic=True, color="606E80")

    month_picker = DataValidation(
        type="list", formula1=f"={month_lookup}", allow_blank=False, showErrorMessage=True
    )
    month_picker.error = "Pick a month that exists in the data."
    board.add_data_validation(month_picker)
    month_picker.add("B4")

    # ----------------------------------------------------------------- Charts
    trend = LineChart()
    trend.title = "Revenue and margin by month"
    trend.height, trend.width = 8, 20
    trend.y_axis.numFmt = "#,##0"
    trend.add_data(Reference(summary, min_col=2, max_col=2, min_row=1, max_row=summary_last),
                   titles_from_data=True)
    trend.add_data(Reference(summary, min_col=4, max_col=4, min_row=1, max_row=summary_last),
                   titles_from_data=True)
    trend.set_categories(Reference(summary, min_col=1, min_row=2, max_row=summary_last))
    board.add_chart(trend, "A11")

    region_chart = BarChart()
    region_chart.type = "col"
    region_chart.title = "Revenue by region"
    region_chart.height, region_chart.width = 8, 10
    region_chart.legend = None
    region_chart.add_data(
        Reference(summary, min_col=11, min_row=1, max_row=region_last), titles_from_data=True
    )
    region_chart.set_categories(Reference(summary, min_col=10, min_row=2, max_row=region_last))
    board.add_chart(region_chart, "A28")

    product_chart = PieChart()
    product_chart.title = "Revenue share by product"
    product_chart.height, product_chart.width = 8, 10
    product_chart.add_data(
        Reference(summary, min_col=15, min_row=1, max_row=product_last), titles_from_data=True
    )
    product_chart.set_categories(Reference(summary, min_col=14, min_row=2, max_row=product_last))
    board.add_chart(product_chart, "H28")

    board.print_area = "A1:L45"
    board.page_setup.orientation = "landscape"
    board.page_setup.fitToWidth = 1
    board.sheet_properties.pageSetUpPr.fitToPage = True

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)

    return Layout(
        data_first=first,
        data_last=last,
        data_limit=limit,
        months=months,
        summary_last=summary_last,
        regions=regions,
        region_last=region_last,
        products=products,
        product_last=product_last,
    )
