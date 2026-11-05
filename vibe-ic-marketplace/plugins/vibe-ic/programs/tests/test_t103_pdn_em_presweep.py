"""T103 (steps 25/25b): the PDN is sized for EM BEFORE routing, and the EM
currents are computed on the design's own power basis.

What was wrong, measured on spm (gf180mcuD, vibeic-eda 0.3.79, run23 copy):

* The Step-25 EM producer solved PSM with no SDC and only the standard-cell
  liberty: OpenSTA's default activity, 23.1 mW. With the SDC alone it read
  1.19 mW -- a false PASS, because the clock enters through an IO pad whose
  liberty was not loaded and never reached its tree. With SDC + SPEF + the IO
  liberty the PnR and sign-off sessions load: 21.0 mW. Metal4 still failed
  (1.438 / 1.295 of the margined Jmax): the violation is REAL, not an
  instrument artefact, and the old basis only overstated it.
* The only remedy was the post-route resize + second PnR (removed in
  v1.24.85). Nothing sized the grid before routing.

The rule the code follows now:

* The EM producer reads the flow's SDC (propagated clocks), the step-22 SPEF
  when it is not older than the routed DEF, and the same-PVT IO/macro
  liberties; em.json records that basis and whether the clock reached its
  network.
* Inside the PnR session, after CTS/hold and before global routing, the deck's
  own PDN block is re-run over a lattice of strap widths/pitches and each
  candidate is judged by the Step-25 gate's own instrument; the cheapest that
  clears the gate with its guardband applied once more is rebuilt in place.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402
from _ppa import pdn_em_presweep as S  # noqa: E402

# A generic two-strap-layer stack: 1 mA/um DC limit, 0.5 um thick, so the
# per-width Jmax is 1e-3 A/um. No PDK literal.
TLEF = """\
UNITS
  DATABASE MICRONS 1000 ;
END UNITS
MANUFACTURINGGRID 0.005 ;
LAYER M1
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  WIDTH 0.2 ;
  THICKNESS 0.5 ;
  SPACING 0.2 ;
  DCCURRENTDENSITY AVERAGE 1.0 ;
END M1
LAYER M4
  TYPE ROUTING ;
  DIRECTION VERTICAL ;
  WIDTH 0.3 ;
  THICKNESS 0.5 ;
  SPACING 0.3 ;
  DCCURRENTDENSITY AVERAGE 1.0 ;
END M4
LAYER M5
  TYPE ROUTING ;
  DIRECTION HORIZONTAL ;
  WIDTH 0.4 ;
  THICKNESS 0.5 ;
  SPACING 0.4 ;
  DCCURRENTDENSITY AVERAGE 1.0 ;
