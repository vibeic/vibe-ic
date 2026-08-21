#!/usr/bin/env python3
"""Two "the tool reports success while silently not doing the thing" guards
found by the sha256 benchmark canary run (2026-07-19).

CAPTURE A — vacuous_pass at 0% functional coverage
--------------------------------------------------
`full_stack_tb_gen` synthesises stimulus ONLY from `L3.opcodes`. For a
MEMORY-MAPPED REGISTER-FILE design (write data regs -> write control ->
poll status -> read result, fully specified in the L4 register map + L5
command sequence) `L3.opcodes == []`, so the generator emitted a
connectivity-only skeleton, padded to MIN_VECTORS_FAIL=8 placeholder
vectors, and `bit_level_full_stack_tb_check` self-declared
`vacuous_pass: true` -> the functional-verification pillar was satisfied at
ZERO golden-scored vectors.

Guard: `opcodes == []` AND an L4/L5 register map present -> explicit
FUNCTIONAL_COVERAGE_GAP (pass=False), not a vacuous pass. And Pillar 1 of
the benchmark verification report refuses 100% whenever the full-stack
result reports `scored_with_golden == 0`.

CAPTURE B — silent wrong-PDK fallback
--------------------------------------
`_detect_pdk` keys the staged PDK on `<project>/input/pdk/`. Absent that it
silently fell back to the container's OSS enablement even when a commercial
PDK is configured for the host — so Phase 3 emitted authoritative-looking
OSS DRC/LVS sign-off reports for a run the operator believed used the
commercial PDK. Those reports are VOID but look real.

Guard: commercial configured + `--pdk auto` + resolution landed on an OSS
in-container enablement -> REFUSE loudly. A genuinely-OSS host is
unaffected.

Every test below is chip-AGNOSTIC (no design/foundry literal) and every
guard carries BOTH a positive (must still pass) and a negative (must be
caught) proof, per the §4.05 no-leak requirement.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import bit_level_full_stack_tb_check as tbgate  # noqa: E402
import benchmark_verify_report as bvr  # noqa: E402
import phase3_one_shot_runner as p3  # noqa: E402


# ===========================================================================
# CAPTURE A — helpers
# ===========================================================================
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


def _mk_project(tmp_path: Path, *, opcodes, registers,
                scored_vectors: int, placeholder_vectors: int) -> Path:
    """Build a minimal project tree exercising the L3/L4 discriminator."""
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "doc_class": "cmd_protocol",
        "opcodes": opcodes,
        "no_opcodes_in_input": not bool(opcodes),
    }, indent=2))
    (gd / "L4_REGMAP.json").write_text(json.dumps({
        "doc_class": "regmap",
        "register_map_present": bool(registers),
        "no_registers_in_input": not bool(registers),
        "registers": registers,
    }, indent=2))

    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.v").write_text("module chip_top(); endmodule\n")

    sim = proj / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "tb_chip_top_full.v").write_text(_TB)

    per_vector = []
    for i in range(scored_vectors):
        per_vector.append({"vector_id": f"vec_{i}",
                           "expected_bytes": "AA BB",
                           "actual_bytes": "AA BB",
                           "verdict": "PASS"})
    for i in range(placeholder_vectors):
        per_vector.append({"vector_id": f"vec_brk_{i}",
                           "expected_bytes": None,
                           "actual_bytes": None,
                           "verdict": "UNVERIFIED"})
    time.sleep(0.02)
    (sim / "results.json").write_text(json.dumps({
        "pass": scored_vectors > 0 and placeholder_vectors == 0,
        "functional_verified": scored_vectors > 0 and placeholder_vectors == 0,
        "functional_coverage": {"scored_with_golden": scored_vectors,
                                "placeholder": placeholder_vectors},
        "opcodes_tested": opcodes,
        "distinct_non_padding_bytes": 16,
        "per_vector": per_vector,
        "vectors_total": len(per_vector),
    }, indent=2))
    return proj


def _regs(n: int):
    return [{"name": f"REG{i}", "address": f"0x{i * 4:02X}",
             "address_int": i * 4, "access": "R/W"} for i in range(n)]


def _run_gate(proj: Path, tmp_path: Path):
    out = tmp_path / "gate.json"
    old = sys.argv
    sys.argv = ["bit_level_full_stack_tb_check.py", str(proj),
                "--json", str(out)]
    try:
        rc = tbgate.main()
    finally:
        sys.argv = old
    return rc, json.loads(out.read_text())


# ===========================================================================
# CAPTURE A — discriminator unit proofs
# ===========================================================================
def test_a_regmap_evidence_detects_register_file(tmp_path):
    """A real register map (>=2 distinct addressable registers) is detected."""
    proj = _mk_project(tmp_path, opcodes=[], registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    ev = tbgate.register_map_protocol_evidence(
        proj / "phase1" / "generated_docs")
    assert ev is not None
    assert ev["registers"] == 7
    assert ev["distinct_addresses"] == 7


def test_a_regmap_evidence_absent_for_pure_datapath(tmp_path):
    """A pure datapath primitive (no registers) has NO register-map protocol."""
    proj = _mk_project(tmp_path, opcodes=[], registers=[],
                       scored_vectors=0, placeholder_vectors=8)
    assert tbgate.register_map_protocol_evidence(
        proj / "phase1" / "generated_docs") is None


def test_a_regmap_evidence_ignores_bare_claim_without_content(tmp_path):
    """`register_map_present: true` with a single register is not a protocol.

    A write-regs -> control-write -> status-poll -> read-result sequence is
    not expressible from one address, so the opcode-TB N/A decision stands.
    """
    proj = _mk_project(tmp_path, opcodes=[], registers=_regs(1),
                       scored_vectors=0, placeholder_vectors=8)
    assert tbgate.register_map_protocol_evidence(
        proj / "phase1" / "generated_docs") is None


# ===========================================================================
# CAPTURE A — §4.05 no-leak: POSITIVE (must still pass unchanged)
# ===========================================================================
def test_a_positive_opcode_stream_path_unchanged(tmp_path):
    """POSITIVE — the opcode-stream path is untouched by the new guard.

    An IC WITH opcodes never enters the vacuous/gap branch at all; it still
    reaches the strict structural check exactly as before.
    """
    proj = _mk_project(tmp_path, opcodes=["0x70", "0x72", "0x74"],
                       registers=_regs(7),
                       scored_vectors=8, placeholder_vectors=0)
    rc, res = _run_gate(proj, tmp_path)
    # Reaches the real check (not the vacuous / gap early-exit).
    assert res.get("vacuous_pass") is not True
    assert res.get("verdict") != "FUNCTIONAL_COVERAGE_GAP"
    assert "tb_path" in res and "bit_level_evidence" in res
    assert res["pass"] is True
    assert rc == 0


def test_a_positive_pure_datapath_still_vacuous_na(tmp_path):
    """POSITIVE — a genuinely non-protocol IC still gets its honest N/A.

    No opcodes AND no register map => nothing was failed to be synthesised;
    the opcode-driven full-stack TB is legitimately not applicable.
    """
    proj = _mk_project(tmp_path, opcodes=[], registers=[],
                       scored_vectors=0, placeholder_vectors=8)
    rc, res = _run_gate(proj, tmp_path)
    assert rc == 2
    assert res["pass"] is True
    assert res["vacuous_pass"] is True
    assert res["rule"] == "N/A"


def test_a_positive_regmap_with_real_golden_coverage_not_flagged(tmp_path):
    """POSITIVE — a register-map IC that DID score goldens is not a gap.

    The guard fires on ZERO functionally-scored vectors, not on the mere
    presence of a register map. Once the follow-on transaction driver lands
    and scores vectors, this path must not regress into a FAIL.
    """
    proj = _mk_project(tmp_path, opcodes=[], registers=_regs(7),
                       scored_vectors=8, placeholder_vectors=0)
    rc, res = _run_gate(proj, tmp_path)
    assert res.get("verdict") != "FUNCTIONAL_COVERAGE_GAP"
    assert rc == 2 and res["vacuous_pass"] is True


# ===========================================================================
# CAPTURE A — §4.05 no-leak: NEGATIVE (must be caught)
# ===========================================================================
def test_a_negative_vacuous_regmap_tb_is_caught(tmp_path):
    """NEGATIVE — the exact canary shape must no longer be a vacuous pass.

    L3.opcodes == [] but L4 declares a register file, and the full-stack TB
    scored ZERO vectors against a golden (8 bring-up placeholders). That is
    OUR TB-generation gap, and it must surface as an explicit
    functional-coverage GAP.
    """
    proj = _mk_project(tmp_path, opcodes=[], registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    rc, res = _run_gate(proj, tmp_path)
    assert rc == 1, res
    assert res["pass"] is False
    assert res["vacuous_pass"] is False
    assert res["functional_verified"] is False
    assert res["verdict"] == "FUNCTIONAL_COVERAGE_GAP"
    assert res["scored_with_golden"] == 0
    assert res["rule"] == "register_map_protocol_unsynthesized"
    assert "register-map protocol not yet synthesizable" in res["rationale"]
    assert res["register_map_evidence"]["registers"] == 7


# ===========================================================================
# CAPTURE A — processor_cpu CSR file is NOT a register-slave protocol
# (ORGANIC — ibex x sky130A: L4 = RISC-V CSRs reachable only by executed
#  csr* instructions, never an externally addressable top-level slave).
# ===========================================================================
def _stamp_ic_class(proj: Path, ic_class: str) -> None:
    rep = proj / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "ic_class.json").write_text(json.dumps(
        {"ic_class": ic_class,
         "has_command_protocol": ic_class != "processor_cpu",
         "protocol_class": "none" if ic_class == "processor_cpu"
         else "slave_like"}, indent=2))


def test_a_regmap_evidence_none_for_processor_cpu(tmp_path):
    """UNIT — a processor_cpu's L4 (CSR file) is NOT a register-slave protocol.

    Even with many addressable registers, ic_class=processor_cpu means the L4
    map is internal architectural state (CSRs/GPRs) reachable only by a csr*
    instruction the core executes — not a top-level addr/data/we slave. The
    evidence resolver must return None so the opcode-TB N/A decision stands.
    """
    proj = _mk_project(tmp_path, opcodes=[], registers=_regs(43),
                       scored_vectors=0, placeholder_vectors=8)
    gd = proj / "phase1" / "generated_docs"
    assert tbgate.register_map_protocol_evidence(
        gd, ic_class="processor_cpu") is None
    # …and WITHOUT the CPU hint the same map IS a register-slave protocol,
    # proving the discriminator is exactly ic_class (no accidental blanket).
    assert tbgate.register_map_protocol_evidence(gd) is not None


def test_a_regmap_evidence_present_for_non_cpu_slave(tmp_path):
    """UNIT — a non-CPU class with a real register map still yields evidence."""
    proj = _mk_project(tmp_path, opcodes=[], registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    ev = tbgate.register_map_protocol_evidence(
        proj / "phase1" / "generated_docs",
        ic_class="serial_peripheral_protocol")
    assert ev is not None and ev["registers"] == 7


def test_a_positive_processor_cpu_csr_is_vacuous_na(tmp_path):
    """POSITIVE — the exact canary shape under ic_class=processor_cpu is N/A.

    L3.opcodes == [] + a 43-register L4 (RISC-V CSR map) + 0 scored vectors —
    identical to the FUNCTIONAL_COVERAGE_GAP canary — but because the IC is a
    CPU core it has NO externally-addressable register-slave protocol, so the
    gate mirrors reports/ic_class.json (has_command_protocol=false) and the
    cpu_functional_oracle deferral: VACUOUS_PASS, not a FAIL.
    """
    proj = _mk_project(tmp_path, opcodes=[], registers=_regs(43),
                       scored_vectors=0, placeholder_vectors=8)
    _stamp_ic_class(proj, "processor_cpu")
    rc, res = _run_gate(proj, tmp_path)
    assert rc == 2, res
    assert res["pass"] is True
    assert res["vacuous_pass"] is True
    assert res["rule"] == "N/A"
    assert res.get("verdict") != "FUNCTIONAL_COVERAGE_GAP"


def test_a_negative_non_cpu_slave_stamp_still_caught(tmp_path):
    """NEGATIVE — a NON-CPU ic_class stamp must NOT leak the CPU relaxation.

    Same canary shape, ic_class=serial_peripheral_protocol: the register-slave
    functional-coverage GAP must still fire exactly as before.
    """
    proj = _mk_project(tmp_path, opcodes=[], registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    _stamp_ic_class(proj, "serial_peripheral_protocol")
    rc, res = _run_gate(proj, tmp_path)
    assert rc == 1, res
    assert res["pass"] is False
    assert res["verdict"] == "FUNCTIONAL_COVERAGE_GAP"
    assert res["rule"] == "register_map_protocol_unsynthesized"


def test_a_negative_pillar1_refuses_100pct_at_zero_scored(tmp_path):
    """NEGATIVE — Pillar 1 must HONOR the gap even if a coverage report
    claims 100%. A vacuous TB is not a pass, and an upstream requirements
    tally cannot override the flow's own admission of 0 scored vectors."""
    proj = _mk_project(tmp_path, opcodes=[], registers=_regs(7),
                       scored_vectors=0, placeholder_vectors=8)
    reports = proj / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "functional_coverage.json").write_text(json.dumps({
        "requirements": [{"id": "R1", "status": "PASS"},
                         {"id": "R2", "status": "PASS"}],
    }, indent=2))

    scored, placeholder, rel = bvr._full_stack_functional_coverage(proj)
    assert scored == 0 and placeholder == 8
    assert rel.endswith("sim_full_stack/results.json")

    out = tmp_path / "REPORT.md"
    old = sys.argv
    sys.argv = ["benchmark_verify_report.py", str(proj), "--out", str(out)]
    try:
        with pytest.raises(SystemExit):
            bvr.main()
    finally:
        sys.argv = old
    text = out.read_text()
    assert "FUNCTIONAL COVERAGE GAP" in text
    assert "scored_with_golden=0" in text
    # The Pillar-1 gate row must NOT read PASS.
    row = [ln for ln in text.splitlines()
           if ln.startswith("| 1. Functional Coverage")]
    assert row, text
    assert "PASS" not in row[0], row[0]


