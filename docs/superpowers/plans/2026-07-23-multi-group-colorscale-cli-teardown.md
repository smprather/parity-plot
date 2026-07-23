# Multi-group, colorscale, CLI→TOML teardown, richer example data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add composite (multi-column) grouping and a numeric colorscale colour channel, strip all plot-setting flags from the CLI in favour of TOML, and enrich the example data — landing together on `feature/multi-group-colorscale-cli`.

**Architecture:** Composite grouping happens at the `data.py` seam (each column resolved file-independently, values joined with `, `), so `encoding.py`/`plot.py` still see one opaque label per point. The colorscale channel adds a fourth colour mode whose colour key is constant (colour is per-point, so it does not partition traces); a single numeric `file:column` rides on `ParityData` and renders as a Plotly colorbar. The CLI stops driving settings; TOML + the designer are the only ways to shape a plot, with `parity-plot init` as the discovery surface.

**Tech Stack:** Python ≥3.14, stdlib `csv`/`math`/`random`, Plotly, rich-click, NiceGUI (designer), tomlkit (serialize), uv, pytest.

## Global Constraints

- **Python floor `>=3.14`** — do not lower it.
- **No numpy or pandas** (no polars either) — stdlib `csv`/`math`/`random` only.
- **A non-numeric, non-null cell is an error**, never a silent null; errors name `file:line`.
- **Unknown TOML keys raise.**
- **Default encoding stays behaviour-preserving:** with no group columns and `color_by != "colorscale"`, every existing golden test must stay green.
- **The designer must never reimplement plotting** — it calls `build_figure`; `tests/designer/test_golden_wysiwyg.py` guards designer↔CLI figure identity.
- Run tests with `uv run pytest`. Colorscale default name is `"viridis"`.
- Commit after each task. Branch is already `feature/multi-group-colorscale-cli`.

---

## File Structure

- `parity_plot/config.py` — `DataConfig.group` → tuple (normalised in `__post_init__`); new `DataConfig.color_column`; `Encoding` import unchanged; `EXAMPLE_TOML` docs; tomlkit encoder emits `colorscale`.
- `parity_plot/encoding.py` — split `CHANNELS` into `COLOR_CHANNELS`/`SYMBOL_CHANNELS`; add `Encoding.colorscale` + validation; `color_key_of` constant under colorscale.
- `parity_plot/data.py` — `_group_lookup` multi-column composite; colour-column resolution/alignment; `ParityData.color_values`/`color_label`; `_Builder` carries colour.
- `parity_plot/plot.py` — `_add_paired` colorscale rendering + colorbar; `build_figure` guard + `has_colorbar`; `_apply_layout` colorbar/legend margins; `_drop_non_positive` carries colour.
- `parity_plot/examples.py` — richer `Record` + generators + writers.
- `parity_plot/cli.py` — teardown of `plot`/`example` flags; positional TOML; help epilog.
- `parity_plot/__init__.py` — API `group` accepts a list of column names.
- `parity_plot/designer/panels/data_panel.py` — group multiselect + colour-column select.
- `parity_plot/designer/panels/encoding.py` — colorscale channel + scale dropdown.
- Tests under `tests/` and `tests/designer/` as noted per task.
- Docs: `README.md`, `CLAUDE.md`.

---

## Task 1: `DataConfig.group` becomes a tuple (composite-ready), plus `color_column`

**Files:**
- Modify: `parity_plot/config.py` (DataConfig)
- Test: `tests/test_data_config.py`

**Interfaces:**
- Produces: `DataConfig.group: tuple[str, ...]` (default `()`), normalised from `None`/`str`/`list`/`tuple` in `__post_init__`; `DataConfig.color_column: str | None = None`.

- [ ] **Step 1: Write failing tests**

In `tests/test_data_config.py`, update the existing `group is None` / `group == "batch"` expectations and add normalisation + colour-column cases:

```python
def test_group_defaults_to_empty_tuple():
    d = DataConfig()
    assert d.join is None and d.group == () and d.color_column is None

def test_group_string_normalises_to_one_tuple():
    d = DataConfig(group="batch")
    assert d.group == ("batch",)

def test_group_list_normalises_to_tuple():
    d = DataConfig(group=["package", "vendor"])
    assert d.group == ("package", "vendor")

def test_color_column_is_a_plain_ref():
    d = DataConfig(color_column="d.csv:temperature")
    assert d.color_column == "d.csv:temperature"
```

Also update any other assertion in this file that reads `group is None` / `group == "batch"` to the tuple forms above.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_data_config.py -v`
Expected: FAIL (`group` is `None`/`"batch"`, no `color_column`).

- [ ] **Step 3: Implement**

In `parity_plot/config.py`, edit `DataConfig`:

```python
@dataclass(frozen=True)
class DataConfig:
    files: tuple[Path, ...] = ()
    ref: str | None = None
    test: str | None = None
    join: str | None = None
    # Zero or more bare, file-independent column names. A paired point's group
    # label joins the per-column values with ", " (see data._group_lookup).
    group: tuple[str, ...] = ()
    # A single file:column numeric ref driving the colorscale channel. Pinned to
    # one file (unlike group) because the same column can differ across files.
    color_column: str | None = None
    na_values: tuple[str, ...] = DEFAULT_NA_VALUES

    def __post_init__(self) -> None:
        # Accept None / "col" / ["a","b"] and store a tuple of column names, so
        # both direct construction and TOML/CLI merging converge on one shape.
        group = self.group
        if group is None:
            normalised: tuple[str, ...] = ()
        elif isinstance(group, str):
            normalised = (group,)
        else:
            normalised = tuple(str(g) for g in group)
        object.__setattr__(self, "group", normalised)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_data_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/config.py tests/test_data_config.py
git commit -m "feat(config): group is a tuple of columns; add color_column"
```

---

## Task 2: Composite group resolution in `data.py`

**Files:**
- Modify: `parity_plot/data.py` (`load`, `_group_lookup`)
- Test: `tests/test_data_load.py`

**Interfaces:**
- Consumes: `DataConfig.group: tuple[str, ...]` (Task 1).
- Produces: `data._group_lookup(src, groups: tuple[str, ...], join, na)` returning `callable(point) -> str | None`; the label is per-column values joined by `", "`, `"(none)"` for a blank slot, `None` when all slots blank. `ParityData.group` unchanged in shape (one label per paired point).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_data_load.py`:

