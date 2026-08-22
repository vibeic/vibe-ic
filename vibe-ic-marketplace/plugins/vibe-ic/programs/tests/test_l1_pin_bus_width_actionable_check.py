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
import subprocess
import sys
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


# ============================================================== #
# STRUCTURED SYMBOLIC WIDTH (`width_symbolic`)
#
# The gate used to report two OPPOSITE states with one sentence:
# extraction produced NOTHING (real defect) and extraction produced a
# structured parameterised width (legitimate). These assert the split,
# and — the load-bearing half — that the second does NOT become a free
# pass. Direction 1 of every pair is the state that must still FAIL.
# ============================================================== #

_PARAM_PINS = [
    dict(_GOOD_PINS[0]),
    dict(_GOOD_PINS[1]),
    {"name": "accum_bus", "mode": "output",
     "width": "N-bit ([DEPTH-1:0], parameter DEPTH default 16)",
     "width_symbolic": "DEPTH-1:0", "msb": None, "lsb": None},
    dict(_GOOD_PINS[3]),
]


def test_symbolic_width_resolves_against_an_hdl_parameter_declaration(tmp_path):
    """Structured symbolic width + `parameter DEPTH = 16` in the inputs."""
    _write_input(tmp_path, "vendor_rtl/synth_block.v", _SYNTH_RTL)
    _write_l1(tmp_path, _PARAM_PINS)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    got = {d["pin"]: d["bits"] for d in rep["symbolic_widths_resolved"]}
    assert got == {"accum_bus": 16}, rep


def test_symbolic_width_resolves_against_a_doc_interface_table(tmp_path):
    """Docs-only design: the parameter default lives in a table row.

    No RTL is staged at all, so the HDL dialect cannot fire. This is the
    shape a doc-driven phase1 actually produces.
    """
    _write_input(tmp_path, "docs/interface.md", (
        "| signal | width | dir |\n|---|---|---|\n"
        "| `sample_bus` | 24-bit (`[23:0]`) | in |\n"
        "| `accum_bus` | N-bit (`[DEPTH-1:0]`) | out |\n\n"
        "### Parameters\n\n| name | default | notes |\n|---|---|---|\n"
        "| `DEPTH` | 16 | any positive integer >= 4 |\n"))
    _write_l1(tmp_path, _PARAM_PINS)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    d = rep["symbolic_widths_resolved"][0]
    assert d["bits"] == 16 and "doc-table" in d["resolved_from"], rep


def test_symbolic_width_naming_an_undefined_parameter_still_fails(tmp_path):
    """THE RUBBER-STAMP GUARD.

    `width_symbolic` is present and well-formed, but nothing in the
    design's own inputs gives `DEPTH` a value. Nobody can produce a
    number, so this must still FAIL. Without this, "carries a
    width_symbolic" would itself become the new vacuous pass.
    """
    _write_input(tmp_path, "vendor_rtl/synth_block.v",
                 _SYNTH_RTL.replace("#(parameter DEPTH = 16) ", ""))
    _write_l1(tmp_path, _PARAM_PINS)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL"
    assert rep["violations"][0]["pin"] == "accum_bus"
    assert rep["symbolic_widths_resolved"] == [], rep


def test_symbolic_width_that_is_not_a_range_still_fails(tmp_path):
    """A `width_symbolic` the grammar cannot parse resolves nothing."""
    _write_input(tmp_path, "vendor_rtl/synth_block.v", _SYNTH_RTL)
    pins = [dict(p) for p in _PARAM_PINS]
    pins[2] = dict(pins[2], width_symbolic="see the parameter section")
    _write_l1(tmp_path, pins)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["violations"][0]["pin"] == "accum_bus"


def test_symbolically_resolved_width_is_still_checked_against_the_bound(tmp_path):
    """Resolution does not exempt a pin from the numeric lower bound.

    The inputs index bit 23 of `sample_bus`, and the parameter resolves
    it to 8 — below what the design's own inputs prove. Still FAIL, now
    as below-bound rather than unresolvable.
    """
    _write_input(tmp_path, "vendor_rtl/synth_block.v",
                 _SYNTH_RTL.replace("DEPTH = 16", "NARROW = 8"))
    pins = [dict(p) for p in _GOOD_PINS]
    pins[1] = {"name": "sample_bus", "mode": "input",
               "width": "N-bit ([NARROW-1:0])",
               "width_symbolic": "NARROW-1:0", "msb": None, "lsb": None}
    _write_l1(tmp_path, pins)
    rc, rep = _run(tmp_path)
    assert rc == 1, rep
    assert rep["violations"][0]["kind"] == "bus_width_below_input_bound"
    assert rep["violations"][0]["required_min_bits"] == 24, rep


def test_an_hdl_declaration_outranks_a_doc_table_row(tmp_path):
    """Both dialects present and disagreeing -> the declaration wins."""
    _write_input(tmp_path, "vendor_rtl/synth_block.v", _SYNTH_RTL)
    _write_input(tmp_path, "docs/params.md",
                 "| name | default |\n|---|---|\n| `DEPTH` | 4 |\n")
    _write_l1(tmp_path, _PARAM_PINS)
    rc, rep = _run(tmp_path)
    assert rc == 0, rep
    d = rep["symbolic_widths_resolved"][0]
    assert d["bits"] == 16, rep
    assert "hdl-declaration" in d["resolved_from"], rep


