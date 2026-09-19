# automation-engineer

The site at **[melad2010.github.io/automation-engineer](https://melad2010.github.io/automation-engineer/)**,
and the four projects behind it.

I build automation that survives real use: AI agents and LLM workflows, Python
data pipelines that come with a written QA report, and Excel or Google Sheets
tools a team can run every day. Twelve years of medical-device engineering
behind it, which mostly means the failure cases get tested too.

## The projects

| Project | What it delivers | Tests |
|---|---|---|
| [web-scraper-qa](projects/web-scraper-qa/) | Source-tracked dataset + a written QA report | 38 |
| [quote-generator](projects/quote-generator/) | An Excel quote tool, plus VBA and Apps Script | 50 |
| [kpi-dashboard](projects/kpi-dashboard/) | Excel KPI dashboard from a CSV | 45 |
| [ai-agent](projects/ai-agent/) | An agent with budgets, limits and a schema-checked verdict | 71 |

Every project runs with no network, no API key and no paid service. See
[projects/README.md](projects/README.md) for what they have in common, and
[projects.html](https://melad2010.github.io/automation-engineer/projects.html)
for the readable version.

## Running everything

```bash
git clone https://github.com/Melad2010/automation-engineer
cd automation-engineer

./run-tests.sh                 # all 204 tests, standard library only

pip install openpyxl           # only the two spreadsheet projects need it
./run-tests.sh                 # now including the workbook tests
```

Individual demos:

```bash
cd projects/web-scraper-qa  && python3 run.py --start fixtures/page-1.html --out out/
cd projects/quote-generator && python3 quote.py --demo
cd projects/kpi-dashboard   && python3 build.py --csv sample-sales.csv --summary
cd projects/ai-agent        && python3 run.py --dry-run
```

## Layout

```
index.html            the landing page
projects.html         the portfolio page
img/                  images used by both
projects/
  _shared/            an Excel formula evaluator both spreadsheet projects test with
  web-scraper-qa/
  quote-generator/
  kpi-dashboard/
  ai-agent/
run-tests.sh          every suite
.github/workflows/    CI on Python 3.9, 3.11 and 3.12
```

## Work with me

Orders, messages and files go through Fiverr, so payment is held until you
approve the delivery: **[fiverr.com/meladfekry](https://www.fiverr.com/meladfekry)**.