```python
def test_two_group_columns_join_with_comma(tmp_path):
    f = write(tmp_path, "d.csv",
              "reference,test,package,vendor\n10,11,SMD,Acme\n20,22,DIP,Beta\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test",
                           group=("package", "vendor")))
    assert data.group == ["SMD, Acme", "DIP, Beta"]

def test_one_blank_slot_shows_none_token(tmp_path):
    f = write(tmp_path, "d.csv",
              "reference,test,package,vendor\n10,11,SMD,\n20,22,,Beta\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test",
                           group=("package", "vendor")))
    assert data.group == ["SMD, (none)", "(none), Beta"]

def test_all_blank_slots_is_none(tmp_path):
    f = write(tmp_path, "d.csv",
              "reference,test,package,vendor\n10,11,,\n20,22,DIP,Beta\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test",
                           group=("package", "vendor")))
    assert data.group == [None, "DIP, Beta"]

def test_single_group_column_keeps_bare_value(tmp_path):
    f = write(tmp_path, "d.csv", "reference,test,batch\n10,11,x\n20,22,y\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test",
                           group=("batch",)))
    assert data.group == ["x", "y"]  # no separator for a single column
```

The existing single-column tests (`group="batch"`) still pass because `DataConfig.__post_init__` normalises the string to `("batch",)`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_data_load.py -v`
Expected: FAIL (`_group_lookup` receives a tuple it does not handle).

- [ ] **Step 3: Implement**

In `parity_plot/data.py`, replace `_group_lookup` with a multi-column version. `load` already calls `_group_lookup(src, cfg.group, cfg.join, na) if cfg.group else None` — an empty tuple is falsy, so no change at the call site is needed.

```python
def _group_lookup(src, groups: tuple[str, ...], join: str | None, na: frozenset[str]):
    """A callable giving a paired point's composite group label.

    Each column is resolved file-independently (present in one file or several,
    values must agree across files via ``_agree``). The point's label joins the
    per-column values with ", "; a blank column contributes "(none)", and a
    point whose columns are all blank has no group (``None``).
    """
    per_column = [_one_group_lookup(src, col, join, na) for col in groups]

    def composite(point):
        parts = [fn(point) for fn in per_column]
        if all(p is None for p in parts):
            return None
        return ", ".join("(none)" if p is None else p for p in parts)

    return composite


def _one_group_lookup(src, group: str, join: str | None, na: frozenset[str]):
    """The single-column resolver (the old ``_group_lookup`` body)."""
    files = src.files_with_column(group)
    if not files:
        raise DataError(
            f"group column {group!r} not found in any open file; "
            f"available: {sorted(set(src.columns()))}"
        )
    if join:
        keyed = {
            f: dict(zip(src.tables[f][join], src.tables[f][group]))
            for f in files
            if join in src.tables[f]
        }

        def lookup(key, _keyed=keyed, _group=group):
            return _agree(
                {f: d[key] for f, d in _keyed.items() if key in d}, key, _group, na
            )

        return lookup

    columns = {f: src.tables[f][group] for f in files}

    def lookup_by_index(index, _columns=columns, _group=group):
        present = {f: v[index] for f, v in _columns.items() if index < len(v)}
        return _agree(present, str(index), _group, na)

    return lookup_by_index
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_data_load.py -v`
Expected: PASS (new and existing group tests).

- [ ] **Step 5: Commit**

```bash
git add parity_plot/data.py tests/test_data_load.py
git commit -m "feat(data): composite group labels from multiple columns"
```

---

## Task 3: Colour-column resolution → `ParityData.color_values`

**Files:**
- Modify: `parity_plot/data.py` (`ParityData`, `_Builder`, `load`, add `_color_lookup`/`_color_value`)
- Test: `tests/test_data_load.py`

**Interfaces:**
- Consumes: `DataConfig.color_column` (Task 1).
- Produces: `ParityData.color_values: list[float | None] | None = None` and `ParityData.color_label: str = ""`, aligned to paired points; `None` when no colour column (or when every value is blank).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_data_load.py`:

```python
def test_color_column_values_align_to_paired_points(tmp_path):
    f = write(tmp_path, "d.csv",
              "reference,test,temp\n10,11,25\n20,22,80\n30,29,-40\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test",
                           color_column="d.csv:temp"))
    assert data.color_values == [25.0, 80.0, -40.0]
    assert data.color_label == "temp"

def test_color_column_none_without_setting(tmp_path):
    f = write(tmp_path, "d.csv", "reference,test\n10,11\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test"))
    assert data.color_values is None

def test_color_column_blank_cell_is_none(tmp_path):
    f = write(tmp_path, "d.csv", "reference,test,temp\n10,11,25\n20,22,\n")
    data = load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test",
                           color_column="d.csv:temp"))
    assert data.color_values == [25.0, None]

def test_color_column_must_be_numeric(tmp_path):
    f = write(tmp_path, "d.csv", "reference,test,temp\n10,11,hot\n")
    with pytest.raises(DataError, match="non-numeric"):
        load(DataConfig(files=(f,), ref="d.csv:reference", test="d.csv:test",
                        color_column="d.csv:temp"))

def test_color_column_aligns_through_join(tmp_path):
    a = write(tmp_path, "a.csv", "id,v,temp\nA1,10,25\nA2,20,80\n")
    b = write(tmp_path, "b.csv", "id,v\nA1,11\nA2,22\n")
    data = load(DataConfig(files=(a, b), ref="a.csv:v", test="b.csv:v", join="id",
                           color_column="a.csv:temp"))
    assert dict(zip(data.keys, data.color_values)) == {"A1": 25.0, "A2": 80.0}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_data_load.py -k color -v`
Expected: FAIL (`ParityData` has no `color_values`).

- [ ] **Step 3: Implement**

In `parity_plot/data.py`:

Add fields to `ParityData` (after `group`):

```python
    # Per-paired-point numeric value for the colorscale channel, aligned to
    # keys/x/y; None when no colour column (or every value blank). color_label
    # is the column's display name, used as the colorbar title.
    color_values: list[float | None] | None = None
    color_label: str = ""
```

Extend `_Builder`:

```python
        self.colors: list[float | None] = []
```
in `__init__`; add `color` param to `add`:

