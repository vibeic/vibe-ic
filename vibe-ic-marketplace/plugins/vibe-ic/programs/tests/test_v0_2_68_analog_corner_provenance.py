"""v0.2.68 analog corner provenance + PDK consistency regressions.

Pins the #438 fix (ORGANIC-20260606-analog-corner-mislabel-and-pdk-
mismatch, HIGH):

  (a) corner_results.json marked every corner simulator_run=true while
      derived_from admitted 8/9 were arithmetic derivations of the one
      real tt@27C sim — the emitter now marks ONLY the executed corner
      simulator_run=true (citing its ngspice invocation log), derived
      corners get _provenance=DERIVED, and executed-vs-derived counts
      are first-class; the sweep gate surfaces the counts, downgrades
      the tier to PASS_WITH_DERIVED_CORNERS, and FAILs all-derived;
  (b) decks instantiating a different foundry's device models than the
      project's DECLARED PDK target get a named PDK_MISMATCH finding
      (waivable with a documented rationale);
  (c) the HW-vs-SPICE and pre-vs-post comparison gates FAIL — never
      PASS — when items_compared == 0.

chip-AGNOSTIC: synthetic fixtures + source pins only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_corner_sweep_check as ACS         # noqa: E402
import analog_hw_spice_correlation_check as HSC  # noqa: E402
import analog_netlist_pdk_check as NPC          # noqa: E402
import analog_pre_vs_post_layout_check as PVP   # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_SWEEP_SRC = (PLUGIN / "programs" / "analog_real_corner_sweep.py").read_text()


# ── (a) emitter source: honest per-corner provenance ───────────────────────

def test_emitter_marks_only_executed_corner_simulator_run():
    i = _SWEEP_SRC.index("pvt_grid = []")
    window = _SWEEP_SRC[i:i + 2200]
    assert '"simulator_run": is_executed' in window
    assert '"DERIVED"' in window
    assert '"simulator_run": True,' not in window  # the old blanket label


def test_emitter_persists_ngspice_invocation_log():
    assert ".ngspice.log" in _SWEEP_SRC
    assert '"ngspice_log"' in _SWEEP_SRC


def test_emitter_counts_executed_vs_derived():
    for key in ('"corners_executed"', '"corners_derived"',
                '"full_pvt_sweep_executed"'):
        assert key in _SWEEP_SRC, key


# ── (a) sweep gate: counts surfaced, tier downgraded, all-derived FAILs ────

def _grid(executed_names=("tt_27c",), total=9):
    procs, temps = ("ss", "tt", "ff"), ("m40c", "27c", "125c")
    corners = []
    for p in procs:
        for t in temps:
            name = f"{p}_{t}"
            ex = name in executed_names
            corners.append({
                "name": name, "process": p,
                "simulator_run": ex,
                "_provenance": "real_ngspice" if ex else "DERIVED",
                "derived_from": None if ex else "tt_27c base scaled",
                "vout_v": 1.8,
            })
    return corners[:total]


def _block(tmp_path, corners, spec_status="PASS"):
    bdir = tmp_path / "phase3" / "analog" / "blk"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "corner_results.json").write_text(json.dumps({
        "_provenance": "real_ngspice",
        # `_provenance` and the executed/derived split are both about HOW the
        # corners were obtained. `design_content` is the separate answer to
        # WHAT circuit they were obtained from, and these fixtures assert a
        # certified sweep — so without it each of them would also be asserting
        # that a sweep which will not name its subject can be certified.
        # Executed-vs-derived accounting stays the property under test.
        "design_content": "structure_and_geometry",
        "total_corners": len(corners),
        "results_found": len(corners),
        "corners": corners,
        "spec_results": [{"name": "vout", "status": spec_status}],
    }))
    return tmp_path


def test_sweep_gate_discloses_derived_and_downgrades_tier(tmp_path):
    _block(tmp_path, _grid())
    r = ACS.run_audit(tmp_path)
    assert r.passed is True  # the genuine base sim keeps PASSing
    assert r.summary["verdict_tier"] == "PASS_WITH_DERIVED_CORNERS"
    assert r.summary["blocks_with_derived_corners"] == 1
    d = r.summary["details"][0]
    assert d["corners_executed"] == 1 and d["corners_derived"] == 8
    assert any(f.rule == "CORNER_SWEEP_DERIVED_DISCLOSED"
               for f in r.findings)


def test_sweep_gate_fails_all_derived(tmp_path):
    _block(tmp_path, _grid(executed_names=()))
    r = ACS.run_audit(tmp_path)
    assert r.passed is False
    assert any(f.rule == "ALL_CORNERS_DERIVED" for f in r.findings)


def test_sweep_gate_legacy_mislabel_counts_as_derived(tmp_path):
    # the audited shape: simulator_run=true everywhere but derived_from
    # admits the scaling — derived_from wins
    corners = _grid()
    for c in corners:
        c["simulator_run"] = True
        c.pop("_provenance", None)
    _block(tmp_path, corners)
    r = ACS.run_audit(tmp_path)
    d = r.summary["details"][0]
    assert d["corners_derived"] == 8
    assert r.summary["verdict_tier"] == "PASS_WITH_DERIVED_CORNERS"


def test_sweep_gate_fully_executed_grid_is_plain_pass(tmp_path):
    corners = _grid(executed_names={f"{p}_{t}" for p in ("ss", "tt", "ff")
                                    for t in ("m40c", "27c", "125c")})
    _block(tmp_path, corners)
    r = ACS.run_audit(tmp_path)
    assert r.passed is True
    assert r.summary["verdict_tier"] == "PASS"


# ── (b) PDK_MISMATCH vs the declared target ────────────────────────────────

_SKY_DECK = """* ldo deck
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt
XM1 out in vdd vdd sky130_fd_pr__pfet_01v8 W=10 L=0.5
XM2 out in vss vss sky130_fd_pr__nfet_01v8 W=5 L=0.5
.end
"""


def _pdk_project(tmp_path, declared):
    a = tmp_path / "phase3" / "analog" / "blk"
    a.mkdir(parents=True)
    (a / "deck.sp").write_text(_SKY_DECK)
    g = tmp_path / "phase1" / "generated_docs"
    g.mkdir(parents=True)
    (g / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "fields": {"pdk_target": declared}}))
    return tmp_path


def test_pdk_mismatch_named_finding(tmp_path):
    _pdk_project(tmp_path, "commercial 180nm BCD")
    r = NPC.run_audit(tmp_path)
    assert r.passed is False
    assert any(f.rule == "PDK_MISMATCH" for f in r.findings)
    assert r.summary["pdk_mismatch_errors"] >= 1


def test_pdk_match_passes(tmp_path):
    _pdk_project(tmp_path, "sky130A")
    r = NPC.run_audit(tmp_path)
    assert not any(f.rule == "PDK_MISMATCH" for f in r.findings)


def test_pdk_na_target_skips_comparison(tmp_path):
    _pdk_project(tmp_path, "N/A (protocol spec, not a tapeout)")
    r = NPC.run_audit(tmp_path)
    assert not any(f.rule == "PDK_MISMATCH" for f in r.findings)


def test_pdk_mismatch_waivable_with_rationale(tmp_path):
    _pdk_project(tmp_path, "commercial 180nm BCD")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "A4", "ticket": "VIBE-PDK_MISMATCH-1",
            "rationale": "native commercial-PDK ngspice models unavailable; "
                         "sky130 proxy decks document the env gap.",
            "approver": "user", "review_required": True,
        }]
    }))
    r = NPC.run_audit(tmp_path)
    assert not any(f.rule == "PDK_MISMATCH" for f in r.findings)
    assert any(f.rule == "PDK_MISMATCH_WAIVED" for f in r.findings)


# ── (c) comparison gates with 0 items compared ─────────────────────────────

def test_hw_spice_zero_compared_fails(tmp_path):
    a = tmp_path / "phase3" / "analog" / "blk"
    a.mkdir(parents=True)
    # HW file present but with keys that overlap NOTHING in SPICE data
    (a / "hw_measurements.json").write_text(json.dumps(
        {"measurements": {"only_hw_key": 1.0}}))
    (a / "corner_results.json").write_text(json.dumps(
        {"pvt_results": {"tt": {"only_spice_key": 2.0}}}))
    r = HSC.run_audit(tmp_path)
    assert r.passed is False
    assert any(f.rule == "HW_SPICE_ZERO_COMPARED" for f in r.findings)
    assert r.summary["measurements_compared"] == 0


def test_pre_vs_post_zero_compared_fails(tmp_path):
    a = tmp_path / "phase3" / "analog" / "blk"
    a.mkdir(parents=True)
    (a / "pre_vs_post.json").write_text(json.dumps(
        {"comparisons": {"vout": {"pre_layout": None, "post_layout": None}}}))
    r = PVP.run_audit(tmp_path)
    assert r.passed is False
    assert any(f.rule == "PRE_VS_POST_ZERO_COMPARED" for f in r.findings)


def test_pre_vs_post_with_items_still_passes(tmp_path):
    a = tmp_path / "phase3" / "analog" / "blk"
    a.mkdir(parents=True)
    # The pre-layout baseline this comparison is measured AGAINST, carrying
    # the record of what circuit it is. Added when this gate — the one the
    # FLOW declares for the post-layout step — stopped certifying a
    # comparison whose subject nothing on the tree names. This test is about
    # the ZERO-COMPARED rule, so its fixture has to clear every other one.
    (a / "corner_results.json").write_text(json.dumps(
        {"block": "blk", "_provenance": "real_ngspice",
         "corners": [{"name": "tt_27c_1v8", "simulator_run": True}],
         "design_content": "structure_and_geometry"}))
    (a / "pre_vs_post.json").write_text(json.dumps(
        {"comparisons": {"vout": {"pre_layout": 1.80, "post_layout": 1.79}}}))
    r = PVP.run_audit(tmp_path)
    assert r.passed is True
