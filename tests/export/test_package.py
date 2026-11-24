import csv
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from canadian_macro.catalog import Dataset
from canadian_macro.charts.alt_text import build_alt_text
from canadian_macro.export.package import export_package
from canadian_macro.sources.boc import parse_valet_series

RELEASE = date(2026, 11, 11)  # latest observation in the saved sample response


@pytest.fixture
def stored(ingest: Callable[..., int], make_payload: Callable[..., bytes]) -> int:
    return ingest(make_payload())


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_writes_the_package_folder_named_by_dataset_and_release_date(
    conn: sqlite3.Connection, dataset: Dataset, stored: int, tmp_path: Path
) -> None:
    folder = export_package(conn, dataset, tmp_path / "outputs")

    assert folder == tmp_path / "outputs" / "boc_policy_rate" / "2026-11-11"
    assert sorted(path.name for path in folder.iterdir()) == [
        "alt_text.txt",
        "boc_policy_rate.png",
        "boc_policy_rate.svg",
        "data.csv",
        "manifest.json",
        "sources.md",
    ]


def test_writes_no_narrative_yet(
    conn: sqlite3.Connection, dataset: Dataset, stored: int, tmp_path: Path
) -> None:
    folder = export_package(conn, dataset, tmp_path / "outputs")
    assert not (folder / "narrative.md").exists()


def test_chart_files_are_real_images_that_carry_the_attribution(
    conn: sqlite3.Connection, dataset: Dataset, stored: int, tmp_path: Path
) -> None:
    folder = export_package(conn, dataset, tmp_path / "outputs")

    assert (folder / "boc_policy_rate.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    svg = (folder / "boc_policy_rate.svg").read_text(encoding="utf-8")
    assert "Bank of Canada, Valet API, series V39079" in svg
    assert "Data release date: 2026-11-11" in svg


def test_csv_holds_the_exact_stored_values(
    conn: sqlite3.Connection, dataset: Dataset, stored: int, tmp_path: Path
) -> None:
    folder = export_package(conn, dataset, tmp_path / "outputs")

    stored_rows = conn.execute(
        "SELECT period, value, status FROM core_data_raw_extracts ORDER BY period"
    ).fetchall()
    rows = _read_csv(folder / "data.csv")
    assert rows == [
        {"period": r["period"], "value": r["value"], "status": r["status"]} for r in stored_rows
    ]
    assert len(rows) == 3


def test_csv_leaves_a_missing_value_empty_and_keeps_its_status(
    conn: sqlite3.Connection,
    dataset: Dataset,
    tmp_path: Path,
    ingest: Callable[..., int],
    make_payload: Callable[..., bytes],
) -> None:
    ingest(make_payload(**{"2026-11-10": None}))

    folder = export_package(conn, dataset, tmp_path / "outputs")

    gap = next(row for row in _read_csv(folder / "data.csv") if row["period"] == "2026-11-10")
    assert gap == {"period": "2026-11-10", "value": "", "status": "missing"}


def test_alt_text_file_matches_the_alt_text_builder(
    conn: sqlite3.Connection,
    dataset: Dataset,
    stored: int,
    tmp_path: Path,
    make_payload: Callable[..., bytes],
) -> None:
    folder = export_package(conn, dataset, tmp_path / "outputs")

    observations = parse_valet_series(json.loads(make_payload()), dataset)
    expected = build_alt_text(dataset, observations, RELEASE)
    assert (folder / "alt_text.txt").read_text(encoding="utf-8").strip() == expected


def test_manifest_records_the_fetch_and_release_date(
    conn: sqlite3.Connection, dataset: Dataset, stored: int, tmp_path: Path
) -> None:
    folder = export_package(conn, dataset, tmp_path / "outputs")

    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    fetch = conn.execute("SELECT * FROM core_data_fetch_log WHERE id = ?", (stored,)).fetchone()
    assert manifest["dataset_id"] == "boc_policy_rate"
    assert manifest["fetch_id"] == stored
    assert manifest["release_date"] == "2026-11-11"
    assert manifest["fetched_at"] == fetch["fetched_at"]
    assert manifest["content_hash"] == fetch["content_hash"]
    assert sorted(manifest["files"]) == [
        "alt_text.txt",
        "boc_policy_rate.png",
        "boc_policy_rate.svg",
        "data.csv",
        "sources.md",
    ]


def test_sources_md_names_the_fetch_the_package_came_from(
    conn: sqlite3.Connection, dataset: Dataset, stored: int, tmp_path: Path
) -> None:
    folder = export_package(conn, dataset, tmp_path / "outputs")

    text = (folder / "sources.md").read_text(encoding="utf-8")
    assert f"Fetch id: {stored}" in text
    assert "V39079" in text


def test_after_a_revision_the_package_uses_the_latest_value_and_the_latest_fetch(
    conn: sqlite3.Connection,
    dataset: Dataset,
    stored: int,
    tmp_path: Path,
    ingest: Callable[..., int],
    make_payload: Callable[..., bytes],
) -> None:
    revised = ingest(
        make_payload(**{"2026-11-11": "9.99"}),
        fetched_at=datetime(2026, 11, 13, 15, 0, tzinfo=UTC),
    )

    folder = export_package(conn, dataset, tmp_path / "outputs")

    rows = _read_csv(folder / "data.csv")
    assert [row["value"] for row in rows if row["period"] == "2026-11-11"] == ["9.99"]
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fetch_id"] == revised


def test_exporting_twice_gives_identical_files(
    conn: sqlite3.Connection, dataset: Dataset, stored: int, tmp_path: Path
) -> None:
    folder = export_package(conn, dataset, tmp_path / "outputs")
    first = {path.name: path.read_bytes() for path in folder.iterdir()}

    export_package(conn, dataset, tmp_path / "outputs")

    assert {path.name: path.read_bytes() for path in folder.iterdir()} == first


def test_refuses_when_nothing_has_been_fetched_and_writes_nothing(
    conn: sqlite3.Connection, dataset: Dataset, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="no stored fetch"):
        export_package(conn, dataset, tmp_path / "outputs")
    assert not (tmp_path / "outputs").exists()
