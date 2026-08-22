#!/usr/bin/env python3
"""Tests for real_artefact_test_backing_check (vibe-ic#400).

A change whose tests are all synthetic fixtures authored alongside it cannot
distinguish itself from its own absence. This classifier reports the split.

Every case is paired: a classifier that called everything SYNTHETIC would
satisfy the headline case, and one that called everything REAL would satisfy
its inverse. Only both together say anything.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import real_artefact_test_backing_check as C  # noqa: E402


def _mod(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "test_sample.py"
    p.write_text(body)
    return p


def test_a_pure_fixture_test_is_synthetic(tmp_path):
    r = C.classify_module(_mod(tmp_path, (
        "def test_a(tmp_path):\n"
        "    (tmp_path / 'x.json').write_text('{}')\n"
        "    assert True\n")))
    assert r["real"] == [] and len(r["synthetic"]) == 1


def test_the_helper_marks_a_test_real(tmp_path):
    r = C.classify_module(_mod(tmp_path, (
        "from _hostpaths import require_repo\n"
        "def test_a():\n"
        "    assert require_repo('benchmark-data').is_dir()\n")))
    assert len(r["real"]) == 1 and "[helper]" in r["real"][0]


def test_a_module_level_constant_counts(tmp_path):
    """`_CORPUS = require_repo(...)` at import time backs every test in the
    module; missing that would under-report the idiomatic shape."""
    r = C.classify_module(_mod(tmp_path, (
        "from _hostpaths import require_repo\n"
        "_CORPUS = require_repo('benchmark-data')\n"
        "def test_a():\n"
        "    assert _CORPUS\n")))
    assert len(r["real"]) == 1


def test_a_fixture_that_reaches_the_helper_counts(tmp_path):
    r = C.classify_module(_mod(tmp_path, (
        "import pytest\n"
        "from _hostpaths import require_repo\n"
        "@pytest.fixture\n"
        "def corpus():\n"
        "    return require_repo('benchmark-data')\n"
        "def test_a(corpus):\n"
        "    assert True\n")))
    # The fixture name is deliberately NOT referenced in the body: when it is,
    # the transitive call walk already reaches the helper and labels it
    # `[helper]`. This case exercises the PARAMETER path specifically — the
    # one that would silently misreport every fixture-driven real test.
    assert len(r["real"]) == 1 and "[fixture]" in r["real"][0]


def test_a_hand_rolled_corpus_sweep_counts(tmp_path):
    """REGRESSION, found by running this program on its own author's tests.

    Three test modules written this session sweep the committed corpus via
    `Path(__file__).parents[3] / "benchmark-data"` rather than the helper.
    Calling those SYNTHETIC reported `0 of 24` for a change whose tests really
    do walk the corpus — misleading a reviewer in exactly the direction this
    program exists to prevent.
    """
    r = C.classify_module(_mod(tmp_path, (
        "from pathlib import Path\n"
        "def test_a():\n"
        "    root = Path(__file__).parents[3] / 'benchmark-data'\n"
        "    assert list(root.rglob('*.json')) is not None\n")))
    assert len(r["real"]) == 1 and "[ad-hoc path]" in r["real"][0]


def test_naming_a_data_root_without_reading_it_is_not_enough(tmp_path):
    """The paired half: a docstring or a message mentioning the corpus must
    not promote a fixture-only test."""
    r = C.classify_module(_mod(tmp_path, (
        "def test_a(tmp_path):\n"
        "    '''Compare against benchmark-data conventions.'''\n"
        "    assert 1 == 1\n")))
    assert r["real"] == []


def test_an_external_corpus_helper_does_not_count(tmp_path):
    """`require_corpus` reaches an EXTERNAL corpus and SKIPs when absent, so
    a test using it proves nothing on a bare checkout."""
    r = C.classify_module(_mod(tmp_path, (
        "from _hostpaths import require_corpus\n"
        "def test_a():\n"
        "    assert require_corpus('vendor').is_dir()\n")))
    assert r["real"] == []


def test_the_gate_is_advisory_and_says_so(tmp_path):
    """It must never block. A static misclassification should cost one line
    of reading, not a rejected change."""
    m = _mod(tmp_path, "def test_a(tmp_path):\n    assert True\n")
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "real_artefact_test_backing_check.py"),
         str(m)], capture_output=True, text=True)
    assert r.returncode == 0
    assert "ADVISORY" in r.stdout
    assert "mutation run" in r.stdout


def test_it_refuses_to_report_on_nothing(tmp_path):
    """No test module in the change -> SKIP, not a clean 0-of-0 PASS."""
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "real_artefact_test_backing_check.py"),
         "--base", "HEAD", "--head", "HEAD", "--repo", str(tmp_path)],
        capture_output=True, text=True)
    assert r.returncode == 2 and "SKIP" in r.stdout


def test_the_skill_no_longer_pushes_authors_to_a_synthetic_suite():
    """Criterion 4 said fixtures must be synthesised neutral data, full stop.
    Read literally that produces the 100%-synthetic suite this program
    reports on, so the two would contradict each other."""
    doc = (_PROGRAMS.parent / "skills" / "flow-change-acceptance"
           / "SKILL.md").read_text()
    assert "cannot distinguish\nitself from its own absence" in doc \
        or "cannot distinguish" in doc
    assert "require_repo" in doc
    assert "real_artefact_test_backing_check" in doc


# --------------------------------------------------------------------------- #
# The zero-backed NOTE asserted more than the program measured.
#
# MEASURED, on a real branch: a pad-ring suite of 90 tests scored `0 of 90`
# and was told "every test in this change is a fixture authored alongside it".
# Three of those tests iterate the host's INSTALLED PDK trees — naming no PDK,
# foundry or library, and skipping honestly where none is present. That is not
# a fixture authored alongside the change, and it is not a checked-in artefact
# either; it is a third thing this program cannot see.
#
# The COUNT is not the defect and is not changed here: under-claiming is the
# decided design choice (see _GIT_REPO_READS), because over-claiming "real" is
# what lets a fixture-only change look backed. The defect is the sentence — a
# conservative measurement licenses a question, not a conclusion.
# --------------------------------------------------------------------------- #
def _zero_backed_note(tmp_path, monkeypatch):
    """Run the program's own reporting path over a module with 0 real tests."""
    mod = _mod(tmp_path, ("def test_a(tmp_path):\n"
                          "    (tmp_path / 'x.json').write_text('{}')\n"
                          "    assert True\n"))
    out = subprocess.run(
        [sys.executable, str(_PROGRAMS / "real_artefact_test_backing_check.py"),
         str(mod)], capture_output=True, text=True, cwd=str(tmp_path))
    return out.stdout


