"""A gate is selected on the predicate it declares, not on half of it. #1075.

`macro OBS not crossed` declares a two-part corpus — "a routed DEF AND a macro
LEF" — and was driven by a producer that tested the first half only. On this
repository the intersection is EMPTY, so the gate was handed a cell that fails
the unstated half, answered rc 2, and did so permanently: that loop is its only
wiring.

Every producer assertion here drives the REAL functions out of
`tools/ci/_published_cell_corpus.sh` over a THROWAWAY git repository, so the
corpus can be varied — which is the only way to show the selector responds to
the thing it claims to select on rather than happening to return the right
number once. A fixture copy of the pathspec would pass while the shipped one
drifted.

The dispatcher pair at the bottom drives the REAL `_gate_dispatch.sh`.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
ROOT = PLUGIN.parent.parent.parent
CORPUS_LIB = ROOT / "tools" / "ci" / "_published_cell_corpus.sh"
DISPATCH = ROOT / "tools" / "ci" / "_gate_dispatch.sh"
HYGIENE = ROOT / "tools" / "ci" / "repo_hygiene_gates.sh"

DEF_REL = "phase3/stage3/pnr/routed.def"


def _repo(tmp_path, cells):
    """A throwaway repo whose tracked tree is exactly `cells`.

    `cells` maps `<ic>/<run>` -> iterable of relative paths to create inside it.
    Committed, because both producers read `git ls-files`: the denominator is a
    property of the COMMIT, which is the property the loop was given after a
    working-directory glob once took the declared-gate count from 68 to 169.
    """
    repo = tmp_path / "repo"
    (repo / "tools" / "ci").mkdir(parents=True)
    for cell, rels in cells.items():
        for rel in rels:
            p = repo / "benchmark-data" / "ic" / cell / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qm", "corpus"], cwd=repo, check=True)
    return repo


def _producer(repo, fn):
    """Run one REAL producer from the shipped library. Returns (rc, [items])."""
    script = (f'set -euo pipefail\nROOT="{repo}"\n'
              f'. "{CORPUS_LIB}"\n{fn}\n')
    res = subprocess.run(["bash", "-c", script], capture_output=True,
                         text=True, timeout=120)
    items = [l for l in res.stdout.splitlines() if l.strip()]
    return res.returncode, items


BOTH = {"ic_a/run1": [DEF_REL, "phase3/analog/hardmacro/m/m.lef"]}
DEF_ONLY = {"ic_b/run1": [DEF_REL]}
LEF_ONLY = {"ic_c/run1": ["phase3/analog/hardmacro/m/m.lef"]}


# ---------------------------------------------------------------------------
# The producer responds to the predicate it names — both directions
# ---------------------------------------------------------------------------
def test_a_cell_with_both_is_selected(tmp_path):
    rc, items = _producer(_repo(tmp_path, BOTH),
                          "published_cells_with_routed_def_and_macro_lef")
    assert rc == 0
    assert items == [f"benchmark-data/ic/ic_a/run1/{DEF_REL}"]


def test_a_cell_with_only_a_routed_def_is_not_selected(tmp_path):
    """The arm that matters: this is the state of the real repository, and the
    state under which the gate could never answer."""
    repo = _repo(tmp_path, DEF_ONLY)
    rc, items = _producer(repo, "published_cells_with_routed_def_and_macro_lef")
    assert rc == 0 and items == []
    # ...and the OLD producer does select it, so the two genuinely differ
    rc2, items2 = _producer(repo, "published_cells_with_routed_def")
    assert rc2 == 0 and len(items2) == 1, items2


def test_a_cell_with_only_a_lef_is_not_selected(tmp_path):
    rc, items = _producer(_repo(tmp_path, LEF_ONLY),
                          "published_cells_with_routed_def_and_macro_lef")
    assert rc == 0 and items == []


def test_a_mixed_corpus_selects_exactly_the_intersection(tmp_path):
    """Three cells, one qualifying. A producer that returned everything, or
    nothing, passes each single-cell case above but not this one."""
    cells = {}
    cells.update(BOTH)
    cells.update(DEF_ONLY)
    cells.update(LEF_ONLY)
    rc, items = _producer(_repo(tmp_path, cells),
                          "published_cells_with_routed_def_and_macro_lef")
    assert rc == 0
    assert items == [f"benchmark-data/ic/ic_a/run1/{DEF_REL}"], items


def test_a_lef_nested_anywhere_under_the_cell_counts(tmp_path):
    """The checker's own discovery is `**/*.lef`; the producer's pathspec has to
    reach as deep or it would exclude cells the gate could actually read."""
    deep = {"ic_d/run1": [DEF_REL, "phase3/a/b/c/d/macro.lef"]}
    rc, items = _producer(_repo(tmp_path, deep),
                          "published_cells_with_routed_def_and_macro_lef")
    assert rc == 0 and len(items) == 1, items


def test_an_empty_intersection_is_rc_0_and_not_a_producer_failure(tmp_path):
    """`gate_dispatch_over` reports PRODUCER_FAILED on a non-zero producer and
    tells the reader the loop covered an unknown fraction of its corpus. An
    empty intersection is a fact, not a failure to look, and must not be
    announced as one — `set -e` inheriting the last test's status would."""
    rc, items = _producer(_repo(tmp_path, DEF_ONLY),
                          "published_cells_with_routed_def_and_macro_lef")
    assert (rc, items) == (0, [])


