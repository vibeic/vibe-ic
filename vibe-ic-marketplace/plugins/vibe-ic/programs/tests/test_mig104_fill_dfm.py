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
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import dfm_screen_check as DFM  # noqa: E402
import librelane_contract as LLC  # noqa: E402
import librelane_fill_dfm as LF  # noqa: E402
import metal_fill_density_check as MFD  # noqa: E402
import pg_supply_pin_ownership_check as G  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402
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


def _pnr(project: Path) -> Path:
    d = project / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _switch(project: Path, **steps) -> None:
    p = project / "phase3" / "librelane_switch.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"steps": steps}))


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


def test_an_advisory_dfm_screen_is_a_pass_with_its_advisory_disclosed(tmp_path):
    (_pnr(tmp_path) / "routed.def").write_text(_SINGLE_CUT_DEF)
    row = R._run_declared_signoff_gate(tmp_path, "dfm_screen", "dfm_screen_check.py",
                                       "reports/phase3/dfm_screen.json")
    doc = json.loads((tmp_path / "reports/phase3/dfm_screen.json").read_text())
    assert doc["verdict"] == "PASS_WITH_ADVISORIES"
    assert doc["via_redundancy"]["single_cut_fraction"] == 1.0
    assert row.status == "PASS", row.detail
    assert row.extras.get("advisory_verdict") == "PASS_WITH_ADVISORIES"
    assert "advisory" in row.disclosures


def _fake_gate(tmp_path, monkeypatch, verdict):
    progs = tmp_path / "progs"
    progs.mkdir()
    body = ("import json,sys\n"
            "out=sys.argv[sys.argv.index('--json')+1]\n"
            + (f"open(out,'w').write(json.dumps({{'verdict': {verdict!r}}}))\n"
               if verdict else "")
            + "sys.exit(1)\n")
    (progs / "g.py").write_text(body)
    monkeypatch.setattr(R, "PROGRAMS_DIR", progs)
    proj = tmp_path / "p"
    proj.mkdir()
    return proj


@pytest.mark.parametrize("name,verdict", [
    ("dfm_screen", "FAIL"),                   # the document says FAIL
    ("dfm_screen", None),                     # no document at all
    ("erc_density", "PASS_WITH_ADVISORIES"),  # not an advisory-tier gate
])
def test_every_other_rc1_is_still_a_fail(tmp_path, monkeypatch, name, verdict):
    proj = _fake_gate(tmp_path, monkeypatch, verdict)
    row = R._run_declared_signoff_gate(proj, name, "g.py", "out.json")
    assert row.status == "FAIL", (name, verdict, row.detail)


# ── the direct step-34 producer connects what it inserts (F24 at the fill) ──

def _stage_fill(tmp_path, monkeypatch, tool_writes):
    """The runner's real `_emit_metal_fill`; the ONLY fake is the tool's own
    file write (`tool_writes(tcl_text) -> DEF text`)."""
    project = tmp_path / "proj"
    # This fixture substitutes the direct OpenROAD producer, not LibreLane.
    _switch(project, **{"34": "direct"})
    pnr = _pnr(project)
    (pnr / "top.def").write_text(CAL_NEG.read_text())
    (pnr / "routed.def").write_text(CAL_NEG.read_text())
    (pnr / "pnr.tcl").write_text(DECK)
    pdk = SimpleNamespace(name="calpdk", tech_lef=str(tmp_path / "t.lef"),
                          cell_lef=str(CAL_LEF), liberty=str(tmp_path / "c.lib"),
                          macro_lefs=[])
    monkeypatch.setattr(R, "_filler_masters_for_pdk", lambda p: ["FILLX"])
    monkeypatch.setattr(R, "_slot_geometry", lambda p: None)
    monkeypatch.setattr(R, "_def_reopen_extra_lefs_c", lambda *a, **k: [])
    seen = {}

    def _docker_exec(container, cmd, *a, outputs=None, **k):
        tcl = Path(cmd.split("-exit ")[1].split()[0]).read_text()
        seen["tcl"] = tcl
        Path(outputs[0]).write_text(tool_writes(tcl))
        return 0, "Placed 3 filler instances\nROW_UTILIZATION_PCT 100.0\n", ""
    monkeypatch.setattr(R, "_docker_exec", _docker_exec)
    return project, pnr, pdk, seen


