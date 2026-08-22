#!/usr/bin/env python3
"""vibe-ic#886 — two defects in `flow_gate_enforcement_audit` cancelled into a
clean PASS.

Measured on the shipped program AFTER #885 landed the clause-grammar walk: 150
gates in the flow definition, 129 of them AUDIT_ONLY, 127 with no declared
intent — and the audit exited 0 with `[PASS] no NEW enforcement contradiction`.

It could do that because the only failing shape was "a gate DECLARES blocking
and is wired AUDIT_ONLY", and no gate was in it. The other 113 AUDIT_ONLY gates
had declared nothing at all and were therefore exempt BY CONSTRUCTION: saying
nothing was the reliable way to stay clean, which is the exact inversion of
what a gate register is for.

The second defect hid inside the first. The declaration pattern was unanchored,
so it matched the token anywhere — including the sentence in the audit's OWN
docstring that DOCUMENTS the convention. The audit read that sentence as a
declaration about itself. It stayed invisible only because the orphan scan
globbed `*_check.py` and `*_disclosure.py` and so could not reach a
`*_audit.py`. Widening the glob alone made the program report ITSELF as an
orphan declaring blocking.

Every test here is paired: the failing shape AND the shape that must stay
clean, because "reports a finding" is trivially satisfiable by a program that
reports everything.
"""
from __future__ import annotations

import importlib.util
import json
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
    #
    # The invocation below CONSUMES the exit status on purpose. Until #884 a
    # bare `STEP = "<gate>.py --run"` — the filename in a string literal — was
    # enough to be scored ENFORCED, and this fixture used exactly that. #884
    # made ENFORCED mean "the status reaches a control-flow decision", so the
    # old fixture stopped producing an enforced gate and this file's paired
    # CONTROL began failing: the gate it calls enforced was, correctly, no
    # longer enforced. The test's intent was always "a genuinely wired gate is
    # not reported"; only the way to build one changed. Keep it honest — a
    # fixture that fakes enforcement would re-assert the very definition #884
    # deleted.
    (programs / "phase3_one_shot_runner.py").write_text(
        "".join(
            f"def step_{i}():\n"
            f"    cp = subprocess.run([sys.executable, \"{n}.py\", \"p\"], check=False)\n"
            f"    if cp.returncode != 0:\n"
            f"        return \"FAIL\"\n"
            f"    return \"PASS\"\n"
            for i, n in enumerate(enforced)
        ) or "# no gates\n")
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
    the signal, and the suffix list could not reach a `*_audit.py` or a
    `*_lint.py` at all, so a genuinely unreachable one was invisible by
    construction."""
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


# ------------------------- (d) the new class is DIFFERENT debt, recorded apart
#
# THE REFUTATION VECTOR. The first fix for #886 was correct about (a) and (b)
# and still had to be rejected: it appended the new `undeclared::` entries to
# `known`, the register whose documented contract is "gates that DECLARE an
# intent they are not wired for". That grew a SHRINK-ONLY register from 0 to 86
# in one commit and turned five previously-green tests red —
#
#     test_306_register_never_grows                    (register grew 0 -> 86)
#     test_306_shipped_tree_is_green_against_its_register
#     test_316_shipped_tree_passes_against_its_recorded_debt
#     test_316_the_recorded_debt_is_named_not_hidden    (kind not in the pair)
#     test_316_a_new_contradiction_fails                (failure wording merged)
#
# — two of them inside the file `ci_targeted_test_select.py` picks for this very
# change. Every test below fails on that shape and passes on this one, so the
# guard is the separation itself and not just the reporting.

_BASELINE = _PROGRAMS / "flow_gate_enforcement_baseline.json"


def test_the_undeclared_class_is_not_recorded_in_the_known_register():
    """`known` keeps its contract. An `undeclared::` entry there makes the
    register's own `_comment` false and is the precise shape that turned the
    two #316 guards red."""
    doc = json.loads(_BASELINE.read_text())
    assert [k for k in doc["known"] if k.startswith("undeclared::")] == [], (
        "the #886 class was appended to `known`, whose stated contract is "
        "gates that DECLARE an intent they are not wired for")
    for k in doc["known"]:
        assert k.partition("::")[0] in ("contradiction", "orphan"), k


def test_the_new_register_is_ratcheted_too():
    """A second register that nobody ratchets is a waiver list with extra
    steps. It carries its own recorded size, in its own key, so growth in one
    class can never be licensed by a reason given for the other."""
    doc = json.loads(_BASELINE.read_text())
    assert "undeclared_known" in doc, "the #886 register is not in the baseline"
    assert "undeclared_previous_size" in doc, (
        "`undeclared_known` has no recorded previous size, so nothing stops "
        "it growing")
    prev_u = doc["undeclared_previous_size"]
    assert prev_u is None or len(doc["undeclared_known"]) <= prev_u
    assert doc["undeclared_known"], (
        "the register is empty while the audit reports the class — that would "
        "mean the finding is not actually recorded anywhere")


