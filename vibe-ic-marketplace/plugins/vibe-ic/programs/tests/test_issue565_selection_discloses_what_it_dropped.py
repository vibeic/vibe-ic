"""#565 — a bounded selection that does not say what it dropped reads as full coverage.

`ci_targeted_test_select`'s default `ownership` mode maps a changed module to
tests by FILENAME, so a test named after the chip or the feature is invisible
however directly it imports the module. Measured over the tests tree: 2035 of
2850 import edges — 71% — are unseeable by name.

WHETHER TO WIDEN THE DEFAULT IS A COST DECISION and stays the owner's; #534
built the `--mode import-edge` lane and left the default where it is with the
reason written down. This is the other half of the issue's own ask:

    "If the measured cost turns out to be unacceptable, the fallback must
     DISCLOSE what it dropped rather than silently narrow."

MEASURED ON THIS REPO'S OWN LANDINGS, which is what makes it worth the 3 s:

    #628 landing (formal_property_run)   selected 18   4 importers not selected
    #627 landing (phase3_one_shot_runner) selected 20  161 importers not selected

The gate stamped `targeted tests (20 file(s)) PASS` on the second one. 161 test
files that import the module that landing changed did not run, and nothing said
so. That is the shape this repo keeps finding — an absence rendering as a pass —
sitting inside the gate that certifies every landing.

THE SELECTION IS UNCHANGED. This adds a sentence, not a test.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

C = importlib.import_module("ci_targeted_test_select")

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent


def _tree(tmp_path):
    """A plugin tree where one source module is imported by a test whose NAME
    does not own it — the exact shape name-ownership cannot see."""
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\ntestpaths = programs/tests\npython_files = test_*.py\n",
        encoding="utf-8")
    prog = tmp_path / "programs"
    tests = prog / "tests"
    tests.mkdir(parents=True)
    (prog / "widget_runner.py").write_text("X = 1\n", encoding="utf-8")
    # owned by name -> selected by rule 1
    (tests / "test_widget_runner.py").write_text(
        "import widget_runner\n", encoding="utf-8")
    # NOT owned by name, but imports it -> the invisible edge
    (tests / "test_acme_chip_flow.py").write_text(
        "import widget_runner\n", encoding="utf-8")
    (tests / "test_other_feature.py").write_text(
        "from widget_runner import X\n", encoding="utf-8")
    return tmp_path


# ── the disclosure, driven as a PURE function against a real tree ──────────
# The CLI resolves `plugin_root` from the SCRIPT's own location, so a fixture
# handed to it is never read — the first version of this file "passed" while
# auditing the real plugin. `import_edge_gap` exists so the computation can be
# driven against a constructed tree, which is the only way these assertions
# mean what they say.


def test_the_invisible_edge_is_the_one_named_after_the_chip(tmp_path):
    """The exact shape name-ownership cannot see: a test that imports the
    module directly but is named for the chip."""
    root = _tree(tmp_path)
    sel = set(C.select_tests(["programs/widget_runner.py"], root))
    imp = C._build_import_edge_index(root, {"widget_runner"})["widget_runner"]
    missed = sorted(imp - sel)
    assert any("acme_chip_flow" in m for m in missed), missed
    assert not any("test_widget_runner" in m for m in missed), (
        "the name-owned test should already be selected")
