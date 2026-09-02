#!/usr/bin/env python3
"""`fsm_state_coverage_check` selects FSM files by the SHARED structural rule.

MEASURED, opentitan_aes on plugin v1.15.66 (a clean clone, a clean corpus and a
new project dir):

    FAIL: FSM_STATE_COVERAGE_MISSING — L9/L11 docs name 30 FSM state(s) but
    RTL FSM(s) lack matches for 2: [EVEN, ODD]. RTL declared 127 states.

EVEN and ODD are declared in `prim_sync_reqack.sv`, a file staged in the very
tree the gate was reading:

    typedef enum logic { EVEN, ODD } sync_reqack_fsm_e;
    sync_reqack_fsm_e src_fsm_ns, src_fsm_cs;

The gate never opened it. Its file selector required the identifier prefix
`S_` / `ST_` / `STATE_` to appear somewhere in the file — a NAME CONVENTION —
while the L6/L9 producer that put EVEN and ODD into the documents reads the
tree with `_rtl_fsm_extract`, the STRUCTURAL rule. Of a 130-file staged tree
declaring five credited machines, the convention selected exactly one file.

Two readers of one artefact reaching opposite verdicts is the shape
`_rtl_fsm_extract` exists to end; this pins that this gate is now one of its
readers, and that the widening is additive.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import fsm_state_coverage_check as G  # noqa: E402


# The measured shape, reduced: a credited state machine whose file carries no
# `S_` / `ST_` / `STATE_` identifier anywhere.
NO_CONVENTION = """
module prim_sync_reqack (input clk_i, input rst_ni, input req, output ack);
  typedef enum logic { EVEN, ODD } sync_reqack_fsm_e;
  sync_reqack_fsm_e src_fsm_ns, src_fsm_cs;
  always_comb begin
    src_fsm_ns = src_fsm_cs;
    case (src_fsm_cs)
      EVEN: if (req) src_fsm_ns = ODD;
      ODD:  if (req) src_fsm_ns = EVEN;
      default: src_fsm_ns = EVEN;
    endcase
  end
endmodule
"""

# The convention shape the gate has always selected.
CONVENTION = """
module ctrl;
  typedef enum logic [1:0] { S_IDLE, S_RUN, S_DONE } ctrl_e;
  ctrl_e c_fsm_cs, c_fsm_ns;
  always_comb begin
    c_fsm_ns = c_fsm_cs;
    case (c_fsm_cs)
      S_IDLE: c_fsm_ns = S_RUN;
      S_RUN:  c_fsm_ns = S_DONE;
      default: c_fsm_ns = S_IDLE;
    endcase
  end
endmodule
"""

# An enum that is NOT a state type: declared, never bound to a state register.
# The rule must refuse it, or "structural" would just mean "any enum".
NOT_A_STATE_TYPE = """
module cfg;
  typedef enum logic [1:0] { MODE_ECB, MODE_CBC, MODE_CTR } mode_e;
  mode_e cfg_mode;
  assign cfg_mode = MODE_ECB;
endmodule
"""


def _project(tmp_path: Path, rtl: dict[str, str],
             doc_states: list[str]) -> Path:
    proj = tmp_path / "proj"
    rtl_dir = proj / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    for name, text in rtl.items():
        (rtl_dir / name).write_text(text)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L11_OTP_CONTENT.json").write_text(
        json.dumps({"fsm_states": doc_states}))
    return proj


def _names(files) -> set[str]:
    return {f.name for f in files}


def test_a_credited_machine_without_the_name_convention_is_selected(tmp_path):
    """The measured case. `prim_sync_reqack.sv` carries no `S_`/`ST_`/`STATE_`
    identifier and is a state machine by the rule."""
    proj = _project(tmp_path, {"prim_sync_reqack.sv": NO_CONVENTION},
                    ["EVEN", "ODD"])
    assert "prim_sync_reqack.sv" in _names(G._find_fsm_files(proj))


def test_the_gate_passes_where_it_used_to_report_the_states_as_missing(
        tmp_path):
    """End to end: the documents name EVEN and ODD, the RTL declares them, and
    the verdict is no longer that the RTL lacks them."""
    proj = _project(tmp_path, {"prim_sync_reqack.sv": NO_CONVENTION},
                    ["EVEN", "ODD"])
    result = G.check(proj)
    assert result["pass"] is True, result
    assert result.get("missing_states") == [], result
    assert "prim_sync_reqack.sv" in {Path(p).name
                                     for p in result.get("fsm_files", [])}


def test_the_convention_shape_is_still_selected(tmp_path):
    """REGRESSION CONTROL. The change is additive — a design whose FSM files
    carry the convention must be byte-unchanged."""
    proj = _project(tmp_path, {"ctrl.sv": CONVENTION},
                    ["S_IDLE", "S_RUN", "S_DONE"])
    assert "ctrl.sv" in _names(G._find_fsm_files(proj))
    assert G.check(proj)["pass"] is True


def test_an_enum_that_is_not_a_state_type_does_not_make_a_file_eligible(
        tmp_path):
    """VACUITY CONTROL. Without this the widening would read "any file with a
    typedef enum", and every mode/opcode enum in the tree would enter the
    denominator. `mode_e` is declared and never bound to a state register."""
    proj = _project(tmp_path, {"cfg.sv": NOT_A_STATE_TYPE}, ["MODE_ECB"])
    assert "cfg.sv" not in _names(G._find_fsm_files(proj))


def test_a_state_the_rtl_really_lacks_is_still_a_failure(tmp_path):
    """DIRECTIONAL CONTROL. The gate must still be able to fail: widening the
    file set must not turn it into a gate that cannot refuse."""
    proj = _project(tmp_path, {"prim_sync_reqack.sv": NO_CONVENTION},
                    ["EVEN", "ODD", "QUIESCENT_TEARDOWN"])
    result = G.check(proj)
    assert result["pass"] is False, result
    assert "QUIESCENT_TEARDOWN" in result["missing_states"], result


def test_a_type_declared_in_a_package_and_bound_in_a_module_is_found(
        tmp_path):
    """Eligibility is decided over the WHOLE tree. The package/module split
    every real design uses declares the type in one file and binds it in
    another; a per-file reading finds neither half."""
    pkg = ("package aes_pkg;\n"
           "  typedef enum logic [1:0] { INIT, ROUND, FINISH } aes_ctrl_e;\n"
           "endpackage\n")
    mod = ("module aes_control_fsm import aes_pkg::*; ();\n"
           "  aes_ctrl_e aes_ctrl_cs, aes_ctrl_ns;\n"
           "  always_comb begin\n"
           "    aes_ctrl_ns = aes_ctrl_cs;\n"
           "    case (aes_ctrl_cs)\n"
           "      INIT: aes_ctrl_ns = ROUND;\n"
           "      ROUND: aes_ctrl_ns = FINISH;\n"
           "      default: aes_ctrl_ns = INIT;\n"
           "    endcase\n"
           "  end\n"
           "endmodule\n")
    proj = _project(tmp_path, {"aes_pkg.sv": pkg, "aes_control_fsm.sv": mod},
                    ["INIT", "ROUND", "FINISH"])
    assert "aes_pkg.sv" in _names(G._find_fsm_files(proj))
    assert G.check(proj)["pass"] is True
