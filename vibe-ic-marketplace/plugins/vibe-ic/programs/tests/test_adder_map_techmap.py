#!/usr/bin/env python3
"""adder_map_techmap.py — staged adder-map recipe + applied-verification.

These tests are built from REAL yosys artefacts, not invented strings:
  * the map fixtures reproduce the shape of yosys's own `+/choices/*.v`
    (a `$lcu` map) and `+/techmap.v` (a self-sufficient map declaring both
    `$lcu` and the `$alu` rule that creates it);
  * the log fixtures reproduce yosys's real `Using template ...` output, both
    from the run where the declared Kogge-Stone map BOUND and from the run
    where it silently fell through to the default Brent-Kung.

The regression they guard: `techmap -map <lcu-map>` alone rewrites NOTHING, and
the flow used to report that no-op as an adopted knob.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import adder_map_techmap as A  # noqa: E402


# --- fixtures: real yosys map/log shapes -----------------------------------

# A parallel-prefix choice map: keys on $lcu, does NOT provide the $alu rule.
LCU_MAP = '''
(* techmap_celltype = "$lcu" *)
module _80_lcu_kogge_stone (P, G, CI, CO);
        parameter WIDTH = 2;
        input [WIDTH-1:0] P, G;
        input CI;
        output [WIDTH-1:0] CO;
        wire [1023:0] _TECHMAP_DO_ = "proc; opt -fast";
endmodule
'''

# The base techmap shape: declares $lcu AND $alu, so it can create what it
# consumes -> self-sufficient, must NOT get +/techmap.v appended.
SELF_SUFFICIENT_MAP = '''
(* techmap_celltype = "$lcu" *)
module _90_lcu_brent_kung (P, G, CI, CO);
        parameter WIDTH = 2;
endmodule

(* techmap_celltype = "$alu" *)
module _90_alu (A, B, CI, BI, X, Y, CO);
        parameter A_WIDTH = 1;
endmodule
'''

# An ORFS-style map keyed on a front-end cell: needs no help, must stay
# byte-identical to the legacy single-map command.
ADD_MAP = '''
(* techmap_celltype = "$add" *)
module my_tech_adder (A, B, Y);
        parameter A_WIDTH = 1;
endmodule
'''

# Real log excerpt: the declared Kogge-Stone map DID bind.
LOG_APPLIED = """
7.1. Executing Verilog-2005 frontend: /foss/tools/yosys/share/yosys/choices/kogge-stone.v
Using template $paramod\\_80_lcu_kogge_stone\\WIDTH=32'00000000000000000000000000100000 for cells of type $lcu.
Using template $paramod\\_80_lcu_kogge_stone\\WIDTH=32'00000000000000000000000000000111 for cells of type $lcu.
"""

# Real log excerpt: the SAME map was staged, but the default Brent-Kung ran.
LOG_SILENT_FALLTHROUGH = """
Using template $paramod\\_90_lcu_brent_kung\\WIDTH=32'00000000000000000000000000100000 for cells of type $lcu.
Using template \\_90_alu for cells of type $alu.
Using template \\_90_fa for cells of type $fa.
"""


# --- celltype / module parsing ---------------------------------------------

def test_declared_celltypes_reads_the_techmap_attribute():
    assert A.declared_celltypes(LCU_MAP) == {"$lcu"}
    assert A.declared_celltypes(SELF_SUFFICIENT_MAP) == {"$lcu", "$alu"}
    assert A.declared_celltypes(ADD_MAP) == {"$add"}


def test_declared_celltypes_empty_for_a_map_without_the_attribute():
    assert A.declared_celltypes("module foo(); endmodule") == set()


def test_map_module_names_in_declaration_order():
    assert A.map_module_names(SELF_SUFFICIENT_MAP) == [
        "_90_lcu_brent_kung", "_90_alu"]


# --- the recipe decision ----------------------------------------------------

def test_lcu_map_needs_the_base_techmap():
    """THE BUG: a $lcu map alone matches nothing, because $lcu does not exist
    until the $alu rule runs."""
    assert A.needs_base_techmap(LCU_MAP) is True


def test_map_that_declares_its_own_producer_is_self_sufficient():
    """yosys's own +/techmap.v declares $lcu AND $alu — appending the base map
    to it would be redundant."""
    assert A.needs_base_techmap(SELF_SUFFICIENT_MAP) is False


def test_front_end_celltype_map_needs_no_help():
    assert A.needs_base_techmap(ADD_MAP) is False


def test_step_for_lcu_map_puts_staged_first_then_base_in_ONE_call():
    step = A.build_adder_map_step("/w/_ref_adder_map.v", LCU_MAP)
    assert step == "techmap -map /w/_ref_adder_map.v -map +/techmap.v"
    # Ordering is load-bearing: the staged map must win over the base map.
    assert step.index("/w/_ref_adder_map.v") < step.index("+/techmap.v")
    # ONE techmap call, not two — they must share a fixpoint.
    assert step.count("techmap -map") == 1


def test_step_for_add_map_is_the_legacy_single_map_command():
    """Backward-compat guard: a map needing no help must emit exactly what the
    flow emitted before this fix."""
    assert (A.build_adder_map_step("/w/_ref_adder_map.v", ADD_MAP)
            == "techmap -map /w/_ref_adder_map.v")


def test_empty_staged_path_is_rejected():
    with pytest.raises(ValueError):
        A.build_adder_map_step("", LCU_MAP)


# --- applied-verification (the §4.05 honesty half) -------------------------

def test_verify_detects_the_map_actually_binding():
    applied, reason = A.verify_map_applied(LOG_APPLIED, LCU_MAP)
    assert applied is True
    assert "_80_lcu_kogge_stone" in reason


def test_verify_detects_the_SILENT_fallthrough_and_names_the_culprit():
    """The regression this whole module exists for: the staged map was present
    but yosys used the default. That must read NOT APPLIED, and must say what
    ran instead."""
    applied, reason = A.verify_map_applied(LOG_SILENT_FALLTHROUGH, LCU_MAP)
    assert applied is False
    assert "_90_lcu_brent_kung" in reason


def test_verify_never_passes_on_absence_of_evidence():
    for log in ("", "yosys finished with no errors", "Using template"):
        applied, _ = A.verify_map_applied(log, LCU_MAP)
        assert applied is False, f"empty/opaque log must not read APPLIED: {log!r}"


def test_verify_is_false_when_the_map_declares_no_module():
    applied, reason = A.verify_map_applied(LOG_APPLIED, "// only a comment")
    assert applied is False
    assert "no module" in reason


def test_paramod_specialisation_resolves_to_the_module_name():
    assert A._template_base_name(
        "$paramod\\_80_lcu_kogge_stone\\WIDTH=32'0000") == "_80_lcu_kogge_stone"
    assert A._template_base_name("\\_90_alu") == "_90_alu"


# --- the provenance line ----------------------------------------------------

def test_applied_note_claims_success_only_when_applied():
    ok = A.applied_note("adder_map.v", True, "yosys instantiated _80_lcu_kogge_stone")
    assert "APPLIED" in ok and "NOT APPLIED" not in ok

    bad = A.applied_note("adder_map.v", False, "staged map was NOT used")
    assert "NOT APPLIED" in bad
    # A miss must never be phrased as an adopted knob.
    assert "-> techmap -map" not in bad


# --- real-artefact end-to-end (drives the CLI, reads observable output) -----

def test_cli_exits_nonzero_when_the_declared_map_did_not_bind(tmp_path, capsys):
    m = tmp_path / "adder_map.v"
    m.write_text(LCU_MAP)
    lg = tmp_path / "synth.log"
    lg.write_text(LOG_SILENT_FALLTHROUGH)
    rc = A.main(["--map", str(m), "--log", str(lg)])
    assert rc == 1
    assert "NOT APPLIED" in capsys.readouterr().out


def test_cli_exits_zero_when_the_declared_map_bound(tmp_path):
    m = tmp_path / "adder_map.v"
    m.write_text(LCU_MAP)
    lg = tmp_path / "synth.log"
    lg.write_text(LOG_APPLIED)
    assert A.main(["--map", str(m), "--log", str(lg)]) == 0
