"""Write a publish package (without a narrative) for one dataset from the stored data.

The package lives in ``<outputs_dir>/<dataset id>/<release date>/`` and holds the chart as PNG
and SVG, its alt text, a CSV of the plotted values, ``sources.md`` and a manifest. Everything is
built from the latest stored fetch; values come from the exact decimal strings in the database,
never from the float convenience column.

A narrative, its AI disclosure and the approval gate arrive with the narrative tasks (T14, T15).
"""

import csv
import io
import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from canadian_macro.catalog import Dataset
from canadian_macro.charts.alt_text import build_alt_text
from canadian_macro.charts.line import write_line_chart
from canadian_macro.export.sources_md import build_sources_md
from canadian_macro.sources.types import Observation, Status
from canadian_macro.store.files import write_atomic

CSV_HEADER = ("period", "value", "status")


def _latest_fetch(conn: sqlite3.Connection, dataset: Dataset) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        "SELECT id, fetched_at, content_hash, release_date FROM core_data_fetch_log "
        "WHERE dataset_id = ? ORDER BY id DESC LIMIT 1",
        (dataset.id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no stored fetch for dataset {dataset.id!r}; run refresh first")
    return row


def _current_observations(conn: sqlite3.Connection, dataset: Dataset) -> list[Observation]:
    """The latest known value for every period (``is_current = 1``), oldest first."""
    rows = conn.execute(
        "SELECT period, value, status FROM core_data_raw_extracts "
        "WHERE dataset_id = ? AND series = ? AND is_current = 1 ORDER BY period",
        (dataset.id, dataset.identifier),
    ).fetchall()
    return [
        Observation(
            dataset_id=dataset.id,
            period=date.fromisoformat(row["period"]),
            value=None if row["value"] is None else Decimal(row["value"]),
            status=Status(row["status"]),
        )
        for row in rows
    ]


def _data_csv(observations: list[Observation]) -> str:
    """CSV of the plotted values. A missing value is an empty cell, never a filled-in number."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for obs in observations:
        value = "" if obs.value is None else format(obs.value, "f")
        writer.writerow((obs.period.isoformat(), value, obs.status.value))
    return buffer.getvalue()


def export_package(conn: sqlite3.Connection, dataset: Dataset, outputs_dir: Path) -> Path:
    """Write the package for the dataset's latest fetch and return its folder.

    The folder is named by the data release date, so exporting the same data again rewrites the
    same files with identical contents. Raises ``ValueError`` if nothing has been fetched, or
    if the dataset has no licence statement yet. Both checks run before anything is written.
    """
    fetch = _latest_fetch(conn, dataset)
    release_date = date.fromisoformat(fetch["release_date"])
    observations = _current_observations(conn, dataset)

    # Everything that can fail is built in memory first, so a refusal leaves no folder behind.
    alt_text = build_alt_text(dataset, observations, release_date)
    sources_md = build_sources_md(
        dataset,
        fetch_id=fetch["id"],
        release_date=release_date,
        fetched_at=datetime.fromisoformat(fetch["fetched_at"]),
        content_hash=fetch["content_hash"],
    )
    data_csv = _data_csv(observations)

    folder = outputs_dir / dataset.id / release_date.isoformat()
    chart = write_line_chart(dataset, observations, release_date, folder)
    write_atomic(folder / "alt_text.txt", (alt_text + "\n").encode())
    write_atomic(folder / "data.csv", data_csv.encode())
    write_atomic(folder / "sources.md", sources_md.encode())

    manifest = {
        "dataset_id": dataset.id,
        "fetch_id": fetch["id"],
        "fetched_at": fetch["fetched_at"],
        "release_date": release_date.isoformat(),
        "content_hash": fetch["content_hash"],
        "files": sorted([chart.png.name, chart.svg.name, "alt_text.txt", "data.csv", "sources.md"]),
    }
    write_atomic(folder / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return folder
