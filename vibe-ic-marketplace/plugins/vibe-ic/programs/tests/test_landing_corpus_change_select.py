#!/usr/bin/env python3
"""Both directions of the corpus change-selection, and the refusal it produces.

The module under test generalises `ci_targeted_test_select`'s edge rules to the
two landing corpora that run unconditionally. Two questions have to be answered
about it, and the second is the one that decides whether anything may be
skipped:

  1. does a change that CAN flip a corpus file's verdict select it?
  2. does a change that cannot, NOT select it?

A selector that answers (1) by selecting everything is useless, and a selector
that answers (2) by selecting nothing is dangerous, so both directions are
asserted here rather than one.

THE SYNTHETIC TREES ARE REAL GIT REPOS. `_repo_files` and the census both go
through `git ls-files`, so a tmp_path with no history would exercise the
degraded path (`repo_files is None` -> basename keying) rather than the one a
landing takes, and every rule-7 assertion below would be measuring the fallback.
"""
from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from _plugin_tree import repo_path_or_missing

import landing_corpus_change_select as L


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _mkrepo(tmp_path: Path, files: dict) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-qm", "seed"], cwd=root, check=True)
    return root


#: One tree carrying every edge kind at once, so a rule that quietly stops
#: firing shows up as a single failing assertion rather than as a tree nobody
#: rebuilt.
_TREE = {
    "tools/test_direct.py": """
        def test_x():
            assert True
        """,
    "tools/test_imports.py": """
        import leaf_helper
        def test_x():
            assert leaf_helper.VALUE == 1
        """,
    "tools/leaf_helper.py": """
        import deep_helper
        VALUE = deep_helper.VALUE
        """,
    "tools/deep_helper.py": "VALUE = 1\n",
    "tools/test_names_a_data_file.py": """
        from pathlib import Path
        def test_x():
            assert Path("data/one_of_a_kind.yaml").exists()
        """,
    "tools/test_globs.py": """
        from pathlib import Path
        def test_x():
            assert list(Path("src").glob("*.sv"))
        """,
    "tools/test_loads_by_loader.py": """
        import importlib.util
        def test_x():
            spec = importlib.util.spec_from_file_location(
                "aliased", "src/loaded_by_path.py")
            assert spec is not None
        """,
    "tools/test_subprocess_only.py": """
        import subprocess, sys
        from pathlib import Path
        RUNNER = Path(__file__).resolve().parent / "runner.py"
        def test_x():
            assert subprocess.run([sys.executable, str(RUNNER)]).returncode == 0
        """,
    "tools/runner.py": """
        import callee_module
        raise SystemExit(0 if callee_module.OK else 1)
        """,
    "tools/callee_module.py": "OK = True\n",
    "data/one_of_a_kind.yaml": "k: v\n",
    "src/thing.sv": "module thing; endmodule\n",
    "src/loaded_by_path.py": "X = 1\n",
    "docs/unrelated_prose.md": "nothing here names anything\n",
    "tools/unrelated_module.py": "NOTHING = 0\n",
}


@pytest.fixture()
def tree(tmp_path):
    return _mkrepo(tmp_path, _TREE)


def _select(root: Path, *changed: str) -> set:
    return L.CorpusIndex(root, L.CORPUS_REPO_TOOLS).select(list(changed))


# ---------------------------------------------------------------------------
# DIRECTION 1 — a change that can flip a corpus file's verdict selects it
# ---------------------------------------------------------------------------

def test_the_corpus_is_discovered_not_listed(tree):
    files = L.corpus_files(tree, L.CORPUS_REPO_TOOLS)
    assert "tools/test_direct.py" in files
    # helpers are not tests and must not join the corpus
    assert "tools/leaf_helper.py" not in files


def test_changing_a_corpus_file_selects_that_file(tree):
    assert _select(tree, "tools/test_direct.py") >= {"tools/test_direct.py"}


def test_changing_a_directly_imported_module_selects_the_file(tree):
    assert "tools/test_imports.py" in _select(tree, "tools/leaf_helper.py")


def test_changing_a_TRANSITIVELY_imported_module_selects_the_file(tree):
    """`test_imports -> leaf_helper -> deep_helper`.

    The one-hop version of this rule passes every other test in this file and
    fails only here, which is why the chain is two links rather than one.
    """
    assert "tools/test_imports.py" in _select(tree, "tools/deep_helper.py")


def test_changing_a_file_the_corpus_names_by_path_selects_it(tree):
    got = _select(tree, "data/one_of_a_kind.yaml")
    assert "tools/test_names_a_data_file.py" in got


def test_changing_a_file_a_corpus_glob_matches_selects_it(tree):
    assert "tools/test_globs.py" in _select(tree, "src/thing.sv")


