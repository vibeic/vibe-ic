"""mig104 — steps 34 (fill) and 35 (DFM) on LibreLane, and what the direct
path owed first.

MEASURED on spm x gf180mcuD, vibeic-eda 0.3.79, run23's own inputs (the
routed `spm.def`, the chip path's legalized tech LEF and IO LEFs):

  * the direct step-34 producer (`_emit_metal_fill`) wrote a filled.def with
    274,148 of 304,990 supply pins on NO net -- `filler_placement` created the
    decaps/fillers in a session that never had the PDN's global-connect rules
    (F24's defect, at the fill). With the deck's rules registered after
    `read_def` and applied before `write_def`: 0 of 304,990, and COMPONENTS,
    NETS and SPECIALNETS identical to LibreLane `OpenROAD.FillInsertion`'s.
  * the step-35 DFM screen said PASS_WITH_ADVISORIES (100 % single-cut vias,
    0 errors) and the phase-3 front door turned its advisory rc 1 into a step
    FAIL (T77, spm final14).
  * the tool's GDS fill (the PDK's `fill_all.rb` through `KLayout.Filler`)
    leaves `M2.4` (Metal2 coverage over the die < 30 %) = 1 where the direct
    lattice engine leaves 0; the deck is the same `KLayout.Density` on both.

chip-AGNOSTIC: fixture nets/cells are the calibration pair's or synthetic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import dfm_screen_check as DFM  # noqa: E402
import librelane_contract as LLC  # noqa: E402
import librelane_fill_dfm as LF  # noqa: E402
import metal_fill_density_check as MFD  # noqa: E402
import _default_backend_fixtures as BF  # noqa: E402
from _ppa import pareto as P  # noqa: E402
from _ppa.backends import openroad as ORB  # noqa: E402
from test_ppa_feasibility import candidate, metric  # noqa: E402

CAL = PROGRAMS / "calibration"
CAL_LEF = CAL / "pg_supply_buf_1.lef"
CAL_POS = CAL / "pg_supply_unowned_positive.def"   # supply pins on no net
CAL_NEG = CAL / "pg_supply_owned_negative.def"     # every supply pin owned

DECK = """\
if {[catch {
  add_global_connection -net VDD -pin_pattern "^VDD$" -power
  add_global_connection -net VSS -pin_pattern "^VSS$" -ground
  global_connect
} err]} { puts "PDN_FAILED: $err" }
"""


@pytest.fixture(autouse=True)
def legacy_arm_transport(monkeypatch):
    # This module's multi-arm controls replace native process transport.
    # They do not supply a Default single-stream checkpoint or LOCAL proof.
    import execution_policy
    from _stated_eda_image import mock_docker_route
    original_request = execution_policy.request
    monkeypatch.setattr(execution_policy, 'request',
                        lambda: dict(original_request(), mode='ultra'))
    mock_docker_route(monkeypatch)


def _pnr(project: Path) -> Path:
    d = project / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _switch(project: Path, **steps) -> None:
    p = project / "phase3" / "librelane_switch.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"steps": {'37': 'direct', **steps}}))


# ── T77: an advisory DFM screen is not a step FAIL ─────────────────────────

_SINGLE_CUT_DEF = """\
VERSION 5.8 ;
DESIGN top ;
VIAS 1 ;
    - V1 + ROWCOL 1 1 ;
END VIAS
NETS 1 ;
    - n0 ( u0 A ) ( u1 Z ) + USE SIGNAL
      + ROUTED M1 ( 0 0 ) ( 100 * ) V1
      NEW M2 ( 100 0 ) ( * 100 ) ;