def test_a_positive_pillar1_unaffected_when_goldens_scored(tmp_path):
    """POSITIVE — Pillar 1 still reports 100% for a genuinely verified run."""
    proj = _mk_project(tmp_path, opcodes=["0x70", "0x72", "0x74"],
                       registers=_regs(7),
                       scored_vectors=8, placeholder_vectors=0)
    reports = proj / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "functional_coverage.json").write_text(json.dumps({
        "requirements": [{"id": "R1", "status": "PASS"},
                         {"id": "R2", "status": "PASS"}],
    }, indent=2))
    out = tmp_path / "REPORT.md"
    old = sys.argv
    sys.argv = ["benchmark_verify_report.py", str(proj), "--out", str(out)]
    try:
        with pytest.raises(SystemExit):
            bvr.main()
    finally:
        sys.argv = old
    text = out.read_text()
    assert "FUNCTIONAL COVERAGE GAP" not in text
    row = [ln for ln in text.splitlines()
           if ln.startswith("| 1. Functional Coverage")]
    assert row and "2/2 requirements verified" in row[0]


def test_a_negative_regmap_with_no_full_stack_result_is_a_gap(tmp_path):
    """NEGATIVE — a register-map IC with NO full-stack result at all has zero
    functional coverage too; it must not be waived as a vacuous pass."""
    proj = _mk_project(tmp_path, opcodes=[], registers=_regs(4),
                       scored_vectors=0, placeholder_vectors=0)
    (proj / "phase2" / "stage1" / "sim_full_stack" / "results.json").unlink()
    rc, res = _run_gate(proj, tmp_path)
    assert rc == 1
    assert res["verdict"] == "FUNCTIONAL_COVERAGE_GAP"
    assert res["scored_with_golden"] == 0


