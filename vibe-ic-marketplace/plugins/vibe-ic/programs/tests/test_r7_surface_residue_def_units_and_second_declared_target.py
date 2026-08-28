#!/usr/bin/env python3
"""Four defects a second PDK exposed, each of which was invisible on the first.

Measured on one real run (`subservient` x `gf180mcuD`, r7). Every one of them is
a case where a program assumed something that happens to be true of one PDK / one
document shape and is silently false on the next, and where the WRONG answer is
indistinguishable from the right one in the artefact it produces:

  (1) `sdc_gen` filters the L9 pin list AGAINST the synthesizable top surface
      (#619/#207) and never reads that surface as a SOURCE. When L9 spells a pin
      differently from the RTL that implements it, the pin is DROPPED and the
      port it describes gets no I/O constraint at all. In the limit every input
      is dropped and the deck carries no `set_input_delay` — which is still a
      syntactically valid SDC, and which `sdc_validator_check` FAILs on.

  (2) `def_gds_port_power_restore` converted DEF coordinates to GDS dbu with a
      hard-coded 1000 units/um. A DEF emitted at 2000 units/um puts every
      injected label and rail marker at TWICE its true position, which inflates
      the streamed GDS bounding box by 2x linear / 4x area. A foundry density
      deck divides by that bbox, so it reports every layer at a QUARTER of its
      real coverage and manufactures die-level density violations.

  (3) `declared_pdk_is_the_pdk_used_check` read only the SCALAR `pdk_target`,
      so a design that declares two targets and is built on the second was told
      its declaration names a process no loaded library corroborates.
      `declared_pdk_target_guard` already honours `pdk_target_alternates`; two
      consumers of one declaration must not disagree about what it permits.

  (4) `metal_fill_emit` refused to promote a PARTIAL fill whenever any layer was
      below the foundry floor — so the sign-off DRC measured the UNFILLED GDS
      and reported violations the flow had already fixed on the layers where the
      fill DID succeed.

Every test below is written so it FAILS against the pre-fix code. chip-AGNOSTIC:
the fixtures name open PDKs (the flow's own registry vocabulary) and generic
port/module names; no chip, foundry SKU, vendor or design literal appears.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


# ---------------------------------------------------------------------------
# (1) sdc_gen — the top surface is a SOURCE, not only a filter
# ---------------------------------------------------------------------------
_TOP_RTL = """\
`default_nettype none
module chip_top
  #(parameter memsize = 1024,
    parameter aw = 8)
  (
   input  wire            clk_in,
   input  wire            rst_in,
   output wire [aw-1:0]   o_bus_adr,
   output wire [31:0]     o_bus_wdata,
   output wire            o_bus_we,
   input  wire [31:0]     i_bus_rdata
   );
   assign o_bus_adr   = {aw{1'b0}};
   assign o_bus_wdata = i_bus_rdata;
   assign o_bus_we    = 1'b0;
endmodule
"""


def _sdc_project(tmp_path: Path, l9_pins) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl" / "chip_top.v").write_text(_TOP_RTL)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "doc_id": "L9", "top_module": "chip_top",
        "fields": {"top_module": "chip_top", "top_module_pins": l9_pins},
        "top_module_pins": l9_pins,
    }))
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "doc_id": "L8", "fields": {"clock_mhz": 50.0, "period_ns": 20.0}}))
    (gd / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "doc_id": "L8", "fields": {"clock_mhz": 50.0, "period_ns": 20.0}}))
    return proj


def _run_sdc_gen(proj: Path):
    return _pr.run(
        [sys.executable, str(PROGRAMS / "sdc_gen.py"), str(proj), "--force"],
        capture_output=True, text=True)


def _emitted_sdc(proj: Path) -> str:
    hits = sorted(proj.rglob("chip_top.sdc"))
    assert hits, "sdc_gen wrote no deck"
    return hits[0].read_text()


def test_l9_pin_names_that_miss_the_rtl_still_leave_the_surface_constrained(
        tmp_path):
    """THE DEFECT. L9 names the data ports differently from the RTL that
    implements them, so #619/#207 drop them — and the pre-fix generator emitted
    a deck with NO `set_input_delay` line at all, because `inputs` was empty."""
    l9 = [
        {"name": "clk_in", "mode": "input"},
        {"name": "rst_in", "mode": "input"},
        # spelled as the DOCUMENT spells them, not as the RTL does
        {"name": "o_bus_addr", "mode": "output"},
        {"name": "i_bus_data", "mode": "input"},
        {"name": "o_bus_we", "mode": "output"},
    ]
    proj = _sdc_project(tmp_path, l9)
    res = _run_sdc_gen(proj)
    assert res.returncode == 0, res.stderr
    sdc = _emitted_sdc(proj)

    # The real RTL input keeps its constraint even though L9 misnamed it.
    assert "set_input_delay" in sdc, (
        "the deck carries no input delay at all — every input path is untimed:\n"
        + sdc)
    assert "i_bus_rdata" in sdc
    # ...and the outputs L9 misnamed are constrained on their REAL names.
    for port in ("o_bus_adr", "o_bus_wdata"):
        assert port in sdc, f"{port} left unconstrained\n{sdc}"
    # The names that do NOT exist on the top must never be emitted (#207).
    for ghost in ("o_bus_addr", "i_bus_data"):
        assert f"{{{ghost}}}" not in sdc, f"emitted a non-existent port {ghost}"


def test_a_fully_covering_l9_pin_list_renders_exactly_as_before(tmp_path):
    """NEGATIVE CONTROL. When L9 covers the surface the residue is empty, so a
    design that constrains correctly today must not move."""
    l9 = [
        {"name": "clk_in", "mode": "input"},
        {"name": "rst_in", "mode": "input"},
        {"name": "o_bus_adr", "mode": "output"},
        {"name": "o_bus_wdata", "mode": "output"},
        {"name": "o_bus_we", "mode": "output"},
        {"name": "i_bus_rdata", "mode": "input"},
    ]
    proj = _sdc_project(tmp_path, l9)
    res = _run_sdc_gen(proj)
    assert res.returncode == 0, res.stderr
    assert "did not cover" not in res.stdout, (
        "the residue pass fired on a fully-covered surface:\n" + res.stdout)


def test_residue_never_constrains_a_port_absent_from_the_top(tmp_path):
    """The residue comes from the same parse #207 uses to VALIDATE the deck, so
    it cannot name a port that does not exist — asserted, not assumed."""
    proj = _sdc_project(tmp_path, [{"name": "clk_in", "mode": "input"}])
    res = _run_sdc_gen(proj)
    assert res.returncode == 0, res.stderr
    sdc = _emitted_sdc(proj)
    import re as _re
    top_ports = {"clk_in", "rst_in", "o_bus_adr", "o_bus_wdata",
                 "o_bus_we", "i_bus_rdata"}
    for ref in _re.findall(r"\[get_ports\s*\{?\s*([A-Za-z_]\w*)", sdc):
        assert ref in top_ports, f"SDC references a non-port {ref!r}"


# ---------------------------------------------------------------------------
# (2) def_gds_port_power_restore — the DEF declares its own resolution
# ---------------------------------------------------------------------------
def test_def_units_are_read_from_the_def_not_assumed():
    import def_gds_port_power_restore as dr

    assert dr.def_units_per_micron(
        "VERSION 5.8 ;\nUNITS DISTANCE MICRONS 2000 ;\n") == 2000
    assert dr.def_units_per_micron(
        "VERSION 5.8 ;\nUNITS DISTANCE MICRONS 1000 ;\n") == 1000
    # No declaration -> None, so the caller can DISCLOSE the fallback instead of
    # silently applying it.
    assert dr.def_units_per_micron("VERSION 5.8 ;\n") is None
    assert dr.def_units_per_micron("") is None


def test_a_2000_unit_def_does_not_double_every_injected_coordinate():
    """THE CONSEQUENCE, stated as arithmetic: at 2000 units/um a hard-coded 1000
    puts a label at 2x its true micron position. The scale the restorer computes
    must be the DEF's own, so the same DEF coordinate lands at the same micron
    on both resolutions."""
    import def_gds_port_power_restore as dr

    dbu = 0.001                       # 1000 GDS dbu per micron
    for units, def_coord, want_um in ((1000, 725_000, 725.0),
                                      (2000, 1_450_000, 725.0)):
        scale = (1.0 / dr.def_units_per_micron(
            f"UNITS DISTANCE MICRONS {units} ;")) / dbu
        assert round(def_coord * scale * dbu, 6) == want_um, (
            f"{units} units/um DEF: {def_coord} landed at "
            f"{def_coord * scale * dbu} um, not {want_um}")


# ---------------------------------------------------------------------------
# (3) declared_pdk_is_the_pdk_used_check — a co-declared target is declared
# ---------------------------------------------------------------------------
def _pdk_project(tmp_path: Path, alternates, loaded_lib: str,
                 primary: str = "sky130") -> Path:
    proj = tmp_path / "pdkproj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    fields = {"pdk_target": primary}
    if alternates is not None:
        fields["pdk_target_alternates"] = alternates
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "doc_id": "L19", "doc_name": "L19_CONSTRAINTS_PDK",
        "schema_version": 2, "fields": fields}))
    synth = proj / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "synth.log").write_text(
        f"-- Running command `abc -liberty /pdks/{loaded_lib}/lib/"
        f"{loaded_lib}__tt.lib' --\n")
    return proj


