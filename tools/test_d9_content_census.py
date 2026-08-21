"""The census's own controls — and the one that decides whether it can be believed.

`d9_content_census` makes a claim no other instrument here makes: that a gate
never read a byte. The load-bearing test is therefore
`test_an_existence_only_gate_is_CAUGHT`, which plants a gate that checks only
that a file exists and proves the census names it — because a D9 instrument that
cannot detect an existence check is the exact defect D9 exists to detect, shipped
inside D9 itself.

The second half is the corruption's own contract. If the corruption breaks SHAPE
(unparseable JSON, a vanished file) then every gate that merely calls
`json.load` in a `try` scores content-sensitive, and the census silently
overstates the good news. So the shape invariants are asserted directly, not
assumed.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS))
import d9_content_census as C  # noqa: E402


# --------------------------------------------------------------------------
# The corruption's contract: change MEANING, preserve SHAPE.
# --------------------------------------------------------------------------

def _shape(node):
    """Keys and value TYPES, with every leaf value erased."""
    if isinstance(node, dict):
        return {k: _shape(v) for k, v in sorted(node.items())}
    if isinstance(node, list):
        return [_shape(v) for v in node]
    return type(node).__name__


def test_json_corruption_keeps_every_key_and_type_and_moves_every_value(tmp_path):
    doc = {"verdict": "PASS", "violations": 0, "slack_ns": 1.25,
           "clean": True, "cells": [{"name": "u0", "area": 3}], "note": ""}
    out = C._corrupt_json_value(doc, random.Random(1))
    assert _shape(out) == _shape(doc), out          # shape survives
    assert out["violations"] != doc["violations"]
    assert out["slack_ns"] != doc["slack_ns"]
    assert out["clean"] is not doc["clean"]
    assert out["verdict"] != doc["verdict"]
    assert out["cells"][0]["area"] != doc["cells"][0]["area"]
    # and it is still real JSON, because an unparseable file would be caught by
    # any `try: json.load` — a parse check wearing a content check's clothes
    json.loads(json.dumps(out))


def test_text_corruption_keeps_the_line_count(tmp_path):
    text = "Final result: Circuits match uniquely.\nNumber of devices: 386\nok\n"
    out = C._corrupt_text(text, random.Random(1))
    assert out.count("\n") == text.count("\n"), out
    assert "386" not in out                       # the number moved
    assert "Circuits match" not in out            # and so did the verdict word
    assert "Circuits mismatch" in out


@pytest.mark.parametrize("before,after_expected", [
    ("Final result: Circuits match uniquely.", "Final result: Circuits mismatch uniquely."),
    ("Netlists mismatch.", "Netlists match."),
    ("LVS clean", "LVS violating"),
    ("verdict: PASS", "verdict: fail"),
])
def test_polarity_inverts_in_BOTH_directions(before, after_expected):
    """Not a push toward "bad" — an inversion.

    A corruption that always inserts the word "fail" would score a gate that
    only ever greps for "fail" as content-sensitive, which is a different and
    much weaker claim than the one this census makes.
    """
    # exact strings, not substrings: `mismatch` CONTAINS `match`, so a
    # substring assertion here passes on an unchanged file and this control
    # would be the vacuous kind it exists to replace
    after = C._flip_polarity(before)
    assert after == after_expected, (before, after)
    assert C._flip_polarity(after).strip() != ""   # a mapping, never a wipe


def test_the_corruption_reports_what_it_actually_touched(tmp_path, monkeypatch):
    """An arm that corrupted NOTHING must be visible as such.

    Otherwise a step whose declared outputs are absent from the run scores
    EXISTENCE-ONLY — the gate "did not react to a corruption" that never
    happened — which is a fabricated accusation.
    """
    monkeypatch.setattr(C.F, "required_outputs", lambda sid: ("reports/x.json",))
    monkeypatch.setattr(C.F, "split_any_of", lambda e: (e,))
    monkeypatch.setattr(C.F, "is_glob", lambda p: False)
    assert C.corrupt_declared_outputs(tmp_path, "1", random.Random(1)) == []

    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "x.json").write_text('{"v": 1}')
    assert C.corrupt_declared_outputs(tmp_path, "1", random.Random(1)) \
        == ["reports/x.json"]


# --------------------------------------------------------------------------
# THE CONTROL. Three planted gates, one per verdict, driven for real.
# --------------------------------------------------------------------------

_GATES = {
    # reads the bytes and judges them: a self-consistency criterion, no oracle
    "content_gate": """
        import json, sys, pathlib
        d = json.loads((pathlib.Path(sys.argv[1]) / "reports/x.json").read_text())
        # SELF-CONSISTENCY: the parts must sum to the whole it also reports
        ok = d["total"] == d["a"] + d["b"]
        print("[PASS] consistent" if ok else "[FAIL] total != a + b")
        sys.exit(0 if ok else 1)
        """,
    # never opens the file: the shape D9 exists to catch
    "existence_gate": """
        import sys, pathlib
        p = pathlib.Path(sys.argv[1]) / "reports/x.json"
        print("[PASS] present" if p.is_file() else "[FAIL] missing")
        sys.exit(0 if p.is_file() else 1)
        """,
    # not measuring this step at all
    "inert_gate": """
        import sys
        print("[PASS] nothing to do")
        sys.exit(0)
        """,
}


@pytest.fixture()
def planted(tmp_path, monkeypatch):
    progs = tmp_path / "programs"
    progs.mkdir()
    for name, body in _GATES.items():
        (progs / f"{name}.py").write_text(textwrap.dedent(body))
    run = tmp_path / "repo" / "run"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "x.json").write_text(json.dumps({"a": 2, "b": 3, "total": 5}))

    monkeypatch.setattr(C.F, "required_outputs", lambda sid: ("reports/x.json",))
    monkeypatch.setattr(C.F, "split_any_of", lambda e: (e,))
    monkeypatch.setattr(C.F, "is_glob", lambda p: False)
    monkeypatch.setattr(C.F, "program_path", lambda n: progs / f"{n}.py")
    return tmp_path / "repo"


@pytest.mark.parametrize("gate,expected", [
    ("content_gate", C.CONTENT_SENSITIVE),
    ("existence_gate", C.EXISTENCE_ONLY),
    ("inert_gate", C.DARK),
])
def test_the_three_verdicts_are_each_reachable(planted, tmp_path, gate, expected):
    """One planted gate per verdict, driven through the real three arms.

    `existence_gate` is the load-bearing one: it PASSES arm A, PASSES arm C with
    the numbers inverted under it, and only reacts when the file is deleted.
    That is precisely a gate that is green on every other dimension and has
    never read a byte.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    cell = C.three_arm_cell("1", "run", [gate], planted, scratch, 60)
    assert cell["corrupted"] == 1, cell
    assert cell["removed"] == 1, cell
    assert cell["programs"][gate]["verdict"] == expected, cell


