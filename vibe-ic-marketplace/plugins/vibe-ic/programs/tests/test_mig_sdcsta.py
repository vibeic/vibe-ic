"""T92 migration lane mig-sdcsta: steps 7, 8, 10, 12, 13 and 14 on the tool path.

Every tool artefact here is a REAL one (programs/calibration/, produced by the
released vibeic-eda 0.3.77 image); only the process edge that would have
written it is substituted.
"""
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
CAL = PROGRAMS / "calibration"
contract = importlib.import_module("librelane_contract")


def _optional(name):
    """A module this lane adds; absent on the tree it branched from."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj) if not isinstance(obj, str) else obj)
    return path


def design(tmp_path, pads=False):
    p = tmp_path / "design"
    put(p / "phase1/generated_docs/L8_TIMING_WAVEFORM.json", {
        "clock_domains": [{"role": "primary", "period_ns": 10, "source_pin": "clk"}]})
    put(p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {"top_module": "cal_chain"})
    put(p / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json", {"fields": {}})
    put(p / "input/submission_template/tapeout_declaration.json", {"answers": {}})
    if pads:
        put(p / "phase3/stage3/pnr/pad_assignment.json", {"PAD_NORTH": ["u_a"]})
    return p


# ── contract ────────────────────────────────────────────────────────────────

def test_emit_config_before_the_pad_producer_has_run(tmp_path):
    """Synthesis and pre-layout STA run before step 15.5ic writes the pads."""
    p = design(tmp_path, pads=False)
    out = contract.emit_config(p, "pdkA", p / "phase3/librelane/c.json")
    assert out["CLOCK_PERIOD"] == 10
    assert not any(k.startswith("PAD_") for k in out)


def test_edited_config_file_reruns_the_step(tmp_path, monkeypatch):
    """A step config that names a file (SDC, EQY script) must not resume stale."""
    p = design(tmp_path)
    netlist = put(p / "a.nl.v", "module cal_chain; endmodule\n")
    sdc = put(p / "deck.sdc", "create_clock -period 10 [get_ports clk]\n")
    state = put(p / "state.json", {"nl": str(netlist)})
    cfg = put(p / "cfg.json", {"PNR_SDC_FILE": str(sdc),
                               "meta": {"step": "OpenROAD.STAPrePNR"}})
    calls = []

    def tool(cmd, **_):
        calls.append(cmd)
        folder = Path(cmd[cmd.index("-o") + 1])
        put(folder / "state_out.json", {"nl": str(netlist), "metrics": {}})
        # Retained-step validation requires a non-empty invocation record.
        return SimpleNamespace(returncode=0, stdout="tool completed\n", stderr="")

    monkeypatch.setattr(contract, "image_capability", lambda *a: None)
    monkeypatch.setattr(contract.subprocess, "run", tool)
    contract.run_chain(p, "img", [("OpenROAD.STAPrePNR", cfg, state)], pdk_root='/pdk')
    contract.run_chain(p, "img", [("OpenROAD.STAPrePNR", cfg, state)], pdk_root='/pdk')
    assert len(calls) == 1
    sdc.write_text("create_clock -period 5 [get_ports clk]\n")
    contract.run_chain(p, "img", [("OpenROAD.STAPrePNR", cfg, state)], pdk_root='/pdk')
    assert len(calls) == 2


# ── steps 8 and 10: judging STAPrePNR's own output ─────────────────────────

prelayout = _optional("librelane_prelayout")


def sta_folder(root, log="sta_prepnr_linked_clean_negative.log",
               checks="sta_prepnr_check_setup_clean_negative.rpt",
               setup=5.0, hold=0.3, sdc="cal_full.sdc"):
    """A STAPrePNR step directory carrying real tool artefacts."""
    folder = root / "02-openroad-staprepnr"
    corner = folder / "nom_tt_025C_5v00"
    corner.mkdir(parents=True)
    shutil.copy(CAL / log, corner / "sta.log")
    if checks:
        shutil.copy(CAL / checks, corner / "checks.rpt")
    deck = root / sdc
    shutil.copy(CAL / sdc, deck)
    put(folder / "state_out.json", {"nl": str(root / "n.v"), "metrics": {
        "timing__setup__ws__corner:nom_tt_025C_5v00": setup,
        "timing__hold__ws__corner:nom_tt_025C_5v00": hold,
        "timing__setup__wns__corner:nom_tt_025C_5v00": 0,
        "timing__setup__tns__corner:nom_tt_025C_5v00": 0}})
    put(folder / "config.json", {"PNR_SDC_FILE": str(deck),
                                 "FALLBACK_SDC": "/tool/base.sdc",
                                 "STA_CORNERS": ["nom_tt_025C_5v00", "nom_ss_125C_4v50"],
                                 "DEFAULT_CORNER": "nom_tt_025C_5v00",
                                 "CELL_LIBS": {"*_tt_025C_5v00": ["/pdk/tt.lib"],
                                               "*_ss_125C_4v50": ["/pdk/ss.lib"]}})
    return folder, deck


def test_black_box_link_is_refused_even_though_slack_exists(tmp_path):
    folder, _ = sta_folder(tmp_path, log="sta_prepnr_black_box_positive.log")
    report = prelayout.judge_slack(folder, tmp_path / "g.json")
    assert report["verdict"] == "FAIL"
    assert report["corners"]["nom_tt_025C_5v00"]["black_boxes"] == [
        {"module": "cal_absent_master", "instance": "i0"}]


@pytest.mark.parametrize("raw", [float("inf"), None])
def test_absent_or_infinite_slack_is_not_measured_not_zero(tmp_path, raw):
    folder, _ = sta_folder(tmp_path, setup=raw)
    report = prelayout.judge_slack(folder, tmp_path / "g.json")
    assert report["verdict"] == "NOT_MEASURED"
    assert report["corners"]["nom_tt_025C_5v00"]["setup_ws"]["status"] == "NOT_MEASURED"


def test_linked_measured_slack_passes(tmp_path):
    folder, _ = sta_folder(tmp_path)
    assert prelayout.judge_slack(folder, tmp_path / "g.json")["verdict"] == "PASS"


def test_opensta_rejecting_a_constraint_fails_step8(tmp_path):
    folder, deck = sta_folder(tmp_path, log="sta_prepnr_sdc_bad_port_positive.log",
                              checks="sta_prepnr_check_setup_clock_only_positive.rpt",
                              sdc="cal_bad_port.sdc")
    config = json.loads((folder / "config.json").read_text())
    report = prelayout.judge_sdc(folder, config, deck, tmp_path / "g.json")
    assert report["verdict"] == "FAIL"
    corner = report["corners"]["nom_tt_025C_5v00"]
    assert corner["sdc_diagnostics"][0]["id"] == 366
    assert corner["check_setup"] == {"no_input_delay": 1, "unconstrained_endpoints": 2}


def test_untimed_io_alone_fails_step8(tmp_path):
    """create_clock only: OpenSTA reads it cleanly and still leaves I/O untimed."""
    folder, deck = sta_folder(tmp_path, checks="sta_prepnr_check_setup_clock_only_positive.rpt",
                              sdc="cal_clock_only.sdc")
    config = json.loads((folder / "config.json").read_text())
    report = prelayout.judge_sdc(folder, config, deck, tmp_path / "g.json")
    assert report["corners"]["nom_tt_025C_5v00"]["sdc_diagnostics"] == []
    assert report["verdict"] == "FAIL"


def test_a_declared_supply_port_is_not_an_untimed_endpoint(tmp_path):
    """check_setup lists a port named like the declared supply; it is not timing."""
    folder, deck = sta_folder(tmp_path, checks="sta_prepnr_check_setup_supply_named.rpt")
    config = json.loads((folder / "config.json").read_text())
    assert prelayout.judge_sdc(folder, config, deck, tmp_path / "a.json")["verdict"] == "FAIL"
    config.update({"VDD_NETS": ["VDD"], "GND_NETS": ["VSS"]})
    report = prelayout.judge_sdc(folder, config, deck, tmp_path / "b.json")
    assert report["verdict"] == "PASS"
    assert report["corners"]["nom_tt_025C_5v00"]["check_setup"] == {"unconstrained_endpoints": 0}


def test_step8_refuses_the_fallback_deck_and_an_absent_check_section(tmp_path):
    folder, deck = sta_folder(tmp_path, checks=None)
    config = json.loads((folder / "config.json").read_text())
    assert prelayout.judge_sdc(folder, config, deck, tmp_path / "a.json")["verdict"] == "NOT_MEASURED"
    config["PNR_SDC_FILE"] = None
    assert prelayout.judge_sdc(folder, config, deck, tmp_path / "b.json")["verdict"] == "FAIL"


def test_step7_pvt_matrix_is_the_tools_corner_set(tmp_path):
    folder, _ = sta_folder(tmp_path)
    config = json.loads((folder / "config.json").read_text())
    pvt = prelayout.pvt_matrix_from_sta_corners(
        config, folder, lambda n: "SS" if "_ss" in n else "TT")
    assert [c["name"] for c in pvt["corners"]] == config["STA_CORNERS"]
    assert pvt["corners"][1]["liberty"] == "/pdk/ss.lib"
    assert pvt["prelayout_timed_corners"] == ["nom_tt_025C_5v00"]


def test_sdc_syntax_check_defers_to_opensta_when_step8_is_switched(tmp_path):
    """The regex passes a deck OpenSTA rejects; the tool path does not."""
    import sdc_syntax_check
    p = tmp_path / "proj"
    deck = p / "phase3/stage3/pnr/constraint.sdc"
    deck.parent.mkdir(parents=True)
    shutil.copy(CAL / "cal_bad_port.sdc", deck)
    # The record the step-8 tool path writes (librelane_prelayout.judge_sdc
    # over the real Warning-366 sta.log); written literally so the tree this
    # branched from can run the control and answer.
    put(p / "phase3/librelane/prelayout/gates/step8_sdc_opensta.json", {
        "verdict": "FAIL", "sdc": str(deck), "sdc_sha256": contract.digest(deck),
        "findings": ["nom_tt_025C_5v00: 1 OpenSTA diagnostic(s) on cal_bad_port.sdc: "
                     "Warning 366 line 2: port 'cal_no_such_port' not found."]})
    assert sdc_syntax_check.audit(str(p)).passed          # direct: regex only
    for mode in ("librelane", "dual"):
        put(p / "phase3/librelane_switch.json", {"steps": {"8": mode}})
        assert not sdc_syntax_check.audit(str(p)).passed
    deck.write_text(deck.read_text() + "\n")                # record now stale
    result = sdc_syntax_check.audit(str(p))
    assert result.findings[0].rule == "OPENSTA_GATE_STALE" and not result.passed


def test_step10_tool_path_publishes_and_blocks_on_a_black_box(tmp_path, monkeypatch):
    runner = importlib.import_module("phase3_one_shot_runner")
    p = design(tmp_path)
    libs = p / "input/pdk/liberty"
    libs.mkdir(parents=True)
    for name in ("x_ss_125C.lib", "x_tt_025C.lib"):
        (libs / name).write_text("library(x) {}\n")
    put(p / "phase3/stage3/pnr/constraint.sdc", (CAL / "cal_full.sdc").read_text())
    # The stated environment: image AND PDK root declared, so the contract's
    # resolvers answer without asking this host's docker.
    (tmp_path / "pdkroot").mkdir()
    put(p / "phase3/librelane_switch.json", {"steps": {"7": "librelane", "8": "librelane",
                                                        "10": "librelane"}, "image": "img",
                                              "pdk_root_host": str(tmp_path / "pdkroot")})
    logs = {"clean": "sta_prepnr_linked_clean_negative.log",
            "bad": "sta_prepnr_black_box_positive.log"}
    chosen = {}

    def tool(project, image, pdk, top, netlist, sdc, rtl, **_):
        root = project / "phase3/librelane/prelayout/design_sdc"
        shutil.rmtree(root, ignore_errors=True)
        folder, _ = sta_folder(root, log=logs[chosen["log"]])
        config = json.loads((folder / "config.json").read_text())
        config["PNR_SDC_FILE"] = str(sdc)
        put(folder / "config.json", config)
        return folder

    monkeypatch.setattr(prelayout, "run_prelayout", tool)
    pdk = SimpleNamespace(name="pdkA", liberty=str(libs / "x_tt_025C.lib"))
    chosen["log"] = "clean"
    ok = runner.step_prelayout_signoff(p, "cal_chain", pdk, "")
    assert ok.status == "PASS", ok.detail
    rpt = (p / "phase3/stage3/sta/prelayout_per_corner/sta_TT.rpt").read_text()
    assert "STA_BASIS: PRE_LAYOUT_ESTIMATE" in rpt and "worst slack max 5.00" in rpt
    # CUT_W1A: step 10 never writes step 23's post-route corner directory
    assert not (p / "phase3/stage3/sta/per_corner").exists()
    pvt = json.loads((p / "phase2/stage2/constraints/pvt_matrix.json").read_text())
    assert pvt["corner_source"].startswith("LibreLane resolved STA_CORNERS")
    chosen["log"] = "bad"
    bad = runner.step_prelayout_signoff(p, "cal_chain", pdk, "")
    assert bad.status == "FAIL" and "LL_STA_BLACK_BOX" in bad.detail


# ── step 13: EQY arm B ─────────────────────────────────────────────────────

eqy = _optional("librelane_eqy")


def eqy_folder(root, sample):
    """A Yosys.EQY step directory holding a real EQY run's status files."""
    import tarfile
    folder = root / "01-yosys-eqy"
    (folder / "scratch").mkdir(parents=True)
    with tarfile.open(CAL / f"{sample}.tar") as tar:
        tar.extractall(folder / "scratch")
    return folder


