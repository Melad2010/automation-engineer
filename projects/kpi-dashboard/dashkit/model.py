"""Loading the source CSV into a clean data model.

A dashboard built on pasted values is a dashboard that lies the first time
someone pastes a number as text. Every row is parsed and checked here, and a row
that fails is quarantined with the reason and the line number — never coerced to
zero and never silently dropped.
"""

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

REQUIRED_COLUMNS = ("date", "region", "product", "channel", "units", "unit_price", "unit_cost")


class RowError(ValueError):
    pass


@dataclass(frozen=True)
class Sale:
    date: date
    region: str
    product: str
    channel: str
    units: int
    unit_price: float
    unit_cost: float

    @property
    def revenue(self) -> float:
        return round(self.units * self.unit_price, 2)

    @property
    def cost(self) -> float:
        return round(self.units * self.unit_cost, 2)

    @property
    def margin(self) -> float:
        return round(self.revenue - self.cost, 2)

    @property
    def month(self) -> str:
        return self.date.strftime("%Y-%m")


@dataclass
class LoadReport:
    """What the loader did, in the same spirit as the scraper's QA report."""

    path: str = ""
    rows_read: int = 0
    rows_accepted: int = 0
    rejected: list = field(default_factory=list)
    columns: tuple = ()

    @property
    def rows_rejected(self) -> int:
        return len(self.rejected)

    @property
    def clean(self) -> bool:
        return not self.rejected

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "rows_read": self.rows_read,
            "rows_accepted": self.rows_accepted,
            "rows_rejected": self.rows_rejected,
            "clean": self.clean,
            "rejected": self.rejected,
        }


@dataclass
class DataSet:
    sales: list = field(default_factory=list)
    report: LoadReport = field(default_factory=LoadReport)

    def __len__(self) -> int:
        return len(self.sales)

    @property
    def months(self) -> list:
        return sorted({sale.month for sale in self.sales})

    def values(self, dimension: str) -> list:
        return sorted({getattr(sale, dimension) for sale in self.sales})


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%Y/%m/%d")


def parse_date(raw: str) -> date:
    text = (raw or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise RowError(f"date {raw!r} is not one of {', '.join(_DATE_FORMATS)}")


def parse_number(raw: str, field_name: str, integer: bool = False) -> float:
    """Accepts the shapes a real export produces: '1,250.00', ' 12 ', '(30)'."""
    text = (raw or "").strip().replace(",", "").replace(" ", "")
    if not text:
        raise RowError(f"{field_name} is empty")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        value = float(text)
    except ValueError:
        raise RowError(f"{field_name} {raw!r} is not a number") from None
    if negative:
        value = -value
    if integer:
        if value != int(value):
            raise RowError(f"{field_name} {raw!r} must be a whole number")
        return int(value)
    return value


def parse_row(row: dict, line: int) -> Sale:
    missing = [name for name in REQUIRED_COLUMNS if not (row.get(name) or "").strip()]
    if missing:
        raise RowError(f"missing {', '.join(missing)}")

    units = parse_number(row["units"], "units", integer=True)
    if units <= 0:
        raise RowError(f"units must be greater than zero, got {units}")

    unit_price = parse_number(row["unit_price"], "unit_price")
    unit_cost = parse_number(row["unit_cost"], "unit_cost")
    if unit_price < 0 or unit_cost < 0:
        raise RowError("unit_price and unit_cost cannot be negative")

    return Sale(
        date=parse_date(row["date"]),
        region=row["region"].strip(),
        product=row["product"].strip(),
        channel=row["channel"].strip(),
        units=int(units),
        unit_price=unit_price,
        unit_cost=unit_cost,
    )


def load_csv(path, strict: bool = False) -> DataSet:
    """Read the CSV into a DataSet. `strict` raises on the first bad row."""
    path = Path(path)
    report = LoadReport(path=str(path))
    sales = []

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        report.columns = tuple(reader.fieldnames or ())
        missing = [name for name in REQUIRED_COLUMNS if name not in report.columns]
        if missing:
            raise RowError(
                f"{path} is missing the column(s): {', '.join(missing)}. "
                f"Found: {', '.join(report.columns) or 'nothing'}"
            )

        for line, row in enumerate(reader, start=2):
            report.rows_read += 1
            try:
                sales.append(parse_row(row, line))
            except RowError as exc:
                if strict:
                    raise RowError(f"line {line}: {exc}") from None
                report.rejected.append({"line": line, "reason": str(exc), "row": dict(row)})

    report.rows_accepted = len(sales)
    return DataSet(sales=sales, report=report)
