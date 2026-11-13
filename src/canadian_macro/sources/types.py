"""Types shared by the source parsers. Pure data: no I/O."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class ParseError(ValueError):
    """A source response has an unexpected shape, or a present value can't be trusted."""


class Status(StrEnum):
    """Closed set of status flags; the lowercase value is what gets stored."""

    OK = "ok"  # a normal reported value
    MISSING = "missing"  # the source reported no value (null, absent or empty)
    SUPPRESSED = "suppressed"  # the source withheld the value
    ESTIMATED = "estimated"  # the source flags the value as an estimate
    REVISED = "revised"  # the source flags the value as revised


@dataclass(frozen=True)
class Observation:
    dataset_id: str
    period: date
    value: Decimal | None  # None = missing/suppressed; never imputed
    status: Status
