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

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import _gate_denominator as _gd            # noqa: E402
import _record_adjudication as _ra         # noqa: E402
import published_record_staleness_check as P  # noqa: E402
import si_mcf_sta_check as SI              # noqa: E402

from _published_corpus import corpus_root, needs_corpus  # noqa: E402

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
_DEFAULT_REGISTER = _PROGRAMS / P.DEFAULT_BASELINE


# ── helpers ────────────────────────────────────────────────────────────────
def _si_record(verdict="PASS", coupling_pairs=0, findings=None, **extra):
    """A published si_mcf_sta_check record, in the shape HEAD actually holds.

    Deliberately WITHOUT `summary.denominator` and `summary.vacuous`: the
    records this check exists for predate both fields, so a rule that needed
    them would adjudicate nothing at all.
    """
    rec = {
        "program": "si_mcf_sta_check",
        "version": "1.0.0",
        "project_dir": ".",
        "verdict": verdict,
        "summary": {
            "corners_checked": ["setup", "hold"],
            "windows_exact": True,
            "coupling_pairs": coupling_pairs,
            "errors_count": sum(1 for f in (findings or [])
                                if f.get("severity") == "ERROR"),
            "findings_count": len(findings or []),
            "pass": verdict == "PASS",
        },
        "recount": {},
        "monotonicity": {},
        "findings": list(findings or []),
    }
    rec.update(extra)
    return rec


def _corpus(tmp_path: Path, records: dict) -> Path:
    root = tmp_path / "published"
    for rel, data in records.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2) + "\n")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _run(root: Path, *args, programs_dir: Path = None) -> tuple:
    """Drive the real CLI in a subprocess; return (rc, stdout, stderr)."""
    argv = [sys.executable, str(_CLI), str(root),
            "--programs-dir", str(programs_dir or _PROGRAMS), *args]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr


def _report(root: Path, tmp_path: Path, *args, programs_dir: Path = None):
    out = tmp_path / "report.json"
    rc, _so, se = _run(root, "--json", str(out), *args,
                       programs_dir=programs_dir)
    return rc, json.loads(out.read_text()), se


def _tree_digest(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ── 1. the defect itself, on a corpus that carries only records ────────────
def test_zero_coupling_pass_is_reported_as_superseded(tmp_path):
    """The shape two tracked records are in: PASS beside coupling_pairs 0."""
    root = _corpus(tmp_path, {
        "ic/a/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0),
    })
    rc, rep, _se = _report(root, tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    stale = [f for f in rep["findings"] if f["kind"] == P.STALE]
    assert len(stale) == 1
    assert stale[0]["carried_verdict"] == "PASS"
    assert stale[0]["would_issue"] == "VACUOUS_PASS"
    assert stale[0]["landed_in"] == "#502"
    assert "coupling_pairs: 0" in stale[0]["because"]


def test_a_record_that_folded_something_is_not_reported(tmp_path):
    """The other five tracked records must not be swept up with the two.

    A non-zero pair count is where the rule DECLINES to speak: `examined` can
    still be 0 there (a coupled net whose expectation is 0.0), so certifying it
    either way would be a claim the record does not support.
    """
    root = _corpus(tmp_path, {
        "ic/b/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=1558),
    })
    rc, rep, se = _report(root, tmp_path)
    assert rc == 0, se
    assert rep["verdict"] == "PASS"
    assert rep["summary"]["stale_count"] == 0
    assert rep["summary"]["records_adjudicated"] == 1


def test_a_vacuous_pass_record_is_already_current(tmp_path):
    """A record written by the POST-fix gate is consistent, not stale."""
    root = _corpus(tmp_path, {
        "ic/c/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="VACUOUS_PASS", coupling_pairs=0),
    })
    rc, rep, se = _report(root, tmp_path)
    assert rc == 0, se
    assert rep["summary"]["stale_count"] == 0
    assert rep["summary"]["records_adjudicated"] == 1


def test_error_findings_route_a_zero_to_the_gate_own_precedence(tmp_path):
    """The rule does not hard-code VACUOUS_PASS; it asks the gate.

    A zero denominator reached because the artefact was REJECTED is a decided
    FAIL, not a skip (#506). Adjudicating it as VACUOUS_PASS would re-introduce
    the contradiction #506 removed, so the rule runs the gate's own
    `verdict_for` over the record's findings.
    """
    root = _corpus(tmp_path, {
        "ic/d/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0,
            findings=[{"severity": "ERROR", "category": "FOLD_WITHOUT_SOURCE",
                       "message": "x"}]),
        "ic/e/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0,
            findings=[{"severity": "ERROR", "category": "NO_SPEF",
                       "message": "x"}]),
    })
    rc, rep, _se = _report(root, tmp_path)
    assert rc == 1
    issued = {f["record"].split("/")[1]: f["would_issue"]
              for f in rep["findings"] if f["kind"] == P.STALE}
    assert issued == {"d": "FAIL", "e": "NOT_RUN"}


# ── 2. the denominator: undecidable is DISCLOSED, never skipped ────────────
def test_a_gate_with_no_rules_makes_its_records_undecidable_not_clean(tmp_path):
    root = _corpus(tmp_path, {
        "ic/f/reports/phase3/spare_cell_coverage_check.json": {
            "program": "spare_cell_coverage_check", "verdict": "PASS",
            "summary": {}},
    })
    rc, rep, se = _report(root, tmp_path)
    # Nothing adjudicated -> a DISCLOSED SKIP at rc 2, not a pass.
    assert rc == 2
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["summary"]["records_adjudicated"] == 0
    assert rep["summary"]["records_undecidable"] == 1
    u = rep["undecidable"][0]
    assert u["reason"] == _ra.LOAD_NO_DECLARATION
    assert "declares no" in u["detail"]
    assert "VACUOUS_PASS:" in se


