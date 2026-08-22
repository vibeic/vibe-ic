"""A failure count names its runtime, or it may not be subtracted from another.

WHY
===
MEASURED: 28 of 127 failures were one missing test plugin — every test in those
files died AT LOAD — and 26 of them vanished on a second runtime. They were
counted against the revision because nothing named the runtime. Attribution took
five controlled arms.

THE ARM THAT MATTERS IS --diff
==============================
The point is not that an aggregate is annotated. It is that two aggregates from
DIFFERENT runtimes may not be differenced at all. `test_differencing_across_
runtimes_is_refused` is the negative control for that, and it is the case the
original defect would have failed.

A RULE THAT CANNOT TELL ITS OWN SUBJECT
=======================================
The discriminator is tested against a GATE PROFILE, which counts passes and
failures over gates and is not a test aggregate. An earlier key-count version
matched it, and matched a checker report too. Both are asserted NOT judged.

chip-AGNOSTIC: JSON records and runtime identifiers only.
"""
from __future__ import annotations

import importlib.util
import json
import pytest
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "pytest_aggregate_carries_its_runtime_identity.py"

_spec = importlib.util.spec_from_file_location("tacri", _TOOL)
tacri = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tacri)

_RT = {"image": "ghcr.io/vibeic/vibeic-eda@sha256:abc",
       "interpreter": "CPython 3.12.3",
       "unimportable_plugins": []}


def _agg(tmp_path, name, runtime=None, cases=None):
    obj = {"cases": cases or [{"nodeid": "t.py::test_a", "outcome": "passed"}],
           "passed": 1, "failed": 0}
    if runtime is not None:
        obj["runtime"] = runtime
    p = tmp_path / name
    p.write_text(json.dumps(obj, indent=2))
    return p


