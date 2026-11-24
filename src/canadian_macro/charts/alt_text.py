"""Plain-language description of a line chart, for screen readers and the exported package.

Pure: no I/O. Every figure in the text is copied from the stored values, never rounded or
recomputed, so the description can never disagree with the chart.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from canadian_macro.catalog import Dataset
from canadian_macro.sources.types import Observation


def build_alt_text(
    dataset: Dataset, observations: Sequence[Observation], release_date: date
) -> str:
    """Describe the chart of ``observations`` in a few sentences.

    Raises ``ValueError`` if an observation belongs to another dataset, or if none has a value.
    """
    for obs in observations:
        if obs.dataset_id != dataset.id:
            raise ValueError(f"observation for dataset {obs.dataset_id!r}, expected {dataset.id!r}")

    present = sorted(
        ((obs.period, obs.value) for obs in observations if obs.value is not None),
        key=lambda point: point[0],
    )
    if not present:
        raise ValueError(f"dataset {dataset.id!r} has no values to describe")

    missing = len(observations) - len(present)
    lowest = min(present, key=lambda point: point[1])  # first one wins a tie
    highest = max(present, key=lambda point: point[1])
    latest = present[-1]

    def show(point: tuple[date, Decimal]) -> str:
        period, value = point
        return f"{format(value, 'f')} {dataset.units} on {period.isoformat()}"

    first_day, last_day = present[0][0].isoformat(), latest[0].isoformat()
    sentences = [
        f"Line chart: {dataset.title}.",
        f"{len(present)} observations from {first_day} to {last_day}.",
        f"Latest {show(latest)}; lowest {show(lowest)}; highest {show(highest)}.",
    ]
    if missing:
        sentences.append(f"{missing} missing observations are not drawn.")
    sentences.append(f"{dataset.attribution} Data release date: {release_date.isoformat()}.")
    return " ".join(sentences)
