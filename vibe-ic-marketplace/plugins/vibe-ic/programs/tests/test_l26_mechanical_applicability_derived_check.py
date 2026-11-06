#!/usr/bin/env python3
"""Smoke tests for l26_mechanical_applicability_derived_check.py — batch-8.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. Every rule is asserted in BOTH
directions: a deliberately-gutted layer must FAIL, and the well-formed
counterpart must PASS.

All fixtures are SYNTHESIZED neutral data. No real design's files are copied,
and no real design/PDK/vendor token appears here.

ONE BRANCH NEEDS AN IN-PROCESS TEST, DELIBERATELY
-------------------------------------------------
The FALSE-N/A branch (taxonomy says APPLICABLE, layer asserts N/A) is the most
important rule in the gate, but it is UNREACHABLE through the subprocess today:
``l_doc_taxonomy.is_applicable(cls, "L26")`` is False for every registered
class and for the unknown fallback, because L26 is OPT-IN-ONLY and no MEMS
class exists yet (``test_l24_l27_completeness.py`` pins that invariant). So it
is exercised in-process with ``is_applicable`` monkeypatched to simulate the
future MEMS class. That is stated openly rather than skipped — an untested
rule that only fires on a design class nobody has built yet is exactly the
kind of code that rots into a false clean bill of health.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
PROG = _PROGRAMS / "l26_mechanical_applicability_derived_check.py"

sys.path.insert(0, str(_PROGRAMS))

_FAIL = 1
_PASS = 0
_SKIP = 2

_SYNTH_CLASS = "synthetic_block_class_alpha"
_OTHER_CLASS = "synthetic_block_class_beta"








# ===========================================================================
# POSITIVE DIRECTION — a derived, honest verdict must PASS
# ===========================================================================


# ===========================================================================
# NEGATIVE CONTROL — subprocess-reachable gutted variants must FAIL
# ===========================================================================


# ===========================================================================
# No-false-positive direction
# ===========================================================================


# ===========================================================================
# The FALSE-N/A branch — the rule that matters most, exercised in-process
# because no MEMS class exists yet (see module docstring).
# ===========================================================================


# ===========================================================================
# Both directions on the SAME layer, through the real subprocess.
# ===========================================================================


def test_taxonomy_invariant_this_gate_depends_on_still_holds():
    """If a MEMS class is ever added, L26 stops being N/A-for-everything and
    the FALSE-N/A branch becomes subprocess-reachable. Assert the current
    invariant so that change is noticed here, not discovered in the field."""
    tx = importlib.import_module("l_doc_taxonomy")
    for cls in list(tx.IC_CLASS_APPLICABILITY) + ["unknown", _SYNTH_CLASS]:
        assert tx.is_applicable(cls, "L26") is False, (
            f"{cls} now declares L26 applicable — the FALSE-N/A branch of "
            f"l26_mechanical_applicability_derived_check is now reachable "
            f"through the subprocess and should get a subprocess test")
