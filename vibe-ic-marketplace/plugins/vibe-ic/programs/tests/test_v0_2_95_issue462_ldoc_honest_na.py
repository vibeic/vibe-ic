"""Tests for issue #462 — honest-N/A escapes for L6 (no-FSM) and L9 (flat
single-module) in l_doc_structured_field_count_check.py.

ISSUE #462
==========
There was no honest-N/A escape for two legitimate structures:

  (1) L6 FSM floor — an input that explicitly forbids a control FSM (the L6
      doc records fsm_states:[] AND no_fsm_in_input:true) still FAILed the L6
      FSM floor (l6_min=2 for datapath/compute classes), because the floor had
      no zero-value escape. A pure datapath/compute primitive whose spec
      forbids an FSM has no source for FSM states — phase1 cannot synthesise
      one. FIX: when the doc carries no_fsm_in_input/no_fsm==true AND the
      ic_class is a datapath/compute (no-command-protocol) class, return
      N/A-SKIP for the FSM floor.

  (2) L9 structural floor — a flat single-module primitive (submodules:[] but
      top_ports complete) FAILed the ≥3/5 structural floor although a flat
      module with a named top + complete port list is a legitimate, complete
      structure. FIX: for a flat single module (explicit empty submodules AND a
      complete top_ports list AND a named top_module) pass the structural floor
      on structural-fact grounds.

These complete the same honest-N/A family as L3.no_crc / L11.no_otp /
L13.no_lab / L5.no_analog / L12.no_calibration.

CORPUS-SWEEP GUARDS (both required by the issue):
  - an IC with a real FSM must STILL hit the L6 floor;
  - a multi-module design must STILL hit the L9 floor.

chip-AGNOSTIC: all fixtures use synthetic names (mod_top / blk_a / op0…).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROG = Path(__file__).parent.parent / "l_doc_structured_field_count_check.py"
_spec = importlib.util.spec_from_file_location("_l_doc_sfc_462", _PROG)
mod = importlib.util.module_from_spec(_spec)
sys.modules["_l_doc_sfc_462"] = mod
_spec.loader.exec_module(mod)

_check = mod._check_l_doc

# A no-command-protocol datapath/compute class (matches the registry flag
# command_protocol_applicable=False + rtl_gen=null) — chip-AGNOSTIC, names the
# class only, never a chip/vendor/SKU.
_DATAPATH = "digital_arithmetic_primitive"
_CPU = "processor_cpu"


# ===========================================================================
# L6 — honest no-FSM N/A escape (the fixed path)
# ===========================================================================

def test_l6_no_fsm_in_input_datapath_passes():
    """fsm_states:[] + explicit no_fsm_in_input:true + datapath class → N/A
    SKIP → PASS. This is the core fixed path from the issue."""
    data = {"fsm_states": [], "no_fsm_in_input": True}
    ok, reason = _check(6, data, ic_class=_DATAPATH)
    assert ok, reason


def test_l6_no_fsm_flag_datapath_passes():
    """The shorter `no_fsm:true` alias also escapes for a datapath class."""
    data = {"fsm_states": [], "no_fsm": True}
    ok, reason = _check(6, data, ic_class=_DATAPATH)
    assert ok, reason


def test_l6_no_fsm_in_input_cpu_passes():
    """processor_cpu is also a no-command-protocol datapath/compute class →
    escape applies."""
    data = {"fsm_states": [], "no_fsm_in_input": True}
    ok, reason = _check(6, data, ic_class=_CPU)
    assert ok, reason


# ===========================================================================
# L6 — honesty guards (must NOT weaken)
# ===========================================================================

def test_l6_no_fsm_flag_but_not_datapath_class_still_fails():
    """The no_fsm flag alone, on a command/protocol/unknown class, does NOT
    escape — the escape is DOUBLE-KEYED (class flag AND honest declaration).
    A protocol chip's missing FSM is a real extraction bug, not an honest N/A.
    Corpus-sweep spirit: class-detection degradation must not ride into a
    silent skip."""
    data = {"fsm_states": [], "no_fsm_in_input": True}
    ok, _ = _check(6, data, ic_class="unknown")
    assert not ok


def test_l6_datapath_class_but_no_honest_flag_still_fails():
    """A datapath class with zero FSM states but NO explicit no_fsm flag still
    FAILs — a bare missing/empty field never counts as an honest N/A
    (honesty guard (a))."""
    data = {"fsm_states": []}
    ok, _ = _check(6, data, ic_class=_DATAPATH)
    assert not ok


def test_l6_no_fsm_false_still_fails():
    """no_fsm_in_input:false (the design genuinely HAS an FSM) keeps the floor
    in force → FAIL (honesty guard (b))."""
    data = {"fsm_states": [], "no_fsm_in_input": False}
    ok, _ = _check(6, data, ic_class=_DATAPATH)
    assert not ok


def test_l6_partial_fsm_with_flag_still_fails():
    """A doc with a PARTIAL FSM (1 state, below the l6_min=2 datapath floor)
    must NOT ride the no-FSM escape — a source for FSM states exists, so a
    shortfall is an extraction defect, not an honest N/A (the escape fires only
    on a strictly EMPTY fsm_states list)."""
    data = {"fsm_states": [{"name": "idle"}], "no_fsm_in_input": True}
    ok, _ = _check(6, data, ic_class=_DATAPATH)
    assert not ok


# ===========================================================================
# L6 — CORPUS-SWEEP GUARD: a real FSM must still hit the L6 floor
# ===========================================================================

def test_l6_real_fsm_datapath_passes_at_floor():
    """A datapath class WITH a real 2-state FSM passes the l6_min=2 floor on
    real content (not via the escape) — the floor still exists."""
    data = {"fsm_states": [{"name": "idle"}, {"name": "run"}]}
    ok, reason = _check(6, data, ic_class=_DATAPATH)
    assert ok, reason


def test_l6_real_fsm_protocol_class_needs_five():
    """Corpus-sweep guard: a command/protocol class with a REAL FSM still must
    hit the strict ≥5 floor. 4 states fail; 5 pass — the floor is untouched."""
    four = {"fsm_states": [{"name": f"s{i}"} for i in range(4)]}
    ok4, _ = _check(6, four, ic_class="unknown")
    assert not ok4
    five = {"fsm_states": [{"name": f"s{i}"} for i in range(5)]}
    ok5, reason = _check(6, five, ic_class="unknown")
    assert ok5, reason


# ===========================================================================
# L9 — flat single-module structural-fact escape (the fixed path)
# ===========================================================================

def _ports(n):
    return [{"name": f"p{i}", "dir": "input" if i % 2 else "output"}
            for i in range(n)]


def test_l9_flat_single_module_passes():
    """Flat single module: named top_module + explicit empty submodules[] +
    complete top_ports list → PASS on structural-fact grounds (the core fixed
    path from the issue)."""
    data = {
        "top_module": "mod_top",
        "submodules": [],
        "top_ports": _ports(6),
    }
    ok, reason = _check(9, data)
    assert ok, reason


def test_l9_flat_single_module_ports_alias_passes():
    """The `ports` alias (instead of `top_ports`) also satisfies the escape."""
    data = {
        "top_module": "mod_top",
        "submodules": [],
        "ports": _ports(4),
    }
    ok, reason = _check(9, data)
    assert ok, reason


def test_l9_flat_single_module_scalar_ports_passes():
    """Port list of plain string names (not dicts) still counts toward the
    complete-port-list requirement."""
    data = {
        "top_module": "mod_top",
        "submodules": [],
        "top_ports": ["clk", "rst_n", "a", "b", "y"],
    }
    ok, reason = _check(9, data)
    assert ok, reason


# ===========================================================================
# L9 — guards (must NOT weaken)
# ===========================================================================

def test_l9_flat_module_missing_top_module_still_fails():
    """Empty submodules + complete ports but NO named top_module → FAIL (the
    escape requires the named top to anchor the flat structure)."""
    data = {"submodules": [], "top_ports": _ports(6)}
    ok, _ = _check(9, data)
    assert not ok


def test_l9_flat_module_no_ports_still_fails():
    """Named top + empty submodules but an EMPTY port list is not a complete
    structure → FAIL (a flat module with no ports is not a valid structure)."""
    data = {"top_module": "mod_top", "submodules": [], "top_ports": []}
    ok, _ = _check(9, data)
    assert not ok


def test_l9_no_explicit_empty_submodules_still_fails():
    """Named top + complete ports but NO submodules key at all (not an EXPLICIT
    empty list) → FAIL. A bare missing field never rides the escape — only the
    doc's OWN honest `submodules: []` record qualifies."""
    data = {"top_module": "mod_top", "top_ports": _ports(6)}
    ok, _ = _check(9, data)
    assert not ok