def test_the_fill_session_registers_the_decks_rules_and_connects_before_writing(
        tmp_path, monkeypatch):
    project, pnr, pdk, seen = _stage_fill(tmp_path, monkeypatch,
                                          lambda tcl: CAL_NEG.read_text())
    R._emit_metal_fill(project, "top", pdk, "", pnr / "filled.def", [])
    tcl = seen["tcl"]
    rule = 'add_global_connection -net VDD -pin_pattern "^VDD$" -power'
    assert rule in tcl
    assert tcl.index("read_def ") < tcl.index(rule) < tcl.index("filler_placement")
    write = tcl.index("write_def ")
    apply_at = tcl.rindex("{global_connect}", 0, write)
    assert tcl.rindex("filler_placement", 0, write) < apply_at
    assert apply_at < tcl.index("METAL_FILL_PG_NO_NET: total=", apply_at) < write


def test_a_fill_that_leaves_a_supply_pin_off_its_net_is_refused(tmp_path, monkeypatch):
    project, pnr, pdk, _ = _stage_fill(tmp_path, monkeypatch,
                                       lambda tcl: CAL_POS.read_text())
    notes = []
    assert R._emit_metal_fill(project, "top", pdk, "", pnr / "filled.def", notes) is False
    assert not (pnr / "filled.def").exists()
    assert not (pnr / "metal_fill.done").exists()
    assert (pnr / "filled.pg_refused.def").read_text() == CAL_POS.read_text()
    rec = json.loads((project / "reports/phase3/postroute_pg_ownership_metal_fill.json")
                     .read_text())
    assert rec["verdict"] == "FAIL" and rec["code"] == G.REFUSE_CODE
    assert any(G.REFUSE_CODE in n for n in notes), notes


def test_a_fill_whose_supply_is_owned_stands(tmp_path, monkeypatch):
    project, pnr, pdk, _ = _stage_fill(tmp_path, monkeypatch,
                                       lambda tcl: CAL_NEG.read_text())
    notes = []
    assert R._emit_metal_fill(project, "top", pdk, "", pnr / "filled.def", notes)
    assert (pnr / "metal_fill.done").is_file()
    rec = json.loads((project / "reports/phase3/postroute_pg_ownership_metal_fill.json")
                     .read_text())
    assert rec["verdict"] == "PASS"
    assert any("supply ownership: PASS" in n for n in notes), notes


def test_the_direct_fill_records_the_cells_it_placed(tmp_path, monkeypatch):
    """F20b reads which cells step 34 placed; the production default writes it
    too. The two fixture masters are in no LEF given, so ownership is
    NOT_MEASURED -- published, never clean, and not a refusal."""
    project, pnr, pdk, _ = _stage_fill(
        tmp_path, monkeypatch, lambda tcl: CAL_NEG.read_text().replace(
            "COMPONENTS 1 ;\n",
            "COMPONENTS 3 ;\n    - F0 FILLX + PLACED ( 0 0 ) N ;\n"
            "    - F1 lib__fillcap_4 + PLACED ( 0 0 ) N ;\n"))
    monkeypatch.setattr(R, "_filler_masters_for_pdk", lambda p: ["lib__fillcap_4", "FILLX"])
    assert R._emit_metal_fill(project, "top", pdk, "", pnr / "filled.def", [])
    placed = json.loads((project / LF.CELLS_REL).read_text())
    assert placed["per_master"] == {"FILLX": 1, "lib__fillcap_4": 1}
    assert placed["class_of_master"] == {"FILLX": "fill", "lib__fillcap_4": "decap"}
    assert placed["def_sha256"] == LLC.digest(pnr / "filled.def")
    rec = json.loads((project / "reports/phase3/postroute_pg_ownership_metal_fill.json")
                     .read_text())
    assert rec["verdict"] == "NOT_MEASURED"


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

def _tool_folder(project: Path, def_text: str) -> Path:
    folder = project / "phase3/librelane/34/01-openroad-fillinsertion"
    folder.mkdir(parents=True)
    (folder / "chip_top.def").write_text(def_text)
    (folder / "openroad-fillinsertion.log").write_text("filler_placement\n")
    (folder / "state_out.json").write_text(json.dumps({"def": str(folder / "chip_top.def")}))
    return folder


def _tool_record(project: Path, refusals=()):
    folder = _tool_folder(project, CAL_NEG.read_text() + "\n# filled\n")
    return {"step": LF.ODB_FILL_STEP, "state": str(folder / "state_out.json"),
            "state_sha256": LLC.digest(folder / "state_out.json"),
            "filled_def": str(folder / "chip_top.def"), "filled_def_sha256": "x",
            "subject_sha256": "y", "patterns": PATTERNS,
            "census": {"added": 7, "removed": 0,
                       "per_class": {"decap": 5, "fill": 2, "other": 0},
                       "per_master": {}, "class_of_master": {}},
            "occupancy": {"after": {"row_utilization_pct": 100.0}},
            "supply_ownership": {"verdict": "PASS"}, "refusals": list(refusals)}


