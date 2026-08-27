"""#766 — the post-route repair analysed a DIFFERENT DESIGN, with DIFFERENT
parasitics, than the one whose number fired it.

Measured on `subservient` x `gf180mcuD` (Vibe-IC benchmark matrix, r8):

    trigger (sta_mcorner_ocv.rpt, shipped post-route design + extracted SPEF
             + propagated clock + flat-OCV derate)   setup WNS -0.09 / TNS -0.13
    repair     (postroute_timing_repair.log, post_hold.def + estimate_parasitics)
                                       [INFO RSZ-0098] No setup violations found

and a deck pointed at `pnr/routed_repaired.def` + `extracted/spef_corners/
<top>.max.spef` with `read_spef -corner ss` closed the SAME design with ONE
buffer and one pin swap (-0.09 -> +0.14 ns, TNS -0.13 -> 0.00, +0.0% area).

Every test here RUNS the emitter / audit and reads its real output; none of
them assert on this file's own source text.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3  # noqa: E402
import postroute_timing_repair_audit  # noqa: E402


TOP = "subservient"
CORNER_LIBS = {"SS": "/pdk/ss.lib", "TT": "/pdk/tt.lib", "FF": "/pdk/ff.lib"}


# ---------------------------------------------------------------------------
# helpers — a project tree in the shape the flow leaves after a shipped route
# ---------------------------------------------------------------------------

def _project(tmp_path, *, post_route=True):
    proj = tmp_path / "proj"
    pnr = proj / "phase3/stage3/pnr"
    ext = proj / "phase3/stage3/extracted/spef_corners"
    for d in (pnr, ext, proj / "phase3/stage3/sta", proj / "phase3/stage3/postroute_timing_repair"):
        d.mkdir(parents=True, exist_ok=True)
    files = ["post_hold.def", "constraint.sdc"]
    if post_route:
        # what `step_signoff_spef_repair` leaves behind once it PROMOTES the
        # repaired route: routed.def / <top>.def / <top>_pnr.v all carry it.
        files += ["routed.def", f"{TOP}.def", f"{TOP}_pnr.v",
                  "routed_repaired.def", f"{TOP}_pnr_repaired.v"]
    for f in files:
        (pnr / f).write_text("# stub\n")
    if post_route:
        for c in ("min", "nom", "max"):
            (ext / f"{TOP}.{c}.spef").write_text("*SPEF stub\n")
    return proj


def _trigger_deck(monkeypatch, proj):
    """RUN the emitter that produces the number which FIRES the repair and return
    the Tcl it actually wrote."""
    sta = proj / "phase3/stage3/sta"
    ext = proj / "phase3/stage3/extracted/spef_corners"
    monkeypatch.setattr(p3, "_docker_exec", lambda *a, **k: (0, "", ""))
    monkeypatch.setattr(p3, "_to_container_path", lambda p, c: str(p))

    class _Pdk:
        tech_lef = "/pdk/t.lef"
        cell_lef = "/pdk/c.lef"
        liberty = "/pdk/tt.lib"
        macro_libs: list = []
        macro_lefs: list = []
        metal_prefix = "Metal"

    p3._emit_mcorner_ocv_sta(
        proj, TOP, _Pdk(), "cx", CORNER_LIBS,
        {c: ext / f"{TOP}.{c}.spef" for c in ("min", "nom", "max")},
        None, sta / "sta_mcorner_ocv.rpt", [])
    return (sta / "sta_mcorner_ocv_setup.tcl").read_text()


def _repair_deck(proj, **kw):
    pnr = proj / "phase3/stage3/pnr"
    start, basis = p3._repair_start_point(pnr, TOP)
    ext = proj / "phase3/stage3/extracted/spef_corners"
    spefs = {c: str(ext / f"{TOP}.{c}.spef")
             for c in ("min", "nom", "max")
             if (ext / f"{TOP}.{c}.spef").is_file()}
    post_route = basis.startswith("post_route")
    args = dict(
        corner_libs=CORNER_LIBS,
        start_def_c=str(start) if start else None,
        post_route_start=post_route,
        corner_spefs_c=spefs if post_route else {},
        captables_c=({"max": "/pdk/rules.max.magic",
                      "min": "/pdk/rules.min.magic"} if post_route else {}),
        filler_masters=["FILL_1"],
    )
    args.update(kw)
    return p3._build_postroute_timing_repair_tcl(
        TOP, "/pdk/t.lef", "/pdk/c.lef", "/pdk/tt.lib",
        str(pnr), str(proj / "phase3/stage3/postroute_timing_repair"), "Metal", **args)


def _first_cmd(tcl, *prefixes):
    for ln in tcl.splitlines():
        s = ln.strip()
        if s.startswith(prefixes):
            return s
    return ""


def _cmd_lines(tcl):
    return [ln.strip() for ln in tcl.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def _cmd_index(tcl, token):
    for n, s in enumerate(_cmd_lines(tcl)):
        if token in s:
            return n
    return None


# ---------------------------------------------------------------------------
# (a) the repair must repair the design the trigger number was measured on
# ---------------------------------------------------------------------------

def test_postroute_timing_repairs_the_same_design_the_trigger_number_was_measured_on(
        tmp_path, monkeypatch):
    """The trigger deck times `<top>_pnr.v` — the SHIPPED post-route netlist
    `step_signoff_spef_repair` promoted. The repair deck used to read
    `post_hold.def`, the last PRE-route DEF: 9656 instances against the shipped
    9701, three of them a different MASTER."""
    proj = _project(tmp_path)
    trig = _trigger_deck(monkeypatch, proj)
    repair = _repair_deck(proj)

    trig_design = _first_cmd(trig, "read_verilog ")
    repair_input_def_cmd = _first_cmd(repair, "read_def ")
    assert trig_design, "the trigger deck must read a design"
    assert repair_input_def_cmd, "the repair deck must read a design"
    # the two must name the SAME implementation: the shipped post-route one.
    assert Path(trig_design.split()[-1]).name == f"{TOP}_pnr.v", trig_design
    assert Path(repair_input_def_cmd.split()[-1]).name in (f"{TOP}.def", "routed.def"), (
        f"the repair reads {repair_input_def_cmd!r} — the trigger measured "
        f"{trig_design!r}; a repair of a different netlist answers about a "
        "different design (#766 a)")
    assert "post_hold.def" not in repair_input_def_cmd


def test_repair_start_point_precedence_prefers_the_shipped_post_route_def(tmp_path):
    proj = _project(tmp_path)
    pnr = proj / "phase3/stage3/pnr"
    assert p3._repair_start_point(pnr, TOP) == (pnr / f"{TOP}.def",
                                             "post_route_shipped")
    (pnr / f"{TOP}.def").unlink()
    assert p3._repair_start_point(pnr, TOP) == (pnr / "routed.def", "post_route")
    (pnr / "routed.def").unlink()
    # honest PRE-ROUTE fallback: a run that never completed a route
    assert p3._repair_start_point(pnr, TOP) == (pnr / "post_hold.def",
                                             "pre_route_post_hold")
    (pnr / "post_hold.def").unlink()
    assert p3._repair_start_point(pnr, TOP) == (None, "none")


# ---------------------------------------------------------------------------
# (b) the repair must analyse the parasitics the violation exists under
# ---------------------------------------------------------------------------

def test_repair_annotates_the_extracted_spef_the_trigger_was_measured_with(
        tmp_path, monkeypatch):
    """`estimate_parasitics -placement` -> RSZ-0098 No setup violations found;
    the extracted SPEF at `-corner ss` -> RSZ-0094 Found 2 endpoints. The
    parasitics SOURCE is the dominant term and the CORNER SCOPING is
    load-bearing (plain read_spef read +0.04 where -corner ss read -0.09)."""
    proj = _project(tmp_path)
    trig = _trigger_deck(monkeypatch, proj)
    repair = _repair_deck(proj)
    ext = proj / "phase3/stage3/extracted/spef_corners"

    assert f"read_spef {ext}/{TOP}.max.spef" in trig, (
        "precondition: the trigger deck annotates the extracted max-RC SPEF")
    # setup @ ss <-> max-RC, hold @ ff <-> min-RC, tt <-> nom — the SAME
    # pairing the sign-off measurement uses.
    assert f"read_spef -corner ss {ext}/{TOP}.max.spef" in repair, repair
    assert f"read_spef -corner ff {ext}/{TOP}.min.spef" in repair
    assert f"read_spef -corner tt {ext}/{TOP}.nom.spef" in repair


def test_repair_does_not_overwrite_the_annotated_spef_with_an_estimate(tmp_path):
    """`estimate_parasitics -placement` after `read_spef` re-creates exactly the
    blindness this closes."""
    repair = _repair_deck(_project(tmp_path))
    cmds = _cmd_lines(repair)   # comment-blind: only what the tool executes
    assert any("read_spef" in c for c in cmds)
    assert not any("estimate_parasitics -placement" in c for c in cmds), (
        "a placement estimate would overwrite the real annotated parasitics")
    assert any("estimate_parasitics -detailed_routing" in c for c in cmds), (
        "the resizer must be pinned to the annotated detailed-route parasitics")


def test_repair_keeps_the_timing_view_the_trigger_measured_with(tmp_path,
                                                             monkeypatch):
    proj = _project(tmp_path)
    trig = _trigger_deck(monkeypatch, proj)
    repair = _repair_deck(proj)
    for cmd in ("set_propagated_clock [all_clocks]",
                f"set_timing_derate -early {p3._FLAT_OCV_DERATE_EARLY}",
                f"set_timing_derate -late {p3._FLAT_OCV_DERATE_LATE}"):
        assert cmd in trig, f"precondition: trigger deck carries {cmd!r}"
        assert cmd in repair, f"the repair must analyse with {cmd!r} too"


def test_post_route_start_removes_fillers_and_clears_routing_in_the_right_order(
        tmp_path):
    """A fill-tiled post-route DEF leaves the resizer no legal site, and
    removing instances AFTER annotation invalidates the parasitics (EST-0104);
    a post-route DEF's committed routing makes `global_route` regenerate 0
    guides (DRT-0626) and can abort the reroute on one of OpenROAD's own wires
    (DRT-1010 non-orthogonal, measured on this design)."""
    repair = _repair_deck(_project(tmp_path))
    i_rm = _cmd_index(repair, "remove_fillers")
    i_spef = _cmd_index(repair, "read_spef")
    i_repair = _cmd_index(repair, "repair_design")
    i_clear = _cmd_index(repair, "odb::dbWire_destroy")
    i_gr = _cmd_index(repair, "global_route")
    i_dr = _cmd_index(repair, "detailed_route")
    assert None not in (i_rm, i_spef, i_repair, i_clear, i_gr, i_dr)
    assert i_rm < i_spef < i_repair, "remove_fillers -> annotate -> repair"
    assert i_repair < i_clear < i_gr < i_dr, "clear routing before global_route"
    assert "POSTROUTE_TIMING_REPAIR_ROUTING_CLEARED" in repair


def test_pre_route_fallback_is_unchanged(tmp_path):
    """A run with no completed route has nothing shipped to repair — the honest
    fallback is the pre-route DEF, and it must emit exactly what it did before
    (no SPEF, no filler removal, no routing clear)."""
    proj = _project(tmp_path, post_route=False)
    repair = _repair_deck(proj)
    assert _first_cmd(repair, "read_def ").endswith("post_hold.def")
    assert "read_spef" not in repair
    assert "remove_fillers" not in repair
    assert "odb::dbWire_destroy" not in repair
    assert "estimate_parasitics -placement" in repair


@pytest.mark.skipif(shutil.which("tclsh") is None, reason="tclsh not installed")
@pytest.mark.parametrize("post_route", [True, False])
def test_the_emitted_deck_parses_and_evaluates_in_a_real_tclsh(tmp_path,
                                                               post_route):
    """A deck the tool cannot parse repairs nothing at all. `proc unknown`
    stubs every OpenROAD command so this exercises the TCL structure, not the
    tool."""
    proj = _project(tmp_path, post_route=post_route)
    script = tmp_path / "repair.tcl"
    script.write_text('proc unknown {args} { return "" }\n'
                      + _repair_deck(proj)
                      + '\nputs "REPAIR_TCL_END"\n')
    res = subprocess.run(["tclsh", str(script)], capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    assert "REPAIR_TCL_END" in res.stdout


# ---------------------------------------------------------------------------
# (c) the post-repair "after" must be measured on the repair's OWN parasitics
# ---------------------------------------------------------------------------

def test_repair_reextracts_its_own_parasitics_after_the_reroute(tmp_path):
    repair = _repair_deck(_project(tmp_path))
    i_dr = _cmd_index(repair, "detailed_route")
    i_x = _cmd_index(repair, "extract_parasitics -ext_model_file")
    assert i_x is not None and i_dr < i_x, (
        "the repair must re-extract AFTER its own reroute")
    assert "write_spef " in repair
    assert f"spef_corners/{TOP}.max.spef" in repair
    assert f"spef_corners/{TOP}.min.spef" in repair


def test_postrepair_measurement_prefers_the_repairs_own_reextracted_parasitics(
        tmp_path, monkeypatch):
    """`_measure_postrepair_mcorner_ocv` handed the repair NETLIST to the OCV emitter
    while rediscovering the SPEFs from the BASE route's extraction — the report
    said so in its own banner (`SPEF=<top>.max.spef` beside `<top>_timing_repaired.v`)."""
    proj = _project(tmp_path)
    postroute_timing_repair_dir = proj / "phase3/stage3/postroute_timing_repair"
    (postroute_timing_repair_dir / f"{TOP}_timing_repaired.v").write_text("// repair netlist\n")
    (postroute_timing_repair_dir / "postroute_timing_repair.log").write_text("[INFO RSZ-0040] Inserted 1 buffers.\n")
    repair_spefs = postroute_timing_repair_dir / "spef_corners"
    repair_spefs.mkdir(parents=True, exist_ok=True)
    for c in ("min", "nom", "max"):
        (repair_spefs / f"{TOP}.{c}.spef").write_text("*SPEF repair\n")

    seen = {}

    def _fake_emit(project, top, pdk, container, corner_libs, corner_spefs,
                   nom_spef, rpt_out, notes, netlist_override=None):
        seen["spefs"] = {k: str(v) for k, v in corner_spefs.items()}
        seen["netlist"] = str(netlist_override)
        Path(rpt_out).parent.mkdir(parents=True, exist_ok=True)
        Path(rpt_out).write_text(
            "=== SETUP corner: process=SS liberty=/pdk/ss.lib, "
            f"SPEF={TOP}.max.spef ===\nworst slack max 0.14\n")
        return True

    monkeypatch.setattr(p3, "_emit_mcorner_ocv_sta", _fake_emit)
    out = p3._measure_postrepair_mcorner_ocv(
        proj, TOP, object(), "cx", CORNER_LIBS,
        proj / "phase3/stage3/extracted/spef_corners",
        None, proj / "phase3/stage3/sta", [])
    assert out["parasitics_source"] == "repair_reextracted", out
    for p in seen["spefs"].values():
        assert "/postroute_timing_repair/spef_corners/" in p, (
            f"the after was measured on {p} — the BASE route's parasitics do "
            "not describe the repair's own route (#766 c)")


def test_postrepair_falls_back_to_base_parasitics_and_says_so(tmp_path,
                                                           monkeypatch):
    """When the repair reroute aborted, its re-extraction does not describe a
    complete route — the fallback is disclosed, never silently used."""
    proj = _project(tmp_path)
    postroute_timing_repair_dir = proj / "phase3/stage3/postroute_timing_repair"
    (postroute_timing_repair_dir / f"{TOP}_timing_repaired.v").write_text("// repair netlist\n")
    (postroute_timing_repair_dir / "postroute_timing_repair.log").write_text(
        "POSTROUTE_TIMING_REPAIR_DETAILED_ROUTE_NONFATAL: DRT-1010 Unsupported non-orthogonal wire\n")
    repair_spefs = postroute_timing_repair_dir / "spef_corners"
    repair_spefs.mkdir(parents=True, exist_ok=True)
    (repair_spefs / f"{TOP}.max.spef").write_text("*SPEF repair\n")
    monkeypatch.setattr(
        p3, "_emit_mcorner_ocv_sta",
        lambda *a, **k: Path(a[7]).write_text(
            "=== SETUP corner: process=SS ===\nworst slack max -0.09\n"))
    notes = []
    out = p3._measure_postrepair_mcorner_ocv(
        proj, TOP, object(), "cx", CORNER_LIBS,
        proj / "phase3/stage3/extracted/spef_corners",
        None, proj / "phase3/stage3/sta", notes)
    assert out["parasitics_source"] == "base_route_spef_reroute_failed"
    assert any("like-for-like" in n for n in notes), notes


# ---------------------------------------------------------------------------
# the silent-no-op guard
# ---------------------------------------------------------------------------

_BLIND_LOG = """\
[INFO RSZ-0058] Using max wire length 1500um.
[INFO RSZ-0098] No setup violations found
[INFO RSZ-0098] No setup violations found
"""

_SEEING_LOG = """\
[INFO RSZ-0094] Found 2 endpoints with setup violations.
[INFO RSZ-0099] Repairing 2 out of 2 (100.00%) violating endpoints...
[INFO RSZ-0040] Inserted 1 buffers.
[INFO RSZ-0043] Swapped pins on 1 instances.
"""


def test_no_setup_violations_found_on_a_violating_design_is_a_contradiction():
    v = p3._postroute_timing_repair_log_verdict(_BLIND_LOG, -0.09)
    assert v["blind_to_violation"] is True
    assert v["saw_no_setup_violations"] is True
    assert v["saw_setup_violations"] is False


def test_a_repair_that_saw_the_violation_is_not_blind():
    v = p3._postroute_timing_repair_log_verdict(_SEEING_LOG, -0.09)
    assert v["blind_to_violation"] is False
    assert v["setup_endpoints_found"] == 2


@pytest.mark.parametrize("log,wns", [("", -0.09), (_BLIND_LOG, None),
                                     (_BLIND_LOG, 0.14)])
def test_absence_is_not_the_finding(log, wns):
    """Unmeasured is not "blind": this reports a CONTRADICTION between two
    measured things, and nothing else."""
    assert p3._postroute_timing_repair_log_verdict(log, wns)["blind_to_violation"] is False


def _repair_project(tmp_path, log_payload):
    proj = tmp_path / "auditproj"
    repair = proj / "phase3/stage3/postroute_timing_repair"
    repair.mkdir(parents=True, exist_ok=True)
    (repair / "postroute_timing_repair_decision.json").write_text(json.dumps(
        {"repair_needed": True, "action": "timing_repair_ran"}))
    (repair / "repair_log.json").write_text(json.dumps(log_payload))
    return proj


_BASE_LOG_JSON = {
    "verdict": "REPAIR_APPLIED",
    "changes": [{"type": "multi_corner_repair_timing"}],
    "re_verified": True,
    "affected_steps": [21, 23],
    "repair_before": {"setup_worst_slack_ns": -0.09},
    "repair_after": {"setup_worst_slack_ns": -0.09},
}


def test_audit_fails_loudly_when_the_repair_could_not_see_the_violation(tmp_path):
    payload = dict(_BASE_LOG_JSON)
    payload["postroute_timing_repair_log"] = p3._postroute_timing_repair_log_verdict(_BLIND_LOG, -0.09)
    payload["repair_blind_to_violation"] = True
    findings, stats = postroute_timing_repair_audit.audit(_repair_project(tmp_path, payload))
    cats = [f.category for f in findings if f.severity == "ERROR"]
    assert "REPAIR_BLIND_TO_VIOLATION" in cats, [
        (f.severity, f.category) for f in findings]
    report = postroute_timing_repair_audit.build_report(findings, stats, "x")
    assert report["summary"]["pass"] is False


def test_audit_passes_a_repair_that_saw_and_fixed_the_violation(tmp_path):
    payload = dict(_BASE_LOG_JSON)
    payload["repair_after"] = {"setup_worst_slack_ns": 0.14}
    payload["repair_setup_delta_ns"] = 0.23
    payload["repair_delta_comparable"] = True
    payload["postroute_timing_repair_log"] = p3._postroute_timing_repair_log_verdict(_SEEING_LOG, -0.09)
    payload["repair_blind_to_violation"] = False
    findings, stats = postroute_timing_repair_audit.audit(_repair_project(tmp_path, payload))
    assert [f for f in findings if f.severity == "ERROR"] == []


def test_a_delta_between_two_different_implementations_is_not_a_regression(
        tmp_path):
    """The r8 record: `repair_setup_delta_ns = -8.220` on a run whose
    `repair_timing -setup` made ZERO changes — it subtracted a number measured
    on the shipped design from one measured on a different netlist with the
    base route's parasitics."""
    payload = dict(_BASE_LOG_JSON)
    payload["repair_after"] = {"setup_worst_slack_ns": -8.31}
    payload["repair_setup_delta_ns"] = -8.22
    payload["repair_delta_comparable"] = False
    payload["repair_delta_comparable_reason"] = (
        "repair start point was 'pre_route_post_hold' and the after was measured "
        "on 'base_route_spef' parasitics")
    payload["postroute_timing_repair_log"] = p3._postroute_timing_repair_log_verdict(_SEEING_LOG, -0.09)
    findings, _ = postroute_timing_repair_audit.audit(_repair_project(tmp_path, payload))
    cats = {f.category: f.severity for f in findings}
    assert cats.get("REPAIR_DELTA_NOT_COMPARABLE") == "WARNING", cats
    assert "REPAIR_REGRESSED" not in cats


