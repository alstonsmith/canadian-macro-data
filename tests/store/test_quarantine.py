from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canadian_macro.catalog import get_dataset
from canadian_macro.store.quarantine import QUARANTINE_KEEP, quarantine_payload

BOC = get_dataset("boc_policy_rate")
CPI = get_dataset("cpi_all_items_canada")
T0 = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _payloads(qdir: Path, dataset_id: str) -> list[Path]:
    folder = qdir / dataset_id
    return sorted(p for p in folder.glob("*.json")) if folder.exists() else []


def test_default_limit_is_five() -> None:
    assert QUARANTINE_KEEP == 5


def test_keeps_exact_bytes_and_a_sidecar_with_the_reason(tmp_path: Path) -> None:
    content = b'{"observations": [{"d": "2026-11-11", "V39079": {"v": "abc"}}]}\n'
    path = quarantine_payload(tmp_path, BOC, content, "value is not a decimal", now=T0)

    assert path.read_bytes() == content
    assert path.is_relative_to(tmp_path / BOC.id)
    sidecar = path.with_suffix(".txt")
    text = sidecar.read_text()
    assert "value is not a decimal" in text
    assert "2026-11-13T12:00:00" in text


def test_keeps_only_the_newest_n_and_deletes_sidecars_of_pruned_ones(tmp_path: Path) -> None:
    for i in range(7):
        quarantine_payload(
            tmp_path, BOC, f"bad {i}".encode(), f"reason {i}", now=T0 + timedelta(minutes=i), keep=5
        )

    kept = _payloads(tmp_path, BOC.id)
    assert [p.read_bytes() for p in kept] == [f"bad {i}".encode() for i in range(2, 7)]
    assert len(list((tmp_path / BOC.id).glob("*.txt"))) == 5  # no orphaned sidecars


def test_datasets_are_pruned_independently(tmp_path: Path) -> None:
    for i in range(3):
        quarantine_payload(
            tmp_path, BOC, f"boc {i}".encode(), "r", now=T0 + timedelta(minutes=i), keep=2
        )
    quarantine_payload(tmp_path, CPI, b"cpi", "r", now=T0, keep=2)

    assert len(_payloads(tmp_path, BOC.id)) == 2
    assert len(_payloads(tmp_path, CPI.id)) == 1


def test_identical_bytes_replace_the_earlier_entry_instead_of_adding_another(
    tmp_path: Path,
) -> None:
    quarantine_payload(tmp_path, BOC, b"same", "first", now=T0, keep=5)
    quarantine_payload(tmp_path, BOC, b"other", "r", now=T0 + timedelta(minutes=1), keep=5)
    newest = quarantine_payload(
        tmp_path, BOC, b"same", "second", now=T0 + timedelta(minutes=2), keep=5
    )

    kept = _payloads(tmp_path, BOC.id)
    assert len(kept) == 2
    assert kept[-1] == newest  # the repeat is now the most recent entry
    assert "second" in newest.with_suffix(".txt").read_text()
    assert len(list((tmp_path / BOC.id).glob("*.txt"))) == 2


def test_a_repeating_bad_payload_cannot_evict_older_distinct_evidence(tmp_path: Path) -> None:
    for i in range(3):
        quarantine_payload(
            tmp_path, BOC, f"distinct {i}".encode(), "r", now=T0 + timedelta(minutes=i), keep=4
        )
    for i in range(10):
        quarantine_payload(
            tmp_path, BOC, b"loop", "r", now=T0 + timedelta(hours=1, minutes=i), keep=4
        )

    contents = {p.read_bytes() for p in _payloads(tmp_path, BOC.id)}
    assert contents == {b"distinct 1", b"distinct 2", b"distinct 0", b"loop"}


def test_unrelated_files_in_the_folder_are_left_alone(tmp_path: Path) -> None:
    folder = tmp_path / BOC.id
    folder.mkdir(parents=True)
    (folder / "notes.md").write_text("mine")
    for i in range(3):
        quarantine_payload(
            tmp_path, BOC, f"bad {i}".encode(), "r", now=T0 + timedelta(minutes=i), keep=1
        )
    assert (folder / "notes.md").read_text() == "mine"


def test_keep_must_be_at_least_one(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="keep"):
        quarantine_payload(tmp_path, BOC, b"x", "r", now=T0, keep=0)