def _run(*args):
    cp = subprocess.run([sys.executable, str(_TOOL), *[str(a) for a in args]],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ------------------------------------------------------- the subject test

def test_a_gate_profile_is_not_a_test_aggregate():
    """The real false positive an earlier version produced."""
    profile = {"listed_only": 0, "declared": 74, "ran": 74, "passed": 70,
               "failed": 4, "not_checked": 0, "gates": ["a", "b"]}
    assert not tacri.is_aggregate(profile)


def test_a_checker_report_is_not_a_test_aggregate():
    assert not tacri.is_aggregate(
        {"program": "antenna", "passed": True, "findings": [], "summary": "ok"})


def test_a_junit_shaped_record_is_a_test_aggregate():
    assert tacri.is_aggregate(
        {"cases": [{"nodeid": "t.py::test_a", "outcome": "failed"}],
         "failed": 1})


# ------------------------------------------------- single-aggregate arm

def test_a_stamped_aggregate_passes(tmp_path):
    rc, out = _run("--aggregate", _agg(tmp_path, "a.json", _RT))
    assert rc == 0, out


def test_an_unstamped_aggregate_goes_red(tmp_path):
    """THE NEGATIVE CONTROL: the aggregate as the defect produced it."""
    rc, out = _run("--aggregate", _agg(tmp_path, "a.json"))
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "image" in out and "interpreter" in out
    assert "charged to the revision" in out


@pytest.mark.parametrize("junk", ["unknown", "n/a", "-", "TBD", "none", ""])
def test_a_placeholder_identity_is_not_an_identity(tmp_path, junk):
    """MEASURED FALSE PASS: {"image": "unknown", "interpreter": "n/a"} passed.

    A stamp reading "unknown" is the ABSENCE of an identity wearing its shape —
    this capture's seam exactly: the binding is reported true while nothing was
    established. An aggregate that names no runtime could satisfy the rule that
    exists to make it name one.
    """
    rc, out = _run("--aggregate",
                   _agg(tmp_path, "a.json", dict(_RT, image=junk)))
    assert rc == 1, f"placeholder {junk!r} passed as an identity:\n{out}"
    assert "image" in out


def test_an_empty_unimportable_list_is_a_real_answer(tmp_path):
    """"asked, none missing" must PASS; only ABSENCE is a finding."""
    rc, out = _run("--aggregate", _agg(tmp_path, "a.json", dict(_RT)))
    assert rc == 0, out


def test_a_missing_unimportable_list_goes_red(tmp_path):
    rt = {k: v for k, v in _RT.items() if k != "unimportable_plugins"}
    rc, out = _run("--aggregate", _agg(tmp_path, "a.json", rt))
    assert rc == 1, out
    assert "unimportable_plugins" in out


# ------------------------------------- the arm that matters: --diff refuses

def test_differencing_across_runtimes_is_refused(tmp_path):
    """THE CASE THE ORIGINAL DEFECT WOULD HAVE FAILED. Two aggregates whose
    runtimes differ by exactly the missing plugin must not be subtracted."""
    a = _agg(tmp_path, "a.json", _RT)
    b_rt = dict(_RT, unimportable_plugins=["pytest_timeout"])
    b = _agg(tmp_path, "b.json", b_rt)
    rc, out = _run("--diff", a, b)
    assert rc == 1, f"the difference was not refused:\n{out}"
    assert "REFUSED" in out
    assert "pytest_timeout" in out
    assert "do not" in out.lower()


def test_differencing_within_one_runtime_is_allowed(tmp_path):
    """BIDIRECTIONAL: identical runtimes must be comparable, or the rule is a
    ban on differencing rather than a check."""
    a = _agg(tmp_path, "a.json", _RT)
    b = _agg(tmp_path, "b.json", dict(_RT))
    rc, out = _run("--diff", a, b)
    assert rc == 0, out
    assert "same runtime" in out


def test_a_differing_image_is_refused(tmp_path):
    a = _agg(tmp_path, "a.json", _RT)
    b = _agg(tmp_path, "b.json", dict(_RT, image="ghcr.io/x@sha256:def"))
    rc, out = _run("--diff", a, b)
    assert rc == 1, out


def test_unstamped_aggregates_are_not_checked_not_refused(tmp_path):
    """"they differ" and "I cannot tell whether they differ" are different
    facts and must not share an exit code."""
    a = _agg(tmp_path, "a.json")
    b = _agg(tmp_path, "b.json")
    rc, out = _run("--diff", a, b)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_the_two_negative_states_have_different_exit_codes(tmp_path):
    a = _agg(tmp_path, "a.json", _RT)
    b = _agg(tmp_path, "b.json", dict(_RT, interpreter="CPython 3.10.0"))
    rc_refused, _ = _run("--diff", a, b)
    rc_unknown, _ = _run("--diff", _agg(tmp_path, "c.json"),
                         _agg(tmp_path, "d.json"))
    assert rc_refused == 1 and rc_unknown == 2


# -------------------------------------------------------------- verdicts

def test_a_tree_with_no_aggregate_is_not_checked(tmp_path):
    (tmp_path / "x.json").write_text('{"passed": 3, "failed": 1}')
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_a_tree_with_an_unstamped_aggregate_goes_red(tmp_path):
    _agg(tmp_path, "agg.json")
    rc, out = _run(tmp_path)
    assert rc == 1, out


def test_unparseable_json_is_not_checked(tmp_path):
    p = tmp_path / "a.json"
    p.write_text("{not json")
    rc, out = _run("--aggregate", p)
    assert rc == 2, out


def test_absent_file_is_bad_invocation(tmp_path):
    rc, out = _run("--aggregate", tmp_path / "nope.json")
    assert rc == 3, out


def test_repository_sweep_is_not_checked_and_says_why():
    """The repository is not a run tree. NOT CHECKED is the correct answer and
    it must not be a PASS."""
    rc, out = _run(_PROGRAMS.parents[3])
    assert rc == 2, out
    assert "not a run tree" in out


# ── THE ADMISSION NAMES THIS REPO'S OWN RUN-SUMMARY PRODUCER ────────────────
# The empty population is not an accident of a checkout: the one production
# writer of a run summary puts it in a temporary directory and lets it go. An
# admission that says only "none found" invites the reader to conclude the rule
# has no subject here. It has one; the artefact is never kept.

_DISP = "tools/ci/_gate_dispatch.sh"


def _with_dispatcher(tmp_path, body):
    p = tmp_path / _DISP
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return tmp_path


def test_note_is_absent_when_the_dispatcher_is(tmp_path):
    """No dispatcher, no claim about one. The gate must not invent a subject."""
    assert tacri._run_summary_note(tmp_path) is None


def test_note_is_absent_when_the_file_emits_no_summary(tmp_path):
    _with_dispatcher(tmp_path, "#!/bin/sh\necho hello\n")
    assert tacri._run_summary_note(tmp_path) is None


def test_note_names_the_runtime_gap(tmp_path):
    _with_dispatcher(tmp_path, '#!/bin/sh\n# --summary-json\n'
                               'printf \'{"declared": 1, "benchmark_data_sha": "x"}\'\n')
    note = tacri._run_summary_note(tmp_path)
    assert note is not None
    assert "does not name the RUNTIME" in note, note
    assert "recorded here rather than judged" in note, note


def test_note_says_so_when_runtime_identity_is_present(tmp_path):
    """The other direction — the note must not accuse a producer that complies."""
    _with_dispatcher(tmp_path, '#!/bin/sh\n# --summary-json\n'
                               'printf \'{"declared": 1, "python": "3.11"}\'\n')
    note = tacri._run_summary_note(tmp_path)
    assert note is not None
    assert "does emit a run summary carrying runtime identity" in note, note
    assert "does not name the RUNTIME" not in note, note


def test_the_note_never_changes_the_verdict(tmp_path):
    """A disclosure is not a finding. rc stays 2 with and without the note."""
    bare = _run(tmp_path)
    _with_dispatcher(tmp_path, '#!/bin/sh\n# --summary-json\n'
                               'printf \'{"declared": 1, "benchmark_data_sha": "x"}\'\n')
    withnote = _run(tmp_path)
    assert bare[0] == 2 and withnote[0] == 2, (bare, withnote)
    assert "does not name the RUNTIME" in withnote[1]
    assert "does not name the RUNTIME" not in bare[1]


def test_an_unreadable_dispatcher_does_not_break_the_gate(tmp_path):
    """Guarded on every side: this must never be the reason the gate fails."""
    d = tmp_path / _DISP
    d.parent.mkdir(parents=True, exist_ok=True)
    d.mkdir()                       # a directory where a file is expected
    assert tacri._run_summary_note(tmp_path) is None
    assert _run(tmp_path)[0] == 2