def test_eqy_counterexample_and_proof_are_read_per_partition(tmp_path):
    bad = eqy.judge_eqy(eqy_folder(tmp_path / "a", "eqy_not_equivalent_positive"), tmp_path / "a.json")
    good = eqy.judge_eqy(eqy_folder(tmp_path / "b", "eqy_defined_init_negative"), tmp_path / "b.json")
    assert (bad["verdict"], bad["non_equivalent_points"]) == ("FAIL", ["cal_chain.y"])
    assert (good["verdict"], good["proven_points"]) == ("PASS", 2)


def test_eqy_pass_over_xbits_is_inconclusive(tmp_path):
    folder = eqy_folder(tmp_path, "eqy_xbits_vacuous_positive")
    statuses = eqy.partition_status(folder / "scratch")
    assert all(set(s.values()) == {"PASS"} for s in statuses.values())
    report = eqy.judge_eqy(folder, tmp_path / "x.json")
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["xbits_partitions"] == ["cal_chain.y", "cal_chain.q0"]


def test_eqy_script_drops_bitwuzla_and_defines_initial_values():
    text = eqy.eqy_script("top", [Path("/r.v")], Path("/n.v"), "/lib/tt.lib")
    assert "bitwuzla" not in text and "setundef -init -zero" in text
    assert "read_liberty -ignore_miss_func /lib/tt.lib" in text and "-icells /n.v" in text