def test_the_zero_backed_note_does_not_assert_every_test_is_a_fixture(
        tmp_path, monkeypatch):
    """The pre-fix text says it flatly. Reading the OUTPUT, not a constant, so
    the old code answers this wrongly rather than failing to import."""
    note = _zero_backed_note(tmp_path, monkeypatch)
    assert "0 test(s)" in note or "0 of 1" in note, (
        "expected the zero-backed path to run at all; got:\n" + note)
    assert "every test in this change is a fixture" not in note, (
        "the NOTE states as fact something the program did not measure: a test "
        "driving an installed PDK or toolchain also scores 0 and is not a "
        "fixture authored alongside the change.\nGot:\n" + note)


def test_the_zero_backed_note_names_its_own_denominator(tmp_path, monkeypatch):
    """Scoped to the NOTE, not the whole output.

    The first draft of this test asserted on the full stdout and PASSED
    pre-fix, because the HEADLINE line already contains "checked-in artefact".
    It could not fail, so it measured nothing -- caught by running the control
    rather than by reading the test.
    """
    out = _zero_backed_note(tmp_path, monkeypatch)
    note = "\n".join(ln for ln in out.splitlines()
                     if "NOTE:" in ln or ln.startswith("        "))
    assert note.strip(), "no NOTE emitted at all:\n" + out
    assert "CHECKED-IN" in note.upper(), (
        "the NOTE itself must say what was counted, or a reader who reads only "
        "the NOTE takes 0 for 'nothing real here'.\nNOTE was:\n" + note)


def test_the_zero_backed_note_asks_which_case_it_is(tmp_path, monkeypatch):
    """Not merely softened wording: the gate must still demand an answer, and
    must demand a DIFFERENT answer for each of the two cases."""
    note = _zero_backed_note(tmp_path, monkeypatch)
    assert "mutation run" in note, (
        "the hand-authored case must still be asked for a mutation run")
    assert "name the subject" in note, (
        "the external-subject case must be asked to name the subject and say "
        "how the test behaves when it is absent")
