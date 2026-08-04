"""Two chip-AGNOSTIC Phase-3 defects, both found on a real multi-supply
hard-macro design and both invisible to every gate that ran at the time.

A. SECONDARY-SUPPLY PDN — a hard macro can carry a supply pin bound to a rail
   that is not one of the two core rails (a programming/erase supply, an
   always-on domain, an analog bias). The runner bound such a pin correctly,
   but it emitted the binding AFTER the PDN block, so by the time the rail
   existed `pdngen` had already run and `set_voltage_domain` had only ever been
   told about the core rails. Result: the net existed in the netlist and
   NOWHERE in the layout — a physically floating supply terminal that every
   net-level connectivity check calls "connected", because the NET is
   connected. The rail had no geometry at all.

   The fix builds the PDN AFTER the macro-supply plan and hands it in:
   the rail is registered on the voltage domain and given a macro grid with a
   strap whose offset is computed at RUNTIME from the PLACED pin bbox, so the
   strap is centred on the terminal by construction. A pin that genuinely
   cannot be reached is REPORTED (SECONDARY_PDN_UNREACHED), never fabricated.

B. RESIZER SIZING LIMITS — `PreChecks::checkSlewLimit` computes the best
   achievable transition over `getSwappableCells(buffer_lowest_drive_)`, and
   `getSwappableCells` drops any candidate more than `sizing_area_limit_` /
   `sizing_leakage_limit_` (BOTH default 4.0) times the current cell's. On a
   library whose buffer family spans wider than 4X — which is every library
   measured, open or commercial — the weakest buffer cannot see the strong
   ones, "best achievable" is computed from a crippled pool, and
   `repair_design` ABORTS with [ERROR RSZ-0090] against a max_transition the
   library can in fact meet.

   The fix does NOT widen the timing constraint. `max_transition` is untouched;
   what is restored is the resizer's SWAP POOL, whose 4.0X area/leakage cut-off
   (getSwappableCells, Resizer.cc:2188-2233) is a cost heuristic, not a
   statement about the library's contents. The VALUE is the library's own
   measured buffer-family span, so a library that already fits inside 4X is
   never touched. The block must be emitted BEFORE the first timing-driven
   step, because RSZ-0090 is a fatal error raised from
   `global_placement -timing_driven`.

Both suites pin the EMISSION contract; no OpenROAD needed.
"""
import importlib
import math
import re
from pathlib import Path

R = importlib.import_module("phase3_one_shot_runner")


def _stmt(tcl, statement):
    """Offset of the line that IS ``statement`` (stripped), not merely a line
    that contains it as a substring. `global_connect` is a substring of
    `add_global_connection`, and both `repair_design` and `repair_timing`
    appear in comments — ordering assertions anchored on the bare phrase test
    the comments, not the flow."""
    off = 0
    for line in tcl.splitlines(keepends=True):
        if line.strip() == statement:
            return off
        off += len(line)
    raise AssertionError(f"no line is exactly {statement!r}")


def _stmt_prefix(tcl, statement):
    """Offset of the first line that STARTS with ``statement`` — for commands
    that carry flags (`global_placement -routability_driven ...`). Comment
    lines start with `#`, so the prose that discusses the command is skipped."""
    off = 0
    for line in tcl.splitlines(keepends=True):
        if line.startswith(statement):
            return off
        off += len(line)
    raise AssertionError(f"no line starts with {statement!r}")


class _Pdk:
    """Duck-typed PDK stub: a commercial-style (non-sky130) PDK with a
    two-layer strap plan. No PDK/vendor identity is asserted anywhere."""

    tapcell_master = "TIEFILL"
    metal_prefix = "MET"
    cell_lef = None
    tech_lef = None
    pdn_straps = {
        "stripes": [{"layer": "MET4", "width": 1.12, "pitch": 22.4,
                     "offset": 5.6},
                    {"layer": "MET5", "width": 1.76, "pitch": 24.4,
                     "offset": 6.1}],
        "connects": [["MET1", "MET4"], ["MET4", "MET5"]],
    }


def _pdn(secondary=None, monkey=None):
    pdk = _Pdk()
    # `_discover_pg_from_lef` is the only file read on this path; stub it so the
    # test stays pure-emission and PDK-independent.
    orig = R._discover_pg_from_lef
    R._discover_pg_from_lef = lambda *a, **k: ("VDD", "VSS", "MET1", 0.8)
    orig_wb = R._discover_well_bias_pins_from_lef
    R._discover_well_bias_pins_from_lef = lambda *a, **k: ([], [])
    try:
        return R._build_pdn_tcl(pdk, secondary=secondary)
    finally:
        R._discover_pg_from_lef = orig
        R._discover_well_bias_pins_from_lef = orig_wb


