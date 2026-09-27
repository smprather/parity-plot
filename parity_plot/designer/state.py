"""The designer's single source of truth."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Sequence

import plotly.graph_objects as go

from ..config import ConfigError, DataConfig, ParityConfig
from ..data import DataError, ParityData, load
from ..plot import build_figure
from ..tolerances import NamedTolerance
from .filters import FilterSet
from .records import RecordView, find_record, record_views


def _with_defaults(section: Any, keys: Sequence[str]) -> Any:
    """A copy of ``section`` with the named fields at their dataclass defaults.

    Shared by :meth:`DesignerState.reset_fields` (a pure reset) and
    :meth:`DesignerState.set_data_source` (a reset folded into a reload). Both
    need to put a field back to its default; ``merge`` cannot, because it drops
    ``None`` overrides, and ``None`` is sometimes the meaningful value.
    """
    defaults: dict[str, object] = {}
    for f in dataclasses.fields(section):
        if f.name in keys:
            if f.default is not dataclasses.MISSING:
                defaults[f.name] = f.default
            elif f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
                defaults[f.name] = f.default_factory()  # type: ignore[misc]
    return dataclasses.replace(section, **defaults)


class Generation:
    """A monotonic counter for work that can be superseded while in flight.

    Claim a number before starting slow work, then check it has not moved
    before acting on the result. Used twice in the designer, for the same
    reason both times: an NFS read takes seconds, the user does not wait, and
    "whoever finished last" is not "what the user last asked for".
    """

    def __init__(self) -> None:
        self._value = 0

    @property
    def value(self) -> int:
        return self._value

    def bump(self) -> int:
        """Claim the next generation, invalidating everything in flight."""
        self._value += 1
        return self._value

    def current(self, claim: int) -> bool:
        """Whether ``claim`` is still the newest one handed out."""
        return claim == self._value


@dataclass(frozen=True)
class PreparedData:
    """The outcome of preparing a data-source change, before it is applied.

    Produced by :meth:`DesignerState.prepare_data_source` (which runs in a
    worker thread, off the event loop) and consumed by
    :meth:`DesignerState.commit_data_source` (which runs on the loop). It
    carries a *description* of the outcome rather than the effect, so a result
    that finishes after the user has moved on can simply be dropped.
    """

    # The validated [data] section to merge in. Merged on commit, not on
    # prepare, so a plot edit made while the load ran is not reverted.
    section: DataConfig
    # The loaded dataset, or None for an incomplete (blanked) source.
    data: ParityData | None
    # A complete source that failed to load: keep the previous dataset.
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class DesignerState:
    """Everything the UI reads from and writes to.

    Widgets never hold state of their own; they push edits in here and re-read
    the result, so the config on screen and the config that will be saved
    cannot disagree.
    """

    config: ParityConfig
    # None before any file is opened -- the designer starts empty and shows a
    # blank plot until files and ref/test are chosen.
    data: ParityData | None = None
    selection: str | None = None
    filters: FilterSet = field(default_factory=FilterSet)
    last_error: str | None = None
    _last_figure: go.Figure | None = field(default=None, repr=False)
    # Monotonic counter for in-flight data-source changes. Bumped when one
    # begins and when a config is swapped in; a commit whose generation is no
    # longer current is stale and is dropped. This is what stops an older slow
    # load from overwriting a newer choice, and a pre-swap load from
    # overwriting the config that replaced it.
    _generation: Generation = field(default_factory=Generation, repr=False)

    @property
    def has_data(self) -> bool:
        return self.data is not None

    def update(self, section: str, **values: Any) -> bool:
        """Apply settings to one config section. Returns whether it worked.

        Routed through ``ParityConfig.merge`` so the designer inherits exactly
        the validation and error text the TOML and CLI paths already use.
        """
        try:
            self.config = self.config.merge(**{section: values})
        except (ConfigError, ValueError) as exc:
            self.last_error = str(exc)
            return False
        self.last_error = None
        return True

    def begin_data_source(self) -> int:
        """Claim a generation for a data-source change about to be prepared.

        Call this *before* the (slow) prepare, on the loop, and pass the result
        to both :meth:`prepare_data_source` and :meth:`commit_data_source`. A
        later change, or a config swap, bumps the counter and invalidates
        everything in flight.
        """
        return self._generation.bump()

    def prepare_data_source(
        self, *, clear: Sequence[str] = (), **values: Any
    ) -> PreparedData:
        """Validate and load a new new data source. Pure: touches no state.

        Safe to run in a worker thread off the event loop -- it only *reads*
        ``self.config`` (to validate the override and to build the ``[data]``
        section) and returns a description of what the result would be. The
        companion :meth:`commit_data_source` applies it, merging into whatever
        the config has become by then.

        It takes no generation: a stale result is caught at commit time, where
        the loop can act on it, and a thread cannot usefully cancel itself.

        ``clear`` names ``data`` fields to reset to their dataclass default on
        the candidate *before* loading. This exists because ``merge`` drops
        ``None`` overrides by design (so a CLI can pass every flag
        unconditionally), and for some fields ``None`` *is* the meaningful
        value -- ``hover_columns`` is ``None`` for "auto". Passing
        ``hover_columns=None`` through ``merge`` would silently keep the stale
        pinned set, so the designer routes "back to auto" through ``clear``
        instead. ``reset_fields`` cannot serve here: it does not reload the
        data, and ``hover_columns`` changes what ``load`` produces.
        """
        try:
            candidate = self.config.merge(data=values)
        except (ConfigError, ValueError) as exc:
            return PreparedData(section=self.config.data, data=None, error=str(exc))

        if clear:
            new_data = _with_defaults(candidate.data, clear)
            candidate = dataclasses.replace(candidate, data=new_data)
        section = candidate.data

        # An incomplete source -- no files, or no ref/test yet -- is the empty
        # state, not an error: the user removed the last file or has not finished
        # picking columns. Go blank cleanly rather than keeping stale data.
        if not section.files or not section.ref or not section.test:
            return PreparedData(section=section, data=None)

        try:
            return PreparedData(section=section, data=load(section))
        except (ConfigError, DataError, ValueError) as exc:
            return PreparedData(section=section, data=None, error=str(exc))

    def commit_data_source(self, prepared: PreparedData, generation: int) -> bool:
        """Apply a prepared data source. Runs on the event loop.

        Returns whether it was applied. A stale ``generation`` -- one that a
        later change or a config swap has superseded -- is dropped, so an older
        slow load cannot overwrite a newer choice.

        Only the ``[data]`` section is merged, and it is merged into the config
        as it stands *now*: an edit the user made while the load was in flight
        is a different section, and reverting it would lose their work.
        """
        if not self._generation.current(generation):
            return False

        if prepared.error is not None:
            # A complete-but-broken source (bad column, unreadable file) keeps
            # the working dataset -- losing it to a typo is worse than the
            # message.
            self.last_error = prepared.error
            return False

        self.config = dataclasses.replace(self.config, data=prepared.section)
        self.data = prepared.data
        self.last_error = None
        if prepared.data is None:
            self.selection = None
        elif (
            self.selection is not None
            and find_record(record_views(prepared.data), self.selection) is None
        ):
            # The pinned record does not exist in the new dataset.
            self.selection = None
        return True

    def set_data_source(self, *, clear: Sequence[str] = (), **values: Any) -> bool:
        """Point at a different file or column mapping. Returns whether it worked.

        The synchronous one-call form: begin, prepare and commit without an await
        in between. The designer splits the same three steps around its
        off-the-loop load, which is what this method could not do safely -- see
        :class:`PreparedData`.
        """
        generation = self.begin_data_source()
        prepared = self.prepare_data_source(clear=clear, **values)
        return self.commit_data_source(prepared, generation)

    def reset_fields(self, section: str, *keys: str) -> None:
        """Reset the named fields of one section to their dataclass defaults.

        Needed because ``ParityConfig.merge`` drops ``None`` overrides (a
        deliberate CLI convenience), so it cannot clear an optional field back
        to its default. Blanking a text control routes here instead, so an
        emptied ``x_label`` truly reverts to the column name rather than keeping
        its stale value.
        """
        current = getattr(self.config, section)
        new_section = _with_defaults(current, keys)
        self.config = dataclasses.replace(self.config, **{section: new_section})
        self.last_error = None

    def load_session_config(
        self, config: ParityConfig, data: ParityData | None
    ) -> None:
        """Swap in a freshly opened config (and its data), clearing view state.

        Used when the toolbar opens a different config or starts a New Design:
        the whole config changes, so a pinned selection and any prior error are
        no longer meaningful. Filters reset to their default (a no-op) view.
        """
        self.config = config
        self.data = data
        self.selection = None
        self.filters = FilterSet()
        self.last_error = None
        # Invalidate any data-source change still in flight: it was prepared
        # against the config being replaced, and committing it would put the old
        # design back -- and then auto-save it over the newly opened file.
        self._generation.bump()

    def selected_record(
        self, tolerances: Sequence[NamedTolerance] = ()
    ) -> RecordView | None:
        """The pinned record, judged against ``tolerances`` if any are given."""
        if self.selection is None or self.data is None:
            return None
        return find_record(record_views(self.data, tolerances), self.selection)

    def tolerances(self) -> tuple[NamedTolerance, ...]:
        """The tolerance list the current config specifies."""
        return self.config.plot.tolerances

    def visible_data(self) -> ParityData:
        """The dataset after filtering. The plot and the table both read this.

        Empty (not None) before any file is opened, so consumers need no None
        guard of their own.
        """
        if self.data is None:
            return ParityData()
        return self.filters.apply(self.data, self.tolerances())

    def visible_records(self) -> list[RecordView]:
        """One row per visible record, judged against the current tolerances."""
        return record_views(self.visible_data(), self.tolerances())

    def counts(self) -> tuple[int, int]:
        """``(showing, total)`` records -- a filtered view that looks unfiltered
        is a trap, so the UI always states both."""
        if self.data is None:
            return 0, 0
        visible = self.visible_data()
        showing = visible.n_paired + visible.n_unpaired
        total = self.data.n_paired + self.data.n_unpaired
        return showing, total

    def figure(self) -> go.Figure:
        """Build the preview, keeping the last good one if this build fails.

        A rejected setting must not clear the screen -- losing the plot on a
        typo makes the tool feel broken and hides what you were comparing
        against.
        """
        try:
            figure = build_figure(
                self.visible_data(), self.config.plot, self.config.stats
            )
        except (ConfigError, ValueError) as exc:
            self.last_error = str(exc)
            if self._last_figure is None:
                raise
            return self._last_figure

        # Deliberately does NOT clear `last_error`. A failed `set_data_source`
        # leaves the previous dataset loaded, so the very next `figure()` call
        # succeeds -- and clearing here would wipe the explanation before the
        # error banner ever displayed it. Errors are cleared by whatever
        # succeeds next: `update` or `set_data_source`.
        self._last_figure = figure
        return figure
