import dataclasses
import math
import re
import struct
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from conftest import RELEASE_DATE, make_observation
from matplotlib.figure import Figure

from canadian_macro.catalog import Dataset
from canadian_macro.charts.alt_text import build_alt_text
from canadian_macro.charts.line import build_line_figure, write_line_chart
from canadian_macro.sources.types import Observation

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _svg_text_pieces(path: Path) -> list[str]:
    """Each separate piece of visible text in the SVG, in drawing order."""
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    return ["".join(el.itertext()) for el in root.iter() if el.tag.endswith("}text")]


def _svg_text(path: Path) -> str:
    """All visible text in the SVG, in drawing order, with whitespace collapsed."""
    return re.sub(r"\s+", " ", " ".join(_svg_text_pieces(path))).strip()


def _svg_all_text(path: Path) -> str:
    """Every piece of text in the SVG file, including hidden metadata such as the description."""
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    return re.sub(r"\s+", " ", " ".join(root.itertext()))


def _drawn_values(figure: Figure) -> list[float]:
    """The y-values of the chart's main line, as plain floats (a missing value is ``nan``)."""
    values: list[float] = np.asarray(figure.axes[0].lines[0].get_ydata(), dtype=float).tolist()
    return values


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])  # the IHDR chunk follows the 8-byte signature
    return int(width), int(height)