# ---------------------------------------------------------------------------
# The dispatcher pair — the REAL `_gate_dispatch.sh`
# ---------------------------------------------------------------------------
def _dispatch_over(tmp_path, repo, fn, label="g"):
    """Expand one loop through the real dispatcher; return its record."""
    rec = tmp_path / "summary.json"
    script = (
        f'set -euo pipefail\nROOT="{repo}"\n'
        f'. "{DISPATCH}"\n. "{CORPUS_LIB}"\n'
        f'gate_dispatch_init --summary-json "{rec}"\n'
        f'run "a gate that decided" "{repo}" true\n'
        f'_body() {{ run_tolerating_uncheckable "{label}" "{repo}" '
        f'bash -c "exit 2"; }}\n'
        f'gate_dispatch_over "the corpus" _body {fn}\n'
        f'gate_dispatch_finish\n')
    res = subprocess.run(["bash", "-c", script], capture_output=True,
                         text=True, timeout=120)
    return res, json.loads(rec.read_text())


def test_red_arm_the_old_selector_declares_a_gate_that_cannot_answer(tmp_path):
    """What `origin/main` does: the gate is declared, runs, and concludes
    nothing — every run, forever, because this loop is its only wiring."""
    repo = _repo(tmp_path, DEF_ONLY)
    res, doc = _dispatch_over(tmp_path, repo, "published_cells_with_routed_def")
    assert doc["declared"] == 2, doc
    assert doc["not_checked"] == 1, doc
    assert "NOT CHECKED" in res.stderr


def test_green_arm_the_declared_predicate_yields_a_disclosed_zero(tmp_path):
    """What this branch does: no gate is declared for a corpus that is empty,
    and the loop STATES the zero rather than leaving a permanent NOT_CHECKED."""
    repo = _repo(tmp_path, DEF_ONLY)
    res, doc = _dispatch_over(
        tmp_path, repo, "published_cells_with_routed_def_and_macro_lef")
    assert doc["declared"] == 1, doc          # only the stand-in gate
    assert doc["not_checked"] == 0, doc
    assert "expanded over 0 item(s)" in res.stdout, res.stdout
    assert "NOTHING was checked over" in res.stdout, res.stdout


def test_the_zero_disclosure_is_absent_when_the_corpus_is_not_empty(tmp_path):
    """The control for the pair above. Without it, a harness that always
    printed the zero sentence would satisfy the green arm."""
    repo = _repo(tmp_path, BOTH)
    res, doc = _dispatch_over(
        tmp_path, repo, "published_cells_with_routed_def_and_macro_lef")
    assert doc["declared"] == 2, doc
    assert "expanded over 0 item(s)" not in res.stdout, res.stdout


# ---------------------------------------------------------------------------
# The wiring itself — that the shipped script uses these producers
# ---------------------------------------------------------------------------
def test_the_script_sources_the_corpus_library():
    assert ". \"$HERE/_published_cell_corpus.sh\"" in HYGIENE.read_text()


def test_macro_obs_is_dispatched_over_the_intersection_and_the_other_two_are_not():
    """Pins WHICH loop each gate sits in. The whole change is the selector, so
    a test that only checked the producers would pass while the gate stayed
    wired to the old one."""
    text = HYGIENE.read_text()
    assert ("gate_dispatch_over \"published cells carrying a routed DEF AND a "
            "macro LEF\"") in text
    # the macro-OBS body must be the one driven by the intersection loop
    inter = text.index("published cells carrying a routed DEF AND a macro LEF\"")
    tail = text[inter:inter + 400]
    assert "_macro_obs_published_cell_gate" in tail, tail
    assert "published_cells_with_routed_def_and_macro_lef" in tail, tail
    # and the other two must still be on the routed-DEF loop
    body = text[text.index("_per_published_cell_gates() {"):
                text.index("gate_dispatch_over \"published cells carrying a "
                           "routed DEF\"")]
    assert "drc_vacuous_pass_check.py" in body
    assert "step_internal_fail_bubble_up_check.py" in body
    assert "macro_obs_geometry_intersect_check.py" not in body, (
        "macro OBS must no longer be declared inside the routed-DEF loop")


def test_the_real_repository_intersection_is_empty_and_that_is_why():
    """Records the measured fact this change is about, against the real tree.

    If a published cell ever carries BOTH, this fires — and it should: the gate
    would then have a corpus, the loop would declare it again, and the reason
    written into the script's comment would have changed under it.
    """
    rc, both = _producer(ROOT, "published_cells_with_routed_def_and_macro_lef")
    rc2, defs = _producer(ROOT, "published_cells_with_routed_def")
    assert rc == 0 and rc2 == 0
    assert len(defs) >= 1, "the routed-DEF corpus collapsed to nothing"
    assert both == [], (
        "a published cell now carries a routed DEF AND a LEF; `macro OBS not "
        f"crossed` has a real corpus again: {both}")
