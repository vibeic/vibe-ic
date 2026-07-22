#!/usr/bin/env python3
"""bit_level_full_stack_tb_check — crypto/compute-accelerator register-map
FUNCTIONAL-ORACLE deferral guard (sha256 x sky130A convergence, 2026-07-23).

Context
-------
The 2026-07-19 sha256 canary correctly stopped a register-map design from
reporting a GREEN `vacuous_pass` at 0 functionally-scored vectors. But it then
hard-FAILed (rc=1, `register_map_protocol_unsynthesized`) EVERY register-map
design with 0 scored vectors — including `crypto_accelerator` cores whose
functional ORACLE is legitimately DEFERRED, not a synthesizable-now tooling gap.

For a crypto/compute accelerator (`reports/ic_class.json` has_command_protocol=
false: write data-block -> start -> poll-done -> read result-block) the register
STIMULUS is synthesizable, but the RESPONSE VALUE (e.g. the SHA-256 digest) is
defined by a chip-specific ALGORITHM the deterministic generator cannot
fabricate. The plugin's OWN Phase-2 TB generators already say so for such a run:

  * step-4 reference_tb writes capability_gap==cap:cpu_functional_oracle into
    phase2/stage1/sim/results.xml, AND/OR
  * professional_tb_gen emits reference_model_tier==hook_unfilled into
    sim_professional/<top>/verification_plan.json (its reference_model hook
    RAISES until a per-IC oracle is supplied — never a vacuous pass).

So the bit-level full-stack gate must, for exactly this class, emit
WAIVED-DEFERRED (rc=3 + PASS_WITH_WAIVERS sentinel — visible, review_required,
non-blocking) instead of a hard-FAIL — the SAME #228 / cpu_functional_oracle_
waiver idiom step 4 uses. A real professional-cocotb functional PASS SUPERSEDES
the deferral (rc=0). A genuine register-SLAVE peripheral (has_command_protocol=
true) or a run where NEITHER generator declared the deferral still hard-FAILs.

Every test is chip-AGNOSTIC (no design/foundry literal) and carries BOTH the
positive (must defer / supersede) and the negative (must still FAIL) proof.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest  # noqa: F401

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import bit_level_full_stack_tb_check as tbgate  # noqa: E402

_TB = """\
`timescale 1ns/1ps
module tb_chip_top_full;
    wire acc_id;
    reg  drive;
    chip_top u_dut(.acc_id(acc_id), .clk(clk), .rstn(rstn));
    initial begin
        drive = 0; #1800;
        drive = 1; #7100;
        $display("FULL_STACK_TB_DONE");
        $finish;
    end
endmodule
"""


def _regs(n: int):
    return [{"name": f"REG{i}", "address": f"0x{i * 4:02X}",
             "address_int": i * 4, "access": "R/W"} for i in range(n)]


def _mk_project(tmp_path: Path, *, registers, scored_vectors: int,
                placeholder_vectors: int) -> Path:
    """Minimal register-map project: L3 opcodes==[] + an L4 register file +
    a sim_full_stack/results.json with the given scored/placeholder split."""
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "doc_class": "cmd_protocol", "opcodes": [],
        "no_opcodes_in_input": True}, indent=2))
    (gd / "L4_REGMAP.json").write_text(json.dumps({
        "doc_class": "regmap", "register_map_present": bool(registers),
        "no_registers_in_input": not bool(registers),
        "registers": registers}, indent=2))
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.v").write_text("module chip_top(); endmodule\n")
    sim = proj / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "tb_chip_top_full.v").write_text(_TB)
    per_vector = []
    for i in range(scored_vectors):
        per_vector.append({"vector_id": f"vec_{i}", "expected_bytes": "AA BB",
                           "actual_bytes": "AA BB", "verdict": "PASS"})
    for i in range(placeholder_vectors):
        per_vector.append({"vector_id": f"vec_brk_{i}", "expected_bytes": None,
                           "actual_bytes": None, "verdict": "UNVERIFIED"})
    time.sleep(0.02)
    (sim / "results.json").write_text(json.dumps({
        "pass": scored_vectors > 0 and placeholder_vectors == 0,
        "functional_verified": scored_vectors > 0 and placeholder_vectors == 0,
        "functional_coverage": {"scored_with_golden": scored_vectors,
                                "placeholder": placeholder_vectors},
        "opcodes_tested": [], "distinct_non_padding_bytes": 16,
        "per_vector": per_vector, "vectors_total": len(per_vector)},
        indent=2))
    return proj


def _stamp_ic_class(proj: Path, ic_class: str, has_cmd_proto: bool) -> None:
    rep = proj / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "ic_class.json").write_text(json.dumps(
        {"ic_class": ic_class, "has_command_protocol": has_cmd_proto,
         "protocol_class": "none" if not has_cmd_proto else "slave_like"},
        indent=2))


def _write_reference_tb_capgap(proj: Path, gap: str) -> None:
    d = proj / "phase2" / "stage1" / "sim"
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.xml").write_text(
        "<results><verdict>CONNECTIVITY_PASS</verdict>"
        "<functional_verified>false</functional_verified>"
        f"<capability_gap>{gap}</capability_gap></results>\n")


def _write_professional_hook(proj: Path, top: str, tier: str) -> None:
    d = proj / "phase2" / "stage1" / "sim_professional" / top
    d.mkdir(parents=True, exist_ok=True)
    (d / "verification_plan.json").write_text(json.dumps(
        {"top": top, "ic_class": "crypto_accelerator",
         "reference_model_tier": tier}, indent=2))


def _write_professional_pass(proj: Path, top: str) -> None:
    d = proj / "phase2" / "stage1" / "sim_professional" / top
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<testsuites><testsuite name="cocotb" tests="4" failures="0" '
        'errors="0" skipped="0">'
        '<testcase name="nist_abc" classname="tb"/>'
        '<testcase name="nist_abcdbcde" classname="tb"/>'
        '<testcase name="nist_1m_a" classname="tb"/>'
        '<testcase name="sha224_abc" classname="tb"/>'
        '</testsuite></testsuites>\n')


def _run_gate(proj: Path, tmp_path: Path, capsys=None):
    out = tmp_path / "gate.json"
    old = sys.argv
    sys.argv = ["bit_level_full_stack_tb_check.py", str(proj),
                "--json", str(out)]
    try:
        rc = tbgate.main()
    finally:
        sys.argv = old
    res = json.loads(out.read_text())
    stdout = capsys.readouterr().out if capsys is not None else ""
    return rc, res, stdout


# ===========================================================================
# POSITIVE — the deferred-oracle class becomes WAIVED-DEFERRED, not FAIL
# ===========================================================================
def test_crypto_regmap_deferred_via_reference_tb_capgap(tmp_path, capsys):
    """crypto_accelerator (has_command_protocol=false) + 0 scored vectors +
    step-4 reference_tb declared cap:cpu_functional_oracle -> WAIVED-DEFERRED
    (rc=3 + PASS_WITH_WAIVERS), NOT the rc=1 FUNCTIONAL_COVERAGE_GAP."""
    proj = _mk_project(tmp_path, registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    _stamp_ic_class(proj, "crypto_accelerator", has_cmd_proto=False)
    _write_reference_tb_capgap(proj, "cap:cpu_functional_oracle")
    rc, res, stdout = _run_gate(proj, tmp_path, capsys)
    assert rc == 3, res
    assert res["pass"] is True
    assert res["vacuous_pass"] is False           # NOT a green vacuous pass
    assert res["functional_verified"] is False    # honestly not verified
    assert res["waived_deferred"] is True
    assert res["verdict"] == "PASS_WITH_WAIVERS"
    assert res["capability_gap"] == "cap:cpu_functional_oracle"
    assert res["rule"] == "register_map_functional_oracle_deferred"
    # flow_compliance requires a stdout line starting with the sentinel.
    assert any(ln.lstrip().startswith("PASS_WITH_WAIVERS")
               for ln in stdout.splitlines()), stdout


def test_crypto_regmap_deferred_via_professional_hook(tmp_path, capsys):
    """Deferral signalled ONLY by professional_tb reference_model_tier=
    hook_unfilled (no reference_tb capgap xml) still -> WAIVED-DEFERRED."""
    proj = _mk_project(tmp_path, registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    _stamp_ic_class(proj, "crypto_accelerator", has_cmd_proto=False)
    _write_professional_hook(proj, "chip_top", "hook_unfilled")
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 3, res
    assert res["waived_deferred"] is True
    assert res["verdict"] == "PASS_WITH_WAIVERS"
    assert "hook_unfilled" in res["deferral_evidence"]


def test_crypto_regmap_professional_pass_supersedes(tmp_path, capsys):
    """A REAL professional cocotb functional PASS (failures=0) supersedes the
    deferral: genuine PASS (rc=0, functional_verified=true)."""
    proj = _mk_project(tmp_path, registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    _stamp_ic_class(proj, "crypto_accelerator", has_cmd_proto=False)
    _write_reference_tb_capgap(proj, "cap:cpu_functional_oracle")
    _write_professional_pass(proj, "chip_top")
    rc, res, _ = _run_gate(proj, tmp_path, capsys)
    assert rc == 0, res
    assert res["pass"] is True
    assert res["functional_verified"] is True
    assert res["rule"] == "register_map_functional_pass_professional"


# ===========================================================================
# NEGATIVE — the deferral must NOT leak; these still hard-FAIL (rc=1)
# ===========================================================================
def test_negative_crypto_regmap_without_any_deferral_still_fails(tmp_path):
    """has_command_protocol=false BUT neither the reference_tb capgap nor the
    professional hook was recorded -> the plugin never declared a deferral, so
    the register-map functional-coverage GAP must still hard-FAIL. (Prevents a
    blanket relaxation keyed on ic_class alone.)"""
    proj = _mk_project(tmp_path, registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    _stamp_ic_class(proj, "crypto_accelerator", has_cmd_proto=False)
    rc, res, _ = _run_gate(proj, tmp_path)
    assert rc == 1, res
    assert res["verdict"] == "FUNCTIONAL_COVERAGE_GAP"
    assert res["rule"] == "register_map_protocol_unsynthesized"


def test_negative_true_slave_with_capgap_present_still_fails(tmp_path):
    """A genuine register-SLAVE peripheral (has_command_protocol=true) must
    NEVER be relaxed even if a stray cap:cpu_functional_oracle xml is present —
    its oracle IS synthesizable, so 0 scored vectors is a real FAIL."""
    proj = _mk_project(tmp_path, registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    _stamp_ic_class(proj, "serial_peripheral_protocol", has_cmd_proto=True)
    _write_reference_tb_capgap(proj, "cap:cpu_functional_oracle")
    rc, res, _ = _run_gate(proj, tmp_path)
    assert rc == 1, res
    assert res["verdict"] == "FUNCTIONAL_COVERAGE_GAP"
    assert res["rule"] == "register_map_protocol_unsynthesized"


def test_negative_no_ic_class_stamp_still_fails(tmp_path):
    """No ic_class.json at all (has_command_protocol unknown) -> conservative:
    the original canary FAIL stands (the 2026-07-19 guard is preserved)."""
    proj = _mk_project(tmp_path, registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    _write_reference_tb_capgap(proj, "cap:cpu_functional_oracle")
    rc, res, _ = _run_gate(proj, tmp_path)
    assert rc == 1, res
    assert res["rule"] == "register_map_protocol_unsynthesized"


def test_positive_scored_regmap_unaffected(tmp_path):
    """A register-map design that DID score golden vectors is unaffected by
    the deferral path (it never enters the 0-scored branch)."""
    proj = _mk_project(tmp_path, registers=_regs(7),
                       scored_vectors=4, placeholder_vectors=0)
    _stamp_ic_class(proj, "crypto_accelerator", has_cmd_proto=False)
    _write_reference_tb_capgap(proj, "cap:cpu_functional_oracle")
    rc, res, _ = _run_gate(proj, tmp_path)
    # scored>0 -> not the 0-scored gap branch; gate passes on its own merits.
    assert rc in (0, 2), res
    assert res.get("verdict") != "FUNCTIONAL_COVERAGE_GAP"
