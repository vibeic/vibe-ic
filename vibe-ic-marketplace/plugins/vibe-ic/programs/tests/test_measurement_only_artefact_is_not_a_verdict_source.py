"""A measurement is not a verdict, and an unmeasured axis is not a zero.

WHY
===
MEASURED: a consumer resolved a reliability axis to the emitter's RAW
MEASUREMENT — 2431 segments, max segment current 1.951e-4 A, no limit and no
count anywhere in it — instead of to the sign-off checker that compares against
the limit from the process kit's technology file. With no count in the artefact
the ABSENCE of a count became indistinguishable from a count of ZERO, and the
axis reported a pass no comparison had produced.

The emitter said so itself, and this tree still carries the sentence at
`_ppa/backends/orfs.py:436` — asserted below, because if that self-declaration
is ever dropped this rule silently loses its subject.

chip-AGNOSTIC: metric-record vocabulary only.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "measurement_only_artefact_is_not_a_verdict_source.py"

_spec = importlib.util.spec_from_file_location("moainavs", _TOOL)
moainavs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(moainavs)

_KEY = "reliability.em.violations"
_NOTE = ("this is the router's own count of its own result; it is not a "
         "sign-off verdict and must not be used as the eligibility term")






_GOOD = {"metric": _KEY, "state": "MEASURED", "value": 0,
         "outcomes": ["SATISFIED"]}


# ------------------------------------------------------------ red controls











# -------------------------------------- a proxy may exist, it may not decide





# ------------------------------------- the self-declaration must still exist

def test_the_emitters_own_disqualifying_sentence_is_still_in_the_tree():
    src = (_PROGRAMS / "_ppa" / "backends" / "orfs.py").read_text(encoding="utf-8")
    assert "it is not a sign-off verdict and must not be used" in src, (
        "the emitter's self-declaration has moved — this rule's subject is "
        "gone and it would pass over nothing")






# -------------------------------------------------------------- verdicts
