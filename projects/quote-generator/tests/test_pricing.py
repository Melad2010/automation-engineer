import unittest
from datetime import date

from quotekit import Catalog, LineRequest, PricingError, price_quote
from quotekit.catalog import CatalogError
from quotekit.pricing import _round, price_line

CATALOG = Catalog.load()
TODAY = date(2026, 9, 19)


def quote(*requests, tier="standard", customer="Acme"):
    return price_quote(CATALOG, list(requests), customer, tier, quote_date=TODAY)


class RoundingTests(unittest.TestCase):
    """A quote is read by a human, so halves round away from zero, not to even."""

    def test_half_rounds_up_not_to_even(self):
        self.assertEqual(_round(2.675, 2), 2.68)
        self.assertEqual(_round(0.125, 2), 0.13)
        self.assertEqual(_round(2.5, 0), 3)

    def test_negative_halves_round_away_from_zero(self):
        self.assertEqual(_round(-2.675, 2), -2.68)

    def test_exact_values_are_untouched(self):
        self.assertEqual(_round(1450.0, 2), 1450.0)


class LinePricingTests(unittest.TestCase):
    def test_options_add_to_the_unit_price(self):
        line = price_line(CATALOG, LineRequest("PMP-100", 1, ["STN", "VFD"]), "standard")
        self.assertEqual(line.unit_list_price, 4200.0 + 640.0 + 980.0)

    def test_options_add_to_the_unit_cost(self):
        line = price_line(CATALOG, LineRequest("PMP-100", 1, ["STN"]), "standard")
        self.assertEqual(line.unit_cost, 3100.0 + 480.0)

    def test_quantity_break_uses_the_highest_tier_reached(self):
        self.assertEqual(price_line(CATALOG, LineRequest("PMP-100", 2), "standard")
                         .quantity_discount_percent, 0.0)
        self.assertEqual(price_line(CATALOG, LineRequest("PMP-100", 3), "standard")
                         .quantity_discount_percent, 4.0)
        self.assertEqual(price_line(CATALOG, LineRequest("PMP-100", 11), "standard")
                         .quantity_discount_percent, 7.5)
        self.assertEqual(price_line(CATALOG, LineRequest("PMP-100", 50), "standard")
                         .quantity_discount_percent, 11.0)

    def test_quantity_and_tier_discounts_add_up(self):
        line = price_line(CATALOG, LineRequest("PMP-100", 6), "distributor")
        self.assertEqual(line.applied_discount_percent, 7.5 + 6.5)

    def test_line_total_is_net_price_times_quantity(self):
        line = price_line(CATALOG, LineRequest("PNL-040", 4), "standard")
        self.assertEqual(line.line_total, _round(line.unit_net_price * 4, 2))

    def test_description_lists_the_chosen_options(self):
        line = price_line(CATALOG, LineRequest("PNL-040", 1, ["HMI"]), "standard")
        self.assertIn("7 inch HMI touchscreen", line.description)


class MarginFloorTests(unittest.TestCase):
    """The floor is the rule that stops a quote being sold below cost + margin."""

    def test_a_large_manual_discount_is_capped(self):
        line = price_line(
            CATALOG, LineRequest("SRV-INS", 1, manual_discount_percent=60), "standard"
        )
        self.assertLess(line.applied_discount_percent, 60)
        self.assertTrue(line.discount_was_capped)

    def test_a_capped_line_lands_on_the_floor_not_below_it(self):
        line = price_line(
            CATALOG, LineRequest("SRV-INS", 1, manual_discount_percent=60), "standard"
        )
        self.assertAlmostEqual(line.margin_percent, CATALOG.margin_floor_percent, places=1)

    def test_the_cap_is_recorded_in_a_note(self):
        line = price_line(
            CATALOG, LineRequest("SRV-INS", 1, manual_discount_percent=60), "standard"
        )
        self.assertTrue(any("margin floor" in note for note in line.notes))
        self.assertIn("requested 60.00%", line.notes[0])

    def test_a_discount_below_the_ceiling_passes_through_untouched(self):
        line = price_line(
            CATALOG, LineRequest("CMP-220", 1, manual_discount_percent=5), "standard"
        )
        self.assertEqual(line.applied_discount_percent, 5.0)
        self.assertEqual(line.notes, ())

    def test_every_catalogue_line_stays_at_or_above_the_floor(self):
        for code in CATALOG.products:
            for tier in CATALOG.customer_tiers:
                line = price_line(
                    CATALOG, LineRequest(code, 12, manual_discount_percent=90), tier
                )
                self.assertGreaterEqual(
                    line.margin_percent, CATALOG.margin_floor_percent - 0.05,
                    f"{code}/{tier} fell through the margin floor",
                )