```python
    def add(self, key, xv, yv, group=None, color=None) -> None:
        if xv is not None and yv is not None:
            self.keys.append(key)
            self.x.append(xv)
            self.y.append(yv)
            self.groups.append(group)
            self.colors.append(color)
        elif xv is not None:
            self.missing_y_keys.append(key)
            self.missing_y_vals.append(xv)
        elif yv is not None:
            self.missing_x_keys.append(key)
            self.missing_x_vals.append(yv)
        else:
            self.n_dropped += 1
```

Add a `color_label` argument to `_Builder.__init__` (default `""`) stored as `self.color_label`, and in `build()`:

```python
        color_values = self.colors if any(c is not None for c in self.colors) else None
        return ParityData(
            ...,
            group=group,
            color_values=color_values,
            color_label=self.color_label,
        )
```

In `load`, resolve the colour column and thread it through:

```python
    color_col = src.resolve(cfg.color_column) if cfg.color_column else None
    if color_col is not None:
        _require_numeric(color_col, na, "color_column")
    color_lookup = _color_lookup(src, color_col, cfg.join, na) if color_col else None

    builder = _Builder(
        x_label=ref_col.name,
        y_label=test_col.name,
        color_label=color_col.name if color_col else "",
    )
    if cfg.join:
        _load_joined(builder, src, ref_col, test_col, group_lookup, color_lookup, cfg.join, na)
    else:
        _load_by_order(builder, ref_col, test_col, group_lookup, color_lookup, na)
    return builder.build()
```

Update `_load_by_order` / `_load_joined` signatures to take `color_lookup` and pass `color=color_lookup(point) if color_lookup else None` into `builder.add(...)` (the point is the row index `i` in order mode, the join `key` in join mode — mirroring `group_lookup`).

Add the colour resolver and value parser:

```python
def _color_lookup(src, color_col, join: str | None, na: frozenset[str]):
    """A callable giving a paired point's numeric colour value.

    Pinned to the colour column's own file (no cross-file agreement): the same
    column can legitimately differ between the reference and test files.
    """
    if join:
        table = src.tables[color_col.file]
        if join not in table:
            raise DataError(
                f"{color_col.file}: colour column's file lacks join column "
                f"{join!r}; cannot align colour values"
            )
        mapping = dict(zip(table[join], color_col.values))

        def lookup(key):
            return _color_value(mapping.get(key), na)

        return lookup

    values = color_col.values

    def lookup_by_index(index):
        return _color_value(values[index] if index < len(values) else None, na)

    return lookup_by_index


def _color_value(raw: str | None, na: frozenset[str]) -> float | None:
    """Parse a colour cell to a float, or None if blank/NA.

    The whole column has already passed ``_require_numeric``, so ``float`` here
    cannot raise on a non-null cell.
    """
    if raw is None:
        return None
    text = raw.strip()
    if text.lower() in na:
        return None
    return float(text)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_data_load.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/data.py tests/test_data_load.py
git commit -m "feat(data): resolve numeric colour column into ParityData.color_values"
```

---

## Task 4: Encoding — split channels, add `colorscale`

**Files:**
- Modify: `parity_plot/encoding.py`
- Test: `tests/test_encoding.py`

**Interfaces:**
- Produces: `COLOR_CHANNELS = ("single","pass-fail","group","colorscale")`, `SYMBOL_CHANNELS = ("single","pass-fail","group")`; `Encoding.colorscale: str = "viridis"`; `color_key_of(...) == "colorscale"` (constant) when `color_by == "colorscale"`; `_validate_colorscale`.
- `CHANNELS` is retained as an alias of `SYMBOL_CHANNELS` for any external import, or removed and all references updated (see Task 12 designer + Task 6 plot).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_encoding.py`:

```python
import pytest
from parity_plot.encoding import (
    Encoding, EncodingError, color_key_of, partition, COLOR_CHANNELS, SYMBOL_CHANNELS,
)

def test_colorscale_is_a_colour_channel_only():
    assert "colorscale" in COLOR_CHANNELS
    assert "colorscale" not in SYMBOL_CHANNELS

def test_symbol_by_rejects_colorscale():
    with pytest.raises(EncodingError):
        Encoding(symbol_by="colorscale")

def test_colorscale_name_validates_and_strips_reverse_suffix():
    Encoding(color_by="colorscale", colorscale="Viridis")   # case-insensitive
    Encoding(color_by="colorscale", colorscale="viridis_r") # reverse suffix ok
    with pytest.raises(EncodingError):
        Encoding(color_by="colorscale", colorscale="notascale")

def test_colorscale_color_key_is_constant():
    # colour must not split traces under colorscale.
    k0 = color_key_of(0, True, "a", Encoding(color_by="colorscale"), has_group_column=True)
    k1 = color_key_of(1, False, "b", Encoding(color_by="colorscale"), has_group_column=True)
    assert k0 == k1 == "colorscale"

def test_colorscale_partitions_by_symbol_only():
    specs = partition(
        4, [True] * 4, ["a", "b", "a", "b"],
        Encoding(color_by="colorscale", symbol_by="group"),
    )
    assert len(specs) == 2  # one trace per symbol group, colour does not split
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_encoding.py -k colorscale -v`
Expected: FAIL (`COLOR_CHANNELS`/`colorscale` undefined).

- [ ] **Step 3: Implement**

In `parity_plot/encoding.py`:

```python
import plotly.colors as _pcolors

COLOR_CHANNELS: tuple[str, ...] = ("single", "pass-fail", "group", "colorscale")
SYMBOL_CHANNELS: tuple[str, ...] = ("single", "pass-fail", "group")
# Back-compat alias for callers that referenced the old single tuple.
CHANNELS = SYMBOL_CHANNELS

_NAMED_COLORSCALES: frozenset[str] = frozenset(_pcolors.named_colorscales())


def _validate_colorscale(name: str) -> None:
    if not isinstance(name, str) or not name.strip():
        raise EncodingError(f"colorscale must be a non-empty name, got {name!r}")
    base = name.lower()
    if base.endswith("_r"):
        base = base[:-2]
    if base not in _NAMED_COLORSCALES:
        raise EncodingError(
            f"unknown colorscale {name!r}; use a Plotly named scale "
            f"(e.g. viridis, cividis, plasma, turbo)"
        )
