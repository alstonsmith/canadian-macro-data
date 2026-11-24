from datetime import UTC, date, datetime

import pytest

from canadian_macro.catalog import get_dataset
from canadian_macro.export.sources_md import build_sources_md

FETCHED_AT = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)
CONTENT_HASH = "ab" * 32


def _boc_text() -> str:
    return build_sources_md(
        get_dataset("boc_policy_rate"),
        fetch_id=7,
        release_date=date(2026, 11, 11),
        fetched_at=FETCHED_AT,
        content_hash=CONTENT_HASH,
    )


def test_names_the_source_identifier_and_units() -> None:
    text = _boc_text()
    assert "- Source: Bank of Canada\n" in text
    assert "V39079" in text
    assert "percent" in text


def test_states_the_release_date_and_explains_where_it_comes_from() -> None:
    text = _boc_text()
    assert "2026-11-11" in text
    # The Bank publishes no release date, so a reader must be told what the date stands for.
    assert "latest observation" in text


def test_records_which_download_the_data_came_from() -> None:
    text = _boc_text()
    assert "Fetch id: 7" in text
    assert "2026-11-12T15:00:00+00:00" in text
    assert CONTENT_HASH in text


def test_includes_the_catalog_attribution_text_unchanged() -> None:
    assert get_dataset("boc_policy_rate").attribution in _boc_text()


def test_states_the_licence_terms_and_that_the_bank_does_not_endorse_this() -> None:
    text = _boc_text()
    assert "https://www.bankofcanada.ca/terms/" in text
    assert "not endorsed" in text


def test_refuses_a_dataset_whose_licence_wording_is_not_yet_written() -> None:
    # StatCan's acknowledgement has not been finalised; inventing one would break the rule
    # against unsourced text.
    with pytest.raises(ValueError, match="statcan-open-licence"):
        build_sources_md(
            get_dataset("cpi_all_items_canada"),
            fetch_id=1,
            release_date=date(2026, 11, 18),
            fetched_at=FETCHED_AT,
            content_hash=CONTENT_HASH,
        )
