"""Pins the wiring of the `signoff` bucket of previously-unreachable checkers.

Every program exercised here already existed, already worked, and was reachable
from NOTHING but its own unit test (or from a sentence of skill prose, which is
not an invocation). This file pins the CHANNEL each one was wired through so it
cannot silently fall out again:

  flow step gate   drc_vacuous_pass_check, lvs_signoff_guard,
  (yaml clause)    lvs_triage_classify (advisory), hold_corner_coverage_check
                   (Steps 20 + 27), gds_topcell_name_check, pdk_consistency_check,
                   sv_compat_check, mixed_signal_top_lvs_run
  runner subproc   l21_to_upf_emit  (phase3_one_shot_runner.step_canonicalize_artefacts)
  CI hygiene lane  flow_step_executor_coverage_check,
                   convergence_doctrine_present_check  (tools/ci/repo_hygiene_gates.sh)
  benchmark        clause_smoke_tb  (benchmark/cvdp_gate.py B2b pre-emit block)

Two kinds of assertion, and they fail for different reasons:
  * WIRING     — the clause / registry entry / call site exists.
  * DISCRIMINATION — the check still FAILs on a bad input THROUGH the new
    channel. A wiring that cannot fail is the same defect one layer up.

Fixtures are synthetic; nothing here needs a PDK, a container or a run dir.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
REPO = PLUGIN.parents[2]
FLOW_YAML = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
HYGIENE_SH = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
CVDP_GATE = PLUGIN / "benchmark" / "cvdp_gate.py"
PHASE3_RUNNER = PROGRAMS / "phase3_one_shot_runner.py"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def flow():
    return yaml.safe_load(FLOW_YAML.read_text())


def _step(flow, step_id):
    for s in flow["steps"]:
        if s.get("id") == step_id:
            return s
    raise AssertionError(f"step {step_id} missing from the flow")


_BLOCKING_SLOTS = ("program_exit_zero", "optional_program_exit_zero")
_ADVISORY_SLOT = "advisory_program_exit_zero"


def _commands(gate, slots):
    """Every command string under `gate` reachable through `slots`."""
    out = []
    if isinstance(gate, dict):
        for key, val in gate.items():
            if key in slots:
                out.append(val["command"] if isinstance(val, dict) else val)
            else:
                out.extend(_commands(val, slots))
    elif isinstance(gate, list):
        for item in gate:
            out.extend(_commands(item, slots))
    return out


def blocking(flow, step_id):
    return _commands(_step(flow, step_id)["gate"], _BLOCKING_SLOTS)


def advisory(flow, step_id):
    return _commands(_step(flow, step_id)["gate"], (_ADVISORY_SLOT,))


def _run(prog, *args):
    r = subprocess.run([sys.executable, str(PROGRAMS / prog), *map(str, args)],
                       capture_output=True, text=True, timeout=300)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ---------------------------------------------------------------------------
# WIRING — flow step gates
# ---------------------------------------------------------------------------
def test_drc_vacuous_pass_check_is_blocking_in_step_31(flow):
    assert any(c.startswith("drc_vacuous_pass_check") for c in blocking(flow, 31)), \
        "Step 31 does not run drc_vacuous_pass_check — a 0-violation DRC " \
        "verdict over an empty layout signs off clean again"


def test_lvs_signoff_guard_is_blocking_in_step_31(flow):
    cmds = [c for c in blocking(flow, 31) if c.startswith("lvs_signoff_guard")]
    assert cmds, "Step 31 does not run lvs_signoff_guard"
    assert all("--project" in c for c in cmds), (
        "a bare --spice leaves --top defaulting to the FIRST .subckt, which "
        "in a hierarchical extraction is a standard cell — the guard would "
        "then PASS a portless design top")


def test_lvs_triage_classify_is_advisory_only(flow):
    """Its `_cli()` ends `return 0` unconditionally — it has NO reachable FAIL
    path, so it must never sit in a slot that can fail a step."""
    assert any(c.startswith("lvs_triage_classify") for c in advisory(flow, 31)), \
        "lvs_triage_classify is not wired into Step 31's advisory slot"
    assert not any(c.startswith("lvs_triage_classify")
                   for c in blocking(flow, 31)), \
        "lvs_triage_classify cannot fail, so it must not be a blocking gate"


def test_hold_corner_coverage_is_wired_unconditionally(flow):
    """Unconditional and --project, for two reasons that both bite: a
    `condition_files_exist` on a hold script is the self-disabling shape
    (no hold analysis at all is the defect the check exists to name), and a
    single named artefact would miss the SECOND hold view a flow emits."""
    gate = _step(flow, 20)["gate"]
    unconditional = _commands(gate, ("program_exit_zero",))
    s20 = [c for c in unconditional
           if c.startswith("hold_corner_coverage_check")]
    assert s20, "Step 20 does not check the hold CORNER unconditionally"
    assert all("--project" in c for c in s20)
    conditional = _commands(gate, ("optional_program_exit_zero",))
    assert not any(c.startswith("hold_corner_coverage_check")
                   for c in conditional), \
        "a conditioned hold-corner gate disables itself in the case it guards"


def test_hold_closure_check_is_preserved(flow):
    """The corner gate ADDS an opinion; it must not have replaced one."""
    assert any(c.startswith("hold_closure_check") for c in blocking(flow, 20))


def test_gds_topcell_name_check_is_blocking_in_step_37(flow):
    cmds = [c for c in blocking(flow, 37)
            if c.startswith("gds_topcell_name_check")]
    assert cmds, "Step 37 does not verify WHICH cell is the GDS top"
    assert all("--project" in c for c in cmds), \
        "the flow gate has no top-name variable — it must use --project"


def test_gds_size_and_substance_gates_are_preserved(flow):
    cmds = blocking(flow, 37)
    assert any(c.startswith("gds_size_check") for c in cmds)
    assert any(c.startswith("gds_substance_check") for c in cmds)


def test_pdk_consistency_check_is_wired_into_synthesis(flow):
    cmds = [c for c in blocking(flow, 9) if c.startswith("pdk_consistency_check")]
    assert cmds, "Step 9 does not check that netlist cells exist in the PDK"
    assert all("--pdk-lib" in c and "--netlist" in c for c in cmds)


def test_sv_compat_check_is_wired_scoped_to_its_defect_rule(flow):
    cmds = [c for c in blocking(flow, 2) if c.startswith("sv_compat_check")]
    assert cmds, "Step 2 does not run sv_compat_check"
    assert all("--fail-on unpacked-ports" in c for c in cmds), (
        "the bare exit code conflates NEEDS_SV (informational, and already "
        "enforced by yosys_script_template_check) with FAIL_UNPACKED_PORTS "
        "(a real Yosys-fatal defect) — gating on it would fail every "
        "SystemVerilog design")


def test_mixed_signal_top_lvs_run_is_wired_before_its_consumer(flow):
    cmds = _commands(_step(flow, "M1")["gate"], _BLOCKING_SLOTS)
    prod = [i for i, c in enumerate(cmds)
            if c.startswith("mixed_signal_top_lvs_run")]
    cons = [i for i, c in enumerate(cmds)
            if c.startswith("mixed_signal_merge_check")]
    assert prod, ("M1 runs mixed_signal_merge_check, whose "
                  "MERGE_NOT_LVS_SUBSTANTIATED rule needs top_lvs.json — "
                  "written by mixed_signal_top_lvs_run and nothing else")
    assert cons, "M1 lost its merge_check gate"
    assert prod[0] < cons[0], "the producer must run before its consumer"


# ---------------------------------------------------------------------------
# WIRING — runner subprocess / CI lane / benchmark harness
# ---------------------------------------------------------------------------
def test_l21_to_upf_emit_is_called_by_the_runner():
    src = PHASE3_RUNNER.read_text()
    assert "l21_to_upf_emit.py" in src, (
        "nothing emits the Step-7 <top>.upf deliverable, so upf_syntax_check "
        "still has no input")
    assert "def step_canonicalize_artefacts" in src
    # …and inside the function that stages the other Step-7 deliverables.
    body = src.split("def step_canonicalize_artefacts", 1)[1]
    head = body.split("\ndef ", 1)[0]
    assert "l21_to_upf_emit.py" in head, \
        "the UPF emit landed outside the Step-7 canonicalisation step"


def test_l21_to_upf_emit_is_not_a_flow_gate(flow):
    """It is a PRODUCER with an rc=2 vacuous path; a single rc=2 sub-gate
    promotes the WHOLE step to VACUOUS_PASS, which would mislabel Step 7 on
    every single-domain design even though its other gates really ran."""
    assert not any(c.startswith("l21_to_upf_emit") for c in blocking(flow, 7))


@pytest.mark.skipif(not HYGIENE_SH.is_file(), reason="repo CI lane absent")
def test_repo_hygiene_lane_runs_the_two_plugin_source_audits():
    sh = HYGIENE_SH.read_text()
    assert "flow_step_executor_coverage_check.py" in sh, (
        "nothing proves every flow step has an executor that can run it")
    assert "--strict" in sh.split("flow_step_executor_coverage_check.py", 1)[1] \
        .split("\n", 1)[0], "without --strict an ORPHANED step cannot go red"
    assert "convergence_doctrine_present_check.py" in sh


@pytest.mark.skipif(not HYGIENE_SH.is_file(), reason="repo CI lane absent")
def test_the_two_wired_checkers_left_the_test_only_baseline():
    baseline = json.loads(
        (PROGRAMS / "checker_execution_wiring_baseline.json").read_text())
    for name in ("flow_step_executor_coverage_check.py",
                 "pdk_consistency_check.py"):
        assert name not in baseline["known"], (
            f"{name} is wired now; leaving it in the test-only register turns "
            f"the register into permission")


def test_clause_smoke_tb_is_wired_into_the_cvdp_pre_emit_gate():
    src = CVDP_GATE.read_text()
    assert "import clause_smoke_tb" in src, \
        "the EXAMPLE-FREE smoke gate (#740 G2) is still imported by nothing"
    assert "def clause_smoke_gate_record" in src
    assert "clause_smoke_gate_record(" in src.split(
        "def clause_smoke_gate_record", 1)[1], \
        "clause_smoke_gate_record is defined but never called"


# ---------------------------------------------------------------------------
# DISCRIMINATION — the checks still FAIL on a bad input
# ---------------------------------------------------------------------------
def test_lvs_signoff_guard_fails_on_a_portless_extraction(tmp_path):
    sp = tmp_path / "top_extracted.sp"
    sp.write_text(".subckt top\nM1 a b c d nfet\n.ends\n")
    rc, out = _run("lvs_signoff_guard.py", "--spice", sp)
    assert rc == 1 and "PORTLESS" in out
    sp.write_text(".subckt top a b vdd vss\nM1 a b vdd vss nfet\n.ends\n")
    rc, _ = _run("lvs_signoff_guard.py", "--spice", sp)
    assert rc == 0
    # the historical bare form still works (no --project) — unchanged.
    rc, _ = _run("lvs_signoff_guard.py", "--spice", sp, "--top", "top")
    assert rc == 0


def test_hold_corner_coverage_fails_when_hold_reads_a_slow_liberty(tmp_path):
    tcl = tmp_path / "hold.tcl"
    tcl.write_text("read_liberty /pdk/lib/stdcell_slow_1p08V_125C.lib\n"
                   "read_spef x.spef\nreport_worst_slack -min -digits 4\n")
    rc, out = _run("hold_corner_coverage_check.py", tcl)
    assert rc == 1 and "HOLD_NOT_AT_FF" in out
    tcl.write_text("read_liberty /pdk/lib/stdcell_fast_1p32V_m40C.lib\n"
                   "read_spef x.spef\nreport_worst_slack -min -digits 4\n")
    rc, _ = _run("hold_corner_coverage_check.py", tcl)
    assert rc == 0


def test_sv_compat_check_fail_on_scopes_the_exit_code(tmp_path):
    rtl, out = tmp_path / "rtl", tmp_path / "out"
    rtl.mkdir()
    # SystemVerilog, but no unpacked-array port: informational, NOT a defect.
    (rtl / "m.v").write_text(
        "module m(input logic a, output logic y);\nalways_comb y = ~a;\n"
        "endmodule\n")
    rc, txt = _run("sv_compat_check.py", "--rtl-dir", rtl, "--out-dir", out,
                   "--fail-on", "unpacked-ports")
    assert rc == 0 and "NEEDS_SV" in txt, \
        "scoped mode must report NEEDS_SV without failing on it"
    rc, _ = _run("sv_compat_check.py", "--rtl-dir", rtl, "--out-dir", out)
    assert rc == 1, "the historical default (--fail-on any) must be unchanged"
    # The Yosys-fatal rule still fails in BOTH modes.
    (rtl / "m.v").write_text("module m(output logic [7:0] foo [0:3]);\n"
                             "endmodule\n")
    for extra in ([], ["--fail-on", "unpacked-ports"]):
        rc, txt = _run("sv_compat_check.py", "--rtl-dir", rtl,
                       "--out-dir", out, *extra)
        assert rc == 1 and "FAIL_UNPACKED_PORTS" in txt


def test_gds_topcell_project_mode_resolves_and_discriminates(tmp_path):
    """A GDS whose top cell is not the DEF's DESIGN name must FAIL, and an
    unresolvable project must be a DISCLOSED skip (rc 2), never a pass."""
    rc, out = _run("gds_topcell_name_check.py", "--project", tmp_path)
    assert rc == 2, out
    assert "no GDS found" in out and "UNRESOLVED" in out, \
        "an unresolvable project must SAY what it could not find"

    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    gdsd = tmp_path / "phase3" / "stage4" / "gds"
    pnr.mkdir(parents=True)
    gdsd.mkdir(parents=True)
    (pnr / "routed.def").write_text("VERSION 5.8 ;\nDESIGN widget ;\nEND DESIGN\n")

    def _rec(rtype, dtype, payload=b""):
        return (4 + len(payload)).to_bytes(2, "big") + bytes([rtype, dtype]) \
            + payload

    def _gds(top):
        name = top.encode() + (b"\0" if len(top) % 2 else b"")
        return (_rec(0x00, 0x02, b"\x00\x05") + _rec(0x05, 0x02, b"\x00" * 24)
                + _rec(0x06, 0x06, name) + _rec(0x07, 0x00)
                + _rec(0x04, 0x00))

    (gdsd / "chip.gds").write_bytes(_gds("widget"))
    rc, out = _run("gds_topcell_name_check.py", "--project", tmp_path)
    assert rc == 0, out
    assert "DESIGN widget" in out

    (gdsd / "chip.gds").write_bytes(_gds("leftover_subcell"))
    rc, out = _run("gds_topcell_name_check.py", "--project", tmp_path)
    assert rc == 1 and "TOPCELL_NAME_MISMATCH" in out


def test_l21_to_upf_emit_produces_the_step7_deliverable(tmp_path):
    """The exact argv the runner now issues. Before this wiring `<top>.upf`
    was produced by nothing, so `upf_syntax_check` had no input in any run."""
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    l21 = gd / "L21_POWER_INTENT.json"
    out_json = tmp_path / "reports" / "phase2" / "gates" / "l21_to_upf_emit.json"

    # single-domain (the pure-digital majority) → disclosed vacuous, rc 2
    l21.write_text('{"power_domains": []}')
    rc, _ = _run("l21_to_upf_emit.py", tmp_path, "--top", "widget",
                 "--json", out_json)
    assert rc == 2
    assert not (tmp_path / "phase2" / "stage2" / "constraints"
                / "widget.upf").exists()

    # multi-domain → the deliverable is rendered AND self-validated
    l21.write_text(json.dumps({
        "power_domains": [{"name": "PD_CORE", "supply": "VDD",
                           "retention": True},
                          {"name": "PD_IO", "supply": "VDDIO"}],
        "isolation": [{"domain": "PD_CORE", "clamp": "0"}],
        "level_shifters": [{"name": "LS0", "domain": "PD_IO"}],
    }))
    rc, out = _run("l21_to_upf_emit.py", tmp_path, "--top", "widget",
                   "--json", out_json)
    assert rc == 0, out
    upf = tmp_path / "phase2" / "stage2" / "constraints" / "widget.upf"
    assert upf.is_file(), "the Step-7 <top>.upf deliverable was not emitted"
    body = upf.read_text()
    assert "create_power_domain" in body and "set_design_top widget" in body
    assert json.loads(out_json.read_text())["self_check"].endswith("rc=0")


def test_convergence_doctrine_check_fails_when_the_doctrine_is_stripped(tmp_path):
    skill = PLUGIN / "skills" / "benchmark-enhancement-capture" / "SKILL.md"
    rc, out = _run("convergence_doctrine_present_check.py", "--skill", skill)
    assert rc == 0
    assert "required doctrine marker(s) present" in out, \
        "a PASS must disclose its denominator (vibe-ic#447)"
    stripped = tmp_path / "SKILL.md"
    stripped.write_text("# benchmark-enhancement-capture\n\nnothing here.\n")
    rc, out = _run("convergence_doctrine_present_check.py", "--skill", stripped)
    assert rc == 1 and "MISSING" in out


def test_flow_step_executor_coverage_is_strict_capable():
    rc, out = _run("flow_step_executor_coverage_check.py", "--strict")
    assert rc == 0, out
    assert "ORPHANED=0" in out, \
        "an ORPHANED step is now red in CI — wire an executor for it"


def test_mixed_signal_merge_check_fails_without_the_producers_artefact(tmp_path):
    """The reason the producer had to be wired: the consumer's substance rule
    is unsatisfiable without it."""
    (tmp_path / "phase3" / "mixed_signal").mkdir(parents=True)
    (tmp_path / "phase3" / "mixed_signal" / "top_merged.gds").write_bytes(
        b"\x00" * 4096)
    (tmp_path / "phase1" / "analog").mkdir(parents=True)
    (tmp_path / "phase1" / "analog" / "analog_block_list.json").write_text(
        '{"blocks": [{"name": "b0"}]}')
    rc, out = _run("mixed_signal_merge_check.py", tmp_path)
    assert rc == 1, out


def test_drc_vacuous_pass_check_flags_a_zero_count_over_no_geometry(tmp_path):
    log = tmp_path / "drc.rpt"
    log.write_text("magic drc\nTotal errors: 0\n")
    rc, out = _run("drc_vacuous_pass_check.py", log)
    assert rc == 1, out
    assert "INCONCLUSIVE" in out or "VACUOUS" in out


# ---------------------------------------------------------------------------
# DISCRIMINATION *THROUGH THE GATE MACHINERY* — the yaml command strings are
# executed by flow_compliance_check's own resolver, with its own exit-code
# semantics (rc 0 PASS / rc 2 VACUOUS / rc 1 FAIL). A wiring that only passes
# a hand-written command line proves nothing about the clause that shipped.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def fcc():
    sys.path.insert(0, str(PROGRAMS))
    import flow_compliance_check as m  # noqa: E402
    return m


def _yaml_cmd(flow, step_id, prefix):
    cmds = [c for c in blocking(flow, step_id) if c.startswith(prefix)]
    assert cmds, f"no {prefix} clause on step {step_id}"
    return cmds[0]


def test_step_37_topcell_clause_fails_a_mismatched_gds(fcc, flow, tmp_path):
    cmd = _yaml_cmd(flow, 37, "gds_topcell_name_check")
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    gdsd = tmp_path / "phase3" / "stage4" / "gds"
    pnr.mkdir(parents=True)
    gdsd.mkdir(parents=True)
    (pnr / "routed.def").write_text("VERSION 5.8 ;\nDESIGN widget ;\nEND DESIGN\n")

    def _rec(rt, dt, payload=b""):
        return (4 + len(payload)).to_bytes(2, "big") + bytes([rt, dt]) + payload

    def _gds(top):
        nm = top.encode() + (b"\0" if len(top) % 2 else b"")
        return (_rec(0x00, 0x02, b"\x00\x05") + _rec(0x05, 0x02, b"\x00" * 24)
                + _rec(0x06, 0x06, nm) + _rec(0x07, 0x00) + _rec(0x04, 0x00))

    (gdsd / "chip.gds").write_bytes(_gds("widget"))
    ok, _ = fcc._check_program_exit_zero(tmp_path, cmd)
    assert ok, "the shipped Step-37 clause must PASS a matching GDS"

    (gdsd / "chip.gds").write_bytes(_gds("leftover_subcell"))
    ok, out = fcc._check_program_exit_zero(tmp_path, cmd)
    assert not ok, "the shipped Step-37 clause did not fail a mismatched top"
    assert "MISMATCH" in out or "mismatch" in out.lower()


def test_step_31_lvs_guard_clause_judges_the_DESIGN_top_not_a_leaf_cell(
        fcc, flow, tmp_path):
    """The regression this pins was MEASURED on a real sign-off run: with a
    bare `--spice` the guard read the FIRST .subckt (a 2-port standard cell)
    of a design whose top has 38 ports — so a PORTLESS top would have passed."""
    cmd = _yaml_cmd(flow, 31, "lvs_signoff_guard")
    ext = tmp_path / "phase3" / "stage3" / "extracted"
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    ext.mkdir(parents=True)
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text("VERSION 5.8 ;\nDESIGN widget ;\nEND DESIGN\n")
    sp = ext / "widget_extracted.sp"
    # a ported LEAF CELL first, a PORTLESS design top second — the shape the
    # bare form got wrong.
    sp.write_text(".subckt inv_1 a y vdd vss\nM1 a y vdd vss nfet\n.ends\n"
                  ".subckt widget\nX1 n1 n2 vdd vss inv_1\n.ends\n")
    ok, out = fcc._check_program_exit_zero(tmp_path, cmd)
    assert not ok, "the clause passed a PORTLESS design top (it read a leaf)"
    assert "Refuse to sign off" in out, out
    sp.write_text(".subckt inv_1 a y vdd vss\nM1 a y vdd vss nfet\n.ends\n"
                  ".subckt widget in out vdd vss\nX1 in out vdd vss inv_1\n"
                  ".ends\n")
    ok, out = fcc._check_program_exit_zero(tmp_path, cmd)
    assert ok, out
    assert "`widget`" in out, out


def test_lvs_guard_project_mode_skips_loudly_when_unresolvable(tmp_path):
    ext = tmp_path / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True)
    (ext / "widget_extracted.sp").write_text(".subckt widget a\n.ends\n")
    rc, out = _run("lvs_signoff_guard.py", "--project", tmp_path)
    assert rc == 2, out          # no DEF → no expected top
    assert "NOT a pass" in out


def test_step_20_hold_clause_fails_when_ANY_hold_view_is_slow_fed(fcc, flow,
                                                                  tmp_path):
    """The measured shape on the real run: the multi-corner OCV hold script is
    FF-fed and PASSes, while the SI-MCF hold re-run beside it is SS-fed. One of
    two being right must not be enough."""
    cmd = _yaml_cmd(flow, 20, "hold_corner_coverage_check")
    sta = tmp_path / "phase3" / "stage3" / "sta"
    mcf = tmp_path / "phase3" / "stage3" / "extracted" / "si_mcf"
    sta.mkdir(parents=True)
    mcf.mkdir(parents=True)

    # nothing produced yet → DISCLOSED skip, never a silent pass
    ok, out = fcc._check_program_exit_zero(tmp_path, cmd)
    assert ok and out.startswith(fcc._VACUOUS_HINT_PREFIX), out

    good = ("read_liberty /pdk/lib/cell_fast_1p32V_m40C.lib\n"
            "read_spef x.spef\nreport_worst_slack -min -digits 4\n")
    bad = ("read_liberty /pdk/lib/cell_slow_1p08V_125C.lib\n"
           "read_spef x.spef\nreport_worst_slack -min -digits 4\n")
    (sta / "sta_mcorner_ocv_hold.tcl").write_text(good)
    ok, out = fcc._check_program_exit_zero(tmp_path, cmd)
    assert ok, out

    (mcf / "si_mcf_sta_mcf_hold.tcl").write_text(bad)
    ok, out = fcc._check_program_exit_zero(tmp_path, cmd)
    assert not ok, "an SS-fed second hold view passed the Step-20 gate"
    assert "si_mcf_sta_mcf_hold.tcl" in out, out


def test_hold_corner_gate_carries_no_self_disabling_condition():
    """The repo's own guard on the shape; run here so this file's wirings are
    judged by it directly rather than only by the whole-flow CI gate."""
    rc, out = _run("flow_condition_reachability_check.py")
    assert rc == 0, out


def test_step_2_sv_compat_clause_fails_an_unpacked_array_port(fcc, flow,
                                                             tmp_path):
    cmd = _yaml_cmd(flow, 2, "sv_compat_check")
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "m.v").write_text("module m(output logic [7:0] foo [0:3]);\n"
                             "endmodule\n")
    ok, out = fcc._check_program_exit_zero(tmp_path, cmd)
    assert not ok, "the shipped Step-2 clause did not fail an unpacked port"
    assert "unpacked-array port" in out, out
    # …and a SystemVerilog design with no unpacked port must stay green.
    (rtl / "m.v").write_text("module m(input logic a, output logic y);\n"
                             "always_comb y = ~a;\nendmodule\n")
    ok, out = fcc._check_program_exit_zero(tmp_path, cmd)
    assert ok, f"the clause blocked a clean SystemVerilog design: {out}"


def test_step_31_drc_vacuous_clause_is_a_disclosed_skip_before_layout(
        fcc, flow, tmp_path):
    """rc=2 must reach the VACUOUS_PASS tier, not a bare PASS: 'no layout yet'
    and 'the layout was checked and is clean' must not print the same."""
    cmd = _yaml_cmd(flow, 31, "drc_vacuous_pass_check")
    ok, out = fcc._check_program_exit_zero(tmp_path, cmd)
    assert ok
    assert out.startswith(fcc._VACUOUS_HINT_PREFIX), out
