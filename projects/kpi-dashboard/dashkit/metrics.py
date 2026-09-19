"""The numbers on the dashboard, computed here so they can be tested.

Every figure the workbook displays is also computed in this module, and the
tests assert the two agree. A KPI nobody can reproduce outside the spreadsheet
is a KPI nobody can check.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KPI:
    label: str
    value: float
    previous: Optional[float] = None
    unit: str = ""

    @property
    def delta(self) -> Optional[float]:
        if self.previous is None:
            return None
        return round(self.value - self.previous, 2)

    @property
    def delta_percent(self) -> Optional[float]:
        """Change against the previous period, or None when there is no base.

        A previous period of zero has no percentage change — reporting "+100%"
        or "infinite" there is how a dashboard starts lying.
        """
        if self.previous is None or self.previous == 0:
            return None
        return round((self.value - self.previous) / abs(self.previous) * 100, 2)


@dataclass
class Series:
    """One labelled set of values — a chart's worth of data."""

    name: str
    labels: list = field(default_factory=list)
    values: list = field(default_factory=list)

    def as_pairs(self):
        return list(zip(self.labels, self.values))


def _sum(sales, attribute: str) -> float:
    return round(sum(getattr(sale, attribute) for sale in sales), 2)


def by_month(sales, attribute: str = "revenue") -> Series:
    months = sorted({sale.month for sale in sales})
    values = [
        _sum([sale for sale in sales if sale.month == month], attribute) for month in months
    ]
    return Series(name=f"{attribute} by month", labels=months, values=values)


def by_dimension(sales, dimension: str, attribute: str = "revenue") -> Series:
    keys = sorted({getattr(sale, dimension) for sale in sales})
    values = [
        _sum([sale for sale in sales if getattr(sale, dimension) == key], attribute)
        for key in keys
    ]
    return Series(name=f"{attribute} by {dimension}", labels=keys, values=values)


def top_n(sales, dimension: str, attribute: str = "revenue", count: int = 5) -> Series:
    series = by_dimension(sales, dimension, attribute)
    ranked = sorted(series.as_pairs(), key=lambda pair: pair[1], reverse=True)[:count]
    return Series(
        name=f"top {count} {dimension} by {attribute}",
        labels=[label for label, _ in ranked],
        values=[value for _, value in ranked],
    )


def summarise(sales, month: Optional[str] = None) -> list:
    """The KPI cards. `month` compares that month against the one before it.

    With no month, the cards cover everything and carry no comparison, because
    a total has nothing to be compared against.
    """
    months = sorted({sale.month for sale in sales})
    if month is None:
        current, previous = sales, []
        base = None
    else:
        if month not in months:
            raise ValueError(f"{month} is not in the data. Available: {', '.join(months)}")
        index = months.index(month)
        current = [sale for sale in sales if sale.month == month]
        previous = (
            [sale for sale in sales if sale.month == months[index - 1]] if index > 0 else []
        )
        base = months[index - 1] if index > 0 else None

    def paired(attribute):
        return _sum(current, attribute), (_sum(previous, attribute) if base else None)

    revenue, revenue_before = paired("revenue")
    margin, margin_before = paired("margin")
    units, units_before = paired("units")

    # Kept unrounded: rounding a ratio to two decimals and *then* taking the
    # change against the previous month moves the reported swing by a few
    # hundredths of a point. The workbook computes it from the full-precision
    # ratio, so this does too, and only the display rounds.
    margin_percent = margin / revenue * 100 if revenue else 0.0
    margin_percent_before = (
        margin_before / revenue_before * 100 if base and revenue_before else None
    )
    order_value = round(revenue / len(current), 2) if current else 0.0
    order_value_before = (
        round(revenue_before / len(previous), 2) if base and previous else None
    )

    return [
        KPI("Revenue", revenue, revenue_before, "currency"),
        KPI("Margin", margin, margin_before, "currency"),
        KPI("Margin %", margin_percent, margin_percent_before, "percent"),
        KPI("Units", units, units_before, "number"),
        KPI("Orders", len(current), len(previous) if base else None, "number"),
        KPI("Average order value", order_value, order_value_before, "currency"),
    ]
