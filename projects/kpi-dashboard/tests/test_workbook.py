"""Executes the dashboard's own formulas and compares them with dashkit.

Same reasoning as the quote generator: the workbook is the deliverable, so its
formulas get run, not eyeballed. The evaluator is projects/_shared/xlformula.py.
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

try:
    import openpyxl
except ImportError:  # pragma: no cover - the suite skips rather than fails
    openpyxl = None

from dashkit import load_csv, summarise
from dashkit.metrics import by_dimension, by_month
from dashkit.model import DataSet, Sale

if openpyxl is not None:
    from dashkit.workbook import build
    from tests.shared import Evaluator

SAMPLE = Path(__file__).resolve().parent.parent / "sample-sales.csv"


@unittest.skipIf(openpyxl is None, "openpyxl is not installed")
class DashboardTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_csv(SAMPLE)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls._tmp.name) / "dashboard.xlsx"
        cls.layout = build(cls.dataset, cls.path)
        cls.workbook = openpyxl.load_workbook(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def evaluator(self, sheet="Dashboard"):
        return Evaluator(openpyxl.load_workbook(self.path), sheet)

    def value(self, sheet, ref, workbook=None):
        book = workbook or self.workbook
        return Evaluator(book, sheet).evaluate(book[sheet][ref].value, sheet)


class StructureTests(DashboardTestCase):
    def test_every_expected_sheet_exists(self):
        self.assertEqual(
            self.workbook.sheetnames, ["Dashboard", "Data", "Rejected rows", "Summary"]
        )

    def test_data_sheet_holds_every_accepted_row(self):
        sheet = self.workbook["Data"]
        self.assertEqual(self.layout.data_last - self.layout.data_first + 1,
                         len(self.dataset.sales))
        self.assertEqual(sheet["A1"].value, "Date")

    def test_revenue_cost_and_margin_are_formulas_not_pasted_values(self):
        sheet = self.workbook["Data"]
        for column in ("I", "J", "K"):
            self.assertTrue(
                str(sheet[f"{column}{self.layout.data_first}"].value).startswith("="),
                f"Data!{column} should be a formula",
            )

    def test_quarantined_rows_are_listed_with_their_reason(self):
        sheet = self.workbook["Rejected rows"]
        listed = [sheet.cell(row=row, column=1).value for row in range(5, 5 + 10)]
        self.assertEqual(
            [value for value in listed if value is not None],
            [bad["line"] for bad in self.dataset.report.rejected],
        )

    def test_the_month_picker_is_a_dropdown_over_the_months_that_exist(self):
        board = self.workbook["Dashboard"]
        picker = next(v for v in board.data_validations.dataValidation
                      if str(v.sqref) == "B4")
        self.assertEqual(picker.type, "list")
        self.assertIn("Summary!$A$2", picker.formula1)

    def test_summifs_ranges_reach_past_the_last_row_so_new_rows_are_included(self):
        formula = self.workbook["Summary"]["B2"].value
        self.assertIn(f"$I${self.layout.data_limit}", formula)
        self.assertGreater(self.layout.data_limit, self.layout.data_last)

    def test_the_dashboard_has_three_charts(self):
        self.assertEqual(len(self.workbook["Dashboard"]._charts), 3)


class SummaryParityTests(DashboardTestCase):
    """Summary sheet SUMIFS vs. the Python aggregation, month by month."""

    def test_revenue_by_month_matches(self):
        expected = dict(by_month(self.dataset.sales).as_pairs())
        sheet = self.workbook["Summary"]
        evaluator = Evaluator(self.workbook, "Summary")
        for row in range(2, self.layout.summary_last + 1):
            month = sheet[f"A{row}"].value
            with self.subTest(month=month):
                self.assertAlmostEqual(
                    evaluator.evaluate(sheet[f"B{row}"].value, "Summary"),
                    expected[month], places=2,
                )

    def test_margin_units_and_orders_by_month_match(self):
        margins = dict(by_month(self.dataset.sales, "margin").as_pairs())
        units = dict(by_month(self.dataset.sales, "units").as_pairs())
        sheet = self.workbook["Summary"]
        evaluator = Evaluator(self.workbook, "Summary")
        for row in range(2, self.layout.summary_last + 1):
            month = sheet[f"A{row}"].value
            orders = sum(1 for sale in self.dataset.sales if sale.month == month)
            with self.subTest(month=month):
                self.assertAlmostEqual(
                    evaluator.evaluate(sheet[f"D{row}"].value, "Summary"),
                    margins[month], places=2, msg="margin")
                self.assertAlmostEqual(
                    evaluator.evaluate(sheet[f"F{row}"].value, "Summary"),
                    units[month], places=2, msg="units")
                self.assertEqual(
                    evaluator.evaluate(sheet[f"G{row}"].value, "Summary"), orders,
                    msg="orders")

    def test_revenue_by_region_matches(self):
        expected = dict(by_dimension(self.dataset.sales, "region").as_pairs())
        sheet = self.workbook["Summary"]
        evaluator = Evaluator(self.workbook, "Summary")
        for row in range(2, self.layout.region_last + 1):
            region = sheet[f"J{row}"].value
            with self.subTest(region=region):
                self.assertAlmostEqual(
                    evaluator.evaluate(sheet[f"K{row}"].value, "Summary"),
                    expected[region], places=2,
                )

    def test_revenue_by_product_matches(self):
        expected = dict(by_dimension(self.dataset.sales, "product").as_pairs())
        sheet = self.workbook["Summary"]
        evaluator = Evaluator(self.workbook, "Summary")
        for row in range(2, self.layout.product_last + 1):
            product = sheet[f"N{row}"].value
            with self.subTest(product=product):
                self.assertAlmostEqual(
                    evaluator.evaluate(sheet[f"O{row}"].value, "Summary"),
                    expected[product], places=2,
                )


class KpiCardParityTests(DashboardTestCase):
    """The cards on the Dashboard vs. dashkit.summarise, for every month."""

    CARD_COLUMNS = {"Revenue": "A", "Margin": "C", "Margin %": "E",
                    "Units": "G", "Orders": "I", "Avg order": "K"}
    LABELS = {"Revenue": "Revenue", "Margin": "Margin", "Margin %": "Margin %",
              "Units": "Units", "Orders": "Orders", "Avg order": "Average order value"}

    def _cards_for(self, month):
        workbook = openpyxl.load_workbook(self.path)
        board = workbook["Dashboard"]
        board["B4"] = month
        evaluator = Evaluator(workbook, "Dashboard")
        return {
            name: (
                evaluator.evaluate(board[f"{column}7"].value, "Dashboard"),
                evaluator.evaluate(board[f"{column}8"].value, "Dashboard"),
            )
            for name, column in self.CARD_COLUMNS.items()
        }

    def test_every_card_matches_for_every_month(self):
        for month in self.layout.months:
            expected = {kpi.label: kpi for kpi in summarise(self.dataset.sales, month)}
            actual = self._cards_for(month)
            for name, (value, delta) in actual.items():
                kpi = expected[self.LABELS[name]]
                with self.subTest(month=month, card=name):
                    scale = 100.0 if name == "Margin %" else 1.0
                    self.assertAlmostEqual(value * scale, kpi.value, places=2, msg="value")
                    if kpi.delta_percent is None:
                        self.assertEqual(delta, "", msg="delta should be blank")
                    else:
                        self.assertAlmostEqual(delta * 100, kpi.delta_percent, places=2,
                                               msg="delta")

    def test_the_first_month_shows_no_change_rather_than_a_fake_one(self):
        for _, delta in self._cards_for(self.layout.months[0]).values():
            self.assertEqual(delta, "")


class RefreshTests(DashboardTestCase):
    """The claim is that new data refreshes the dashboard. This checks it."""

    def test_appending_rows_below_the_data_moves_every_number(self):
        workbook = openpyxl.load_workbook(self.path)
        data = workbook["Data"]
        month = self.layout.months[-1]
        row = self.layout.data_last + 1

        data.cell(row=row, column=1, value=date(int(month[:4]), int(month[5:]), 15))
        data.cell(row=row, column=2, value=month)
        data.cell(row=row, column=3, value="Cairo")
        data.cell(row=row, column=4, value="Screw compressor")
        data.cell(row=row, column=5, value="Direct")
        data.cell(row=row, column=6, value=10)
        data.cell(row=row, column=7, value=1000.0)
        data.cell(row=row, column=8, value=600.0)
        data.cell(row=row, column=9, value=f"=ROUND(F{row}*G{row},2)")
        data.cell(row=row, column=10, value=f"=ROUND(F{row}*H{row},2)")
        data.cell(row=row, column=11, value=f"=I{row}-J{row}")

        board = workbook["Dashboard"]
        board["B4"] = month
        evaluator = Evaluator(workbook, "Dashboard")

        extra = Sale(date=date(int(month[:4]), int(month[5:]), 15), region="Cairo",
                     product="Screw compressor", channel="Direct", units=10,
                     unit_price=1000.0, unit_cost=600.0)
        expected = {kpi.label: kpi
                    for kpi in summarise(self.dataset.sales + [extra], month)}

        self.assertAlmostEqual(
            evaluator.evaluate(board["A7"].value, "Dashboard"),
            expected["Revenue"].value, places=2,
            msg="revenue card did not pick up the appended row",
        )
        self.assertAlmostEqual(
            evaluator.evaluate(board["I7"].value, "Dashboard"),
            expected["Orders"].value, places=2, msg="order count",
        )

    def test_correcting_a_unit_price_flows_through_to_the_kpi(self):
        workbook = openpyxl.load_workbook(self.path)
        data = workbook["Data"]
        row = self.layout.data_first
        month = data.cell(row=row, column=2).value
        data.cell(row=row, column=7, value=99999.0)

        board = workbook["Dashboard"]
        board["B4"] = month
        evaluator = Evaluator(workbook, "Dashboard")

        original = self.dataset.sales[0]
        corrected = [
            Sale(date=s.date, region=s.region, product=s.product, channel=s.channel,
                 units=s.units, unit_price=99999.0 if s is original else s.unit_price,
                 unit_cost=s.unit_cost)
            for s in sorted(self.dataset.sales, key=lambda s: (s.date, s.region))
        ]
        corrected[0] = Sale(
            date=corrected[0].date, region=corrected[0].region, product=corrected[0].product,
            channel=corrected[0].channel, units=corrected[0].units,
            unit_price=99999.0, unit_cost=corrected[0].unit_cost,
        )
        expected = {kpi.label: kpi for kpi in summarise(corrected, month)}

        self.assertAlmostEqual(
            evaluator.evaluate(board["A7"].value, "Dashboard"),
            expected["Revenue"].value, places=2,
            msg="a corrected unit price should move the revenue card",
        )


if __name__ == "__main__":
    unittest.main()