def test_writes_a_png_and_an_svg(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    files = write_line_chart(dataset, observations, RELEASE_DATE, tmp_path)
    assert files.png == tmp_path / f"{dataset.id}.png"
    assert files.svg == tmp_path / f"{dataset.id}.svg"
    assert files.png.read_bytes().startswith(PNG_SIGNATURE)
    assert files.svg.read_text(encoding="utf-8").lstrip().startswith(("<?xml", "<svg"))


def test_png_is_large_enough_to_stay_sharp_at_substack_width(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    files = write_line_chart(dataset, observations, RELEASE_DATE, tmp_path)
    width, height = _png_size(files.png)
    assert width >= 1200
    assert width > height  # landscape


def test_creates_the_output_folder_if_it_is_missing(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    files = write_line_chart(dataset, observations, RELEASE_DATE, tmp_path / "a" / "b")
    assert files.png.exists()


def test_svg_shows_title_and_units(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    text = _svg_text(write_line_chart(dataset, observations, RELEASE_DATE, tmp_path).svg)
    assert dataset.title in text
    assert dataset.units in text.lower()


def test_svg_shows_the_full_source_and_licence_attribution_line(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    text = _svg_text(write_line_chart(dataset, observations, RELEASE_DATE, tmp_path).svg)
    assert re.sub(r"\s+", " ", dataset.attribution) in text


def test_svg_shows_the_data_release_date(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    text = _svg_text(write_line_chart(dataset, observations, RELEASE_DATE, tmp_path).svg)
    assert "release date: 2026-11-11" in text.lower()


def test_svg_has_no_wording_that_implies_government_endorsement(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    text = _svg_text(write_line_chart(dataset, observations, RELEASE_DATE, tmp_path).svg).lower()
    for phrase in ("endorse", "approved by", "sponsored", "in partnership", "certified"):
        assert phrase not in text


def test_the_time_axis_shows_the_real_observation_dates(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    # The release date is set far from the data so a "2026" in the text can only come from the
    # axis. A wrong date origin would show 1990 or 2050 labels instead.
    files = write_line_chart(dataset, observations, date(2030, 1, 1), tmp_path)
    assert "2026" in _svg_text(files.svg)


@pytest.mark.parametrize(
    "title",
    [
        "Bank of Canada policy interest rate (target for the overnight rate)",
        (
            "Population estimates by age group and sex, quarterly, Canada, "
            "provinces and territories, seasonally adjusted, thousands of persons"
        ),
    ],
    ids=["the real catalog title", "a very long title"],
)
def test_no_text_runs_off_the_edge_of_the_image(
    dataset: Dataset, observations: list[Observation], title: str
) -> None:
    # The SVG text tests cannot see clipping: text can be present in the file and still be cut
    # off by the image edge. This measures where each piece of text is actually drawn.
    figure = build_line_figure(
        dataclasses.replace(dataset, title=title), observations, RELEASE_DATE
    )
    figure.draw_without_rendering()  # works out the final layout, so positions can be measured
    image = figure.bbox
    for text in [*figure.texts, *figure.axes[0].texts]:
        box = text.get_window_extent()
        label = text.get_text()[:40]
        assert box.x0 >= 0 and box.x1 <= image.width, f"{label!r} runs off the left or right edge"
        assert box.y0 >= 0 and box.y1 <= image.height, f"{label!r} runs off the top or bottom"


def test_the_title_does_not_overlap_the_units_line_or_the_plot(
    dataset: Dataset, observations: list[Observation]
) -> None:
    long_title = (
        "Population estimates by age group and sex, quarterly, Canada, provinces and territories"
    )
    figure = build_line_figure(
        dataclasses.replace(dataset, title=long_title), observations, RELEASE_DATE
    )
    figure.draw_without_rendering()
    title, units = figure.texts[0], figure.texts[1]
    plot_top = figure.axes[0].get_window_extent().y1
    assert title.get_window_extent().y0 >= units.get_window_extent().y1
    assert units.get_window_extent().y0 >= plot_top


def test_time_axis_labels_are_whole_days_with_no_repeats_or_times_of_day(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    # The data has one value per day, so a label like "11-09 06" (six in the morning) would
    # suggest readings that do not exist.
    files = write_line_chart(dataset, observations, RELEASE_DATE, tmp_path)
    labels = [p for p in _svg_text_pieces(files.svg) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p)]
    assert len(labels) >= 2
    assert len(set(labels)) == len(labels)
    assert all(label.startswith("2026-11-") for label in labels)


def test_latest_value_is_labelled_with_its_number_so_colour_is_not_the_only_cue(
    tmp_path: Path, dataset: Dataset
) -> None:
    observations = [
        make_observation(dataset, 9, "2.25"),
        make_observation(dataset, 10, "2.50"),
        make_observation(dataset, 11, "2.75"),
    ]
    text = _svg_text(write_line_chart(dataset, observations, RELEASE_DATE, tmp_path).svg)
    assert "2.75" in text


def test_alt_text_is_returned_and_stored_in_the_svg(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    files = write_line_chart(dataset, observations, RELEASE_DATE, tmp_path)
    assert files.alt_text.strip()
    assert files.alt_text == build_alt_text(dataset, observations, RELEASE_DATE)
    assert files.alt_text in _svg_all_text(files.svg)


def test_a_missing_value_is_a_gap_in_the_line_not_an_interpolated_point(dataset: Dataset) -> None:
    observations = [
        make_observation(dataset, 9, "2.25"),
        make_observation(dataset, 10, None),
        make_observation(dataset, 11, "2.75"),
    ]
    ydata = _drawn_values(build_line_figure(dataset, observations, RELEASE_DATE))
    assert len(ydata) == 3
    assert ydata[0] == 2.25
    assert math.isnan(ydata[1])
    assert ydata[2] == 2.75


def test_observations_given_out_of_order_are_drawn_in_date_order(dataset: Dataset) -> None:
    observations = [
        make_observation(dataset, 11, "2.75"),
        make_observation(dataset, 9, "2.25"),
        make_observation(dataset, 10, "2.50"),
    ]
    figure = build_line_figure(dataset, observations, RELEASE_DATE)
    assert _drawn_values(figure) == [2.25, 2.50, 2.75]


def test_dollar_signs_in_text_are_shown_literally_not_read_as_maths(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    tricky = dataclasses.replace(dataset, title="Price in $ and $ terms", attribution="Source: $x$")
    text = _svg_text(write_line_chart(tricky, observations, RELEASE_DATE, tmp_path).svg)
    assert "Price in $ and $ terms" in text
    assert "Source: $x$" in text


def test_a_series_with_no_values_writes_nothing(tmp_path: Path, dataset: Dataset) -> None:
    observations = [make_observation(dataset, 9, None), make_observation(dataset, 10, None)]
    with pytest.raises(ValueError, match="no values"):
        write_line_chart(dataset, observations, RELEASE_DATE, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_writing_the_same_chart_twice_gives_identical_files(
    tmp_path: Path, dataset: Dataset, observations: list[Observation]
) -> None:
    first = write_line_chart(dataset, observations, RELEASE_DATE, tmp_path / "one")
    second = write_line_chart(dataset, observations, RELEASE_DATE, tmp_path / "two")
    assert first.png.read_bytes() == second.png.read_bytes()
    assert first.svg.read_bytes() == second.svg.read_bytes()
