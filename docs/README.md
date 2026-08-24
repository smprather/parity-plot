# Documentation

## Current guides

- [Project README](../README.md) — installation, data model, configuration,
  Python API, designer, polynomial reference lines, and development commands.
- [Embedding parity plots](embedding.md) — static fragments, dynamic JSON,
  Plotly library ownership, resizing, determinism, and WebGL limits.
- [Tabbed report example](../examples/tabbed-report/README.md) — complete offline
  multi-plot consumer with one shared Plotly library.
- [Contributor architecture](../CLAUDE.md) — module boundaries, invariants,
  validation rules, tests, and release process.

## Historical records

Files under `superpowers/specs/` and `superpowers/plans/` record the designs and
implementation sequences used to build earlier releases. They are retained for
decision context. Their old branches, dependency floors, task checkboxes, and
proposed APIs are historical; the current contracts live in the guides above.

### Designs

- [Interactive designer](superpowers/specs/2026-07-19-designer-design.md)
- [Designer auto-save and validation](superpowers/specs/2026-07-23-designer-autosave-validation-design.md)
- [Composite groups, colorscale, and TOML-only CLI](superpowers/specs/2026-07-23-multi-group-colorscale-cli-teardown-design.md)
- [Hover-text column selection](superpowers/specs/2026-07-25-hover-text-columns-design.md)

### Implementation plans

- [Designer phase 1: skeleton](superpowers/plans/2026-07-19-designer-phase-1-skeleton.md)
- [Designer phase 2: explorer](superpowers/plans/2026-07-20-designer-phase-2-explorer.md)
- [Designer phase 3: triage](superpowers/plans/2026-07-20-designer-phase-3-triage.md)
- [Designer brush selection](superpowers/plans/2026-07-20-designer-brush-selection.md)
- [Data sources phase 1: multi-file model](superpowers/plans/2026-07-20-data-sources-phase-1.md)
- [Data sources phase 2: marker encoding](superpowers/plans/2026-07-21-data-sources-phase-2-encoding.md)
- [Data sources phase 3: designer GUI](superpowers/plans/2026-07-21-data-sources-phase-3-designer.md)
- [Tolerances phase 1: model and config](superpowers/plans/2026-07-20-tolerances-phase-1-model.md)
- [Tolerances phase 2: rendering and verdicts](superpowers/plans/2026-07-20-tolerances-phase-2-rendering.md)
- [Designer auto-save and validation](superpowers/plans/2026-07-23-designer-autosave-validation.md)
- [Composite groups, colorscale, and CLI teardown](superpowers/plans/2026-07-23-multi-group-colorscale-cli-teardown.md)
