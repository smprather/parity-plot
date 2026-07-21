"""45-degree parity plots, as a Python package and a CLI.

    from parity_plot import parity_plot

    fig = parity_plot("data/example.csv", x="reference", y="measured")
    fig.show()
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

import plotly.graph_objects as go

from .config import (
    ConfigError,
    DataConfig,
    OutputConfig,
    ParityConfig,
    PlotConfig,
    StatsConfig,
)
from .data import DataError, ParityData, Unpaired, from_sequences, load
from .examples import ExampleSpec, SpecError
from .examples import generate as generate_example
from .examples import write_all as write_example_data
from .plot import build_figure, save
from .stats import Stats, compute as compute_stats
from .tolerance import Tolerance
from .themes import THEMES as THEME_NAMES
from .themes import Theme

__version__ = "0.1.0"

__all__ = [
    "parity_plot",
    "build_figure",
    "save",
    "load",
    "from_sequences",
    "compute_stats",
    "generate_example",
    "write_example_data",
    "ExampleSpec",
    "SpecError",
    "ParityData",
    "Unpaired",
    "Stats",
    "Tolerance",
    "Theme",
    "THEME_NAMES",
    "ParityConfig",
    "DataConfig",
    "PlotConfig",
    "StatsConfig",
    "OutputConfig",
    "ConfigError",
    "DataError",
    "__version__",
]


def parity_plot(
    *paths: str | Path,
    x: str | Iterable[float | None] | None = None,
    y: str | Iterable[float | None] | None = None,
    keys: Sequence[str] | None = None,
    key: str | None = None,
    config: str | Path | ParityConfig | None = None,
    **options,
) -> go.Figure:
    """Build a parity plot figure in one call.

    Accepts either paths or raw sequences:

        parity_plot("wide.csv", x="reference", y="measured")
        parity_plot("ref.csv", "meas.csv", key="id")
        parity_plot(x=[1.0, 2.0], y=[1.1, None], theme="light")

    Keyword ``options`` are :class:`PlotConfig` fields (``theme``, ``title``,
    ``log``, ``tolerance``, ``nulls``, ...). They take precedence over
    ``config``, matching the CLI's flag-over-file ordering.
    """
    if isinstance(config, ParityConfig):
        cfg = config
    elif config is not None:
        cfg = ParityConfig.from_toml(config)
    else:
        cfg = ParityConfig()

    x_is_column = x is None or isinstance(x, str)
    y_is_column = y is None or isinstance(y, str)
    if x_is_column != y_is_column:
        raise TypeError(
            "x and y must both be column names or both be sequences of values"
        )

    plot_overrides = {k: v for k, v in options.items() if v is not None}
    unknown = set(plot_overrides) - {f for f in PlotConfig.__dataclass_fields__}
    if unknown:
        raise TypeError(f"unexpected keyword argument(s): {sorted(unknown)}")

    if not x_is_column:
        if paths:
            raise TypeError("pass either paths or x/y sequences, not both")
        data = from_sequences(x, y, keys=keys)  # type: ignore[arg-type]
    else:
        data_overrides = {"x": x, "y": y, "key": key}
        if paths:
            data_overrides["paths"] = tuple(Path(p) for p in paths)
        cfg = cfg.merge(data=data_overrides)
        data = load(cfg.data)

    cfg = cfg.merge(plot=plot_overrides)
    return build_figure(data, cfg.plot, cfg.stats)
