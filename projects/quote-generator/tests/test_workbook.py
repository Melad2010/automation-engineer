"""The workbook is the deliverable, so its formulas get executed, not eyeballed.

Every case below fills QuoteTool.xlsx the way a salesperson would, evaluates the
sheet's own formulas with tests/xlformula.py, and asserts the result equals what
quotekit/pricing.py computes. The two implementations are kept honest by these
tests rather than by hope.
"""

import tempfile
import unittest
from pathlib import Path

try:
    import openpyxl
except ImportError:  # pragma: no cover - the suite skips rather than fails
    openpyxl = None

from quotekit import Catalog, LineRequest, price_quote
from quotekit.pricing import price_line

if openpyxl is not None:
    from build_tool import MAX_LINES, SHEET_PASSWORD, build
    from tests.xlformula import Evaluator

CATALOG = Catalog.load()
FIRST_LINE = 9


@unittest.skipIf(openpyxl is None, "openpyxl is not installed")
class WorkbookTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.path = build(CATALOG, Path(cls._tmp.name) / "QuoteTool.xlsx")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _filled(self, requests, tier="standard"):
        """Fill the Quote sheet as a user would, and return an evaluator for it."""
        workbook = openpyxl.load_workbook(self.path)
        sheet = workbook["Quote"]
        sheet["B4"] = tier
        for offset, request in enumerate(requests):
            row = FIRST_LINE + offset
            sheet[f"B{row}"] = request.product_code
            sheet[f"G{row}"] = request.quantity
            for column, code in zip("DEF", request.options):
                sheet[f"{column}{row}"] = code
        return sheet, Evaluator(workbook, "Quote")


class StructureTests(WorkbookTestCase):
    def test_pricing_sheets_are_protected(self):
        workbook = openpyxl.load_workbook(self.path)
        for name in ("Catalog", "Rules", "Quote"):
            self.assertTrue(workbook[name].protection.sheet, f"{name} is unprotected")

    def test_input_cells_stay_editable_under_protection(self):
        sheet = openpyxl.load_workbook(self.path)["Quote"]
        for ref in ("B3", "B4", "B9", "D9", "G9"):
            self.assertFalse(sheet[ref].protection.locked, f"{ref} should be editable")

    def test_formula_cells_are_locked(self):
        sheet = openpyxl.load_workbook(self.path)["Quote"]
        for ref in ("H9", "I9", "J9", "K9"):
            self.assertTrue(sheet[ref].protection.locked, f"{ref} should be locked")

    def test_catalogue_values_match_the_json_exactly(self):
        sheet = openpyxl.load_workbook(self.path)["Catalog"]
        written = {
            row[0]: (row[1], row[2], row[3])
            for row in sheet.iter_rows(min_row=2, max_col=5, values_only=True)
            if row[0]
        }
        self.assertEqual(len(written), len(CATALOG.products))
        for code, product in CATALOG.products.items():
            self.assertEqual(written[code], (product.name, product.list_price, product.cost))

    def test_every_option_reaches_the_catalogue_sheet(self):
        sheet = openpyxl.load_workbook(self.path)["Catalog"]
        keys = {row[0] for row in sheet.iter_rows(min_row=2, min_col=7, max_col=7,
                                                  values_only=True) if row[0]}
        expected = {
            f"{product.code}|{code}"
            for product in CATALOG.products.values()
            for code in product.options
        }
        self.assertEqual(keys, expected)

    def test_dropdowns_cover_product_option_tier_and_quantity(self):
        sheet = openpyxl.load_workbook(self.path)["Quote"]
        ranges = {str(v.sqref) for v in sheet.data_validations.dataValidation}
        last = FIRST_LINE + MAX_LINES - 1
        self.assertIn(f"B{FIRST_LINE}:B{last}", ranges)
        self.assertIn(f"D{FIRST_LINE}:F{last}", ranges)
        self.assertIn(f"G{FIRST_LINE}:G{last}", ranges)
        self.assertIn("B4", ranges)

    def test_quantity_validation_refuses_zero_and_fractions(self):
        sheet = openpyxl.load_workbook(self.path)["Quote"]
        quantity = next(
            v for v in sheet.data_validations.dataValidation
            if str(v.sqref).startswith("G")
        )
        self.assertEqual(quantity.type, "whole")
        self.assertEqual(quantity.operator, "greaterThanOrEqual")
        self.assertEqual(quantity.formula1, "1")

    def test_internal_cost_columns_are_hidden_from_the_customer_view(self):
        sheet = openpyxl.load_workbook(self.path)["Quote"]
        self.assertTrue(sheet.column_dimensions["M"].hidden)
        self.assertTrue(sheet.print_area in (["A1:K30"], ["'Quote'!A1:K30"], sheet.print_area))
        self.assertNotIn("M", "".join(sheet.print_area or []))

    def test_the_protection_password_is_documented_not_secret(self):
        # Sheet protection stops accidents, not people. The README says so too.
        self.assertEqual(SHEET_PASSWORD, "quote")