def _odb_stage(tmp_path, monkeypatch, mode, refusals=()):
    project = tmp_path / "proj"
    pnr = _pnr(project)
    (pnr / "top.def").write_text(CAL_NEG.read_text())
    (pnr / "routed.def").write_text(CAL_NEG.read_text())
    _switch(project, **{"34": mode})
    monkeypatch.setattr(R, "_librelane_step_ctx", lambda *a: ("img", tmp_path))
    monkeypatch.setattr(LF, "run_fill_insertion",
                        lambda *a, **k: _tool_record(project, refusals))
    return project, pnr


def test_on_librelane_the_tools_def_is_filled_def_and_its_reports_follow(
        tmp_path, monkeypatch):
    project, pnr = _odb_stage(tmp_path, monkeypatch, "librelane")
    monkeypatch.setattr(R, "_docker_exec", lambda *a, **k: pytest.fail("direct ran"))
    notes = []
    assert R._emit_metal_fill(project, "top", SimpleNamespace(name="p"), "",
                              pnr / "filled.def", notes)
    assert (pnr / "filled.def").read_text().endswith("# filled\n")
    density = json.loads((project / "reports/density.json").read_text())
    assert density["tool"] == "librelane:OpenROAD.FillInsertion"
    assert density["filler_instances"] == 7 and density["row_utilization_pct"] == 100.0
    assert "OpenROAD.FillInsertion" in (pnr / "metal_fill.done").read_text()
    rec = json.loads((project / LF.RECORD_REL).read_text())["odb"]
    assert rec["shipped"] == "librelane" and rec["mode"] == "librelane"
    assert json.loads((project / LF.CELLS_REL).read_text())["per_class"]["decap"] == 5


def test_on_librelane_a_tool_refusal_ships_nothing(tmp_path, monkeypatch):
    project, pnr = _odb_stage(tmp_path, monkeypatch, "librelane",
                              refusals=["LL_FILL_NO_OP: placed 0"])
    (pnr / "filled.def").write_text("stale\n")
    notes = []
    assert not R._emit_metal_fill(project, "top", SimpleNamespace(name="p"), "",
                                  pnr / "filled.def", notes)
    assert not (pnr / "filled.def").exists()
    assert any("LL_FILL_NO_OP" in n for n in notes)
    assert json.loads((project / LF.RECORD_REL).read_text())["odb"]["shipped"] is None


@pytest.mark.parametrize("direct_verdict,shipped", [("PASS", "direct"),
                                                    ("FAIL", "librelane")])
def test_dual_ships_the_feasible_arm_and_a_tie_keeps_direct(
        tmp_path, monkeypatch, direct_verdict, shipped):
    project, pnr = _odb_stage(tmp_path, monkeypatch, "dual")
    rpt = project / "reports/phase3"

    def _direct(project_, top, pdk, container, filled, notes, *, _direct_arm=False):
        assert _direct_arm
        rpt.mkdir(parents=True, exist_ok=True)
        (rpt / "postroute_pg_ownership_metal_fill.json").write_text(
            json.dumps({"verdict": direct_verdict}))
        if direct_verdict == "FAIL":
            return False
        filled.write_text("direct\n")
        return True
    real = R._emit_metal_fill
    monkeypatch.setattr(R, "_emit_metal_fill",
                        lambda *a, **k: (_direct(*a, **k) if k.get("_direct_arm")
                                         else real(*a, **k)))
    assert R._emit_metal_fill(project, "top", SimpleNamespace(name="p"), "",
                              pnr / "filled.def", [])
    rec = json.loads((project / LF.RECORD_REL).read_text())["odb"]
    assert rec["shipped"] == shipped, rec
    assert ((pnr / "filled.def").read_text() == "direct\n") == (shipped == "direct")


def test_the_direct_switch_leaves_the_gds_passes_to_the_caller(tmp_path):
    assert R._step34_gds_tool_arm(tmp_path, SimpleNamespace(name="p"),
                                  tmp_path / "x.gds") is None


def _gds_stage(tmp_path, monkeypatch, mode, counts):
    project = tmp_path / "proj"
    project.mkdir()
    _switch(project, **{"34": mode})
    gds = project / "top.gds"
    gds.write_bytes(b"sealed")
    monkeypatch.setattr(R, "_librelane_step_ctx", lambda *a: ("img", tmp_path))
    calls = []

    def _density(project_, image, root, pdk, *, gds, lane, steps=LF.DENSITY_STEPS, **k):
        calls.append(lane)
        state = tmp_path / f"{lane}.state.json"
        state.write_text("{}")
        out = {LF.DENSITY_METRIC: counts[lane], "state": str(state),
               "state_sha256": LLC.digest(state), "subject_sha256": "s"}
        if "KLayout.Filler" in steps:
            filled = tmp_path / "tool.gds"
            filled.write_bytes(Path(gds).read_bytes() + b"+pdkfill")
            out["filler"] = {"filled_gds": str(filled), "script": "fill.rb"}
            out["subject"] = str(filled)
        return out
    monkeypatch.setattr(LF, "run_density", _density)
    return project, gds, calls