def test_a_pillar1_silent_when_no_full_stack_result(tmp_path):
    """A project with no full-stack TB result at all is unaffected."""
    proj = tmp_path / "bare"
    (proj / "reports").mkdir(parents=True, exist_ok=True)
    assert bvr._full_stack_functional_coverage(proj) == (None, None, None)


# ===========================================================================
# CAPTURE B — silent wrong-PDK fallback
# ===========================================================================
def test_b_negative_commercial_configured_oss_fallback_refused(tmp_path):
    """NEGATIVE — commercial configured + no staged input/pdk/ => the guard
    FIRES. Phase 3 must never emit OSS sign-off reports under a commercial
    PDK belief."""
    proj = tmp_path / "proj"
    proj.mkdir()
    msg = p3.commercial_pdk_fallback_guard(
        proj, "sky130A", "auto", commercial_configured=True)
    assert msg is not None
    assert "REFUSED" in msg
    assert "sky130A" in msg                 # names the resolved fallback
    assert "COMMERCIAL PDK" in msg          # names the configured intent
    assert "input/pdk" in msg               # names how to fix
    assert "--allow-oss-pdk-fallback" in msg


def test_b_negative_fires_for_every_oss_enablement(tmp_path):
    """The guard is not sky130-specific — any in-container OSS enablement
    reached by silent fallback is refused."""
    proj = tmp_path / "proj"
    proj.mkdir()
    for name in p3._OSS_CONTAINER_PDKS:
        assert p3.commercial_pdk_fallback_guard(
            proj, name, "auto", commercial_configured=True) is not None, name