def test_the_content_gate_really_did_pass_before_the_corruption(planted, tmp_path):
    """Guards the direction of the evidence.

    A gate that was ALREADY failing in arm A would show a verdict "change" for
    reasons that have nothing to do with the bytes, so the arm-A verdict is
    asserted rather than assumed.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    cell = C.three_arm_cell("1", "run", ["content_gate"], planted, scratch, 60)
    info = cell["programs"]["content_gate"]
    assert info["arm_a"].startswith("CLEAN"), info
    assert not info["arm_c"].startswith("CLEAN"), info


def test_cell_verdict_prefers_the_STRONGEST_evidence_across_runs(planted):
    """One run proving the gate can read bytes settles it; the claim is
    capability, and a run with a thinner artefact set must not mask it."""
    mk = lambda v: {"programs": {"g": {"verdict": v}}}
    assert C.cell_verdict([mk(C.EXISTENCE_ONLY), mk(C.CONTENT_SENSITIVE)]) \
        == C.CONTENT_SENSITIVE
    assert C.cell_verdict([mk(C.DARK), mk(C.EXISTENCE_ONLY)]) == C.EXISTENCE_ONLY
    assert C.cell_verdict([]) == C.NO_DENOMINATOR


def test_no_corpus_REFUSES_rather_than_reporting_a_clean_zero(tmp_path, monkeypatch, capsys):
    """After a corpus withdrawal this is the EXPECTED state, and a census over
    nothing that printed `0 EXISTENCE-ONLY` would read as good news."""
    monkeypatch.setattr(C.R, "tracked_files", lambda repo: [])
    rc = C.main(["--out", str(tmp_path / "out.json")])
    assert rc == 2
    assert "REFUSE" in capsys.readouterr().out


def test_no_oracle_is_consulted_anywhere(tmp_path):
    """The rule the owner sent D9 back for, as a test rather than a promise.

    Nothing in this module may read a known-correct answer: no golden, no
    expected-output fixture, no reference tree. The corruption is derived from
    the artefact's own bytes and the verdict from the gate's own exit code.
    """
    src = (_TOOLS / "d9_content_census.py").read_text()
    for forbidden in ("golden", "expected_output", "reference_run",
                      "answer_key", "oracle/"):
        assert forbidden not in src.lower(), forbidden


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))


# --------------------------------------------------------------------------
# ARM A IS A BASELINE, AND NOT EVERY ARM A CAN BE ONE.
#
# Both of these were found by re-probing step 11 across THREE published runs
# instead of one, and both were the census accusing a gate of the sample's
# limitation. The step reported EXISTENCE-ONLY on a single run and
# CONTENT-SENSITIVE across three.
# --------------------------------------------------------------------------

_ARM_A_GATES = {
    # already RED before anything is mutated: its arm C staying red is not
    # evidence that the bytes went unread, because the first finding masks any
    # second one. Measured shape: caravel `dft_atpg_coverage_check` A=FINDING.
    "already_failing_gate": """
        import sys
        print("[FAIL] already_failing_gate: unrelated pre-existing finding")
        sys.exit(1)
        """,
    # examined nothing on the pristine tree, then found something once the
    # bytes moved. Measured shape: spm `dft_signoff_check` NO-INPUT -> FINDING.
    "vacuous_then_finding_gate": """
        import json, sys, pathlib
        d = json.loads((pathlib.Path(sys.argv[1]) / "reports/x.json").read_text())
        if d["total"] >= 0:
            print("VACUOUS_PASS: vacuous_then_finding_gate examined nothing")
            sys.exit(0)
        print("[FAIL] negative total")
        sys.exit(1)
        """,
}


@pytest.fixture()
def planted_arm_a(tmp_path, monkeypatch):
    progs = tmp_path / "programs"
    progs.mkdir()
    for name, body in _ARM_A_GATES.items():
        (progs / f"{name}.py").write_text(textwrap.dedent(body))
    run = tmp_path / "repo" / "run"
    (run / "reports").mkdir(parents=True)
    (run / "reports" / "x.json").write_text(json.dumps({"a": 2, "b": 3, "total": 5}))
    monkeypatch.setattr(C.F, "required_outputs", lambda sid: ("reports/x.json",))
    monkeypatch.setattr(C.F, "split_any_of", lambda e: (e,))
    monkeypatch.setattr(C.F, "is_glob", lambda p: False)
    monkeypatch.setattr(C.F, "program_path", lambda n: progs / f"{n}.py")
    return tmp_path / "repo"


def test_a_run_whose_arm_A_is_already_RED_cannot_decide(planted_arm_a, tmp_path):
    """It must say INCONCLUSIVE, not EXISTENCE-ONLY.

    Scoring it EXISTENCE-ONLY reports the SAMPLE's limitation as the GATE's
    defect — an accusation the probe did not earn.
    """
    scratch = tmp_path / "s1"; scratch.mkdir()
    cell = C.three_arm_cell("1", "run", ["already_failing_gate"],
                            planted_arm_a, scratch, 60)
    info = cell["programs"]["already_failing_gate"]
    assert info["arm_a"].startswith("FINDING"), info
    assert info["verdict"] == C.INCONCLUSIVE, info


def test_NO_INPUT_moving_to_FINDING_is_the_bytes_being_READ(planted_arm_a, tmp_path):
    """The strongest evidence the probe can produce, previously discarded.

    The sibling's `verdict_moved` requires arm A to be content-derived, which is
    right for a DELETION arm and wrong here: the file is still present, so a
    verdict that moves can only have moved because of the bytes.
    """
    scratch = tmp_path / "s2"; scratch.mkdir()
    cell = C.three_arm_cell("1", "run", ["vacuous_then_finding_gate"],
                            planted_arm_a, scratch, 60)
    info = cell["programs"]["vacuous_then_finding_gate"]
    assert info["arm_a"].startswith("NO-INPUT"), info
    assert info["arm_c"].startswith("FINDING"), info
    assert info["verdict"] == C.CONTENT_SENSITIVE, info


def test_one_deciding_run_outranks_an_inconclusive_one(planted_arm_a):
    """A cell is not condemned by the run that could not decide."""
    mk = lambda v: {"programs": {"g": {"verdict": v}}}
    assert C.cell_verdict([mk(C.INCONCLUSIVE), mk(C.CONTENT_SENSITIVE)]) \
        == C.CONTENT_SENSITIVE
    assert C.cell_verdict([mk(C.INCONCLUSIVE), mk(C.EXISTENCE_ONLY)]) \
        == C.EXISTENCE_ONLY
    assert C.cell_verdict([mk(C.INCONCLUSIVE)]) == C.INCONCLUSIVE
