#!/usr/bin/env python3
"""wire/misc — the nine checks that existed, worked, and ran NOWHERE.

Each of these programs shipped with its own passing unit tests and (mostly)
its own SKILL paragraph saying it was "enforced deterministically", while no
machine path ever invoked it. A unit test that only proves the ALGORITHM is
what let that happen: the algorithm was never the doubtful part.

So every test here is PAIRED. One half pins the WIRING — the exact clause in
`flow/phase1_phase2_phase3.yaml`, or the exact entry in
`flow_compliance_check._STRUCTURAL_RTL_GATES`, or the exact subprocess in
`_run_yosys_gates` — so it cannot silently fall back out. The other half
drives a BAD input through that same channel and asserts the channel carries
the verdict, so the clause cannot rot into a decoration that runs a program
whose result is discarded.

Severities are asserted too, and deliberately differ:
  * blocking  — l_doc_todo_stub_count_check, foundry_signoff_plan_check,
                pnr_timing_repair_completeness_check, waiver_growth_check,
                reported_figure_artifact_backing_check, fpga_led_probe_lint,
                yosys_tiecell_recipe_order_check
  * advisory  — l_doc_cross_consistency_check, agent_report_presence_check
An advisory gate that quietly became blocking (or a blocking one that quietly
became advisory) is the regression these assertions exist to catch.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
_FLOW_YAML = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
_flow = importlib.util.module_from_spec(_spec)
sys.modules["flow_compliance_check"] = _flow
_spec.loader.exec_module(_flow)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _steps() -> dict:
    doc = yaml.safe_load(_FLOW_YAML.read_text())
    return {str(s["id"]): s for s in doc["steps"]}


def _subgates(step: dict) -> list:
    gate = step["gate"]
    return gate["all_of"] if "all_of" in gate else [gate]


def _commands(step: dict, slot: str) -> list[str]:
    """Every command string wired into `step` under gate key `slot`."""
    out = []
    for sub in _subgates(step):
        if not isinstance(sub, dict) or slot not in sub:
            continue
        spec = sub[slot]
        out.append(spec if isinstance(spec, str) else spec.get("command", ""))
    return out


def _cond_files(step: dict, slot: str, stem: str) -> list[str]:
    for sub in _subgates(step):
        if not isinstance(sub, dict) or slot not in sub:
            continue
        spec = sub[slot]
        if isinstance(spec, dict) and spec.get("command", "").startswith(stem):
            return spec.get("condition_files_exist", [])
    return []


def _run_gate_as_umbrella(gate_name: str, project: Path):
    """Invoke a gate EXACTLY as `_run_structural_rtl_gates` does."""
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / f"{gate_name}.py"), str(project)],
        cwd=project, capture_output=True, text=True, timeout=120)


def _rtl(project: Path) -> None:
    """Minimum RTL so the P0 umbrella runs at all (it self-skips otherwise)."""
    d = project / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    (d / "dut.v").write_text("module dut(input clk); endmodule\n")


# ===========================================================================
# Channel (a) — step gate clauses in flow/phase1_phase2_phase3.yaml
# ===========================================================================
def test_d1_wires_todo_stub_count_as_blocking():
    """BLOCKING: a `__TODO__` stub in an L doc is a half-extracted spec."""
    d1 = _steps()["D1"]
    assert any(c.startswith("l_doc_todo_stub_count_check")
               for c in _commands(d1, "program_exit_zero")), \
        "l_doc_todo_stub_count_check dropped out of step D1's blocking slot"
    # and it must NOT have been demoted into the advisory slot
    assert not any(c.startswith("l_doc_todo_stub_count_check")
                   for c in _commands(d1, "advisory_program_exit_zero"))


def test_d1_wires_cross_consistency_as_advisory():
    """ADVISORY: it FAILs 7/8 published cells on a producer-side L1 defect."""
    d1 = _steps()["D1"]
    assert any(c.startswith("l_doc_cross_consistency_check")
               for c in _commands(d1, "advisory_program_exit_zero")), \
        "l_doc_cross_consistency_check dropped out of step D1's advisory slot"
    assert not any(c.startswith("l_doc_cross_consistency_check")
                   for c in _commands(d1, "program_exit_zero")), \
        "l_doc_cross_consistency_check was promoted to blocking without a " \
        "re-measurement — it fails ~90% of real runs today"


def test_step17_wires_pnr_timing_repair_completeness():
    s17 = _steps()["17"]
    cmds = _commands(s17, "optional_program_exit_zero")
    assert any(c.startswith("pnr_timing_repair_completeness_check")
               for c in cmds), \
        "pnr_timing_repair_completeness_check dropped out of step 17"
    assert _cond_files(s17, "optional_program_exit_zero",
                       "pnr_timing_repair_completeness_check") == \
        ["phase3/stage3/pnr/pnr.tcl"]


def test_step36_wires_agent_report_presence_as_advisory():
    s36 = _steps()["36"]
    assert any(c.startswith("agent_report_presence_check")
               for c in _commands(s36, "advisory_program_exit_zero")), \
        "agent_report_presence_check dropped out of step 36's advisory slot"
    # the pre-existing blocking sign-off gate must survive the all_of rewrite
    assert any(c.startswith("tapeout_signoff_check")
               for c in _commands(s36, "program_exit_zero"))
    assert not any(c.startswith("agent_report_presence_check")
                   for c in _commands(s36, "program_exit_zero")), \
        "agent_report_presence_check was promoted to blocking — it fails " \
        "9/9 real projects because it accepts only AGENT_REPORT.md while " \
        "the flow's canonical report is reports/final_summary.md"


def test_step38_wires_foundry_signoff_plan_as_blocking():
    s38 = _steps()["38"]
    assert any(c.startswith("foundry_signoff_plan_check")
               for c in _commands(s38, "optional_program_exit_zero")), \
        "foundry_signoff_plan_check dropped out of step 38"
    assert _cond_files(s38, "optional_program_exit_zero",
                       "foundry_signoff_plan_check") == ["waivers.json"]
    assert any(c.startswith("foundry_handoff_package_check")
               for c in _commands(s38, "program_exit_zero"))


# ---- and the clauses actually carry a verdict -----------------------------
def test_d1_todo_stub_clause_fails_a_stubbed_l_doc(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"part": "__TODO__"}))
    d1 = _steps()["D1"]
    clause = next(sub for sub in _subgates(d1)
                  if isinstance(sub, dict)
                  and str(sub.get("program_exit_zero", "")).startswith(
                      "l_doc_todo_stub_count_check"))
    passed, reasons = _flow._evaluate_gate(tmp_path, clause)
    assert passed is False, reasons
    assert any("l_doc_todo_stub_count_check" in r for r in reasons)


def test_d1_cross_consistency_clause_records_but_never_blocks(tmp_path):
    """Paired: it must RUN and RECORD, and must NOT change the verdict."""
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps(
        {"pin_table": [{"name": "sclk"}, {"name": "sdata"}]}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"ports": []}))
    d1 = _steps()["D1"]
    clause = next(sub for sub in _subgates(d1)
                  if isinstance(sub, dict)
                  and str(sub.get("advisory_program_exit_zero", "")).startswith(
                      "l_doc_cross_consistency_check"))
    passed, reasons = _flow._evaluate_gate(tmp_path, clause)
    assert passed is True, "advisory gate must never block"
    assert any("l_doc_cross_consistency_check" in r for r in reasons), \
        "advisory gate ran but recorded nothing — indistinguishable from " \
        "not being wired at all"


def test_step38_foundry_plan_clause_fails_a_waivered_project_with_no_plan(
        tmp_path):
    (tmp_path / "waivers.json").write_text(json.dumps(
        {"waived_steps": [{"id": 31, "reason": "deferred to foundry"}]}))
    s38 = _steps()["38"]
    clause = next(sub for sub in _subgates(s38)
                  if isinstance(sub, dict)
                  and "optional_program_exit_zero" in sub
                  and sub["optional_program_exit_zero"]["command"].startswith(
                      "foundry_signoff_plan_check"))
    passed, reasons = _flow._evaluate_gate(tmp_path, clause)
    assert passed is False, reasons
    assert any("foundry_signoff_plan_check" in r for r in reasons)


def test_step38_foundry_plan_clause_is_silent_without_waivers(tmp_path):
    """The condition must keep a waiver-free project untouched."""
    s38 = _steps()["38"]
    clause = next(sub for sub in _subgates(s38)
                  if isinstance(sub, dict)
                  and "optional_program_exit_zero" in sub
                  and sub["optional_program_exit_zero"]["command"].startswith(
                      "foundry_signoff_plan_check"))
    passed, reasons = _flow._evaluate_gate(tmp_path, clause)
    assert passed is True and reasons == []


def test_step17_pnr_clause_fails_a_hold_only_script(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    # The silicon-DOA shape: hold repaired, setup never.
    pnr.joinpath("pnr.tcl").write_text(
        "read_lef tech.lef\n"
        "global_placement\n"
        "detailed_placement\n"
        "clock_tree_synthesis\n"
        "repair_timing -hold\n"
        "global_route\n"
        "detailed_route\n")
    s17 = _steps()["17"]
    clause = next(sub for sub in _subgates(s17)
                  if isinstance(sub, dict)
                  and "optional_program_exit_zero" in sub
                  and sub["optional_program_exit_zero"]["command"].startswith(
                      "pnr_timing_repair_completeness_check"))
    passed, reasons = _flow._evaluate_gate(tmp_path, clause)
    assert passed is False, reasons
    assert any("pnr_timing_repair_completeness_check" in r for r in reasons)


def test_step36_all_of_rewrite_preserves_the_pass_with_waivers_tier(
        tmp_path, monkeypatch):
    """Step 36 was a BARE `program_exit_zero` before the advisory slot was
    added; `tapeout_signoff_check` signals PASS_WITH_WAIVERS by exit code 3,
    which `check_step` promotes to WAIVED-DEFERRED. Wrapping the step in an
    `all_of` must not swallow that hint — a DRC-waived tapeout silently
    collapsing onto a bare PASS is exactly the substitution #651 forbids.
    """
    monkeypatch.setattr(
        _flow, "_check_program_exit_zero",
        lambda p, c: (True, _flow._WAIVER_HINT_PREFIX + c))
    passed, reasons = _flow._evaluate_gate(tmp_path, _steps()["36"]["gate"])
    assert passed is True
    assert any(r.startswith(_flow._WAIVER_HINT_PREFIX)
               and "tapeout_signoff_check" in r for r in reasons), reasons


def test_step36_agent_report_clause_records_but_never_blocks(tmp_path):
    s36 = _steps()["36"]
    clause = next(sub for sub in _subgates(s36)
                  if isinstance(sub, dict)
                  and "advisory_program_exit_zero" in sub)
    passed, reasons = _flow._evaluate_gate(tmp_path, clause)
    assert passed is True, "advisory gate must never block"
    assert any("agent_report_presence_check" in r for r in reasons)


# ===========================================================================
# Channel (b) — the P0 structural umbrella registry
# ===========================================================================
@pytest.mark.parametrize("gate", [
    "waiver_growth_check",
    "reported_figure_artifact_backing_check",
    "fpga_led_probe_lint",
])
def test_gate_is_registered_in_the_p0_umbrella(gate):
    assert gate in _flow._STRUCTURAL_RTL_GATES, \
        f"{gate} fell out of _STRUCTURAL_RTL_GATES — it then runs nowhere"


def test_p0_umbrella_reports_the_three_new_gates_failing(tmp_path):
    """One fixture, three real defects, driven through the real umbrella.

    Asserting on `_run_structural_rtl_gates`' own fail list (not on the
    programs directly) is the point: it proves the registry entry is
    reachable, invoked with the argv the umbrella actually uses, and that
    its non-zero exit reaches the verdict.
    """
    _rtl(tmp_path)
    # (1) waiver growth with no baseline and no growth_rationale
    (tmp_path / "waivers.json").write_text(json.dumps(
        {"waived_steps": [{"id": 31, "reason": "deferred"},
                          {"id": 32, "reason": "deferred"}]}))
    # (2) a published figure with nothing on disk behind it
    (tmp_path / "RESULT.md").write_text(
        "# RESULT\n\nFinal GDS is 4,242,424 bytes.\n")
    # (3) a 1-cycle pulse wired straight to an LED
    (tmp_path / "phase2" / "stage1" / "rtl" / "fpga_top.v").write_text(
        "// LED PROBE TABLE\n"
        "module fpga_top(input CLK_50M, output [9:0] LEDR);\n"
        "    wire tx_done_pulse;\n"
        "    assign LEDR[9] = tx_done_pulse;\n"
        "endmodule\n")

    passed, fails, _skips, _waivers = _flow._run_structural_rtl_gates(tmp_path)
    assert passed is False
    joined = "\n".join(fails)
    for gate in ("waiver_growth_check",
                 "reported_figure_artifact_backing_check",
                 "fpga_led_probe_lint"):
        assert gate in joined, \
            f"{gate} is registered but its FAIL never reached the umbrella " \
            f"verdict. Fails were:\n{joined}"


def test_p0_umbrella_new_gates_are_quiet_on_a_clean_project(tmp_path):
    """The other half: a project with no waivers, no report and no LED
    probes must not be reddened by any of the three."""
    _rtl(tmp_path)
    for gate in ("waiver_growth_check",
                 "reported_figure_artifact_backing_check",
                 "fpga_led_probe_lint"):
        r = _run_gate_as_umbrella(gate, tmp_path)
        assert r.returncode in (0, 2), \
            f"{gate} fired on a clean fixture: {r.stdout}\n{r.stderr}"


# ===========================================================================
# Channel (b) — the in-process Step-14 pre-PnR Yosys auditor gate
# ===========================================================================
_MISORDERED_YS = (
    "read_verilog -sv rtl/dut.v\n"
    "synth -top dut\n"
    "dfflibmap -liberty pdk.lib\n"
    "abc -liberty pdk.lib\n"
    "techmap\n"
    "hilomap -hicell TIEHI Y -locell TIELO Y\n"
    "opt_clean\n"                     # RULE 2: strips the tie cells
    "write_verilog netlist.v\n"
)
_ORDERED_YS = (
    "read_verilog -sv rtl/dut.v\n"
    "synth -top dut -flatten\n"
    "dfflibmap -liberty pdk.lib\n"
    "abc -liberty pdk.lib\n"
    "techmap\n"
    "setundef -zero\n"
    "hilomap -hicell TIEHI Y -locell TIELO Y\n"
    "splitnets\n"
    "clean\n"
    "write_verilog netlist.v\n"
)


def test_run_yosys_gates_invokes_the_tiecell_order_check():
    src = (_PROGRAMS / "flow_compliance_check.py").read_text()
    start = src.index("def _run_yosys_gates")
    body = src[start:src.index("\ndef ", start + 10)]
    assert "yosys_tiecell_recipe_order_check.py" in body, \
        "_run_yosys_gates stopped invoking yosys_tiecell_recipe_order_check"
    assert "--ys-file" in body


def test_step14_yosys_gate_fails_a_misordered_tiecell_recipe(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "synth.ys").write_text(_MISORDERED_YS)
    passed, reasons = _flow._run_yosys_gates(tmp_path)
    assert passed is False
    assert any("yosys_tiecell_recipe_order_check" in r for r in reasons), \
        f"the tie-cell ordering FAIL never reached Step 14: {reasons}"


def test_step14_yosys_gate_accepts_the_ordered_recipe(tmp_path):
    """Paired: the conformant recipe must not be reddened by the new check."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "synth.ys").write_text(_ORDERED_YS)
    _passed, reasons = _flow._run_yosys_gates(tmp_path)
    assert not any("yosys_tiecell_recipe_order_check" in r for r in reasons), \
        f"tie-cell check fired on a conformant recipe: {reasons}"


# ===========================================================================
# The wiring register must record the paydown, not keep standing permission
# ===========================================================================
def test_wiring_baseline_no_longer_excuses_the_two_paid_down_checkers():
    doc = json.loads(
        (_PROGRAMS / "checker_execution_wiring_baseline.json").read_text())
    for name in ("waiver_growth_check.py",
                 "reported_figure_artifact_backing_check.py"):
        assert name not in doc["known"], \
            f"{name} is wired now; leaving it in the #381 register turns a " \
            f"record of debt into standing permission"
        assert name not in doc["triage"]
