"""Quote generator: one catalogue, one set of pricing rules, three front ends.

The rules live in catalog.json. The Python engine here is the reference
implementation; the VBA module and the Apps Script version implement the same
arithmetic so a quote costs the same whichever tool produced it.
"""

from .catalog import Catalog, Product, Option, CatalogError
from .pricing import Quote, QuoteLine, LineRequest, price_quote, PricingError

__all__ = [
    "Catalog",
    "Product",
    "Option",
    "CatalogError",
    "Quote",
    "QuoteLine",
    "LineRequest",
    "price_quote",
    "PricingError",
]