```

Add `colorscale: str = "viridis"` to `Encoding` and update `__post_init__`:

```python
    def __post_init__(self) -> None:
        if self.color_by not in COLOR_CHANNELS:
            raise EncodingError(
                f"color_by must be one of {COLOR_CHANNELS!r}, got {self.color_by!r}"
            )
        if self.symbol_by not in SYMBOL_CHANNELS:
            raise EncodingError(
                f"symbol_by must be one of {SYMBOL_CHANNELS!r}, got {self.symbol_by!r}"
            )
        _validate_symbol(self.symbol, where="symbol")
        _validate_colorscale(self.colorscale)
        object.__setattr__(self, "symbol_sequence", tuple(self.symbol_sequence))
        for s in self.symbol_sequence:
            _validate_symbol(s, where="symbol_sequence entry")
```

In `color_key_of`, add before the group branch:

```python
    if enc.color_by == "colorscale":
        return "colorscale"  # constant: colour is per-point, must not split traces
```

Add `"colorscale"` to `__all__`? Not required. Ensure `COLOR_CHANNELS`/`SYMBOL_CHANNELS` are exported (add to `__all__`).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_encoding.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add parity_plot/encoding.py tests/test_encoding.py
git commit -m "feat(encoding): colorscale colour channel, split colour/symbol channels"
```

---

## Task 5: Config coercion + tomlkit encoder for `colorscale`; `[data].color_column`

**Files:**
- Modify: `parity_plot/config.py` (`_coerce_encoding` already routes; encoder; `_CHOICES`/no change needed; EXAMPLE_TOML deferred to Task 11)
- Test: `tests/test_encoding_config.py`

**Interfaces:**
- Consumes: `Encoding.colorscale` (Task 4), `DataConfig.color_column` (Task 1).
- Produces: TOML `[plot.encoding].colorscale` and `[data].color_column` load and validate; unknown keys still raise; tomlkit encoder writes `colorscale` only when non-default.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_encoding_config.py`:

```python
def test_colorscale_key_loads():
    cfg = ParityConfig.from_dict({
        "plot": {"encoding": {"color_by": "colorscale", "colorscale": "plasma"}}
    })
    assert cfg.plot.encoding.color_by == "colorscale"
    assert cfg.plot.encoding.colorscale == "plasma"

def test_bad_colorscale_raises_configerror():
    import pytest
    from parity_plot.config import ConfigError
    with pytest.raises(ConfigError):
        ParityConfig.from_dict({"plot": {"encoding": {"colorscale": "nope"}}})

def test_color_column_loads_in_data_section():
    cfg = ParityConfig.from_dict({"data": {"color_column": "d.csv:temp"}})
    assert cfg.data.color_column == "d.csv:temp"
```

Add to `tests/designer/test_serialize.py`:

```python
def test_colorscale_round_trips_when_non_default():
    from parity_plot.encoding import Encoding
    from parity_plot.designer.serialize import config_to_toml
    from parity_plot.config import ParityConfig
    cfg = ParityConfig()
    cfg = cfg.merge(plot={"encoding": Encoding(color_by="colorscale", colorscale="turbo")})
    text = config_to_toml(cfg)
    assert "colorscale" in text and "turbo" in text
    # A default scale is not written.
    cfg2 = ParityConfig().merge(plot={"encoding": Encoding()})
    assert "colorscale =" not in config_to_toml(cfg2)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_encoding_config.py tests/designer/test_serialize.py -k "colorscale or color_column" -v`
Expected: FAIL (`colorscale` not emitted; `color_column` OK only if `DataConfig` accepts it — it does from Task 1, so that subtest may already pass).

- [ ] **Step 3: Implement**

`_coerce_encoding` already builds `Encoding(**value)` and raises `ConfigError` on `EncodingError`, so `colorscale` validation flows through with no change. `color_column` is a plain string field on `DataConfig` — the generic `_coerce` fallthrough returns it as-is; no special case needed.

Extend the tomlkit encoder in `config._register_tomlkit_encoding_encoder`, inside `_encode_encoding`, after `symbol_sequence`:

```python
        # Only emit a non-default scale, matching symbol_sequence's treatment.
        if value.colorscale and value.colorscale != "viridis":
            table["colorscale"] = value.colorscale
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_encoding_config.py tests/designer/test_serialize.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/config.py tests/test_encoding_config.py tests/designer/test_serialize.py
git commit -m "feat(config): colorscale + color_column TOML load and serialize"
```

---

## Task 6: Plot the colorscale channel (colorbar + layout)

**Files:**
- Modify: `parity_plot/plot.py` (`_add_paired`, `build_figure`, `_apply_layout`, `_drop_non_positive`)
- Test: `tests/test_plot.py`

**Interfaces:**
- Consumes: `ParityData.color_values`/`color_label` (Task 3), `Encoding.colorscale` + constant colour key (Task 4).
- Produces: exactly one paired trace with `marker.showscale=True` and a `colorbar` when colorscale is active; shared `cmin`/`cmax`; `build_figure` raises when `color_by=="colorscale"` and `color_values is None`; right-legend margin/x shifted to clear the colorbar.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_plot.py` (mirror the existing group-plot test style around line 315):