END NETS
"""








# ── the direct step-34 producer connects what it inserts (F24 at the fill) ──











# ── librelane_fill_dfm: the readers ────────────────────────────────────────

def _def(components, rows="ROW R0 core 0 0 N DO 10 BY 1 STEP 100 0 ;\n"):
    body = "".join(f"    - {i} {m} + PLACED ( 0 0 ) N ;\n" for i, m in components)
    return (f"VERSION 5.8 ;\nDESIGN t ;\nUNITS DISTANCE MICRONS 1000 ;\n{rows}"
            f"COMPONENTS {len(components)} ;\n{body}END COMPONENTS\nEND DESIGN\n")


PATTERNS = {"decap": ["lib__fillcap_*"], "fill": ["lib__fill_*"]}


def test_the_census_counts_what_the_step_added_by_class():
    before = _def([("u0", "lib__buf_1")])
    after = _def([("u0", "lib__buf_1"), ("F0", "lib__fillcap_4"),
                  ("F1", "lib__fillcap_4"), ("F2", "lib__fill_1")])
    c = LF.fill_census(before, after, PATTERNS)
    assert c["added"] == 3 and c["removed"] == 0
    assert c["per_class"] == {"decap": 2, "fill": 1, "other": 0}
    assert c["per_master"] == {"lib__fill_1": 1, "lib__fillcap_4": 2}


def test_a_master_both_families_match_is_a_decap_as_fill_tcl_orders_them():
    """`fill.tcl` hands DECAP_CELLS to `filler_placement` before FILL_CELLS, so
    a fill wildcard broad enough to match the decaps must not reclassify them
    (F20b would then see no decap at all)."""
    broad = {"decap": ["lib__fillcap_*"], "fill": ["lib__fill*"]}
    c = LF.fill_census(_def([]), _def([("F0", "lib__fillcap_4"), ("F1", "lib__fill_1")]),
                       broad)
    assert c["class_of_master"] == {"lib__fill_1": "fill", "lib__fillcap_4": "decap"}


def test_the_census_names_a_non_fill_edit():
    c = LF.fill_census(_def([("u0", "lib__buf_1")]), _def([("x", "lib__inv_1")]),
                       PATTERNS)
    assert c["removed"] == 1 and c["per_class"]["other"] == 1


_LEF = """\
SITE core
  SIZE 0.1 BY 1.0 ;
END core
MACRO lib__buf_1
  CLASS CORE ;
  SIZE 0.2 BY 1.0 ;
END lib__buf_1
MACRO lib__fill_1
  CLASS CORE SPACER ;
  SIZE 0.1 BY 1.0 ;
END lib__fill_1
MACRO lib__pad
  CLASS PAD ;
  SIZE 50 BY 50 ;
END lib__pad
"""


def test_row_occupancy_counts_core_class_area_over_row_sites():
    occ = LF.row_occupancy(_def([("u0", "lib__buf_1"), ("f", "lib__fill_1"),
                                 ("p", "lib__pad")]), [_LEF])
    assert occ["status"] == "MEASURED"
    assert occ["row_area_um2"] == pytest.approx(1.0)
    assert occ["row_utilization_pct"] == pytest.approx(30.0)


def test_a_lowercase_class_keyword_is_still_core():
    """MEASURED: the gf180 cell LEF spells every standard cell `CLASS core ;`;
    read case-sensitively, spm's 82,037-instance filled DEF measured 0 %."""
    occ = LF.row_occupancy(_def([("u0", "lib__buf_1")]),
                           [_LEF.replace("CLASS CORE ;", "CLASS core ;")])
    assert occ["row_utilization_pct"] == pytest.approx(20.0)


def test_the_not_prose_claim_for_the_lef_reader_is_falsifiable():
    """`_NOT_PROSE["librelane_fill_dfm::lef_geometry"]`: a master the LEF gives
    no SIZE is never given one; the occupancy is NOT_MEASURED, not a number."""
    lef = _LEF.replace("  SIZE 0.2 BY 1.0 ;\nEND lib__buf_1", "END lib__buf_1")
    occ = LF.row_occupancy(_def([("u0", "lib__buf_1")]), [lef])
    assert occ["status"] == "NOT_MEASURED"
    assert occ["unknown_masters"] == {"lib__buf_1": 1}
    assert occ["row_utilization_pct"] is None
    assert LF.row_occupancy(_def([("u0", "lib__buf_1")]),
                            [_LEF.replace("SITE core", "SITE other").replace(
                                "END core", "END other")])["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("router,verdict", [
    ({"singlecut": 90, "multicut": 10}, "AGREE"),
    ({"singlecut": 80, "multicut": 20}, "DISAGREE"),
    ({"singlecut": 90, "multicut": 11}, "SCOPE_DIFFERS"),
    (None, "NOT_MEASURED"),
])
def test_the_def_recount_is_checked_against_the_routers_own_counts(router, verdict):
    assert LF.via_agreement(90, 100, router)["verdict"] == verdict


