#!/usr/bin/env python3
"""vibe-ic#886 — two defects in `flow_gate_enforcement_audit` cancelled into a
clean PASS.

Measured on the shipped program: 120 gates in the flow definition, 101 of them
AUDIT_ONLY, 97 with no declared intent — and the audit exited 0 with
`[PASS] no NEW enforcement contradiction`.

It could do that because the only failing shape was "a gate DECLARES blocking
and is wired AUDIT_ONLY". Four gates declared blocking and all four were
ENFORCED, so the set was empty. The other 85 AUDIT_ONLY gates had declared
nothing at all and were therefore exempt BY CONSTRUCTION: saying nothing was
the reliable way to stay clean, which is the exact inversion of what a gate
register is for.

The second defect hid inside the first. The declaration pattern was unanchored,
so it matched the token anywhere — including the sentence in the audit's OWN
docstring that DOCUMENTS the convention. The audit read that sentence as a
declaration about itself. It stayed invisible only because the orphan scan
globbed `*_check.py` and `*_disclosure.py` and so could not reach a
`*_audit.py`. Widening the glob alone made the program report ITSELF as an
orphan declaring blocking, alongside `silent_decline_audit` — a real orphan the
shipped glob could not reach either.

Every test here is paired: the failing shape AND the shape that must stay
clean, because "reports a finding" is trivially satisfiable by a program that
reports everything.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent


def _audit_mod():
    """Load a private copy so a sibling test's `sys.modules` entry cannot
    decide which version of the program this file measures."""
    spec = importlib.util.spec_from_file_location(
        "_fgea_886", _PROGRAMS / "flow_gate_enforcement_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The sentence from the audit's own docstring that documents the convention.
# It is prose ABOUT the declaration, not a declaration. Reproduced here so the
# regression is pinned to the real text, not a paraphrase of it.
_CONVENTION_PROSE = '''"""A gate program declares its own intent in its
docstring via
              `ENFORCEMENT: blocking` or `ENFORCEMENT: advisory`
and this file only DESCRIBES that convention.
"""
'''

_REAL_DECLARATION = '''"""A gate that means it.

ENFORCEMENT: blocking — and it says so at the start of its own line.
"""
'''


def _tree(root: Path, *, gates: dict, enforced=(), extra: dict = None):
    """A synthetic plugin: `gates` are wired into the flow definition, `extra`
    files sit in the programs dir without being referenced by it. Names in
    `enforced` are invoked by a runner, so the audit calls them ENFORCED."""
    programs = root / "programs"
    programs.mkdir(parents=True, exist_ok=True)
    for name, body in gates.items():
        (programs / f"{name}.py").write_text(body)
    for name, body in (extra or {}).items():
        (programs / f"{name}.py").write_text(body)
    # `runner_source` reads only the names in `_RUNNERS`; one of them is enough.
    (programs / "phase3_one_shot_runner.py").write_text(
        "".join(f'STEP = "{n}.py --run"\n' for n in enforced) or "# no gates\n")
    flow = root / "flow.yaml"
    flow.write_text("steps:\n" + "".join(
        f"  - gate:\n      program_exit_zero: {n}.py\n" for n in gates))
    return flow, programs


# ------------------------------------------------- (a) silence is not consent

def test_an_undeclared_audit_only_gate_is_reported():
    """THE defect. A gate nothing invokes inline, which says nothing about
    whether that was intended, is a gate whose enforcement was never decided.
    The shipped audit could not report this shape at all."""
    m = _audit_mod()
    flow, programs = _tree(
        _mk(), gates={"quiet_check": '"""No declaration anywhere."""\n'})
    rep = m.audit(flow, programs)
    assert [u["gate"] for u in rep["undeclared_audit_only"]] == ["quiet_check.py"], rep
    assert m.main(["--flow", str(flow), "--programs", str(programs),
                   "--baseline", str(programs / "nonexistent.json")]) == 1


def test_an_undeclared_gate_that_a_runner_invokes_is_not_reported():
    """The paired control. ENFORCED means a runner can stop the step it
    guards — the wiring made the decision, so the missing docstring line is
    not a gate whose enforcement is unknown. Without this half, the test
    above is satisfied by reporting every gate in the flow."""
    m = _audit_mod()
    flow, programs = _tree(
        _mk(), gates={"quiet_check": '"""No declaration anywhere."""\n'},
        enforced=["quiet_check"])
    rep = m.audit(flow, programs)
    assert rep["undeclared_audit_only"] == [], rep
    assert m.main(["--flow", str(flow), "--programs", str(programs),
                   "--baseline", str(programs / "nonexistent.json")]) == 0


def test_a_declared_advisory_audit_only_gate_is_not_reported():
    """Second control. `advisory` + AUDIT_ONLY is a decision that was taken
    and matches the wiring. Reporting it would make the register punish the
    gates that did declare, which is backwards."""
    m = _audit_mod()
    flow, programs = _tree(_mk(), gates={
        "polite_check": '"""Says so.\n\nENFORCEMENT: advisory\n"""\n'})
    rep = m.audit(flow, programs)
    assert rep["undeclared_audit_only"] == [], rep


# -------------------------------------- (b) prose about a rule is not the rule

def test_the_sentence_documenting_the_convention_is_not_a_declaration():
    """The self-match. Reading this sentence as intent is how the auditor came
    to declare `blocking` about itself."""
    m = _audit_mod()
    programs = _mk() / "programs"
    programs.mkdir(parents=True)
    (programs / "convention_doc_check.py").write_text(_CONVENTION_PROSE)
    assert m.declared_intent(programs, "convention_doc_check") is None


def test_a_declaration_that_opens_its_line_is_still_read():
    """The paired control: anchoring must not stop reading real declarations.
    Measured over all 120 in-flow gates, it changes no gate's verdict."""
    m = _audit_mod()
    programs = _mk() / "programs"
    programs.mkdir(parents=True)
    (programs / "honest_check.py").write_text(_REAL_DECLARATION)
    assert m.declared_intent(programs, "honest_check") == "blocking"


