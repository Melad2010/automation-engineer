import tempfile
import unittest
from datetime import date
from pathlib import Path

from dashkit import load_csv
from dashkit.model import RowError, Sale, parse_date, parse_number, parse_row

HEADER = "date,region,product,channel,units,unit_price,unit_cost\n"


def write(rows) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    handle.write(HEADER + "".join(rows))
    handle.close()
    return handle.name


class DateParsingTests(unittest.TestCase):
    def test_accepts_the_formats_real_exports_produce(self):
        for text in ("2026-03-09", "09/03/2026", "09-Mar-2026", "2026/03/09"):
            self.assertEqual(parse_date(text).year, 2026)

    def test_rejects_an_impossible_date_rather_than_shifting_it(self):
        with self.assertRaises(RowError):
            parse_date("2026-13-05")

    def test_rejects_free_text(self):
        with self.assertRaises(RowError):
            parse_date("last tuesday")


class NumberParsingTests(unittest.TestCase):
    def test_strips_thousand_separators_and_spaces(self):
        self.assertEqual(parse_number(" 1,250.00 ", "x"), 1250.0)

    def test_reads_accounting_negatives(self):
        self.assertEqual(parse_number("(30)", "x"), -30.0)

    def test_rejects_text_rather_than_treating_it_as_zero(self):
        with self.assertRaises(RowError):
            parse_number("three", "units")

    def test_rejects_an_empty_value(self):
        with self.assertRaises(RowError):
            parse_number("", "units")

    def test_integer_fields_refuse_fractions(self):
        with self.assertRaises(RowError):
            parse_number("2.5", "units", integer=True)


class RowRulesTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "date": "2026-03-09", "region": "Cairo", "product": "Pump",
            "channel": "Direct", "units": "2", "unit_price": "100", "unit_cost": "60",
        }
        row.update(overrides)
        return row

    def test_a_valid_row_computes_revenue_cost_and_margin(self):
        sale = parse_row(self._row(), 2)
        self.assertEqual((sale.revenue, sale.cost, sale.margin), (200.0, 120.0, 80.0))
        self.assertEqual(sale.month, "2026-03")

    def test_missing_columns_are_named_in_the_error(self):
        with self.assertRaises(RowError) as caught:
            parse_row(self._row(region="", channel=""), 2)
        self.assertIn("region", str(caught.exception))
        self.assertIn("channel", str(caught.exception))

    def test_zero_units_is_rejected(self):
        with self.assertRaises(RowError):
            parse_row(self._row(units="0"), 2)

    def test_negative_price_is_rejected(self):
        with self.assertRaises(RowError):
            parse_row(self._row(unit_price="-5"), 2)


class LoadTests(unittest.TestCase):
    def test_bad_rows_are_quarantined_with_their_line_number(self):
        path = write([
            "2026-03-09,Cairo,Pump,Direct,2,100,60\n",
            "2026-13-09,Cairo,Pump,Direct,2,100,60\n",
            "2026-03-11,Delta,Panel,Online,1,50,30\n",
        ])
        dataset = load_csv(path)
        self.assertEqual(dataset.report.rows_read, 3)
        self.assertEqual(dataset.report.rows_accepted, 2)
        self.assertEqual(dataset.report.rejected[0]["line"], 3)
        self.assertFalse(dataset.report.clean)
        Path(path).unlink()

    def test_a_clean_file_reports_clean(self):
        path = write(["2026-03-09,Cairo,Pump,Direct,2,100,60\n"])
        self.assertTrue(load_csv(path).report.clean)
        Path(path).unlink()

    def test_strict_mode_stops_at_the_first_bad_row(self):
        path = write([
            "2026-03-09,Cairo,Pump,Direct,2,100,60\n",
            "2026-03-10,Cairo,Pump,Direct,x,100,60\n",
        ])
        with self.assertRaises(RowError) as caught:
            load_csv(path, strict=True)
        self.assertIn("line 3", str(caught.exception))
        Path(path).unlink()

    def test_a_missing_column_fails_the_whole_file_not_every_row(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
        handle.write("date,region,units\n2026-03-09,Cairo,2\n")
        handle.close()
        with self.assertRaises(RowError) as caught:
            load_csv(handle.name)
        self.assertIn("product", str(caught.exception))
        Path(handle.name).unlink()


if __name__ == "__main__":
    unittest.main()
