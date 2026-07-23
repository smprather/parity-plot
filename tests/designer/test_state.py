from __future__ import annotations

from dataclasses import replace

import pytest

from parity_plot.config import ParityConfig
from parity_plot.data import from_sequences
from parity_plot.designer.state import DesignerState


@pytest.fixture
def state() -> DesignerState:
    data = from_sequences(x=[1.0, 2.0, 3.0], y=[1.1, 2.2, None], keys=["a", "b", "c"])
    return DesignerState(config=ParityConfig(), data=data)


def test_figure_comes_from_the_cli_code_path(state):
    """The preview must be the CLI's own figure, or the two can drift."""
    from parity_plot.plot import build_figure

    assert state.figure().to_dict() == build_figure(
        state.data, state.config.plot, state.config.stats
    ).to_dict()


def test_update_applies_a_setting(state):
    assert state.update("plot", theme="light")
    assert state.config.plot.theme == "light"
    assert state.last_error is None


def test_update_reports_failure_and_keeps_the_old_value(state):
    assert not state.update("plot", theme="neon")
    assert state.config.plot.theme == "dark"
    assert "neon" in state.last_error


def test_an_invalid_update_never_blanks_the_plot(state):
    good = state.figure().to_dict()
    state.update("plot", theme="neon")
    assert state.figure().to_dict() == good


def break_legend(config: ParityConfig) -> ParityConfig:
    """Force a value past validation that `build_figure` will still reject.

    `replace` first, then mutate the *copy*: a frozen dataclass instance used as
    a field default is shared by every `ParityConfig()`, so forcing a value into
    `config.plot` directly corrupts that shared default for the whole process
    and silently breaks unrelated tests later in the run.
    """
    broken = replace(config.plot, legend="nonsense")
    return replace(config, plot=broken)


def test_a_figure_that_fails_to_build_falls_back_to_the_last_good_one(state):
    good = state.figure().to_dict()
    state.config = break_legend(state.config)

    assert state.figure().to_dict() == good
    assert state.last_error is not None


def test_the_first_figure_cannot_fall_back_and_raises(state):
    state.config = break_legend(state.config)
    with pytest.raises(ValueError):
        state.figure()


def test_forcing_a_broken_config_does_not_leak_into_other_configs():
    """Guards the trap the helper above exists to avoid."""
    break_legend(ParityConfig())
    assert ParityConfig().plot.legend == "right"


def test_none_values_are_ignored_by_update(state):
    state.update("plot", theme="light")
    state.update("plot", theme=None)
    assert state.config.plot.theme == "light"


def test_selection_defaults_to_nothing(state):
    assert state.selection is None


def test_reset_fields_reverts_x_label_to_none():
    from parity_plot.config import ParityConfig
    from parity_plot.designer.state import DesignerState

    config = ParityConfig.from_dict({"plot": {"x_label": "custom", "title": "Keep me"}})
    st = DesignerState(config=config)
    st.reset_fields("plot", "x_label")

    assert st.config.plot.x_label is None      # back to default, not "custom"
    assert st.config.plot.title == "Keep me"   # siblings untouched


def test_reset_fields_reverts_join_to_none():
    from parity_plot.config import ParityConfig
    from parity_plot.designer.state import DesignerState

    config = ParityConfig.from_dict(
        {"data": {"files": ["d.csv"], "ref": "d.csv:a", "test": "d.csv:b", "join": "id"}}
    )
    st = DesignerState(config=config)
    st.reset_fields("data", "join")
    assert st.config.data.join is None


def test_load_session_config_swaps_and_clears_selection():
    from parity_plot.config import ParityConfig
    from parity_plot.designer.state import DesignerState

    st = DesignerState(config=ParityConfig(), selection="A1", last_error="boom")
    new = ParityConfig.from_dict({"plot": {"theme": "light"}})
    st.load_session_config(new, None)

    assert st.config.plot.theme == "light"
    assert st.data is None
    assert st.selection is None
    assert st.last_error is None