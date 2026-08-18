"""test_dft_foundry_depth.py — DFT-depth raise to a foundry / ATE bar.

Pins the 2026-07 DFT-depth work across four programs:

  1. fault_atpg_run.py         — foundry-grade stuck-at default (95 %) +
                                 transition (at-speed) fault model, honest
                                 engine-limited reporting (no fake number).
  2. dft_atpg_coverage_check.py— foundry floor clamps a lenient written
                                 target UP; below the floor a design FAILs.
  3. bsdl_emit.py              — BSDL + boundary-scan-cell-per-pad plan;
                                 padded → PASS, bare core / no ports → N/A,
                                 padded-missing-parse → FAIL.
  4. dft_signoff_check.py      — aggregate PASS iff stuck-at PASS AND
                                 transition (PASS | documented engine-limited)
                                 AND BSDL (PASS | bare-core SKIP). §4.05:
                                 absent evidence FAILs, never a vacuous pass.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import fault_atpg_run as far          # noqa: E402
import dft_atpg_coverage_check as sac  # noqa: E402
import bsdl_emit as bsdl              # noqa: E402
import dft_signoff_check as sign      # noqa: E402


def _run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG_DIR / script), *args],
        capture_output=True, text=True)


# ════════════════════════════════════════════════════════════════════════
# 1. fault_atpg_run — foundry default + transition fault model
# ════════════════════════════════════════════════════════════════════════

def test_foundry_stuck_at_default_is_95():
    """The producer's default stuck-at target is the foundry bar, not 80 %."""
    assert far.FOUNDRY_STUCK_AT_DEFAULT >= 95.0
    # default surfaces in the CLI
    r = _run("fault_atpg_run.py", "--help")
    assert r.returncode == 0
    assert "FOUNDRY-GRADE" in r.stdout or "foundry" in r.stdout.lower()


def test_transition_report_unsupported_is_engine_limited_not_fake():
    r = far.build_transition_report(
        supported=False, reason="Fault is stuck-at only",
        transition_target=90.0, plan_rel="p.md")
    assert r["fault_model"] == "transition"
    assert r["supported"] is False
    assert r["engine_limited"] is True
    assert r["coverage_pct"] is None        # NEVER fabricated
    assert r["ge_target"] is None
    assert r["target_pct"] == 90.0
    assert "stuck-at only" in r["reason"]


def test_transition_report_supported_computes_verdict():
    ok = far.build_transition_report(True, "ok", 90.0, "p.md", measured_pct=93.0)
    assert ok["engine_limited"] is False and ok["ge_target"] is True
    lo = far.build_transition_report(True, "ok", 90.0, "p.md", measured_pct=80.0)
    assert lo["engine_limited"] is False and lo["ge_target"] is False


def test_run_transition_writes_plan_and_engine_limited(tmp_path):
    """Injected probe reports no support → plan file is written and the block
    is engine_limited with a documented reason (no docker needed)."""
    rep = far.run_transition_atpg(
        tmp_path, cut_rel="phase2/stage2/dft/cut.v",
        cell_model="cells.v", clock="clk", transition_target=90.0,
        probe_fn=lambda project, pdk_dir: (False, "no transition flag"))
    assert rep["engine_limited"] is True
    assert rep["coverage_pct"] is None
    plan = tmp_path / "phase2" / "stage2" / "dft" / "transition_atpg_plan.md"
    assert plan.is_file()
    body = plan.read_text()
    assert "launch-off-capture" in body.lower()
    assert "Supported     : False" in body


def test_probe_no_docker_treated_unsupported_not_faked(tmp_path):
    """When the engine/docker cannot be probed, capability is UNKNOWN and
    treated as unsupported — never assumed-supported with a fake number."""
    # No docker image present in CI; the real probe returns (False, reason).
    supported, reason = far._fault_supports_transition(tmp_path)
    assert supported is False
    assert reason  # documented


# ════════════════════════════════════════════════════════════════════════
# 2. dft_atpg_coverage_check — foundry floor
# ════════════════════════════════════════════════════════════════════════

def test_floor_clamps_lenient_target_up_pass():
    """96 % measured vs a lenient written 55 % → effective 95 % → PASS."""
    e = sac.evaluate({"coverage_pct": 96.0, "target_pct": 55.0}, None)
    assert e["verdict"] == "PASS"
    assert e["effective_target_pct"] == 95.0
    assert e["foundry_floor_governs"] is True