# ── gatekeeper addition at merge (#427): the published layout ───────────────

def test_a_published_cell_resolves_via_the_shared_per_IC_input():
    """#427's corpus table says the three spm cells move FAIL -> PASS. On the
    PUBLISHED cells they did not, and that is the layout the repo points at.

    A published cell is `ic/<IC>/v<ver>_<PDK>/` and has NO `input/` of its
    own — the design input is shared once per IC at `ic/<IC>/input/`.
    `_iter_input_files` looked only at `project/input`, so the symbolic
    resolution found no parameters and the cell still FAILed, while
    `size = 32` sits in `ic/spm/input/docs/L3_external_interface.md`. The fix
    reached source run directories and not the deliverable.
    """
    root = Path(__file__).resolve().parents[5] / "benchmark-data" / "ic"
    cell = root / "spm" / "v1.5.58_ihp-sg13g2"
    if not (cell / "phase1/generated_docs/L1_DATASHEET.json").is_file():
        import pytest
        pytest.skip("published cell not present")
    assert not (cell / "input").is_dir(), \
        "fixture assumption: a published cell carries no input/ of its own"
    assert (cell.parent / "input").is_dir()
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent
                             / "l1_pin_bus_width_actionable_check.py"),
         str(cell)], capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    assert out.lstrip().startswith("PASS"), out[:300]


def test_the_shared_input_fallback_does_not_rescue_a_genuinely_missing_width():
    """The paired half, on a real cell. `caravel_user_project` HAS its own
    `input/` and an `irq` pin with no width at all; reaching further for
    parameters must not turn that into a pass."""
    root = Path(__file__).resolve().parents[5] / "benchmark-data" / "ic"
    cell = root / "caravel_user_project"
    if not (cell / "phase1/generated_docs/L1_DATASHEET.json").is_file():
        import pytest
        pytest.skip("published cell not present")
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent
                             / "l1_pin_bus_width_actionable_check.py"),
         str(cell)], capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    assert out.lstrip().startswith("FAIL"), out[:300]
    assert "irq" in out


# ── the same pair, on a fixture that OWNS ITS PREMISE ───────────────────────
#
# The two tests above read published cells out of the corpus, so each skips
# when its cell is not in the tree. That makes the both-directions property
# above only as durable as the corpus: a retirement that removes one cell
# disarms one half and leaves the other half passing, which proves nothing —
# a fallback that rescued everything would look identical.
#
# These two assert the SAME property on a SYNTHESIZED tree laid out the way
# a published cell is: the design input shared once per IC at `<ic>/input/`,
# and the cell itself carrying no `input/` of its own. They cannot skip, so
# the negative control survives any deletion.
_SHARED_DOCS = (
    "| signal | width | dir |\n|---|---|---|\n"
    "| `sample_bus` | 24-bit (`[23:0]`) | in |\n"
    "| `accum_bus` | N-bit (`[DEPTH-1:0]`) | out |\n\n"
    "### Parameters\n\n| name | default | notes |\n|---|---|---|\n"
    "| `DEPTH` | 16 | any positive integer >= 4 |\n")


def _shared_input_cell(ic_root: Path, pin_table) -> Path:
    """Lay out `<ic>/input/docs/` + `<ic>/<cell>/phase1/generated_docs/` and
    return the CELL, which deliberately carries no `input/` of its own."""
    docs = ic_root / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "interface.md").write_text(_SHARED_DOCS, encoding="utf-8")
    rtl = ic_root / "input" / "vendor_rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "synth_block.v").write_text(_SYNTH_RTL, encoding="utf-8")
    cell = ic_root / "v0.0.0_synthpdk"
    _write_l1(cell, pin_table)
    assert not (cell / "input").is_dir(), \
        "fixture assumption: a published cell carries no input/ of its own"
    return cell


def test_shared_per_IC_input_resolves_a_cell_with_no_input_of_its_own(tmp_path):
    """CAN-PASS half. `accum_bus` is symbolic and nothing in the cell can
    resolve it; reaching up to the shared per-IC input finds `DEPTH = 16`."""
    cell = _shared_input_cell(tmp_path / "synth_ic_pass", _PARAM_PINS)
    rc, rep = _run(cell)
    assert rc == 0, rep
    assert rep["verdict"] == "PASS"
    got = {d["pin"]: d["bits"] for d in rep["symbolic_widths_resolved"]}
    assert got == {"accum_bus": 16}, rep


def test_the_shared_input_fallback_does_not_invent_a_missing_width(tmp_path):
    """CAN-FAIL half, on the identical layout. The shared input is what
    confirms `sample_bus` is a 24-bit bus, and the cell's L1 gives it no
    width at all. Reaching further for parameters must report that, not
    paper over it — otherwise the half above would pass for the wrong
    reason and nobody would be able to tell."""
    gutted = [dict(p) for p in _PARAM_PINS]
    gutted[1] = {"name": "sample_bus", "mode": "input",
                 "width": None, "msb": None, "lsb": None}
    cell = _shared_input_cell(tmp_path / "synth_ic_fail", gutted)
    rc, rep = _run(cell)
    assert rc == 1, rep
    assert rep["verdict"] == "FAIL"
    kinds = {v["kind"] for v in rep["violations"]}
    assert kinds == {"bus_width_unresolvable"}, rep
    v = rep["violations"][0]
    assert v["pin"] == "sample_bus", rep
    assert v["required_min_bits"] == 24, rep
