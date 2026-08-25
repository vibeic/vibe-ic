"""`measurement only artefact is not a verdict s` — an axis proof resolved to
the raw measurement instead of to the sign-off comparison.

THE MUTATION IS THE DEFECT THE GATE WAS WRITTEN FOR, verbatim from its
docstring: a consumer resolved a reliability axis to the emitter's RAW
MEASUREMENT file — a record that says, in its own words, that it is the
router's own count of its own result and not a sign-off verdict — and the axis
reported a pass that no comparison had ever produced.

WHAT MOVES, AND WHAT DOES NOT
=============================
One string moves: the `provenance.note` of ONE already-SATISFIED record. Every
file, every record and every axis key is byte-identical between the two arms
apart from that sentence, so the gate prints the SAME denominator in both
directions — MEASURED, both arms:

    examined 5 axis-key record(s) across 2 JSON file(s)

— and the only thing that changed is the ANSWER. That is the property that
makes this pair evidence: a can-fail reached by deleting the corpus would prove
the gate's rc-2 `no record for any axis key was found` path and nothing about
the clause.

THE CORPUS DELIBERATELY CARRIES THE DISQUALIFIED RECORD IN BOTH ARMS.
`em_router_raw.json` is a raw measurement that declares itself not a verdict,
in the CAN-PASS tree too. The gate's own contract says such a record "may be
published, read and reported — it simply cannot carry the verdict", so a
can-pass that omitted it would be passing a tree the defect cannot even occur
in, and would not show that the gate distinguishes publication from proof.

THE AXIS KEYS COME FROM THE GATE'S OWN `_ppa.feasibility`, not from a list
retyped here: the subject's `programs/` directory is left EMPTY so the import
falls through to the real programs tree on `sys.path`. A private copy of that
table is the drift shape that lets a fixture look fine while measuring a
population the gate no longer has.

The tree, the records and the numbers in them are SYNTHETIC and say so. No PPA
or sign-off run stands behind them.

chip-AGNOSTIC / PDK-AGNOSTIC: no process, foundry, tool, vendor or product is
named; the metrics are the repository's own axis keys.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gate_mutation_fixtures as F  # noqa: E402 — kept for the shared helpers

GATE = "measurement only artefact is not a verdict s"

#: Where the axis records live in the subject. Any depth would do — the gate
#: walks the whole root — so this is only a plausible shape.
_AXES_REL = "reports/signoff_axes.json"
_RAW_REL = "reports/em_router_raw.json"

#: The record whose provenance the mutation moves, by axis key.
_MUTATED_METRIC = "reliability.em.violations"

#: A note that describes a COMPARISON: a limit was read, a measurement was read,
#: and the two were put beside each other. Carries no phrase from the gate's
#: disqualifying list.
_COMPARED = ("the sign-off checker read the limit from the process kit's own "
             "technology file and compared the measurement against it")

#: The emitter's own sentence, quoted by the gate's docstring off this tree at
#: `_ppa/backends/orfs.py`. The mutation writes THIS where `_COMPARED` was.
_DISCLAIMED = ("2431 segments, max segment current 1.951e-4 A: this is the "
               "router's own count of its own result; it is not a sign-off "
               "verdict and must not be used as the eligibility term")


def _axes_doc(em_note: str) -> dict:
    """Four SATISFIED axis-key records. `em_note` is the only thing either arm
    changes, and it is the provenance of exactly one of them."""
    def rec(metric, value, note):
        return {
            "metric": metric,
            "value": value,
            "state": "MEASURED",
            "outcomes": ["SATISFIED"],
            "provenance": {"note": note, "synthetic": True},
        }
    return {
        "synthetic": True,
        "what_this_is": "a gate fixture; no sign-off run stands behind it",
        "records": [
            rec("physical.drc.violations", 0, _COMPARED),
            rec("physical.lvs.verdict", "clean", _COMPARED),
            rec("timing.setup.violations", 0, _COMPARED),
            rec(_MUTATED_METRIC, 0, em_note),
        ],
    }


#: A raw measurement, published and disclaimed, satisfying NOTHING. Present in
#: BOTH arms so the corpus is identical and the gate is shown to be quiet about
#: a non-verdict record that carries no proof.
_RAW_DOC = {
    "synthetic": True,
    "records": [{
        "metric": _MUTATED_METRIC,
        "state": "MEASURED",
        "segments": 2431,
        "max_segment_current_a": 1.951e-4,
        "note": _DISCLAIMED,
    }],
}


def _tree(work: Path, em_note: str) -> Path:
    root = work / "subject"
    # The nested layout the gate resolves `programs` through. Left EMPTY: the
    # axis table then imports from the real programs tree, which is the gate's
    # own code and not the fixture's input.
    (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs").mkdir(
        parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / _AXES_REL).write_text(
        json.dumps(_axes_doc(em_note), indent=2) + "\n", encoding="utf-8")
    (root / _RAW_REL).write_text(
        json.dumps(_RAW_DOC, indent=2) + "\n", encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """Every SATISFIED proof names a comparison. rc 0."""
    return _tree(work, _COMPARED)


def can_fail(work: Path):
    """The same four records; the EM proof now rests on the router's own count.

    The expected fragment is the clause's own words. `state` and `outcomes` are
    untouched, so the refusal cannot be the NEVER-A-ZERO clause firing by
    accident — it is the SELF-DECLARED clause, on the sentence the record makes
    about itself.
    """
    return _tree(work, _DISCLAIMED), "declares itself not a verdict"