def test_changing_a_file_loaded_by_spec_from_file_location_selects_it(tree):
    assert "tools/test_loads_by_loader.py" in _select(tree,
                                                      "src/loaded_by_path.py")


# ---------------------------------------------------------------------------
# DIRECTION 2 — an unrelated change selects nothing
# ---------------------------------------------------------------------------

def test_an_unrelated_prose_file_selects_nothing(tree):
    assert _select(tree, "docs/unrelated_prose.md") == set()


def test_an_unrelated_module_nobody_imports_selects_nothing(tree):
    assert _select(tree, "tools/unrelated_module.py") == set()


def test_the_negative_is_not_vacuous(tree):
    """A selector wired to `return set()` passes both tests above.

    So the negatives are only worth having beside a positive taken from the
    SAME tree and the SAME call — this asserts the corpus is non-empty and that
    something in it is reachable.
    """
    index = L.CorpusIndex(tree, L.CORPUS_REPO_TOOLS)
    assert len(index.files) == 6, index.files
    assert index.select(["tools/deep_helper.py"]), (
        "nothing at all was selectable in this tree — the negative results "
        "above measure a dead selector, not an unrelated change")


# ---------------------------------------------------------------------------
# THE GAP PROBE — it must fire, and it must be able to stay silent
# ---------------------------------------------------------------------------

def test_an_edge_across_a_subprocess_is_reported_as_unfollowable(tree):
    """`test_subprocess_only -> runner.py -> callee_module.py`.

    The test file states no dependency on `callee_module` — the callee does.
    This is the shape of BOTH real counterexamples in the module docstring, and
    it is the reason neither corpus can be skipped.
    """
    index = L.CorpusIndex(tree, L.CORPUS_REPO_TOOLS)
    gaps = L.closure_gaps(
        index, {"tools/test_subprocess_only.py": ["tools/callee_module.py"]})
    assert gaps == [("tools/test_subprocess_only.py", "tools/callee_module.py")]


def test_an_edge_the_mechanism_follows_is_NOT_reported_as_a_gap(tree):
    """The silent arm. Without it, a probe that returns every pair would pass
    the test above and would prove nothing at all."""
    index = L.CorpusIndex(tree, L.CORPUS_REPO_TOOLS)
    assert L.closure_gaps(
        index, {"tools/test_imports.py": ["tools/deep_helper.py"]}) == []


def test_a_touch_map_key_outside_the_corpus_is_a_REFUSAL(tree):
    """Attribution that lands in a second key space inflated the first real
    audit from 95 gaps to 256. A measurement that can only err towards its own
    conclusion has to refuse instead."""
    index = L.CorpusIndex(tree, L.CORPUS_REPO_TOOLS)
    with pytest.raises(L.NotDetermined):
        L.closure_gaps(index, {"mcp-eda/test/test_x.py": ["tools/deep_helper.py"]})


def test_an_untouched_path_outside_the_tracked_tree_is_ignored(tree):
    index = L.CorpusIndex(tree, L.CORPUS_REPO_TOOLS)
    assert L.closure_gaps(index, {"tools/test_direct.py": ["/etc/hosts"]}) == []


# ---------------------------------------------------------------------------
# REFUSALS — never an empty answer
# ---------------------------------------------------------------------------

def test_an_unknown_corpus_is_refused(tmp_path):
    root = _mkrepo(tmp_path, {"tools/test_a.py": "def test_a():\n    pass\n"})
    with pytest.raises(L.NotDetermined):
        L.corpus_files(root, "not-a-corpus")


def test_an_empty_corpus_is_refused_rather_than_returned_empty(tmp_path):
    root = _mkrepo(tmp_path, {"tools/keep.txt": "x\n"})
    with pytest.raises(L.NotDetermined):
        L.corpus_files(root, L.CORPUS_REPO_TOOLS)


def test_the_cli_refuses_outside_a_git_repository(tmp_path):
    rc = L.main(["--repo", str(tmp_path), "--corpus", L.CORPUS_REPO_TOOLS,
                 "--list-corpus"])
    assert rc == 2


def test_the_cli_prints_the_selection_and_returns_zero(tree, capsys):
    rc = L.main(["--repo", str(tree), "--corpus", L.CORPUS_REPO_TOOLS,
                 "--changed", "tools/deep_helper.py"])
    assert rc == 0
    assert "tools/test_imports.py" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# THE REAL TREE — the guard that stops a skip being wired onto this selection
# ---------------------------------------------------------------------------

_LAND = repo_path_or_missing("tools", "gatekeeper-land.sh")


