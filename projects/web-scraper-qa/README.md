# Source-tracked scraper with a QA report

Clean, de-duplicated data from public sources — and a written report saying how
far you can trust it. Every row carries the URL it was read from, so any value
can be traced back to the page that published it.

This is the delivery shape behind the "Python web scraping with a QA report"
service: the dataset is only half of it, the report is the other half.

## Run the demo

No network, no third-party packages. Python 3.9 or newer:

```bash
cd projects/web-scraper-qa
python3 run.py --start fixtures/page-1.html --out out/
```

You get three files in `out/`:

| File | What it is |
|---|---|
| `dataset.csv` | The delivered rows, one `source_url` per row |
| `dataset.json` | The same rows for anything that prefers JSON |
| `qa-report.md` | The report a client reads (plus a `.json` sibling for CI) |

## What the QA report answers

The bundled fixtures deliberately contain every defect a real source throws at
you, so the demo report is not a clean one — that is the point:

- **Rows found vs. published total.** The source claims 13; 12 survive
  de-duplication, so the report states a variance of `-1` instead of quietly
  shipping a short file.
- **Duplicates removed**, with the colliding key listed so you can overrule the
  decision.
- **Per-field completeness**, required fields separated from optional ones.
- **Rows missing a required field**, named and linked to their source page —
  reported, never filled with a guess.
- **Values that failed a shape check**: a website that is not a URL, an email
  that is not an email.
- **Pages that could not be read**, with the reason and the retries spent.

`--fail-on-dirty` exits non-zero when the report is not clean, which is what you
want when the scrape runs on a schedule.

## Why it is built this way

A scraper that only works on the happy path produces a dataset nobody can trust,
because a page silently dropped after a 503 looks exactly like a source that had
nothing to publish. So:

- `Fetcher` retries 429/5xx with exponential backoff, refuses to retry a 404,
  keeps one request per host per `--delay` seconds, and logs every attempt. The
  retry count lands in the report.
- The crawler stops at `--max-pages` so a circular pager costs a bounded number
  of requests.
- Parsing is `html.parser` from the standard library; the selectors live in one
  dict (`scrapekit/parser.py`), because retargeting a scraper at a new source is
  almost always a selector change, not a logic change.

## Retargeting it at a real source

1. Point `SELECTORS` in `scrapekit/parser.py` at the new page's class names.
2. Set `--start` to the first listing page and pick a polite `--delay`.
3. Run with `--fail-on-dirty` and read the report before you trust the CSV.

Check the source's terms and `robots.txt` first. This collects public data only.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

38 tests covering the parser, the retry and rate-limit behaviour (with a scripted
server, so no test waits on real time), the QA rules, and the CLI end to end.
