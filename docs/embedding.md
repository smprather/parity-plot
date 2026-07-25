# Embedding parity plots in an app

How to put several parity plots on one page, minimally and correctly. Written to
be read start-to-finish by whoever (or whatever) is building the consuming app.

Every number and behaviour here was verified against plotly.js v3.7.0 as shipped
in the plotly wheel that parity-plot depends on.

## The contract

parity-plot produces **Plotly figures**. It does not own your page, and it never
ships a runtime of its own. You get three output shapes:

| shape | call | contains |
|---|---|---|
| standalone document | `save(fig, OutputConfig(path="p.html"))` | full `<html>`, plotly.js inlined (~4.9 MB) |
| **fragment** | `to_fragment(fig, div_id=...)` | a `<div>` + `<script>`, **no library** |
| figure data | `fig.to_json()` | `{"data": [...], "layout": {...}}` |

For a multi-plot page you want the second or third. The first is for handing a
single self-contained file to a person.

## Choosing between fragments and JSON

**Use fragments** when the HTML is generated ahead of time — a static site, a
Jinja/Hugo/Eleventy template, a server-rendered page. The fragment is emitted
into the document body at build time.

**Use `to_json()`** when plots are created, replaced, or inserted **after** the
page has loaded — a React/Vue/Svelte app, tab switching, filtering, live data.

This is not a style preference. It is a hard constraint:

> **Inline `<script>` tags inserted via `innerHTML` never execute.** That is the
> HTML5 spec, not a browser quirk. A fragment's plot is drawn by its own inline
> script, so `el.innerHTML = fragment` inserts a visible but permanently empty
> div, with no error in the console.

If you are assigning HTML into the DOM at runtime, you must use the JSON path.

## Getting plotly.min.js, exactly once

The library is already on the machine that generates the plots — inside the
plotly wheel. It is **minified** (`plotly.min.js`, 4,851,164 bytes; no
unminified variant ships). Copy it into your static assets:

```bash
uv run python -c "import plotly, pathlib, shutil; \
shutil.copy(pathlib.Path(plotly.__file__).parent / 'package_data' / 'plotly.min.js', \
            'static/plotly.min.js')"
```

Prefer this over a CDN URL for two reasons: it works offline, and it is
**guaranteed to be the same version** that rendered your figures, because it came
from the same wheel.

Two alternatives:

- `[output].plotlyjs = "directory"` on any one plot writes `plotly.min.js` beside
  its HTML for you.
- A CDN `<script src>` if the app is online-only. One cached download shared
  across every plot, ~1.4 MB gzipped.

**Serve it compressed.** Measured on this exact file: 4,851,164 raw → 1,463,784
gzip -9 → 1,097,899 brotli -q 11. Any static host enables this with one config
line; without it you ship 4.4× the bytes you need to.

## Minimal complete page

Three plots, one library, nothing else:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <!-- MUST be a plain script. Not defer, not type="module". See below. -->
  <script src="/static/plotly.min.js"></script>
  <style>
    /* Fragments are height:100%. Their container MUST have a real height. */
    .plot { width: 100%; height: 480px; }
  </style>
</head>
<body>
  <div class="plot">{{ fragment_run7 }}</div>
  <div class="plot">{{ fragment_run8 }}</div>
  <div class="plot">{{ fragment_run9 }}</div>
</body>
</html>
```

Generating those three:

```python
from parity_plot import parity_plot, to_fragment

for name in ("run7", "run8", "run9"):
    fragment = to_fragment(parity_plot(config=f"configs/{name}.toml"), div_id=name)
    (out / f"{name}.html").write_text(fragment, encoding="utf-8")
