"""The pricing engine — the one place the arithmetic is decided.

Rules, in the order they are applied to every line:

1. Unit list price  = product list price + the price of each selected option.
2. Unit cost        = product cost + the cost of each selected option.
3. Discount         = quantity break + customer tier + any manual discount,
                      added together.
4. Margin floor     = the discount is capped so the net unit price never falls
                      below `unit_cost / (1 - margin_floor)`. The cap keeps
                      full precision — rounding it up would breach the very
                      floor it enforces. A capped line carries a note; it is
                      never silently repriced.
5. Net unit price   = unit list x (1 - discount), rounded to `line_decimals`.
6. Line total       = net unit price x quantity, rounded to `line_decimals`.

VAT is applied once to the subtotal, not per line, so the total matches what an
accountant would compute by hand.
"""

import zlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

from .catalog import Catalog, CatalogError


class PricingError(ValueError):
    """Raised for an input a quote cannot be built from (bad quantity, etc.)."""


def _round(value: float, decimals: int) -> float:
    """Round half away from zero, the way a price list is read by a human.

    Python's built-in round() is banker's rounding: round(2.675, 2) is 2.67.
    A customer reading a quote expects 2.68, and so does the VBA version.
    """
    factor = 10 ** decimals
    shifted = value * factor
    # The tiny epsilon absorbs binary representation error (2.675 * 100 = 267.49999...).
    epsilon = 1e-9 if shifted >= 0 else -1e-9
    return int(shifted + (0.5 if shifted >= 0 else -0.5) + epsilon) / factor


@dataclass
class LineRequest:
    """What the salesperson asked for, before any pricing is applied."""

    product_code: str
    quantity: int = 1
    options: Sequence = field(default_factory=tuple)
    manual_discount_percent: float = 0.0


@dataclass
class QuoteLine:
    product_code: str
    description: str
    quantity: int
    options: tuple
    unit_list_price: float
    unit_cost: float
    quantity_discount_percent: float
    tier_discount_percent: float
    manual_discount_percent: float
    applied_discount_percent: float
    unit_net_price: float
    line_total: float
    lead_time_days: int
    notes: tuple = ()

    @property
    def margin_percent(self) -> float:
        if not self.unit_net_price:
            return 0.0
        return _round((self.unit_net_price - self.unit_cost) / self.unit_net_price * 100, 2)

    @property
    def discount_was_capped(self) -> bool:
        return any("margin floor" in note for note in self.notes)


@dataclass
class Quote:
    reference: str
    customer: str
    tier: str
    currency: str
    quote_date: date
    valid_until: date
    lines: list
    subtotal: float
    vat_percent: float
    vat_amount: float
    total: float
    lead_time_days: int

    @property
    def total_cost(self) -> float:
        return _round(sum(line.unit_cost * line.quantity for line in self.lines), 2)

    @property
    def margin_percent(self) -> float:
        if not self.subtotal:
            return 0.0
        return _round((self.subtotal - self.total_cost) / self.subtotal * 100, 2)

    @property
    def capped_lines(self) -> list:
        return [line for line in self.lines if line.discount_was_capped]


def _max_discount_for_margin(unit_list: float, unit_cost: float, floor_percent: float) -> float:
    """The largest discount that still leaves `floor_percent` margin."""
    if unit_list <= 0:
        return 100.0
    if floor_percent >= 100:
        raise PricingError("margin_floor_percent must be below 100")
    min_net = unit_cost / (1 - floor_percent / 100.0)
    return max(0.0, (1 - min_net / unit_list) * 100.0)


def price_line(catalog: Catalog, request: LineRequest, tier: str) -> QuoteLine:
    if int(request.quantity) != request.quantity or request.quantity < 1:
        raise PricingError(
            f"Quantity for {request.product_code} must be a whole number of 1 or more, "
            f"got {request.quantity!r}"
        )
    if request.manual_discount_percent < 0:
        raise PricingError("A manual discount cannot be negative")

    product = catalog.product(request.product_code)

    seen = []
    for code in request.options:
        if code in seen:
            raise PricingError(f"Option {code!r} is listed twice on {product.code}")
        seen.append(code)
    options = tuple(product.option(code) for code in seen)

    unit_list = product.list_price + sum(option.price for option in options)
    unit_cost = product.cost + sum(option.cost for option in options)

    quantity_discount = catalog.quantity_discount(request.quantity)
    tier_discount = catalog.tier_discount(tier)
    requested = quantity_discount + tier_discount + request.manual_discount_percent

    notes = []
    ceiling = _max_discount_for_margin(unit_list, unit_cost, catalog.margin_floor_percent)
    applied = requested
    if requested > ceiling:
        # Kept at full precision on purpose: rounding the cap up by even 0.005%
        # pushes the line back under the floor it was capped to protect. Only
        # the note rounds, because only the note is read by a human.
        applied = ceiling
        notes.append(
            f"Discount capped at {ceiling:.2f}% by the {catalog.margin_floor_percent:.1f}% "
            f"margin floor (requested {requested:.2f}%)"
        )

    unit_net = _round(unit_list * (1 - applied / 100.0), catalog.line_decimals)
    line_total = _round(unit_net * request.quantity, catalog.line_decimals)

    description = product.name
    if options:
        description += " + " + ", ".join(option.name for option in options)

    return QuoteLine(
        product_code=product.code,
        description=description,
        quantity=request.quantity,
        options=tuple(option.code for option in options),
        unit_list_price=_round(unit_list, catalog.line_decimals),
        unit_cost=_round(unit_cost, catalog.line_decimals),
        quantity_discount_percent=quantity_discount,
        tier_discount_percent=tier_discount,
        manual_discount_percent=request.manual_discount_percent,
        applied_discount_percent=applied,
        unit_net_price=unit_net,
        line_total=line_total,
        lead_time_days=product.lead_time_days,
        notes=tuple(notes),
    )


def _reference(customer: str, quote_date: date) -> str:
    """A stable reference: the same customer and date always give the same one.

    zlib.crc32 rather than hash(), because Python randomises string hashes per
    process and a quote reference that changes between runs is a support call.
    """
    digest = zlib.crc32(customer.strip().lower().encode("utf-8")) % 10000
    return f"Q-{quote_date:%Y%m%d}-{digest:04d}"


def price_quote(
    catalog: Catalog,
    requests: Sequence,
    customer: str,
    tier: str = "standard",
    reference: str = "",
    quote_date: Optional[date] = None,
) -> Quote:
    """Price a whole quote. Raises rather than guessing on any bad input."""
    if not requests:
        raise PricingError("A quote needs at least one line")

    catalog.tier_discount(tier)  # fail fast on an unknown tier, before any pricing
    quote_date = quote_date or date.today()
    lines = [price_line(catalog, request, tier) for request in requests]

    subtotal = _round(sum(line.line_total for line in lines), catalog.total_decimals)
    vat_amount = _round(subtotal * catalog.vat_percent / 100.0, catalog.total_decimals)
    total = _round(subtotal + vat_amount, catalog.total_decimals)

    return Quote(
        reference=reference or _reference(customer, quote_date),
        customer=customer,
        tier=tier,
        currency=catalog.currency,
        quote_date=quote_date,
        valid_until=quote_date + timedelta(days=catalog.quote_valid_days),
        lines=lines,
        subtotal=subtotal,
        vat_percent=catalog.vat_percent,
        vat_amount=vat_amount,
        total=total,
        lead_time_days=max((line.lead_time_days for line in lines), default=0),
    )
