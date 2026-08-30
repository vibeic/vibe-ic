#!/usr/bin/env python3
"""The emitted-test templates must not share lines with each other.

WHAT WENT WRONG, MEASURED
=========================
Every emitted regression opens with the same eight docstring lines, carries the
same `run_root()`, and closes with the same `__main__` guard. Each rule's
template used to carry its OWN copy of all three, so ANY TWO templates shared a
run of up to NINE consecutive identical source lines.

That is a merge hazard, not a tidiness complaint. Rebasing the stage-5 rule onto
main, the unconflicted region between two conflict hunks was the START of one
template while BOTH SIDES of the next hunk were TAILS: git had aligned one
template's prefix against another's, so "keep both sides" spliced one head onto
two tails. MEASURED here as a control: two branches that each add one rule,
resolved by keeping both sides of every hunk, produce a file that DOES NOT PARSE
("unterminated triple-quoted string literal") in EITHER merge order.

It was caught only because the two tails happened to close on different quote
characters. A pair that agreed on its quote would have produced a VALID string
containing both bodies, and the emitted regression would have been silently
wrong -- a rejection "proven" by a test that is not the test for it.

THE PROPERTY: a line that exists once cannot be aligned against its own copy.
The shared skeleton lives in `_emitted_doc` / `_emitted_prelude` /
`_emitted_main`, each template composes them, and adding a rule writes no line
another rule also writes.

THIS TEST CAN GO RED, WHICH IS WHY IT IS WORTH HAVING. Every assertion below
fails against the pre-refactor program: the templates were bare string literals
(not compositions), the skeleton appeared five times rather than once, and the
worst shared run was 9.
"""
import ast
import importlib.util
import itertools
import sys
import uuid
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "stage_on_pass_review.py"

#: The builders that hold the skeleton. A template must go through all three.
BUILDERS = ("_emitted_doc", "_emitted_prelude", "_emitted_main")

#: Longest run of consecutive identical source lines two templates may share.
#: What remains at this bound is RULE LOGIC that happens to coincide (R1 and R4
#: both read `top_module` out of the intent), not skeleton -- so it is content,
#: and de-duplicating it would mean sharing a rule's reading of the intent.
MAX_SHARED_RUN = 4

#: A line of the skeleton, which must appear EXACTLY ONCE in the whole program.
SKELETON_ONCE = (
    'This test FAILS while that is true of this run tree and PASSES once ',
    'REPAIR is one of exactly two things, and which one is a design ',
    '        if (d / "phase1" / "generated_docs").is_dir():',
    '    raise AssertionError("no run root above %s" % __file__)',
    '        print("FAIL: %s" % e)',
)


def _source():
    return PROG.read_text(encoding="utf-8")


def _template_nodes(src):
    return {n.targets[0].id: n for n in ast.parse(src).body
            if isinstance(n, ast.Assign)
            and getattr(n.targets[0], "id", "").startswith("_EMITTED_TEST")}


def _template_blocks(src):
    """Each template's own SOURCE lines, keyed by name."""
    lines = src.splitlines()
    nodes = _template_nodes(src)
    return {name: lines[n.lineno - 1:n.end_lineno] for name, n in nodes.items()}


