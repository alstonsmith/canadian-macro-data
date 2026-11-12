"""DDL for the SQLite store. Approved design: SPEC.md "Data model".

SQLite has no schemas, so the two logical schemas are table-name prefixes:
``core_`` (fixed tables) and ``raw_data_`` (one table per series, created on demand).
"""

SCHEMA_VERSION = 1

CORE_DDL = """
CREATE TABLE IF NOT EXISTS core_data_fetch_log (
    id           INTEGER PRIMARY KEY,
    dataset_id   TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    raw_path     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    release_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS core_data_raw_extracts (
    id         INTEGER PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    fetch_id   INTEGER NOT NULL REFERENCES core_data_fetch_log (id),
    series     TEXT NOT NULL,
    period     TEXT NOT NULL,
    value      TEXT,
    value_num  REAL,
    status     TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    UNIQUE (fetch_id, series, period),
    CHECK (value IS NOT NULL OR value_num IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_core_data_raw_extracts_lookup
    ON core_data_raw_extracts (dataset_id, series, period);

CREATE TABLE IF NOT EXISTS core_narrative (
    id               INTEGER PRIMARY KEY,
    dataset_id       TEXT NOT NULL,
    fetch_id         INTEGER NOT NULL REFERENCES core_data_fetch_log (id),
    text             TEXT NOT NULL,
    model            TEXT NOT NULL,
    prompt_hash      TEXT NOT NULL,
    check_result     TEXT NOT NULL,
    checklist_result TEXT,
    approval_state   TEXT NOT NULL DEFAULT 'draft'
                     CHECK (approval_state IN ('draft', 'rejected', 'approved')),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
"""

# ``{table}`` is always a name produced by ``db.series_table_name`` (``[a-z0-9_]`` only).
SERIES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS "{table}" (
    id         INTEGER PRIMARY KEY,
    extract_id INTEGER NOT NULL UNIQUE REFERENCES core_data_raw_extracts (id),
    fetch_id   INTEGER NOT NULL REFERENCES core_data_fetch_log (id),
    period     TEXT NOT NULL,
    value      TEXT,
    value_num  REAL,
    status     TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    UNIQUE (fetch_id, period),
    CHECK (value IS NOT NULL OR value_num IS NULL)
);
"""