def test_on_librelane_the_tool_fill_ships(tmp_path, monkeypatch):
    project, gds, calls = _gds_stage(tmp_path, monkeypatch, "librelane", {"34-fill": 0})
    ctx = R._step34_gds_tool_arm(project, SimpleNamespace(name="p"), gds)
    ok, note = R._step34_gds_ship(project, gds, ctx, (False, ctx["not_run"]))
    assert ok and "KLayout.Filler" in note
    assert gds.read_bytes() == b"sealed+pdkfill"
    assert calls == ["34-fill"]
    assert json.loads((project / LF.RECORD_REL).read_text())["gds"]["shipped"] == "librelane"


@pytest.mark.parametrize("tool,direct,shipped", [(1, 0, "direct"), (0, 1, "librelane"),
                                                 (0, 0, "direct")])
def test_dual_measures_both_fills_with_one_deck(tmp_path, monkeypatch, tool, direct, shipped):
    project, gds, calls = _gds_stage(tmp_path, monkeypatch, "dual",
                                     {"34-fill": tool, "34-direct-density": direct})
    ctx = R._step34_gds_tool_arm(project, SimpleNamespace(name="p"), gds)
    gds.write_bytes(b"sealed+directfill")          # the caller's direct passes
    R._step34_gds_ship(project, gds, ctx, (True, "direct"))
    assert calls == ["34-fill", "34-direct-density"]
    assert gds.read_bytes() == (b"sealed+pdkfill" if shipped == "librelane"
                                else b"sealed+directfill")
    rec = json.loads((project / LF.RECORD_REL).read_text())["gds"]
    assert rec["shipped"] == shipped
    assert LF.tool_density(project)["errors"] == min(tool, direct) if shipped else True


@pytest.mark.parametrize("mode,counts,shipped,gds_bytes", [
    ("librelane", {"34-fill": 2}, None, b"sealed"),
    ("dual", {"34-fill": 1, "34-direct-density": 2}, "direct", b"sealed+directfill"),
], ids=["librelane", "dual"])
def test_a_tool_fill_that_was_not_copied_is_not_recorded_as_shipped(
        tmp_path, monkeypatch, mode, counts, shipped, gds_bytes):
    """Review wave 57: the copy into gds_out runs only at 0 density errors,
    but the record still said shipped='librelane' with the digest of bytes
    that arm never produced, and step 35 then read the tool arm's count as
    the density of the shipped stream."""
    project, gds, calls = _gds_stage(tmp_path, monkeypatch, mode, counts)
    ctx = R._step34_gds_tool_arm(project, SimpleNamespace(name="p"), gds)
    if mode == "dual":
        gds.write_bytes(b"sealed+directfill")      # the caller's direct passes
    ok, _ = R._step34_gds_ship(project, gds, ctx, (True, "direct"))
    assert not ok
    assert gds.read_bytes() == gds_bytes
    rec = json.loads((project / LF.RECORD_REL).read_text())["gds"]
    assert rec["shipped"] == shipped
    assert "librelane arm not shipped" in rec["ship_refusal"]
    if shipped is None:
        assert rec["shipped_sha256"] is None
        assert LF.tool_density(project) is None
        refused = [f for f in MFD.tool_arm_findings(project)[0]
                   if f.category == "LL_FILL_GDS_REFUSED"]
        assert refused and "librelane arm not shipped" in refused[0].message
    else:
        assert rec["shipped_sha256"] == LLC.digest(gds)
        assert LF.tool_density(project)["arm"] == "direct"


# ── step 34's gate and step 35's screen read the tool ──────────────────────

def _record(project, odb=None, gds=None):
    doc = {"step": "34"}
    if odb is not None:
        doc["odb"] = odb
    if gds is not None:
        doc["gds"] = gds
    p = project / LF.RECORD_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))


def _gate_project(tmp_path, mode="librelane"):
    project = tmp_path / "g"
    (_pnr(project) / "routed.def").write_text("routed\n")
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
    state = root / f"37-{arm}-finish/03-klayout-density/state_out.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{}")
    (root / "37-promotion.json").write_text(json.dumps({"selection": arm}))
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
    _record(project, gds={"shipped": "librelane", "librelane": {
        LF.DENSITY_METRIC: 1, "rules": {"M2.4": 1}, "state": str(state),
        "state_sha256": LLC.digest(state)}})
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
