"""KPI dashboard toolkit: load, validate, aggregate, build the workbook."""

from .model import Sale, DataSet, LoadReport, load_csv, RowError
from .metrics import KPI, Series, summarise, by_month, by_dimension, top_n

__all__ = [
    "Sale",
    "DataSet",
    "LoadReport",
    "load_csv",
    "RowError",
    "KPI",
    "Series",
    "summarise",
    "by_month",
    "by_dimension",
    "top_n",
]
