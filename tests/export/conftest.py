import hashlib
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from canadian_macro.catalog import Dataset, get_dataset
from canadian_macro.sources.boc import parse_valet_series
from canadian_macro.store.db import connect, init_db
from canadian_macro.store.ingest import ingest_observations, save_raw

FIXTURE = Path(__file__).parent.parent / "fixtures" / "boc_policy_rate.json"
FIRST_FETCH_AT = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


@pytest.fixture
def dataset() -> Dataset:
    return get_dataset("boc_policy_rate")


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(tmp_path / "test.sqlite")
    init_db(connection)
    return connection


def fixture_payload(dataset: Dataset, **overrides: str | None) -> bytes:
    """The saved sample response, with {date: value} replacements (None = no value)."""
    data: dict[str, Any] = json.loads(FIXTURE.read_bytes())
    for row in data["observations"]:
        if row["d"] in overrides:
            value = overrides[row["d"]]
            row[dataset.identifier] = {"v": value} if value is not None else {}
    return json.dumps(data).encode()


@pytest.fixture
def make_payload(dataset: Dataset) -> Callable[..., bytes]:
    """Build a Valet response from the sample, e.g. ``make_payload(**{"2026-11-10": None})``."""
    return lambda **overrides: fixture_payload(dataset, **overrides)


@pytest.fixture
def ingest(conn: sqlite3.Connection, dataset: Dataset, tmp_path: Path) -> Callable[..., int]:
    """Store one fetch the way ``refresh`` does and return its fetch id."""

    def _ingest(content: bytes, fetched_at: datetime = FIRST_FETCH_AT) -> int:
        observations = parse_valet_series(json.loads(content), dataset)
        result = ingest_observations(
            conn,
            dataset,
            observations,
            raw_path=save_raw(tmp_path / "raw", dataset, content),
            content_hash=hashlib.sha256(content).hexdigest(),
            release_date=max(obs.period for obs in observations),
            fetched_at=fetched_at,
        )
        assert result.fetch_id is not None
        return result.fetch_id

    return _ingest