def test_router_counts_are_read_in_both_dialects():
    assert LF.router_via_counts({"route__vias__singlecut": 3,
                                 "route__vias__multicut": 1})["key_prefix"] == "route__vias"
    got = LF.router_via_counts({"detailedroute__route__vias__singlecut": 5,
                                "detailedroute__route__vias__multicut": 0})
    assert got["singlecut"] == 5 and got["multicut"] == 0
    assert LF.router_via_counts({"route__vias__singlecut": 3}) is None


@pytest.mark.parametrize("direct,tool,winner", [
    (0, 1, "direct"),      # spm: the PDK script leaves M2.4
    (1, 0, "librelane"),
    (0, 0, "direct"),      # a tie keeps what the flow has shipped
    (0, None, "direct"),   # an unmeasured arm is never the winner
])
def test_the_gds_fill_is_selected_by_the_same_deck(tmp_path, direct, tool, winner):
    arm = lambda n: None if n is None else {LF.DENSITY_METRIC: n}  # noqa: E731
    sel = LF.select_gds_fill(tmp_path, arm(direct), arm(tool))
    assert (sel["winner"] or "direct") == winner, sel


def test_the_two_halves_share_one_record(tmp_path):
    LF.update_record(tmp_path, "gds", {"shipped": "direct"})
    LF.update_record(tmp_path, "odb", {"shipped": "librelane"})
    doc = json.loads((tmp_path / LF.RECORD_REL).read_text())
    assert doc["gds"] == {"shipped": "direct"} and doc["odb"]["shipped"] == "librelane"


def test_the_placed_cells_record_is_what_f20b_reads():
    rec = {"step": LF.ODB_FILL_STEP, "filled_def": "/x/f.def", "filled_def_sha256": "a",
           "subject_sha256": "b", "patterns": PATTERNS,
           "census": {"per_class": {"decap": 2, "fill": 1, "other": 0},
                      "per_master": {"lib__fillcap_4": 2, "lib__fill_1": 1},
                      "class_of_master": {"lib__fillcap_4": "decap", "lib__fill_1": "fill"}}}
    out = LF.cells_placed_record(rec)
    assert out["def_sha256"] == "a" and out["per_class"]["decap"] == 2
    assert out["class_of_master"]["lib__fillcap_4"] == "decap"


def test_the_stream_finishing_steps_read_the_stream_alone():
    for step in ("KLayout.Filler", "KLayout.Density"):
        LLC._check_state({"gds": __file__}, step_id=step)
    LLC._check_state({}, step_id="Checker.KLayoutDensity")
    with pytest.raises(LLC.Refusal):
        LLC._check_state({}, step_id="KLayout.Filler")


# ── the step-34 switch in the runner ───────────────────────────────────────























# ── step 34's gate and step 35's screen read the tool ──────────────────────

def _record(project, odb=None, gds=None):
    doc = {"step": "34"}
    if odb is not None:
        if odb.get('shipped') == 'librelane':
            tool = BF.fill_record(project, subject=_pnr(project) / 'routed.def')
            BF.consume_fill(project, tool)
            odb = dict(odb, tool=tool)
        doc["odb"] = odb
    if gds is not None:
        shipped = gds.get('shipped')
        if isinstance(gds.get(shipped), dict):
            old = gds[shipped]
            current = BF.density_record(project, project / 'phase3/stage4/gds/top.gds',
                                         old.get(LF.DENSITY_METRIC))
            gds = dict(gds, **{shipped: dict(old, **current)})
        doc["gds"] = gds
    p = project / LF.RECORD_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))
    return doc


def _gate_project(tmp_path, mode="librelane"):
    project = tmp_path / "g"
    (_pnr(project) / "routed.def").write_text(CAL_NEG.read_text())
    stream = project / 'phase3/stage4/gds/top.gds'
    stream.parent.mkdir(parents=True)
    stream.write_bytes(b'SOURCE_FIXTURE_ONLY current stream')
    _switch(project, **{"34": mode})
    return project, LLC.digest(project / "phase3/stage3/pnr/routed.def")


