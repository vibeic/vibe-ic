"""The layer-membership rule, driven in both directions.

This gate is RED on the tree it ships with, deliberately, so the shipped-tree
test asserts rc 1 and names what must change for it to go green. A test that
asserted rc 0 here would be asserting the defect away.
"""
from __future__ import annotations

import json
import shutil
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parents[1]
        / "layer_membership_is_declared_not_inferred_from_a_filename_prefix.py")

# ── THE PIN IS A MEMBER SET, NOT A COUNT ─────────────────────────────────────
# Every earlier spelling of this pin was three counts (`glob 21, relation 28,
# 7 outside`) with ONE member named beside them. A count cannot report an
# arrival that a departure cancels -- 8 members leave 8 members -- and a count
# is the one thing that can be re-derived without reading the tree, so a
# re-derivation and an edit-to-fit are indistinguishable in the diff. These are
# the members. A move is then reported as a NAME that entered or left.
#
# Read from the program's own `--json` (`glob_members` / `relation_members` /
# `outside`), which is the program's `_imports` / `_is_executable` over the live
# tree -- not a filename pattern this file wrote for the occasion.
_PPA_GLOB_MEMBERS = frozenset({
    "ppa_ablation_check.py", "ppa_agent_context_build.py",
    "ppa_area_threshold_check.py", "ppa_closure_run.py",
    "ppa_contract_build.py", "ppa_contract_check.py",
    "ppa_diagnostic_router.py", "ppa_eco_spare_records.py",
    "ppa_feasibility_check.py", "ppa_head_to_head_check.py",
    "ppa_measurement_check.py", "ppa_metric_extract.py",
    "ppa_page_claim_check.py", "ppa_pareto_check.py",
    "ppa_pnr_search_space.py", "ppa_pr_scope_check.py",
    "ppa_predict_aggregate.py", "ppa_problem_integrity_check.py",
    "ppa_report_gen.py", "ppa_search_run.py", "ppa_signoff_records.py",
})
#: The finding itself: layer members no `ppa_*.py` glob reaches.
#: `phase3_one_shot_runner.py` entered at v1.17.91 `8d7a76cca`, which added
#: `from _ppa import delivery_path` to an executable module. Nothing left.
_PPA_OUTSIDE_MEMBERS = frozenset({
    "area.py", "gate_proof_vocabulary_has_a_producer.py", "openroad.py",
    "phase3_one_shot_runner.py", "power_total_vs_budget_check.py",
    "readme_ppa_extractor.py", "records_migrate.py", "timing.py",
})


def _moved(what: str, pinned, seen) -> str:
    return (f"the ppa layer's {what} population MOVED: "
            f"entered={sorted(set(seen) - set(pinned))} "
            f"left={sorted(set(pinned) - set(seen))}. "
            f"RE-DERIVE the finding and record which member entered or left "
            f"and why -- do not edit this set to fit, and do not replace it "
            f"with a count.")

_LAYER_MEMBER = '''\
import _demo


def main():
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

_NOT_EXECUTABLE = '''\
import _demo


def helper():
    return 1
