import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from canadian_macro.catalog import get_dataset
from canadian_macro.sources.boc import parse_valet_series
from canadian_macro.sources.types import Observation, Status
from canadian_macro.store.db import connect, init_db, series_table_name
from canadian_macro.store.ingest import ingest_observations, save_raw

DATASET = get_dataset("boc_policy_rate")
FIXTURE = Path(__file__).parent.parent / "fixtures" / "boc_policy_rate.json"
FETCHED_AT = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
SERIES_TABLE = series_table_name(DATASET.id, DATASET.identifier)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "test.sqlite")
    init_db(connection)
    return connection


def _payload(**overrides: str | None) -> bytes:
    """The fixture, with the given {date: value} replacements (None = null value)."""
    data: dict[str, Any] = json.loads(FIXTURE.read_bytes())
    for row in data["observations"]:
        if row["d"] in overrides:
            value = overrides[row["d"]]
            row[DATASET.identifier] = {"v": value} if value is not None else {}
    return json.dumps(data).encode()


def _ingest(
    conn: sqlite3.Connection, content: bytes, raw_dir: Path, fetched_at: datetime = FETCHED_AT
) -> tuple[int | None, int]:
    observations = parse_valet_series(json.loads(content), DATASET)
    raw_path = save_raw(raw_dir, DATASET, content)
    result = ingest_observations(
        conn,
        DATASET,
        observations,
        raw_path=raw_path,
        content_hash=hashlib.sha256(content).hexdigest(),
        release_date=max(o.period for o in observations),
        fetched_at=fetched_at,
    )
    return result.fetch_id, result.rows_added


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


# --- save_raw -----------------------------------------------------------------------------


def test_save_raw_writes_bytes_unchanged(tmp_path: Path) -> None:
    content = FIXTURE.read_bytes()
    path = save_raw(tmp_path / "raw", DATASET, content)
    assert path.read_bytes() == content
    assert path.is_relative_to(tmp_path / "raw" / DATASET.id)