def _run_pdk_gate(proj: Path):
    return _pr.run(
        [sys.executable,
         str(PROGRAMS / "declared_pdk_is_the_pdk_used_check.py"), str(proj)],
        capture_output=True, text=True)


@pytest.mark.parametrize("alternates,loaded,want_rc", [
    # THE DEFECT: built on the SECOND declared target -> must PASS.
    (["sky130", "gf180mcu"], "gf180mcu_fd_sc_mcu7t5v0", 0),
    # NEGATIVE CONTROL 1: no alternates declared -> unchanged, still FAIL.
    (None, "gf180mcu_fd_sc_mcu7t5v0", 1),
    # NEGATIVE CONTROL 2: the alternate is declared but a THIRD process was
    # loaded -> the widening must not leak; still FAIL.
    (["sky130", "gf180mcu"], "NangateOpenCellLibrary", 1),
    # NEGATIVE CONTROL 3: the declared scalar itself was built -> PASS as before.
    (None, "sky130_fd_sc_hd", 0),
])
def test_a_second_declared_target_is_not_a_contradiction(
        tmp_path, alternates, loaded, want_rc):
    proj = _pdk_project(tmp_path / f"{alternates}-{loaded}".replace("/", "_"),
                        alternates, loaded)
    res = _run_pdk_gate(proj)
    assert res.returncode == want_rc, (
        f"alternates={alternates} loaded={loaded}\n"
        f"stdout:\n{res.stdout}\nstderr:\n{res.stderr}")