def test_the_gate_is_silent_on_the_direct_switch(tmp_path):
    project, _ = _gate_project(tmp_path, "direct")
    _record(project, odb={"shipped": None})
    assert MFD.tool_arm_findings(project)[0] == []


def test_the_gate_refuses_a_tool_path_that_left_no_evidence(tmp_path):
    project, _ = _gate_project(tmp_path)
    cats = {f.category for f in MFD.tool_arm_findings(project)[0]}
    assert cats == {"LL_FILL_RECORD_ABSENT"}


@pytest.mark.parametrize("count,expect", [(0, set()), (1, {"DENSITY_DECK_FAIL"}),
                                          (None, {"LL_DENSITY_NOT_MEASURED"})])
def test_the_gate_judges_the_shipped_fill_by_the_pdk_deck(tmp_path, count, expect):
    project, sha = _gate_project(tmp_path)
    _record(project, odb={"def_sha256": sha, "shipped": "librelane"},
            gds={"shipped": "librelane", "librelane": {LF.DENSITY_METRIC: count}})
    findings, stats = MFD.tool_arm_findings(project)
    assert {f.category for f in findings} == expect
    assert stats["density_errors"] == count


def test_the_gate_refuses_a_record_about_another_route(tmp_path):
    project, _ = _gate_project(tmp_path)
    _record(project, odb={"def_sha256": "other", "shipped": "librelane"},
            gds={"shipped": "librelane", "librelane": {LF.DENSITY_METRIC: 0}})
    assert {f.category for f in MFD.tool_arm_findings(project)[0]} == {
        "LL_FILL_RECORD_STALE"}


def _step37(project, arm="klayout", count=0):
    root = project / "phase3/librelane"
    canonical = project / 'phase3/stage4/gds/top.gds'
    measured = BF.density_record(project, canonical, count,
        lane=f'37-{arm}-finish/03-klayout-density', config_folder='37-config')
    state = Path(measured['state'])
    (root / "37-promotion.json").write_text(json.dumps({
        'selection': arm, 'canonical': str(canonical), 'source': str(canonical),
        'finished': {arm: str(canonical)}, 'canonical_sha256': LLC.digest(canonical),
        'source_sha256': LLC.digest(canonical)}))
    (root / f"37-{arm}-density.json").write_text(json.dumps({
        "verdict": "PASS" if count == 0 else "FAIL", "source": str(state),
        "sha256": {"state_out.json": LLC.digest(state)},
        "metrics": {LF.DENSITY_METRIC: {"status": "MEASURED" if count == 0 else "FAIL",
                                        "value": count}}}))
    return state


def test_on_a_tool_stream_the_gds_half_is_step_37s_chain(tmp_path):
    project, sha = _gate_project(tmp_path)
    _switch(project, **{"34": "librelane", "37": "librelane"})
    _record(project, odb={"def_sha256": sha, "shipped": "librelane"})
    state = _step37(project, count=0)
    findings, stats = MFD.tool_arm_findings(project)
    assert findings == [] and stats["density_errors"] == 0
    ref = DFM.audit(project)["density_ref"]
    assert ref["status"] == "MEASURED" and ref["errors"] == 0
    state.write_text('{"moved": 1}')
    assert {f.category for f in MFD.tool_arm_findings(project)[0]} >= {"LL_FILL_RECORD_STALE"}
    _step37(project, count=2)
    assert {f.category for f in MFD.tool_arm_findings(project)[0]} == {"DENSITY_DECK_FAIL"}


def test_the_dfm_screen_reads_cmp_density_from_the_tool(tmp_path):
    project, sha = _gate_project(tmp_path)
    state = project / "st.json"
    state.write_text("{}")
    recorded = _record(project, gds={"shipped": "librelane", "librelane": {
        LF.DENSITY_METRIC: 1, "rules": {"M2.4": 1}, "state": str(state),
        "state_sha256": LLC.digest(state)}})
    state = Path(recorded['gds']['librelane']['state'])
    ref = DFM.audit(project)["density_ref"]
    assert ref["tool"].startswith("KLayout.Density")
    assert ref["errors"] == 1 and ref["step34_pass"] is False
    state.write_text('{"moved": 1}')
    assert DFM.audit(project)["density_ref"]["status"] == "STALE"


