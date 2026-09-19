"""Loads and validates catalog.json.

A catalogue with a typo in it is the most common way a quote tool goes wrong
quietly, so every lookup raises rather than returning a default.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "catalog.json"


class CatalogError(LookupError):
    """Raised for an unknown product or option code, with the valid codes listed."""


@dataclass(frozen=True)
class Option:
    code: str
    name: str
    price: float
    cost: float


@dataclass(frozen=True)
class Product:
    code: str
    name: str
    list_price: float
    cost: float
    lead_time_days: int
    options: dict = field(default_factory=dict)

    def option(self, code: str) -> Option:
        try:
            return self.options[code]
        except KeyError:
            raise CatalogError(
                f"{self.code} has no option {code!r}. Available: "
                f"{', '.join(sorted(self.options)) or 'none'}"
            ) from None


@dataclass(frozen=True)
class QuantityBreak:
    min_quantity: int
    discount_percent: float


@dataclass
class Catalog:
    currency: str
    vat_percent: float
    quote_valid_days: int
    margin_floor_percent: float
    line_decimals: int
    total_decimals: int
    quantity_breaks: tuple
    customer_tiers: dict
    products: dict

    @classmethod
    def load(cls, path=None) -> "Catalog":
        path = Path(path) if path else DEFAULT_CATALOG
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, data: dict) -> "Catalog":
        products = {}
        for entry in data["products"]:
            options = {
                option["code"]: Option(
                    option["code"], option["name"], float(option["price"]), float(option["cost"])
                )
                for option in entry.get("options", [])
            }
            products[entry["code"]] = Product(
                code=entry["code"],
                name=entry["name"],
                list_price=float(entry["list_price"]),
                cost=float(entry["cost"]),
                lead_time_days=int(entry.get("lead_time_days", 0)),
                options=options,
            )

        breaks = tuple(
            sorted(
                (
                    QuantityBreak(int(b["min_quantity"]), float(b["discount_percent"]))
                    for b in data["quantity_breaks"]
                ),
                key=lambda b: b.min_quantity,
            )
        )
        if not breaks or breaks[0].min_quantity != 1:
            raise CatalogError("quantity_breaks must start at a minimum quantity of 1")

        rounding = data.get("rounding", {})
        return cls(
            currency=data.get("currency", "USD"),
            vat_percent=float(data.get("vat_percent", 0.0)),
            quote_valid_days=int(data.get("quote_valid_days", 30)),
            margin_floor_percent=float(data.get("margin_floor_percent", 0.0)),
            line_decimals=int(rounding.get("line_decimals", 2)),
            total_decimals=int(rounding.get("total_decimals", 2)),
            quantity_breaks=breaks,
            customer_tiers={k: float(v) for k, v in data.get("customer_tiers", {}).items()},
            products=products,
        )

    def product(self, code: str) -> Product:
        try:
            return self.products[code]
        except KeyError:
            raise CatalogError(
                f"Unknown product {code!r}. Available: {', '.join(sorted(self.products))}"
            ) from None

    def tier_discount(self, tier: str) -> float:
        try:
            return self.customer_tiers[tier]
        except KeyError:
            raise CatalogError(
                f"Unknown customer tier {tier!r}. Available: "
                f"{', '.join(sorted(self.customer_tiers))}"
            ) from None

    def quantity_discount(self, quantity: int) -> float:
        """The discount for a quantity: the highest break the quantity reaches."""
        discount = 0.0
        for item in self.quantity_breaks:
            if quantity >= item.min_quantity:
                discount = item.discount_percent
        return discount