```

Or entirely from TOML, with no Python of your own:

```toml
[output]
path = "site/_includes/run7.html"
embed = true            # plotlyjs resolves to "none" automatically
div_id = "parity-run7"  # pin it; see Determinism
```

## The five constraints that actually break things

### 1. The container must have a height

A fragment's outer div is literally `style="height:100%; width:100%"`. CSS
`height: 100%` against a parent of `height: auto` resolves to **zero**. The plot
is inserted, the script runs without error, and you see nothing.

Give the wrapper a concrete height — `height: 480px`, an aspect-ratio box, or a
grid/flex track with a definite size. This is the single most common failure.

Parity plots are square by nature (both axes share one range), so a square-ish
container reads best; the figure will letterbox itself inside a wide one rather
than distort, because `constrain="domain"` protects the 45° geometry.

### 2. plotly.js must be loaded before any fragment runs

A fragment contains a **plain `<script>`**, which executes synchronously the
moment the parser reaches it. If you load the library with `defer` or
`type="module"`, it is still queued when that inline script runs and you get
`Uncaught ReferenceError: Plotly is not defined`.

Either a plain `<script src>` in `<head>`, or a plain `<script src>` earlier in
`<body>` than the first fragment. Both are fine; `defer`/`async`/`module` are
not.

### 3. Fragments cannot be injected with innerHTML

Covered above. Build-time insertion only. Runtime insertion uses the JSON path.

### 4. Resize: `responsive: true` covers the *window*, not the container

Fragments are emitted with `{"responsive": true}`, so plotly installs its own
**window**-resize handler. You get free reflow when the browser window changes,
and you do **not** need to write anything for that case.

What it does not catch is the container changing size while the window does not:
a collapsing sidebar, a CSS grid reflow, a tab or accordion becoming visible, a
split pane being dragged. For those:

```js
const ro = new ResizeObserver(entries => {
  for (const e of entries) Plotly.Plots.resize(e.target);
});
document.querySelectorAll('.plotly-graph-div').forEach(d => ro.observe(d));
```

A plot revealed inside a previously-hidden tab or accordion needs one
`Plotly.Plots.resize(div)` when it becomes visible, because it was laid out at
zero size. **This does not fail loudly — it fails plausibly.**

Here is the same plot revealed from a `display:none` tab panel, with and without
that one call. Both were captured from `examples/tabbed-report`:

| with `Plotly.Plots.resize` | without it |
|---|---|
| ![Correctly sized parity plot filling its tab panel, with a complete legend.](images/embed-tab-resized.png) | ![The same plot at a stale smaller layout: subtitle overlapping the modebar and the legend clipped behind a scrollbar.](images/embed-tab-stale.png) |

Note what the broken one is *not*: it is not blank, and it throws nothing. It is
laid out for the box the panel had while hidden — undersized, the subtitle
colliding with the modebar, and **three legend entries clipped behind a
scrollbar**, so a reader silently loses the fact that some groups exist at all.

The geometry is at risk for the same reason. The 45° line is true only while both
axes share one range, their pixel scales are locked (`scaleanchor`/`scaleratio`),
**and** `constrain="domain"` is set. Against stale dimensions Plotly satisfies the
pixel ratio for a box the page no longer has, so when the real container's aspect
ratio differs from the stale one the parity line stops being the diagonal. Never
conclude the plot is fine because nothing threw.

### 5. WebGL context limits on a page of large plots

Above **5,000 paired points** a parity plot's marker trace is rendered as
`scattergl` instead of `scatter`. The boundary is exact and verified: 5,000
points yields `type: "scatter"`, 5,001 yields `type: "scattergl"`. WebGL keeps a
large plot interactive, but browsers allow only roughly **8–16 simultaneous
WebGL contexts**.
Past that, the oldest contexts are evicted and those plots render **blank**.

For a page of many large plots, pick one:

- **Render lazily** and keep the live count bounded — the standard fix:

  ```js
  const io = new IntersectionObserver((entries, obs) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      drawPlot(e.target);          // Plotly.newPlot on first reveal
      obs.unobserve(e.target);
    }
  }, { rootMargin: '200px' });
  ```

  This needs the JSON path, since drawing is deferred to JS.

- **Downsample** before plotting so each figure stays under 5,000 points.

- **Force SVG** by rewriting the trace type in the figure JSON:

  ```python
  spec = json.loads(fig.to_json())
  for trace in spec["data"]:
      if trace.get("type") == "scattergl":
          trace["type"] = "scatter"
  ```

  SVG has no context limit but gets sluggish past a few thousand markers, so this
  suits small-multiples, not 100k-point plots. There is deliberately no config key
  for this yet — `plot._WEBGL_THRESHOLD` is a module constant.

## The dynamic path in full

```python
# server side, one endpoint per plot (or one returning many)
from parity_plot import parity_plot

figure_json = parity_plot(
    config="configs/run7.toml"
).to_json()  # {"data":…, "layout":…}
```

```js
// client side
const spec = await (await fetch('/api/plots/run7')).json();
Plotly.newPlot(document.getElementById('run7'), spec.data, spec.layout,
               { responsive: true });

// replacing data later in the same div — cheaper and keeps zoom/pan state
Plotly.react(document.getElementById('run7'), next.data, next.layout,
             { responsive: true });
```

Pass `{ responsive: true }` yourself here: it is a `to_html` nicety, not part of
`to_json()`.

Payload is data only — tens of KB for a thousand points against the flat 4.9 MB
of library that a standalone file repeats per plot.

## Determinism, for caches and diffs

Without an explicit `div_id`, plotly generates a random UUID per fragment. The
same input then produces a byte-different fragment on every run, which defeats
content hashing, ETags, and `git diff` on generated output. Always pass `div_id`
(or set `[output].div_id`) for build-time output.

## Themes

Each figure carries its own Plotly template, so `theme = "dark"` and
`theme = "light"` plots can coexist on one page. Two practical notes: match the
figures to your page background or the plot area will float in a mismatched
rectangle, and switching your app's theme at runtime does **not** restyle already
-drawn plots — re-issue `Plotly.react` with a figure built at the new theme.

## Checklist

- [ ] One copy of `plotly.min.js`, served compressed, copied from the same wheel
      that rendered the figures.
- [ ] Loaded via a **plain** `<script src>` before the first fragment.
- [ ] Every plot container has a **definite height**.
- [ ] Build-time HTML → fragments. Runtime insertion → `to_json()`.
- [ ] Explicit `div_id` on anything cached or committed.
- [ ] `ResizeObserver` → `Plotly.Plots.resize` if containers resize independently
      of the window; one `resize` when a hidden plot is revealed.
- [ ] Plots over 5,000 points: lazy-render, downsample, or force `scatter`.
- [ ] Never `innerHTML` a fragment.