END M5
"""
STRAPS = [{"layer": "M4", "width": 1.6, "pitch": 40.0, "offset": 10.0},
          {"layer": "M5", "width": 1.6, "pitch": 40.0, "offset": 10.0}]
NETS = {"VDD": 5.0, "VSS": 0.0}


def _sweep(tmp_path, straps=STRAPS):
    tl = tmp_path / "tech.lef"
    tl.write_text(TLEF)
    doc = S.lattice(straps, TLEF, budget=0.5, offset_div=4.0)
    sweep = tmp_path / "pnr" / S.SWEEP_DIR
    S.stage(sweep, lattice_doc=doc, blocks={c["id"]: f"# block {c['id']}\n"
                                              for c in doc["candidates"]},
            tech_lef=tl, tech_lef_text=TLEF, nets=NETS, margin=0.1)
    return sweep, {c["id"]: c for c in doc["candidates"]}, doc


def _measure(sweep, cid, *, currents, strap_w=None, ring_w=1.0, ring_current=None):
    """What the session writes for one candidate: its DEF (a ring that sets
    each layer's narrowest PG width, and the strap), the PSM segment CSV per
    net, the geometry dump and the voltage file."""
    d = sweep / f"c{cid}"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for net in NETS:
        rows.append(
            f"    - {net} ( * {net} )\n"
            f"      + ROUTED M4 {int(ring_w * 1000)} + SHAPE RING ( 0 0 ) ( 0 100000 )\n"
            f"      NEW M4 {int((strap_w or 1.6) * 1000)} + SHAPE STRIPE ( 50000 0 ) ( 50000 100000 )\n"
            f"      NEW M5 {int(ring_w * 1000)} + SHAPE RING ( 0 0 ) ( 100000 0 )\n"
            f"      + USE {'POWER' if net == 'VDD' else 'GROUND'} ;\n")
    (d / "cand.def").write_text(
        "VERSION 5.8 ;\nUNITS DISTANCE MICRONS 1000 ;\n"
        f"SPECIALNETS {len(NETS)} ;\n" + "".join(rows) + "END SPECIALNETS\nEND DESIGN\n")
    (d / "em_pg_geometry.tsv").write_text(
        "net\tlayer\tx0_um\ty0_um\tx1_um\ty1_um\tsource\n"
        + "".join(f"{n}\tM4\t{50 - (strap_w or 1.6) / 2}\t0\t{50 + (strap_w or 1.6) / 2}\t100\tspecial_wire\n"
                  for n in NETS))
    for net in NETS:
        (d / f"em_segments_{net}.csv").write_text(
            "Node0 Layer,Node0 X location,Node0 Y location,Node1 Layer,"
            "Node1 X location,Node1 Y location,Current\n"
            f"M4,50,10,M4,50,20,{currents.get(net, 1e-5)}\n"
            + (f"M5,10,0,M5,20,0,{ring_current}\n" if ring_current else ""))
        (d / f"voltage_{net}.txt").write_text(f"M4,50,10,{NETS[net] - 0.01 if NETS[net] else 0.01}\n")
    (d / "pg_on_no_net.txt").write_text("0\n")
    (d / "MEASURED").write_text(cid)
    return d


# --------------------------------------------------------------------------
# the lattice
# --------------------------------------------------------------------------
def test_lattice_starts_at_the_decks_own_grid_and_orders_by_planned_tracks(tmp_path):
    doc = S.lattice(STRAPS, TLEF, budget=0.5, offset_div=4.0)
    cands = doc["candidates"]
    assert cands[0]["id"] == "0" and cands[0]["changed"] == []
    assert cands[0]["straps"]["M4"]["width"] == 1.6
    fr = [c["planned_track_fraction"] for c in cands]
    assert fr == sorted(fr), "the first feasible candidate must be the cheapest"
    # widths on 2x the manufacturing grid (pdngen centres a stripe: PDN-0117)
    for c in cands:
        for o in c["straps"].values():
            assert abs(o["width"] / 0.01 - round(o["width"] / 0.01)) < 1e-6
            assert abs(o["pitch"] / 0.005 - round(o["pitch"] / 0.005)) < 1e-6
    # a halved pitch re-derives the offset by the deck's rule (pitch / 4)
    half = next(c for c in cands if c["straps"]["M4"]["pitch_div"] == 2)
    assert half["straps"]["M4"]["pitch"] == 20.0 and half["straps"]["M4"]["offset"] == 5.0


def test_lattice_refuses_what_the_tech_lef_or_the_routing_budget_forbids(tmp_path):
    tight = [{"layer": "M4", "width": 1.6, "pitch": 12.0, "offset": 3.0}]
    doc = S.lattice(tight, TLEF, budget=0.5, offset_div=4.0)
    refused = {(r["width_x"], r["pitch_div"]): r["refused"] for r in doc["refused_options"]}
    # 3 x 1.6 = 4.8 um at pitch 12: 2w + s = 9.9 < 12 fits, but 2w/p = 0.8 > 0.5
    assert "routing budget" in refused[(3.0, 1)]
    # pitch 6: two 3.2 um straps + 0.3 spacing do not fit
    assert "do not fit" in refused[(2.0, 2)]
    kept = {(c["straps"]["M4"]["width_x"], c["straps"]["M4"]["pitch_div"]) for c in doc["candidates"]}
    assert (3.0, 1) not in kept and (2.0, 2) not in kept and (1.0, 1) in kept
    maxw = TLEF.replace("  SPACING 0.3 ;\n", "  SPACING 0.3 ;\n  MAXWIDTH 3.0 ;\n", 1)
    doc = S.lattice(STRAPS[:1], maxw, budget=0.5, offset_div=4.0)
    assert any("MAXWIDTH" in r["refused"] for r in doc["refused_options"])


# --------------------------------------------------------------------------
# the search
# --------------------------------------------------------------------------
def test_a_clearing_flow_grid_is_kept_and_nothing_is_rebuilt(tmp_path):
    sweep, _c, _d = _sweep(tmp_path)
    _measure(sweep, "0", currents={"VDD": 1e-4, "VSS": 1e-4})
    assert S.next_action(sweep) == ("DONE", "0")
    rec = json.loads((sweep / S.RECORD_FILE).read_text())
    assert rec["verdict"] == "PASS" and rec["chosen"] == "0"


def test_a_failing_flow_grid_is_widened_to_the_cheapest_candidate_that_clears(tmp_path):
    sweep, cands, _d = _sweep(tmp_path)
    # 1.5 mA on a 1.6 um strap: 0.94 of Jmax -- the gate fails it.
    _measure(sweep, "0", currents={"VDD": 1.5e-3, "VSS": 1e-4})
    op, first = S.next_action(sweep)
    assert op == "EVAL"
    # only candidates that change the worst layer (M4), and nothing else
    rec = json.loads((sweep / S.RECORD_FILE).read_text())
    assert rec["worst_layer"] == "M4"
    assert all(cands[c]["changed"] == ["M4"] for c in rec["eligible"])
    assert first == rec["eligible"][0]
    w = cands[first]["straps"]["M4"]["width"]
    _measure(sweep, first, currents={"VDD": 1.5e-3, "VSS": 1e-4}, strap_w=w)
    op, chosen = S.next_action(sweep)
    assert (op, chosen) == ("DONE", first)
    rec = json.loads((sweep / S.RECORD_FILE).read_text())
    assert rec["verdict"] == "PASS"
    assert rec["chosen_straps"]["M4"]["width"] == w > 1.6


def test_only_the_worst_layer_is_widened_first(tmp_path):
    """M4 at 0.94 and M5 at 0.85 of Jmax: both are short of the clearing bar,
    but a candidate that leaves M4 alone cannot fix the worst segment."""
    sweep, cands, _d = _sweep(tmp_path)
    _measure(sweep, "0", currents={"VDD": 1.5e-3, "VSS": 1e-4}, ring_current=0.85e-3)
    op, first = S.next_action(sweep)
    rec = json.loads((sweep / S.RECORD_FILE).read_text())
    assert op == "EVAL" and rec["worst_layer"] == "M4"
    assert rec["layers_short_of_headroom"] == ["M4", "M5"]
    assert rec["eligible"] and all("M4" in cands[c]["changed"] for c in rec["eligible"])
    assert any(cands[c]["changed"] == ["M4", "M5"] for c in rec["eligible"])


def test_passing_without_the_estimate_guardband_does_not_end_the_search(tmp_path):
    """0.85 of Jmax passes the gate (< 0.9) but not (1 - m)^2 = 0.81: the
    routed layout carries more current than this estimate (spm: x1.10)."""
    sweep, cands, _d = _sweep(tmp_path)
    _measure(sweep, "0", currents={"VDD": 1.5e-3, "VSS": 1e-4})
    _op, first = S.next_action(sweep)
    w = cands[first]["straps"]["M4"]["width"]
    _measure(sweep, first, currents={"VDD": 0.85e-3 * w, "VSS": 1e-4}, strap_w=w)
    op, nxt = S.next_action(sweep)
    assert op == "EVAL" and nxt != first
    rec = json.loads((sweep / S.RECORD_FILE).read_text())
    assert rec["evaluated"][first]["passes_gate"] is True
    assert rec["evaluated"][first]["clears_with_guardband"] is False


def test_a_segment_below_the_gate_bar_is_judged_at_its_drawn_width(tmp_path):
    """The gate re-judges a segment at its covering wire's width only when
    the layer-minimum bound makes it an offender. At 0.85 of Jmax on the 1.0 um
    ring bound, a segment on a 4 um strap is really at 0.21 -- judged at the
    gate's own margin it would read 0.85 and never clear (spm: 0.871 vs
    0.803 on 3.2 um straps)."""
    sweep, _c, _d = _sweep(tmp_path)
    d = _measure(sweep, "0", currents={"VDD": 0.85e-3, "VSS": 1e-4}, strap_w=4.0)
    r = S.judge(d, sweep.parent.parent / "tech.lef", NETS, 0.1)
    assert r["worst_utilization"] == pytest.approx(0.85e-3 / 4.0e-3)
    assert S.next_action(sweep) == ("DONE", "0")


def test_a_candidate_that_did_not_build_is_never_chosen(tmp_path):
    sweep, _c, _d = _sweep(tmp_path)
    _measure(sweep, "0", currents={"VDD": 1.5e-3, "VSS": 1e-4})
    _op, first = S.next_action(sweep)
    (sweep / f"c{first}").mkdir()
    (sweep / f"c{first}" / "BUILD_FAILED").write_text("PDN-0108 no grid")
    op, nxt = S.next_action(sweep)
    assert op == "EVAL" and nxt != first
    rec = json.loads((sweep / S.RECORD_FILE).read_text())
    assert rec["evaluated"][first]["verdict"] == "BUILD_FAILED"


def test_a_spent_budget_keeps_the_passing_candidate_with_most_headroom(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "MAX_EVALUATIONS", 2)
    sweep, cands, _d = _sweep(tmp_path)
    _measure(sweep, "0", currents={"VDD": 1.5e-3, "VSS": 1e-4})
    seen = []
    for util in (0.87, 0.84):
        op, cid = S.next_action(sweep)
        assert op == "EVAL"
        w = cands[cid]["straps"]["M4"]["width"]
        _measure(sweep, cid, currents={"VDD": util * w * 1e-3, "VSS": 1e-4}, strap_w=w)
        seen.append(cid)
    op, chosen = S.next_action(sweep)
    rec = json.loads((sweep / S.RECORD_FILE).read_text())
    assert (op, chosen) == ("DONE", seen[1])
    assert rec["verdict"] == "PASS_WITHOUT_HEADROOM"
    assert "supply pad count" in rec["next_axis"]


def test_a_grid_solved_with_floating_supply_pins_is_not_judged(tmp_path):
    """spm, in the PnR session after CTS: the clock tree's supply pins were on
    no net, PSM drew 6 mW of 19.5, and the flow grid read 0.153 of Jmax --
    a PASS about a third of the design."""
    sweep, _c, _d = _sweep(tmp_path)
    d = _measure(sweep, "0", currents={"VDD": 1e-4, "VSS": 1e-4})
    (d / "pg_on_no_net.txt").write_text("21888\n")
    assert S.next_action(sweep) == ("DONE", "0")
    rec = json.loads((sweep / S.RECORD_FILE).read_text())
    assert rec["verdict"] == "NOT_MEASURED"
    assert "21888 supply terminal(s) on no net" in rec["evaluated"]["0"]["reason"]
    (d / "pg_on_no_net.txt").unlink()
    S.next_action(sweep)
    assert json.loads((sweep / S.RECORD_FILE).read_text())["verdict"] == "NOT_MEASURED"


def test_an_unmeasured_flow_grid_changes_nothing(tmp_path):
    sweep, _c, _d = _sweep(tmp_path)
    (sweep / "c0").mkdir()
    assert S.next_action(sweep) == ("DONE", "0")
    assert json.loads((sweep / S.RECORD_FILE).read_text())["verdict"] == "NOT_MEASURED"


def test_the_staged_judge_runs_by_path_as_the_session_runs_it(tmp_path):
    import subprocess
    sweep, _c, _d = _sweep(tmp_path)
    _measure(sweep, "0", currents={"VDD": 1e-4, "VSS": 1e-4})
    out = subprocess.run([sys.executable, str(sweep / "lib" / "_ppa" / "pdn_em_presweep.py"),
                          "next", str(sweep)], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin"}, cwd=str(tmp_path))
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["DONE", "0"]


def test_finalize_publishes_the_record_with_the_pareto_frontier(tmp_path):
    sweep, cands, _d = _sweep(tmp_path)
    _measure(sweep, "0", currents={"VDD": 1.5e-3, "VSS": 1e-4})
    _op, first = S.next_action(sweep)
    _measure(sweep, first, currents={"VDD": 1.5e-3, "VSS": 1e-4},
             strap_w=cands[first]["straps"]["M4"]["width"])
    S.next_action(sweep)
    rec = S.finalize(tmp_path, sweep.parent)
    out = json.loads((tmp_path / S.REPORT_REL).read_text())
    assert out["chosen"] == first == rec["chosen"]
    assert out["frontier"]["frontier"] == [first]
    assert [x["candidate_id"] for x in out["frontier"]["excluded_infeasible"]] == ["0"]
    assert out["lattice"]["layers"] == ["M4", "M5"]


# --------------------------------------------------------------------------
# the session block
# --------------------------------------------------------------------------
def test_the_session_keeps_the_supply_pins_and_restores_the_flow_grid_on_error():
    tcl = S.session_tcl(sweep_dir="/p/pdn_em_presweep", python="python3", nets=NETS,
                        corner="tt", declared_pads=["u_pwr", "u_gnd"],
                        stage_marker="PNR_STAGE:")
    # `pdngen -ripup` also deletes the supply BTerms' pins, and PSM then makes
    # every top-layer node a source (spm: peak segment 1.40 -> 0.38 mA).
    assert "pdngen -ripup" not in tcl
    assert "odb::dbSWire_destroy" in tcl and "pdngen -reset" in tcl
    assert "uplevel #0 [list source $_pes_dir/cand_$k.tcl]" in tcl
    assert "estimate_parasitics -placement" in tcl
    assert "set_pdnsim_net_voltage -net VDD -voltage 5 -corner tt" in tcl
    assert "analyze_power_grid -net $_n -corner tt -enable_em" in tcl
    assert "check_current_density -net $_n -corner tt" in tcl
    assert "exec python3 $_pes_dir/lib/_ppa/pdn_em_presweep.py next $_pes_dir" in tcl
    assert "_vibeic_pes_build 0" in tcl and "PDN_EM_PRESWEEP_RESTORE_FAILED" in tcl
    assert "PDN_EM_PRESWEEP_NET_UNSOURCED" in tcl
    assert "u_pwr u_gnd" in tcl
    # every measurement first connects the post-PDN instances, lifting and
    # restoring do-not-touch, and records what is still floating
    i_conn = tcl.index("proc _vibeic_pes_connect")
    assert "setDoNotTouch false" in tcl[i_conn:] and "setDoNotTouch true" in tcl[i_conn:]
    i_meas = tcl.index("proc _vibeic_pes_measure")
    body = tcl[i_meas:tcl.index("analyze_power_grid", i_meas)]
    assert "pg_on_no_net.txt" in body and "_vibeic_pes_connect" in body




def test_prepare_declines_a_deck_it_cannot_size(tmp_path):
    kw = dict(pnr_dir=tmp_path, sweep_dir_c="x", build=lambda st: "", tech_lef=tmp_path,
              tech_lef_c="x", corner=None, declared_pads=[], stage_marker="PNR_STAGE:")
    assert S.prepare(plan={}, tech_lef_text=TLEF, nets=NETS, **kw)[0] == ""
    no_jmax = TLEF.replace("  DCCURRENTDENSITY AVERAGE 1.0 ;\n", "")
    tcl, note = S.prepare(plan={"straps": STRAPS}, tech_lef_text=no_jmax, nets=NETS, **kw)
    assert tcl == "" and "no Jmax" in note
    tcl, note = S.prepare(plan={"straps": STRAPS}, tech_lef_text=TLEF, nets={}, **kw)
    assert tcl == "" and "NOT_MEASURED" in note




# --------------------------------------------------------------------------
# the Step-25 producer's power basis
# --------------------------------------------------------------------------
_PSM_LOG = """=== EM_POWER_BASIS ===
Group                  Internal  Switching    Leakage      Total
                          Power      Power      Power      Power (Watts)
