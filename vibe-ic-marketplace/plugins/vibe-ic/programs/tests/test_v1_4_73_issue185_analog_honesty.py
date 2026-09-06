"""v1.4.73 — #185: three chip-AGNOSTIC analog-honesty fixes.

(1) benchmark_verify_report._has_synth_digital_rtl counted the runner's OWN
    emitted `sim_full_stack/tb_<top>_full.v` skeleton as digital RTL — so an
    all-analog IC read as digital and FAILed Pillars 3/4 it can never satisfy.
    Fix: exclude testbench files via the SHARED rtl_hygiene_lint._is_testbench
    predicate (#524 anti-drift).

(2) analog_real_corner_sweep stamped `pdk_used_for_sim` = the verbatim --pdk
    CLI arg even when the resolved deck context .lib'd a DIFFERENT foundry's
    model set. Fix: stamp the resolved ctx.family (+ record ctx.model_lib), and
    accept a native analog PDK selector on --pdk so the truth is expressible.

(3) The A4 corner gate graded only the best/nominal corner, so a real
    process/temp corner outside the spec window passed. Fix: grade the WORST
    REAL corner, guarded by nominal-in-spec (a legitimate env/template mismatch
    is still reported informationally, not newly failed).

chip-AGNOSTIC: no chip/vendor/SKU literal.
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import benchmark_verify_report as BVR  # noqa: E402
import analog_real_corner_sweep as ARC  # noqa: E402

_A4 = PROGRAMS / "analog_a4_corner_sweep_check.py"


# ════════════════════════════════════════════════════════════════════════
# (1) _has_synth_digital_rtl excludes the emitted TB skeleton
# ════════════════════════════════════════════════════════════════════════

def _mk_full_stack_skeleton(project: Path, top="u_hawaii_adc"):
    d = project / "phase2" / "stage1" / "sim_full_stack"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"tb_{top}_full.v").write_text(
        f"// runner-emitted full-stack TB skeleton\n"
        f"module tb_{top}_full;\n  initial $finish;\nendmodule\n")


def test_tb_skeleton_is_not_digital_rtl(tmp_path):
    # THE #185 REPRO: the project's ONLY .v is the runner-emitted TB skeleton.
    _mk_full_stack_skeleton(tmp_path)
    assert BVR._has_synth_digital_rtl(tmp_path) is False


def test_real_rtl_still_reads_digital(tmp_path):
    # NO-LEAK: a genuine design .v is still detected as digital RTL.
    _mk_full_stack_skeleton(tmp_path)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "sha256.v").write_text("module sha256(input clk); endmodule\n")
    assert BVR._has_synth_digital_rtl(tmp_path) is True


def test_all_analog_ic_reads_analog_only_not_digital(tmp_path):
    # End-to-end: an analog IC whose only .v is the TB skeleton + no PnR reads
    # ANALOG-ONLY, so the digital pillars N/A instead of FAILing.
    ana = tmp_path / "phase3" / "analog"
    ana.mkdir(parents=True, exist_ok=True)
    (ana / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "ldo", "type": "ldo"}]}))
    _mk_full_stack_skeleton(tmp_path)
    assert BVR._is_analog_ic(tmp_path) is True
    assert BVR._has_synth_digital_rtl(tmp_path) is False
    assert BVR._is_analog_only_ic(tmp_path) is True


# ════════════════════════════════════════════════════════════════════════
# (2) pdk_used_for_sim reflects the resolved family, --pdk is expressible
# ════════════════════════════════════════════════════════════════════════

class _Ctx:
    def __init__(self, family=None, model_lib=None):
        self.family = family
        self.model_lib = model_lib


def test_pdk_label_uses_resolved_family_not_arg():
    # The decks resolved a native analog family though --pdk was left at sky130.
    ctx = _Ctx(family="ihp-sg13g2",
               model_lib="/foss/pdks/ihp-sg13g2/.../cornerMOShv.lib")
    assert ARC._resolved_sim_pdk_label(ctx, "sky130") == "ihp-sg13g2"


def test_pdk_label_falls_back_to_arg_when_no_family():
    assert ARC._resolved_sim_pdk_label(_Ctx(family=None), "sky130") == "sky130"
    assert ARC._resolved_sim_pdk_label(None, "gf180") == "gf180"


def test_pdk_arg_accepts_native_selector(monkeypatch, tmp_path):
    # #185: the PROGRAM's own main() argparse must not hard-reject a native
    # analog PDK selector (the old `choices={sky130,gf180}` meant no invocation
    # could even name it). Stub run_block so we only exercise argparse + dispatch.
    captured = {}

    def _stub(project, block, container, pdk, topology):
        captured["pdk"] = pdk
        return 0

    monkeypatch.setattr(ARC, "run_block", _stub)
    monkeypatch.setattr(sys, "argv",
                        ["prog", str(tmp_path), "--block", "ldo",
                         "--pdk", "sg13g2"])
    rc = ARC.main()
    assert rc == 0
    assert captured["pdk"] == "sg13g2"       # argparse accepted the native name


def test_worst_corner_of_picks_largest_real_error():
    grid = [
        {"name": "tt_27c", "simulator_run": True, "vout_v": 1.2,
         "temp_c": 27, "process": "tt"},
        {"name": "ff_125c", "simulator_run": True, "vout_v": 1.30029,
         "temp_c": 125, "process": "ff"},
        {"name": "ss_m40c", "simulator_run": False, "vout_v": 0.9,  # DERIVED
         "temp_c": -40, "process": "ss"},
    ]
    wc = ARC._worst_corner_of(grid, target_center=1.2, tol=0.05)
    assert wc["name"] == "ff_125c"          # largest REAL error
    assert wc["in_spec"] is False


# ════════════════════════════════════════════════════════════════════════
# (3) the A4 gate grades the WORST real corner
# ════════════════════════════════════════════════════════════════════════

def _block_list(project, blocks):
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(json.dumps({"blocks": blocks}))


def _corners(project, block, doc):
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "corner_results.json").write_text(json.dumps(doc))
    # A4's declared upstream input. These fixtures are about WHICH corner the
    # gate grades; a sweep with no netlist behind it never gets that far (the
    # gate's A4_NETLIST_ABSENT rule stops it), so they carry the netlist a run
    # that reached A4 would have.
    (d / f"{block}.sp").write_text(
        f"* {block} — synthetic block netlist\n"
        f".subckt {block} vdd vss vin vout\n"
        f"xm1 vout vin vss vss nch w=8 l=1\n"
        f"r1 vout vss 100k\n"
        f".ends {block}\n")


def _run_a4(project, *args):
    return subprocess.run(
        [sys.executable, str(_A4), str(project),
         "--json", str(project / "a4.json"), *args],
        capture_output=True, text=True)


def _ldo_doc(nominal_vout, worst_vout, worst_real=True):
    # target 1.2 V, tol 0.05 (window ~1.14..1.26). best_corner = nominal tt_27c.
    return {
        # These fixtures are about WHICH corner the gate grades. Two of them
        # assert a clean PASS, and a corner artefact that will not say what
        # circuit it simulated no longer reaches one — so, like the netlist
        # `_corners` already writes, the record of WHAT was simulated is part
        # of the run these fixtures stand in for rather than a property under
        # test here.
        "design_content": "structure_and_geometry",
        "best_corner": {"name": "tt_27c", "value": nominal_vout},
        "corners": [
            {"name": "tt_27c", "process": "tt", "temp_c": 27,
             "simulator_run": True, "vout_v": nominal_vout, "margin": 0.05},
            {"name": "ff_125c", "process": "ff", "temp_c": 125,
             "simulator_run": worst_real, "vout_v": worst_vout, "margin": 0.05},
        ],
        "spec_results": [
            {"name": "vout", "status": "PASS_INFORMATIONAL",
             "target": 1.2, "tolerance_pct": 0.05},
        ],
    }


def test_a4_fails_on_worst_real_corner(tmp_path):
    # THE #185 REPRO: nominal tt_27c in-spec (1.2) but real ff_125c out-of-spec
    # (1.35 → rel 0.125 > 0.05). Best-corner view PASSed; worst-corner FAILs.
    _block_list(tmp_path, [{"name": "ldo", "type": "ldo"}])
    _corners(tmp_path, "ldo", _ldo_doc(1.2, 1.35))
    r = _run_a4(tmp_path)
    rpt = json.loads((tmp_path / "a4.json").read_text())
    assert rpt["verdict"] == "FAIL", rpt
    rules = [f.get("rule") for f in rpt.get("findings", [])]
    assert "A4_CORNER_MARGIN_FAIL" in rules, rpt


def test_a4_env_gap_nominal_out_of_spec_not_newly_failed(tmp_path):
    # NO-REGRESSION (v1.6.228 env-gap): the NOMINAL itself is out-of-spec (the
    # demo template doesn't match the target) → not a corner-margin failure; the
    # worst-corner gate does NOT newly FAIL it.
    _block_list(tmp_path, [{"name": "ldo", "type": "ldo"}])
    _corners(tmp_path, "ldo", _ldo_doc(0.9, 1.35))   # nominal 0.9 way off 1.2
    r = _run_a4(tmp_path)
    rpt = json.loads((tmp_path / "a4.json").read_text())
    rules = [f.get("rule") for f in rpt.get("findings", [])]
    assert "A4_CORNER_MARGIN_FAIL" not in rules, rpt


def test_a4_derived_out_of_spec_corner_not_failed(tmp_path):
    """NO-REGRESSION, KEPT: an out-of-spec corner that is DERIVED
    (simulator_run False) is arithmetic, not a measurement, so it is NOT
    GRADED — `A4_CORNER_MARGIN_FAIL` must not fire on it. That assertion is
    unchanged and still holds.

    RE-AIMED on the VERDICT (vibe-ic#2062). Not-graded was also being read as
    CERTIFIED: the step passed over a record carrying a corner nobody measured.
    Measured on a real run, this gate returned PASS over a record whose own
    fields said `corners_executed: 1`, `total_corners: 9` and
    `full_pvt_sweep_executed: false` — eight cells of arithmetic in the same
    column as one measurement. A derived corner is now ACCOUNTED FOR
    (NOT_MEASURED, rc 1) rather than certified: not a measured defect, and not
    a pass either. The two verdicts are different words for a reason.
    """
    _block_list(tmp_path, [{"name": "ldo", "type": "ldo"}])
    _corners(tmp_path, "ldo", _ldo_doc(1.2, 1.35, worst_real=False))
    r = _run_a4(tmp_path)
    rpt = json.loads((tmp_path / "a4.json").read_text())
    rules = [f.get("rule") for f in rpt.get("findings", [])]
    assert "A4_CORNER_MARGIN_FAIL" not in rules, rpt
    assert rpt["verdict"] == "INCOMPLETE", rpt
    assert rpt["reason_class"] == "NOT_MEASURED", rpt
    assert r.returncode == 1, r.stderr[-2000:]
    # ...and it NAMES the corner it could not account for, so the record is
    # actionable rather than merely non-green.
    nm = [f for f in rpt["findings"]
          if f.get("rule") == "A4_PVT_SWEEP_NOT_MEASURED"]
    assert nm and nm[0]["unaccounted_corners"], rpt


def test_a4_all_real_corners_in_spec_passes(tmp_path):
    # NO-REGRESSION: all real corners in-spec → PASS.
    _block_list(tmp_path, [{"name": "ldo", "type": "ldo"}])
    _corners(tmp_path, "ldo", _ldo_doc(1.2, 1.22))
    r = _run_a4(tmp_path)
    rpt = json.loads((tmp_path / "a4.json").read_text())
    assert rpt["verdict"] == "PASS", rpt
