import sqlite3
from pathlib import Path

import pytest

from canadian_macro.store.db import (
    SchemaVersionError,
    connect,
    ensure_series_table,
    init_db,
    parse_value_num,
    series_table_name,
)
from canadian_macro.store.schema import SCHEMA_VERSION


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "test.sqlite")
    init_db(connection)
    return connection


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def _add_fetch(conn: sqlite3.Connection, dataset_id: str = "boc_policy_rate") -> int:
    cur = conn.execute(
        "INSERT INTO core_data_fetch_log"
        " (dataset_id, fetched_at, raw_path, content_hash, release_date)"
        " VALUES (?, '2026-11-12T10:00:00Z', 'data/raw/x.json', 'abc', '2026-11-12')",
        (dataset_id,),
    )
    assert cur.lastrowid is not None
    return cur.lastrowid


def _add_extract(
    conn: sqlite3.Connection,
    fetch_id: int,
    *,
    series: str = "V39079",
    period: str = "2026-11-01",
    value: str | None = "2.25",
    value_num: float | None = 2.25,
    status: str = "ok",
) -> int:
    cur = conn.execute(
        "INSERT INTO core_data_raw_extracts"
        " (dataset_id, fetch_id, series, period, value, value_num, status)"
        " VALUES ('boc_policy_rate', ?, ?, ?, ?, ?, ?)",
        (fetch_id, series, period, value, value_num, status),
    )
    assert cur.lastrowid is not None
    return cur.lastrowid


# --- schema shape -------------------------------------------------------------------------


def test_core_tables_created_and_old_names_absent(conn: sqlite3.Connection) -> None:
    tables = _tables(conn)
    assert {"core_data_fetch_log", "core_data_raw_extracts", "core_narrative"} <= tables
    assert not tables & {"dataset", "fetch", "observation", "core_dataset"}


