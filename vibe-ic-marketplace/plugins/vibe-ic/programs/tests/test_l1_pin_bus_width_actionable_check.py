#!/usr/bin/env python3
"""Smoke tests for l1_pin_bus_width_actionable_check.py.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. Every behaviour is asserted
in BOTH directions: a deliberately-gutted L1 whose bus pin has no
actionable width must FAIL (rc 1), and the byte-identical fixture with
the width resolved must PASS (rc 0). A test that cannot fail proves
nothing.

All fixtures are SYNTHESIZED neutral data — invented pin names on an
invented block. No real design's files are copied, and no design name,
PDK name or vendor part number appears anywhere.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "l1_pin_bus_width_actionable_check.py"

_spec = importlib.util.spec_from_file_location(
    "l1_pin_bus_width_actionable_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ---------------------------------------------------------------- fixture
def _write_l1(project: Path, pin_table):
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "synth_block", "pin_table": pin_table},
                   ensure_ascii=False), encoding="utf-8")


def _write_input(project: Path, relpath: str, text: str):
    p = project / "input" / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _run(project: Path):
    out = project / "verdict.json"
    rc = mod.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


# A synthesized design input that declares one numeric bus, one
# parameterised bus and one scalar. Neutral names, no real design.
_SYNTH_RTL = """
module synth_block #(parameter DEPTH = 16) (
  input  wire                 clk_in,
  input  wire [23:0]          sample_bus,
  output wire [DEPTH-1:0]     accum_bus,
  output wire                 ready_flag
);
endmodule
"""

_GOOD_PINS = [
    {"name": "clk_in", "mode": "input", "width": 1, "msb": 0, "lsb": 0},
    {"name": "sample_bus", "mode": "input", "width": 24, "msb": 23, "lsb": 0},
    {"name": "accum_bus", "mode": "output", "width": 16, "msb": 15, "lsb": 0},
    {"name": "ready_flag", "mode": "output", "width": 1, "msb": 0, "lsb": 0},
]


# ------------------------------------------------- POSITIVE: well-formed
def test_pass_well_formed_layer(tmp_path):
    """Well-formed L1: every bus-confirmed pin has an integer width."""
    _write_input(tmp_path, "vendor_rtl/synth_block.v", _SYNTH_RTL)
    _write_l1(tmp_path, _GOOD_PINS)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    # Both the numeric and the parameterised bus were derived from the
    # design's OWN input, not from any hardcoded list.
    assert rep["bus_confirmed"] == 2
    assert rep["violations"] == []


# ------------------------------- NEGATIVE CONTROL: numeric bus, no width
def test_fail_gutted_numeric_bus_width_missing(tmp_path):
    """Gutted layer: the 24-bit bus loses its width -> must FAIL."""
    _write_input(tmp_path, "vendor_rtl/synth_block.v", _SYNTH_RTL)
    gutted = [dict(p) for p in _GOOD_PINS]
    gutted[1] = {"name": "sample_bus", "mode": "input",
                 "width": None, "msb": None, "lsb": None}
    _write_l1(tmp_path, gutted)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL"
    kinds = {v["kind"] for v in rep["violations"]}
    assert kinds == {"bus_width_unresolvable"}
    v = rep["violations"][0]
    assert v["pin"] == "sample_bus"
    assert v["required_min_bits"] == 24


def test_fail_gutted_prose_width_is_not_actionable(tmp_path):
    """The measured real-world shape: width present but PROSE.

    A token/presence-shaped check reports CAPTURED here. The consumer
    cannot emit a port declaration from a sentence, so this must FAIL.
    """
    _write_input(tmp_path, "vendor_rtl/synth_block.v", _SYNTH_RTL)
    gutted = [dict(p) for p in _GOOD_PINS]
    gutted[2] = {"name": "accum_bus", "mode": "output",
                 "width": "N-bit ([DEPTH-1:0], parameter DEPTH default 16)",
                 "msb": None, "lsb": None}
    _write_l1(tmp_path, gutted)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL"
    assert rep["violations"][0]["pin"] == "accum_bus"


def test_pass_same_pin_once_width_is_resolved(tmp_path):
    """Direction 2 of the same control: resolve the prose -> PASS."""
    _write_input(tmp_path, "vendor_rtl/synth_block.v", _SYNTH_RTL)
    fixed = [dict(p) for p in _GOOD_PINS]
    fixed[2] = {"name": "accum_bus", "mode": "output", "width": 16}
    _write_l1(tmp_path, fixed)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"


def test_fail_width_below_bound_proven_by_input(tmp_path):
    """L1 under-declares a width the design's own input contradicts."""
    _write_input(tmp_path, "vendor_rtl/synth_block.v", _SYNTH_RTL)
    gutted = [dict(p) for p in _GOOD_PINS]
    gutted[1] = {"name": "sample_bus", "mode": "input", "width": 8}
    _write_l1(tmp_path, gutted)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["violations"][0]["kind"] == "bus_width_below_input_bound"
    assert rep["violations"][0]["required_min_bits"] == 24