_SEC = [{"master": "OTPMACRO", "pin": "VPP", "rail": "PROG_V",
         "use": "POWER"}]


# ---------------------------------------------------------------- A. PDN ---

def test_no_secondary_supply_emits_the_identical_pdn():
    # Regression safety: every existing single-supply design must keep a
    # byte-identical PDN. `None` and `[]` are the same thing.
    assert _pdn(None) == _pdn([])
    tcl = _pdn(None)
    assert "-secondary_power" not in tcl
    assert "define_pdn_grid -macro" not in tcl
    assert "SECONDARY_PDN" not in tcl


def test_secondary_rail_is_registered_on_the_voltage_domain():
    tcl = _pdn(_SEC)
    assert '-secondary_power "PROG_V"' in tcl
    vd = next(l for l in tcl.splitlines() if "set_voltage_domain" in l)
    assert "-power VDD" in vd and "-ground VSS" in vd


def test_secondary_binding_precedes_pdngen():
    # THE defect. Before the fix the binding for this pin was emitted in a
    # different block, AFTER the PDN block had already run `pdngen` — so the
    # rail was born with no grid to be generated on.
    tcl = _pdn(_SEC)
    gc = tcl.index("add_global_connection -net PROG_V")
    assert gc < _stmt(tcl, "global_connect")
    assert _stmt(tcl, "global_connect") < tcl.index("set_voltage_domain")
    assert tcl.index("set_voltage_domain") < tcl.index("define_pdn_grid -macro")
    assert tcl.index("define_pdn_grid -macro") < _stmt(tcl, "pdngen")


def test_pdn_is_built_after_the_macro_supply_plan():
    """The defect in its original form was pure ORDER, at the call site: the
    PDN block was built BEFORE the macro-supply plan existed, so it could not
    have been told about a secondary rail even in principle. Emission-order
    tests inside the block cannot see that; this one can."""
    src = Path(R.__file__).read_text()
    plan = src.index("_hm_connect, _hm_unconn = _macro_supply_gc_plan(")
    build = src.index("pdn_block = _build_pdn_tcl(")
    assert plan < build, (
        "pdn_block is built before the macro-supply plan; a secondary rail "
        "can never reach pdngen")
    assert "secondary=" in src[build:build + 200]


def test_secondary_strap_offset_is_computed_from_the_placed_pin():
    # The strap must be aligned to the terminal by MEASUREMENT, not by a tuned
    # constant: a hard-coded offset is a one-design fix wearing a general coat.
    tcl = _pdn(_SEC)
    strap = next(l for l in tcl.splitlines()
                 if "-number_of_straps 1" in l and "-nets" in l)
    assert "-offset [lindex $_sp_s 3]" in strap
    assert "-allow_out_of_core" in strap
    assert "getBBox" in tcl and "ord::dbu_to_microns" in tcl
    # ...and the axis comes from the layer's own LEF direction, not an
    # assumption about which metal runs which way.
    assert "getDirection" in tcl
    assert "getRoutingLevel" in tcl
    # nothing about the strap geometry is a literal number
    assert not re.search(r"-number_of_straps 1 [^\n]*-offset [0-9]", tcl)


def test_unreachable_secondary_pin_is_reported_not_fabricated():
    tcl = _pdn(_SEC)
    assert tcl.count("SECONDARY_PDN_UNREACHED") >= 3
    for why in ("has no terminal",
                "no routing-layer metal",
                "NO layer above it"):
        assert why in tcl
    assert "not fabricated" in tcl


def test_core_rail_pins_are_not_treated_as_secondary():
    # negative control: a macro pin that binds to a CORE rail must not create a
    # second voltage-domain rail or a macro grid.
    tcl = _pdn([{"master": "OTPMACRO", "pin": "VDD", "rail": "VDD",
                 "use": "POWER"},
                {"master": "OTPMACRO", "pin": "VSS", "rail": "VSS",
                 "use": "GROUND"}])
    assert "-secondary_power" not in tcl
    assert "define_pdn_grid -macro" not in tcl


def test_no_strap_plan_means_no_fabricated_secondary_grid():
    # A PDK with nothing to strap with cannot reach a secondary rail; the fix
    # must not invent a layer for it.
    assert R._build_secondary_supply_pdn_tcl(_SEC, [], []) == ""
    assert R._build_secondary_supply_pdn_tcl([], [{"layer": "MET4",
                                                   "width": 1, "pitch": 2}],
                                             []) == ""


