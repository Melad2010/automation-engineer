# Configurable quote generator

A quotation tool for an industrial equipment supplier: pick a machine, tick the
options, type a quantity, and the quote prices itself — with the pricing logic
protected so a stray paste cannot break it.

The pricing rules live in one file, `catalog.json`, and are implemented three
times because clients live in three places:

| Implementation | For | File |
|---|---|---|
| Python | the reference, the CLI, and automation | `quotekit/pricing.py` |
| Excel formulas | the workbook the sales team actually opens | `build_tool.py` → `QuoteTool.xlsx` |
| VBA | macro-driven `.xlsm` workbooks, PDF export | `vba/QuoteGenerator.bas` |
| Apps Script | the same tool in Google Sheets | `apps-script/Code.gs` |

Three implementations of one rule is three chances to drift, so the tests run all
of them against every product, tier and quantity break and fail if any two
disagree. That check has already earned its keep — see *What the tests caught*.

## Run it

```bash
cd projects/quote-generator

python3 quote.py --demo                       # price the bundled example
python3 quote.py --customer "Acme Industrial" --tier partner \
    --line PMP-100:6:STN,VFD --line SRV-INS:1 --xlsx dist/quote.xlsx

pip install openpyxl                          # only needed for .xlsx output
python3 build_tool.py --out dist/QuoteTool.xlsx
```

`quote.py --demo` needs nothing installed. `build_tool.py` and `--xlsx` need
`openpyxl`, and say so plainly if it is missing.

## The pricing rules

Applied to every line, in this order:

1. **Unit list price** = product list price + the price of each selected option.
2. **Unit cost** = product cost + the cost of each option (internal only).
3. **Discount** = quantity break + customer tier + any manual discount, added.
4. **Margin floor** — the discount is capped so the net price never falls below
   `unit_cost / (1 - floor)`. A capped line carries a note saying what was asked
   for and what was allowed. It is never silently repriced.
5. **Net unit price** = `ROUND(unit list × (1 − discount), 2)`.
6. **Line total** = `ROUND(net price × quantity, 2)`.

VAT is applied once to the subtotal, not per line, so the total matches what an
accountant computes by hand.

Rounding is half **away from zero**, not Python's or VBA's banker's rounding:
`2.675` becomes `2.68`, because that is what the printed price list says.

## What the workbook gives a salesperson

- Product, option and customer-tier **dropdowns** — no typing a code wrong.
- Quantity validation that refuses `0`, `2.5` and `-1` at entry.
- **Protected** Catalog and Rules sheets; only the shaded input cells accept
  edits. The password is `quote` and it is written down here on purpose:
  sheet protection stops accidents, it was never a security control.
- Cost and margin on a hidden column and a separate sheet, outside the print
  area, so the customer copy never carries them.
- A print area and fit-to-width page setup, so Ctrl+P produces the document.

## What the tests caught

`tests/xlformula.py` is a small Excel formula evaluator — enough of `IF`,
`INDEX`, `MATCH`, `LOOKUP`, `IFERROR`, `MIN`/`MAX` and `ROUND` to execute the
generated workbook. There is no Excel on a CI box, and a workbook whose formulas
were never executed is an untested deliverable.

It found a real bug on its first run. The Python engine rounded the margin-floor
cap to two decimals; the sheet did not. Rounding a cap **up** by 0.005% pushes
the line back under the very floor the cap exists to protect — about 19 cents on
a $4,200 pump, on exactly the high-volume distributor orders where margin is
already thinnest. The cap now keeps full precision and only the printed note
rounds.

## Adapting it to another business

1. Edit `catalog.json` — products, options, costs, quantity breaks, tiers, VAT,
   margin floor.
2. Re-run `python3 build_tool.py`. Nothing in the workbook is hand-edited, so it
   rebuilds from the catalogue every time.
3. Run the tests. If a new price breaks the margin floor at some quantity, the
   suite says which product and tier.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

50 tests: the pricing rules and their rounding, input validation, the workbook's
structure and protection, workbook-vs-engine parity across every product × tier ×
quantity break, and Apps-Script-vs-engine parity run under Node. The workbook
tests skip if `openpyxl` is missing; the Apps Script test skips if Node is
missing. Neither pretends to pass.
