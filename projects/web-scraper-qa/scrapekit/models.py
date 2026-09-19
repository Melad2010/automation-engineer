"""The record shape and the field rules the QA report checks against."""

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class FieldSpec:
    """One column of the dataset, plus what "present" means for it.

    required: a row missing this field is reported as incomplete, never guessed.
    """

    name: str
    required: bool = False
    description: str = ""


DATASET_FIELDS = (
    FieldSpec("name", required=True, description="Organisation name as published"),
    FieldSpec("category", required=True, description="Sector label from the source"),
    FieldSpec("city", required=False, description="City, when the source states one"),
    FieldSpec("website", required=False, description="Public website, checked for shape"),
    FieldSpec("email", required=False, description="Contact email, when published"),
    FieldSpec("source_url", required=True, description="Page this row was read from"),
)


@dataclass
class Record:
    """One row of the delivered dataset.

    Every row carries the URL it came from, so any value can be traced back to
    the page that published it. Missing values stay empty on purpose: a gap is
    reported in the QA sheet rather than filled with a guess.
    """

    name: str = ""
    category: str = ""
    city: str = ""
    website: str = ""
    email: str = ""
    source_url: str = ""
    notes: list = field(default_factory=list)

    def key(self) -> str:
        """Identity used for de-duplication: name + city, case and space folded."""
        return " ".join(f"{self.name} {self.city}".lower().split())

    def missing_required(self) -> list:
        return [f.name for f in DATASET_FIELDS if f.required and not getattr(self, f.name, "")]

    def missing_optional(self) -> list:
        return [f.name for f in DATASET_FIELDS if not f.required and not getattr(self, f.name, "")]

    def as_row(self) -> dict:
        data = asdict(self)
        data["notes"] = "; ".join(self.notes)
        return data
