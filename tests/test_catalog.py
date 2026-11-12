import dataclasses

import pytest

from canadian_macro.catalog import CATALOG, Dataset, get_dataset


def test_catalog_has_cpi_and_boc_policy_rate() -> None:
    assert {"cpi_all_items_canada", "boc_policy_rate"} <= set(CATALOG)


def test_catalog_keys_match_dataset_ids() -> None:
    for key, dataset in CATALOG.items():
        assert key == dataset.id


@pytest.mark.parametrize("dataset", list(CATALOG.values()), ids=list(CATALOG))
def test_every_dataset_field_is_filled(dataset: Dataset) -> None:
    for field in dataclasses.fields(dataset):
        value = getattr(dataset, field.name)
        if isinstance(value, str):
            assert value.strip(), f"{dataset.id}.{field.name} is empty"
    assert isinstance(dataset.scale_factor, int)


def test_cpi_entry() -> None:
    cpi = get_dataset("cpi_all_items_canada")
    assert cpi.source == "statcan"
    assert cpi.identifier == "18-10-0004-01"
    assert cpi.frequency == "monthly"


def test_boc_entry() -> None:
    boc = get_dataset("boc_policy_rate")
    assert boc.source == "boc"
    assert boc.identifier == "V39079"
    assert "Bank of Canada" in boc.attribution


def test_attribution_never_implies_endorsement() -> None:
    for dataset in CATALOG.values():
        assert "endorse" not in dataset.attribution.lower()


def test_unknown_dataset_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        get_dataset("nope")


def test_dataset_is_immutable() -> None:
    dataset = get_dataset("boc_policy_rate")
    with pytest.raises(dataclasses.FrozenInstanceError):
        dataset.units = "changed"  # type: ignore[misc]
