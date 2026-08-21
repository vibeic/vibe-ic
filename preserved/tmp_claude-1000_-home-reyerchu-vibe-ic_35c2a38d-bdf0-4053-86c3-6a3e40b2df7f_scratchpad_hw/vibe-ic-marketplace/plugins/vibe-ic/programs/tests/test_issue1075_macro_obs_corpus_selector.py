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
                         text=True, timeout=55)
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
                         text=True, timeout=55)
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


def test_macro_obs_stays_on_the_routed_def_loop_until_957_is_arbitrated():
    """The retreat, pinned so it cannot be undone by accident.

    Selecting `macro OBS not crossed` on the intersection its comment declares
    ("a routed DEF AND a macro LEF") yields a corpus of ZERO items on this repo.
    #957's landed guard asserts every loop corpus is non-empty — "a disclosure
    that was achieved by dropping a gate, or by NARROWING the corpus, would be a
    coverage cut wearing a fix's clothes" — and an empty corpus is the limit
    case of narrowing. That is a disagreement with a landed test, not an
    implementation detail, so the gate stays where #957 expects it.

    The producer for the intersection SHIPS and is tested below; it is simply
    not wired yet. When #957's empty-corpus question is arbitrated, wiring it is
    a one-line change and this test is the thing that has to be updated with it.
    """
    text = HYGIENE.read_text()
    assert "_per_published_cell_gates" in text, (
        "macro OBS must still be dispatched from the routed-DEF loop")
    i = text.index("_per_published_cell_gates() {")
    body = text[i:text.index("gate_dispatch_over", i)]
    assert "macro_obs_geometry_intersect_check.py" in body, body[:400]
    assert "published cells carrying a routed DEF AND a macro LEF" not in text, (
        "the empty-corpus split is not wired on this branch — see #957")
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

# ---------------------------------------------------------------------------
# The other two gates: selected on what they READ (#1075, second half)
# ---------------------------------------------------------------------------
DRC_REL = "phase3/reports/drc_signoff.rpt"
REP_REL = "reports/phase3/lvs.json"


def _repo2(tmp_path, tree):
    """A throwaway repo whose tracked tree is exactly `tree` (path -> content)."""
    repo = tmp_path / "repo2"
    for rel in tree:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    subprocess.run(["git", "init", "-q", "."], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qm", "corpus"], cwd=repo, check=True)
    return repo


def test_the_drc_producer_selects_a_root_that_has_a_drc_report(tmp_path):
    repo = _repo2(tmp_path, [f"benchmark-data/ic/ic_a/run1/{DRC_REL}"])
    rc, items = _producer(repo, "published_cells_with_drc_report")
    assert rc == 0 and items == ["benchmark-data/ic/ic_a/run1"], items


def test_the_drc_producer_skips_a_root_with_no_drc_report(tmp_path):
    """The other direction. A producer returning every root would satisfy the
    test above and select cells the gate cannot answer about."""
    repo = _repo2(tmp_path, ["benchmark-data/ic/ic_b/run1/phase3/reports/sta.rpt"])
    rc, items = _producer(repo, "published_cells_with_drc_report")
    assert rc == 0 and items == [], items


def test_the_drc_producer_is_not_keyed_on_a_routed_def(tmp_path):
    """The defect this change removes, stated as a test: a cell with a routed
    DEF and no DRC report must NOT be selected for the DRC gate, and a cell with
    a DRC report and no DEF MUST be."""
    repo = _repo2(tmp_path, [
        f"benchmark-data/ic/only_def/run1/{DEF_REL}",
        f"benchmark-data/ic/only_drc/run1/{DRC_REL}",
    ])
    rc, items = _producer(repo, "published_cells_with_drc_report")
    assert rc == 0 and items == ["benchmark-data/ic/only_drc/run1"], items


def test_the_reports_producer_selects_an_ic_with_a_reports_tree(tmp_path):
    repo = _repo2(tmp_path, [f"benchmark-data/ic/ic_c/{REP_REL}"])
    rc, items = _producer(repo, "published_ics_with_reports_tree")
    assert rc == 0 and items == ["benchmark-data/ic/ic_c"], items


def test_the_reports_producer_skips_an_ic_with_no_reports_tree(tmp_path):
    repo = _repo2(tmp_path, [f"benchmark-data/ic/ic_d/run1/{DEF_REL}"])
    rc, items = _producer(repo, "published_ics_with_reports_tree")
    assert rc == 0 and items == [], items


def test_a_root_is_not_confused_with_its_own_structural_subdirectory(tmp_path):
    """The bug my first reducer had, pinned. `<ic>/phase3` and `<ic>/reports`
    are not projects — they are one project seen through its own trees — and a
    reducer that emitted them produced a list in which six entries were
    subdirectories of another entry."""
    repo = _repo2(tmp_path, [
        f"benchmark-data/ic/ic_e/{DRC_REL}",
        "benchmark-data/ic/ic_e/reports/phase3/drc_router.rpt",
    ])
    rc, items = _producer(repo, "published_cells_with_drc_report")
    assert rc == 0 and items == ["benchmark-data/ic/ic_e"], items
    assert not any(i.endswith(("/phase3", "/reports")) for i in items), items


def test_a_run_directory_IS_part_of_the_root(tmp_path):
    """The control for the test above: the structural-name rule must not also
    swallow a real run directory, or every versioned cell would collapse onto
    its IC and the gates would be handed a root they were never invoked with."""
    repo = _repo2(tmp_path, [f"benchmark-data/ic/ic_f/v1.2.3_sky130A/{DRC_REL}"])
    rc, items = _producer(repo, "published_cells_with_drc_report")
    assert rc == 0 and items == ["benchmark-data/ic/ic_f/v1.2.3_sky130A"], items


def test_the_script_dispatches_each_gate_over_its_own_input():
    """Pins WHICH producer drives WHICH gate — the whole point of the change.

    The two gates that do not read a DEF are now selected on what they DO read.
    `macro OBS` is deliberately still on the routed-DEF loop (see the test
    above), so this asserts the two re-pointed gates and not the third.
    """
    text = HYGIENE.read_text()
    for corpus, producer, prog in (
            ("published roots carrying a DRC report",
             "published_cells_with_drc_report", "drc_vacuous_pass_check.py"),
            ("published ICs carrying a reports/ tree",
             "published_ics_with_reports_tree",
             "step_internal_fail_bubble_up_check.py")):
        i = text.index(f'gate_dispatch_over "{corpus}"')
        assert producer in text[i:i + 200], corpus
        body_start = text.rindex("_published", 0, i)
        assert prog in text[body_start - 900:i], (corpus, prog)
    # and neither of them is still driven by the routed-DEF loop
    j = text.index("_per_published_cell_gates() {")
    shared = text[j:text.index("gate_dispatch_over", j)]
    assert "drc_vacuous_pass_check.py" not in shared
    assert "step_internal_fail_bubble_up_check.py" not in shared
def test_the_real_repository_populations_differ_from_the_old_selector():
    """The measured claim, against the real tree: the routed-DEF selector is a
    strictly smaller population than either gate's real input. If these ever
    coincide the change stops being justified and this fires."""
    _, defs = _producer(ROOT, "published_cells_with_routed_def")
    _, drc = _producer(ROOT, "published_cells_with_drc_report")
    _, reps = _producer(ROOT, "published_ics_with_reports_tree")
    assert len(defs) < len(drc), (len(defs), len(drc))
    assert len(defs) < len(reps), (len(defs), len(reps))
