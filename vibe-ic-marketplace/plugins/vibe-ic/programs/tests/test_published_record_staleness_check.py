#!/usr/bin/env python3
"""A landed gate rule does not reach the records the gate already published
(vibe-ic#510).

WHAT WAS MEASURED BEFORE THIS EXISTED
--------------------------------------
v1.7.73 landed #502 — an SI sign-off that re-derived ZERO coupling folds is
``VACUOUS_PASS`` at rc 2, not ``PASS``. Every tracked ``si_mcf_sta_check.json``
read out of ``HEAD`` at that same version still said ``PASS``, and two of the
seven had ``coupling_pairs: 0`` beside it — verdicts the gate that wrote them
would refuse to issue. Nothing in the repo measured that gap, so it could have
persisted indefinitely with no reader able to tell a current record from a
superseded one.

THE THREE PROPERTIES THESE TESTS PIN
------------------------------------
1. DECIDED FROM THE RECORD. Every adjudication here runs on JSON alone — the
   synthetic corpora hold no SPEF, no report, no design. If the check ever
   needed an input to re-derive, these tests could not pass, which is the
   point: the real records name absolute paths on a machine that no longer
   exists (#506).
2. UNDECIDABLE IS DISCLOSED, NOT PASSED. A record whose gate registers nothing,
   or that lacks the fields a rule reads, is counted and named. The denominator
   is asserted to ADD UP, so a record can never fall out of both buckets.
3. A RULE CANNOT BE ADDED TO A GATE WITHOUT THIS CHECK KNOWING. The
   fingerprint test alters one decision branch in a copy of the gate and
   requires the check to go RED with ``RULES_UNREVIEWED`` — because a
   registration that could silently drift would be the very defect this
   program exists to catch, one level up.

4. A DEBT NOBODY RE-EXAMINED IS NOT A DEBT SOMEBODY PAID (section 7, #536).
   The register MAY ONLY SHRINK, so *shrink the register* is an irreversible
   instruction, and until #536 it was derived by set subtraction — which
   cannot tell a record that was re-adjudicated clean from one that was never
   adjudicated. Section 7 injects each way a record becomes undecidable and
   requires the resolution claim, and the instruction, to disappear.

AND ONE BEHAVIOURAL PIN, which no source fingerprint can give: the real gate
CLI is run on both shipped zero-coupling fixtures and the adjudicator must
agree with the verdict the gate actually emitted. That is what keeps the rule's
premise — ``coupling_pairs == 0`` implies nothing was proved — true against
real input rather than true on paper.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import _record_adjudication as _ra         # noqa: E402
import si_mcf_sta_check as SI              # noqa: E402


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_REPO = _PROGRAMS.parents[3]
#: The CLI's DEFAULT corpus argument — still this path, whatever it holds. Used
#: only by the read-only control, whose subject is the program, not the cells.
_CORPUS = _REPO / "benchmark-data"
_FIXTURES = _PROGRAMS / "tests" / "fixtures" / "si_mcf_zero_coupling"
_CLI = _PROGRAMS / "published_record_staleness_check.py"
#: The register the CLI loads when it is given no corpus argument. Naming it
#: here lets the two published-corpus tests keep the register/corpus PAIRING
#: when the cells are read from a clone elsewhere — handing the CLI an explicit
#: corpus root suppresses the default register on purpose (see its comment),
#: so the pairing has to be restored explicitly or every recorded entry would
#: look PAID.


# ── helpers ────────────────────────────────────────────────────────────────










# ── 1. the defect itself, on a corpus that carries only records ────────────








# ── 2. the denominator: undecidable is DISCLOSED, never skipped ────────────
















# ── 3. it reports, it does not rewrite ─────────────────────────────────────


# ── 4. registration cannot silently drift ──────────────────────────────────
def test_the_shipped_declaration_matches_its_gate(tmp_path):
    assert SI.RECORD_ADJUDICATION.drift() is None


def test_fingerprint_ignores_comments_blank_lines_and_leading_module_text():
    """Three of the four insensitivities this test originally claimed survive
    the v1.7.76 rebuild, and they survive for a better reason: they are pure
    text normalisation (drop blank and comment-only lines, rstrip the rest), so
    nothing about them can drift with the interpreter."""
    a = ('def build_report(x):\n'
         '    if x:\n'
         '        return "FAIL"\n'
         '    return "PASS"\n')
    b = ('# a new comment\n'
         'def build_report(x):\n'
         '    # an explanation\n'
         '    if x:\n'
         '        return "FAIL"\n'
         '\n'
         '    return "PASS"\n')
    roots = ("build_report",)
    assert (_ra.decision_fingerprint(a, roots)
            == _ra.decision_fingerprint(b, roots))


def test_fingerprint_now_MOVES_on_a_docstring_rewrite():
    """The fourth claim is reversed, deliberately, and it is a repair.

    This test used to assert that rewriting a decision function's docstring left
    the fingerprint alone — the old implementation ran `_without_docstring`
    first. But si_mcf_sta_check.py's own comment above its `decision_digest`
    says the opposite, verbatim: the digest "changes when the decision logic
    changes — INCLUDING the written reasons, which are part of what a rule
    pins", and a fingerprint that stayed quiet through a prose rewrite of a
    verdict reason "would be the wrong kind of quiet".

    The declaration's documentation and its implementation disagreed. Hashing
    the definition's own source bytes — the v1.7.76 repair for the
    interpreter-dependence that took CI red twice — brings them into agreement.
    """
    a = ('def build_report(x):\n'
         '    """One thing."""\n'
         '    return "PASS"\n')
    b = ('def build_report(x):\n'
         '    """A completely rewritten reason, much longer."""\n'
         '    return "PASS"\n')
    roots = ("build_report",)
    assert (_ra.decision_fingerprint(a, roots)
            != _ra.decision_fingerprint(b, roots))


def test_fingerprint_changes_when_a_decision_branch_changes():
    a = 'def build_report(x):\n    if x:\n        return "FAIL"\n    return "PASS"\n'
    b = ('def build_report(x):\n    if x:\n        return "FAIL"\n'
         '    return "VACUOUS_PASS"\n')
    roots = ("build_report",)
    assert (_ra.decision_fingerprint(a, roots)
            != _ra.decision_fingerprint(b, roots))


def test_fingerprint_follows_helpers_without_them_being_declared():
    """An author cannot under-declare the surface by forgetting a helper."""
    a = ('def _tier(v):\n    return "PASS" if v else "FAIL"\n'
         'def build_report(x):\n    return _tier(x)\n')
    b = ('def _tier(v):\n    return "PASS" if v else "VACUOUS_PASS"\n'
         'def build_report(x):\n    return _tier(x)\n')
    roots = ("build_report",)
    assert (_ra.decision_fingerprint(a, roots)
            != _ra.decision_fingerprint(b, roots))


def test_fingerprint_covers_module_level_constants_a_decision_reads():
    a = ('SKIP = frozenset({"NO_SPEF"})\n'
         'def build_report(c):\n    return "SKIP" if c in SKIP else "FAIL"\n')
    b = ('SKIP = frozenset({"NO_SPEF", "NO_REPORT"})\n'
         'def build_report(c):\n    return "SKIP" if c in SKIP else "FAIL"\n')
    roots = ("build_report",)
    assert (_ra.decision_fingerprint(a, roots)
            != _ra.decision_fingerprint(b, roots))


def test_a_missing_decision_root_is_an_error_not_an_empty_digest():
    with pytest.raises(_ra.FingerprintError):
        _ra.decision_fingerprint("x = 1\n", ("build_report",))












# ── 5. the debt register: it may only shrink ───────────────────────────────


















# ── 6. the behavioural pin no fingerprint can give ─────────────────────────
@pytest.mark.parametrize("fixture", ["grounded_only", "coupled"])
def test_adjudicator_agrees_with_what_the_real_gate_emits(tmp_path, fixture):
    """Run the REAL gate, then re-adjudicate the record it wrote.

    The rule's premise — ``coupling_pairs == 0`` implies nothing was proved —
    is a claim about the gate's INPUT-gathering code, which is deliberately
    outside the fingerprint boundary (it changes constantly for parsing
    reasons). So it is pinned here instead, end to end: whatever the gate
    answers on a real project directory, the paper adjudication of its own
    output must not contradict it.
    """
    import shutil
    work = tmp_path / fixture
    shutil.copytree(_FIXTURES / fixture, work)
    r = _pr.run(
        [sys.executable, str(_PROGRAMS / "si_mcf_sta_check.py"), "."],
        cwd=str(work), capture_output=True, text=True)
    assert r.returncode in (0, 2), r.stderr
    emitted = json.loads(
        (work / "reports" / "phase3" / "si_mcf_sta_check.json").read_text())

    outcome = SI._zero_fold_supersession(emitted)
    assert not isinstance(outcome, _ra.Undecidable), outcome
    assert outcome is None, (
        f"the gate emitted {emitted['verdict']!r} on {fixture} but "
        f"re-adjudicating its own record claims it would issue "
        f"{getattr(outcome, 'would_issue', None)!r}")
    if fixture == "grounded_only":
        assert emitted["verdict"] == "VACUOUS_PASS"
        assert emitted["summary"]["coupling_pairs"] == 0
    else:
        assert emitted["verdict"] == "PASS"
        assert emitted["summary"]["coupling_pairs"] > 0


# ── 7. "never examined" is not "no longer superseded" (vibe-ic#536) ────────
#
# The register MAY ONLY SHRINK, so the instruction it emits — *shrink the
# register* — is a destructive, irreversible edit. Until #536 that
# instruction was derived by set subtraction: an entry that produced no finding
# was PAID. An entry that was never adjudicated also produces no finding, and
# on this repo's own corpus at v1.7.89 a stale decision digest made both
# recorded entries undecidable and the gate duly reported both as paid. Both
# records still carried PASS and both still superseded.
#
# These tests fix the inference, not one of its false premises. Section 4
# already pins that a stale declaration is caught; what is pinned here is that
# NOTHING follows about the register from an entry nobody looked at.
_ENTRY = ("si_mcf_sta_check::{rec}::PASS->VACUOUS_PASS::"
          "si_mcf_sta_check.zero-fold-is-not-a-signoff")


























# ── 8. the real corpus, which is why this program exists ───────────────────




# --- vibe-ic#555: git lists it, the disk does not have it









# ── 9. MAY ONLY SHRINK is enforced on the READ path too (vibe-ic#922) ──────
#
# The ratchet lived entirely inside --write-baseline. A register is a JSON
# file, so the writer was never the only way to add an entry to it, and adding
# one by hand is exactly how a NEW superseded record stops being NEW.
_A_WRITTEN_REASON = ("a rule was newly registered for this gate, so records "
                     "it never reached are adjudicated for the first time")