def test_the_pass_says_which_declared_target_was_not_built(tmp_path):
    """A PASS on a multi-target design must not read like a single-target PASS:
    it has to name the target that was NOT implemented."""
    proj = _pdk_project(tmp_path, ["sky130", "gf180mcu"],
                        "gf180mcu_fd_sc_mcu7t5v0")
    res = _run_pdk_gate(proj)
    assert res.returncode == 0, res.stdout + res.stderr
    out = res.stdout + res.stderr
    assert "declares more than one target" in out, out
    assert "sky130" in out and "gf180mcu" in out, out


# ---------------------------------------------------------------------------
# (4) metal_fill_emit — ship the better of the two layouts, keep the verdict
# ---------------------------------------------------------------------------
def _fill_res(pairs):
    return {"verdict": "PARTIAL", "layers": [
        {"name": n, "density_before": b, "density_after": a,
         "worst_window_before": b, "worst_window_after": a}
        for n, b, a in pairs]}


def test_a_below_floor_fill_that_improved_every_layer_is_promoted():
    """THE DEFECT: the pre-fix policy shipped the UNFILLED GDS whenever any
    layer stayed below the floor, so sign-off reported density violations on the
    layers where the fill HAD succeeded."""
    import metal_fill_emit as mfe

    got = mfe._is_monotone_improvement(_fill_res([
        ("m1", 0.3347, 0.3501),   # cleared
        ("m2", 0.0943, 0.2212),   # improved, still below a 0.30 floor
        ("m4", 0.0219, 0.4235),   # cleared
    ]))
    assert got is not None
    assert [l["layer"] for l in got["layers"]] == ["m1", "m2", "m4"]
    assert "verdict stays FAIL" in got["note"]


@pytest.mark.parametrize("pairs,why", [
    ([("m1", 0.35, 0.34)], "a layer REGRESSED"),
    ([("m1", 0.35, 0.35)], "nothing moved — nothing to gain"),
    ([], "no layers measured"),
])
def test_promotion_refuses_anything_it_cannot_show_is_better(pairs, why):
    import metal_fill_emit as mfe
    assert mfe._is_monotone_improvement(_fill_res(pairs)) is None, why


def test_promotion_refuses_a_layer_with_no_measured_density():
    import metal_fill_emit as mfe
    res = {"verdict": "PARTIAL",
           "layers": [{"name": "m1", "density_before": 0.1},   # no _after
                      {"name": "m2", "density_before": 0.1, "density_after": 0.2}]}
    assert mfe._is_monotone_improvement(res) is None


def test_promotion_refuses_a_fill_that_overshot_a_rule():
    import metal_fill_emit as mfe
    res = _fill_res([("m1", 0.10, 0.99)])
    res["layers"][0]["over_max"] = True
    assert mfe._is_monotone_improvement(res) is None