@pytest.mark.parametrize("body,want", [
    # the one-line docstring form — the quote opens the line, not prose
    ('"""ENFORCEMENT: advisory"""\n', "advisory"),
    ("'''ENFORCEMENT: blocking'''\n", "blocking"),
    # behind a comment marker
    ('"""x"""\n# ENFORCEMENT: advisory\n', "advisory"),
    # indented inside a docstring body
    ('"""x\n\n    ENFORCEMENT: blocking — because y\n"""\n', "blocking"),
])
def test_the_shapes_a_real_declaration_takes(body, want):
    """The anchor must admit every form a gate in this repo actually uses.
    An anchor that only accepted column zero silently demoted
    `\"\"\"ENFORCEMENT: advisory\"\"\"` to UNDECLARED — caught by
    `test_issue306_advisory_gate_slot::test_docstring_declaration_still_wins`,
    which is why that pairing is left intact."""
    m = _audit_mod()
    programs = _mk() / "programs"
    programs.mkdir(parents=True)
    (programs / "shape_check.py").write_text(body)
    assert m.declared_intent(programs, "shape_check") == want


def test_the_token_does_not_bind_to_a_value_on_the_next_line():
    """`\\s*` crossed newlines, so a bare token at the end of a line bound to
    prose underneath it. A declaration lives on one line."""
    m = _audit_mod()
    programs = _mk() / "programs"
    programs.mkdir(parents=True)
    (programs / "wrapped_check.py").write_text(
        '"""Discussion of ENFORCEMENT:\nblocking gates in general.\n"""\n')
    assert m.declared_intent(programs, "wrapped_check") is None


def test_the_orphan_scan_reaches_a_program_that_is_not_named_check():
    """The glob decided what could be an orphan by FILENAME. A declaration is
    the signal; `silent_decline_audit` was a real orphan that `*_check.py` and
    `*_disclosure.py` could not reach."""
    m = _audit_mod()
    flow, programs = _tree(
        _mk(), gates={"wired_check": '"""x"""\n'},
        extra={"stray_audit": _REAL_DECLARATION})
    rep = m.audit(flow, programs)
    assert [o["gate"] for o in rep["orphaned"]] == ["stray_audit"], rep


def test_a_prose_only_program_is_not_reported_as_an_orphan():
    """The paired control for the wider glob: reaching more files must not
    mean inventing declarations in them. This is the exact shape that made the
    auditor name itself once the glob was widened.

    One fixture carries a name the SHIPPED glob already reached, so this is a
    false positive the old program produced on its own terms, not only under
    the widened scan."""
    m = _audit_mod()
    flow, programs = _tree(
        _mk(), gates={"wired_check": '"""x"""\n'},
        extra={"talks_about_it_check": _CONVENTION_PROSE,
               "talks_about_it_audit": _CONVENTION_PROSE})
    rep = m.audit(flow, programs)
    assert rep["orphaned"] == [], rep


def test_the_audit_does_not_report_itself_over_the_real_tree():
    """End to end on the shipped tree. The program is the auditor, not one of
    the gates it audits, and it must not appear in its own findings."""
    m = _audit_mod()
    rep = m.audit(_PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml",
                  _PROGRAMS)
    named = ([o["gate"] for o in rep["orphaned"]]
             + [c["gate"] for c in rep["contradictions"]]
             + [u["gate"] for u in rep["undeclared_audit_only"]])
    assert not [n for n in named if n.startswith("flow_gate_enforcement_audit")], named


# ------------------------------------------------------- (c) it must be run

def test_the_audit_is_invoked_by_the_repo_hygiene_suite():
    """An auditor nobody runs has judged nothing. This is a PIN, not a
    regression: the wiring already exists (vibe-ic#538 / v1.6.29). It fails if
    someone deletes the invocation, or downgrades it to the tolerating form
    that cannot fail the landing gate."""
    ci = _PROGRAMS.parents[3] / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not ci.is_file():
        pytest.skip(f"repo hygiene suite not present at {ci}")
    lines = [ln.strip() for ln in ci.read_text().splitlines()
             if "flow_gate_enforcement_audit.py" in ln
             and not ln.lstrip().startswith("#")]
    assert lines, f"nothing in {ci} invokes the audit"
    assert all(ln.startswith("run ") for ln in lines), (
        "the audit is wired, but not at a severity that can fail the suite: "
        f"{lines}")


# --------------------------------------------------------------------- helper

_COUNT = [0]


def _mk() -> Path:
    """A fresh temp dir per call. `tmp_path` is per-test, and several tests
    here build two trees."""
    import tempfile
    _COUNT[0] += 1
    return Path(tempfile.mkdtemp(prefix=f"fgea886_{_COUNT[0]}_"))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
