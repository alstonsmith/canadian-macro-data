"""Text of ``sources.md``: where a dataset came from and on what terms it may be reused.

Pure: no I/O. The licence wording is looked up by the catalog's ``licence_id``. A dataset whose
wording has not been written down yet raises ``ValueError`` instead of getting invented text.
"""

from datetime import date, datetime

from canadian_macro.catalog import Dataset

# Licence statements, keyed by ``Dataset.licence_id``. Source: docs/sources.md (read 2026-11-23).
# There is no entry for "statcan-open-licence": its acknowledgement wording is still to be
# written after the StatCan Open Licence page has been read.
LICENCE_STATEMENTS: dict[str, str] = {
    "boc-terms-of-use": (
        "Bank of Canada terms of use, https://www.bankofcanada.ca/terms/. The Bank permits free "
        "use, copying and distribution of its website content on the condition that it is "
        "credited as the source and that any changes are indicated. This project is not "
        "endorsed by, and is not affiliated with, the Bank of Canada."
    ),
}

# Readable organisation names for the catalog's short source codes.
SOURCE_NAMES: dict[str, str] = {"boc": "Bank of Canada", "statcan": "Statistics Canada"}

# What the release date means for each source, because the sources differ.
RELEASE_DATE_NOTES: dict[str, str] = {
    "boc": (
        "The Bank of Canada publishes no release date for this series, so the date of the "
        "latest observation is used instead."
    ),
}


def build_sources_md(
    dataset: Dataset,
    *,
    fetch_id: int,
    release_date: date,
    fetched_at: datetime,
    content_hash: str,
) -> str:
    """Return the sourcing page for one exported package.

    Raises ``ValueError`` if no licence statement has been written for the dataset's licence.
    """
    licence = LICENCE_STATEMENTS.get(dataset.licence_id)
    if licence is None:
        raise ValueError(
            f"no licence statement written for {dataset.licence_id!r} "
            f"(dataset {dataset.id!r}); add one to LICENCE_STATEMENTS first"
        )
    release_note = RELEASE_DATE_NOTES.get(dataset.source, "")
    lines = [
        f"# Sources: {dataset.title}",
        "",
        "## Where the data comes from",
        "",
        f"- Source: {SOURCE_NAMES.get(dataset.source, dataset.source)}",
        f"- Identifier: {dataset.identifier}",
        f"- Units: {dataset.units}",
        f"- Data release date: {release_date.isoformat()}",
    ]
    if release_note:
        lines.append(f"  - {release_note}")
    lines += [
        "",
        "## Which download this package was built from",
        "",
        f"- Fetch id: {fetch_id}",
        f"- Fetched at: {fetched_at.isoformat()}",
        f"- SHA-256 of the raw download: {content_hash}",
        "",
        "## Attribution",
        "",
        dataset.attribution,
        "",
        "## Licence",
        "",
        licence,
        "",
    ]
    return "\n".join(lines)