def test_secondary_pdn_carries_no_pdk_or_vendor_literal():
    tcl = _pdn(_SEC).lower()
    for banned in ("sky130", "gf180", "nangate", "asap7", "otp_v", "0.18",
                   "180nm"):
        assert banned not in tcl
    # every design-specific token in the block came from the caller
    assert "otpmacro" in tcl and "prog_v" in tcl and "vpp" in tcl


# ------------------------------------------------------- B. SIZING LIMITS ---

def _lib(name, cells):
    """Minimal liberty text: ``cells`` is [(cell, area, leakage), ...]."""
    out = [f'library ({name}) {{']
    for cell, area, leak in cells:
        out.append(f"""  cell ("{cell}") {{
    area : {area};
    cell_leakage_power : {leak};
    pin (A) {{ direction : input; capacitance : 0.01; }}
    pin (Z) {{ direction : output; function : "A";
      timing () {{ related_pin : "A"; cell_rise (t) {{ values("1,2"); }} }}
    }}
  }}""")
    out.append("}")
    return "\n".join(out)


_NARROW = _lib("narrow", [("BUFX1", 10.0, 1.0), ("BUFX2", 20.0, 2.0),
                          ("BUFX4", 35.0, 3.5)])            # 3.5X / 3.5X
_WIDE = _lib("wide", [("BUFX1", 10.0, 1.0), ("BUFX8", 80.0, 40.0)])  # 8X / 40X
_WIDER = _lib("wider", [("BUFX1", 10.0, 1.0), ("BUFX16", 160.0, 90.0)])


def test_buffer_family_is_inferred_structurally():
    fam = {c for c, _, _ in R._liberty_buffer_family(_NARROW)}
    assert fam == {"BUFX1", "BUFX2", "BUFX4"}


def test_inverters_and_logic_gates_are_not_counted_as_buffers():
    # an inverter (function "!A") and a 2-input gate must not enter the span,
    # or the measured ratio would be the whole library's, not the family's.
    txt = _lib("mix", [("BUFX1", 10.0, 1.0)]) + """
library (extra) {
  cell ("INVX1") {
    area : 5.0; cell_leakage_power : 0.5;
    pin (A) { direction : input; }
    pin (Z) { direction : output; function : "!A"; }
  }
  cell ("NAND2X1") {
    area : 7.0; cell_leakage_power : 0.7;
    pin (A) { direction : input; }
    pin (B) { direction : input; }
    pin (Z) { direction : output; function : "!(A B)"; }
  }
}"""
    assert {c for c, _, _ in R._liberty_buffer_family(txt)} == {"BUFX1"}


def test_library_within_openroad_default_limits_is_left_alone():
    # A library whose family fits inside 4X needs nothing; emitting anything
    # here would change optimisation for a design that never had the problem.
    assert R._sizing_limits_preamble_tcl([_NARROW]) == ""
    assert R._sizing_limits_preamble_tcl([]) == ""
    assert R._sizing_limits_drv_report_tcl([_NARROW]) == ""


def _limits(tcl):
    m = re.search(r"-limit_sizing_area ([\d.]+) -limit_sizing_leakage "
                  r"([\d.]+)", tcl)
    return (float(m.group(1)), float(m.group(2)))


def _expect(span, margin=1.1):
    """The limit is the measured span x margin, rounded UP to 2dp — rounding
    DOWN could land back under the span it was measured from."""
    return math.ceil(span * margin * 100.0) / 100.0


def test_limits_are_measured_from_the_library_not_a_constant():
    # THE defect-present test. A blanket relaxation — any fixed pair of
    # numbers — passes "the violation disappeared" and fails THIS: two
    # libraries with different spans must produce different limits, each
    # traceable to its own measured span.
    a = _limits(R._sizing_limits_preamble_tcl([_WIDE]))
    b = _limits(R._sizing_limits_preamble_tcl([_WIDER]))
    assert a != b
    assert a[0] == _expect(8.0)      # 80/10 area span, x1.1 margin
    assert a[1] == _expect(40.0)     # 40/1  leakage span
    assert b[0] == _expect(16.0)
    assert b[1] == _expect(90.0)
    # and never below the span it was measured from
    assert a[0] >= 8.0 and a[1] >= 40.0
    assert b[0] >= 16.0 and b[1] >= 90.0