def test_a_record_missing_the_fields_a_rule_reads_is_undecidable(tmp_path):
    rec = _si_record(verdict="PASS", coupling_pairs=0)
    del rec["summary"]["coupling_pairs"]
    root = _corpus(tmp_path, {"ic/g/r.json": rec})
    rc, rep, _se = _report(root, tmp_path)
    assert rc == 2
    u = rep["undecidable"][0]
    assert u["reason"] == P.UNDECIDABLE_FIELDS_ABSENT
    assert "summary.coupling_pairs" in u["detail"]


def test_a_field_present_but_unreadable_is_undecidable_not_adjudicated(tmp_path):
    """Presence is not readability — the third outcome a rule may return."""
    rec = _si_record(verdict="PASS", coupling_pairs=0)
    rec["summary"]["coupling_pairs"] = "many"
    root = _corpus(tmp_path, {"ic/h/r.json": rec})
    rc, rep, _se = _report(root, tmp_path)
    assert rc == 2
    assert rep["undecidable"][0]["reason"] == P.UNDECIDABLE_FIELD_UNREADABLE
    assert "not a count" in rep["undecidable"][0]["detail"]


def test_findings_that_are_not_objects_are_undecidable(tmp_path):
    rec = _si_record(verdict="PASS", coupling_pairs=0)
    rec["findings"] = "none"
    root = _corpus(tmp_path, {"ic/i/r.json": rec})
    rc, rep, _se = _report(root, tmp_path)
    assert rc == 2
    assert rep["undecidable"][0]["reason"] == P.UNDECIDABLE_FIELD_UNREADABLE


def test_the_denominator_always_adds_up(tmp_path):
    """No record may fall out of both buckets — the whole disclosure claim."""
    bad = _si_record(verdict="PASS", coupling_pairs=0)
    del bad["summary"]["coupling_pairs"]
    root = _corpus(tmp_path, {
        "ic/j/r.json": _si_record(verdict="PASS", coupling_pairs=0),
        "ic/k/r.json": _si_record(verdict="PASS", coupling_pairs=7),
        "ic/l/r.json": bad,
        "ic/m/r.json": {"program": "spare_cell_coverage_check",
                        "verdict": "PASS"},
        "ic/n/not-a-record.json": {"hello": "world"},
    })
    rc, rep, _se = _report(root, tmp_path)
    s = rep["summary"]
    assert s["records_found"] == 4          # the non-record is not a record
    assert s["records_adjudicated"] + s["records_undecidable"] == 4
    d = s[_gd.DENOMINATOR_KEY]
    assert d["examined"] == s["records_adjudicated"]
    assert d["considered"] == s["records_found"]
    assert d["details"]["json_not_a_gate_record"] == 1
    assert rc == 1


def test_the_report_satisfies_the_denominator_disclosure_contract(tmp_path):
    """Checked against the shared contract, not restated here."""
    for i, records in enumerate((
            {"ic/o/r.json": _si_record(verdict="PASS", coupling_pairs=9)},
            {"ic/p/r.json": {"program": "spare_cell_coverage_check",
                             "verdict": "PASS"}},
            {})):
        root = _corpus(tmp_path / f"case{i}", records)
        _rc, rep, _se = _report(root, tmp_path / f"out{i}")
        assert _gd.disclosure_violations(rep["summary"]) == []


def test_an_empty_corpus_is_a_disclosed_skip_with_a_written_reason(tmp_path):
    root = _corpus(tmp_path, {})
    rc, rep, se = _report(root, tmp_path)
    assert rc == 2
    assert rep["summary"]["records_found"] == 0
    reason = rep["summary"][_gd.DENOMINATOR_KEY]["not_applicable_reason"]
    assert "no published gate record was found" in reason
    assert "VACUOUS_PASS:" in se


def test_undecidable_is_broken_down_by_gate_and_by_reason(tmp_path):
    bad = _si_record(verdict="PASS", coupling_pairs=0)
    del bad["summary"]["coupling_pairs"]
    root = _corpus(tmp_path, {
        "ic/q/r.json": bad,
        "ic/r/r.json": {"program": "lec_run", "verdict": "PASS"},
        "ic/s/r.json": {"program": "lec_run", "verdict": "FAIL"},
    })
    _rc, rep, _se = _report(root, tmp_path)
    det = rep["summary"][_gd.DENOMINATOR_KEY]["details"]
    assert det["undecidable_by_gate"]["lec_run"] == {
        _ra.LOAD_NO_DECLARATION: 2}
    assert det["undecidable_by_gate"]["si_mcf_sta_check"] == {
        P.UNDECIDABLE_FIELDS_ABSENT: 1}
    assert det["gates_publishing_records"] == 2
    assert det["gates_with_registered_rules"] == 1


# ── 3. it reports, it does not rewrite ─────────────────────────────────────
def test_the_check_writes_nothing_into_the_corpus(tmp_path):
    """Correcting a published record is the benchmark-agent's call (NO-MIX)."""
    root = _corpus(tmp_path, {
        "ic/t/r.json": _si_record(verdict="PASS", coupling_pairs=0),
        "ic/u/r.json": _si_record(verdict="PASS", coupling_pairs=3),
    })
    before = _tree_digest(root)
    rc, _rep, _se = _report(root, tmp_path)
    assert rc == 1                       # it DID find the stale one
    assert _tree_digest(root) == before  # and changed nothing


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


def _gate_copy(tmp_path: Path, mutate) -> Path:
    """A programs dir holding ONE altered copy of the real gate.

    Only the gate is copied: its bare sibling imports (`_record_adjudication`,
    `_gate_denominator`, ...) still resolve to the real modules, so the
    declaration it builds is the same type this check compares against.
    """
    d = tmp_path / "altered_programs"
    d.mkdir(parents=True, exist_ok=True)
    src = (_PROGRAMS / "si_mcf_sta_check.py").read_text()
    (d / "si_mcf_sta_check.py").write_text(mutate(src))
    return d


