#!/usr/bin/env python3
"""A hand-written test fixture is not a published corpus document.

THE DEFECT THIS CLOSES
======================
`l4_systemrdl_export.py audit-corpus` walks `--root` for `L4_REGMAP.json` and
certifies that every register/field key in the PUBLISHED CORPUS has a recorded
disposition. The corpus left this repository in v1.10.56; the walk stayed.

`4ce74e03b` (v1.13.37, PR #1845) then landed seven hand-written L4 documents
under `programs/tests/fixtures/stage_phase1_on_pass_review/**` as inputs to an
unrelated on-pass-review suite. The walk had no reason to tell them apart from
a corpus, and MEASURED at 20031834c1 with no pointer bound it reported::

    root <repo>: 7 on disk, 7 published
    L4 documents scanned : 7 of 7 published (0 unreadable)
    [PASS] every register/field key in the published corpus has a recorded
    disposition.

Two consequences, and the second is the one that matters:

  * `NO_CORPUS` could never fire, and `--corpus-may-be-absent` -- a flag whose
    entire job is to make the program STATE that it scanned nothing -- printed
    a certificate over seven fixtures instead. Without the flag the program is
    supposed to exit 2 UNDETERMINED; it exited 0.
  * AN ENTIRELY UNREADABLE CORPUS WAS CERTIFIED. Point the pointer at a tree
    whose only L4 document does not parse and the seven fixtures supply the
    keys, every key has a disposition, and the verdict is PASS. That is the
    exact `audit-corpus found 0 of 201 documents -> PASS` shape this program's
    own docstring records it having shipped once.

This repo has paid for the same lesson before, in another gate:
`registry_is_the_iteration_domain` excludes test trees from its census because
three JSON basenames existing ONLY as fixtures moved a shipped gate's pinned
reach from 1 to 3.

THE PIN, IN BOTH DIRECTIONS
===========================
The first three go RED on the pre-fix walk. The fourth holds in BOTH
directions and is the half that keeps the fix from becoming its own defect: the
exclusion is anchored to THIS plugin's `programs/tests/` by absolute path, not
to the NAME `tests`, so a corpus checkout that happens to carry a `tests/`
directory keeps every document it publishes. An exclusion by name would turn a
false certificate into a silent blindness, which is the worse of the two.
"""
import json
import os
import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import l4_systemrdl_export as L4  # noqa: E402
import _corpus_location  # noqa: E402

REPO = _PROGRAMS.parents[3]
PROG = _PROGRAMS / "l4_systemrdl_export.py"
ENV = _corpus_location.CORPUS_ENV
OWN_TESTS = _PROGRAMS / "tests"


def _doc(path: pathlib.Path, text: str) -> pathlib.Path:
    d = path / "ic" / "unit" / "v0.0.0_pdkX" / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "L4_REGMAP.json"
    f.write_text(text, encoding="utf-8")
    return f


def _commit(root: pathlib.Path) -> None:
    for cmd in (("init", "-q"), ("config", "user.email", "t@t"),
                ("config", "user.name", "t"), ("add", "-Af"),
                ("commit", "-qm", "corpus")):
        subprocess.run(["git", "-C", str(root), *cmd], check=True,
                       capture_output=True, timeout=120)


def _run(*args: str, env_tree: str | None = None):
    env = dict(os.environ)
    env.pop(ENV, None)
    if env_tree is not None:
        env[ENV] = env_tree
    r = subprocess.run([sys.executable, str(PROG), *args], env=env,
                       capture_output=True, text=True, timeout=900)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ---------------------------------------------------------------------------
# RED before the fix, GREEN after
# ---------------------------------------------------------------------------
def test_no_document_under_this_plugins_own_tests_tree_is_walked_as_a_corpus():
    """THE CAUSE, at the walk. Everything below is a consequence of this."""
    hits = [p for p in L4._iter_l4(REPO)
            if pathlib.Path(p).resolve().is_relative_to(OWN_TESTS)]
    assert not hits, (
        "these are inputs to this repo's own tests, not documents any run "
        "published: " + ", ".join(sorted(str(h.relative_to(REPO))
                                         for h in hits)))


def test_with_no_pointer_the_repo_scan_states_that_it_scanned_nothing():
    """`--corpus-may-be-absent` exists to turn an absent corpus into a STATED
    zero. A certificate over seven fixtures is the opposite of what it buys."""
    rc, out = _run("audit-corpus", "--root", str(REPO),
                   "--corpus-may-be-absent")
    assert rc == 0, out
    assert "NO_CORPUS" in out, out


def test_a_corpus_of_unreadable_documents_is_not_certified_by_the_fixtures(
        tmp_path):
    """The harm. The supplied corpus parses to nothing; before the fix the
    repo's own fixtures supplied the keys and the program printed PASS."""
    bad = tmp_path / "unreadable"
    _doc(bad, "{ not json")
    _commit(bad)
    rc, out = _run("audit-corpus", "--root", str(REPO),
                   "--corpus-may-be-absent", env_tree=str(bad))
    assert rc == 2, "a corpus that could not be parsed was certified\n" + out


# ---------------------------------------------------------------------------
# UNCHANGED in both directions -- the exclusion must not become a blindness
# ---------------------------------------------------------------------------
def test_a_corpus_carrying_a_tests_directory_is_still_scanned_in_full(tmp_path):
    """POSITIVE CONTROL ON THE INSTRUMENT. The exclusion is anchored to this
    plugin's own `programs/tests/` absolutely; a corpus is entitled to a
    directory of that name and must lose nothing to it.

    Passes before the fix as well, on purpose: a fix that made this fail would
    have replaced a false certificate with a silent zero, and a silent zero is
    the harder of the two to notice.
    """
    corpus = tmp_path / "clone" / "tests" / "corpus"
    doc = _doc(corpus, json.dumps({"registers": []}))
    walked = {pathlib.Path(p).resolve() for p in L4._iter_l4(corpus)}
    assert doc.resolve() in walked, sorted(str(w) for w in walked)
