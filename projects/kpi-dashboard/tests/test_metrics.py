import unittest
from datetime import date

from dashkit.metrics import KPI, by_dimension, by_month, summarise, top_n
from dashkit.model import Sale


def sale(month, region="Cairo", product="Pump", units=1, price=100.0, cost=60.0):
    return Sale(date=date(int(month[:4]), int(month[5:]), 5), region=region,
                product=product, channel="Direct", units=units,
                unit_price=price, unit_cost=cost)


SALES = [
    sale("2026-01", units=2),                       # rev 200, margin 80
    sale("2026-01", region="Delta", units=1),       # rev 100, margin 40
    sale("2026-02", units=3),                       # rev 300, margin 120
    sale("2026-02", product="Panel", units=1, price=50.0, cost=20.0),  # rev 50, margin 30
]


class DeltaTests(unittest.TestCase):
    def test_percentage_change_against_the_previous_period(self):
        self.assertEqual(KPI("x", 120, 100).delta_percent, 20.0)
        self.assertEqual(KPI("x", 80, 100).delta_percent, -20.0)

    def test_no_previous_period_means_no_percentage(self):
        self.assertIsNone(KPI("x", 120).delta_percent)

    def test_a_previous_period_of_zero_has_no_percentage_change(self):
        # Reporting "+100%" or infinity here is how a dashboard starts lying.
        self.assertIsNone(KPI("x", 120, 0).delta_percent)
        self.assertEqual(KPI("x", 120, 0).delta, 120)


class AggregationTests(unittest.TestCase):
    def test_revenue_by_month(self):
        series = by_month(SALES)
        self.assertEqual(series.as_pairs(), [("2026-01", 300.0), ("2026-02", 350.0)])

    def test_margin_by_month(self):
        self.assertEqual(by_month(SALES, "margin").values, [120.0, 150.0])

    def test_by_region(self):
        self.assertEqual(
            by_dimension(SALES, "region").as_pairs(),
            [("Cairo", 550.0), ("Delta", 100.0)],
        )

    def test_top_n_is_ranked_and_truncated(self):
        series = top_n(SALES, "product", count=1)
        self.assertEqual(series.as_pairs(), [("Pump", 600.0)])


class SummaryTests(unittest.TestCase):
    def test_cards_cover_the_selected_month(self):
        cards = {kpi.label: kpi for kpi in summarise(SALES, "2026-02")}
        self.assertEqual(cards["Revenue"].value, 350.0)
        self.assertEqual(cards["Margin"].value, 150.0)
        self.assertEqual(cards["Units"].value, 4)
        self.assertEqual(cards["Orders"].value, 2)

    def test_previous_month_is_the_comparison(self):
        cards = {kpi.label: kpi for kpi in summarise(SALES, "2026-02")}
        self.assertEqual(cards["Revenue"].previous, 300.0)
        self.assertAlmostEqual(cards["Revenue"].delta_percent, 16.67, places=2)

    def test_the_first_month_has_nothing_to_compare_against(self):
        for kpi in summarise(SALES, "2026-01"):
            self.assertIsNone(kpi.previous)
            self.assertIsNone(kpi.delta_percent)

    def test_margin_percent_is_margin_over_revenue(self):
        cards = {kpi.label: kpi for kpi in summarise(SALES, "2026-02")}
        self.assertAlmostEqual(cards["Margin %"].value, 150.0 / 350.0 * 100, places=2)

    def test_average_order_value_is_revenue_over_orders(self):
        cards = {kpi.label: kpi for kpi in summarise(SALES, "2026-02")}
        self.assertEqual(cards["Average order value"].value, 175.0)

    def test_no_month_means_totals_with_no_comparison(self):
        cards = {kpi.label: kpi for kpi in summarise(SALES)}
        self.assertEqual(cards["Revenue"].value, 650.0)
        self.assertIsNone(cards["Revenue"].previous)

    def test_an_unknown_month_names_the_months_that_exist(self):
        with self.assertRaises(ValueError) as caught:
            summarise(SALES, "2099-01")
        self.assertIn("2026-01", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