@pytest.mark.parametrize("a,b,expect", [
    ("PASS", "PASS", ("PASS", "lec_run")),
    ("PASS", "FAIL", ("FAIL", None)),
    ("FAIL", "PASS", ("FAIL", None)),
    ("INCONCLUSIVE", "FAIL", ("FAIL", "eqy")),
    ("INCONCLUSIVE", "PASS", ("PASS", "eqy")),
    ("INCONCLUSIVE", "INCONCLUSIVE", ("INCONCLUSIVE", None)),
])
def test_combine_keeps_the_conclusive_arm_and_never_outvotes_a_counterexample(a, b, expect):
    got = eqy.combine({"verdict": a}, {"verdict": b})
    assert (got["verdict"], got.get("selected")) == expect
    if {a, b} == {"PASS", "FAIL"}:
        assert got["reason"] == "LEC_ARMS_DISAGREE"


def test_step13_row_takes_the_eqy_counterexample(tmp_path, monkeypatch):
    runner = importlib.import_module("design_one_shot_runner")
    p = tmp_path / "proj"
    (tmp_path / "pdkroot").mkdir()          # stated: image and PDK root declared
    put(p / "phase3/librelane_switch.json", {"steps": {"13": "dual"}, "image": "img", "pdk": "pdkA",
                                              "pdk_root_host": str(tmp_path / "pdkroot")})
    put(p / "phase2/stage1/rtl/cal_chain.v", (CAL / "cal_chain_rtl.v").read_text())
    put(p / "phase2/stage2/synth/netlist.v", (CAL / "cal_eqy_gate_noneq.v").read_text())
    put(p / "reports/lec.json", {"verdict": "INCONCLUSIVE"})
    monkeypatch.setattr(eqy, "run_eqy", lambda project, *a, namespace="lec_eqy", **k:
                        eqy_folder(project / "phase3/librelane" / namespace,
                                   "eqy_not_equivalent_positive"))
    arm_a = runner.StepResult("lec_equivalence", "NOT_MEASURED", 1.0, "arm A",
                              reason_class=runner._V.ReasonClass.INCONCLUSIVE)
    rows = runner._lec_eqy_arm(p, "cal_chain", "phase2/stage2/synth/netlist.v", [arm_a])
    assert [r.name for r in rows] == ["lec_equivalence"]
    assert rows[0].status == "FAIL"
    assert json.loads((p / "reports/lec_arms.json").read_text())["selected"] == "eqy"