def test_a_landed_rule_change_without_re_review_fails_loudly(tmp_path):
    """REQUIREMENT 4, and the reason a hand-maintained list is not acceptable.

    A new decision rule is landed in the gate and the declaration is left
    untouched. The check must not keep quietly adjudicating against the rules
    it last reviewed — that is the staleness it exists to catch, one level up.
    """
    def add_a_rule(src: str) -> str:
        return src.replace(
            '    if vacuous:\n        return "VACUOUS_PASS"\n'
            '    return "PASS"\n',
            '    if vacuous:\n        return "VACUOUS_PASS"\n'
            '    if not_run:\n        return "NOT_RUN"\n'
            '    return "PASS"\n', 1)

    altered = _gate_copy(tmp_path, add_a_rule)
    assert (altered / "si_mcf_sta_check.py").read_text() != (
        _PROGRAMS / "si_mcf_sta_check.py").read_text(), "mutation did not apply"

    root = _corpus(tmp_path, {
        "ic/v/r.json": _si_record(verdict="PASS", coupling_pairs=0)})
    rc, rep, se = _report(root, tmp_path, programs_dir=altered)
    assert rc == 1
    assert rep["summary"]["gates_unreviewed"] == ["si_mcf_sta_check"]
    # ... and the record is no longer adjudicated against rules nobody reviewed
    assert rep["summary"]["records_adjudicated"] == 0
    assert rep["undecidable"][0]["reason"] == P.UNDECIDABLE_RULES_UNREVIEWED
    assert "RULES_UNREVIEWED" in se


def test_re_reviewing_the_rules_clears_the_drift(tmp_path):
    """The escape hatch is an EDIT, which is reviewable; not a flag."""
    def add_a_rule_and_re_review(src: str) -> str:
        src = src.replace(
            '    if vacuous:\n        return "VACUOUS_PASS"\n'
            '    return "PASS"\n',
            '    if vacuous:\n        return "VACUOUS_PASS"\n'
            '    if not_run:\n        return "NOT_RUN"\n'
            '    return "PASS"\n', 1)
        return src

    altered = _gate_copy(tmp_path, add_a_rule_and_re_review)
    new = subprocess.run(
        [sys.executable, str(_CLI), "--programs-dir", str(altered),
         "--print-decision-digest", "si_mcf_sta_check"],
        capture_output=True, text=True, timeout=60)
    assert new.returncode == 0, new.stderr
    digest = new.stdout.strip().split("digest=")[1]

    src = (altered / "si_mcf_sta_check.py").read_text()
    old = SI.RECORD_ADJUDICATION.decision_digest
    assert old in src and old != digest
    (altered / "si_mcf_sta_check.py").write_text(src.replace(old, digest, 1))

    root = _corpus(tmp_path, {
        "ic/w/r.json": _si_record(verdict="PASS", coupling_pairs=0)})
    rc, rep, _se = _report(root, tmp_path, programs_dir=altered)
    assert rep["summary"]["gates_unreviewed"] == []
    assert rep["summary"]["records_adjudicated"] == 1
    assert rc == 1                       # the STALE record, not the drift
    assert rep["summary"]["stale_count"] == 1


def test_a_gate_module_that_disappeared_is_disclosed(tmp_path):
    root = _corpus(tmp_path, {
        "ic/x/r.json": {"program": "a_gate_that_no_longer_exists",
                        "verdict": "PASS"}})
    rc, rep, _se = _report(root, tmp_path)
    assert rc == 2
    assert rep["undecidable"][0]["reason"] == _ra.LOAD_NO_MODULE


def test_strict_fails_when_a_publishing_gate_registers_nothing(tmp_path):
    root = _corpus(tmp_path, {
        "ic/y/r.json": _si_record(verdict="PASS", coupling_pairs=4),
        "ic/z/r.json": {"program": "lec_run", "verdict": "PASS"}})
    rc, rep, _se = _report(root, tmp_path)
    assert rc == 0
    rc2, rep2, _se2 = _report(root, tmp_path / "strict", "--strict")
    assert rc2 == 1
    assert rep2["summary"]["strict_unregistered_gates"] == ["lec_run"]


# ── 5. the debt register: it may only shrink ───────────────────────────────
def _baseline(tmp_path: Path, keys) -> Path:
    """A register in the shape ``--write-baseline`` produces.

    The bookkeeping fields are not decoration. Since #922 the READ path refuses
    a register the writer could not have produced, so a fixture that omits them
    describes a file this program is right to reject — it would pin the wrong
    behaviour and hide the one these fields exist to catch.
    """
    p = tmp_path / "register.json"
    keys = sorted(str(k) for k in keys)
    p.write_text(json.dumps({"previous_size": None, "size": len(keys),
                             "scope_expanded": None, "known": keys},
                            indent=2) + "\n")
    return p


