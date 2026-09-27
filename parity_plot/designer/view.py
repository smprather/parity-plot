"""Everything a refresh shows, computed in one pass off the event loop.

A refresh used to build the figure, convert it for the browser, and build a row
for every record, all on the asyncio loop -- ~30-35 ms of stall per thousand
rows, for *any* edit, a title change included. The loop also answers the
websocket heartbeat, and NiceGUI allows 2 s for that: past ~60k rows the browser
showed the reconnect overlay while the server was only busy.

So a refresh is now two halves. On the loop, ``DesignerState.view_inputs``
takes a snapshot -- a handful of references to immutable objects, no work. In a worker
thread, :func:`compute_view` does all of the per-record work and returns a
:class:`View` of plain data. Back on the loop, the app only assigns it to
widgets. The thread still holds the GIL while it computes, but the interpreter
hands the GIL back every few milliseconds, so the loop keeps answering.

Pure and browser-free, so it is tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import ConfigError, ParityConfig
from ..data import ParityData
from ..plot import build_figure
from .filters import FilterSet
from .records import record_views
from .table_rows import UNSORTED, TableSort, sort_rows, to_rows


def placeholder_figure() -> dict[str, Any]:
    """What the plot shows before the first view lands.

    Nothing, on a transparent background, rather than a figure built
    synchronously while the page loads. A fresh dict per call: the widget keeps
    a reference to the one it is given.
    """
    return {
        "data": [],
        "layout": {
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
        },
    }


@dataclass(frozen=True)
class ViewInputs:
    """A snapshot of what the view depends on, taken on the loop.

    Every field is immutable (or never mutated once built, like ``ParityData``),
    so a worker thread can read it while the loop moves on to newer state.
    """

    config: ParityConfig
    data: ParityData | None
    filters: FilterSet
    sort: TableSort = UNSORTED


@dataclass(frozen=True)
class View:
    """One refresh's worth of output, ready to hand to the widgets."""

    # The figure as plotly JSON -- the form the browser needs, converted here
    # rather than by NiceGUI on the loop. None when the build failed.
    figure: dict[str, Any] | None
    # Why the build failed; the app keeps showing the previous figure.
    error: str | None
    # Every visible record as a table row, already in ``inputs.sort`` order.
    rows: list[dict[str, Any]] = field(default_factory=list)
    # The same rows by record key, for selection highlighting.
    rows_by_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    showing: int = 0
    total: int = 0


def compute_view(inputs: ViewInputs) -> View:
    """Build the figure, the table rows and the counts from one snapshot.

    Mirrors :meth:`DesignerState.figure`, :meth:`~DesignerState.visible_records`
    and :meth:`~DesignerState.counts` -- the golden tests hold those to the CLI --
    but filters the data once instead of once per consumer.
    """
    tolerances = inputs.config.plot.tolerances
    if inputs.data is None:
        visible = ParityData()
    else:
        visible = inputs.filters.apply(inputs.data, tolerances)

    try:
        figure: dict[str, Any] | None = _frozen(
            build_figure(
                visible, inputs.config.plot, inputs.config.stats
            ).to_plotly_json()
        )
        error = None
    except (ConfigError, ValueError) as exc:
        figure, error = None, str(exc)

    rows = sort_rows(to_rows(record_views(visible, tolerances)), *inputs.sort)
    total = 0 if inputs.data is None else inputs.data.n_paired + inputs.data.n_unpaired
    return View(
        figure=figure,
        error=error,
        rows=rows,
        rows_by_key={row["key"]: row for row in rows},
        showing=visible.n_paired + visible.n_unpaired,
        total=total,
    )


def _frozen(value: Any) -> Any:
    """``value`` with every list turned into a tuple, recursively.

    NiceGUI stores an element's props in observable collections, and assigning
    a value converts every nested ``list`` and ``dict`` into an observable one
    -- on the event loop. A figure's per-point ``customdata`` is a list per
    point, so a 200k-point figure cost 200k conversions, over a second, on
    every paint. Tuples are left alone and serialize to the same JSON arrays,
    so freezing here, in the worker, leaves the loop only the few dicts.
    """
    if isinstance(value, dict):
        return {key: _frozen(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        if any(isinstance(item, (list, tuple, dict)) for item in value):
            return tuple(_frozen(item) for item in value)
        return tuple(value)
    return value
