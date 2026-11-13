"""Dataset registry. Code, not a database table: ``dataset_id`` columns are validated against it.

Attribution texts are drafts from ``docs/sources.md`` (T0). The StatCan wording is finalised in T7
after reading the StatCan Open Licence page.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Dataset:
    id: str
    source: str  # "statcan" | "boc"
    identifier: str  # StatCan table number or BoC Valet series id
    title: str
    units: str
    scale_factor: int  # power of ten the published values are multiplied by (0 = as published)
    frequency: str
    licence_id: str
    attribution: str


CATALOG: dict[str, Dataset] = {
    dataset.id: dataset
    for dataset in (
        Dataset(
            id="cpi_all_items_canada",
            source="statcan",
            identifier="18-10-0004-01",
            title="Consumer Price Index (CPI), all-items, Canada",
            # UNVERIFIED base period: confirm from the table's metadata when T8 parses a fixture.
            units="index (2002=100)",
            scale_factor=0,
            frequency="monthly",
            licence_id="statcan-open-licence",
            attribution=(
                "Source: Statistics Canada, Table 18-10-0004-01. "
                "Contains information licensed under the Statistics Canada Open Licence. "
                "Any derived values (such as year-over-year change) are calculated by this project."
            ),
        ),
        Dataset(
            id="boc_policy_rate",
            source="boc",
            identifier="V39079",  # Confirmed in T4: Valet label "Target for the overnight rate".
            title="Bank of Canada policy interest rate (target for the overnight rate)",
            units="percent",
            scale_factor=0,
            frequency="daily",
            licence_id="boc-terms-of-use",
            attribution=(
                "Source: Bank of Canada, Valet API, series V39079. "
                "Figures are reproduced as published; any derived values are calculated "
                "by this project."
            ),
        ),
    )
}


def get_dataset(dataset_id: str) -> Dataset:
    """Return the catalog entry, or raise ``KeyError`` for an unknown id."""
    try:
        return CATALOG[dataset_id]
    except KeyError:
        raise KeyError(f"unknown dataset id: {dataset_id!r}") from None