def test_an_aborted_repair_reroute_is_visible_in_the_audit(tmp_path):
    """The fix the repair pass made is only real once it is routed. DRT-1010 on this
    design aborted the reroute; that must not be invisible."""
    payload = dict(_BASE_LOG_JSON)
    payload["postroute_timing_repair_log"] = p3._postroute_timing_repair_log_verdict(
        _SEEING_LOG + "POSTROUTE_TIMING_REPAIR_DETAILED_ROUTE_NONFATAL: DRT-1010\n", -0.09)
    assert payload["postroute_timing_repair_log"]["reroute_failed"] is True
    findings, _ = postroute_timing_repair_audit.audit(_repair_project(tmp_path, payload))
    cats = {f.category: f.severity for f in findings}
    assert cats.get("REPAIR_REROUTE_INCOMPLETE") == "WARNING", cats


def test_a_real_regression_on_a_comparable_delta_still_errors(tmp_path):
    """The #766 comparability rule must not become a way to silence the
    regression guard: a delta the runner itself called comparable still fails."""
    payload = dict(_BASE_LOG_JSON)
    payload["repair_after"] = {"setup_worst_slack_ns": -8.31}
    payload["repair_setup_delta_ns"] = -8.22
    payload["repair_delta_comparable"] = True
    findings, _ = postroute_timing_repair_audit.audit(_repair_project(tmp_path, payload))
    assert "REPAIR_REGRESSED" in [f.category for f in findings
                               if f.severity == "ERROR"]


def test_a_record_without_the_comparability_field_behaves_exactly_as_before(
        tmp_path):
    """Backward compatibility: a repair_log.json from before #766 carries no
    `repair_delta_comparable`, and a negative delta there must still be ERROR."""
    payload = dict(_BASE_LOG_JSON)
    payload["repair_after"] = {"setup_worst_slack_ns": -8.31}
    payload["repair_setup_delta_ns"] = -8.22
    findings, _ = postroute_timing_repair_audit.audit(_repair_project(tmp_path, payload))
    assert "REPAIR_REGRESSED" in [f.category for f in findings
                               if f.severity == "ERROR"]
