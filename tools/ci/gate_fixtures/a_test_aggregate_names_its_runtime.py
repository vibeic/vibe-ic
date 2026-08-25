"""`a test aggregate names its runtime` — an aggregate whose runtime identity is
PRESENT and is a placeholder.

THE MUTATION IS THE DEFECT THE GATE WAS WRITTEN FOR, verbatim from its
docstring: ``MEASURED: {"image": "unknown", "interpreter": "n/a"} passed, so an
aggregate that named no runtime could satisfy the rule that exists to make it
name one.`` The can-fail arm writes exactly that pair of strings.

Deleting the `runtime` object would also go red, and would prove less: a stamp
that is simply MISSING is the easy half. The half that got past the rule's first
version is the stamp that is there, has the right shape, and establishes nothing
— so that is the one the pair exercises.

WHAT MOVES, AND WHAT DOES NOT
=============================
Two strings move, inside ONE already-present `runtime` object. The file path,
the `kind`, the `cases` list, the per-case rows and `unimportable_plugins` are
byte-identical between the arms, so the gate prints the SAME denominator in both
directions — MEASURED, both arms:

    examined 1 test aggregate(s) under '<subject>'

and the only thing that changed is the ANSWER. That is the property that makes
this pair evidence. A can-fail reached by emptying the tree would drive the
gate's rc-2 `no test aggregate was found` path — the very NOT-CHECKED tier this
gate's declaration carries a dated exemption for — and would say nothing at all
about the predicate.

WHY THE SUBJECT CARRIES A NON-AGGREGATE JSON IN BOTH ARMS
=========================================================
`hygiene_gate_profile.json` is the file the gate's own docstring names as the
false positive its first draft matched: a GATE PROFILE counts passed/failed over
GATES, and pass/fail counting is not distinctive. It is present, identical, in
BOTH trees, so the pair also shows the gate still tells its subject from a gate
profile — the narrowing is exercised rather than asserted.

The tree, the ids and the numbers in it are SYNTHETIC and say so. No test run
stands behind them.

chip-AGNOSTIC / PDK-AGNOSTIC: no process, foundry, tool, vendor or product is
named.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402,F401 — shared helpers / path setup

GATE = "a test aggregate names its runtime"

#: Where the aggregate lives in the subject. Any depth would do — the gate walks
#: the whole root — so this is only a plausible shape.
_AGG_REL = "runs/2026-01-01/pytest_aggregate.json"
_PROFILE_REL = "runs/2026-01-01/hygiene_gate_profile.json"

#: A real runtime identity: an immutable image reference, a named interpreter,
#: and `unimportable_plugins` PRESENT and empty — which the gate documents as a
#: real answer ("asked, none missing"), unlike absence.
_NAMED = {
    "image": "example.invalid/synthetic-runner@sha256:"
             "0000000000000000000000000000000000000000000000000000000000000000",
    "interpreter": "CPython 3.11.2 (synthetic)",
    "unimportable_plugins": [],
}

#: The gate's own quoted seam: both identity fields occupied by placeholders.
#: `unimportable_plugins` stays present and empty, so the refusal cannot be the
#: missing-key branch firing instead.
_PLACEHOLDER = {
    "image": "unknown",
    "interpreter": "n/a",
    "unimportable_plugins": [],
}


def _aggregate(runtime: dict) -> dict:
    """One aggregate with per-test-case rows — the structure the gate selects on.

    `runtime` is the only thing either arm changes.
    """
    return {
        "kind": "test_aggregate",
        "synthetic": True,
        "what_this_is": "a gate fixture; no test run stands behind it",
        "runtime": runtime,
        "passed": 2,
        "failed": 1,
        "cases": [
            {"nodeid": "synthetic/test_alpha.py::test_one", "outcome": "passed"},
            {"nodeid": "synthetic/test_alpha.py::test_two", "outcome": "passed"},
            {"nodeid": "synthetic/test_beta.py::test_three", "outcome": "failed"},
        ],
    }


#: A GATE PROFILE: passed/failed over GATES, no per-case rows. Present in BOTH
#: arms so the denominator is one aggregate in both directions and the gate is
#: shown to leave a non-aggregate alone.
_PROFILE_DOC = {
    "synthetic": True,
    "kind": "hygiene_gate_profile",
    "passed": 7,
    "failed": 0,
    "summary": "a gate profile, not a test aggregate",
}


def _tree(work: Path, runtime: dict) -> Path:
    root = work / "subject"
    (root / "runs" / "2026-01-01").mkdir(parents=True, exist_ok=True)
    (root / _AGG_REL).write_text(
        json.dumps(_aggregate(runtime), indent=2) + "\n", encoding="utf-8")
    (root / _PROFILE_REL).write_text(
        json.dumps(_PROFILE_DOC, indent=2) + "\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The one aggregate names the image, the interpreter and the plugin set. rc 0."""
    return _tree(work, _NAMED)


def can_fail(work: Path):
    """The same aggregate; its identity fields now say "unknown" / "n/a".

    The expected fragment is the gate's own finding line. `unimportable_plugins`
    is untouched and still present, so the refusal cannot be the missing-key
    branch — it is the PLACEHOLDER branch, on the exact two strings the gate's
    docstring records as having passed its first version.
    """
    return _tree(work, _PLACEHOLDER), "omits image, interpreter"