def test_step13_direct_mode_leaves_arm_a_untouched(tmp_path):
    runner = importlib.import_module("design_one_shot_runner")
    arm_a = runner.StepResult("lec_equivalence", "PASS", 1.0, "arm A")
    assert runner._lec_eqy_arm(tmp_path, "t", "n.v", [arm_a]) == [arm_a]


# ── step 14: the handoff netlist ────────────────────────────────────────────

handoff = _optional("synth_handoff_netlist_check")
TIES = {"SYNTH_TIEHI_CELL": "gf180mcu_fd_sc_mcu7t5v0__tieh/Z",
        "SYNTH_TIELO_CELL": "gf180mcu_fd_sc_mcu7t5v0__tiel/ZN"}


def test_handoff_gate_fails_literal_constants_and_counts_tie_cells():
    bad = handoff.check(CAL / "synth_const_no_hilomap_positive.v", TIES)
    good = handoff.check(CAL / "synth_const_tied_negative.v", TIES)
    assert bad["verdict"] == "FAIL" and bad["constant_count"] == 2
    assert good["verdict"] == "PASS"
    assert good["tie_cells"] == {"gf180mcu_fd_sc_mcu7t5v0__tieh": 1,
                                 "gf180mcu_fd_sc_mcu7t5v0__tiel": 1}


