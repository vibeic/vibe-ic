#!/usr/bin/env python3
"""Phase 1 reads the implementation a REUSED-IP design STAGES with it.

THE DEFECT, as measured on `opentitan_aes` (2026-09-02, plugin v1.15.50):

  * `L6_CONTROL_LOGIC.json` — `fsm_states: []`, `no_fsm_in_input: true`, over a
    staged tree declaring four closed state enums totalling 28 states.
    `l6_fsm_scaffold_actionable_check` reads that same tree with the same
    structural rule, raised EXTRACTION_APPLICABILITY_CONTRADICTION, and halted
    Phase 1. The gate was right; the producer was blind.
  * `L9_INTEGRATION_SPEC.json` — 9 entries for a 14-port module, missing both
    resets and both alert ports, and carrying two Comportable inter-signal BASE
    names as if they were ports. `professional_tb_gen` then emitted
    `RST = None`.

Both halves are gated on the SAME predicate the rest of the tree already uses
(`_reused_ip_predicate`), and both are fail-closed. The negative controls below
are the load-bearing half: a doc-only design must be byte-unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase1_doc_one_shot_runner as P1  # noqa: E402
import _staged_top_module as STM  # noqa: E402


VENDOR_PKG = """
package d_pkg;
  typedef enum logic [1:0] {
    C_IDLE = 2'b00,
    C_RUN  = 2'b01,
    C_DONE = 2'b10
  } ctrl_e;
endpackage
"""

VENDOR_TOP = """
module widget (
  input  logic          clk_i,
  input  logic          rst_ni,
  input  bus_pkg::req_t bus_i,
  output bus_pkg::rsp_t bus_o,
  output logic          done_o,
  output logic [3:0]    code_o
);
  ctrl_e w_fsm_cs, w_fsm_ns;
  always_comb begin
    case (w_fsm_cs)
      C_IDLE: w_fsm_ns = C_RUN;
      C_RUN:  w_fsm_ns = C_DONE;
      C_DONE: w_fsm_ns = C_IDLE;
    endcase
  end
endmodule
"""

DOC = """# Widget

## Signals