def test_a_write_puts_the_two_classes_in_separate_registers():
    """Not vacuous on the shipped tree's current contents: this builds one gate
    of EACH kind and reads back where each landed."""
    m = _audit_mod()
    root = _mk()
    flow, programs = _tree(root, gates={
        "faux_check": _REAL_DECLARATION,            # declares blocking...
        "quiet_check": '"""No declaration anywhere."""\n',
    })                                              # ...and nothing is ENFORCED
    bl = root / "bl.json"
    assert m.main(["--flow", str(flow), "--programs", str(programs),
                   "--baseline", str(bl), "--write-baseline",
                   "--scope-expanded",
                   # #900 requires the reason to NAME an entry it excuses, so a
                   # padded string cannot buy a widening. This reason predates
                   # that rule; naming the two gates keeps the test's intent
                   # (the classes are recorded APART) and satisfies it honestly.
                   "a synthetic tree built by the #886 regression test to "
                   "prove faux_check and quiet_check are recorded apart"]) == 0
    doc = json.loads(bl.read_text())
    assert doc["known"] == ["contradiction::faux_check.py"], doc
    assert doc["undeclared_known"] == ["undeclared::quiet_check.py"], doc


def test_each_register_fails_in_its_own_words(capsys):
    """The merged wording told a gate that declares NOTHING that it "declares
    an intent it is not wired for" — a small lie about the defect just found,
    and the assertion `test_316_a_new_contradiction_fails` makes."""
    m = _audit_mod()
    root = _mk()
    flow, programs = _tree(root, gates={
        "faux_check": _REAL_DECLARATION,
        "quiet_check": '"""No declaration anywhere."""\n',
    })
    bl = root / "bl.json"
    bl.write_text(json.dumps({"known": [], "undeclared_known": []}))
    assert m.main(["--flow", str(flow), "--programs", str(programs),
                   "--baseline", str(bl)]) == 1
    out = capsys.readouterr().out
    assert "declare an intent they are not wired for" in out, out
    assert "declare no intent at all" in out, out


def test_an_absent_register_is_unrecorded_not_empty(capsys):
    """A baseline written before this register existed must not read as "no
    undeclared debt" — that would report the whole class as absent, and a
    later write would report every entry as `paid`."""
    m = _audit_mod()
    root = _mk()
    flow, programs = _tree(
        root, gates={"quiet_check": '"""No declaration anywhere."""\n'})
    bl = root / "bl.json"
    bl.write_text(json.dumps({"known": []}))       # the pre-#886 file shape
    assert m.main(["--flow", str(flow), "--programs", str(programs),
                   "--baseline", str(bl)]) == 1
    assert "UNRECORDED" in capsys.readouterr().out


def test_a_growing_register_still_needs_a_stated_reason(capsys):
    """The ratchet the two registers share. Splitting them must not create a
    second register that grows for free."""
    m = _audit_mod()
    root = _mk()
    flow, programs = _tree(
        root, gates={"quiet_check": '"""No declaration anywhere."""\n'})
    bl = root / "bl.json"
    bl.write_text(json.dumps({"known": [], "undeclared_known": []}))
    assert m.main(["--flow", str(flow), "--programs", str(programs),
                   "--baseline", str(bl), "--write-baseline"]) == 1
    out = capsys.readouterr().out
    assert "refusing to GROW the baseline `undeclared_known`" in out, out
    assert json.loads(bl.read_text())["undeclared_known"] == [], (
        "the refused write landed anyway")


def test_a_repo_gate_suite_invocation_is_wiring(capsys):
    """`orphan` claims nothing runs the program. The flow definition is not the
    only place a gate is wired: `silent_decline_audit` declares `advisory`, is
    in no flow YAML, and runs blocking from `repo_hygiene_gates.sh` on every
    landing. Widening the orphan glob to every `*.py` surfaced it as the ONE
    new candidate across 1127 files, and reporting it would have recorded debt
    that could only be paid by wiring it somewhere it does not belong."""
    m = _audit_mod()
    root = _mk()
    flow, programs = _tree(root, gates={"wired_check": '"""x"""\n'},
                           extra={"stray_audit": _REAL_DECLARATION})
    assert [o["gate"] for o in m.audit(flow, programs)["orphaned"]] == \
        ["stray_audit"], "control: with no suite, it IS an orphan"
    ci = root / "tools" / "ci"
    ci.mkdir(parents=True)
    (ci / "gates.sh").write_text('run "x" python3 "$PG/stray_audit.py"\n')
    assert m.audit(flow, programs)["orphaned"] == [], (
        "a program the repo-gate suite invokes is not unreachable")


def test_a_gate_only_MENTIONED_in_a_suite_comment_is_still_an_orphan():
    """The paired control. The suite documents heavily, and names gates in
    prose precisely to say they are NOT wired there; counting that as wiring
    would be the false negative mirroring the false positive above."""
    m = _audit_mod()
    root = _mk()
    flow, programs = _tree(root, gates={"wired_check": '"""x"""\n'},
                           extra={"stray_audit": _REAL_DECLARATION})
    ci = root / "tools" / "ci"
    ci.mkdir(parents=True)
    (ci / "gates.sh").write_text("# stray_audit.py is deliberately NOT run\n")
    assert [o["gate"] for o in m.audit(flow, programs)["orphaned"]] == \
        ["stray_audit"], "a comment is not an invocation"


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