def test_user_version_is_set(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_init_is_idempotent_and_keeps_data(conn: sqlite3.Connection) -> None:
    fetch_id = _add_fetch(conn)
    _add_extract(conn, fetch_id)
    conn.commit()
    init_db(conn)
    init_db(conn)
    assert conn.execute("SELECT COUNT(*) FROM core_data_raw_extracts").fetchone()[0] == 1


def test_init_refuses_a_newer_schema_version(conn: sqlite3.Connection) -> None:
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(SchemaVersionError):
        init_db(conn)


def test_foreign_keys_are_enforced(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_extract(conn, fetch_id=999)


# --- core_data_raw_extracts ---------------------------------------------------------------


def test_extract_defaults_to_current(conn: sqlite3.Connection) -> None:
    fetch_id = _add_fetch(conn)
    _add_extract(conn, fetch_id)
    assert conn.execute("SELECT is_current FROM core_data_raw_extracts").fetchone()[0] == 1


def test_is_current_only_accepts_zero_or_one(conn: sqlite3.Connection) -> None:
    fetch_id = _add_fetch(conn)
    extract_id = _add_extract(conn, fetch_id)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE core_data_raw_extracts SET is_current = 2 WHERE id = ?", (extract_id,))


def test_same_fetch_series_period_is_unique(conn: sqlite3.Connection) -> None:
    fetch_id = _add_fetch(conn)
    _add_extract(conn, fetch_id)
    with pytest.raises(sqlite3.IntegrityError):
        _add_extract(conn, fetch_id)


def test_revision_in_a_later_fetch_keeps_both_rows(conn: sqlite3.Connection) -> None:
    first, second = _add_fetch(conn), _add_fetch(conn)
    _add_extract(conn, first, value="2.25", value_num=2.25)
    _add_extract(conn, second, value="2.50", value_num=2.5)
    values = conn.execute("SELECT value FROM core_data_raw_extracts ORDER BY fetch_id").fetchall()
    assert [row[0] for row in values] == ["2.25", "2.50"]


def test_missing_value_is_null_with_status(conn: sqlite3.Connection) -> None:
    fetch_id = _add_fetch(conn)
    _add_extract(conn, fetch_id, value=None, value_num=None, status="suppressed")
    row = conn.execute("SELECT value, value_num, status FROM core_data_raw_extracts").fetchone()
    assert tuple(row) == (None, None, "suppressed")


def test_value_num_without_value_is_rejected(conn: sqlite3.Connection) -> None:
    fetch_id = _add_fetch(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _add_extract(conn, fetch_id, value=None, value_num=1.0)


def test_status_is_required(conn: sqlite3.Connection) -> None:
    fetch_id = _add_fetch(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO core_data_raw_extracts (dataset_id, fetch_id, series, period, status)"
            " VALUES ('boc_policy_rate', ?, 'V39079', '2026-11-01', NULL)",
            (fetch_id,),
        )


# --- core_narrative -----------------------------------------------------------------------


def _add_narrative(conn: sqlite3.Connection, fetch_id: int, **overrides: object) -> None:
    columns: dict[str, object] = {
        "dataset_id": "boc_policy_rate",
        "fetch_id": fetch_id,
        "text": "draft",
        "model": "fake",
        "prompt_hash": "h",
        "check_result": "{}",
        "created_at": "2026-11-12T10:00:00Z",
        "updated_at": "2026-11-12T10:00:00Z",
    } | overrides
    names = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    conn.execute(f"INSERT INTO core_narrative ({names}) VALUES ({marks})", tuple(columns.values()))


def test_narrative_defaults_to_draft(conn: sqlite3.Connection) -> None:
    _add_narrative(conn, _add_fetch(conn))
    assert conn.execute("SELECT approval_state FROM core_narrative").fetchone()[0] == "draft"


def test_narrative_rejects_unknown_approval_state(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_narrative(conn, _add_fetch(conn), approval_state="published")


def test_narrative_requires_existing_fetch(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_narrative(conn, fetch_id=999)


# --- value_num ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2.25", 2.25),
        ("-0.5", -0.5),
        ("100", 100.0),
        ("1e3", 1000.0),
        (None, None),
        ("", None),
        ("x", None),
        ("..", None),
        ("nan", None),
        ("inf", None),
        ("1_000", None),
        ("1,5", None),
    ],
)
def test_parse_value_num(raw: str | None, expected: float | None) -> None:
    assert parse_value_num(raw) == expected


# --- per-series RAW_DATA tables -----------------------------------------------------------


def test_series_table_name_is_prefixed_and_safe() -> None:
    name = series_table_name("boc_policy_rate", "V39079")
    assert name.startswith("raw_data_")
    assert name.replace("_", "").isalnum()
    assert name == name.lower()


def test_clean_names_stay_readable() -> None:
    assert series_table_name("boc_policy_rate", "v39079") == "raw_data_boc_policy_rate__v39079"


def test_name_is_deterministic() -> None:
    assert series_table_name("a", "1.2.3") == series_table_name("a", "1.2.3")


def test_names_that_sanitise_alike_stay_distinct() -> None:
    names = {
        series_table_name("cpi", "1.2.3"),
        series_table_name("cpi", "1_2_3"),
        series_table_name("cpi", "1.2-3"),
        series_table_name("cpi", "V1"),
        series_table_name("cpi", "v1"),
    }
    assert len(names) == 5


def test_same_series_in_different_datasets_is_distinct() -> None:
    assert series_table_name("a", "1.1") != series_table_name("b", "1.1")


def test_hostile_series_name_cannot_inject_sql(conn: sqlite3.Connection) -> None:
    before = _tables(conn)
    hostile = 'x"; DROP TABLE core_narrative; --'
    name = ensure_series_table(conn, "boc_policy_rate", hostile)
    assert name.replace("_", "").isalnum()
    assert _tables(conn) == before | {name}


@pytest.mark.parametrize(("dataset_id", "series"), [("", "v1"), ("a", ""), ("a", "   ")])
def test_series_name_must_not_be_empty(dataset_id: str, series: str) -> None:
    with pytest.raises(ValueError):
        series_table_name(dataset_id, series)


def test_ensure_series_table_is_idempotent_and_keeps_rows(conn: sqlite3.Connection) -> None:
    fetch_id = _add_fetch(conn)
    extract_id = _add_extract(conn, fetch_id)
    name = ensure_series_table(conn, "boc_policy_rate", "V39079")
    conn.execute(
        f'INSERT INTO "{name}" (extract_id, fetch_id, period, value, value_num, status)'
        " VALUES (?, ?, '2026-11-01', '2.25', 2.25, 'ok')",
        (extract_id, fetch_id),
    )
    assert ensure_series_table(conn, "boc_policy_rate", "V39079") == name
    assert conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] == 1


def test_series_table_enforces_keys_and_flags(conn: sqlite3.Connection) -> None:
    fetch_id = _add_fetch(conn)
    extract_id = _add_extract(conn, fetch_id)
    name = ensure_series_table(conn, "boc_policy_rate", "V39079")
    insert = (
        f'INSERT INTO "{name}" (extract_id, fetch_id, period, value, value_num, status)'
        " VALUES (?, ?, ?, '2.25', 2.25, 'ok')"
    )
    conn.execute(insert, (extract_id, fetch_id, "2026-11-01"))
    with pytest.raises(sqlite3.IntegrityError):  # duplicate (fetch, period)
        conn.execute(insert, (extract_id, fetch_id, "2026-11-01"))
    with pytest.raises(sqlite3.IntegrityError):  # unknown fetch
        conn.execute(insert, (extract_id, 999, "2026-11-02"))
    row = conn.execute(f'SELECT is_current FROM "{name}"').fetchone()
    assert row[0] == 1
