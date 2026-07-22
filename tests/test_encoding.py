# tests/test_encoding.py
from __future__ import annotations

import pytest

from parity_plot.encoding import CHANNELS, Encoding, partition


def test_default_is_a_single_trace():
    """The default must reproduce today's one-trace plot for the golden test."""
    specs = partition(3, [True, False, True], None, Encoding())
    assert len(specs) == 1
    assert specs[0].indices == [0, 1, 2]
    assert specs[0].color_key == "blue"
    assert specs[0].symbol_key == "circle"


def test_single_uses_the_configured_token_and_symbol():
    specs = partition(2, [True, True], None, Encoding(color="red", symbol="diamond"))
    assert specs[0].color_key == "red"
    assert specs[0].symbol_key == "diamond"


def test_pass_fail_colour_splits_into_two_traces():
    specs = partition(3, [True, False, True], None, Encoding(color_by="pass-fail"))
    by_key = {s.color_key: s.indices for s in specs}
    assert by_key["pass"] == [0, 2]
    assert by_key["fail"] == [1]


def test_pass_fail_symbol_uses_circle_and_x():
    specs = partition(2, [True, False], None, Encoding(symbol_by="pass-fail"))
    by_sym = {s.symbol_key: s.indices for s in specs}
    assert by_sym["circle"] == [0]
    assert by_sym["x"] == [1]


def test_group_colour_makes_one_trace_per_group_in_first_seen_order():
    specs = partition(4, [True] * 4, ["b", "a", "b", "a"], Encoding(color_by="group"))
    assert [s.color_key for s in specs] == ["b", "a"]     # first-seen order
    assert specs[0].indices == [0, 2]
    assert specs[1].indices == [1, 3]


def test_colour_by_group_and_symbol_by_pass_fail_cross():
    """The headline case: batch colour, verdict symbol -- one trace per pair."""
    specs = partition(
        4, [True, False, True, False], ["a", "a", "b", "b"],
        Encoding(color_by="group", symbol_by="pass-fail"),
    )
    got = {(s.color_key, s.symbol_key): s.indices for s in specs}
    assert got[("a", "circle")] == [0]
    assert got[("a", "x")] == [1]
    assert got[("b", "circle")] == [2]
    assert got[("b", "x")] == [3]


def test_trace_name_reflects_the_meaningful_dimensions():
    single = partition(1, [True], None, Encoding())
    assert "paired" in single[0].name

    pf = partition(2, [True, False], None, Encoding(color_by="pass-fail"))
    assert {s.name for s in pf} == {"pass", "fail"}

    crossed = partition(
        2, [True, False], ["a", "a"],
        Encoding(color_by="group", symbol_by="pass-fail"),
    )
    assert {s.name for s in crossed} == {"a · pass", "a · fail"}


def test_group_encoding_without_a_group_column_is_one_untidy_trace():
    """color_by=group but no group data -> everything is the 'ungrouped' bucket."""
    specs = partition(2, [True, True], None, Encoding(color_by="group"))
    assert len(specs) == 1
    assert specs[0].color_key in ("", "ungrouped")


def test_a_none_group_value_is_its_own_bucket():
    specs = partition(3, [True] * 3, ["a", None, "a"], Encoding(color_by="group"))
    by = {s.color_key: s.indices for s in specs}
    assert by["a"] == [0, 2]
    assert set(by) - {"a"}                       # a bucket for the None too


def test_every_point_lands_in_exactly_one_trace():
    specs = partition(
        5, [True, False, True, False, True], ["a", "b", "a", "c", "b"],
        Encoding(color_by="group", symbol_by="pass-fail"),
    )
    seen = sorted(i for s in specs for i in s.indices)
    assert seen == [0, 1, 2, 3, 4]


@pytest.mark.parametrize("field, bad", [("color_by", "hue"), ("symbol_by", "shape")])
def test_invalid_channel_is_rejected(field, bad):
    from parity_plot.encoding import EncodingError

    with pytest.raises(EncodingError):
        Encoding(**{field: bad})


def test_symbol_by_group_keys_by_group_value_not_glyph():
    """The symbol channel now buckets by the group value, so a trace is named
    for the group -- the headline case: colour by verdict, shape by group."""
    specs = partition(
        4, [True, False, True, False], ["a", "a", "b", "b"],
        Encoding(color_by="pass-fail", symbol_by="group"),
    )
    got = {(s.color_key, s.symbol_key): s.indices for s in specs}
    assert got[("pass", "a")] == [0]
    assert got[("fail", "a")] == [1]
    assert got[("pass", "b")] == [2]
    assert got[("fail", "b")] == [3]
    assert {s.name for s in specs} == {"pass · a", "fail · a", "pass · b", "fail · b"}


def test_symbol_sequence_normalises_a_list_to_a_tuple():
    enc = Encoding(symbol_by="group", symbol_sequence=["circle", "square"])
    assert enc.symbol_sequence == ("circle", "square")
    hash(enc)  # frozen + hashable despite the list input


def test_symbol_sequence_accepts_variant_suffixes():
    Encoding(symbol_sequence=["circle-open", "square-dot", "diamond-open-dot"])


@pytest.mark.parametrize("bad", [["crcle"], ["circle", "definitely-not-a-symbol"], [""]])
def test_symbol_sequence_rejects_unknown_symbols(bad):
    from parity_plot.encoding import EncodingError

    with pytest.raises(EncodingError):
        Encoding(symbol_sequence=bad)


def test_single_symbol_is_validated_too():
    from parity_plot.encoding import EncodingError

    with pytest.raises(EncodingError):
        Encoding(symbol="nonsense")