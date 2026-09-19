# Excel KPI dashboard from a CSV

The KPIs that matter on one page, with a month selector, three charts, and a
refresh that is "paste the new rows and pick the month" — because every number
on the dashboard is a formula over the data, not a pasted value.

## Run it

```bash
cd projects/kpi-dashboard

python3 make_sample_data.py                    # 489 rows, 4 deliberately broken
python3 build.py --csv sample-sales.csv --summary       # numbers, no Excel needed

pip install openpyxl
python3 build.py --csv sample-sales.csv --out dist/dashboard.xlsx
```

`--summary` runs on the standard library alone. Writing the `.xlsx` needs
`openpyxl`, and says so plainly if it is missing.

## What the workbook contains

| Sheet | What it holds |
|---|---|
| **Dashboard** | Six KPI cards, a month dropdown, three charts. Nothing stored, everything derived. |
| **Data** | The clean data model. Revenue, cost and margin are formulas, so correcting a unit price moves every number downstream of it. |
| **Summary** | `SUMIFS` per month, per region and per product. The charts read from here. |
| **Rejected rows** | Every row the loader refused, with its line number and the reason. |

The KPI cards are Revenue, Margin, Margin %, Units, Orders and Average order
value, each with the change against the previous month. The `SUMIFS` ranges
extend 2,000 rows past the end of the data, so appended rows are picked up
without anyone editing a range.

## The two rules this project is built on

**A row that cannot be parsed is quarantined, not coerced.** `units = "three"`,
a date of `2026-13-05`, a blank region, a quantity of zero — each is listed on
the *Rejected rows* sheet with its line number and never reaches a total. A
dashboard that silently turns bad input into zero is worse than one that
refuses it, because the zero looks like a fact. The sample CSV ships with four
such rows precisely so the behaviour is visible.

**A previous period of zero has no percentage change.** The card shows blank
rather than `+100%` or `∞`. So does the first month in the file.

The loader does accept the shapes a real export produces — `1,250.00`, padded
spaces, accounting negatives like `(30)`, and five date formats — because
rejecting those would be pedantry, not rigour.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

45 tests. The interesting ones execute the workbook's own formulas with
`projects/_shared/xlformula.py` and compare them against the Python
implementation: every `SUMIFS` on the Summary sheet, every KPI card for every
month in the file, and two refresh scenarios — appending a row below the data,
and correcting a unit price — asserting the cards actually move.

That comparison caught a real mismatch on its first run. `Margin %` was rounded
to two decimals *before* the month-over-month change was taken, while the sheet
computed the change from the full-precision ratio. The two disagreed by a few
hundredths of a point every month. The engine now keeps the ratio unrounded and
only the display rounds.

## Adapting it to your data

The CSV needs these columns: `date, region, product, channel, units, unit_price,
unit_cost`. To dashboard something else, rename the dimensions in
`dashkit/model.py` and the two `block(...)` calls in `dashkit/workbook.py`;
the metrics, the cards and the charts follow.