def test_b_positive_oss_only_host_unaffected(tmp_path):
    """POSITIVE — a genuinely-OSS run (nothing configured) proceeds."""
    proj = tmp_path / "proj"
    proj.mkdir()
    assert p3.commercial_pdk_fallback_guard(
        proj, "sky130A", "auto", commercial_configured=False) is None
    assert p3.commercial_pdk_fallback_guard(
        proj, "nangate45", "auto", commercial_configured=False) is None


def test_b_positive_explicit_override_is_deliberate(tmp_path):
    """POSITIVE — an explicit `--pdk sky130A` is a deliberate OSS run, not a
    silent fallback, even on a commercially-configured host."""
    proj = tmp_path / "proj"
    proj.mkdir()
    assert p3.commercial_pdk_fallback_guard(
        proj, "sky130A", "sky130A", commercial_configured=True) is None


def test_b_positive_staged_pdk_resolved_is_not_a_fallback(tmp_path):
    """POSITIVE — when a project-staged PDK resolved (`custom:<dir>`) nothing
    fell back, so the guard stays silent."""
    proj = tmp_path / "proj"
    proj.mkdir()
    assert p3.commercial_pdk_fallback_guard(
        proj, "custom:pdk", "auto", commercial_configured=True) is None


def test_b_positive_explicit_acknowledgement_allows_fallback(tmp_path):
    """POSITIVE — the operator may acknowledge the fallback in writing."""
    proj = tmp_path / "proj"
    proj.mkdir()
    assert p3.commercial_pdk_fallback_guard(
        proj, "sky130A", "auto", commercial_configured=True,
        allow_oss_fallback=True) is None


def test_b_guard_message_leaks_no_pdk_identifier(tmp_path):
    """NDA — the refusal must never print the configured PDK's identifier."""
    proj = tmp_path / "proj"
    proj.mkdir()
    msg = p3.commercial_pdk_fallback_guard(
        proj, "sky130A", "auto", commercial_configured=True)
    assert "identifier withheld" in msg
    import _commercial_pdk as cp
    for tok in cp.nda_tokens():
        if tok:
            assert tok.lower() not in msg.lower()


def test_b_cli_exposes_acknowledgement_flag():
    """The escape hatch must be reachable from the CLI."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    assert '"--allow-oss-pdk-fallback"' in src
    assert "commercial_pdk_fallback_guard(" in src
