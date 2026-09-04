#!/usr/bin/env python3
"""One fact, one canonical name — and a synonym table that cannot go stale.

WHAT IT COSTS TO HAVE TWO VOCABULARIES. `every_required_metric_key_has_a
_producer` examines 20 canonical keys and observes TWO of them in emitted
records, then reports axes like `physical.drc` as "NOT PROVEN BY ANY RUN IN
THIS CORPUS". The runs measured them — under the other spelling. A detector
that publishes "I do not recognise this name" as "nobody measured this" is this
repo's worst shape, and the cost is that an axis reported unproven is an axis
nobody goes and fixes.

THE DANGEROUS HALF IS THE FIX, NOT THE DEFECT. A transliteration (`s/__/./g`)
would answer `timing.setup.wns_ns` from `timing__setup__ws`, and those are
different quantities: `ws` is worst slack and may be POSITIVE, `wns` is worst
NEGATIVE slack. Every clean design would then report a negative-slack number it
does not have. So these tests care most about what must NOT resolve.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _metric_vocabulary as V                                 # noqa: E402


def _canonical_axes():
    """The dotted vocabulary, from the module that owns it."""
    feas = importlib.import_module("_ppa.feasibility")
    import re
    return set(re.findall(r"'([a-z_]+(?:\.[a-z_0-9]+)+)'",
                          str(getattr(feas, "DEFAULT_AXES", ""))))


# --------------------------------------------------------------------------- #
# 1. The table describes THIS tree's vocabulary, not one it imagines
# --------------------------------------------------------------------------- #
def test_every_canonical_key_named_here_is_a_real_axis_key():
    """A mapping onto a key no axis asks for answers nobody's question."""
    axes = _canonical_axes()
    assert axes, "the axis vocabulary could not be read; nothing was checked"
    stray = sorted(set(V.SYNONYMS) - axes)
    assert not stray, (
        f"the synonym table names canonical keys the axes do not: {stray}")


def test_every_emitted_spelling_named_here_is_emitted_somewhere():
    """A synonym for a name nothing produces is a table describing fiction."""
    src = "\n".join(p.read_text(errors="replace")
                    for p in _PROGRAMS.glob("*.py"))
    missing = [s for s in V.all_known_spellings() if f'"{s}"' not in src]
    assert not missing, (
        f"the table maps spellings no program emits: {missing}")


# --------------------------------------------------------------------------- #
# 2. What must NOT resolve — the load-bearing half
# --------------------------------------------------------------------------- #
def test_worst_slack_never_answers_worst_NEGATIVE_slack():
    """`ws` may be positive; `wns` may not. The canonical vocabulary carries
    both keys precisely because they are different quantities."""
    rec = {"timing__setup__ws": 0.42}
    val, via = V.resolve(rec, "timing.setup.wns_ns")
    assert (val, via) == (None, None), (
        "worst slack answered worst NEGATIVE slack; a design with 0.42 ns of "
        "positive slack would report a violation number it does not have")
    # And the key it IS is still answered:
    assert V.resolve(rec, "timing.setup.worst_slack_ns") == (0.42,
                                                             "timing__setup__ws")


def test_the_routers_own_drc_never_answers_the_signoff_drc():
    """`route__drc_errors` checks a SUBSET of the sign-off deck, on the DEF.

    Letting it answer is how a clean router log reads as a clean die — the
    exact shape that made a 393-violation run look like a 0-violation one.
    """
    rec = {"route__drc_errors": 0}
    assert V.resolve(rec, "physical.drc.violations") == (None, None)


def test_one_class_of_lvs_error_never_answers_the_total():
    rec = {"design__lvs_unmatched_net__count": 0}
    assert V.resolve(rec, "physical.lvs.violations") == (None, None), (
        "a design may match every net and still fail LVS on devices or pins")


def test_neither_antenna_population_answers_the_total():
    """Counted per NET and per PIN; neither alone is the total."""
    for k in ("antenna__violating__nets", "antenna__violating__pins"):
        assert V.resolve({k: 0}, "physical.antenna.violations") == (None, None)


def test_an_xor_difference_is_not_an_equivalence_verdict():
    """Zero XOR says two LAYOUTS match, not that the netlist implements the
    RTL."""
    rec = {"design__xor_difference__count": 0}
    assert V.resolve(rec, "equivalence.verdict") == (None, None)


def test_a_pre_route_stage_value_never_answers_the_signoff_one():
    rec = {"cts__timing__setup__ws": 0.9}
    assert V.resolve(rec, "timing.setup.worst_slack_ns") == (None, None), (
        "the value after CTS is not the value after route")


# --------------------------------------------------------------------------- #
# 3. What must resolve — or the table is machinery that changes nothing
# --------------------------------------------------------------------------- #
def test_the_signoff_drc_resolves_from_either_engine():
    for k in ("klayout__drc_error__count", "magic__drc_error__count"):
        val, via = V.resolve({k: 3}, "physical.drc.violations")
        assert (val, via) == (3, k), (
            "the tool prefix names WHO measured it, not a different quantity")


def test_max_slew_and_max_transition_are_the_same_rule():
    val, via = V.resolve({"design__max_slew_violation__count": 2},
                         "timing.drv.max_tran_violations")
    assert val == 2 and via == "design__max_slew_violation__count"


def test_the_canonical_key_wins_when_both_are_present():
    """Otherwise a stale synonym could outrank a freshly written canonical."""
    rec = {"physical.drc.violations": 1, "klayout__drc_error__count": 99}
    assert V.resolve(rec, "physical.drc.violations") == (1,
                                                         "physical.drc.violations")


def test_a_zero_resolves_like_any_other_value():
    """`0` is a measurement. A resolver using truthiness would drop exactly the
    values a clean run reports, and report them as unmeasured."""
    val, via = V.resolve({"klayout__drc_error__count": 0},
                         "physical.drc.violations")
    assert val == 0 and via == "klayout__drc_error__count"


# --------------------------------------------------------------------------- #
# 4. The table must not silently go stale
# --------------------------------------------------------------------------- #
def test_every_entry_states_why_it_is_that_relation():
    """A synonym without a reason is a guess carrying a table's authority."""
    for canon, entries in V.SYNONYMS.items():
        for spelling, rel, why in entries:
            assert rel in (V.SAME_FACT, V.NARROWER, V.RELATED), (canon, rel)
            assert len(why.strip()) >= 40, (
                f"{canon} <- {spelling} is asserted with no usable reason "
                f"({len(why.strip())} chars)")


def test_unmapped_reports_by_name_rather_than_silently_passing():
    """The register-that-must-be-hand-fed defect, guarded.

    The emitted vocabulary grows; this table does not grow by itself. What it
    must never do is stay quiet about the difference.
    """
    assert V.unmapped(["timing__setup__ws"]) == []
    assert V.unmapped(["something__nobody__mapped"]) == \
        ["something__nobody__mapped"]