def test_recorded_debt_does_not_fail_but_is_still_printed(tmp_path):
    """The corpus cannot be corrected here, and a red gate is an ignored gate.

    Correcting a published record is the benchmark-agent's commit under
    NO-MIX. Recording the two it owes keeps CI honest about NEW ones without
    this program deciding another role's commit — and the entries are still
    printed in full, so recording is not hiding.
    """
    root = _corpus(tmp_path, {
        "ic/aa/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0)})
    rc0, rep0, _ = _report(root, tmp_path)
    key = P.debt_key([f for f in rep0["findings"]
                      if f["kind"] == P.STALE][0])
    assert rc0 == 1

    bl = _baseline(tmp_path, [key])
    rc, rep, se = _report(root, tmp_path / "b", "--baseline", str(bl))
    assert rc == 0, se
    assert rep["summary"]["superseded_new"] == []
    assert rep["summary"]["superseded_recorded_as_debt"] == [key]
    assert "STALE_VERDICT" in se          # recorded, not hidden
    assert "1 recorded as debt" in se


def test_a_new_superseded_record_fails_even_with_debt_recorded(tmp_path):
    root = _corpus(tmp_path, {
        "ic/ab/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0),
        "ic/ac/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0)})
    _rc, rep, _ = _report(root, tmp_path)
    keys = sorted(P.debt_key(f) for f in rep["findings"]
                  if f["kind"] == P.STALE)
    bl = _baseline(tmp_path, keys[:1])
    rc, rep2, se = _report(root, tmp_path / "b", "--baseline", str(bl))
    assert rc == 1
    assert rep2["summary"]["superseded_new"] == keys[1:]
    assert "1 published record(s) carry a verdict" in se


def test_a_paid_debt_must_shrink_the_register(tmp_path):
    """A stale entry in the register would become standing permission.

    This is the ONE shape that earns the shrink instruction: the rule named in
    the entry RAN over the record named in the entry and declined to supersede
    it. Section 8 pins everything that merely looks like it from the outside.
    """
    root = _corpus(tmp_path, {
        "ic/ad/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="VACUOUS_PASS", coupling_pairs=0)})   # corrected upstream
    bl = _baseline(tmp_path, [
        "si_mcf_sta_check::ic/ad/reports/phase3/si_mcf_sta_check.json::"
        "PASS->VACUOUS_PASS::si_mcf_sta_check.zero-fold-is-not-a-signoff"])
    rc, rep, se = _report(root, tmp_path / "b", "--baseline", str(bl))
    assert rc == 1
    assert len(rep["summary"]["superseded_debt_resolved"]) == 1
    assert [c["status"] for c in rep["summary"]["recorded_debt_status"]] == [
        P.DEBT_RESOLVED]
    assert rep["summary"]["records_adjudicated"] == 1
    assert "the debt was paid" in se
    assert "shrink" in se


def test_a_different_staleness_on_a_recorded_record_is_new(tmp_path):
    """The key carries the verdict pair, so one entry cannot cover another."""
    root = _corpus(tmp_path, {
        "ic/ae/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0,
            findings=[{"severity": "ERROR", "category": "FOLD_WITHOUT_SOURCE",
                       "message": "x"}])})
    bl = _baseline(tmp_path, [
        "si_mcf_sta_check::ic/ae/reports/phase3/si_mcf_sta_check.json::"
        "PASS->VACUOUS_PASS::si_mcf_sta_check.zero-fold-is-not-a-signoff"])
    rc, rep, _se = _report(root, tmp_path / "b", "--baseline", str(bl))
    assert rc == 1
    assert rep["summary"]["superseded_new"] == [
        "si_mcf_sta_check::ic/ae/reports/phase3/si_mcf_sta_check.json::"
        "PASS->FAIL::si_mcf_sta_check.zero-fold-is-not-a-signoff"]


def test_the_register_refuses_to_grow_without_a_written_reason(tmp_path):
    root = _corpus(tmp_path, {
        "ic/af/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0),
        "ic/ag/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0)})
    bl = _baseline(tmp_path, [])
    rc, _so, se = _run(root, "--baseline", str(bl), "--write-baseline")
    assert rc == 1
    assert "refusing to GROW" in se
    assert json.loads(bl.read_text())["known"] == []

    rc2, _so2, se2 = _run(
        root, "--baseline", str(bl), "--write-baseline", "--scope-expanded",
        "a rule was newly registered for this gate, so records it never "
        "reached are adjudicated for the first time")
    assert rc2 == 0, se2
    assert len(json.loads(bl.read_text())["known"]) == 2


def test_rule_drift_is_never_recordable_as_debt(tmp_path):
    """The one thing the register must not be able to absorb."""
    def add_a_rule(src: str) -> str:
        return src.replace(
            '    if vacuous:\n        return "VACUOUS_PASS"\n'
            '    return "PASS"\n',
            '    if vacuous:\n        return "VACUOUS_PASS"\n'
            '    if not_run:\n        return "NOT_RUN"\n'
            '    return "PASS"\n', 1)

    altered = _gate_copy(tmp_path, add_a_rule)
    root = _corpus(tmp_path, {
        "ic/ah/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0)})
    bl = _baseline(tmp_path, [])
    rc, _so, se = _run(root, "--baseline", str(bl), programs_dir=altered)
    assert rc == 1
    assert "re-reviewed" in se
    # ... and writing the register cannot silence it either
    rc2, _so2, _se2 = _run(root, "--baseline", str(bl), "--write-baseline",
                           programs_dir=altered)
    assert json.loads(bl.read_text())["known"] == []
    rc3, _so3, se3 = _run(root, "--baseline", str(bl), programs_dir=altered)
    assert rc3 == 1
    assert "RULES_UNREVIEWED" in se3


def test_ignore_baseline_gives_the_raw_answer(tmp_path):
    root = _corpus(tmp_path, {
        "ic/ai/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=0)})
    _rc, rep, _ = _report(root, tmp_path)
    bl = _baseline(tmp_path, [P.debt_key(rep["findings"][0])])
    assert _run(root, "--baseline", str(bl))[0] == 0
    assert _run(root, "--baseline", str(bl), "--ignore-baseline")[0] == 1


@needs_corpus
def test_the_shipped_register_is_current(tmp_path):
    """Every recorded entry is still stale, and nothing stale is unrecorded.

    Run against the PUBLISHED corpus and the DEFAULT register — the pairing the
    register describes — so a corrected record or a newly-superseded one shows
    up here rather than in whoever next reads CI.

    The old guard asked whether `<repo>/benchmark-data` was a directory. It
    still is — it holds the design INPUT — while the result cells moved to
    vibeic/benchmark-data, so the guard passed and the CLI then answered rc 2
    (VACUOUS_PASS, 0 records found). That is "I could not look" being reported
    as a defect in the register.

    When the cells are read from a clone, the register must be named
    explicitly: handing the CLI a corpus root deliberately suppresses the
    default register, and without it every recorded entry would read as PAID.
    """
    argv = [sys.executable, str(_CLI)]
    if corpus_root() != _CORPUS:
        argv += [str(corpus_root()), "--baseline", str(_DEFAULT_REGISTER)]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


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
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "si_mcf_sta_check.py"), "."],
        cwd=str(work), capture_output=True, text=True, timeout=60)
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


def _stale_digest(src: str) -> str:
    """The declared digest, reverted — the exact v1.7.89 state, on any commit.

    Substituting the FIRST 64-hex literal after `decision_digest=` keeps this
    independent of what the current digest happens to be, so the mutation
    cannot quietly stop applying when the gate's logic next moves.
    """
    import re
    out, n = re.subn(r'(decision_digest=\(\s*")[0-9a-f]{64}(")',
                     r"\g<1>" + "5" * 64 + r"\g<2>", src, count=1)
    assert n == 1, "the declaration no longer has a substitutable digest"
    return out


def _withdraw_declaration(src: str) -> str:
    assert src.count("RECORD_ADJUDICATION = _ra.declare(") == 1
    return src.replace("RECORD_ADJUDICATION = _ra.declare(",
                       "_WITHDRAWN = _ra.declare(", 1)


def _no_gate_module(tmp_path: Path) -> Path:
    """A programs dir the gate module is absent from."""
    d = tmp_path / "gate_module_gone"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_an_unadjudicated_entry_is_not_reported_as_a_resolved_one(tmp_path):
    """THE DEFECT, injected the way it was found: a stale decision digest.

    The record is untouched and still superseded. The only thing that changed
    is that nothing could adjudicate it — and the gate must not turn that into
    an instruction to delete the entry that records it.
    """
    rec = "ic/aj/reports/phase3/si_mcf_sta_check.json"
    root = _corpus(tmp_path, {rec: _si_record(verdict="PASS",
                                              coupling_pairs=0)})
    altered = _gate_copy(tmp_path, _stale_digest)
    bl = _baseline(tmp_path, [_ENTRY.format(rec=rec)])

    rc, rep, se = _report(root, tmp_path / "b", "--baseline", str(bl),
                          programs_dir=altered)
    s = rep["summary"]
    assert rc == 1                                  # the DRIFT, and only it
    assert s["gates_unreviewed"] == ["si_mcf_sta_check"]
    assert s["records_adjudicated"] == 0
    assert s["superseded_debt_resolved"] == []
    assert s["superseded_debt_unadjudicated"] == [_ENTRY.format(rec=rec)]
    [c] = s["recorded_debt_status"]
    assert c["status"] == P.DEBT_UNADJUDICATED
    assert c["blocked_by"] == P.UNDECIDABLE_RULES_UNREVIEWED
    # ... and the destructive instruction is not issued at all
    assert "the debt was paid" not in se
    assert "shrink" not in se
    assert "RULES_UNREVIEWED" in se

    # The record really is still superseded — the claim the old message made
    # about it was false, not merely unsupported.
    rc2, rep2, _se2 = _report(root, tmp_path / "c", "--ignore-baseline")
    assert rc2 == 1
    assert [P.debt_key(f) for f in rep2["findings"]
            if f["kind"] == P.STALE] == [_ENTRY.format(rec=rec)]


@pytest.mark.parametrize("how", ["stale_digest", "declaration_withdrawn",
                                 "gate_module_absent", "fields_absent"])
def test_no_undecidability_class_can_pass_for_a_resolved_debt(tmp_path, how):
    """The conflation was never specific to rule drift.

    Two of these are WORSE than the injection in the issue: a missing gate
    module and a withdrawn declaration raise no other alarm, so *shrink the
    register* was the ONLY thing the gate said. A reader following the one
    instruction on screen would have deleted live debt with nothing to warn
    them.
    """
    rec = "ic/ak/reports/phase3/si_mcf_sta_check.json"
    record = _si_record(verdict="PASS", coupling_pairs=0)
    programs_dir = None
    if how == "stale_digest":
        programs_dir = _gate_copy(tmp_path, _stale_digest)
    elif how == "declaration_withdrawn":
        programs_dir = _gate_copy(tmp_path, _withdraw_declaration)
    elif how == "gate_module_absent":
        programs_dir = _no_gate_module(tmp_path)
    else:
        del record["summary"]["coupling_pairs"]

    root = _corpus(tmp_path, {rec: record})
    bl = _baseline(tmp_path, [_ENTRY.format(rec=rec)])
    rc, rep, se = _report(root, tmp_path / "b", "--baseline", str(bl),
                          programs_dir=programs_dir)
    s = rep["summary"]
    assert s["records_adjudicated"] == 0
    assert s["superseded_debt_resolved"] == [], how
    assert s["recorded_debt_status"][0]["status"] == P.DEBT_UNADJUDICATED
    assert "the debt was paid" not in se, how
    assert "shrink" not in se, how
    # rc 1 only where something else is genuinely red (the drift); the rest are
    # the disclosed-skip tier, which is what "nothing was adjudicated" means.
    assert rc == (1 if how == "stale_digest" else 2), how


def test_nothing_adjudicated_yields_no_resolution_claim_at_all(tmp_path):
    """The property stated as a property, over a whole register.

    `RESOLVED` requires membership in the adjudicated population, so an empty
    adjudicated population can produce no resolution — by construction, not by
    a special case someone has to remember to keep.
    """
    root = _corpus(tmp_path, {
        "ic/al/r.json": {"program": "lec_run", "verdict": "PASS"}})
    bl = _baseline(tmp_path, [
        _ENTRY.format(rec=f"ic/gone_{i}/r.json") for i in range(5)])
    rc, rep, se = _report(root, tmp_path / "b", "--baseline", str(bl))
    s = rep["summary"]
    assert s["records_adjudicated"] == 0
    assert s["superseded_debt_resolved"] == []
    assert rc == 2
    assert "the debt was paid" not in se


def test_an_entry_whose_record_is_no_longer_published_is_reported_not_claimed(
        tmp_path):
    """Inert, and said to be inert — but not called a re-adjudication.

    The entry can suppress nothing, which a reader should know. That it is
    inert is an observation of the CORPUS though; a record can also leave the
    population by becoming unparsable or by the check being pointed at the
    wrong tree, and neither of those is a debt anybody paid.
    """
    root = _corpus(tmp_path, {
        "ic/am/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=9)})
    bl = _baseline(tmp_path, [_ENTRY.format(rec="ic/deleted/r.json")])
    rc, rep, se = _report(root, tmp_path / "b", "--baseline", str(bl))
    s = rep["summary"]
    assert rc == 0, se
    assert s["records_adjudicated"] == 1          # something WAS adjudicated
    assert s["superseded_debt_resolved"] == []
    assert s["recorded_debt_status"][0]["status"] == P.DEBT_RECORD_UNPUBLISHED
    assert "the debt was paid" not in se
    assert "no such record" in se


def test_an_entry_whose_rule_did_not_run_is_not_resolved_by_the_others(
        tmp_path):
    """Per RULE, not per record — a record can be partly adjudicated.

    The record here IS adjudicated, by the rule the gate does declare. An entry
    naming a DIFFERENT rule was not re-examined by that, and inheriting the
    other rule's silence would be the same wrong inference at finer grain.
    """
    rec = "ic/an/reports/phase3/si_mcf_sta_check.json"
    root = _corpus(tmp_path, {rec: _si_record(verdict="PASS",
                                              coupling_pairs=9)})
    bl = _baseline(tmp_path, [
        f"si_mcf_sta_check::{rec}::PASS->FAIL::si_mcf_sta_check.a-rule-that-"
        f"was-withdrawn"])
    rc, rep, se = _report(root, tmp_path / "b", "--baseline", str(bl))
    s = rep["summary"]
    assert rc == 0, se
    assert s["records_adjudicated"] == 1
    assert s["superseded_debt_resolved"] == []
    c = s["recorded_debt_status"][0]
    assert c["status"] == P.DEBT_UNADJUDICATED
    assert c["blocked_by"] == P.DEBT_RULE_NOT_APPLIED
    assert "the debt was paid" not in se


def test_an_unreadable_register_entry_is_not_a_resolution(tmp_path):
    """A hand-edited register can hold something that names no record."""
    root = _corpus(tmp_path, {
        "ic/ao/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=9)})
    bl = _baseline(tmp_path, ["not-a-key"])
    rc, rep, se = _report(root, tmp_path / "b", "--baseline", str(bl))
    assert rc == 0, se
    assert rep["summary"]["superseded_debt_resolved"] == []
    assert rep["summary"]["recorded_debt_status"][0]["status"] == (
        P.DEBT_ENTRY_UNREADABLE)
    assert "the debt was paid" not in se


def test_the_debt_key_round_trips_through_its_parser():
    """The two halves of the entry format cannot drift apart.

    Read outside-in, so a record path is whatever lies between the gate and the
    rule — including a separator, which a corpus path is entitled to contain
    and which this program has no business forbidding.
    """
    for rec in ("ic/a/r.json", "ic/a::b/r.json", "r.json"):
        f = {"gate": "g", "record": rec, "carried_verdict": "PASS",
             "would_issue": "VACUOUS_PASS", "rule_id": "g.rule"}
        assert P.parse_debt_key(P.debt_key(f)) == (
            "g", rec, "PASS->VACUOUS_PASS", "g.rule")
    for bad in ("", "g", "g::r", "g::r::PASS->FAIL", "::r::PASS->FAIL::x"):
        assert P.parse_debt_key(bad) is None, bad


def test_write_baseline_refuses_to_drop_what_nothing_re_adjudicated(tmp_path):
    """The same deletion through the other door — and it was worse there.

    `--write-baseline` performed the shrink the FAIL message asked for, and
    performed it silently at rc 0: measured against the real register under a
    stale digest, the pre-fix write path left ZERO entries and exited clean.
    """
    rec = "ic/ap/reports/phase3/si_mcf_sta_check.json"
    root = _corpus(tmp_path, {rec: _si_record(verdict="PASS",
                                              coupling_pairs=0)})
    altered = _gate_copy(tmp_path, _stale_digest)
    bl = _baseline(tmp_path, [_ENTRY.format(rec=rec)])

    rc, _so, se = _run(root, "--baseline", str(bl), "--write-baseline",
                       programs_dir=altered)
    assert rc == 1
    assert "refusing to DROP" in se
    assert json.loads(bl.read_text())["known"] == [_ENTRY.format(rec=rec)]

    # ... and it is not a flag away: --ignore-baseline is a READ semantic, so a
    # write must still know what it is about to delete.
    rc2, _so2, se2 = _run(root, "--baseline", str(bl), "--write-baseline",
                          "--ignore-baseline", programs_dir=altered)
    assert rc2 == 1, se2
    assert json.loads(bl.read_text())["known"] == [_ENTRY.format(rec=rec)]


def test_write_baseline_still_drops_an_entry_that_was_re_adjudicated(tmp_path):
    """The guard must not freeze the register: a real shrink still writes."""
    root = _corpus(tmp_path, {
        "ic/aq/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="VACUOUS_PASS", coupling_pairs=0)})   # corrected upstream
    bl = _baseline(tmp_path, [
        _ENTRY.format(rec="ic/aq/reports/phase3/si_mcf_sta_check.json")])
    rc, _so, se = _run(root, "--baseline", str(bl), "--write-baseline")
    assert rc == 0, se
    assert json.loads(bl.read_text())["known"] == []


# ── 8. the real corpus, which is why this program exists ───────────────────
@needs_corpus
def test_runs_on_the_real_published_corpus_and_stays_decisive(tmp_path):
    """Structural, so it survives the benchmark-agent correcting the records.

    Pinning "exactly two stale" would red the moment the records are fixed,
    which would make the guard argue against its own remedy. What must hold
    forever is that the check reaches a decision on real data, that its
    denominator adds up, and that every staleness it reports is reproducible
    from the named record's own fields.
    """
    _CELLS = corpus_root()
    rc, rep, _se = _report(_CELLS, tmp_path)
    assert rc in (0, 1)
    s = rep["summary"]
    assert s["records_found"] > 0
    assert s["records_adjudicated"] > 0, "nothing on the real corpus decidable"
    assert s["records_adjudicated"] + s["records_undecidable"] == s[
        "records_found"]
    assert _gd.disclosure_violations(s) == []
    for f in rep["findings"]:
        if f["kind"] != P.STALE:
            continue
        rec = json.loads((_CELLS / f["record"]).read_text())
        assert rec["verdict"] == f["carried_verdict"]
        # The gate-SPECIFIC substance, keyed on which gate declared the rule.
        # This line used to run for EVERY stale record — a si_mcf_sta_check
        # field written into a gate-agnostic loop. It held only while that gate
        # was the sole declarer; the first other declaration (dfm_screen_check,
        # #562) raised KeyError: 'summary' on a record with no such field.
        if f["gate"] == "si_mcf_sta_check":
            assert rec["summary"]["coupling_pairs"] == 0
        elif f["gate"] == "dfm_screen_check":
            _cats = {str(x.get("category", ""))
                     for x in rec.get("findings") or [] if isinstance(x, dict)}
            assert _cats & {"VIA_DEFS_NOT_FOUND", "VIA_USES_NOT_FOUND"}, _cats
        assert f["would_issue"] != f["carried_verdict"]


@pytest.mark.skipif(not _CORPUS.is_dir(), reason="no published corpus here")
def test_the_real_corpus_is_not_written_to(tmp_path):
    """READ-ONLY is a property of the program, asserted on the real tree."""
    before = subprocess.run(
        ["git", "-C", str(_REPO), "status", "--porcelain", "--", "benchmark-data"],
        capture_output=True, text=True, timeout=60).stdout
    _rc, _rep, _se = _report(_CORPUS, tmp_path)
    after = subprocess.run(
        ["git", "-C", str(_REPO), "status", "--porcelain", "--", "benchmark-data"],
        capture_output=True, text=True, timeout=60).stdout
    assert after == before


# --- vibe-ic#555: git lists it, the disk does not have it

def test_a_tracked_file_absent_from_disk_is_not_unparsable(tmp_path, monkeypatch):
    """Enumeration comes from git; reading comes from the filesystem.

    Those disagree in a sparse or partial checkout, and the missing path was
    counted as `unparsable` — a bucket meaning the file's CONTENT is bad. That
    is what made this gate host-dependent: measured on the same commit, a
    working checkout adjudicated 225 records and a fresh `--detach` worktree
    224. Both said PASS, from different populations, and a denominator that
    moves with the machine makes every ratio above it unreadable.
    """
    import published_record_staleness_check as P

    root = tmp_path / "corpus"
    (root / "ic").mkdir(parents=True)
    real = root / "ic" / "present.json"
    real.write_text(json.dumps({"program": "x_check", "verdict": "PASS"}))
    ghost = root / "ic" / "never_materialised.json"      # tracked, not on disk

    monkeypatch.setattr(P, "_tracked_paths",
                        lambda r: ([real, ghost], "git-tracked"))
    d = P.discover(root)
    assert d.absent_from_disk == 1, \
        "a path git lists and the disk lacks is its own state"
    assert d.unparsable == 0, \
        "counted as unparsable — that bucket means the CONTENT is bad"
    assert len(d.records) == 1


def test_the_absent_count_reaches_the_summary():
    """WIRING, and I got this wrong once already in this file.

    The count was published into the DENOMINATOR block while the PASS line
    reads `summary` — two different dicts, so the disclosure would have been
    silently always-zero. Both carry it now.
    """
    import inspect
    import published_record_staleness_check as P
    src = inspect.getsource(P)
    assert src.count('"json_tracked_but_absent_from_disk": disc.absent_from_disk') >= 2, \
        ("the count is published in only one of the two dicts; whichever the "
         "PASS line does not read reports zero forever")


def test_a_record_in_a_deliberately_ignored_tree_is_outside_the_population(
        tmp_path, monkeypatch):
    """Disclosure made the difference legible; it did not remove it.

    The probe still reported HOST_DEPENDENT because 225 != 224. The cause, once
    #556's investigation named it: these are symlinks into
    `benchmark-data/ic/*/clean_run_*/`, which `.gitignore:138` excludes on
    purpose — a raw run directory can carry a commercial-PDK identifier in its
    NAME. Whether such a record resolves is a fact about which machine ran the
    flow, never about the commit, so it is outside the population by the
    repository's own declaration.

    Measured after: checkout and a fresh worktree both report 7 of 224.
    """
    import published_record_staleness_check as P

    root = tmp_path / "corpus"
    (root / "ic").mkdir(parents=True)
    real = root / "ic" / "kept.json"
    real.write_text(json.dumps({"program": "x_check", "verdict": "PASS"}))
    ignored = root / "ic" / "in_ignored_tree.json"
    ignored.symlink_to("../raw/out.json")

    monkeypatch.setattr(P, "_tracked_paths",
                        lambda r: ([real, ignored], "git-tracked"))
    monkeypatch.setattr(P, "_target_deliberately_untracked",
                        lambda r, p: p.name == "in_ignored_tree.json")
    d = P.discover(root)
    assert d.deliberately_untracked == 1
    assert d.absent_from_disk == 0, \
        "an excluded record must not also be counted as missing"
    assert len(d.records) == 1


def test_ignore_is_asked_of_git_rather_than_matched_here():
    """A second implementation of git's ignore rules disagrees with the first.

    Verified the hard way in #555: my model of what a negation inside an
    excluded directory does was wrong, and git's answer was right.
    """
    import inspect
    import published_record_staleness_check as P
    src = inspect.getsource(P._target_deliberately_untracked)
    assert "check-ignore" in src
    assert "fnmatch" not in src and "re.match" not in src


# ── 9. MAY ONLY SHRINK is enforced on the READ path too (vibe-ic#922) ──────
#
# The ratchet lived entirely inside --write-baseline. A register is a JSON
# file, so the writer was never the only way to add an entry to it, and adding
# one by hand is exactly how a NEW superseded record stops being NEW.
_A_WRITTEN_REASON = ("a rule was newly registered for this gate, so records "
                     "it never reached are adjudicated for the first time")


def _write_register(root: Path, bl: Path, *args, programs_dir: Path = None):
    """Produce a register the sanctioned way — through the writer."""
    return _run(root, "--baseline", str(bl), "--write-baseline", *args,
                programs_dir=programs_dir)


def _a_superseded_key(root: Path, tmp_path: Path) -> str:
    """The debt key of a superseded record in ``root``, taken from the report
    the program itself emits rather than rebuilt here."""
    _rc, rep, _se = _report(root, tmp_path, "--ignore-baseline")
    stale = [f for f in rep["findings"] if f["kind"] == P.STALE]
    assert stale, "fixture carries no superseded record"
    return P.debt_key(stale[0])


def _add_superseded(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_si_record(verdict="PASS", coupling_pairs=0),
                            indent=2) + "\n")


def test_an_entry_appended_by_hand_is_not_read_as_recorded_debt(tmp_path):
    """THE BYPASS, end to end through the CLI.

    --write-baseline refuses to GROW the register without a written reason.
    Nothing asked the same question of the file it reads, so the refusal was
    one text editor away from optional: append the key of a NEW superseded
    record and the gate whose whole job is to FAIL on it reports PASS.

    Measured on the unfixed program: rc 0 at the last step.
    """
    root = _corpus(tmp_path, {
        "ic/aj/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=4)})
    bl = tmp_path / "register.json"
    rc, _so, se = _write_register(root, bl)
    assert rc == 0, se
    assert json.loads(bl.read_text())["known"] == []

    # a superseded record lands afterwards — the gate must FAIL on it
    _add_superseded(root, "ic/ak/reports/phase3/si_mcf_sta_check.json")
    assert _run(root, "--baseline", str(bl))[0] == 1

    # ... and appending its key by hand must not be how that stops
    doc = json.loads(bl.read_text())
    doc["known"] = sorted(doc["known"] + [_a_superseded_key(root, tmp_path)])
    bl.write_text(json.dumps(doc, indent=2) + "\n")

    rc2, _so2, se2 = _run(root, "--baseline", str(bl))
    assert rc2 == 1, "a hand-grown register silenced a NEW superseded record"
    assert "outside --write-baseline" in se2


def test_the_same_growth_through_the_writer_is_still_trusted(tmp_path):
    """THE GUARD THAT MUST NOT MOVE.

    Rejecting the hand-grown register is worth nothing if the legitimate one
    is rejected too — that is a gate that says FAIL more often, not a ratchet.
    Same corpus, same entry, same final `known` list as the test above; the
    only difference is which path produced the file. This must pass both
    before and after the fix.
    """
    root = _corpus(tmp_path, {
        "ic/al/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=4)})
    bl = tmp_path / "register.json"
    assert _write_register(root, bl)[0] == 0

    _add_superseded(root, "ic/am/reports/phase3/si_mcf_sta_check.json")
    rc, _so, se = _write_register(root, bl, "--scope-expanded",
                                  _A_WRITTEN_REASON)
    assert rc == 0, se
    assert len(json.loads(bl.read_text())["known"]) == 1
    assert _run(root, "--baseline", str(bl))[0] == 0, "the writer's own output"


def test_a_reason_is_spent_by_the_write_it_authorised(tmp_path):
    """A `scope_expanded` kept past its write pre-authorises the NEXT growth.

    That is the standing-permission shape #922 is named for, reproduced one
    file over: with a reason parked in the register forever, growing it needs
    only a forged number. The writer records the reason for the write that
    grew, and for no other.
    """
    root = _corpus(tmp_path, {
        "ic/an/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=4)})
    bl = tmp_path / "register.json"
    assert _write_register(root, bl)[0] == 0

    _add_superseded(root, "ic/ao/reports/phase3/si_mcf_sta_check.json")
    assert _write_register(root, bl, "--scope-expanded",
                           _A_WRITTEN_REASON)[0] == 0
    assert json.loads(bl.read_text())["scope_expanded"] == _A_WRITTEN_REASON

    # the next write grows nothing, so the reason is spent
    assert _write_register(root, bl, "--scope-expanded",
                           _A_WRITTEN_REASON)[0] == 0
    assert json.loads(bl.read_text())["scope_expanded"] is None
    assert _run(root, "--baseline", str(bl))[0] == 0

    # ... and one put back by hand is not read as authorisation
    doc = json.loads(bl.read_text())
    doc["scope_expanded"] = _A_WRITTEN_REASON
    bl.write_text(json.dumps(doc, indent=2) + "\n")
    rc, _so, se = _run(root, "--baseline", str(bl))
    assert rc == 1
    assert "standing authorisation" in se


def test_a_register_that_records_no_size_is_reported_not_trusted(tmp_path):
    """`size` is the count the writer sanctioned, and it is what a hand-append
    leaves behind. "No size recorded" is therefore the state a hand-edit
    reaches the moment someone notices the field, so it cannot be waved
    through as nothing-to-check."""
    root = _corpus(tmp_path, {
        "ic/ap/reports/phase3/si_mcf_sta_check.json": _si_record(
            verdict="PASS", coupling_pairs=4)})
    bl = tmp_path / "register.json"
    assert _write_register(root, bl)[0] == 0
    doc = json.loads(bl.read_text())
    doc.pop("size")
    bl.write_text(json.dumps(doc, indent=2) + "\n")

    rc, _so, se = _run(root, "--baseline", str(bl))
    assert rc == 1
    assert "records no `size`" in se
    # and the writer is the repair route, so it must not be blocked by the
    # very defect it exists to fix
    assert _write_register(root, bl)[0] == 0
    assert _run(root, "--baseline", str(bl))[0] == 0


def test_the_shipped_register_is_a_state_the_writer_could_have_produced():
    """Asked of the program's own validator, on the file this repo ships.

    v1.8.75 grew it 2 -> 5 by hand — `previous_size: 2` beside five entries
    with `scope_expanded: null`, a document `--write-baseline` exits 1 on. The
    growth was real and justified; the reason was in the commit message and in
    the file's own `_comment`, i.e. everywhere except the field the ratchet
    reads.
    """
    shipped = _PROGRAMS / P.DEFAULT_BASELINE
    if not shipped.is_file():                          # pragma: no cover
        pytest.skip("no default register in this tree")
    assert P._register_defects(shipped) == []
