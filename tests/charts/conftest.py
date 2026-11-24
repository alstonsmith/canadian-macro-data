import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from canadian_macro.catalog import Dataset, get_dataset
from canadian_macro.sources.boc import parse_valet_series
from canadian_macro.sources.types import Observation, Status

FIXTURE = Path(__file__).parent.parent / "fixtures" / "boc_policy_rate.json"

# The fixture's last observation is 2026-11-11, and the BoC publishes no release date of its own,
# so the latest observation date is what the store records as the release date.
RELEASE_DATE = date(2026, 11, 11)


@pytest.fixture
def dataset() -> Dataset:
    return get_dataset("boc_policy_rate")


@pytest.fixture
def observations(dataset: Dataset) -> list[Observation]:
    return parse_valet_series(json.loads(FIXTURE.read_bytes()), dataset)


def make_observation(dataset: Dataset, day: int, value: str | None) -> Observation:
    """One November 2026 observation; ``value=None`` is a missing value."""
    return Observation(
        dataset_id=dataset.id,
        period=date(2026, 11, day),
        value=None if value is None else Decimal(value),
        status=Status.MISSING if value is None else Status.OK,
    )
