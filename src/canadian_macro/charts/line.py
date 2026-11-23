"""Single-series line chart, written as PNG + SVG.

Every chart carries its own sourcing: title, units, the dataset's attribution line (source and
licence statement) and the data release date are drawn on the image itself, so the picture is
still correctly credited when it is copied out of the export package. Colours and mark sizes
follow the ``dataviz`` skill's reference palette (light surface only).

Missing values are drawn as gaps. Nothing is filled in or interpolated.
"""

import io
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator

from canadian_macro.catalog import Dataset
from canadian_macro.charts.alt_text import build_alt_text
from canadian_macro.sources.types import Observation
from canadian_macro.store.files import write_atomic

# dataviz reference palette, light mode.
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
SERIES_COLOUR = "#2a78d6"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

FIGURE_SIZE_INCHES = (8.0, 4.5)
PNG_DPI = 200  # 1600 x 900 pixels: sharp when Substack scales it down to column width
ATTRIBUTION_WRAP = 110  # characters per footer line at the footer font size
TITLE_WRAP = (
    52  # characters per title line at 15 pt bold, so the widest line stays inside the image
)

# Vertical layout, as fractions of the image height (0 = bottom, 1 = top).
TITLE_TOP = 0.95
TITLE_LINE_HEIGHT = 0.058  # one 15 pt title line at 1.2 line spacing on a 4.5 inch tall image
PLOT_BOTTOM = 0.30  # leaves room below the plot for the date labels and the footer

X_TICKS = 5  # about this many date labels along the bottom


def _day_number(day: date) -> float:
    """Where a date sits on the x axis: its proleptic Gregorian day number (``toordinal``).

    The axis is plain numbers with its own tick labels, because matplotlib's date tools pick
    hourly ticks for short ranges, which would suggest readings that do not exist.
    """
    return float(day.toordinal())


def _day_label(position: float, _index: int) -> str:
    return date.fromordinal(round(position)).isoformat()


@dataclass(frozen=True)
class LineChartFiles:
    png: Path
    svg: Path
    alt_text: str


def _literal(text: str) -> str:
    """Escape ``$`` so matplotlib shows it as a dollar sign instead of starting maths mode."""
    return text.replace("$", r"\$")


def build_line_figure(
    dataset: Dataset, observations: Sequence[Observation], release_date: date
) -> Figure:
    """Draw the chart. Raises ``ValueError`` if the data is for another dataset or has no values."""
    build_alt_text(dataset, observations, release_date)  # runs the same checks as the alt text

    ordered = sorted(observations, key=lambda obs: obs.period)
    periods = [_day_number(obs.period) for obs in ordered]
    # float() is for drawing only; labels and alt text use the exact stored decimal.
    values = [float("nan") if obs.value is None else float(obs.value) for obs in ordered]
    last = max((obs for obs in ordered if obs.value is not None), key=lambda obs: obs.period)
    assert last.value is not None

    # The title wraps onto as many lines as it needs; everything below it moves down to match.
    title_lines = textwrap.wrap(dataset.title, width=TITLE_WRAP) or [""]
    title_bottom = TITLE_TOP - len(title_lines) * TITLE_LINE_HEIGHT
    units_top = title_bottom - 0.012
    plot_top = units_top - 0.09  # room for the units line and the top gridline's label

    figure = Figure(figsize=FIGURE_SIZE_INCHES, dpi=PNG_DPI, facecolor=SURFACE)
    figure.text(
        0.04, TITLE_TOP, _literal("\n".join(title_lines)), fontsize=15, fontweight="bold",
        color=INK_PRIMARY, va="top", linespacing=1.2,
    )  # fmt: skip
    figure.text(
        0.04, units_top, _literal(f"Units: {dataset.units}"), fontsize=11,
        color=INK_SECONDARY, va="top",
    )  # fmt: skip

    ax = figure.add_axes((0.09, PLOT_BOTTOM, 0.82, plot_top - PLOT_BOTTOM), facecolor=SURFACE)
    ax.plot(
        periods, values, color=SERIES_COLOUR, linewidth=2,
        solid_joinstyle="round", solid_capstyle="round",
    )  # fmt: skip
    # The end dot (with a surface-coloured ring) and its printed value mean the latest reading
    # does not depend on telling colours apart.
    last_x = _day_number(last.period)
    ax.plot(
        [last_x], [float(last.value)], marker="o", markersize=8, linestyle="none",
        color=SERIES_COLOUR, markeredgecolor=SURFACE, markeredgewidth=2, zorder=3,
    )  # fmt: skip
    ax.annotate(
        format(last.value, "f"),
        (last_x, float(last.value)),
        xytext=(10, 0),
        textcoords="offset points",
        fontsize=11,
        fontweight="bold",
        color=INK_PRIMARY,
        va="center",
        annotation_clip=False,
        bbox={"boxstyle": "square,pad=0.15", "facecolor": SURFACE, "edgecolor": "none"},
    )  # fmt: skip  (the backing keeps a gridline from running through the number)

    ax.xaxis.set_major_locator(MaxNLocator(nbins=X_TICKS, integer=True))  # whole days only
    ax.xaxis.set_major_formatter(FuncFormatter(_day_label))
    ax.yaxis.grid(True, color=GRID, linewidth=1, linestyle="solid")
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(axis="both", length=0, labelsize=10, labelcolor=INK_SECONDARY, pad=6)
    ax.margins(x=0.06, y=0.15)

    attribution = "\n".join(textwrap.wrap(dataset.attribution, width=ATTRIBUTION_WRAP))
    figure.text(
        0.04, 0.075, _literal(attribution), fontsize=9, color=INK_SECONDARY,
        va="bottom", linespacing=1.4,
    )  # fmt: skip
    figure.text(
        0.04, 0.03, f"Data release date: {release_date.isoformat()}", fontsize=9,
        color=INK_SECONDARY, va="bottom",
    )  # fmt: skip
    return figure


def write_line_chart(
    dataset: Dataset, observations: Sequence[Observation], release_date: date, out_dir: Path
) -> LineChartFiles:
    """Write ``<out_dir>/<dataset id>.png`` and ``.svg`` and return their paths and the alt text.

    Both images are rendered in memory first, so a failure leaves no half-written files behind.
    """
    alt_text = build_alt_text(dataset, observations, release_date)
    figure = build_line_figure(dataset, observations, release_date)

    # fonttype "none" keeps SVG text as real, selectable text (not outlines), which screen
    # readers and tests can read. A fixed hashsalt and no Date make the SVG reproducible.
    with mpl.rc_context({"svg.fonttype": "none", "svg.hashsalt": "canadian-macro"}):
        png_bytes = io.BytesIO()
        figure.savefig(png_bytes, format="png", dpi=PNG_DPI, facecolor=SURFACE)
        svg_bytes = io.BytesIO()
        figure.savefig(
            svg_bytes,
            format="svg",
            facecolor=SURFACE,
            metadata={"Title": dataset.title, "Description": alt_text, "Date": None},
        )

    png_path = out_dir / f"{dataset.id}.png"
    svg_path = out_dir / f"{dataset.id}.svg"
    write_atomic(png_path, png_bytes.getvalue())
    write_atomic(svg_path, svg_bytes.getvalue())
    return LineChartFiles(png=png_path, svg=svg_path, alt_text=alt_text)