def test_save_raw_same_bytes_same_path_and_different_bytes_never_overwrite(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    first = save_raw(raw_dir, DATASET, b'{"a": 1}')
    assert save_raw(raw_dir, DATASET, b'{"a": 1}') == first
    second = save_raw(raw_dir, DATASET, b'{"a": 2}')
    assert second != first
    assert first.read_bytes() == b'{"a": 1}'
    assert second.read_bytes() == b'{"a": 2}'


def test_save_raw_refuses_to_overwrite_a_corrupted_existing_file(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    path = save_raw(raw_dir, DATASET, b"original")
    path.write_bytes(b"tampered")
    with pytest.raises(FileExistsError):
        save_raw(raw_dir, DATASET, b"original")
    assert path.read_bytes() == b"tampered"


# --- ingest -------------------------------------------------------------------------------


def test_ingest_records_fetch_and_extracts(conn: sqlite3.Connection, tmp_path: Path) -> None:
    content = FIXTURE.read_bytes()
    fetch_id, added = _ingest(conn, content, tmp_path / "raw")

    assert added == 3
    log = conn.execute("SELECT * FROM core_data_fetch_log").fetchall()
    assert len(log) == 1
    assert log[0]["id"] == fetch_id
    assert log[0]["dataset_id"] == DATASET.id
    assert log[0]["content_hash"] == hashlib.sha256(content).hexdigest()
    assert log[0]["release_date"] == "2026-11-11"
    assert log[0]["fetched_at"] == "2026-11-12T15:00:00+00:00"
    assert Path(log[0]["raw_path"]).read_bytes() == content

    rows = conn.execute(
        "SELECT * FROM core_data_raw_extracts WHERE period = '2026-11-11'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["series"] == DATASET.identifier
    assert rows[0]["value"] == "2.50"  # exact decimal string, trailing zero kept
    assert rows[0]["value_num"] == 2.5
    assert rows[0]["status"] == "ok"
    assert rows[0]["is_current"] == 1


def test_ingest_builds_per_series_table(conn: sqlite3.Connection, tmp_path: Path) -> None:
    _ingest(conn, FIXTURE.read_bytes(), tmp_path / "raw")
    assert _count(conn, SERIES_TABLE) == 3
    row = conn.execute(
        f'SELECT * FROM "{SERIES_TABLE}" WHERE period = ?', ("2026-11-11",)
    ).fetchone()
    assert (row["value"], row["value_num"], row["status"], row["is_current"]) == (
        "2.50",
        2.5,
        "ok",
        1,
    )
    extract = conn.execute(
        "SELECT * FROM core_data_raw_extracts WHERE id = ?", (row["extract_id"],)
    ).fetchone()
    assert extract["period"] == "2026-11-11"


def test_rerun_with_identical_data_adds_nothing(conn: sqlite3.Connection, tmp_path: Path) -> None:
    content = FIXTURE.read_bytes()
    first_id, _ = _ingest(conn, content, tmp_path / "raw")
    second_id, added = _ingest(conn, content, tmp_path / "raw", FETCHED_AT.replace(hour=16))

    assert first_id is not None
    assert second_id is None
    assert added == 0
    assert _count(conn, "core_data_fetch_log") == 1
    assert _count(conn, "core_data_raw_extracts") == 3
    assert _count(conn, SERIES_TABLE) == 3


def test_revision_keeps_both_versions_and_flips_is_current(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    raw_dir = tmp_path / "raw"
    _ingest(conn, FIXTURE.read_bytes(), raw_dir)
    _ingest(conn, _payload(**{"2026-11-11": "2.75"}), raw_dir, FETCHED_AT.replace(hour=16))

    for table in ("core_data_raw_extracts", SERIES_TABLE):
        rows = conn.execute(
            f'SELECT value, is_current FROM "{table}" WHERE period = ? ORDER BY fetch_id',
            ("2026-11-11",),
        ).fetchall()
        assert [(r["value"], r["is_current"]) for r in rows] == [("2.50", 0), ("2.75", 1)]
        # exactly one current row per period
        current = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE is_current = 1').fetchone()
        assert current[0] == 3


def test_older_row_values_are_never_overwritten(conn: sqlite3.Connection, tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    _ingest(conn, FIXTURE.read_bytes(), raw_dir)
    before = conn.execute(
        "SELECT id, period, value, value_num, status FROM core_data_raw_extracts ORDER BY id"
    ).fetchall()
    _ingest(conn, _payload(**{"2026-11-11": "2.75"}), raw_dir, FETCHED_AT.replace(hour=16))
    after = conn.execute(
        "SELECT id, period, value, value_num, status FROM core_data_raw_extracts "
        "WHERE id <= ? ORDER BY id",
        (before[-1]["id"],),
    ).fetchall()
    assert [tuple(r) for r in after] == [tuple(r) for r in before]


def test_reverting_to_earlier_data_is_recorded_as_a_new_fetch(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    raw_dir = tmp_path / "raw"
    original = FIXTURE.read_bytes()
    _ingest(conn, original, raw_dir)
    _ingest(conn, _payload(**{"2026-11-11": "2.75"}), raw_dir, FETCHED_AT.replace(hour=16))
    third_id, added = _ingest(conn, original, raw_dir, FETCHED_AT.replace(hour=17))

    assert third_id is not None and added == 3
    assert _count(conn, "core_data_fetch_log") == 3
    current = conn.execute(
        "SELECT value FROM core_data_raw_extracts WHERE period = '2026-11-11' AND is_current = 1"
    ).fetchall()
    assert [r["value"] for r in current] == ["2.50"]


def test_missing_value_is_stored_as_null_with_status(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    _ingest(conn, _payload(**{"2026-11-10": None}), tmp_path / "raw")
    row = conn.execute(
        "SELECT value, value_num, status FROM core_data_raw_extracts WHERE period = '2026-11-10'"
    ).fetchone()
    assert (row["value"], row["value_num"], row["status"]) == (None, None, "missing")


def test_failed_ingest_rolls_back_completely(conn: sqlite3.Connection, tmp_path: Path) -> None:
    duplicate = [
        Observation(DATASET.id, date(2026, 11, 11), Decimal("2.50"), Status.OK),
        Observation(DATASET.id, date(2026, 11, 11), Decimal("2.75"), Status.OK),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        ingest_observations(
            conn,
            DATASET,
            duplicate,
            raw_path=tmp_path / "x.json",
            content_hash="abc",
            release_date=date(2026, 11, 11),
            fetched_at=FETCHED_AT,
        )
    assert _count(conn, "core_data_fetch_log") == 0
    assert _count(conn, "core_data_raw_extracts") == 0


def test_observation_for_another_dataset_is_rejected(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    stray = [Observation("cpi_all_items_canada", date(2026, 11, 11), Decimal(1), Status.OK)]
    with pytest.raises(ValueError, match="dataset"):
        ingest_observations(
            conn,
            DATASET,
            stray,
            raw_path=tmp_path / "x.json",
            content_hash="abc",
            release_date=date(2026, 11, 11),
            fetched_at=FETCHED_AT,
        )
    assert _count(conn, "core_data_fetch_log") == 0
