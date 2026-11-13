"""Save raw downloads unchanged and ingest parsed observations into SQLite.

Rows are append-only (SPEC "Revisions and ``is_current``"): each fetch inserts its own rows, and
the only update ever made to an existing row is flipping ``is_current`` from 1 to 0 when a later
fetch supplies the same (series, period).
"""

import hashlib
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from canadian_macro.catalog import Dataset
from canadian_macro.sources.types import Observation
from canadian_macro.store.db import ensure_series_table, parse_value_num
from canadian_macro.store.files import write_atomic


@dataclass(frozen=True)
class IngestResult:
    fetch_id: int | None  # None when the fetch was skipped as unchanged
    rows_added: int  # rows written to core_data_raw_extracts
    skipped: bool


def save_raw(raw_dir: Path, dataset: Dataset, content: bytes, suffix: str = ".json") -> Path:
    """Write ``content`` unchanged to ``<raw_dir>/<dataset id>/<sha256><suffix>`` and return the path.

    Content-addressed: identical bytes map to the same file, different bytes never replace an
    existing one. An existing file whose bytes no longer match raises rather than being repaired.
    """
    digest = hashlib.sha256(content).hexdigest()
    path = raw_dir / dataset.id / f"{digest}{suffix}"
    if path.exists():
        if path.read_bytes() != content:
            raise FileExistsError(f"raw file {path} exists but its bytes differ; not overwriting")
        return path
    write_atomic(path, content)
    return path


def ingest_observations(
    conn: sqlite3.Connection,
    dataset: Dataset,
    observations: Sequence[Observation],
    *,
    raw_path: Path,
    content_hash: str,
    release_date: date,
    fetched_at: datetime,
) -> IngestResult:
    """Record one fetch and its observations. Atomic: all rows are written or none are.

    Skips (adds nothing) when the dataset's latest fetch has the same ``content_hash``, so a
    re-run on identical data is a no-op. Data that reverts to an earlier version is not skipped,
    since the latest fetch differs.
    """
    for obs in observations:
        if obs.dataset_id != dataset.id:
            raise ValueError(f"observation for dataset {obs.dataset_id!r}, expected {dataset.id!r}")

    latest = conn.execute(
        "SELECT content_hash FROM core_data_fetch_log WHERE dataset_id = ? ORDER BY id DESC LIMIT 1",
        (dataset.id,),
    ).fetchone()
    if latest is not None and latest["content_hash"] == content_hash:
        return IngestResult(None, 0, skipped=True)

    series = dataset.identifier  # one series per dataset for the BoC; StatCan will pass many
    table = ensure_series_table(conn, dataset.id, series)
    with conn:  # one transaction: commits on success, rolls back on any exception
        fetch_id = _insert_fetch(conn, dataset, raw_path, content_hash, release_date, fetched_at)
        for obs in observations:
            value = None if obs.value is None else str(obs.value)
            value_num = parse_value_num(value)
            extract_id = conn.execute(
                "INSERT INTO core_data_raw_extracts "
                "(dataset_id, fetch_id, series, period, value, value_num, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    dataset.id,
                    fetch_id,
                    series,
                    obs.period.isoformat(),
                    value,
                    value_num,
                    obs.status,
                ),
            ).lastrowid
            conn.execute(
                f'INSERT INTO "{table}" '
                "(extract_id, fetch_id, period, value, value_num, status) VALUES (?, ?, ?, ?, ?, ?)",
                (extract_id, fetch_id, obs.period.isoformat(), value, value_num, obs.status),
            )
        _supersede_older_rows(conn, dataset.id, series, table, fetch_id)
    return IngestResult(fetch_id, len(observations), skipped=False)


def _insert_fetch(
    conn: sqlite3.Connection,
    dataset: Dataset,
    raw_path: Path,
    content_hash: str,
    release_date: date,
    fetched_at: datetime,
) -> int:
    cursor = conn.execute(
        "INSERT INTO core_data_fetch_log "
        "(dataset_id, fetched_at, raw_path, content_hash, release_date) VALUES (?, ?, ?, ?, ?)",
        (
            dataset.id,
            fetched_at.isoformat(),
            str(raw_path),
            content_hash,
            release_date.isoformat(),
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _supersede_older_rows(
    conn: sqlite3.Connection, dataset_id: str, series: str, table: str, fetch_id: int
) -> None:
    """Flip ``is_current`` to 0 on earlier rows that this fetch re-supplied (same series, period)."""
    conn.execute(
        "UPDATE core_data_raw_extracts SET is_current = 0 "
        "WHERE dataset_id = ? AND series = ? AND fetch_id < ? AND is_current = 1 "
        "AND EXISTS (SELECT 1 FROM core_data_raw_extracts AS newer "
        "            WHERE newer.fetch_id = ? AND newer.series = core_data_raw_extracts.series "
        "            AND newer.period = core_data_raw_extracts.period)",
        (dataset_id, series, fetch_id, fetch_id),
    )
    conn.execute(
        f'UPDATE "{table}" SET is_current = 0 '
        "WHERE fetch_id < ? AND is_current = 1 "
        f'AND EXISTS (SELECT 1 FROM "{table}" AS newer '
        f'            WHERE newer.fetch_id = ? AND newer.period = "{table}".period)',
        (fetch_id, fetch_id),
    )