```python
def _scale_data():
    from parity_plot.data import ParityData
    return ParityData(
        keys=["a", "b", "c", "d"],
        x=[1.0, 2.0, 3.0, 4.0], y=[1.1, 2.1, 2.9, 4.2],
        group=["r", "r", "c", "c"],
        color_values=[10.0, 20.0, 30.0, 40.0], color_label="temp",
        x_label="ref", y_label="test",
    )

def test_colorscale_draws_one_colorbar():
    from parity_plot.plot import build_figure
    from parity_plot.config import PlotConfig
    from parity_plot.encoding import Encoding
    fig = build_figure(_scale_data(),
                       PlotConfig(encoding=Encoding(color_by="colorscale",
                                                    symbol_by="group",
                                                    colorscale="turbo")))
    paired = [t for t in fig.data if t.mode == "markers" and t.marker.symbol]
    showscale = [t for t in paired if t.marker.showscale]
    assert len(showscale) == 1                      # single shared colorbar
    assert showscale[0].marker.colorbar.title.text == "temp"
    cmins = {t.marker.cmin for t in paired if t.marker.color and not isinstance(t.marker.color, str)}
    assert cmins == {10.0}                           # shared cmin across groups

def test_colorscale_partitions_by_symbol():
    from parity_plot.plot import build_figure
    from parity_plot.config import PlotConfig
    from parity_plot.encoding import Encoding
    fig = build_figure(_scale_data(),
                       PlotConfig(encoding=Encoding(color_by="colorscale", symbol_by="group")))
    paired = [t for t in fig.data if t.mode == "markers" and hasattr(t.marker, "colorscale") and t.marker.colorscale]
    assert len(paired) == 2                           # one trace per symbol group

def test_colorscale_without_column_raises():
    import pytest
    from parity_plot.plot import build_figure
    from parity_plot.config import PlotConfig
    from parity_plot.encoding import Encoding
    from parity_plot.data import ParityData
    d = ParityData(keys=["a"], x=[1.0], y=[1.0])
    with pytest.raises(ValueError, match="color_column"):
        build_figure(d, PlotConfig(encoding=Encoding(color_by="colorscale")))

def test_colorbar_and_right_legend_do_not_overlap():
    from parity_plot.plot import build_figure
    from parity_plot.config import PlotConfig
    from parity_plot.encoding import Encoding
    fig = build_figure(_scale_data(),
                       PlotConfig(encoding=Encoding(color_by="colorscale", symbol_by="group"),
                                  legend="right"))
    assert fig.layout.legend.x >= 1.15               # legend pushed right of the colorbar
    assert fig.layout.margin.r >= 260
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_plot.py -k colorscale -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `parity_plot/plot.py`:

`build_figure` — compute the guard + flag and pass through:

```python
    is_scale = plot.encoding.color_by == "colorscale"
    if is_scale and data.color_values is None:
        raise ValueError(
            "color_by=colorscale needs a numeric colour column; set "
            "[data].color_column"
        )
    ...
    _add_paired(fig, data, plot.tolerances, plot.encoding, theme)
    ...
    _apply_layout(fig, data, plot, theme, summary, lo, hi, has_colorbar=is_scale)
```

`_add_paired` — branch on colorscale:

```python
def _add_paired(fig, data, tolerances, encoding, theme):
    scatter = go.Scattergl if data.n_paired > _WEBGL_THRESHOLD else go.Scatter
    diffs = [yi - xi for xi, yi in zip(data.x, data.y)]
    verdicts = [verdict_text(failures(tolerances, xi, yi)) for xi, yi in zip(data.x, data.y)]
    passes = [failures(tolerances, xi, yi) == () for xi, yi in zip(data.x, data.y)]

    specs = partition(data.n_paired, passes, data.group, encoding)
    symbols = _resolve_symbols(specs, encoding)

    is_scale = encoding.color_by == "colorscale"
    colours = None if is_scale else _resolve_colours(specs, encoding, theme)
    if is_scale:
        finite = [c for c in data.color_values if c is not None]
        cmin, cmax = (min(finite), max(finite)) if finite else (0.0, 1.0)

    for i, spec in enumerate(specs):
        idx = spec.indices
        name = spec.name if len(specs) > 1 else f"paired (n={data.n_paired:,})"
        if is_scale:
            marker = dict(
                color=[data.color_values[j] for j in idx],
                colorscale=encoding.colorscale,
                cmin=cmin, cmax=cmax,
                showscale=(i == 0),
                colorbar=dict(
                    title=data.color_label, x=1.02, xanchor="left",
                    thickness=14, len=0.6, y=0.5, yanchor="middle",
                ) if i == 0 else None,
                symbol=symbols[spec.symbol_key],
                opacity=theme.marker_opacity, size=7,
                line=dict(color=theme.marker_line, width=0.5),
            )
        else:
            marker = dict(
                color=colours[spec.color_key],
                symbol=symbols[spec.symbol_key],
                opacity=theme.marker_opacity, size=7,
                line=dict(color=theme.marker_line, width=0.5),
            )
        fig.add_trace(scatter(
            x=[data.x[j] for j in idx], y=[data.y[j] for j in idx],
            mode="markers", name=name,
            customdata=[(data.keys[j], diffs[j], verdicts[j]) for j in idx],
            marker=marker,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                f"{data.x_label}: %{{x:.4g}}<br>"
                f"{data.y_label}: %{{y:.4g}}<br>"
                "difference: %{customdata[1]:+.4g}<br>"
                "%{customdata[2]}<extra></extra>"
            ),
        ))
```

`_apply_layout` — accept `has_colorbar` and clear the colorbar:

```python
def _apply_layout(fig, data, plot, theme, summary, lo, hi, has_colorbar=False):
    ...
    placement, margin = _LEGEND_LAYOUTS[plot.legend]
    if has_colorbar:
        if plot.legend == "right" and placement is not None:
            placement = {**placement, "x": 1.16}
            margin = {**margin, "r": 300}
        else:
            margin = {**margin, "r": max(margin["r"], 110)}
    ...
    fig.update_layout(..., margin=margin)
    if placement is not None:
        fig.update_layout(legend=placement)
```

`_drop_non_positive` (log mode) — carry colour in lockstep so it stays aligned:

```python
def _drop_non_positive(data):
    colors = data.color_values if data.color_values is not None else [None] * data.n_paired
    paired = [
        (k, xi, yi, ci)
        for k, xi, yi, ci in zip(data.keys, data.x, data.y, colors)
        if xi > 0 and yi > 0
    ]
    ...
    return replace(
        data,
        keys=[k for k, _, _, _ in paired],
        x=[xi for _, xi, _, _ in paired],
        y=[yi for _, _, yi, _ in paired],
        color_values=(
            [ci for _, _, _, ci in paired] if data.color_values is not None else None
        ),
        missing_y=missing_y, missing_x=missing_x,
    )
```

Note: `_drop_non_positive` does not currently re-slice `group`; that pre-existing behaviour is out of scope here (a follow-up), but do not regress it.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_plot.py -v`
Expected: PASS (including existing 45°/group tests).

- [ ] **Step 5: Commit**

```bash
git add parity_plot/plot.py tests/test_plot.py
git commit -m "feat(plot): render colorscale channel as a shared colorbar"
```

---

## Task 7: Richer example data

**Files:**
- Modify: `parity_plot/examples.py` (`Record`, `generate`, `write_wide`, `write_pair`)
- Test: `tests/test_examples.py`

**Interfaces:**
- Produces: example CSVs carrying `package`, `vendor` (categorical) and `temperature` (numeric) columns, deterministic under the seed. Wide file header: `id, reference, test, package, vendor, temperature`. `reference.csv` header: `id, value, package, vendor, temperature`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_examples.py`:

```python
def test_wide_file_has_rich_columns(tmp_path):
    from parity_plot import examples
    out = examples.write_all(tmp_path, examples.ExampleSpec(n=20, seed=3))
    header = out["wide"].read_text().splitlines()[0].split(",")
    assert header == ["id", "reference", "test", "package", "vendor", "temperature"]

