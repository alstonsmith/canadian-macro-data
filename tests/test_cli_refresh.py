import itertools
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from canadian_macro.__main__ import main

FIXTURE = Path(__file__).parent / "fixtures" / "boc_policy_rate.json"
VALET_URL = "https://www.bankofcanada.ca/valet/observations/V39079/json"


def _transport(
    body: bytes, status: int = 200, seen: list[str] | None = None
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        return httpx.Response(status, content=body)

    return httpx.MockTransport(handler)


_ticks = itertools.count()


def _clock() -> datetime:
    """Strictly increasing fake time, so quarantine ordering is deterministic."""
    return datetime(2026, 11, 13, tzinfo=UTC) + timedelta(seconds=next(_ticks))


def _run(data_dir: Path, transport: httpx.MockTransport) -> int:
    argv = ["refresh", "--source", "boc", "--data-dir", str(data_dir)]
    return main(argv, transport=transport, sleep=lambda _seconds: None, now=_clock)


def _quarantined(data_dir: Path) -> list[Path]:
    return sorted((data_dir / "quarantine" / "boc_policy_rate").glob("*.json"))


def _db(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir / "canadian_macro.sqlite")
    conn.row_factory = sqlite3.Row
    return conn


def test_refresh_boc_stores_raw_file_unchanged_and_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = FIXTURE.read_bytes()
    seen: list[str] = []
    assert _run(tmp_path, _transport(content, seen=seen)) == 0

    assert seen == [VALET_URL]
    raw_files = [p for p in (tmp_path / "raw").rglob("*") if p.is_file()]
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == content  # byte-identical to the download

    conn = _db(tmp_path)
    fetch = conn.execute("SELECT * FROM core_data_fetch_log").fetchall()
    assert len(fetch) == 1
    assert fetch[0]["release_date"] == "2026-11-11"
    assert conn.execute("SELECT COUNT(*) FROM core_data_raw_extracts").fetchone()[0] == 3
    assert "3" in capsys.readouterr().out


def test_refresh_boc_twice_adds_no_duplicates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    content = FIXTURE.read_bytes()
    assert _run(tmp_path, _transport(content)) == 0
    capsys.readouterr()
    assert _run(tmp_path, _transport(content)) == 0
    assert "unchanged" in capsys.readouterr().out

    conn = _db(tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM core_data_fetch_log").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM core_data_raw_extracts").fetchone()[0] == 3
    assert len([p for p in (tmp_path / "raw").rglob("*") if p.is_file()]) == 1


def test_refresh_boc_picks_up_a_revision(tmp_path: Path) -> None:
    content = FIXTURE.read_bytes()
    assert _run(tmp_path, _transport(content)) == 0
    revised = json.loads(content)
    revised["observations"][0]["V39079"]["v"] = "2.75"
    assert _run(tmp_path, _transport(json.dumps(revised).encode())) == 0

    rows = (
        _db(tmp_path)
        .execute(
            "SELECT value, is_current FROM core_data_raw_extracts "
            "WHERE period = '2026-11-11' ORDER BY fetch_id"
        )
        .fetchall()
    )
    assert [(r["value"], r["is_current"]) for r in rows] == [("2.50", 0), ("2.75", 1)]


def test_refresh_boc_malformed_payload_stores_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.loads(FIXTURE.read_bytes())
    payload["observations"][0]["V39079"]["v"] = "abc"
    assert _run(tmp_path, _transport(json.dumps(payload).encode())) == 1

    assert "not a decimal" in capsys.readouterr().err
    assert not (tmp_path / "raw").exists()  # not kept as raw data
    assert not (tmp_path / "canadian_macro.sqlite").exists()  # and no database rows


def test_malformed_payload_is_quarantined_byte_for_byte_with_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.loads(FIXTURE.read_bytes())
    payload["observations"][0]["V39079"]["v"] = "abc"
    content = json.dumps(payload).encode()
    assert _run(tmp_path, _transport(content)) == 1

    (kept,) = _quarantined(tmp_path)
    assert kept.read_bytes() == content
    assert "not a decimal" in kept.with_suffix(".txt").read_text()
    assert str(kept) in capsys.readouterr().err  # tells the user where to look


def test_unparseable_json_and_empty_observations_are_quarantined_too(tmp_path: Path) -> None:
    assert _run(tmp_path, _transport(b"<html>maintenance</html>")) == 1
    assert _run(tmp_path, _transport(b'{"observations": []}')) == 1
    assert [p.read_bytes() for p in _quarantined(tmp_path)] == [
        b"<html>maintenance</html>",
        b'{"observations": []}',
    ]


def test_only_the_last_five_malformed_payloads_are_kept(tmp_path: Path) -> None:
    for i in range(7):
        assert _run(tmp_path, _transport(f'{{"observations": "bad {i}"}}'.encode())) == 1
    kept = [p.read_bytes() for p in _quarantined(tmp_path)]
    assert kept == [f'{{"observations": "bad {i}"}}'.encode() for i in range(2, 7)]


def test_good_and_failed_http_responses_are_not_quarantined(tmp_path: Path) -> None:
    assert _run(tmp_path, _transport(FIXTURE.read_bytes())) == 0
    assert _run(tmp_path, _transport(b"nope", status=404)) == 1
    assert not (tmp_path / "quarantine").exists()


def test_refresh_boc_http_failure_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path, _transport(b"nope", status=404)) == 1
    assert "404" in capsys.readouterr().err


def test_refresh_boc_empty_observations_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path, _transport(b'{"observations": []}')) == 1
    assert "no observations" in capsys.readouterr().err


def test_refresh_requires_a_known_source() -> None:
    with pytest.raises(SystemExit):
        main(["refresh", "--source", "nope"])