def test_floor_fails_sub_foundry_number():
    """85 % measured with a lenient 55 % written target FAILs the foundry
    floor — the exact loophole this raise closes."""
    e = sac.evaluate({"coverage_pct": 85.0, "target_pct": 55.0,
                      "stuck_at_ge_target": True}, None)
    assert e["verdict"] == "FAIL"
    assert e["effective_target_pct"] == 95.0
    assert any("below the required foundry floor" in r
               or "foundry floor" in r for r in e["reasons"])


def test_written_target_above_floor_governs():
    """A stricter written target (98 %) is NOT lowered to the floor."""
    e = sac.evaluate({"coverage_pct": 96.0, "target_pct": 98.0}, None)
    assert e["verdict"] == "FAIL"          # 96 < 98
    assert e["effective_target_pct"] == 98.0
    assert e["foundry_floor_governs"] is False
    ok = sac.evaluate({"coverage_pct": 99.0, "target_pct": 98.0}, None)
    assert ok["verdict"] == "PASS"


def test_default_cli_enforces_95(tmp_path):
    d = tmp_path / "reports" / "phase2" / "dft"
    d.mkdir(parents=True)
    (d / "coverage.json").write_text(json.dumps(
        {"coverage_pct": 90.0, "target_pct": 80.0, "stuck_at_ge_target": True}))
    # default floor 95 → 90 < 95 → FAIL
    assert sac.main([str(tmp_path)]) == 1
    # raise the floor even higher
    assert sac.main([str(tmp_path), "--foundry-floor", "98"]) == 1
    # explicit low floor isolates the recompute (90 >= 80)
    assert sac.main([str(tmp_path), "--foundry-floor", "0"]) == 0


def test_floor_never_invents_a_target_on_missing_data(tmp_path):
    """A missing written target is still an insufficient-substance FAIL — the
    floor RAISES the bar but never fabricates a target to make a run pass."""
    d = tmp_path / "reports" / "phase2" / "dft"
    d.mkdir(parents=True)
    (d / "coverage.json").write_text(json.dumps({"coverage_pct": 99.0}))
    rep = sac.audit(tmp_path)
    assert rep["verdict"] == "FAIL"
    assert any("no stuck-at coverage target" in r for r in rep["reasons"])


# ════════════════════════════════════════════════════════════════════════
# 3. bsdl_emit — BSDL + boundary-scan-cell-per-pad
# ════════════════════════════════════════════════════════════════════════

