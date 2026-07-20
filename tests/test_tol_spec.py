from __future__ import annotations

import pytest

from parity_plot.tol_spec import TolSpecError, build_tolerances, parse_tol_spec
from parity_plot.tolerances import NamedTolerance


# --- parse_tol_spec ---------------------------------------------------------


def test_single_key_spec():
    t = parse_tol_spec("reltol=0.1", "tolerance1")
    assert t.name == "tolerance1"
    assert t.reltol == 0.1
    assert t.abstol is None


def test_multiple_keys():
    t = parse_tol_spec("abstol=2,reltol=10pct,kind=info", "tolerance1")
    assert t.abstol == 2.0
    assert t.reltol == 0.1
    assert t.kind == "info"


@pytest.mark.parametrize("value", ["10pct", "0.1", "10%"])
def test_reltol_accepts_ratio_and_percent(value):
    assert parse_tol_spec(f"reltol={value}", "t1").reltol == pytest.approx(0.1)


def test_auto_name_when_omitted():
    t = parse_tol_spec("reltol=0.1", "tolerance3")
    assert t.name == "tolerance3"


def test_explicit_name_honoured():
    t = parse_tol_spec("name=spec,reltol=0.1", "tolerance1")
    assert t.name == "spec"


def test_kind_color_style_label_parsed():
    t = parse_tol_spec(
        "name=x,reltol=0.1,kind=info,color=yellow,style=shaded,label=my band",
        "tolerance1",
    )
    assert t.kind == "info"
    assert t.color == "yellow"
    assert t.style == "shaded"
    assert t.label == "my band"


def test_unknown_key_errors():
    with pytest.raises(TolSpecError, match="unknown tolerance key"):
        parse_tol_spec("bogus=1,reltol=0.1", "tolerance1")


def test_non_keyvalue_chunk_errors():
    with pytest.raises(TolSpecError, match="is not key=value"):
        parse_tol_spec("reltol=0.1,oops", "tolerance1")


def test_no_bound_errors():
    with pytest.raises(TolSpecError, match="needs abstol or reltol"):
        parse_tol_spec("name=x,color=red", "tolerance1")


def test_bad_abstol_errors():
    with pytest.raises(TolSpecError, match="abstol must be a number"):
        parse_tol_spec("abstol=wide", "tolerance1")


def test_bad_reltol_errors():
    with pytest.raises(TolSpecError):
        parse_tol_spec("reltol=wide", "tolerance1")


# --- build_tolerances -------------------------------------------------------


def test_build_empty_gives_empty_tuple():
    assert build_tolerances((), None, None, None) == ()


def test_build_tol_entries_in_order():
    specs = ("reltol=0.1", "abstol=2")
    result = build_tolerances(specs, None, None, None)
    assert len(result) == 2
    assert result[0].name == "tolerance1"
    assert result[0].reltol == 0.1
    assert result[1].name == "tolerance2"
    assert result[1].abstol == 2.0


def test_build_sugar_appended_as_one_entry():
    result = build_tolerances(("reltol=0.1",), 2.0, None, None)
    assert len(result) == 2
    assert result[0].name == "tolerance1"
    assert result[1].name == "tolerance2"
    assert result[1].abstol == 2.0
    assert result[1].reltol is None


def test_build_sugar_with_both_bounds():
    result = build_tolerances((), 2.0, 0.1, "shaded")
    assert len(result) == 1
    assert result[0].abstol == 2.0
    assert result[0].reltol == 0.1
    assert result[0].style == "shaded"


def test_build_auto_names_do_not_collide():
    specs = ("name=tolerance1,reltol=0.1", "reltol=0.2")
    result = build_tolerances(specs, 3.0, None, None)
    names = [t.name for t in result]
    assert names == ["tolerance1", "tolerance2", "tolerance3"]


def test_build_sugar_only():
    result = build_tolerances((), None, 0.1, None)
    assert len(result) == 1
    assert result[0].name == "tolerance1"
    assert result[0].reltol == 0.1
    assert result[0].style == "lines"


def test_build_returns_namedtolerance_instances():
    result = build_tolerances(("reltol=0.1",), None, None, None)
    assert all(isinstance(t, NamedTolerance) for t in result)