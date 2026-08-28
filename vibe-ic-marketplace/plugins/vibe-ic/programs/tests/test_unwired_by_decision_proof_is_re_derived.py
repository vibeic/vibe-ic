"""An `unwired_by_decision` entry must PROVE it deserves the exclusion.

`checker_execution_wiring_audit` blocks on a checker that nothing but its own
unit test runs. That finding cannot tell a checker nobody got round to wiring
from one that is deliberately not wired for a reason somebody measured — and
the second kind exists: `page_states_one_figure_twice_check` argues its own
non-wiring in its docstring, because declaring it in the hygiene lane would
make it exit 2 on every run over a subject this repository does not hold.

The register that resolves that is `unwired_by_decision`, and the danger of any
such register is obvious: it is one edit away from being a waiver list. The
precedent this file follows is `NOT_WHICH_GATES`, whose entries are DRIVEN by
`test_a_declared_non_which_gate_is_really_not_which_keyed` rather than trusted.

So every test below asks the same question in a different direction: can an
entry that does NOT deserve the exclusion still get it? Each one is a state a
future author can actually reach by editing the register or the tree.
"""
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import checker_execution_wiring_audit as A  # noqa: E402

ROOT = PROGRAMS.parent.parent.parent.parent
BASELINE = PROGRAMS / "checker_execution_wiring_baseline.json"


def _register():
    return json.loads(BASELINE.read_text()).get("unwired_by_decision") or {}


def _entries_with_a_proof():
    return {k: v for k, v in _register().items()
            if isinstance(v, dict) and "proof" in v}


# ---------------------------------------------------------------------------
# 1. every entry that claims an exclusion is RE-DERIVED, one test per entry
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(_entries_with_a_proof()))
def test_each_declared_proof_actually_holds_on_this_tree(name):
    """The register's claim, re-measured. Not read — RUN."""
    holds, detail = A.evaluate_proof(PROGRAMS, ROOT, _register()[name])
    assert holds, (
        f"`unwired_by_decision` excuses {name} from the test-only finding on "
        f"the strength of a proof that does not hold: {detail}")


@pytest.mark.parametrize("name", sorted(_entries_with_a_proof()))
def test_each_excused_checker_really_has_no_machine_runner(name):
    """The other half of the claim. An entry that says "deliberately not
    wired" about a checker something DOES run is a false record, and a false
    record is worse than none: it tells a reader the question was settled."""
    rep = A.audit(PROGRAMS.parent, ROOT)
    assert rep["machine_runners"].get(name) == [], (
        f"{name} is recorded as deliberately unwired, but "
        f"{rep['machine_runners'].get(name)} invoke(s) it — delete the entry")


# ---------------------------------------------------------------------------
# 2. THE REFUSALS. Each is a way an undeserving entry could be written.
# ---------------------------------------------------------------------------
def test_a_bare_reason_string_excuses_nothing():
    """The register's original shape. A reason a human can weigh is a
    disclosure and stays blocking; only a re-derivable proof excuses."""
    holds, detail = A.evaluate_proof(PROGRAMS, ROOT, "x" * 400)
    assert not holds and "does not excuse" in detail, detail


def test_an_entry_with_no_proof_object_excuses_nothing():
    holds, _ = A.evaluate_proof(PROGRAMS, ROOT, {"reason": "y" * 400})
    assert not holds


def test_an_unknown_proof_kind_is_refused_not_ignored():
    """The escape hatch this mechanism must not be. A kind the audit cannot
    re-derive must not be credited BECAUSE it could not be checked."""
    holds, detail = A.evaluate_proof(PROGRAMS, ROOT, {
        "reason": "z" * 400,
        "proof": {"kind": "trust_me", "probe": "a:b"}})
    assert not holds and "not one this audit can re-derive" in detail, detail


def test_a_probe_naming_a_program_that_is_not_here_is_refused():
    holds, detail = A.evaluate_proof(PROGRAMS, ROOT, {
        "reason": "z" * 400,
        "proof": {"kind": "no_subject_in_tree",
                  "probe": "no_such_program_at_all:subject_count"}})
    assert not holds and "not in programs/" in detail, detail


def test_a_probe_that_raises_does_not_buy_the_exclusion(tmp_path):
    """"I could not check the proof" and "the proof went false" are
    indistinguishable from here, and one of them is a checker nobody runs
    wearing a disclosure that stopped being true. Both must refuse."""
    (PROGRAMS / "_tmp_raising_probe.py").write_text(
        "def subject_count(root):\n    raise RuntimeError('boom')\n")
    try:
        holds, detail = A.evaluate_proof(PROGRAMS, ROOT, {
            "reason": "z" * 400,
            "proof": {"kind": "no_subject_in_tree",
                      "probe": "_tmp_raising_probe:subject_count"}})
    finally:
        (PROGRAMS / "_tmp_raising_probe.py").unlink()
    assert not holds and "could not be run" in detail, detail


def test_a_proof_that_finds_the_subject_present_is_refused(tmp_path):
    """The state the register exists to expire in: the subject LANDS. Driven
    against a real page carrying a metric card, so the probe's own pattern
    decides, not a re-typed copy of it."""
    page = tmp_path / "planted.html"
    page.write_text('<div><b>18</b><span>DECLARED_ONLY</span></div>\n')
    holds, detail = A.evaluate_proof(PROGRAMS, tmp_path, {
        "reason": "z" * 400,
        "proof": {"kind": "no_subject_in_tree",
                  "probe":
                      "page_states_one_figure_twice_check:subject_count"}})
    assert not holds and "now HOLDS the subject" in detail, detail


def test_the_probe_is_not_blind_it_finds_a_planted_subject(tmp_path):
    """A zero is only evidence once the instrument has been shown to fire.
    Without this, an entry could be excused forever by a probe that returns 0
    because it never looks."""
    sys.path.insert(0, str(PROGRAMS))
    import page_states_one_figure_twice_check as P
    assert P.subject_count(tmp_path) == 0
    (tmp_path / "p.html").write_text(
        '<div><b>18</b><span>DECLARED_ONLY</span></div>\n')
    assert P.subject_count(tmp_path) == 1
