#!/usr/bin/env python3
"""Regression for #207 — sdc_gen must not be a vacuous PASS: a create_clock (or
any get_ports) targeting a port that does not exist on the top it constrains is
an ERROR, not a silent success.

The defect: sdc_gen selected its port surface from the ALL-modules union
(#619), so a clock pin that lives only on an inner module (e.g. an alias
wrapper's `clk_edn_i`) was emitted as `create_clock [get_ports clk_edn_i]` even
though chip_top exposes no such port. STA then runs with NO clock in effect and
reports meaningless slack, while sdc_gen returns PASS.

The fix resolves the TOP module's OWN ports (the netlist STA constrains),
selects AND validates against them, and FAILs when a get_ports name does not
resolve or when no clock lands on a real top port. Evidence (the resolved port
list, the unresolved names, the netlist resolved against) is emitted so the
verdict is cross-checkable.

chip-AGNOSTIC: synthetic generic module/port names only.
"""
import json
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[1]
if str(_PLUGIN) not in sys.path:
    sys.path.insert(0, str(_PLUGIN))
import sdc_gen as G          # noqa: E402
import _path_layout as _pl   # noqa: E402


def _mk(tmp_path: Path, l9_pins, rtl_text, top="chip_top", clock_mhz=100.0):
    gd = _pl.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(
        json.dumps({"clock_mhz": clock_mhz}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": top, "top_module_pins": l9_pins}))
    rtl = _pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.sv").write_text(rtl_text)


def _sdc_text(tmp_path, top="chip_top"):
    return (_pl.fpga_early_dir(tmp_path) / f"{top}.sdc").read_text()


# ---------------------------------------------------------------------------
# THE DEFECT — the only clock the SDC creates does not exist on the top.
# ---------------------------------------------------------------------------
def test_vacuous_sdc_no_real_clock_fails(tmp_path):
    """chip_top has NO clock port; L9's clock pin (clk_edn_i) lives only on an
    inner module. The old union code emitted create_clock [get_ports clk_edn_i]
    and PASSed — STA with no clock. It must now FAIL."""
    _mk(tmp_path,
        l9_pins=[{"name": "clk_edn_i", "mode": "input"},
                 {"name": "data_i", "mode": "input"},
                 {"name": "data_o", "mode": "output"}],
        rtl_text=(
            "module chip_top (\n  input  [7:0] data_i,\n"
            "  output [7:0] data_o\n);\n"
            "  inner u (.clk_edn_i(1'b0), .data_i(data_i));\n"
            "endmodule\n"
            "module inner (\n  input clk_edn_i, input [7:0] data_i\n);\n"
            "endmodule\n"))
    rc = G.main([str(tmp_path), "--top-name", "chip_top", "--force"])
    assert rc == 1, "an SDC whose only clock is not a top port must FAIL (#207)"


def test_phantom_ports_are_not_constrained(tmp_path):
    """chip_top has a real clock clk_i; L9 also lists inner-only phantom ports.
    The generated SDC must constrain ONLY real top ports (the phantoms are
    dropped), and bind the clock to the real clk_i — a valid, non-vacuous SDC."""
    _mk(tmp_path,
        l9_pins=[{"name": "clk_edn_i", "mode": "input"},   # phantom (inner)
                 {"name": "clk_i", "mode": "input"},        # real top clock
                 {"name": "edn_req_i", "mode": "input"},    # phantom (inner)
                 {"name": "data_o", "mode": "output"}],     # real top port
        rtl_text=(
            "module chip_top (\n  input  clk_i,\n  output [7:0] data_o\n);\n"
            "  inner u (.clk_edn_i(clk_i), .edn_req_i(1'b0));\n"
            "endmodule\n"
            "module inner (\n  input clk_edn_i, input edn_req_i\n);\n"
            "endmodule\n"))
    rc = G.main([str(tmp_path), "--top-name", "chip_top", "--force"])
    assert rc == 0, "a top with a real clock must yield a valid SDC"
    text = _sdc_text(tmp_path)
    assert "[get_ports {clk_i}]" in text, "clock must bind the REAL top port"
    assert "clk_edn_i" not in text, "phantom inner clock must not be constrained"
    assert "edn_req_i" not in text, "phantom inner port must not be constrained"


def test_valid_design_passes(tmp_path):
    _mk(tmp_path,
        l9_pins=[{"name": "clk", "mode": "input"},
                 {"name": "reset_n", "mode": "input"},
                 {"name": "data_o", "mode": "output"}],
        rtl_text=("module chip_top (\n  input clk, input reset_n,\n"
                  "  output [7:0] data_o\n);\nendmodule\n"))
    rc = G.main([str(tmp_path), "--top-name", "chip_top", "--force"])
    assert rc == 0
    assert "[get_ports {clk}]" in _sdc_text(tmp_path)


# ---------------------------------------------------------------------------
# EVIDENCE — the verdict must be cross-checkable from the gate's own output.
# ---------------------------------------------------------------------------
def test_evidence_json_emitted(tmp_path):
    _mk(tmp_path,
        l9_pins=[{"name": "clk_edn_i", "mode": "input"},
                 {"name": "data_o", "mode": "output"}],
        rtl_text=("module chip_top (\n  output [7:0] data_o\n);\n"
                  "  inner u (.clk_edn_i(1'b0));\nendmodule\n"
                  "module inner (input clk_edn_i); endmodule\n"))
    rc = G.main([str(tmp_path), "--top-name", "chip_top", "--force"])
    assert rc == 1
    ev = json.loads(
        _pl.report_path(tmp_path, "phase2/gates/sdc_gen.json").read_text())
    assert ev["top"] == "chip_top"
    assert ev["resolved_against"], "must name the netlist it resolved against"
    assert "data_o" in ev["top_ports"] and "clk_edn_i" not in ev["top_ports"]
    # the only clock target is not a real port → no live clock (the vacuous SDC)
    assert ev["live_clocks"] == []
    assert "clk" in ev["unresolved_ports"] or ev["unresolved_ports"]


# ---------------------------------------------------------------------------
# pure-L9 fallback — no rtl/, no netlist to resolve against → do not newly FAIL.
# ---------------------------------------------------------------------------
def test_no_rtl_fallback_still_passes(tmp_path):
    gd = _pl.generated_docs_dir(tmp_path)
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({"clock_mhz": 50}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"top_module": "chip_top",
         "top_module_pins": [{"name": "clk", "mode": "input"},
                             {"name": "d", "mode": "input"}]}))
    rc = G.main([str(tmp_path), "--top-name", "chip_top", "--force"])
    assert rc == 0, "no rtl/ ⇒ no netlist to validate against ⇒ no new FAIL"


# ---------------------------------------------------------------------------
# unit — the SDC port-reference parser.
# ---------------------------------------------------------------------------
def test_sdc_port_refs_parser():
    sdc = (
        "create_clock -name c -period 10 [get_ports {clk_i}]\n"
        "set_input_delay -clock c -max 4 [get_ports {data_i[0]}]\n"
        "create_generated_clock -name d -source [get_ports {clk_i}] "
        "[get_pins {d_reg/Q}]\n")
    clock_refs, all_refs = G._sdc_port_refs(sdc)
    assert clock_refs == ["clk_i"]
    assert "clk_i" in all_refs and "data_i" in all_refs
    assert "d_reg" not in all_refs, "get_pins must not be read as a port"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