def test_the_dfm_screen_keeps_the_side_file_on_the_direct_switch(tmp_path):
    project, _ = _gate_project(tmp_path, "direct")
    _record(project, gds={"shipped": "librelane", "librelane": {LF.DENSITY_METRIC: 1}})
    gate = project / "reports/phase2/gates/metal_fill_density.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps({"summary": {"pass": True, "errors_count": 0}}))
    ref = DFM.audit(project)["density_ref"]
    assert ref["step34_pass"] is True and "tool" not in ref


def test_the_dfm_screen_cross_checks_the_routers_via_counts(tmp_path):
    project = tmp_path / "v"
    pnr = _pnr(project)
    (pnr / "routed.def").write_text(_SINGLE_CUT_DEF)
    (pnr / "openroad.metrics.json").write_text(json.dumps({
        "detailedroute__route__vias__singlecut": 1,
        "detailedroute__route__vias__multicut": 0}))
    agree = DFM.audit(project)["via_redundancy"]["router_agreement"]
    assert agree["verdict"] == "AGREE", agree
    (pnr / "openroad.metrics.json").write_text(json.dumps({
        "detailedroute__route__vias__singlecut": 0,
        "detailedroute__route__vias__multicut": 1}))
    rep = DFM.audit(project)
    assert rep["via_redundancy"]["router_agreement"]["verdict"] == "DISAGREE"
    assert "VIA_COUNT_DISAGREES" in {f["category"] for f in rep["findings"]}


# ── PPA: the single-cut fraction, and the yield objective ─────────────────

def test_the_openroad_backend_publishes_the_single_cut_fraction(tmp_path):
    p = tmp_path / "openroad.metrics.json"
    p.write_text(json.dumps({"detailedroute__route__vias": 10,
                             "detailedroute__route__vias__singlecut": 8,
                             "detailedroute__route__vias__multicut": 2}))
    recs = {r["metric"]: r for r in ORB.parse_metrics_json(p).records}
    frac = recs["route.via.singlecut.fraction"]
    assert frac["status"] == "DERIVED" and frac["value"] == pytest.approx(0.8)
    assert "singlecut" in frac["formula"]
    assert recs["route.via.multicut.count"]["status"] == "MEASURED"
    p.write_text(json.dumps({"detailedroute__route__vias__singlecut": 0,
                             "detailedroute__route__vias__multicut": 0}))
    recs = {r["metric"]: r for r in ORB.parse_metrics_json(p).records}
    assert recs["route.via.singlecut.fraction"]["status"] == "NOT_MEASURED"


_AREA = P.Objective("area", "area.total_um2", P.SENSE_MIN, {"stage": "s"})


def _cand(cid, area, multicut):
    ms = [metric("area.total_um2", area, "um2", {"stage": "s"})]
    if multicut is not None:
        ms.append(metric("route.via.multicut.count", multicut, "1",
                         {"stage": "detailed_route"}))
    return candidate(cid, ms)


def test_at_equal_ppa_the_layout_with_more_redundant_vias_is_preferred():
    cands = [_cand("a", 10.0, 0), _cand("b", 10.0, 40), _cand("c", 9.0, 0)]
    out = P.prefer_on_yield(cands, ["a", "b", "c"], (_AREA,))
    assert sorted(out["preferred"]) == ["b", "c"]
    assert P.VIA_YIELD_OBJECTIVE not in P.DEFAULT_OBJECTIVES


def test_an_unmeasured_yield_is_neither_preferred_nor_dropped():
    cands = [_cand("a", 10.0, None), _cand("b", 10.0, 40)]
    out = P.prefer_on_yield(cands, ["a", "b"], (_AREA,))
    assert sorted(out["preferred"]) == ["a", "b"]
    assert out["decisions"][0]["reason"] == "YIELD_NOT_COMPARABLE"