'''


def _tree(*, glob_named: int, outside: int, outside_executable: bool = True,
          test_body: str = None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="lmd_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    (progs / "_demo").mkdir(parents=True)
    (progs / "_demo" / "__init__.py").write_text("")
    tests = progs / "tests"
    tests.mkdir()
    for i in range(glob_named):
        (progs / f"demo_{i}.py").write_text(_LAYER_MEMBER)
    body = _LAYER_MEMBER if outside_executable else _NOT_EXECUTABLE
    for i in range(outside):
        (progs / f"other_{i}.py").write_text(body)
    (tests / "test_demo_layer.py").write_text(
        test_body if test_body is not None
        else 'from pathlib import Path\n'
             'P = Path(__file__).parent.parent\n'
             'MEMBERS = sorted(p.name for p in P.glob("demo_*.py"))\n')
    return root


def _run(root: Path):
    return _pr.run([sys.executable, str(PROG), "--root", str(root)],
                          capture_output=True, text=True)


def test_a_layer_member_outside_the_glob_is_refused():
    """NEGATIVE CONTROL."""
    r = _run(_tree(glob_named=3, outside=2))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "other_0.py" in r.stdout and "demo" in r.stdout


def test_a_glob_that_reaches_the_whole_relation_is_not_refused():
    r = _run(_tree(glob_named=3, outside=0))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_non_executable_importer_is_not_a_member():
    """An exit-code contract cannot be enforced on a module with no entry point.

    Counting them would have inflated the real finding by 40 per cent.
    """
    r = _run(_tree(glob_named=3, outside=2, outside_executable=False))
    assert r.returncode == 0, (
        f"a module with no __main__ was counted as a layer executable "
        f"(rc={r.returncode})\n{r.stdout}")


def test_a_prefix_with_no_layer_package_is_out_of_population():
    root = _tree(glob_named=2, outside=1)
    import shutil
    shutil.rmtree(root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
                  / "programs" / "_demo")
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_test_star_glob_is_test_discovery_not_a_layer():
    root = _tree(glob_named=2, outside=1,
                 test_body='from pathlib import Path\n'
                           'P = Path(__file__).parent\n'
                           'T = sorted(p.name for p in P.glob("test_*.py"))\n')
    r = _run(root)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = _pr.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = _pr.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_is_RED_and_that_is_the_point(tmp_path):
    """This gate refuses on the tree it ships with, by design.

    There is no inventory: a recorded waiver would make the question disappear.
    When both `ppa` suites are pointed at the relation-derived population this
    goes green, and THAT is the signal the repair landed.
    """
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    rec = tmp_path / "layer_membership.json"
    r = _pr.run([sys.executable, str(PROG), "--root", str(root),
                 "--json", str(rec)], capture_output=True, text=True)
    assert r.returncode == 1, (
        f"the ppa layer gap is GONE (rc={r.returncode}). If the two suites were "
        f"repaired, delete this assertion and assert rc 0 — do not weaken the "
        f"gate.\n{r.stdout}")
    assert "layer `ppa`" in r.stdout
    assert "power_total_vs_budget_check.py" in r.stdout

    # THE POPULATION, PINNED BY ITS MEMBERS.
    #
    # HISTORY OF THIS PIN, because it is the point. It was three counts
    # (20/26/6 -> 21/27/6 -> 21/28/7 -> 21/29/8) with ONE member named beside
    # them. Every move so far has been a single arrival, so a count happened to
    # be enough to notice it; an arrival cancelled by a departure would have
    # left the count at rest and the pin would have said nothing. Worse, a
    # count can be re-derived without reading the tree, so "I re-ran the
    # program" and "I edited the number until it passed" produce the identical
    # diff. A member set can only be moved by naming who moved.
    #
    # The RELATION is not pinned as a third literal: it is exactly the glob
    # plus what falls outside it, and recording the same fact twice is how two
    # faces of one pin drift apart. The identity is asserted instead.
    #
    # The three counts on the human line are then asserted to be len() of these
    # sets — the line keeps its reader, and no count is a literal anywhere.
    doc = json.loads(rec.read_text(encoding="utf-8"))
    ppa = [f for f in doc["findings"] if f["layer"] == "ppa"]
    assert len(ppa) == 1, f"expected exactly one `ppa` finding\n{doc}"
    ppa = ppa[0]
    glob_m = set(ppa["glob_members"])
    rel_m = set(ppa["relation_members"])
    out_m = set(ppa["outside"])

    assert out_m == set(_PPA_OUTSIDE_MEMBERS), _moved(
        "outside (the finding)", _PPA_OUTSIDE_MEMBERS, out_m)
    assert glob_m == set(_PPA_GLOB_MEMBERS), _moved(
        "glob-derived", _PPA_GLOB_MEMBERS, glob_m)
    assert rel_m == glob_m | out_m, (
        f"the relation is no longer the glob plus what falls outside it: "
        f"in the relation only={sorted(rel_m - (glob_m | out_m))}, "
        f"missing from it={sorted((glob_m | out_m) - rel_m)}")
    assert (ppa["glob"], ppa["relation"], len(ppa["outside"])) == (
        len(glob_m), len(rel_m), len(out_m)), (
        f"the published counts disagree with the published members\n{ppa}")
    # ANCHORED, not a substring: "8 outside" is contained in "18 outside".
    assert re.search(
        rf"glob {len(glob_m)}, relation {len(rel_m)}, "
        rf"{len(out_m)} outside(?!\d)", r.stdout), (
        f"the human line disagrees with the member sets\n{r.stdout}")


def test_no_test_files_read_is_undetermined_not_a_pass():
    """The denominator that decides is TESTS READ, not globs in scope.

    A tree whose only prefix glob is test discovery HAS been examined and found
    nothing in scope -- the tests above pin that as a real rc 0. A tree with no
    test files at all was not examined, and the `[PASS]` sentence is then a
    universal claim over the empty set.

    A first attempt keyed this on `prefix_globs` and turned three of the tests
    above red, correctly, by conflating the two.
    """
    root = Path(tempfile.mkdtemp(prefix="lmzero_"))
    try:
        (root / ".git").mkdir()
        (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
         / "tests").mkdir(parents=True)
        r = _pr.run([sys.executable, str(PROG), "--root", str(root)],
                           capture_output=True, text=True)
        assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}"
        assert "0 test files were read" in r.stdout, r.stdout
        assert "[PASS]" not in r.stdout, r.stdout
    finally:
        shutil.rmtree(root, ignore_errors=True)