----------------------------------------------------------------
Sequential             1.42e-03   5.12e-05   2.62e-08   1.47e-03   7.0%
Combinational          3.93e-04   6.23e-04   4.74e-08   1.02e-03   4.8%
Clock                  {clk}   3.71e-03   1.35e-06   1.43e-02  68.1%
Pad                    3.68e-03   5.26e-04   1.64e-07   4.21e-03  20.1%
Total                  1.61e-02   4.91e-03   1.59e-06   2.10e-02 100.0%
=== EM_POWER_BASIS_END ===
Maximum current : 2.0e-03 A
Worstcase IR drop: 1e-4 V
"""












# --------------------------------------------------------------------------
# the LibreLane hand-off (OpenROAD.GeneratePDN reads PDN_*)
# --------------------------------------------------------------------------
def test_emit_config_hands_the_chosen_straps_to_generate_pdn(tmp_path):
    from test_librelane_contract import contract, design
    p = design(tmp_path)
    rec = {"verdict": "PASS", "chosen": "3",
           "chosen_straps": {"M4": {"width": 3.2, "pitch": 153.6, "offset": 16.32},
                             "M5": {"width": 1.6, "pitch": 153.18, "offset": 16.65}},
           "lattice": {"directions": {"M4": "VERTICAL", "M5": "HORIZONTAL"}}}
    (p / S.REPORT_REL).parent.mkdir(parents=True, exist_ok=True)
    (p / S.REPORT_REL).write_text(json.dumps(rec))
    out = contract.emit_config(p, 'processA', p / 'phase3/librelane/config.json')
    assert (out["PDN_VERTICAL_LAYER"], out["PDN_VWIDTH"], out["PDN_VPITCH"]) == ("M4", 3.2, 153.6)
    assert (out["PDN_HORIZONTAL_LAYER"], out["PDN_HWIDTH"], out["PDN_HPITCH"]) == ("M5", 1.6, 153.18)
    prov = json.loads((p / 'phase3/librelane/config.provenance.json').read_text())
    assert prov["PDN_VWIDTH"].startswith(S.REPORT_REL)
    for verdict in ("INFEASIBLE", "NOT_MEASURED"):
        (p / S.REPORT_REL).write_text(json.dumps(dict(rec, verdict=verdict)))
        out = contract.emit_config(p, 'processA', p / 'phase3/librelane/config.json')
        assert not any(k.startswith("PDN_V") or k.startswith("PDN_H") for k in out)
    (p / S.REPORT_REL).unlink()
    out = contract.emit_config(p, 'processA', p / 'phase3/librelane/config.json')
    assert "PDN_VWIDTH" not in out