def test_pair_reference_carries_group_and_colour(tmp_path):
    from parity_plot import examples
    out = examples.write_all(tmp_path, examples.ExampleSpec(n=20, seed=3))
    header = out["reference"].read_text().splitlines()[0].split(",")
    assert header == ["id", "value", "package", "vendor", "temperature"]

def test_categoricals_come_from_a_small_vocabulary(tmp_path):
    from parity_plot import examples
    recs = examples.generate(examples.ExampleSpec(n=200, seed=3))
    assert {r.package for r in recs} <= {"SMD", "DIP", "BGA", "QFN"}
    assert {r.vendor for r in recs} <= {"Acme", "Beta", "Ceres"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_examples.py -k "rich or carries or vocabulary" -v`
Expected: FAIL (`Record` has no `package`).

- [ ] **Step 3: Implement**

In `parity_plot/examples.py`:

```python
_PACKAGES = ("SMD", "DIP", "BGA", "QFN")
_VENDORS = ("Acme", "Beta", "Ceres")


@dataclass(frozen=True)
class Record:
    key: str
    reference: float | None
    measured: float | None
    package: str = ""
    vendor: str = ""
    temperature: float | None = None
```

In `generate`, inside the build loop, draw the extra fields from the same `rng` (temperature spans a realistic range; light coupling to disparity keeps the colorbar meaningful):

```python
        package = rng.choice(_PACKAGES)
        vendor = rng.choice(_VENDORS)
        temperature = rng.uniform(-40.0, 125.0)
        records.append(Record(
            key=f"S{i:04d}", reference=x, measured=y,
            package=package, vendor=vendor, temperature=temperature,
        ))
```

Preserve the categorical/temperature fields when carving nulls (the `Record(...)` rewrites in the null loops must copy `package`/`vendor`/`temperature`):

```python
    for i in drop_y:
        r = records[i]
        records[i] = Record(r.key, r.reference, None, r.package, r.vendor, r.temperature)
    for i in drop_x:
        r = records[i]
        records[i] = Record(r.key, None, r.measured, r.package, r.vendor, r.temperature)
    for i in drop_both:
        r = records[i]
        records[i] = Record(r.key, None, None, r.package, r.vendor, r.temperature)
```

`write_wide` — extend header and rows:

```python
        writer.writerow(["id", "reference", "test", "package", "vendor", "temperature"])
        for rec in records:
            writer.writerow([
                rec.key, _fmt(rec.reference), _fmt(rec.measured),
                rec.package, rec.vendor, _fmt(rec.temperature),
            ])
```

`write_pair` — put the group + colour columns in `reference.csv` (they resolve for paired points; unpaired rows are simply absent). Keep `measured.csv` as `id,value` only:

```python
    for path, attr in ((x_path, "reference"), (y_path, "measured")):
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            if attr == "reference":
                writer.writerow(["id", "value", "package", "vendor", "temperature"])
            else:
                writer.writerow(["id", "value"])
            for rec in records:
                value = getattr(rec, attr)
                if value is None:
                    continue
                if attr == "reference":
                    writer.writerow([rec.key, _fmt(value), rec.package, rec.vendor, _fmt(rec.temperature)])
                else:
                    writer.writerow([rec.key, _fmt(value)])
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_examples.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/examples.py tests/test_examples.py
git commit -m "feat(examples): richer data (package, vendor, temperature)"
```

---

## Task 8: CLI teardown — `plot` and `example`

**Files:**
- Modify: `parity_plot/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `plot` takes a positional TOML path (default `parity.toml`), plus `-o/--output` and `--open-browser`; a missing config raises a message naming `parity-plot init`. `example` keeps generator + operational flags, drops appearance flags. `cli._default_ref_test` removed. Help epilog on `plot` routes to `init`.

- [ ] **Step 1: Write failing tests**

Rewrite `tests/test_cli.py` around the new surface. Representative tests (use Click's `CliRunner` as the existing file does):

```python
from click.testing import CliRunner
from parity_plot.cli import cli

def test_plot_reads_a_toml_and_writes(tmp_path):
    (tmp_path / "d.csv").write_text("reference,test\n10,11\n20,22\n", encoding="utf-8")
    cfg = tmp_path / "p.toml"
    cfg.write_text(
        '[data]\nfiles=["d.csv"]\nref="d.csv:reference"\ntest="d.csv:test"\n'
        '[output]\npath="out.html"\n', encoding="utf-8")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # run inside tmp_path so relative paths resolve
        pass
    result = runner.invoke(cli, ["plot", str(cfg), "-o", str(tmp_path / "out.html"),
                                 "--no-open-browser"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out.html").exists()

def test_plot_missing_config_points_at_init(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["plot", str(tmp_path / "nope.toml"), "--no-open-browser"])
    assert result.exit_code != 0
    assert "init" in result.output

def test_plot_help_has_no_appearance_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["plot", "--help"])
    for gone in ("--theme", "--ref", "--tol", "--legend", "--width"):
        assert gone not in result.output
    assert "init" in result.output  # epilog routes to init

def test_example_keeps_generator_flags_drops_appearance():
    runner = CliRunner()
    result = runner.invoke(cli, ["example", "--help"])
    assert "--noise" in result.output and "--bias" in result.output
    for gone in ("--theme", "--legend", "--abstol", "--width"):
        assert gone not in result.output
```

Adjust the relative-path handling to match the existing test file's approach (it already writes CSVs under `tmp_path`); the key assertions are: positional TOML works, missing TOML mentions `init`, appearance flags are gone from both `--help` outputs.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `parity_plot/cli.py`:

- Delete `_default_ref_test`.
- Rewrite the `plot` command:

```python
@cli.command()
@click.argument("config", required=False, default="parity.toml",
                type=click.Path(dir_okay=False, path_type=Path))
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path),
              help="Override where the plot is written (path only).")
@click.option("--open-browser/--no-open-browser", "open_browser", default=True,
              help="Open the result in the default browser after writing.  [default: open]")
def plot(config: Path, output: Path | None, open_browser: bool) -> None:
    """Render a parity plot from a TOML **CONFIG** (default `parity.toml`).

    Every plot and data setting lives in the TOML. Run `parity-plot init` to
    write a fully-commented template, or `parity-plot design` to edit visually.
    """
    try:
        if not Path(config).exists():
            raise click.ClickException(
                f"config file not found: {config}. Run `parity-plot init` to "
                f"create one, or pass a path to an existing TOML."
            )
        cfg = ParityConfig.from_toml(config)
        if output is not None:
            fmt = _infer_format(output, None)
            cfg = cfg.merge(output={"path": output, "format": fmt})
        data = load(cfg.data)
        figure = build_figure(data, cfg.plot, cfg.stats)
        written = save(figure, cfg.output)
    except (ConfigError, DataError, ExportError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None

    click.echo(
        f"Wrote {click.style(str(written), bold=True)} — "
        f"{data.n_paired:,} paired, {data.n_unpaired:,} unpaired, "
        f"{data.n_dropped:,} empty"
    )
    if open_browser:
        webbrowser.open(written.resolve().as_uri())
```

- Trim the `example` command: remove the options `--theme --abstol --reltol --tol --no-tolerance --band-style --legend --width --height` and their parameters. Its auto-plot builds the config without them:

```python
        wide = written["wide"]
        cfg = ParityConfig().merge(
            data={"files": (wide,), "ref": f"{wide.name}:reference",
                  "test": f"{wide.name}:test"},
            output={"path": output, "format": _infer_format(output, None)},
        )
        data = load(cfg.data)
        written_plot = save(build_figure(data, cfg.plot, cfg.stats), cfg.output)
```

- Update `HELP_CONFIG.option_groups`: for `parity-plot plot` keep only `["CONFIG", "--output", "--open-browser", "--help"]`; for `parity-plot example` drop the removed flags from the "Plot" group (keep `--plot`, `--output`, `--open-browser`). Remove now-unused imports (`build_tolerances`, `TolSpecError`, `parse_reltol`, `RELTOL`, `BAND_STYLES`, `LEGEND_POSITIONS`, `NULL_MODES`, `THEMES` if no longer referenced — verify before deleting).
- Set a `plot` help epilog routing to `init` (either via the docstring, already mentioning `init`, or `@click.command(epilog=...)`). The test only requires the string `init` to appear in `plot --help`, which the docstring satisfies.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/cli.py tests/test_cli.py
git commit -m "feat(cli): TOML-only plotting; strip plot-setting flags"
```

---

## Task 9: Public API accepts a list of group columns

**Files:**
- Modify: `parity_plot/__init__.py`
- Test: `tests/test_data.py` (or wherever the `parity_plot(...)` API is tested)

**Interfaces:**
- Consumes: `DataConfig.group` tuple (Task 1).
- Produces: `parity_plot(..., group=["package","vendor"])` in the file case sets `data.group=("package","vendor")`.

- [ ] **Step 1: Write failing test**

Add to the API test module:

```python
def test_api_accepts_multiple_group_columns(tmp_path):
    from parity_plot import parity_plot
    f = tmp_path / "d.csv"
    f.write_text("reference,test,package,vendor\n10,11,SMD,Acme\n20,22,DIP,Beta\n",
                 encoding="utf-8")
    fig = parity_plot(str(f), ref=f"{f.name}:reference", test=f"{f.name}:test",
                      group=["package", "vendor"])
    # one trace per composite group when colour-by-group is on by default? No:
    # default encoding is single; just assert it builds and groups resolved.
    assert fig is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_data.py -k multiple_group -v`
Expected: FAIL (list dropped to `None`).

- [ ] **Step 3: Implement**

In `parity_plot/__init__.py`, in the file (column) branch, pass a str or list-of-str `group` through (coercion/`__post_init__` normalises it to a tuple):

```python
        data_overrides = {
            "ref": ref,
            "test": test,
            "join": join,
        }
        if group is not None and isinstance(group, (str, list, tuple)):
            data_overrides["group"] = group
        if paths:
            data_overrides["files"] = tuple(Path(p) for p in paths)
```

Leave the in-memory branch (`from_sequences(..., group=group_seq)`) unchanged: there `group` is a per-point sequence.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_data.py -k group -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/__init__.py tests/test_data.py
git commit -m "feat(api): group accepts a list of column names"
```

---

## Task 10: Designer — group multiselect + colour-column picker

**Files:**
- Modify: `parity_plot/designer/panels/data_panel.py`
- Test: `tests/designer/test_data_panel.py`

**Interfaces:**
- Consumes: `DataConfig.group` tuple, `color_column` (Task 1).
- Produces: `column_options(...)` gains a `"color_column"` key (numeric `file:column`); the panel binds group as a list and sets `data.color_column`.

- [ ] **Step 1: Write failing test**

In `tests/designer/test_data_panel.py`, extend the options expectations:

```python
def test_options_include_numeric_colour_column(tmp_path):
    from parity_plot.designer.panels.data_panel import column_options
    f = tmp_path / "d.csv"
    f.write_text("id,voltage,batch\n1,10,x\n2,20,y\n", encoding="utf-8")
    opts = column_options((f,))
    assert "color_column" in opts
    assert opts["color_column"] == ["d.csv:voltage"]   # numeric only
```

Update the existing `column_options` assertions (`== {"ref": ..., "group": ..., "join": ...}`) to include the new `"color_column"` key so the empty-options tests still match.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/designer/test_data_panel.py -v`
Expected: FAIL (no `color_column` key).

- [ ] **Step 3: Implement**

In `column_options`, add `"color_column": list(numeric)` to the returned dict and to the `empty` dict. In `build_data_panel`:

- Make the group select multiple, bound to the tuple:

```python
        group_sel = ui.select(
            options["group"], value=list(state.config.data.group), multiple=True,
            label="Group by (one or more columns)",
        ).classes("w-full").props("use-chips")
```

- Add a colour-column select:

```python
        color_sel = ui.select(
            [_NONE, *options["color_column"]],
            value=state.config.data.color_column or _NONE,
            label="Colour column (numeric, for colorscale)",
        ).classes("w-full")
```

- In `refresh_options`, refresh `group_sel.options = opts["group"]` and `color_sel.options = [_NONE, *opts["color_column"]]`.
- In `apply`, pass both:

```python
            ok = state.set_data_source(
                files=tuple(files),
                ref=ref_sel.value or None,
                test=test_sel.value or None,
                join=None if join_sel.value == _NONE else join_sel.value,
                group=tuple(group_sel.value or ()),
                color_column=None if color_sel.value == _NONE else color_sel.value,
            )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/designer/test_data_panel.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/panels/data_panel.py tests/designer/test_data_panel.py
git commit -m "feat(designer): multi-column group + colour-column picker"
```

---

## Task 11: Designer encoding panel — colorscale channel + scale dropdown; EXAMPLE_TOML

**Files:**
- Modify: `parity_plot/designer/panels/encoding.py`, `parity_plot/config.py` (`EXAMPLE_TOML`)
- Test: `tests/designer/test_golden_wysiwyg.py`

**Interfaces:**
- Consumes: `COLOR_CHANNELS`/`SYMBOL_CHANNELS`, `Encoding.colorscale` (Task 4), `named_colorscales`.
- Produces: colour-by select offers `colorscale`; a colorscale dropdown visible only under it; `EXAMPLE_TOML` documents `group` list, `color_column`, `color_by="colorscale"`, `colorscale`.

- [ ] **Step 1: Write failing test**

Add a golden WYSIWYG case in `tests/designer/test_golden_wysiwyg.py` mirroring the existing pattern: build a config with `Encoding(color_by="colorscale", symbol_by="group", colorscale="turbo")` and `color_column` set on data, render through the designer `state.figure()` and through the CLI `build_figure`, assert the two figures are equal (same assertion helper the file already uses).

```python
def test_colorscale_multigroup_designer_matches_cli(tmp_path):
    # ... write a CSV with reference,test,package,vendor,temp
    # build DesignerState with data.color_column="d.csv:temp",
    #   group=("package","vendor"),
    #   plot.encoding=Encoding(color_by="colorscale", symbol_by="group", colorscale="turbo")
    # assert figures_equal(state.figure(), build_figure(load(cfg.data), cfg.plot, cfg.stats))
```

Use the module's existing helpers (config construction + figure-equality). If the file compares JSON, reuse that comparison.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/designer/test_golden_wysiwyg.py -v`
Expected: FAIL initially only if the panel/select is wired wrong; the figure equality itself should pass once Tasks 3–6 are in. (If it already passes, that confirms designer↔CLI parity; keep the test.)

- [ ] **Step 3: Implement**

In `parity_plot/designer/panels/encoding.py`:

- Import `COLOR_CHANNELS, SYMBOL_CHANNELS` (and `named_colorscales` from plotly): use `COLOR_CHANNELS` for the colour-by select options and `SYMBOL_CHANNELS` for the symbol-by select. Extend `_CHANNEL_LABELS` with `"colorscale": "colour scale"`.
- Add a colorscale dropdown, visible only when `color_by == "colorscale"`:

```python
        from plotly.colors import named_colorscales
        scale_pick = ui.select(
            sorted(named_colorscales()), value=enc.colorscale,
            on_change=lambda: commit(),
        ).classes("w-40")
        scale_pick.bind_visibility_from(color_by, "value", value="colorscale")
```

- Include `colorscale=scale_pick.value or "viridis"` in the `Encoding(...)` built by `commit()`.

In `parity_plot/config.py`, update `EXAMPLE_TOML`: document `group` as a list (`group = ["package", "vendor"]`), add `color_column = "data/example.csv:temperature"` under `[data]` (commented), and in the `[plot.encoding]` block document `color_by = "colorscale"` and `colorscale = "viridis"` with a note that scales come from Plotly's named set.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/designer -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add parity_plot/designer/panels/encoding.py parity_plot/config.py tests/designer/test_golden_wysiwyg.py
git commit -m "feat(designer): colorscale channel + scale picker; document TOML"
```

---

## Task 12: Full suite green + docs (README, CLAUDE.md)

**Files:**
- Modify: `README.md`, `CLAUDE.md`
- Test: whole suite

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest`
Expected: PASS. Fix any straggler references to `CHANNELS`, `DataConfig.group` as a string, or removed CLI flags (search: `grep -rn "CHANNELS\|_default_ref_test\|--theme\|--ref" parity_plot tests`).

- [ ] **Step 2: Update README**

- Remove the CLI flag tables / any "every key has a matching CLI flag" claim for plot settings.
- Document: plotting is TOML-driven (`parity-plot init` → edit → `parity-plot plot parity.toml`), the designer, composite `group` (list), `color_column` + `color_by="colorscale"` + `colorscale`.

- [ ] **Step 3: Update CLAUDE.md**

- Rewrite the "Encoding has no CLI flags" note: the CLI no longer drives any plot/data setting; TOML + designer only; `init` is the discovery surface. Update the rich-click `OPTION_GROUPS` gotcha to reflect the slimmed commands.
- Note `group` is now a tuple of file-independent columns (composite label `", "`-joined), and `color_column` is a single pinned `file:column` numeric ref feeding the colorscale channel (colorbar, not legend).

- [ ] **Step 4: Regenerate example + screenshot (per project convention)**

Run: `uv run parity-plot example --no-plot` then render a showcase config through the CLI to a PNG under `docs/images/` (needs `uv run plotly_get_chrome` once). Show the PNG inline.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md docs/images
git commit -m "docs: TOML-only CLI, composite group, colorscale"
```

---

## Self-Review

**Spec coverage:**
- Composite group → Tasks 1, 2, 9, 10. ✅
- Colorscale (data/encoding/plot/config/designer) → Tasks 1, 3, 4, 5, 6, 10, 11. ✅
- CLI teardown → Task 8 (+ docs Task 12). ✅
- Richer example data → Task 7. ✅
- Designer controls + serialize + golden WYSIWYG → Tasks 5, 10, 11. ✅
- Docs (README/CLAUDE.md/EXAMPLE_TOML) → Tasks 11, 12. ✅
- Non-goal (hover-text) correctly excluded; only example columns staged. ✅

**Type consistency:** `DataConfig.group: tuple[str,...]`; `_group_lookup(src, groups: tuple, ...)`; `ParityData.color_values: list[float|None]|None`, `color_label: str`; `_add_paired`/`_apply_layout` gain `has_colorbar`; `Encoding.colorscale: str`; `COLOR_CHANNELS`/`SYMBOL_CHANNELS` used consistently in encoding + designer. Consistent across tasks.

**Known edge (documented, accepted):** a colour column that is entirely blank resolves to `color_values=None` and trips the colorscale guard — a genuinely unusable case; message could be refined later. `_drop_non_positive` re-slices colour but not group (pre-existing gap, not regressed here).
