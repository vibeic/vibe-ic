"""`population guard asserts equality not a floo` — a guard that cannot answer NO.

THE DEFECT IS THE ONE THE PROGRAM WAS WRITTEN FOR, taken from its own header:
`len(X) <op> N` where `X` is a collection LITERAL in the same scope and `N` is
that literal's own size. "It passes for free, on every tree, forever." So the
mutation moves exactly one bound — `len(_CONTROL) == 5` becomes
`len(_CONTROL) == 7` over a seven-element literal — and nothing else.

WHY THAT ONE ASSERTION AND NOT A NEW FILE. Both arms of this pair must be
measured over the SAME population, or a red can-fail is only evidence that the
corpus changed size. The control module exists in BOTH subjects, holds the same
literal in both, and is counted by both of the gate's printed denominators in
both:

    test modules parsed:             4   4      unchanged
    len() over an unmutated literal: 4   4      unchanged
    guards that cannot fail:         3   4      <- the only thing that moves

Adding a fourth module for the can-fail arm would have moved the first two, and
`test modules parsed: 0` — the empty-corpus refusal — is the vacuity path this
protocol exists to keep out of a can-fail.

WHY THE SUBJECT REPRODUCES THE SHIPPED INVENTORY, AND READS IT RATHER THAN
COPIES IT. The declaration passes no `--inventory`, so the program loads
`tautological_population_guard_inventory.json` out of its OWN directory
whatever tree it is pointed at. A row in that file matching nothing in the
subject is rc 1 by design ("MAY ONLY SHRINK; a row matching nothing is rc 1"),
so a subject that did not contain the recorded debt would be red in BOTH
directions and the can-pass arm would prove nothing. This fixture therefore
READS the shipped inventory at run time and synthesises one guard per row. When
the tree repairs one of those tautologies and the row is removed, the fixture
follows it down on the next run instead of going stale — a hard-coded copy of
the three rows would have had to be edited by hand, and would have gone red
blaming the wrong thing.

chip-AGNOSTIC / PDK-AGNOSTIC: no IC, vendor, foundry, process or product is
named here; the synthesised literals are opaque strings.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402

GATE = "population guard asserts equality not a floo"

#: Where the program looks. `scan()` returns an empty denominator — and the
#: program then reports NOT-A-PASS — for any root without this directory.
_TESTS_REL = Path("vibe-ic-marketplace/plugins/vibe-ic/programs/tests")

#: Loaded from the program's OWN directory on every run, exactly as the
#: declaration causes the program to load it.
_INVENTORY = F.PROGRAMS / "tautological_population_guard_inventory.json"

#: The inventory key is `<file>::<ast.unparse(compare)[:80]>`, so the subject
#: has to reproduce that text byte-for-byte for the row to match.
_ASSERTION_RE = re.compile(r"^len\((\w+)\)\s*(==|>=|>)\s*(\d+)$")

_CONTROL_FILE = "test_gate_fixture_population_control.py"
_CONTROL_NAME = "_CONTROL"
_CONTROL_SIZE = 7
#: A bound the literal does NOT satisfy: measured by the gate, not a tautology.
_CONTROL_PASS_BOUND = 5
#: The literal's own size. This is the defect, and it is the whole mutation.
_CONTROL_FAIL_BOUND = _CONTROL_SIZE


def _inventory_rows() -> list:
    if not _INVENTORY.is_file():
        return []
    return json.loads(_INVENTORY.read_text(encoding="utf-8")).get("known", [])


def _literal(size: int) -> str:
    """A tuple literal of `size` opaque elements. Trailing comma for size 1."""
    return "(" + "".join("%r, " % ("e%d" % i) for i in range(size)) + ")"


def _module_text(guards) -> str:
    """One function per guard, so each binding is alone in its OWN scope.

    Scope is load-bearing in the program under test — its header records that
    module-wide binding produced false positives and that per-scope binding
    took the finding count from 6 to 3. Function scopes also let two rows in
    one file reuse a name without colliding.
    """
    out = ['"""Synthetic population-guard subject. Built by a gate fixture."""',
           ""]
    for i, (name, size, text) in enumerate(guards):
        out.append("def test_guard_%d():" % i)
        if name is not None:
            out.append("    %s = %s" % (name, _literal(size)))
        out.append("    assert %s" % text)
        out.append("")
    return "\n".join(out) + "\n"


def _recorded_guards():
    """file name -> guards, one per shipped inventory row."""
    by_file = {}
    prefix = _TESTS_REL.as_posix() + "/"
    for row in _inventory_rows():
        key = row["key"]
        rel, sep, text = key.partition("::")
        if not sep or not rel.startswith(prefix):
            raise RuntimeError(
                "inventory row %r is not under %s; this fixture can no longer "
                "reproduce the recorded debt and would be red for a reason "
                "that has nothing to do with the predicate" % (key, prefix))
        m = _ASSERTION_RE.match(text.strip())
        if not m:
            raise RuntimeError(
                "inventory row %r does not have the shape len(NAME) <op> N; "
                "this fixture cannot synthesise a subject that matches it"
                % key)
        name, op, bound = m.group(1), m.group(2), int(m.group(3))
        # The size the literal needs for the recorded comparison to be TRUE.
        size = bound + 1 if op == ">" else bound
        by_file.setdefault(rel[len(prefix):], []).append((name, size, text))
    return by_file


def _subject(work: Path, name: str, control_bound: int) -> Path:
    root = work / name
    tests = root / _TESTS_REL
    tests.mkdir(parents=True, exist_ok=True)
    for fname, guards in _recorded_guards().items():
        p = tests / fname
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_module_text(guards), encoding="utf-8")
    (tests / _CONTROL_FILE).write_text(_module_text([
        (_CONTROL_NAME, _CONTROL_SIZE,
         "len(%s) == %d" % (_CONTROL_NAME, control_bound))]), encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The control guard asserts a bound its literal does NOT meet.

    `len(_CONTROL) == 5` over a seven-element tuple is counted by the gate's
    `len() over an unmutated literal` denominator and is not a tautology: it
    can answer NO, which is the whole property.
    """
    return _subject(work, "subject_pass", _CONTROL_PASS_BOUND)


def can_fail(work: Path):
    """The same guard, asserted against the literal's OWN size."""
    root = _subject(work, "subject_fail", _CONTROL_FAIL_BOUND)
    return root, "len(%s) == %d" % (_CONTROL_NAME, _CONTROL_FAIL_BOUND)
