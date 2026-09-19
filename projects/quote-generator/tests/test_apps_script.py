"""The Google Sheets version has to agree with the Python engine too.

Three implementations of one rule is three chances to drift. This test runs the
real Code.gs functions under Node against every catalogue product, tier and
quantity break, and compares them with quotekit/pricing.py. It skips when Node
is not installed rather than pretending it passed.
"""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from quotekit import Catalog, LineRequest
from quotekit.pricing import _round, price_line

CATALOG = Catalog.load()
CODE_GS = Path(__file__).resolve().parent.parent / "apps-script" / "Code.gs"
NODE = shutil.which("node")

# Code.gs reads its rules from the sheet; here we hand it the same numbers
# catalog.json holds, expressed the way the Rules sheet stores them (fractions).
HARNESS = """
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
// Code.gs is written for the Apps Script runtime; expose its functions here.
const sandbox = {};
new Function('exports', src + '\\nexports.roundHalfUp = roundHalfUp;'
             + '\\nexports.priceLine = priceLine;')(sandbox);

const input = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = input.cases.map(function (item) {
  const priced = sandbox.priceLine(
    input.rules, item.unitList, item.unitCost, item.quantity, item.tier, item.manual
  );
  const net = sandbox.roundHalfUp(item.unitList * (1 - priced.discount), 2);
  return {
    discount: priced.discount,
    capped: priced.capped,
    net: net,
    lineTotal: sandbox.roundHalfUp(net * item.quantity, 2)
  };
});
process.stdout.write(JSON.stringify({
  results: out,
  rounding: [
    sandbox.roundHalfUp(2.675, 2),
    sandbox.roundHalfUp(0.125, 2),
    sandbox.roundHalfUp(-2.675, 2)
  ]
}));
"""


def _rules() -> dict:
    return {
        "breaks": [
            {"minQuantity": b.min_quantity, "discount": b.discount_percent / 100.0}
            for b in CATALOG.quantity_breaks
        ],
        "tiers": {name: percent / 100.0 for name, percent in CATALOG.customer_tiers.items()},
        "vat": CATALOG.vat_percent / 100.0,
        "marginFloor": CATALOG.margin_floor_percent / 100.0,
        "validDays": CATALOG.quote_valid_days,
    }


def _cases():
    """Every product x tier x quantity break, plus a deep manual discount."""
    for code, product in sorted(CATALOG.products.items()):
        for tier in sorted(CATALOG.customer_tiers):
            for quantity in (1, 3, 6, 12):
                yield LineRequest(code, quantity), tier, 0.0
            yield LineRequest(code, 1, manual_discount_percent=80), tier, 80.0


@unittest.skipIf(NODE is None, "node is not installed")
class AppsScriptParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = list(_cases())
        payload = {
            "rules": _rules(),
            "cases": [
                {
                    "unitList": CATALOG.products[request.product_code].list_price,
                    "unitCost": CATALOG.products[request.product_code].cost,
                    "quantity": request.quantity,
                    "tier": tier,
                    "manual": manual / 100.0,
                }
                for request, tier, manual in cls.requests
            ],
        }

        import tempfile

        cls._tmp = tempfile.TemporaryDirectory()
        harness = Path(cls._tmp.name) / "harness.js"
        data = Path(cls._tmp.name) / "input.json"
        harness.write_text(HARNESS, encoding="utf-8")
        data.write_text(json.dumps(payload), encoding="utf-8")

        completed = subprocess.run(
            [NODE, str(harness), str(CODE_GS), str(data)],
            capture_output=True, text=True, timeout=120, check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"Code.gs failed to run under node:\n{completed.stderr}")
        cls.output = json.loads(completed.stdout)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_tmp"):
            cls._tmp.cleanup()

    def test_rounding_matches_the_python_helper(self):
        self.assertEqual(self.output["rounding"], [_round(2.675, 2), _round(0.125, 2),
                                                   _round(-2.675, 2)])

    def test_every_case_matches_the_python_engine(self):
        for (request, tier, _), actual in zip(self.requests, self.output["results"]):
            expected = price_line(CATALOG, request, tier)
            with self.subTest(product=request.product_code, tier=tier, qty=request.quantity):
                self.assertAlmostEqual(actual["discount"] * 100,
                                       expected.applied_discount_percent, places=6)
                self.assertAlmostEqual(actual["net"], expected.unit_net_price, places=2)
                self.assertAlmostEqual(actual["lineTotal"], expected.line_total, places=2)
                self.assertEqual(actual["capped"], expected.discount_was_capped)


if __name__ == "__main__":
    unittest.main()
