"""Command line entry point: ``python -m canadian_macro refresh --source boc``."""

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

from canadian_macro.catalog import get_dataset
from canadian_macro.sources.boc import parse_valet_series
from canadian_macro.sources.client import FetchClient, FetchError
from canadian_macro.sources.types import ParseError
from canadian_macro.store.db import connect, init_db
from canadian_macro.store.ingest import ingest_observations, save_raw

BOC_DATASET_ID = "boc_policy_rate"
VALET_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json"
DEFAULT_DATA_DIR = Path("data")
DB_NAME = "canadian_macro.sqlite"


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run the CLI and return the exit code. ``transport`` and ``sleep`` are test seams."""
    parser = argparse.ArgumentParser(prog="canadian_macro")
    commands = parser.add_subparsers(dest="command", required=True)
    refresh = commands.add_parser("refresh", help="fetch a source and store it")
    refresh.add_argument("--source", choices=["boc"], required=True)
    refresh.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args(argv)

    try:
        return refresh_boc(args.data_dir, transport=transport, sleep=sleep)
    except (FetchError, ParseError, ValueError) as exc:
        print(f"refresh failed: {exc}", file=sys.stderr)
        return 1


def refresh_boc(
    data_dir: Path,
    *,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Fetch the policy rate from Valet, keep the raw bytes, and store the observations."""
    dataset = get_dataset(BOC_DATASET_ID)
    with FetchClient(data_dir / "cache", transport=transport, sleep=sleep) as client:
        # An explicit refresh always downloads: a cached copy could hide a same-day change.
        result = client.get(VALET_URL.format(series=dataset.identifier), refresh=True)

    # Parse before saving anything: an untrusted, malformed response leaves no files or rows.
    observations = parse_valet_series(json.loads(result.content), dataset)
    if not observations:
        raise ValueError("Valet response has no observations")
    # Valet publishes no release date, so the latest observation date stands in for it.
    release_date = max(obs.period for obs in observations)

    raw_path = save_raw(data_dir / "raw", dataset, result.content)
    conn = connect(data_dir / DB_NAME)
    try:
        init_db(conn)
        outcome = ingest_observations(
            conn,
            dataset,
            observations,
            raw_path=raw_path,
            content_hash=hashlib.sha256(result.content).hexdigest(),
            release_date=release_date,
            fetched_at=datetime.fromtimestamp(result.fetched_at, tz=UTC),
        )
    finally:
        conn.close()

    if outcome.skipped:
        print(f"{dataset.id}: unchanged since the last fetch; nothing added")
    else:
        print(f"{dataset.id}: stored {outcome.rows_added} observations (release {release_date})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
