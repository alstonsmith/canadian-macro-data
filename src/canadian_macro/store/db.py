"""SQLite connection, idempotent schema setup and per-series table helpers."""

import hashlib
import math
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path

from canadian_macro.store.schema import CORE_DDL, SCHEMA_VERSION, SERIES_TABLE_DDL

_SERIES_TABLE_RE = re.compile(r"raw_data_[a-z0-9_]+")
_SLUG_MAX = 40


class SchemaVersionError(RuntimeError):
    """The database was created by a newer version of this app."""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the database with foreign keys enforced (SQLite leaves them off by default)."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the CORE tables if missing. Safe to call repeatedly; never touches existing rows."""
    version: int = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"database schema version {version} is newer than supported {SCHEMA_VERSION}"
        )
    conn.executescript(CORE_DDL)
    if version < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")


def parse_value_num(value: str | None) -> float | None:
    """Best-effort float for analysis convenience. ``None`` when ``value`` is not a plain number.

    The exact decimal string in ``value`` stays the source of truth; never use this for checks.
    """
    if value is None or "_" in value:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    result = float(number)
    return result if math.isfinite(result) else None


def _slug(text: str) -> str:
    """Lowercase, runs of non-alphanumerics collapsed to one ``_``, trimmed, length-capped."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:_SLUG_MAX].strip("_")
    return slug or "x"


def series_table_name(dataset_id: str, series: str) -> str:
    """Safe, unique table name for one series of one dataset.

    Names that are already clean (lowercase alphanumeric words joined by single underscores) stay
    readable: ``raw_data_<dataset>__<series>``. Anything else gets a hash of the exact inputs as a
    third ``__`` part. Clean parts never contain ``__``, so the two forms cannot collide, and
    the hash keeps look-alike inputs (``V1`` / ``v1`` / ``1.2.3`` / ``1_2_3``) apart.
    """
    if not dataset_id.strip() or not series.strip():
        raise ValueError("dataset_id and series must be non-empty")
    base = f"raw_data_{_slug(dataset_id)}__{_slug(series)}"
    if dataset_id == _slug(dataset_id) and series == _slug(series):
        name = base
    else:
        digest = hashlib.sha256(f"{dataset_id}\0{series}".encode()).hexdigest()[:16]
        name = f"{base}__{digest}"
    if not _SERIES_TABLE_RE.fullmatch(name):  # defence in depth: the name goes into DDL text
        raise ValueError(f"unsafe table name {name!r}")
    return name


def ensure_series_table(conn: sqlite3.Connection, dataset_id: str, series: str) -> str:
    """Create the series' ``raw_data_*`` table if missing and return its name."""
    name = series_table_name(dataset_id, series)
    conn.execute(SERIES_TABLE_DDL.format(table=name))
    return name
