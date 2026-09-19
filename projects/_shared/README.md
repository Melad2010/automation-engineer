# Shared test tooling

`xlformula.py` is a small Excel formula evaluator. Both spreadsheet projects
(`quote-generator` and `kpi-dashboard`) ship a workbook as the deliverable, and a
workbook whose formulas were never executed is an untested deliverable. There is
no Excel on a CI runner, so the tests parse and evaluate the generated formulas
here and compare the results against the Python implementation of the same rules.

It supports only what those two workbooks use — `IF`, `IFERROR`, `INDEX`,
`MATCH`, `LOOKUP`, `SUMIFS`, `COUNTIFS`, `SUM`, `MIN`, `MAX`, `ROUND`, `ABS`,
`AND`, `OR`, `TODAY`, and the usual operators. Anything else raises, so an
unsupported formula fails loudly instead of quietly returning the wrong number.

It lives here rather than being copied into both projects: one evaluator with
one set of bugs is easier to trust than two.