def test_span_is_the_widest_across_every_signoff_corner():
    # leakage span is corner-dependent; the limit has to cover the worst one,
    # or the escalation helps at tt and still aborts at the ss sign-off corner.
    both = _limits(R._sizing_limits_preamble_tcl([_WIDE, _WIDER]))
    assert both == _limits(R._sizing_limits_preamble_tcl([_WIDER]))


def test_only_the_cell_pool_is_widened_never_the_slew_target():
    # The one thing that must never happen: the fix must not touch
    # max_transition / max_capacitance. It restores the swap pool; the timing
    # constraint is left exactly as the liberty and the SDC declare it.
    tcl = R._sizing_limits_preamble_tcl([_WIDE])
    assert "set_opt_config" in tcl
    assert "set_max_transition" not in tcl
    assert "set_max_capacitance" not in tcl
    assert "set_max_fanout" not in tcl
    assert "SIZING_LIMITS_APPLIED" in tcl
    # a failure to apply is surfaced, never swallowed
    assert "SIZING_LIMITS_NONFATAL" in tcl


def _pnr(**kw):
    base = dict(
        tech_lef_c="/x/tech.lef", cell_lef_c="/x/cell.lef",
        macro_lefs_tcl="", liberty_c="/x/c.lib", macro_libs_tcl="",
        netlist_c="/x/d.v", top="d", sdc_c="/x/d.sdc", dont_use_block="",
        metal_prefix="met", die_w=100, die_h=100, core_pad=10,
        core_w=90, core_h=90, site="unit", out_dir_c="/out",
        tapcell_block="", pdn_block="", util=0.3,
        spare_protection_tcl="", spare_postfix_tcl="",
        clk_buf="BUF", clk_buf_root="BUF", routing_constraint_tcl="",
        pg_cleanup_block="", spef_repair_block="",
        antenna_repair_block="", filler_block="")
    base.update(kw)
    return R._build_pnr_tcl_text(**base)


def test_sizing_limits_precede_the_first_timing_driven_step():
    """THE defect-present test for the placement of this fix.

    RSZ-0090 is raised by PreChecks::checkSlewLimit, which is reached from
    `global_placement -timing_driven` (gpl/nesterovPlace.cpp:460 ->
    timingBase.cpp:128 findResizeSlacks -> RepairDesign -> checkSlewLimit) —
    NOT only from the explicit `repair_design` further down. It is a
    logger_->error, so it ABORTS the script. A sizing-limit block emitted after
    `repair_design` therefore never executes: measured on a real run, the abort
    was at the `global_placement` line while the block sat 262 lines below it.

    So the invariant is positional: set_opt_config must precede
    `global_placement`, and `global_placement` must precede `repair_design`
    (asserted too, so this test cannot silently pass by the template being
    reordered underneath it).
    """
    tcl = _pnr(sizing_limits_block=R._sizing_limits_preamble_tcl([_WIDE]),
               sizing_drv_report_block=R._sizing_limits_drv_report_tcl([_WIDE]))
    cfg = tcl.index("set_opt_config")
    gp = _stmt_prefix(tcl, "global_placement")
    rd = tcl.index("{repair_design}")
    assert cfg < gp, (
        "set_opt_config is emitted after global_placement; RSZ-0090 aborts "
        "there, so the restored pool would never be seen")
    assert gp < rd          # the template really does place gp first
    # the DRV evidence, by contrast, belongs AFTER repair_design
    assert rd < tcl.index("SIZING_LIMITS_DRV_AFTER_REPAIR")


def test_drv_report_is_evidence_only_and_changes_nothing():
    # The post-repair block exists to show what the restored pool bought. If it
    # ever starts acting (another repair_design, another set_opt_config) the
    # before/after number stops being an independent measurement.
    rep = R._sizing_limits_drv_report_tcl([_WIDE])
    assert "sta::max_slew_violation_count" in rep
    assert "sta::max_capacitance_violation_count" in rep
    assert "set_opt_config" not in rep
    # no EXECUTABLE optimisation command — the word may appear in the comment
    # and in the printed message, which is prose, not an action.
    for line in rep.splitlines():
        s = line.strip()
        if s.startswith("#") or s.startswith("puts "):
            continue
        assert "repair_design" not in s, f"report block acts: {s!r}"
        assert "repair_timing" not in s, f"report block acts: {s!r}"
    assert "SIZING_LIMITS_DRV_UNMEASURED" in rep   # counters absent != 0


def test_sizing_escalation_is_absent_when_not_supplied():
    tcl = _pnr()
    assert "SIZING_LIMITS" not in tcl
    assert "set_opt_config" not in tcl