| Signal | Direction | Description |
| --- | --- | --- |
| done_o | output | Completion strobe. |
| code_o | output | Status code. |
| clk_i | input | Core clock. |
"""


def _project(tmp_path: Path, *, ic_class: str, stage_rtl: bool) -> Path:
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "widget_interfaces.md").write_text(DOC)
    (proj / "reports").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": ic_class}))
    if stage_rtl:
        vdir = proj / "input" / "vendor_rtl"
        vdir.mkdir(parents=True)
        (vdir / "d_pkg.sv").write_text(VENDOR_PKG)
        (vdir / "widget.sv").write_text(VENDOR_TOP)
    return proj


def _docs(proj: Path) -> dict:
    return {f.name: f.read_text()
            for f in (proj / "input" / "docs").iterdir() if f.is_file()}


def _l_doc(proj: Path, name: str) -> dict:
    return json.loads(
        (proj / "phase1" / "generated_docs" / name).read_text())


# --------------------------------------------------------------------------
# L6
# --------------------------------------------------------------------------
def test_l6_carries_the_state_machine_the_staged_rtl_declares(tmp_path):
    proj = _project(tmp_path, ic_class="crypto_accelerator", stage_rtl=True)
    P1.gen_l6_control_logic(proj, _docs(proj))
    l6 = _l_doc(proj, "L6_CONTROL_LOGIC.json")

    assert l6["no_fsm_in_input"] is False
    assert l6["no_fsm_states_in_input"] is False
    assert [s["name"] for s in l6["fsm_states"]] == ["C_IDLE", "C_RUN",
                                                     "C_DONE"]
    assert all(s["declared_type"] == "ctrl_e" for s in l6["fsm_states"])
    assert any("input/vendor_rtl/d_pkg.sv" in s["evidence"]
               for s in l6["fsm_states"])
    assert sum(len(s["transitions"]) for s in l6["fsm_states"]) == 3
    machines = {m["machine_id"]: m for m in l6["fsm_machines"]}
    assert machines["ctrl_e"]["closed"] is True
    assert machines["ctrl_e"]["state_count"] == 3


def test_a_design_that_stages_no_rtl_is_unchanged(tmp_path):
    """NEGATIVE CONTROL. The tier must not fire on a doc-only design."""
    proj = _project(tmp_path, ic_class="crypto_accelerator", stage_rtl=False)
    P1.gen_l6_control_logic(proj, _docs(proj))
    l6 = _l_doc(proj, "L6_CONTROL_LOGIC.json")
    assert l6["fsm_states"] == []
    assert l6["no_fsm_in_input"] is True


def test_a_class_with_a_deterministic_generator_is_unchanged(tmp_path):
    """NEGATIVE CONTROL on the OTHER half of the predicate. Staged RTL alone
    is not reused-IP: the class must also carry `rtl_gen: null`."""
    proj = _project(tmp_path, ic_class="unknown", stage_rtl=True)
    P1.gen_l6_control_logic(proj, _docs(proj))
    l6 = _l_doc(proj, "L6_CONTROL_LOGIC.json")
    assert l6["fsm_states"] == []
    assert l6["no_fsm_in_input"] is True


def test_the_gate_accepts_the_l6_this_producer_writes(tmp_path):
    """END TO END, and the point of the whole change: the document and the
    gate now answer the same question with the same code."""
    proj = _project(tmp_path, ic_class="crypto_accelerator", stage_rtl=True)
    P1.gen_l6_control_logic(proj, _docs(proj))
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "d_pkg.sv").write_text(VENDOR_PKG)
    (rtl / "widget.sv").write_text(VENDOR_TOP)

    import l6_fsm_scaffold_actionable_check as gate
    assert gate.main([str(proj)]) == gate.RC_PASS


# --------------------------------------------------------------------------
# L9
# --------------------------------------------------------------------------
def test_resolve_top_module_takes_the_strict_unique_maximum():
    class _M:
        def __init__(self, ports):
            self.ports = {p: object() for p in ports}

    mods = {"top": _M(["clk_i", "done_o", "code_o"]),
            "leaf": _M(["clk_i", "q"]),
            "other": _M(["x"])}
    assert STM.resolve_top_module(mods, ["clk_i", "done_o", "code_o"]) == "top"


def test_resolve_top_module_refuses_a_tie_and_a_thin_overlap():
    class _M:
        def __init__(self, ports):
            self.ports = {p: object() for p in ports}

    tie = {"a": _M(["clk_i", "done_o"]), "b": _M(["clk_i", "done_o"])}
    assert STM.resolve_top_module(tie, ["clk_i", "done_o"]) is None

    thin = {"a": _M(["clk_i"]), "b": _M(["z"])}
    assert STM.resolve_top_module(thin, ["clk_i", "done_o"]) is None
    assert STM.resolve_top_module({}, ["clk_i"]) is None
    assert STM.resolve_top_module(thin, []) is None


def test_declared_ports_carry_the_type_and_withhold_a_struct_width(tmp_path):
    vdir = tmp_path / "input" / "vendor_rtl"
    vdir.mkdir(parents=True)
    (vdir / "widget.sv").write_text(VENDOR_TOP)
    ports = {p["name"]: p for p in STM.staged_top_ports(
        tmp_path, vdir, ["clk_i", "done_o", "code_o"])}

    assert set(ports) == {"clk_i", "rst_ni", "bus_i", "bus_o", "done_o",
                          "code_o"}
    assert ports["rst_ni"]["direction"] == "input"
    assert ports["bus_i"]["data_type"] == "bus_pkg::req_t"
    # A struct instance is not one bit. The number is WITHHELD, not guessed.
    assert "width" not in ports["bus_i"]
    assert ports["code_o"]["width"] == 4
    assert ports["clk_i"]["width"] == 1
    assert ports["done_o"]["source_file"] == "input/vendor_rtl/widget.sv"


def test_l9_gains_the_declared_ports_and_labels_the_doc_only_ones(tmp_path):
    proj = _project(tmp_path, ic_class="crypto_accelerator", stage_rtl=True)
    P1.gen_l1_datasheet(proj, _docs(proj))
    P1.gen_l9_integration_spec(proj, _docs(proj), {})
    l9 = _l_doc(proj, "L9_INTEGRATION_SPEC.json")
    ports = {p["name"]: p for p in l9["top_ports"]}

    # The reset the documents never named is now present, from the RTL.
    assert "rst_ni" in ports
    assert ports["rst_ni"]["direction"] == "input"
    assert "widget.sv" in ports["rst_ni"]["evidence"]
    # A bus-typed port carries its declared type.
    assert ports["bus_i"]["data_type"] == "bus_pkg::req_t"
    # A port the documents DID name keeps its document provenance and gains
    # the RTL declaration alongside it.
    assert ports["done_o"]["declared_by_staged_top"] is True
    assert "rtl_declaration_evidence" in ports["done_o"]
    # The three published aliases still agree (they share one list object in
    # the producer; after serialisation that shows up as equality).
    assert l9["ports"] == l9["top_ports"] == l9["top_module_pins"]


def test_l9_is_unchanged_for_a_design_that_stages_no_rtl(tmp_path):
    """NEGATIVE CONTROL."""
    proj = _project(tmp_path, ic_class="crypto_accelerator", stage_rtl=False)
    P1.gen_l1_datasheet(proj, _docs(proj))
    P1.gen_l9_integration_spec(proj, _docs(proj), {})
    l9 = _l_doc(proj, "L9_INTEGRATION_SPEC.json")
    names = {p["name"] for p in l9["top_ports"]}
    assert "rst_ni" not in names
    assert not any("declared_by_staged_top" in p for p in l9["top_ports"])
