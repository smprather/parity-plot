"""The tabbed-report example is the only executable check on the embedding path.

`docs/embedding.md` makes concrete claims about what a fragment is and how a page
has to host it. Those claims are prose, and prose rots. This builds the real
example and asserts the properties the document promises, so a change to the
fragment shape breaks a test rather than quietly invalidating the guide.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parents[1] / "examples" / "tabbed-report" / "build.py"


def _load_build_module():
    """Import build.py by path -- examples/ is deliberately not a package."""
    spec = importlib.util.spec_from_file_location("tabbed_report_build", BUILD)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    module = _load_build_module()
    dist = tmp_path_factory.mktemp("dist")
    page = module.build(dist=dist)
    return module, page, page.read_text(encoding="utf-8")


def test_the_example_builds(built):
    _, page, html = built
    assert page.exists()
    assert (page.parent / "static" / "plotly.min.js").exists()
    assert html.lstrip().startswith("<!doctype html>")


def test_one_shared_library_for_every_plot(built):
    module, _, html = built
    # Exactly one <script src>, and every plot draws through it.
    assert html.count("<script src=") == 1
    assert html.count("static/plotly.min.js") == 1
    assert html.count("Plotly.newPlot") == len(module.RUNS)
    assert html.count('class="plotly-graph-div"') == len(module.RUNS)


def test_the_page_needs_no_network(built):
    """No remote asset of any kind: this report has to open air-gapped."""
    import re

    _, _, html = built
    remote = re.findall(r'(?:src|href)\s*=\s*"(https?://[^"]*)"', html)
    assert remote == []


def test_the_library_script_is_plain_not_deferred(built):
    """defer/async/module would leave it queued when the inline fragments run."""
    _, _, html = built
    tag = html[html.index("<script src=") : html.index("<script src=") + 120]
    assert "defer" not in tag
    assert "async" not in tag
    assert 'type="module"' not in tag


def test_every_fragment_carries_no_document_wrapper(built):
    module, _, html = built
    # One <html> for the page itself, not one per plot.
    assert html.lower().count("<html") == 1
    assert html.lower().count("<!doctype") == 1
    for slug, _, _ in module.RUNS:
        assert f'id="{slug}"' in html


def test_div_ids_are_pinned_so_rebuilds_are_deterministic(built, tmp_path):
    """An unpinned div_id is a random UUID, which defeats content hashing."""
    module, _, html = built
    again = module.build(dist=tmp_path / "again").read_text(encoding="utf-8")
    assert again == html


def test_panels_start_hidden_and_have_a_definite_height(built):
    module, _, html = built
    # Every panel is hidden at build time; the JS reveals the first one. A
    # fragment is height:100%, so the panel must supply a real height or the
    # plot renders at zero size.
    assert html.count('role="tabpanel"') >= len(module.RUNS)
    assert html.count("hidden>") == len(module.RUNS)
    assert "height: 620px" in html


def test_the_reveal_resize_call_is_present(built):
    """The one line whose absence renders a stale, clipped plot -- silently."""
    _, _, html = built
    assert "Plotly.Plots.resize(div)" in html
    assert "ResizeObserver" in html


def test_build_does_not_leave_the_process_in_another_directory(tmp_path):
    module = _load_build_module()
    before = Path.cwd()
    module.build(dist=tmp_path / "cwd-check")
    assert Path.cwd() == before