_PADDED_NETLIST = """\
module chip_top (
  input  wire        TCK,
  input  wire        TMS,
  input  wire        TDI,
  output wire        TDO,
  input  wire        TRST,
  input  wire        clk_i,
  input  wire [3:0]  gpio_in,
  output wire [1:0]  led_o,
  inout  wire        sda,
  input  wire        VDD,
  input  wire        VSS
);
endmodule
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_bsdl_padded_emits_bsdl_and_plan(tmp_path):
    _write(tmp_path, "net.v", _PADDED_NETLIST)
    plan = bsdl.emit(tmp_path, "net.v", top=None, mode="auto", ir_length=4)
    assert plan["verdict"] == "PASS"
    assert plan["padded"] is True
    # clk_i(1)+gpio_in(4)+led_o(2)+sda(inout=3) = 10 cells; rst absent here
    assert plan["boundary_length"] == 10
    assert plan["tap_present"] is True     # TCK/TMS/TDI/TDO present
    # TAP + supply pins are NOT in the boundary register
    for pin in plan["boundary_scan_pins"]:
        assert pin.lower() not in ("tck", "tms", "tdi", "tdo", "trst",
                                   "vdd", "vss")
    # the BSDL file exists and is 1149.1-shaped
    bsdl_txt = Path(plan["bsdl_file"]).read_text()
    assert "entity chip_top is" in bsdl_txt
    assert "BOUNDARY_LENGTH of chip_top : entity is 10" in bsdl_txt
    assert "INSTRUCTION_OPCODE" in bsdl_txt and "BYPASS (1111)" in bsdl_txt


def test_bsdl_inout_pad_gets_three_cells(tmp_path):
    _write(tmp_path, "net.v", _PADDED_NETLIST)
    plan = bsdl.emit(tmp_path, "net.v", top=None, mode="auto", ir_length=4)
    funcs = [c["function"] for c in plan["boundary_register"]
             if c["port"] == "sda" or c["function"] == "control"]
    # inout → input observe + control + output3 driver
    assert "input" in funcs and "control" in funcs and "output3" in funcs


def test_bsdl_bare_core_is_na(tmp_path):
    _write(tmp_path, "core.v",
           "module core (input clk, input [7:0] d, output [7:0] q);\n"
           "  assign q = d;\nendmodule\n")
    plan = bsdl.emit(tmp_path, "core.v", top=None, mode="auto", ir_length=4)
    assert plan["verdict"] == "N_A"
    assert plan["padded"] is False
    assert plan["boundary_length"] == 0
    assert plan["bsdl_present"] is False


def test_bsdl_no_ports_is_na(tmp_path):
    _write(tmp_path, "tb.v",
           "module tb_top;\n reg clk;\n core u(.clk(clk));\nendmodule\n"
           "module core(input clk); endmodule\n")
    plan = bsdl.emit(tmp_path, "tb.v", top="tb_top", mode="auto", ir_length=4)
    assert plan["verdict"] == "N_A"
    assert plan["classification"] == "EMPTY"


def test_bsdl_pad_cells_force_padded(tmp_path):
    _write(tmp_path, "ring.v",
           "module chip (input clk, output data, input TCK, input TMS,\n"
           "             input TDI, output TDO);\n"
           "  gf180mcu_fd_io__in_c pad0 (.PAD(clk));\n"
           "  sky130_fd_io__top_gpiov2 pad1 (.PAD(data));\n"
           "endmodule\n")
    plan = bsdl.emit(tmp_path, "ring.v", top=None, mode="auto", ir_length=4)
    assert plan["classification"] == "PADDED"
    assert plan["verdict"] == "PASS"
    assert plan["pad_cells_detected"]


def test_bsdl_force_padded_and_force_bare(tmp_path):
    _write(tmp_path, "core.v",
           "module core (input clk, input [3:0] d, output [3:0] q);\n"
           "endmodule\n")
    padded = bsdl.emit(tmp_path, "core.v", top=None, mode="padded", ir_length=4)
    assert padded["verdict"] == "PASS" and padded["padded"] is True
    bare = bsdl.emit(tmp_path, "core.v", top=None, mode="bare", ir_length=4)
    assert bare["verdict"] == "N_A" and bare["padded"] is False


def test_bsdl_missing_netlist_fails(tmp_path):
    plan = bsdl.emit(tmp_path, "does_not_exist.v", top=None, mode="auto",
                     ir_length=4)
    assert plan["verdict"] == "FAIL"
    assert any("netlist not found" in r for r in plan["reasons"])


def test_bsdl_cli_writes_plan_json(tmp_path):
    _write(tmp_path, "net.v", _PADDED_NETLIST)
    r = _run("bsdl_emit.py", str(tmp_path), "--netlist", "net.v")
    assert r.returncode == 0, r.stdout + r.stderr
    plan_json = tmp_path / "reports" / "phase2" / "dft" / "bsdl_plan.json"
    assert plan_json.is_file()
    assert json.loads(plan_json.read_text())["verdict"] == "PASS"


# ════════════════════════════════════════════════════════════════════════
# 4. dft_signoff_check — aggregate gate
# ════════════════════════════════════════════════════════════════════════

def _setup_signoff(tmp_path: Path, *, stuck=96.3, with_transition=True,
                   engine_limited=True, trans_reason="Fault stuck-at only",
                   trans_measured=None, trans_target=90.0,
                   bsdl_mode="padded"):
    """Lay down coverage.json (+ transition block) and a bsdl plan."""
    d = tmp_path / "reports" / "phase2" / "dft"
    d.mkdir(parents=True, exist_ok=True)
    cov = {"coverage_pct": stuck, "target_pct": 95.0,
           "stuck_at_ge_target": stuck >= 95.0}
    if with_transition:
        cov["transition"] = {
            "fault_model": "transition",
            "supported": not engine_limited,
            "engine_limited": engine_limited,
            "coverage_pct": trans_measured,
            "target_pct": trans_target,
            "ge_target": (None if trans_measured is None
                          else trans_measured >= trans_target),
            "reason": trans_reason,
        }
    (d / "coverage.json").write_text(json.dumps(cov))
    if with_transition and engine_limited:
        # The at-speed mechanism plan that `fault_atpg_run.run_transition_atpg`
        # writes on every engine-limited run, before it emits the record this
        # fixture hand-authors. `dft_signoff_check` requires the document the
        # ENGINE_LIMITED tier calls "documented", so a fixture without it was
        # describing a state no producer creates. Adding the artefact, not
        # relaxing the check; `test_signoff_engine_limited_without_plan_fails`
        # is the negative twin.
        plan = tmp_path / "phase2/stage2/dft/transition_atpg_plan.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(
            "# At-speed (launch-off-capture) transition ATPG plan\n\n"
            "Mechanism, clocking, capture window and the engine limitation "
            "this tier is accepted on.\n" + ("detail line\n" * 20))
    # BSDL plan — run the CLI so bsdl_plan.json is persisted exactly as the
    # real flow produces it.
    net = tmp_path / "net.v"
    if bsdl_mode == "padded":
        net.write_text("module chip_top (input TCK, input TMS, input TDI,\n"
                       "  output TDO, input clk, inout sda); endmodule\n")
        _run("bsdl_emit.py", str(tmp_path), "--netlist", "net.v")
    elif bsdl_mode == "bare":
        net.write_text("module core (input clk, input [3:0] d,\n"
                       "  output [3:0] q); endmodule\n")
        _run("bsdl_emit.py", str(tmp_path), "--netlist", "net.v")
    # bsdl_mode == "none" → leave no plan


def test_signoff_all_good_pass(tmp_path):
    _setup_signoff(tmp_path)
    rep = sign.audit(tmp_path)
    assert rep["verdict"] == "PASS"
    assert rep["stuck_at"]["status"] == "PASS"
    assert rep["transition"]["status"] == "ENGINE_LIMITED"
    assert rep["bsdl"]["status"] == "PASS"


def test_signoff_strict_transition_fails_engine_limited(tmp_path):
    _setup_signoff(tmp_path)
    rep = sign.audit(tmp_path, strict_transition=True)
    assert rep["transition"]["status"] == "FAIL"
    assert rep["verdict"] == "FAIL"


def test_signoff_real_transition_number_pass(tmp_path):
    _setup_signoff(tmp_path, engine_limited=False, trans_measured=92.0)
    rep = sign.audit(tmp_path)
    assert rep["transition"]["status"] == "PASS"
    assert rep["verdict"] == "PASS"


def test_signoff_transition_below_target_fails(tmp_path):
    _setup_signoff(tmp_path, engine_limited=False, trans_measured=70.0)
    rep = sign.audit(tmp_path)
    assert rep["transition"]["status"] == "FAIL"
    assert rep["verdict"] == "FAIL"


def test_signoff_stuck_at_below_floor_fails(tmp_path):
    _setup_signoff(tmp_path, stuck=85.0)
    rep = sign.audit(tmp_path)
    assert rep["stuck_at"]["status"] == "FAIL"
    assert rep["verdict"] == "FAIL"


def test_signoff_missing_transition_record_fails(tmp_path):
    _setup_signoff(tmp_path, with_transition=False)
    rep = sign.audit(tmp_path)
    assert rep["transition"]["status"] == "FAIL"
    assert rep["verdict"] == "FAIL"
    assert any("NO `transition`" in r or "never attempted" in r
               for r in rep["transition"]["reasons"])


def test_signoff_undocumented_engine_limit_fails(tmp_path):
    _setup_signoff(tmp_path, trans_reason="")   # engine_limited but no reason
    rep = sign.audit(tmp_path)
    assert rep["transition"]["status"] == "FAIL"
    assert rep["verdict"] == "FAIL"


def test_signoff_missing_bsdl_plan_fails(tmp_path):
    _setup_signoff(tmp_path, bsdl_mode="none")
    rep = sign.audit(tmp_path)
    assert rep["bsdl"]["status"] == "FAIL"
    assert rep["verdict"] == "FAIL"
    assert any("no bsdl_plan.json" in r for r in rep["bsdl"]["reasons"])


def test_signoff_bare_core_bsdl_skips_and_passes(tmp_path):
    _setup_signoff(tmp_path, bsdl_mode="bare")
    rep = sign.audit(tmp_path)
    assert rep["bsdl"]["status"] == "SKIP"
    assert rep["verdict"] == "PASS"


def test_signoff_no_evidence_at_all_fails(tmp_path):
    rep = sign.audit(tmp_path)
    assert rep["verdict"] == "FAIL"
    assert rep["stuck_at"]["status"] == "FAIL"
    assert rep["transition"]["status"] == "FAIL"
    assert rep["bsdl"]["status"] == "FAIL"


def test_signoff_cli_exit_code(tmp_path):
    _setup_signoff(tmp_path)
    r = _run("dft_signoff_check.py", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    _setup_signoff(tmp_path, stuck=80.0)
    r2 = _run("dft_signoff_check.py", str(tmp_path))
    assert r2.returncode == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