def _land_text():
    if not _LAND.is_file():
        pytest.skip(f"gatekeeper-land.sh not present at {_LAND} (mirror tree)")
    return _LAND.read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("fn", ["run_repo_tools_pytest",
                                "run_unselectable_pytest"])
def test_both_corpora_are_still_invoked_UNCONDITIONALLY(fn):
    """The load-bearing test in this file.

    `landing_corpus_change_select` computes a selection whose completeness is
    NOT established — `--prove-closure` refuses on both corpora, measured. A
    later branch that wires the selection into the stage as a skip would turn
    that unproven selection into a landing verdict, and it would look like a
    speed-up in the diff. So the stages are pinned as bare calls at column 0:
    no `if`, no `case`, no `${SKIP_...}` guard.
    """
    src = _land_text()
    assert re.search(rf"^{fn}\(\) \{{", src, re.M), f"{fn} is not defined"
    calls = [ln for ln in src.splitlines() if ln == fn]
    assert calls, (
        f"{fn} is defined but never invoked at column 0 — either the stage was "
        f"removed or it is now behind a guard, and a guarded corpus is a "
        f"corpus a landing can skip")


def test_the_selection_is_not_referenced_by_the_landing_script():
    """This module must not appear in `gatekeeper-land.sh` at all yet.

    Not stylistic. `--prove-closure` says PROVEN INCOMPLETE for both corpora,
    so the only honest wiring is none; the day the residual is genuinely empty
    this test is the thing that has to be edited, which forces the argument to
    be made rather than assumed.
    """
    assert "landing_corpus_change_select" not in _land_text()


@pytest.mark.parametrize("corpus,changed,red_file", [
    # MEASURED 2026-08-17 off f6b0e77dd. Mutating the changed file turns the
    # named corpus file RED (see the module docstring for the two pytest
    # transcripts), and the mechanism selects it in neither case.
    (L.CORPUS_REPO_TOOLS,
     "vibe-ic-marketplace/plugins/vibe-ic/programs/suite_write_guard.py",
     "tools/ci/test_repo_tools_tests_gate.py"),
    (L.CORPUS_UNSELECTABLE,
     "vibe-ic-marketplace/plugins/vibe-ic/skills/sta-review/compliance.yaml",
     "vibe-ic-marketplace/plugins/vibe-ic/skills/sta-review/tests/"
     "test_compliance.py"),
])
def test_the_measured_counterexamples_are_still_unfollowable(corpus, changed,
                                                             red_file):
    """A RATCHET, and it is deliberately pointed at the uncomfortable side.

    While these pairs hold, neither corpus may be skipped. If a future change
    to the mechanism makes one of them followable, this test goes RED — which
    is the correct outcome: it forces somebody to re-run `--prove-closure`
    and decide, rather than letting an improvement quietly imply eligibility.
    """
    repo = repo_path_or_missing(".")
    if not (repo / changed).is_file():
        pytest.skip(f"{changed} not present in this tree")
    index = L.CorpusIndex(repo, corpus)
    assert red_file in index.files, f"{red_file} is not in corpus {corpus}"
    assert red_file not in index.select([changed]), (
        f"{changed} now selects {red_file}. That is an IMPROVEMENT, and it "
        f"means the closure argument recorded in landing_corpus_change_select "
        f"must be re-measured with --prove-closure before this test is "
        f"relaxed — not after.")


def test_the_repo_tools_corpus_is_the_one_the_stage_actually_runs():
    """Same population as `run_repo_tools_pytest`, compared against ITS `find`.

    Two enumerations of "the corpus" is how a selection starts describing a set
    nobody runs — and the drift would be invisible, because a smaller corpus
    still prints PASS. So the shell discovery is executed and differenced
    rather than read.
    """
    repo = repo_path_or_missing(".")
    if not (repo / "tools").is_dir():
        pytest.skip("real tree not available")
    found = subprocess.run(
        ["find", "tools", "(", "-name", "test_*.py", "-o",
         "-name", "*_test.py", ")", "-type", "f"],
        cwd=repo, capture_output=True, text=True, check=True)
    assert sorted(found.stdout.split()) == L.corpus_files(
        repo, L.CORPUS_REPO_TOOLS)


def test_the_positive_control_on_the_real_tree_still_fires():
    """The pair above is only evidence if the same call CAN return the file."""
    repo = repo_path_or_missing(".")
    land = repo / "tools" / "gatekeeper-land.sh"
    if not land.is_file():
        pytest.skip("real tree not available")
    index = L.CorpusIndex(repo, L.CORPUS_REPO_TOOLS)
    got = index.select(["tools/gatekeeper-land.sh"])
    assert "tools/ci/test_repo_tools_tests_gate.py" in got, (
        "the selector returned nothing for a file the corpus names by path — "
        "the negative results above would be measuring a broken probe")