# ------------------------------------------- FALSE-POSITIVE regressions
def test_part_select_is_a_lower_bound_not_an_equality(tmp_path):
    """Measured FP: `bus[31:8]` is a part-select of a 32-bit port.

    An equality rule reported `inputs=24 L1=32` on a real run. Lower-
    bound semantics must PASS this.
    """
    _write_input(tmp_path, "vendor_rtl/slices.v", """
      assign hi_part = wide_bus[31:8];
      assign lo_part = wide_bus[7:0];
    """)
    _write_l1(tmp_path, [{"name": "wide_bus", "mode": "input", "width": 32}])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    assert rep["bus_confirmed"] == 1


def test_scalar_and_analog_pins_are_not_asserted_on(tmp_path):
    """Measured FP: scalar interrupts and analog pads have no width.

    Firing on every width-less pin hit 25/47 and 22/22 on real runs.
    Pins with no bus evidence must not be asserted on at all.
    """
    _write_input(tmp_path, "vendor_rtl/scalars.v", """
      input  wire irq_line;
      inout  wire supply_pad;
    """)
    _write_l1(tmp_path, [
        {"name": "irq_line", "mode": "input"},
        {"name": "supply_pad", "mode": "inout"},
    ])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["bus_confirmed"] == 0


def test_slash_shorthand_does_not_invent_a_bus(tmp_path):
    """Measured FP: a doc writes `sig_a/b/c[37:0]` as shorthand.

    Matching the bare tail token invented a 38-bit bus for an unrelated
    stub row on a real run. The left boundary must reject `/` and `.`.
    """
    _write_input(tmp_path, "docs/integration.md",
                 "wiring through `bus_in/out/oeb[37:0]` (sliced to BITS)\n")
    _write_l1(tmp_path, [{"name": "oeb", "mode": "output"},
                         {"name": "out", "mode": "output"}])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["bus_confirmed"] == 0


def test_struct_member_reference_does_not_invent_a_bus(tmp_path):
    _write_input(tmp_path, "vendor_rtl/pkg.sv",
                 "assign q = cfg_struct.field_sel[7:0];\n")
    _write_l1(tmp_path, [{"name": "field_sel", "mode": "input"}])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["bus_confirmed"] == 0


def test_hdl_keyword_pin_names_are_not_bus_derived(tmp_path):
    """Measured FP: an extractor emitted pin rows named `output`/`logic`.

    `output [Width-1:0]` is the DECLARATION SYNTAX of some other port.
    Matching a keyword-named junk row against every declaration in the
    design invented 320-bit and 128-bit buses on a real run.
    """
    _write_input(tmp_path, "vendor_rtl/prims.sv", """
      module prim_a #(parameter Width = 8) (
        input        [Width-1:0] d_i,
        output logic [319:0]     wide_o
      );
      endmodule
    """)
    _write_l1(tmp_path, [{"name": "output", "mode": "output"},
                         {"name": "logic", "mode": "output"},
                         {"name": "input", "mode": "input"}])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["bus_confirmed"] == 0


def test_keyword_guard_does_not_mask_a_real_neighbouring_bus(tmp_path):
    """The keyword guard must not weaken derivation for real ports."""
    _write_input(tmp_path, "vendor_rtl/prims.sv", """
      module prim_a (
        input        [Width-1:0] d_i,
        output logic [319:0]     wide_o
      );
      endmodule
    """)
    _write_l1(tmp_path, [{"name": "output", "mode": "output"},
                         {"name": "wide_o", "mode": "output"}])
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert [v["pin"] for v in rep["violations"]] == ["wide_o"]
    assert rep["violations"][0]["required_min_bits"] == 320


def test_open_ended_width_prose_without_a_bit_range_is_not_a_bus(tmp_path):
    """Measured FP shape: a doc saying ">= 1-bit" is not a bus claim."""
    _write_input(tmp_path, "docs/iface.md",
                 "| `gpio_line` | >= 1-bit | output | default 1 pin |\n")
    _write_l1(tmp_path, [{"name": "gpio_line", "mode": "output"}])
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "VACUOUS_PASS"


# -------------------------------------------------------------- plumbing
def test_waiver_downgrades_fail(tmp_path):
    _write_input(tmp_path, "vendor_rtl/synth_block.v", _SYNTH_RTL)
    gutted = [dict(p) for p in _GOOD_PINS]
    gutted[1] = {"name": "sample_bus", "mode": "input"}
    _write_l1(tmp_path, gutted)
    (tmp_path / "waivers.json").write_text(json.dumps({
        mod.WAIVER_KEY: "sample_bus is a wrapper-only tie-off in this "
                        "configuration and is not part of the port list."}))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS_WITH_WAIVER"


def test_vacuous_pass_on_empty_pin_table(tmp_path):
    _write_l1(tmp_path, [])
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "VACUOUS_PASS"


def test_rc2_when_l1_absent(tmp_path):
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    rc, _ = _run(tmp_path)
    assert rc == 2


def test_rc2_when_project_dir_absent(tmp_path):
    assert mod.main([str(tmp_path / "nope")]) == 2