def test_handoff_gate_refuses_an_undeclared_tie_cell():
    report = handoff.check(CAL / "synth_const_tied_negative.v", {"SYNTH_TIEHI_CELL": None})
    assert report["verdict"] == "FAIL"
    assert report["findings"][0].startswith("TIE_CELL_UNDECLARED")


def test_handoff_gate_cli_exit_codes(tmp_path):
    cfg = put(tmp_path / "config.json", TIES)
    run = lambda n: subprocess.run([sys.executable, str(PROGRAMS / "synth_handoff_netlist_check.py"),
                                    "--netlist", str(CAL / n), "--resolved", str(cfg)]).returncode
    assert (run("synth_const_tied_negative.v"), run("synth_const_no_hilomap_positive.v")) == (0, 1)


# ── step 12: DFT ports survive, and PPA admits only feasible arms ──────────

def test_scan_survival_fails_when_published_dft_ports_vanish(tmp_path):
    survival = importlib.import_module("dft_post_optimization_scan_survival_check")
    p = tmp_path / "proj"
    dff = "  DFFX1 r0 (.CLK(clk), .D(d), .Q(q));\n"
    put(p / "phase2/stage2/dft/scan_netlist.v",
        "module t(clk, d, q, shift, sout);\n input clk, d, shift;\n output q, sout;\n" + dff + "endmodule\n")
    put(p / "phase2/stage2/synth/netlist.v", "module t(clk, d, q);\nendmodule\n")
    put(p / "reports/phase2/dft/scan_chain.json", {
        "published": True, "functional_mode_tieoff": {"shift": 0}, "scan_out_port": "sout"})
    post = p / "phase2/stage2/synth/post_dft_netlist.v"
    put(post, "module t(clk, d, q);\n input clk, d;\n output q;\n" + dff + "endmodule\n")
    report = survival.assess(p)
    if report["post_dft_netlist_dff_count"] == 0:
        pytest.fail("fixture flop not recognised by the shared DFF detector")
    assert report["verdict"] == "FAIL" and report["missing_dft_ports"] == ["shift", "sout"]
    put(post, "module t(clk, d, q, shift, sout);\n input clk, d, shift;\n output q, sout;\n"
        + dff + "endmodule\n")
    assert survival.assess(p)["verdict"] == "PASS"


def test_post_dft_ppa_never_adopts_an_unproven_arm(tmp_path):
    post_dft = importlib.import_module("_ppa.post_dft")
    arms = {}
    for name, area, lec in (("small_unproven", 10.0, "INCONCLUSIVE"), ("large_proven", 20.0, "PASS")):
        report = put(tmp_path / f"{name}.json", {"verdict": "PASS", "scope": {"stage": "post_dft"},
                     "metrics": {"design__instance__area": {"status": "MEASURED", "value": area},
                                 "design__instance__count": {"status": "MEASURED", "value": 5}}})
        arms[name] = tmp_path / f"{name}.admitted.json"
        post_dft.admit(report, {"verdict": "PASS"}, {"verdict": lec, "unproven_points": 0}, arms[name])
    assert post_dft.select(arms, tmp_path / "sel.json")["selection"] == "large_proven"
