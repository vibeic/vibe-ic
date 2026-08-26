"""`EXECUTABLE = 0` reads like a backlog. It is not.

`closed_loop_executable_coverage_check` publishes 18 `DECLARED_ONLY` edges —
declared in the flow, re-entered by nothing. That number invites the reading
"eighteen edges nobody got round to wiring", and acting on that reading costs
real time: three separate attempts to close the area edge (9 -> 1) in one
session, each abandoned after discovering by hand what this program answers in
a second.

A closed-loop edge is a repair. The trigger names a quantity that is out of
bounds and the fallback step is supposed to change the design so it is not. For
that to be possible the step being re-entered has to be able to SEE the
quantity. If it cannot, re-entering it reproduces what it produced before, and
the loop is inert by construction — which the ECO loop already detects and calls
`FAIL_ECO_INERT`.

MEASURED ON THE SHIPPED FLOW: 21 declared edges, REACHABLE=0, UNREACHABLE=2,
UNSTATED=19.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
_ROOT = _PROGRAMS.parents[3]


def _mod():
    import closed_loop_metric_reaches_its_producer as C
    return C


# ── reading a metric out of a trigger ───────────────────────────────────────
def test_both_metric_spellings_the_flow_uses_are_read():
    """The flow writes metrics two ways and both are its own, not this file's:
    the double-underscore tool form and a dotted L-doc field."""
    m = _mod().metric_tokens(
        "design__instance__area above the design's DECLARED ceiling "
        "(L19.die_area_budget_um); the structure has to change")
    assert m == ["design__instance__area", "L19.die_area_budget_um"]


def test_a_prose_trigger_names_no_metric():
    """19 of the flow's 21 edges are this shape. It is not a defect in the
    trigger — it is the reason the question cannot be put to them."""
    assert _mod().metric_tokens("CDC/RDC violation requires RTL change") == []
    assert _mod().metric_tokens("Test fail traceable to RTL") == []


# ── the false positive that shipped in the first draft ──────────────────────
def test_a_shared_suffix_does_NOT_credit_a_producer():
    """THE BUG THIS TEST EXISTS FOR. The first version searched the last
    segment of a `__` name, so `power__total` searched for `total` — and
    matched the English word inside `placement_legality_check`, reporting the
    power edge REACHABLE on the strength of a coincidence. A metric earns a
    credit only when a producer names the METRIC, never a word it shares."""
    names = _mod()._leaf_names("power__total")
    assert "total" not in names
    assert "power__total" in names


def test_an_L_doc_field_name_IS_searched():
    """The field is what a producer actually reads, and it is specific enough
    to mean only this metric."""
    names = _mod()._leaf_names("L19.die_area_budget_um")
    assert "die_area_budget_um" in names
    assert "L19.die_area_budget_um" in names


# ── the verdict, on the tree that ships ─────────────────────────────────────
def test_the_area_edge_is_unreachable_and_says_why():
    """Measured three ways by hand before this program existed: no RTL producer
    can see an area budget, `step_rtl_gen` is deterministic, and the one
    remediation path accepts two hint kinds, both wiring defects."""
    rows = {r["step"]: r for r in _mod().audit(_ROOT)["edges"]}
    area = rows["9"]
    assert area["verdict"] == "UNREACHABLE", area
    assert "die_area_budget_um" in area["why"]


def test_every_edge_lands_in_exactly_one_of_the_three_verdicts():
    """A census that loses an edge between its buckets is worse than none."""
    rep = _mod().audit(_ROOT)
    kinds = {"REACHABLE", "UNREACHABLE", "UNSTATED"}
    verdicts = [r["verdict"] for r in rep["edges"]]
    assert set(verdicts) <= kinds
    assert len(verdicts) == rep["denominator"]


def test_unstated_is_reported_apart_from_unreachable():
    """"We checked and it cannot" and "we could not check" are different facts.
    Folding the second into the first would report 21 unreachable edges and
    make the flow look worse than it is."""
    rows = _mod().audit(_ROOT)["edges"]
    unstated = [r for r in rows if r["verdict"] == "UNSTATED"]
    assert unstated, "no UNSTATED edge — this distinction is untested"
    assert all("names no metric" in r["why"] or "not in the flow" in r["why"]
               for r in unstated)


# ── the safe direction ──────────────────────────────────────────────────────
def test_the_producer_test_is_deliberately_generous():
    """A bare textual mention counts. Over-crediting is the safe direction for
    an accusation: this program's job is to say an edge CANNOT be closed, and
    that claim must survive the weakest reading of the evidence. An edge
    reported UNREACHABLE under a rule this loose is unreachable under any."""
    import inspect
    src = inspect.getsource(_mod().producer_reads)
    assert "DELIBERATELY GENEROUS" in src
    assert "any(n in text for n in metric_names)" in src


def test_a_zero_denominator_refuses(tmp_path):
    """Nothing to examine is not everything examined and clean."""
    assert _mod().main([str(tmp_path)]) == 2
