import dataclasses
from datetime import date

import pytest
from conftest import RELEASE_DATE, make_observation

from canadian_macro.catalog import Dataset
from canadian_macro.charts.alt_text import build_alt_text
from canadian_macro.sources.types import Observation


def test_alt_text_is_not_empty_and_names_the_dataset(
    dataset: Dataset, observations: list[Observation]
) -> None:
    text = build_alt_text(dataset, observations, RELEASE_DATE)
    assert text.strip()
    assert dataset.title in text


def test_alt_text_states_the_latest_value_by_date_whatever_order_the_data_arrives_in(
    dataset: Dataset,
) -> None:
    # Different values, newest day in the middle of the list, so only a true "latest by date"
    # lookup produces 2.75 (not the first or last item in the list).
    observations = [
        make_observation(dataset, 10, "2.50"),
        make_observation(dataset, 11, "2.75"),
        make_observation(dataset, 9, "2.25"),
    ]
    text = build_alt_text(dataset, observations, RELEASE_DATE)
    assert f"Latest 2.75 {dataset.units} on 2026-11-11" in text


def test_alt_text_states_the_date_range_and_observation_count(dataset: Dataset) -> None:
    observations = [
        make_observation(dataset, 9, "2.25"),
        make_observation(dataset, 10, "2.50"),
        make_observation(dataset, 11, "2.75"),
    ]
    text = build_alt_text(dataset, observations, RELEASE_DATE)
    assert "3 observations" in text
    assert "2026-11-09" in text
    assert "2026-11-11" in text


def test_alt_text_states_the_lowest_and_highest_values_exactly(dataset: Dataset) -> None:
    observations = [
        make_observation(dataset, 9, "2.25"),
        make_observation(dataset, 10, "3.50"),
        make_observation(dataset, 11, "2.75"),
    ]
    text = build_alt_text(dataset, observations, RELEASE_DATE)
    assert f"lowest 2.25 {dataset.units} on 2026-11-09" in text
    assert f"highest 3.50 {dataset.units} on 2026-11-10" in text


def test_alt_text_says_how_many_observations_are_missing_and_not_drawn(dataset: Dataset) -> None:
    observations = [
        make_observation(dataset, 9, "2.25"),
        make_observation(dataset, 10, None),
        make_observation(dataset, 11, "2.75"),
    ]
    text = build_alt_text(dataset, observations, RELEASE_DATE)
    assert "2 observations" in text  # only the two that have values
    assert "1 missing" in text


def test_alt_text_includes_the_source_and_release_date(
    dataset: Dataset, observations: list[Observation]
) -> None:
    text = build_alt_text(dataset, observations, date(2026, 11, 12))
    assert "Bank of Canada" in text
    assert "2026-11-12" in text


def test_alt_text_refuses_a_series_with_no_values(dataset: Dataset) -> None:
    observations = [make_observation(dataset, 9, None), make_observation(dataset, 10, None)]
    with pytest.raises(ValueError, match="no values"):
        build_alt_text(dataset, observations, RELEASE_DATE)


def test_alt_text_refuses_observations_from_another_dataset(
    dataset: Dataset, observations: list[Observation]
) -> None:
    other = dataclasses.replace(dataset, id="some_other_dataset")
    with pytest.raises(ValueError, match="some_other_dataset"):
        build_alt_text(other, observations, RELEASE_DATE)
