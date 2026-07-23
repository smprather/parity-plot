from __future__ import annotations

from parity_plot.config import ParityConfig
from parity_plot.designer.validation import Problem, problems


def _cfg(**data) -> ParityConfig:
    return ParityConfig.from_dict({"data": data})


def test_same_file_ref_and_test_with_a_join_is_an_advisory():
    cfg = _cfg(files=["d.csv"], ref="d.csv:reference", test="d.csv:test", join="id")
    probs = problems(cfg)
    assert len(probs) == 1
    assert probs[0].field == "data.join"
    assert "join" in probs[0].message.lower()
    # Redundant, not wrong -> advisory, not a blocking error.
    assert probs[0].severity == "warning"


def test_problem_defaults_to_error_severity():
    assert Problem(message="x", field="data.join").severity == "error"


def test_same_file_without_a_join_is_fine():
    cfg = _cfg(files=["d.csv"], ref="d.csv:reference", test="d.csv:test")
    assert problems(cfg) == []


def test_different_files_with_a_join_is_fine():
    cfg = _cfg(files=["a.csv", "b.csv"], ref="a.csv:v", test="b.csv:v", join="id")
    assert problems(cfg) == []


def test_incomplete_config_has_no_problems():
    assert problems(ParityConfig()) == []


def test_problem_is_hashable_and_frozen():
    p = Problem(message="x", field="data.join")
    hash(p)