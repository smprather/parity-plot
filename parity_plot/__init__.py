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
    ref: str | Iterable[float | None] | None = None,
    test: str | Iterable[float | None] | None = None,
    join: str | None = None,
    group: str | Sequence[str | None] | None = None,
    keys: Sequence[str] | None = None,
    config: str | Path | ParityConfig | None = None,
    **options,
) -> go.Figure:
    """Build a parity plot figure in one call.

    Accepts either files or raw sequences:

        parity_plot("wide.csv", ref="wide.csv:reference", test="wide.csv:test")
        parity_plot("ref.csv", "meas.csv", ref="ref.csv:value",
                    test="meas.csv:value", join="id")
        parity_plot(ref=[1.0, 2.0], test=[1.1, None], theme="light")

    ``ref`` and ``test`` are ``file:column`` strings when files are given, or
    sequences of numbers for the in-memory case. Keyword ``options`` are
    :class:`PlotConfig` fields and take precedence over ``config``.
    """
    if isinstance(config, ParityConfig):
        cfg = config
    elif config is not None:
        cfg = ParityConfig.from_toml(config)
    else:
        cfg = ParityConfig()

    ref_is_column = ref is None or isinstance(ref, str)
    test_is_column = test is None or isinstance(test, str)
    if ref_is_column != test_is_column:
        raise TypeError(
            "ref and test must both be file:column strings or both be sequences"
        )

    plot_overrides = {k: v for k, v in options.items() if v is not None}
    unknown = set(plot_overrides) - {f for f in PlotConfig.__dataclass_fields__}
    if unknown:
        raise TypeError(f"unexpected keyword argument(s): {sorted(unknown)}")

    if not ref_is_column:
        if paths:
            raise TypeError("pass either files or ref/test sequences, not both")
        group_seq = group if not isinstance(group, str) else None
        data = from_sequences(ref, test, keys=keys, group=group_seq)  # type: ignore[arg-type]
    else:
        data_overrides = {
            "ref": ref,
            "test": test,
            "join": join,
            "group": group if isinstance(group, str) else None,
        }
        if paths:
            data_overrides["files"] = tuple(Path(p) for p in paths)
        cfg = cfg.merge(data=data_overrides)
        data = load(cfg.data)

    cfg = cfg.merge(plot=plot_overrides)
    return build_figure(data, cfg.plot, cfg.stats)
