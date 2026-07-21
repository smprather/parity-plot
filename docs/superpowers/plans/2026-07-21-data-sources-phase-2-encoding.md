# Data Sources Phase 2 (Marker Encoding) Implementation Plan

**Goal:** Drive marker **colour** and **symbol** independently from the data — each by a
constant, by the pass/fail verdict, or by the group column.

## Model

Two channels, each `single | pass-fail | group`:

```toml
[plot.encoding]
color_by  = "group"       # single | pass-fail | group
symbol_by = "pass-fail"
color     = "blue"        # the token used when color_by = single
symbol    = "circle"      # the symbol used when symbol_by = single
```

- **single** — every point the same: `color` token (theme-resolved) / `symbol` name.
- **pass-fail** — the overall verdict (fails ≥1 pass/fail tolerance): pass → green + circle,
  fail → red + x.
- **group** — the point's `ParityData.group` value: a qualitative colour palette / a symbol
  cycle, assigned to distinct group values in first-seen order (stable).

A point's `(colour-key, symbol-key)` pair defines which **trace** it lands in; each distinct
pair is one Plotly trace with its own legend entry. `color by group + symbol by pass-fail`
therefore yields one trace per `(group, verdict)`, named e.g. `batch3 · fail`.

## Global Constraints

- `encoding.py` is **pure** — no plotly, no theme hex. It works in *keys* (`"pass"`,
  `"fail"`, a group value, a token, a symbol name); `plot.py` resolves keys to real colours
  via the theme. So the same encoding renders correctly under dark and light.
- The **verdict reuses `tolerances.failures()`** — do not recompute pass/fail.
- Frozen dataclasses; Python 3.14; no numpy/pandas.
- **Behaviour-preserving default:** the default `Encoding` (`color_by=single`,
  `symbol_by=single`, blue circle) must render the same single trace the tool draws today,
  so the golden test still passes.

---

### Task 1: `encoding.py` — the pure partition logic

**Files:** create `parity_plot/encoding.py`, `tests/test_encoding.py`

**Interfaces produced:**
- `Encoding(color_by="single", symbol_by="single", color="blue", symbol="circle")` — validated
- `CHANNELS = ("single", "pass-fail", "group")`
- `TraceSpec(name, indices, color_key, symbol_key)` — one trace's point indices and keys
- `partition(n, verdicts, groups, enc) -> list[TraceSpec]`
  - `verdicts`: list of bool (True = pass) per paired point
  - `groups`: `list[str|None] | None` per paired point
  - Returns traces in a stable order; every point index appears in exactly one trace.
- `color_key_of(i, verdict, group, enc) -> str` / `symbol_key_of(...)` (helpers, tested)

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2–4:** implement `encoding.py` so the tests pass. Key points:
  - `Encoding.__post_init__` validates `color_by`/`symbol_by ∈ CHANNELS`.
  - `partition` computes each point's `(color_key, symbol_key)` via the channel rules, then
    groups indices by that pair **preserving first-seen order** of the pairs.
  - `color_key_of`: single → `enc.color`; pass-fail → `"pass"`/`"fail"`; group → the group
    value, or `"ungrouped"` when the group list is None/the value is None... **except** a
    real `None` value gets a distinct bucket key (e.g. `"(none)"`) so it is not merged with
    the no-group-column case. Match the tests exactly.
  - `symbol_key_of`: single → `enc.symbol`; pass-fail → `"circle"`/`"x"`; group → cycle
    through a symbol list by the group's first-seen index.
  - `TraceSpec.name`: if both channels are single → `f"paired (n=...)"` style (the caller
    passes n; here just `"paired"`); if one channel varies → that key; if both vary and
    differ → `f"{color_key} · {symbol_key}"`. Follow the name tests precisely.
- [ ] **Step 5: Stop. Do not commit.**

---

### Task 2: config `PlotConfig.encoding` + themes palette

**Files:** `config.py`, `themes.py`; tests `tests/test_encoding_config.py`

- `PlotConfig.encoding: Encoding = field(default_factory=Encoding)`.
- Parse `[plot.encoding]` as a nested table into `Encoding` (mirror how tolerances coerce a
  sub-object; validate via `Encoding.__post_init__`, wrap `EncodingError` as `ConfigError`).
- `themes.py`: add `GROUP_PALETTE` (a qualitative colour token list, per theme — reuse the
  existing `COLOR_TOKENS` order is fine) and `SYMBOL_CYCLE = ("circle","x","diamond",
  "square","triangle-up","cross","star")`; and pass/fail colours `pass_color`/`fail_color`
  per theme (green/red, distinct from the identity green — reuse tolerance red and a marker
  green, or add fields). Tests: every palette entry resolves; the cycle has ≥6 symbols.
- Detail this task's full tests/impl in its worker prompt once Task 1's `Encoding` lands.

---

### Task 3: `plot.py` renders the traces (inline, orchestrator)

`_add_paired` → `_add_encoded`: call `encoding.partition(...)` with per-point verdicts
(`not failures(...)`) and `data.group`, then draw one trace per `TraceSpec`, resolving
`color_key`/`symbol_key` to real values via the theme:

- single colour key → `theme.resolve_color(key)`; group key → `theme` palette by the
  spec's first-seen index; pass/fail key → `theme.pass_color`/`fail_color`.
- symbol key → the name directly (Plotly symbol) — single/pass-fail/group all yield a name.
- Preserve `customdata` (key, diff, verdict) and the hovertemplate per trace; keep the
  WebGL threshold per trace; keep marker opacity/size/line.

Verified visually: the headline case (`color_by=group, symbol_by=pass-fail`) renders
distinct batch colours with circle/x by verdict, and the default still matches the golden.

---

## Verification

```bash
uv run pytest
uv run parity-plot plot data/example.csv \
    --tol 'name=spec,reltol=10pct' \
    -o out/enc.png     # once the CLI/designer expose encoding (Phase 3); for now via TOML
```
Golden test still green (default encoding is behaviour-preserving).