def _longest_run(a, b):
    """Longest run of consecutive identical lines shared by `a` and `b`.

    Blank lines count, because git's diff aligns them too -- excluding them
    would measure a tidier quantity than the one that actually splices
    templates together.
    """
    best, prev = (0, None), [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best[0]:
                    best = (cur[j], a[i - cur[j]:i])
        prev = cur
    return best


def test_every_template_is_composed_from_the_shared_builders():
    """A template that is one big literal carries its own copy of the skeleton."""
    src = _source()
    bare = {}
    for name, node in _template_nodes(src).items():
        calls = {n.func.id for n in ast.walk(node.value)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        missing = [b for b in BUILDERS if b not in calls]
        if missing:
            bare[name] = missing
    assert not bare, (
        "these templates do not go through the shared builders: "
        + "; ".join(f"{k} is missing {v}" for k, v in bare.items())
        + ". A template written as one literal carries its own copy of the "
          "docstring skeleton, the run-root walk and the __main__ guard, which "
          "is the duplication that lets a 3-way merge splice one template's "
          "head onto another's tail.")


def test_the_skeleton_appears_exactly_once_in_the_program():
    """The whole point: one copy, so there is nothing to mis-align against."""
    src = _source()
    dup = {line: src.count(line) for line in SKELETON_ONCE if src.count(line) != 1}
    assert not dup, (
        "these skeleton lines appear more than once: "
        + "; ".join(f"{k!r} x{v}" for k, v in dup.items())
        + ". Each must exist exactly once -- in the builder that owns it -- so "
          "that adding a rule cannot write a line another rule also writes.")


def test_no_two_templates_share_a_long_run_of_lines():
    """The quantity that actually lets git splice two templates together."""
    blocks = _template_blocks(_source())
    assert len(blocks) >= 2, "expected several templates to compare"
    worst = (0, None, None)
    for a, b in itertools.combinations(sorted(blocks), 2):
        n, run = _longest_run(blocks[a], blocks[b])
        if n > worst[0]:
            worst = (n, run, (a, b))
    n, run, pair = worst
    assert n <= MAX_SHARED_RUN, (
        f"{pair[0]} and {pair[1]} share {n} consecutive identical source "
        f"lines (limit {MAX_SHARED_RUN}):\n"
        + "\n".join("    | " + l for l in (run or []))
        + "\nA run this long is what a 3-way merge aligns, and aligning two "
          "templates is how one head acquires two tails.")


def _load():
    """Import the program under its own directory so its siblings resolve."""
    name = "_sopr_" + uuid.uuid4().hex[:8]
    spec = importlib.util.spec_from_file_location(name, PROG)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    sys.path.insert(0, str(PROGRAMS))
    try:
        spec.loader.exec_module(m)
    finally:
        sys.path.remove(str(PROGRAMS))
    return m


def test_no_two_rules_share_an_emitter_or_a_printer():
    """The failure a one-rule-per-stage corpus cannot exhibit.

    `emit_test` looks the body up BY RULE ID, so two rule ids bound to the same
    emitter means one rule's rejection is "proven" by a regression written for
    the other. Composing templates from shared builders is exactly the change
    that could introduce this by accident -- a mis-parameterised composition
    binds two ids to one object and every emitted file still looks well-formed.
    It is invisible while each stage carries one rule, which is why it is
    asserted structurally rather than waited for.
    """
    m = _load()
    for label, reg in (("_EMITTERS", m._EMITTERS), ("_PRINTERS", m._PRINTERS)):
        seen = {}
        for rid, fn in reg.items():
            seen.setdefault(fn, []).append(rid)
        shared = {fn.__name__: ids for fn, ids in seen.items() if len(ids) > 1}
        assert not shared, (
            f"{label} binds one function to several rule ids: {shared}. "
            f"emit_test resolves by rule id, so the second rule's rejection "
            f"would be proven by the first rule's regression.")


def test_every_template_is_distinct():
    """Two rule ids resolving to the same TEXT is the same defect one level down."""
    m = _load()
    tpl = {k: v for k, v in vars(m).items() if k.startswith("_EMITTED_TEST")}
    assert len(tpl) >= 2, "expected several templates"
    dupes = {}
    for a, b in itertools.combinations(sorted(tpl), 2):
        if tpl[a] == tpl[b]:
            dupes.setdefault(tpl[a][:40], []).extend([a, b])
    assert not dupes, (
        f"these templates are byte-identical to each other: {dupes}. Each rule "
        f"emits its own regression; two rules sharing one body means one of "
        f"them refutes nothing it claims to.")


def test_every_enabled_rule_can_reach_its_own_emitter_and_printer():
    """A rule wired in `_RULES` with no emitter raises KeyError in emit_test.

    The reverse -- an emitter registered for a rule `_RULES` does not enable --
    is a LEGITIMATE state this program uses deliberately (v1.13.27 registers
    R5's emitter while leaving it out of `_RULES`, so that enabling it later
    cannot silently write somebody else's test), so it is not asserted against.
    """
    m = _load()
    enabled = {rid for entries in m._RULES.values() for rid, _ in entries}
    for label, reg in (("_EMITTERS", m._EMITTERS), ("_PRINTERS", m._PRINTERS)):
        missing = sorted(enabled - set(reg))
        assert not missing, (
            f"{label} has no entry for enabled rule(s) {missing}; emit_test "
            f"raises KeyError and the rejection is refused as unproven.")
    assert set(m._EMITTERS) == set(m._PRINTERS), (
        "_EMITTERS and _PRINTERS disagree on which rules exist: "
        f"{sorted(set(m._EMITTERS) ^ set(m._PRINTERS))}")
