#!/usr/bin/env python3
"""A pointer at the real corpus is not wrong just because the corpus is empty.

THE DEFECT, THIRD SITE
======================
`citation_routing_is_true_check` deliberately ADDS the tree named by
`$VIBE_IC_BENCHMARK_DATA` to its scan — it prints `note: … adds a corpus to
scan` — and then, finding none of its subject there, concluded:

    UNDETERMINED: VIBE_IC_BENCHMARK_DATA=… is a git checkout but tracks no
    CITATION_ROUTING.txt at all. A corpus that was NAMED and carries none of
    this gate's subject is a wrong pointer, not an absent corpus.

Three causes are implied — a wrong name, a failed clone, a no-op fetch — and
since the publisher withdrew every cell on 2026-08-20 there is a fourth that is
none of them: the pointer is right, the clone succeeded, and
`vibeic/benchmark-data` really does track zero `CITATION_ROUTING.txt`. The
operator is told to fix a pointer that is already correct.

Same defect as vibe-ic#1764 repaired in `tools/ci/routed_def_corpus.py` (rc 0
"the index was read and holds none" vs rc 3 "nothing was opened"), and as
`programs/tests/_published_corpus.py` was repaired for. This is the third site.

WHAT THIS IS NOT, AND THE TESTS ENFORCE IT
==========================================
**The rc does not move.** Both rows stay 2. `routed_def_corpus`'s own docstring
sets the rule — *"BOTH stay NOT CHECKED and BOTH stay blocking; only the sentence
each of them gets is different"* — and an empty population must never become a
clean one. `test_both_rows_are_still_rc_2` asserts that directly so that a later
"simplification" to rc 0 cannot pass this file.

Nothing here adjudicates a RESOLVES row it did not read, and no verdict changes.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
_CHECK = _PROGRAMS / "citation_routing_is_true_check.py"

_CONTRACT = "PUBLISHING.md"   # hand-spelled: a fixture built from the module
                              # under test goes red on a NEW NAME, not on the
                              # defect. Tied to the module in one test below.


def _git(root: Path, *argv: str) -> None:
    _pr.run(["git", "-C", str(root), *argv], check=True,
                   capture_output=True, text=True)


def _checkout(root: Path, *, is_corpus: bool) -> Path:
    """A git checkout tracking no CITATION_ROUTING.txt, corpus-shaped or not."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    if is_corpus:
        (root / "ic" / "somedesign").mkdir(parents=True)
        (root / "ic" / "somedesign" / "input").mkdir()
        (root / "ic" / "somedesign" / "input" / "spec.md").write_text(
            "design input\n", encoding="utf-8")
        (root / _CONTRACT).write_text(
            "# Publishing converged benchmark evidence\n", encoding="utf-8")
    else:
        (root / "datasets").mkdir()
        (root / "datasets" / "notes.md").write_text("not a corpus\n",
                                                    encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "tree with no CITATION_ROUTING.txt")
    return root


def _run(pointer: Path, root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["VIBE_IC_BENCHMARK_DATA"] = str(pointer)
    return _pr.run([sys.executable, str(_CHECK), "--root", str(root)],
                          capture_output=True, text=True, env=env)


def test_the_real_corpus_tracking_none_is_not_called_a_wrong_pointer(tmp_path):
    """The finding. The pointer is correct and must not be blamed."""
    r = _run(_checkout(tmp_path / "corpus", is_corpus=True), _PROGRAMS.parents[2])
    out = r.stdout + r.stderr
    assert "is a wrong pointer" not in out, (
        "a correct pointer at the published corpus was called wrong — the "
        f"operator is sent to fix a configuration that is already right:\n{out[-900:]}")
    assert "MEASURED zero" in out, out[-900:]


def test_a_tree_that_is_not_the_corpus_is_still_a_wrong_pointer(tmp_path):
    """The paired half. Without it the repair would excuse every mistyped path."""
    r = _run(_checkout(tmp_path / "other", is_corpus=False), _PROGRAMS.parents[2])
    out = r.stdout + r.stderr
    assert "is a wrong pointer" in out, out[-900:]


def test_both_rows_are_still_rc_2(tmp_path):
    """THE GUARD THAT MATTERS MOST. An empty population is not a pass.

    The repair changes a SENTENCE. If a later change makes the measured-empty row
    exit 0 — which would read as "this gate adjudicated its corpus and found it
    clean" over zero records read — this fails.
    """
    corpus = _run(_checkout(tmp_path / "c", is_corpus=True), _PROGRAMS.parents[2])
    other = _run(_checkout(tmp_path / "o", is_corpus=False), _PROGRAMS.parents[2])
    assert corpus.returncode == 2, (
        "the measured-empty corpus stopped refusing — an empty population must "
        f"never become a clean one (rc {corpus.returncode})")
    assert other.returncode == 2, other.returncode


def test_neither_row_claims_to_have_adjudicated_anything(tmp_path):
    """Whatever the sentence, it must not read as a scan that happened."""
    r = _run(_checkout(tmp_path / "c", is_corpus=True), _PROGRAMS.parents[2])
    out = r.stdout + r.stderr
    assert "NOT a pass" in out, out[-900:]
    assert "NOTHING WAS ADJUDICATED" in out, out[-900:]


def test_the_contract_spelling_is_tied_to_the_module():
    """`_CONTRACT` is hand-spelled above so the fixtures cannot go red merely
    because a constant is new. This is where the two spellings are reconciled."""
    sys.path.insert(0, str(_PROGRAMS))
    import citation_routing_is_true_check as C
    assert C._CORPUS_CONTRACT == _CONTRACT
