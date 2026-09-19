# Projects

Four running versions of the work the landing page describes. Each one is a real
deliverable, not a snippet: it runs, it has tests, and the tests cover the cases
that actually go wrong rather than the happy path.

| Project | What it delivers | Runs offline | Tests |
|---|---|---|---|
| [web-scraper-qa](web-scraper-qa/) | Source-tracked dataset + a written QA report | yes | 38 |
| [quote-generator](quote-generator/) | An Excel quote tool, plus VBA and Apps Script | yes | 50 |
| [kpi-dashboard](kpi-dashboard/) | Excel KPI dashboard from a CSV | yes | 45 |
| [ai-agent](ai-agent/) | An agent with budgets, limits and a schema-checked verdict | yes | 71 |

```bash
./run-tests.sh          # all four suites
pip install openpyxl    # only the two spreadsheet projects need it
```

Every project runs with no network, no API key and no paid service. The
spreadsheet projects skip their workbook tests if `openpyxl` is missing and the
agent's Node parity test skips if Node is missing — neither pretends to pass.

## Three ideas they share

**Report the gaps, do not fill them.** The scraper lists rows missing a required
field instead of guessing one. The dashboard quarantines an unparseable row
instead of counting it as zero. The agent's lookup tool returns `found: false`
and tells the model not to invent a record. A number you cannot trace is worse
than a number that is missing, because it looks like a fact.

**Test the deliverable, not a model of it.** Both spreadsheet projects ship a
workbook, so [`_shared/xlformula.py`](_shared/) evaluates the generated formulas
in CI and compares them against the Python implementation of the same rules.
That comparison has found two real bugs so far — a margin floor breached by
rounding the cap up, and a month-over-month percentage computed from an
already-rounded ratio. Both are written up in the project READMEs.

**Make the failure path the default case.** Retries with backoff that refuse to
retry a 404 or a 400, a rate limiter, budgets that stop a run rather than warn
about it, validation that names the invalid value. The tests spend most of their
effort here.
