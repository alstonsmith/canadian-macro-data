"""Quarantine for downloaded payloads that failed to parse or validate (SPEC "Quarantine").

The exact bytes are kept for audit, never stored as raw data and never read back by the app.
Each dataset keeps only its newest ``QUARANTINE_KEEP`` payloads.
"""

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from canadian_macro.catalog import Dataset
from canadian_macro.store.files import write_atomic

QUARANTINE_KEEP = 5

# <UTC timestamp, sortable>_<first 16 hex of sha256>.json
_ENTRY = re.compile(r"\d{8}T\d{12}Z_([0-9a-f]{16})\.json")


def quarantine_payload(
    quarantine_dir: Path,
    dataset: Dataset,
    content: bytes,
    reason: str,
    *,
    now: datetime,
    keep: int = QUARANTINE_KEEP,
) -> Path:
    """Keep ``content`` unchanged, plus a ``.txt`` sidecar with the reason, then prune old entries.

    Identical bytes replace their earlier entry, so a payload that keeps failing the same way
    stays one entry and cannot push out older, different evidence.
    """
    if keep < 1:
        raise ValueError("keep must be at least 1")
    digest = hashlib.sha256(content).hexdigest()[:16]
    folder = quarantine_dir / dataset.id
    for old in _entries(folder):
        if old.name.endswith(f"_{digest}.json"):
            _remove(old)

    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = folder / f"{stamp}_{digest}.json"
    write_atomic(path, content)
    note = f"quarantined at: {now.astimezone(UTC).isoformat()}\ndataset: {dataset.id}\nreason: {reason}\n"
    write_atomic(path.with_suffix(".txt"), note.encode())

    for stale in _entries(folder)[:-keep]:
        _remove(stale)
    return path


def _entries(folder: Path) -> list[Path]:
    """Quarantine payload files in the folder, oldest first. Other files are ignored."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if _ENTRY.fullmatch(p.name))


def _remove(payload: Path) -> None:
    payload.unlink(missing_ok=True)
    payload.with_suffix(".txt").unlink(missing_ok=True)