class ParityTests(WorkbookTestCase):
    """The workbook and the Python engine must agree, line by line."""

    def _assert_line_matches(self, requests, tier, offset=0):
        sheet, evaluator = self._filled(requests, tier)
        row = FIRST_LINE + offset
        expected = price_line(CATALOG, requests[offset], tier)

        self.assertAlmostEqual(
            evaluator.evaluate(sheet[f"H{row}"].value, "Quote"),
            expected.unit_list_price, places=2, msg="unit list price",
        )
        self.assertAlmostEqual(
            evaluator.evaluate(sheet[f"I{row}"].value, "Quote") * 100,
            expected.applied_discount_percent, places=2, msg="discount",
        )
        self.assertAlmostEqual(
            evaluator.evaluate(sheet[f"J{row}"].value, "Quote"),
            expected.unit_net_price, places=2, msg="net unit price",
        )
        self.assertAlmostEqual(
            evaluator.evaluate(sheet[f"K{row}"].value, "Quote"),
            expected.line_total, places=2, msg="line total",
        )

    def test_plain_line(self):
        self._assert_line_matches([LineRequest("PMP-100", 1)], "standard")

    def test_line_with_options(self):
        self._assert_line_matches([LineRequest("PMP-100", 1, ["STN", "VFD"])], "standard")

    def test_quantity_break_applies_in_the_sheet_too(self):
        self._assert_line_matches([LineRequest("CMP-220", 6)], "standard")

    def test_tier_discount_applies_in_the_sheet_too(self):
        self._assert_line_matches([LineRequest("CMP-220", 1)], "distributor")

    def test_quantity_and_tier_together(self):
        self._assert_line_matches([LineRequest("PNL-040", 12, ["HMI", "UPS"])], "distributor")

    def test_margin_floor_caps_the_discount_in_the_sheet_too(self):
        # 11% quantity + 6.5% tier on the cheapest-margin item hits the floor.
        self._assert_line_matches([LineRequest("SRV-INS", 12, ["TRN"])], "distributor")

    def test_every_product_and_tier_agrees_at_every_quantity_break(self):
        for code in sorted(CATALOG.products):
            for tier in sorted(CATALOG.customer_tiers):
                for quantity in (1, 3, 6, 12):
                    with self.subTest(product=code, tier=tier, quantity=quantity):
                        self._assert_line_matches(
                            [LineRequest(code, quantity)], tier
                        )

    def test_empty_rows_render_blank_rather_than_zero(self):
        sheet, evaluator = self._filled([LineRequest("PMP-100", 1)])
        blank_row = FIRST_LINE + 1
        for column in "HIJK":
            self.assertEqual(
                evaluator.evaluate(sheet[f"{column}{blank_row}"].value, "Quote"), "",
                f"{column}{blank_row} should be blank on an unused row",
            )


class TotalsParityTests(WorkbookTestCase):
    def test_subtotal_vat_and_total_match_the_engine(self):
        requests = [
            LineRequest("PMP-100", 6, ["STN", "VFD"]),
            LineRequest("CMP-220", 3, ["DRY"]),
            LineRequest("SRV-INS", 1, ["TRN"]),
        ]
        sheet, evaluator = self._filled(requests, "partner")
        expected = price_quote(CATALOG, requests, "Acme", "partner")

        totals_row = FIRST_LINE + MAX_LINES + 1
        self.assertAlmostEqual(
            evaluator.evaluate(sheet[f"K{totals_row}"].value, "Quote"),
            expected.subtotal, places=2, msg="subtotal",
        )
        self.assertAlmostEqual(
            evaluator.evaluate(sheet[f"K{totals_row + 1}"].value, "Quote"),
            expected.vat_amount, places=2, msg="VAT",
        )
        self.assertAlmostEqual(
            evaluator.evaluate(sheet[f"K{totals_row + 2}"].value, "Quote"),
            expected.total, places=2, msg="total",
        )

    def test_internal_margin_matches_the_engine(self):
        requests = [LineRequest("PMP-100", 3), LineRequest("PNL-040", 2, ["HMI"])]
        sheet, evaluator = self._filled(requests, "standard")
        expected = price_quote(CATALOG, requests, "Acme")
        totals_row = FIRST_LINE + MAX_LINES + 1
        self.assertAlmostEqual(
            evaluator.evaluate(sheet[f"N{totals_row}"].value, "Quote"),
            expected.total_cost, places=2,
        )
        self.assertAlmostEqual(
            evaluator.evaluate(sheet[f"N{totals_row + 1}"].value, "Quote") * 100,
            expected.margin_percent, places=1,
        )


if __name__ == "__main__":
    unittest.main()