class ValidationTests(unittest.TestCase):
    def test_unknown_product_names_the_valid_codes(self):
        with self.assertRaises(CatalogError) as caught:
            price_line(CATALOG, LineRequest("NOPE"), "standard")
        self.assertIn("PMP-100", str(caught.exception))

    def test_unknown_option_names_the_valid_codes(self):
        with self.assertRaises(CatalogError) as caught:
            price_line(CATALOG, LineRequest("PMP-100", 1, ["HMI"]), "standard")
        self.assertIn("STN", str(caught.exception))

    def test_unknown_tier_is_rejected_before_any_pricing(self):
        with self.assertRaises(CatalogError):
            quote(LineRequest("PMP-100", 1), tier="vip")

    def test_zero_quantity_is_rejected(self):
        with self.assertRaises(PricingError):
            price_line(CATALOG, LineRequest("PMP-100", 0), "standard")

    def test_fractional_quantity_is_rejected(self):
        with self.assertRaises(PricingError):
            price_line(CATALOG, LineRequest("PMP-100", 1.5), "standard")

    def test_a_repeated_option_is_rejected_rather_than_charged_twice(self):
        with self.assertRaises(PricingError):
            price_line(CATALOG, LineRequest("PMP-100", 1, ["STN", "STN"]), "standard")

    def test_negative_manual_discount_is_rejected(self):
        with self.assertRaises(PricingError):
            price_line(CATALOG, LineRequest("PMP-100", 1, manual_discount_percent=-5), "standard")

    def test_an_empty_quote_is_rejected(self):
        with self.assertRaises(PricingError):
            price_quote(CATALOG, [], "Acme")


class QuoteTotalsTests(unittest.TestCase):
    def test_subtotal_is_the_sum_of_the_lines(self):
        result = quote(LineRequest("PMP-100", 2), LineRequest("PNL-040", 1))
        self.assertEqual(result.subtotal, _round(sum(l.line_total for l in result.lines), 2))

    def test_vat_is_applied_once_to_the_subtotal(self):
        result = quote(LineRequest("PMP-100", 2), LineRequest("PNL-040", 1))
        self.assertEqual(result.vat_amount, _round(result.subtotal * 14.0 / 100, 2))
        self.assertEqual(result.total, _round(result.subtotal + result.vat_amount, 2))

    def test_lead_time_is_the_slowest_line(self):
        result = quote(LineRequest("PNL-040", 1), LineRequest("CMP-220", 1))
        self.assertEqual(result.lead_time_days, 35)

    def test_validity_follows_the_catalogue_setting(self):
        result = quote(LineRequest("PMP-100", 1))
        self.assertEqual((result.valid_until - result.quote_date).days, 30)

    def test_reference_is_stable_for_the_same_customer_and_date(self):
        first = quote(LineRequest("PMP-100", 1), customer="Acme Industrial")
        second = quote(LineRequest("CMP-220", 1), customer="  acme industrial ")
        self.assertEqual(first.reference, second.reference)

    def test_quote_margin_is_computed_against_cost(self):
        result = quote(LineRequest("PMP-100", 1))
        expected = _round((result.subtotal - result.total_cost) / result.subtotal * 100, 2)
        self.assertEqual(result.margin_percent, expected)

    def test_capped_lines_are_listed_on_the_quote(self):
        result = quote(LineRequest("SRV-INS", 1, manual_discount_percent=70),
                       LineRequest("PMP-100", 1))
        self.assertEqual(len(result.capped_lines), 1)


if __name__ == "__main__":
    unittest.main()
