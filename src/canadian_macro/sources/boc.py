"""Bank of Canada Valet parser. Pure: raw JSON in, observations out, no I/O."""

import re
from datetime import date
from decimal import Decimal
from typing import Any

from canadian_macro.catalog import Dataset
from canadian_macro.sources.types import Observation, ParseError, Status

# Plain decimals only. Rejects NaN, Infinity and exponent forms that Decimal() would accept.
_DECIMAL = re.compile(r"-?\d+(\.\d+)?")
_EMPTY = frozenset({"", "''", '""'})


def parse_valet_series(payload: Any, dataset: Dataset) -> list[Observation]:
    """Pure: raw Valet JSON -> observations. Raises ParseError on unexpected shape.

    A null, absent or empty-string value is a ``missing`` observation (value None), not an error.
    A present, non-empty value that is not a plain decimal is malformed and raises.
    """
    if dataset.source != "boc":
        raise ParseError(f"dataset {dataset.id!r} is not a Bank of Canada dataset")
    if not isinstance(payload, dict):
        raise ParseError(f"payload must be an object, got {type(payload).__name__}")
    rows = payload.get("observations")
    if not isinstance(rows, list):
        raise ParseError("payload 'observations' must be a list")
    return [_parse_row(row, dataset) for row in rows]


def _parse_row(row: Any, dataset: Dataset) -> Observation:
    if not isinstance(row, dict):
        raise ParseError(f"observation must be an object, got {type(row).__name__}")
    period = _parse_date(row.get("d"))
    entry = row.get(dataset.identifier)
    if entry is not None and not isinstance(entry, dict):
        raise ParseError(f"{dataset.identifier} entry on {period} must be an object")
    value = _parse_value(entry.get("v") if entry else None, period)
    status = Status.OK if value is not None else Status.MISSING
    return Observation(dataset.id, period, value, status)


def _parse_date(raw: Any) -> date:
    if not isinstance(raw, str):
        raise ParseError(f"observation date must be a string, got {raw!r}")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ParseError(f"unparseable observation date: {raw!r}") from None


def _parse_value(raw: Any, period: date) -> Decimal | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ParseError(f"value on {period} must be a string, got {raw!r}")
    text = raw.strip()
    if text in _EMPTY:
        return None
    if not _DECIMAL.fullmatch(text):
        raise ParseError(f"value on {period} is not a decimal: {raw!r}")
    return Decimal(text)
