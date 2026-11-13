import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from canadian_macro.catalog import get_dataset
from canadian_macro.sources.boc import parse_valet_series
from canadian_macro.sources.types import Observation, ParseError, Status

FIXTURE = Path(__file__).parent.parent / "fixtures" / "boc_policy_rate.json"
DATASET = get_dataset("boc_policy_rate")
SERIES = DATASET.identifier


def payload_with(observations: Any) -> dict[str, Any]:
    return {"terms": {}, "seriesDetail": {}, "observations": observations}


def obs(day: str, value: Any = "2.50") -> dict[str, Any]:
    return {"d": day, SERIES: {"v": value}}


def test_fixture_parses_to_observations() -> None:
    payload = json.loads(FIXTURE.read_text())

    result = parse_valet_series(payload, DATASET)

    assert result == [
        Observation("boc_policy_rate", date(2026, 11, 11), Decimal("2.50"), Status.OK),
        Observation("boc_policy_rate", date(2026, 11, 10), Decimal("2.50"), Status.OK),
        Observation("boc_policy_rate", date(2026, 11, 9), Decimal("2.50"), Status.OK),
    ]


def test_value_is_exact_decimal_not_float() -> None:
    [result] = parse_valet_series(payload_with([obs("2026-01-02", "2.75")]), DATASET)

    assert isinstance(result.value, Decimal)
    assert str(result.value) == "2.75"


@pytest.mark.parametrize("empty", ["", "''", '""', "   ", None])
def test_empty_or_null_value_is_missing(empty: str | None) -> None:
    # "''" and '""' are literal quote characters, treated as empty like "".
    [result] = parse_valet_series(payload_with([obs("2026-01-02", empty)]), DATASET)

    assert result.value is None
    assert result.status is Status.MISSING


def test_observation_without_series_entry_is_missing() -> None:
    [result] = parse_valet_series(payload_with([{"d": "2026-01-02"}]), DATASET)

    assert result.value is None
    assert result.status is Status.MISSING


def test_series_entry_without_v_key_is_missing() -> None:
    [result] = parse_valet_series(payload_with([{"d": "2026-01-02", SERIES: {}}]), DATASET)

    assert result.value is None
    assert result.status is Status.MISSING


def test_missing_value_does_not_drop_or_alter_neighbours() -> None:
    result = parse_valet_series(
        payload_with([obs("2026-01-01", "2.50"), obs("2026-01-02", ""), obs("2026-01-03", "2.25")]),
        DATASET,
    )

    assert [o.status for o in result] == [Status.OK, Status.MISSING, Status.OK]
    assert [o.value for o in result] == [Decimal("2.50"), None, Decimal("2.25")]


def test_empty_observation_list_returns_empty_list() -> None:
    assert parse_valet_series(payload_with([]), DATASET) == []


@pytest.mark.parametrize("bad", ["abc", "2.5.0", "NaN", "Infinity", "1e999"])
def test_non_decimal_value_raises(bad: str) -> None:
    with pytest.raises(ParseError):
        parse_valet_series(payload_with([obs("2026-01-02", bad)]), DATASET)


@pytest.mark.parametrize("bad", [2.5, 2, True, ["2.5"], {"x": 1}])
def test_non_string_value_raises(bad: Any) -> None:
    with pytest.raises(ParseError):
        parse_valet_series(payload_with([obs("2026-01-02", bad)]), DATASET)


@pytest.mark.parametrize("payload", [[], "text", None, 42])
def test_non_dict_payload_raises(payload: Any) -> None:
    with pytest.raises(ParseError):
        parse_valet_series(payload, DATASET)


@pytest.mark.parametrize("observations", [None, {}, "x", 7])
def test_observations_not_a_list_raises(observations: Any) -> None:
    with pytest.raises(ParseError):
        parse_valet_series(payload_with(observations), DATASET)


def test_missing_observations_key_raises() -> None:
    with pytest.raises(ParseError):
        parse_valet_series({"terms": {}}, DATASET)


@pytest.mark.parametrize("bad_obs", ["x", None, 3, ["d"]])
def test_observation_not_a_dict_raises(bad_obs: Any) -> None:
    with pytest.raises(ParseError):
        parse_valet_series(payload_with([bad_obs]), DATASET)


@pytest.mark.parametrize("day", ["not-a-date", "2026-13-01", "", None, 20260102])
def test_unparseable_date_raises(day: Any) -> None:
    with pytest.raises(ParseError):
        parse_valet_series(payload_with([obs(day)]), DATASET)


def test_missing_date_key_raises() -> None:
    with pytest.raises(ParseError):
        parse_valet_series(payload_with([{SERIES: {"v": "2.50"}}]), DATASET)


def test_series_entry_not_a_dict_raises() -> None:
    with pytest.raises(ParseError):
        parse_valet_series(payload_with([{"d": "2026-01-02", SERIES: "2.50"}]), DATASET)


def test_non_boc_dataset_raises() -> None:
    with pytest.raises(ParseError):
        parse_valet_series(payload_with([]), get_dataset("cpi_all_items_canada"))
