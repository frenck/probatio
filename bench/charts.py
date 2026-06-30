"""Render the benchmark charts into the docs assets, themed to the docs.

Run with: ``uv run --no-sync python bench/charts.py`` (after
``uv sync --group bench-world``, which ``just charts`` does for you).

It runs the three benchmark sets (``bench``, ``bench_dataclass``, ``bench_world``)
and writes one SVG per set into ``docs/public/benchmarks/``. The charts are dark
cards (so they read on both the light and dark docs themes) using the docs' brand
colors and font. Numbers are machine-dependent, like the tables; regenerate on the
machine you want to quote.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import bench
import bench_dataclass
import bench_world
import matplotlib as mpl

mpl.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# The docs' palette: the #100F15 base, the #506468 -> #24fefd brand gradient, Inter.
BG = "#13151c"
TEXT = "#e6edf3"
MUTED = "#9aa3ad"
GRID = "#2a2e38"
CYAN = "#24fefd"  # probatio compiled (the brand highlight)
TEAL = "#46b3ac"  # probatio interpreted
GREY = "#5b626d"  # everything else / the baseline

OUT = Path(__file__).resolve().parent.parent / "docs" / "public" / "benchmarks"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Inter", "Inter Variable", "DejaVu Sans"],
        "svg.fonttype": "none",  # keep text as text so the page font (Inter) applies
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "savefig.facecolor": BG,
        "text.color": TEXT,
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": TEXT,
        "axes.edgecolor": GRID,
    }
)


def _style(ax: Any, title: str, xlabel: str) -> None:
    """Apply the shared dark-card styling to an axis."""
    ax.set_title(title, color=TEXT, fontsize=13, fontweight="bold", pad=14, loc="left")
    ax.set_xlabel(xlabel, fontsize=9)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(length=0)
    ax.set_axisbelow(True)
    ax.xaxis.grid(visible=True, color=GRID, linewidth=0.8)


def _legend(ax: Any) -> None:
    """A dark, borderless legend, below the chart so it never overlaps a bar."""
    legend = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=3,
        fontsize=8.5,
        frameon=False,
    )
    for text in legend.get_texts():
        text.set_color(TEXT)


def _grouped(rows: list[dict[str, Any]], series: list[tuple[str, str, str]]) -> Any:
    """Build a grouped horizontal bar chart. ``series`` is ``(key, label, color)``."""
    labels = [row["scenario"] for row in rows]
    fig, ax = plt.subplots(figsize=(8.2, 0.7 * len(labels) + 1.6))
    count = len(series)
    height = 0.82 / count
    base = range(len(labels))
    for index, (key, label, color) in enumerate(series):
        offset = (index - (count - 1) / 2) * height
        positions = [y - offset for y in base]
        values = [row[key] for row in rows]
        ax.barh(
            positions, values, height=height * 0.9, color=color, label=label, zorder=3
        )
    ax.set_yticks(list(base))
    ax.set_yticklabels(labels)
    return fig, ax, base, height


def chart_vs_voluptuous() -> None:
    """Set 1: how many times faster than voluptuous, per scenario."""
    raw = bench.measure()
    rows = [
        {
            "scenario": row["scenario"],
            "voluptuous": 1.0,
            "probatio": row["voluptuous"] / row["probatio"],
            "compiled": row["voluptuous"] / row["compiled"],
        }
        for row in raw
    ]
    series = [
        ("voluptuous", "voluptuous", GREY),
        ("probatio", "probatio", TEAL),
        ("compiled", "probatio (compiled)", CYAN),
    ]
    fig, ax, base, height = _grouped(rows, series)
    for index, (key, _, _) in enumerate(series):
        offset = (index - (len(series) - 1) / 2) * height
        for y, row in zip(base, rows, strict=True):
            ax.text(
                row[key] + 0.07,
                y - offset,
                f"{row[key]:.1f}x",
                va="center",
                ha="left",
                color=MUTED,
                fontsize=7.5,
            )
    ax.set_xlim(right=max(row["compiled"] for row in rows) * 1.18)
    _style(
        ax,
        "Validation throughput vs voluptuous",
        "times faster than voluptuous (higher is better)",
    )
    _legend(ax)
    fig.savefig(OUT / "vs-voluptuous.svg", format="svg", bbox_inches="tight")
    plt.close(fig)


def chart_vs_mashumaro() -> None:
    """Set 2: dataclass construction, microseconds, vs mashumaro."""
    rows = bench_dataclass.measure()
    series = [
        ("mashumaro", "mashumaro", GREY),
        ("probatio", "probatio", TEAL),
        ("compiled", "probatio (compiled)", CYAN),
    ]
    fig, ax, base, height = _grouped(rows, series)
    for index, (key, _, _) in enumerate(series):
        offset = (index - (len(series) - 1) / 2) * height
        for y, row in zip(base, rows, strict=True):
            ax.text(
                row[key] + 0.03,
                y - offset,
                f"{row[key]:.2f}",
                va="center",
                ha="left",
                color=MUTED,
                fontsize=7.5,
            )
    ax.set_xlim(right=max(row["probatio"] for row in rows) * 1.15)
    _style(
        ax,
        "Dataclass construction vs mashumaro",
        "microseconds per construction (lower is faster)",
    )
    _legend(ax)
    fig.savefig(OUT / "dataclass-vs-mashumaro.svg", format="svg", bbox_inches="tight")
    plt.close(fig)


def chart_vs_world() -> None:
    """Set 3: dict to object across libraries, microseconds, log scale."""
    rows = bench_world.measure()  # fastest first
    labels = [row["label"] for row in rows]
    values = [row["us"] for row in rows]
    colors = [
        CYAN
        if "compiled" in row["label"]
        else TEAL
        if "probatio" in row["label"]
        else GREY
        for row in rows
    ]
    fig, ax = plt.subplots(figsize=(8.2, 0.5 * len(rows) + 1.9))
    base = range(len(rows))
    bars = ax.barh(list(base), values, color=colors, height=0.72, zorder=3)
    # Deserializers (trust the declared types) are hatched; validators (check every
    # field) are solid. The hatch lines are the card colour, reading as grooves.
    for bar, row in zip(bars, rows, strict=True):
        if row["group"] == "deserialize":
            bar.set_hatch("////")
            bar.set_edgecolor(BG)
            bar.set_linewidth(0)
    ax.set_xscale("log")
    for y, value in zip(base, values, strict=True):
        ax.text(
            value * 1.12,
            y,
            f"{value:.2f}µs",
            va="center",
            ha="left",
            color=MUTED,
            fontsize=7.5,
        )
    ax.set_yticks(list(base))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()  # fastest at the top
    ax.set_xlim(right=max(values) * 2.2)
    _style(
        ax,
        "dict to object, across libraries",
        "microseconds per load (log scale, lower is faster)",
    )
    key = [
        Patch(facecolor=GREY, label="validates (checks every field)"),
        Patch(
            facecolor=GREY,
            hatch="////",
            edgecolor=BG,
            linewidth=0,
            label="deserializes (trusts the types)",
        ),
    ]
    legend = ax.legend(
        handles=key,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=2,
        fontsize=8.5,
        frameon=False,
    )
    for text in legend.get_texts():
        text.set_color(TEXT)
    fig.savefig(OUT / "vs-world.svg", format="svg", bbox_inches="tight")
    plt.close(fig)


def chart_validators() -> None:
    """Set 4: only the validators, the fair like-for-like, marking the pure-Python ones."""
    rows = [row for row in bench_world.measure() if row["group"] == "validate"]
    labels = [row["label"] for row in rows]
    values = [row["us"] for row in rows]
    colors = [
        CYAN
        if "compiled" in row["label"]
        else TEAL
        if "probatio" in row["label"]
        else GREY
        for row in rows
    ]
    fig, ax = plt.subplots(figsize=(8.2, 0.55 * len(rows) + 1.9))
    base = range(len(rows))
    bars = ax.barh(list(base), values, color=colors, height=0.66, zorder=3)
    # A native core (pydantic v2's Rust pydantic-core) is hatched; everything else,
    # probatio included, is pure Python and solid.
    for bar, row in zip(bars, rows, strict=True):
        if row["impl"] == "native":
            bar.set_hatch("////")
            bar.set_edgecolor(BG)
            bar.set_linewidth(0)
    ax.set_xscale("log")
    for y, value in zip(base, values, strict=True):
        ax.text(
            value * 1.1,
            y,
            f"{value:.2f}µs",
            va="center",
            ha="left",
            color=MUTED,
            fontsize=7.5,
        )
    ax.set_yticks(list(base))
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlim(right=max(values) * 2.2)
    _style(
        ax,
        "Validators only, like for like",
        "microseconds per load (log scale, lower is faster)",
    )
    key = [
        Patch(facecolor=GREY, label="pure Python"),
        Patch(
            facecolor=GREY,
            hatch="////",
            edgecolor=BG,
            linewidth=0,
            label="native core (Rust / C)",
        ),
    ]
    legend = ax.legend(
        handles=key,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=2,
        fontsize=8.5,
        frameon=False,
    )
    for text in legend.get_texts():
        text.set_color(TEXT)
    fig.savefig(OUT / "validators.svg", format="svg", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Render every chart into the docs assets."""
    OUT.mkdir(parents=True, exist_ok=True)
    chart_vs_voluptuous()
    chart_vs_mashumaro()
    chart_vs_world()
    chart_validators()
    print(f"wrote charts to {OUT}")


if __name__ == "__main__":
    main()