# ===========================================================================
# L9 — CORPUS-SWEEP GUARD: a multi-module design must still hit the L9 floor
# ===========================================================================

def test_l9_multimodule_missing_fields_still_fails():
    """Corpus-sweep guard: a MULTI-module design (non-empty submodules) that is
    missing other structural fields does NOT take the flat-module escape and
    must still reach ≥3 typed structural fields. Here: a non-empty submodules
    list alone (n=1) → FAIL."""
    data = {"submodules": [{"inst": "u_a", "of": "blk_a"}]}
    ok, _ = _check(9, data)
    assert not ok


def test_l9_multimodule_with_submodules_but_only_two_fields_still_fails():
    """A multi-module design with top_module + submodules but no ports/fsm
    (n=2) still FAILs the ≥3 floor — the flat-module escape must NOT rescue a
    multi-module design with non-empty submodules."""
    data = {
        "top_module": "mod_top",
        "submodules": [{"inst": "u_a", "of": "blk_a"},
                       {"inst": "u_b", "of": "blk_b"}],
    }
    ok, _ = _check(9, data)
    assert not ok


def test_l9_full_multimodule_still_passes():
    """A complete multi-module design (top + fsm + ports + submodules, n>=3)
    passes on real content — the legacy floor is untouched."""
    data = {
        "top_module": "mod_top",
        "fsm_states": [{"name": "idle"}, {"name": "run"}],
        "top_ports": _ports(4),
        "submodules": [{"inst": "u_a", "of": "blk_a"}],
    }
    ok, reason = _check(9, data)
    assert ok, reason
