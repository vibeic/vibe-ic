"""Small-core PDN pitch and built-metal controls on a neutral logic tile."""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import floorplan_pdn_check as gate






def _project(tmp_path: Path, n_shapes: int, *, mode="apply") -> Path:
    project = tmp_path / "logic_tile"
    pnr = project / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    stripes = ""
    for net, x0 in (("VDD", 10000), ("VSS", 15000)):
        shapes = "\n".join(
            f"      NEW M5 1000 + SHAPE STRIPE ( {x0 + i*10000} 1000 ) "
            f"( {x0 + i*10000} 99000 )" for i in range(n_shapes // 2))
        role = "POWER" if net == "VDD" else "GROUND"
        stripes += f"    - {net} ( c1 {net} )\n{shapes}\n      + USE {role} ;\n"
    (pnr / "floorplan.def").write_text(
        "VERSION 5.8 ;\nDESIGN logic_tile ;\n"
        "UNITS DISTANCE MICRONS 1000 ;\n"
        "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n"
        "ROW R0 SITE 1000 1000 N DO 10 BY 1 STEP 1000 0 ;\n"
        "COMPONENTS 1 ;\n - c1 NAND2 ;\nEND COMPONENTS\n"
        f"SPECIALNETS 2 ;\n{stripes}END SPECIALNETS\nEND DESIGN\n")
    (pnr / "pnr.tcl").write_text(
        "define_pdn_grid -name grid\n"
        "add_pdn_stripe -grid grid -layer M5 -width 1 -pitch 38.4 -offset 2\n"
        "pdngen\n")
    report = project / "reports/phase3"
    report.mkdir(parents=True)
    (report / "floorplan_rectangles.json").write_text(json.dumps({
        "pdn_core_floor": {"budget_pitch": {
            "verdict": "CANDIDATE", "mode": mode,
            "rows": [{"layer": "M5", "required_groups": 3}]}}}))
    return project


def _check(project: Path):
    output = project / "gate.json"
    rc = gate.main([str(project), "--json", str(output)])
    report = json.loads(output.read_text())
    return rc, report








def test_tcl_intent_with_zero_built_straps_fails_when_applied(tmp_path):
    project = _project(tmp_path, 0)
    path = project / "phase3/stage3/pnr/floorplan.def"
    path.write_text(path.read_text().replace(
        "SPECIALNETS 2 ;", "SPECIALNETS 2 ;\n# not SHAPE STRIPE"))
    rc, report = _check(project)
    assert rc == 1
    assert report["verdict"] == "FAIL"
    assert "PDN_DEF_STRAP_SHORTFALL" in {x["rule"] for x in report["findings"]}
    assert report["def_stripe_census"]["count"] == 0


def test_built_three_group_grid_passes_and_reverse_mutation_fails(tmp_path):
    project = _project(tmp_path, 6)
    rc, report = _check(project)
    assert rc == 0
    assert report["verdict"] == "PASS"
    assert report["def_stripe_census"]["count"] == 6
    # Remove actual metal while leaving the apparently correct Tcl untouched.
    body = (project / "phase3/stage3/pnr/floorplan.def").read_text()
    (project / "phase3/stage3/pnr/floorplan.def").write_text(
        body.replace("SHAPE STRIPE", "SHAPE FOLLOWPIN"))
    assert _check(project)[0] == 1


def test_declared_power_roles_count_with_arbitrary_net_names(tmp_path):
    project = _project(tmp_path, 6)
    path = project / "phase3/stage3/pnr/floorplan.def"
    body = path.read_text().replace("- VDD ( c1 VDD )", "- SUPPLY_A ( c1 SUPPLY_A )")
    body = body.replace("- VSS ( c1 VSS )", "- RETURN_A ( c1 RETURN_A )")
    path.write_text(body)
    rc, report = _check(project)
    assert rc == 0 and report["verdict"] == "PASS"
    census = report["def_stripe_census"]
    assert census["count"] == 6
    assert census["by_role_layer"] == {"POWER": {"m5": 3},
                                       "GROUND": {"m5": 3}}


def test_multiline_special_wire_shape_counts_by_role_and_layer(tmp_path):
    project = _project(tmp_path, 6)
    path = project / "phase3/stage3/pnr/floorplan.def"
    path.write_text(path.read_text().replace(
        "NEW M5 1000 + SHAPE STRIPE",
        "NEW M5 1000\n      + SHAPE STRIPE"))
    rc, report = _check(project)
    assert rc == 0 and report["verdict"] == "PASS"
    assert report["def_stripe_census"]["by_role_layer"] == {
        "POWER": {"m5": 3}, "GROUND": {"m5": 3}}


def test_apply_policy_rejects_unresolved_pitch_budget(tmp_path):
    project = _project(tmp_path, 2)
    policy = project / "input/pdn_budget_pitch_policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_text('{"mode":"apply"}')
    report_path = project / "reports/phase3/floorplan_rectangles.json"
    reason = "M5: IR sheet resistance/budget absent"
    report_path.write_text(json.dumps({"pdn_core_floor": {"budget_pitch": {
        "mode": "apply", "verdict": "NOT_MEASURED", "reason": reason}}}))
    rc, report = _check(project)
    assert rc == 2 and report["verdict"] == "NOT_MEASURED"
    finding = next(f for f in report["findings"]
                   if f["rule"] == "PDN_BUDGET_PITCH_UNRESOLVED")
    assert reason in finding["message"]


def test_apply_policy_rejects_infeasible_or_incomplete_candidate(tmp_path):
    project = _project(tmp_path, 2)
    policy = project / "input/pdn_budget_pitch_policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_text('{"mode":"apply"}')
    report_path = project / "reports/phase3/floorplan_rectangles.json"
    report_path.write_text(json.dumps({"pdn_core_floor": {"budget_pitch": {
        "mode": "apply", "verdict": "INFEASIBLE",
        "reason": "M5: no legal pitch"}}}))
    rc, report = _check(project)
    assert rc == 1 and report["verdict"] == "FAIL"
    assert "M5: no legal pitch" in next(f["message"] for f in report["findings"]
                                    if f["rule"] == "PDN_BUDGET_PITCH_UNRESOLVED")
    report_path.write_text(json.dumps({"pdn_core_floor": {"budget_pitch": {
        "mode": "apply", "verdict": "CANDIDATE", "rows": []}}}))
    rc, report = _check(project)
    assert rc == 2 and report["verdict"] == "NOT_MEASURED"
    assert "PDN_BUDGET_PITCH_UNRESOLVED" in {f["rule"] for f in report["findings"]}


def test_signal_stripes_without_budget_cannot_certify_pdn(tmp_path):
    project = _project(tmp_path, 2)
    path = project / "phase3/stage3/pnr/floorplan.def"
    path.write_text(path.read_text().replace("+ USE POWER", "+ USE SIGNAL")
                    .replace("+ USE GROUND", "+ USE SIGNAL"))
    (project / "reports/phase3/floorplan_rectangles.json").write_text("{}")
    rc, report = _check(project)
    assert rc == 2 and report["verdict"] == "NOT_MEASURED"
    assert report["def_stripe_census"]["count"] == 0
    assert "PDN_DEF_STRAP_ROLE_NOT_PG" in {f["rule"] for f in report["findings"]}


def test_no_budget_still_requires_both_supply_roles(tmp_path):
    project = _project(tmp_path, 6)
    path = project / "phase3/stage3/pnr/floorplan.def"
    path.write_text(path.read_text().replace("+ USE GROUND", "+ USE POWER"))
    (project / "reports/phase3/floorplan_rectangles.json").write_text("{}")
    rc, report = _check(project)
    assert rc == 2 and report["verdict"] == "NOT_MEASURED"
    assert report["def_stripe_census"]["by_role_layer"]["GROUND"] == {}
    assert "PDN_DEF_STRAP_SHORTFALL" in {f["rule"] for f in report["findings"]}


def test_no_budget_zero_stripes_on_declared_supply_pair_is_not_measured(tmp_path):
    project = _project(tmp_path, 0)
    (project / "reports/phase3/floorplan_rectangles.json").write_text("{}")
    rc, report = _check(project)
    assert rc == 2 and report["verdict"] == "NOT_MEASURED"
    assert report["def_stripe_census"]["count"] == 0
    assert "PDN_DEF_STRAP_SHORTFALL" in {f["rule"] for f in report["findings"]}


def test_no_budget_zero_stripes_on_one_declared_supply_is_not_clean(tmp_path):
    project = _project(tmp_path, 0)
    path = project / "phase3/stage3/pnr/floorplan.def"
    path.write_text(path.read_text().replace("+ USE GROUND", "+ USE SIGNAL"))
    (project / "reports/phase3/floorplan_rectangles.json").write_text("{}")
    rc, report = _check(project)
    census = report["def_stripe_census"]
    assert census["status"] == "MEASURED"
    assert census["count"] == 0
    assert census["declared_roles"] == ["POWER"]
    assert "PDN_DEF_STRAP_SHORTFALL" in {f["rule"] for f in report["findings"]}
    assert rc == 2 and report["verdict"] == "NOT_MEASURED"


def test_six_stripes_on_one_rail_do_not_count_as_three_groups(tmp_path):
    project = _project(tmp_path, 6)
    path = project / "phase3/stage3/pnr/floorplan.def"
    body = path.read_text()
    body = body.replace("- VSS ( c1 VSS )", "- VDD2 ( c1 VDD )")
    body = body.replace("+ USE GROUND ;", "+ USE POWER ;")
    path.write_text(body)
    rc, report = _check(project)
    assert rc == 1
    assert report["def_stripe_census"]["count"] == 6
    assert "PDN_DEF_STRAP_SHORTFALL" in {x["rule"] for x in report["findings"]}


def test_advisory_mode_discloses_existing_zero_strap_cell(tmp_path):
    # Both rails declared, zero metal: the budget's per-layer shortfall stays
    # advisory, but a declared rail with no stripe is never a clean grid.
    rc, report = _check(_project(tmp_path, 0, mode="advisory"))
    assert rc == 2 and report["verdict"] == "NOT_MEASURED"
    finding = next(x for x in report["findings"]
                   if x["rule"] == "PDN_DEF_STRAP_SHORTFALL")
    assert finding["severity"] == "ADVISORY"


def test_advisory_candidate_single_declared_rail_without_metal_is_not_clean(tmp_path):
    project = _project(tmp_path, 0, mode="advisory")
    path = project / "phase3/stage3/pnr/floorplan.def"
    path.write_text(path.read_text().replace("+ USE GROUND", "+ USE SIGNAL"))
    rc, report = _check(project)
    assert report["def_stripe_census"]["declared_roles"] == ["POWER"]
    assert report["def_stripe_census"]["count"] == 0
    assert rc == 2 and report["verdict"] == "NOT_MEASURED"


def test_advisory_candidate_group_shortfall_on_built_rails_stays_advisory(tmp_path):
    # One built wire per rail, three groups planned: disclosed, not blocking.
    rc, report = _check(_project(tmp_path, 2, mode="advisory"))
    assert rc == 0 and report["verdict"] == "PASS"
    finding = next(x for x in report["findings"]
                   if x["rule"] == "PDN_DEF_STRAP_SHORTFALL")
    assert finding["severity"] == "ADVISORY"


# ---------------------------------------------------------------------------
# The census reads BUILT WIRES in the DEF that carries the built grid.
# ---------------------------------------------------------------------------
def _stripe_vias(project: Path, per_rail: int = 5) -> None:
    """Add OpenROAD's stripe-crossing via paths: one point, a via name, and
    (as written) width 0 -- plus the same with a nonzero width, and a width-0
    two-point path. None of them is a strap wire."""
    path = project / "phase3/stage3/pnr/floorplan.def"
    body = path.read_text()
    for role in ("POWER", "GROUND"):
        vias = "".join(
            f"      NEW M5 0 + SHAPE STRIPE ( {20000 + i * 1000} 50000 ) via4_5_1000_1000\n"
            f"      NEW M4 0 + SHAPE STRIPE ( {20000 + i * 1000} 60000 ) via4_5_1000_1000\n"
            for i in range(per_rail))
        vias += ("      NEW M5 1000 + SHAPE STRIPE ( 30000 70000 ) via4_5_1000_1000\n"
                 "      NEW M5 0 + SHAPE STRIPE ( 30000 1000 ) ( 30000 99000 )\n")
        body = body.replace(f"      + USE {role} ;", f"{vias}      + USE {role} ;")
    path.write_text(body)


def test_stripe_crossing_vias_are_not_counted_as_straps(tmp_path):
    project = _project(tmp_path, 6)
    _stripe_vias(project)
    rc, report = _check(project)
    census = report["def_stripe_census"]
    assert census["by_role_layer"] == {"POWER": {"m5": 3}, "GROUND": {"m5": 3}}
    assert census["count"] == 6
    assert census["stripe_vias_not_counted"] == 2 * (2 * 5 + 2)
    assert rc == 0 and report["verdict"] == "PASS"


def test_vias_cannot_fill_an_apply_mode_group_shortfall(tmp_path):
    # One real wire per rail and five crossing vias on the stripe layer: only
    # one of the three planned groups is built.
    project = _project(tmp_path, 2)
    _stripe_vias(project)
    rc, report = _check(project)
    assert report["def_stripe_census"]["by_role_layer"] == {
        "POWER": {"m5": 1}, "GROUND": {"m5": 1}}
    assert rc == 1 and report["verdict"] == "FAIL"
    assert "PDN_DEF_STRAP_SHORTFALL" in {x["rule"] for x in report["findings"]}


_DIRECT_DECK = """\
# pdngen
read_verilog /work/netlist.v
link_design logic_tile
initialize_floorplan -die_area {0 0 100 100} -site SITE
write_def /work/phase3/stage3/pnr/floorplan.def
tapcell -distance 14
if {[catch {
  define_pdn_grid -name grid
  add_pdn_stripe -grid grid -layer M5 -width 1 -pitch 38.4 -offset 2
  pdngen
} _pdn_err]} {
  puts "PDN_NONFATAL: $_pdn_err"
}
# write_def /work/phase3/stage3/pnr/cts.def
global_placement -density 0.5
write_def /work/phase3/stage3/pnr/placed.def
write_def /work/phase3/stage3/pnr/routed.def
"""


def test_direct_deck_census_reads_the_def_written_after_pdngen(tmp_path):
    # The direct deck writes floorplan.def BEFORE tapcell/pdngen: it holds no
    # stripe. The grid pdngen built is first on disk in placed.def.
    built = _project(tmp_path / "built", 6)
    project = _project(tmp_path, 0)
    pnr = project / "phase3/stage3/pnr"
    (pnr / "placed.def").write_text(
        (built / "phase3/stage3/pnr/floorplan.def").read_text())
    (pnr / "pnr.tcl").write_text(_DIRECT_DECK)
    rc, report = _check(project)
    census = report["def_stripe_census"]
    assert Path(census["source"]).name == "placed.def"
    assert census["by_role_layer"] == {"POWER": {"m5": 3}, "GROUND": {"m5": 3}}
    assert rc == 0 and report["verdict"] == "PASS"
    # No DEF after pdngen on disk: the requirement on built metal is not
    # measured -- neither a pass nor a fail read off the pre-PDN floorplan.
    (pnr / "placed.def").unlink()
    rc, report = _check(project)
    finding = next(x for x in report["findings"]
                   if x["rule"] == "PDN_DEF_STRAPS_NOT_MEASURED")
    assert finding["severity"] == "NOT_MEASURED"
    assert rc == 2 and report["verdict"] == "NOT_MEASURED"


def test_deck_without_pdngen_census_reads_the_handed_over_floorplan(tmp_path):
    # LibreLane step 15: the consumer deck reads the tool's floorplan.def, which
    # already carries the grid; the deck itself runs no pdngen.
    project = _project(tmp_path, 6)
    empty = _project(tmp_path / "empty", 0)
    pnr = project / "phase3/stage3/pnr"
    (pnr / "placed.def").write_text(
        (empty / "phase3/stage3/pnr/floorplan.def").read_text())
    (pnr / "pnr.tcl").write_text(
        "read_def -floorplan_initialize /work/phase3/stage3/pnr/floorplan.def\n"
        "# step 15 (taps, supply connect, PDN): LibreLane state\n"
        "global_placement -density 0.5\n"
        "write_def /work/phase3/stage3/pnr/placed.def\n")
    rc, report = _check(project)
    assert Path(report["def_stripe_census"]["source"]).name == "floorplan.def"
    assert rc == 0 and report["verdict"] == "PASS"




# ---------------------------------------------------------------------------
# The budget override never loosens the EM remedy, and the record says so.
# ---------------------------------------------------------------------------
_NEUTRAL_CELL_LEF = """\
MACRO tile_cell
 CLASS core ;
 SIZE 2 BY 10 ;
 PIN VDD
  DIRECTION INOUT ;
  USE POWER ;
  PORT
   LAYER M1 ;
    RECT 0 9.6 2 10.4 ;
  END
 END VDD
 PIN VSS
  DIRECTION INOUT ;
  USE GROUND ;
  PORT
   LAYER M1 ;
    RECT 0 -0.4 2 0.4 ;
  END
 END VSS
END tile_cell
"""
