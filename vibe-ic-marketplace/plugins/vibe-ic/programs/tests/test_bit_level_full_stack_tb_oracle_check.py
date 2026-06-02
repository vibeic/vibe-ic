#!/usr/bin/env python3
"""Tests for bit_level_full_stack_tb_oracle_check.py (Wave 12)."""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "bit_level_full_stack_tb_oracle_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _proj(tmp_path: Path,
          results: dict | None,
          tb_files: dict[str, str] | None = None,
          rtl_files: dict[str, str] | None = None,
          waivers: dict | None = None) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(parents=True)
    sim = proj / "phase2" / "stage1" / "sim" / "sim_full_stack"
    sim.mkdir(parents=True)
    if results is not None:
        (sim / "results.json").write_text(json.dumps(results))
    if tb_files:
        for n, b in tb_files.items():
            (sim / n).write_text(b)
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    if rtl_files:
        for n, b in rtl_files.items():
            (rtl / n).write_text(b)
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


def _well_formed_results(n: int = 16, all_match: bool = True) -> dict:
    per_vector = []
    for i in range(n):
        per_vector.append({
            "name": f"vec_{i:02d}",
            "expected_bytes": f"F2,{i:02X},22,33,44",
            "actual_bytes": f"F2,{i:02X},22,33,44" if all_match
                           else f"F2,{i:02X},22,33,55",
            "match": all_match,
        })
    passed = n if all_match else 0
    return {
        "pass": all_match,
        "vectors_total": n,
        "vectors_passed": passed,
        "vectors_failed": n - passed,
        "per_vector": per_vector,
        "tb_module": "tb_full_stack",
        "rtl_top": "chip_top",
        "input_doc_evidence": "input/docs/cmd_table.md#opcodes",
        "sim_log_sha256": "deadbeef" * 8,
    }


def test_full_stack_oracle_pass(tmp_path):
    proj = _proj(
        tmp_path,
        _well_formed_results(16, True),
        tb_files={"tb_full_stack.v": "module tb_full_stack; endmodule"},
        rtl_files={"chip_top.v": "module chip_top(); endmodule"},
    )
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_missing_per_vector_fail(tmp_path):
    proj = _proj(
        tmp_path,
        {"pass": True, "distinct_non_padding_bytes": 14},
    )
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "PER_VECTOR_MISSING" in r.stdout


def test_partial_match_fail(tmp_path):
    res = _well_formed_results(16, True)
    res["vectors_passed"] = 10
    res["vectors_failed"] = 6
    proj = _proj(
        tmp_path, res,
        tb_files={"tb_full_stack.v": "module tb_full_stack; endmodule"},
        rtl_files={"chip_top.v": "module chip_top(); endmodule"},
    )
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "VECTORS_NOT_ALL_PASS" in r.stdout


def test_too_few_vectors_warn(tmp_path):
    proj = _proj(
        tmp_path,
        _well_formed_results(10, True),
        tb_files={"tb_full_stack.v": "module tb_full_stack; endmodule"},
        rtl_files={"chip_top.v": "module chip_top(); endmodule"},
    )
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WARN" in r.stdout or "PER_VECTOR_UNDER_TESTED" in r.stdout


def test_tb_module_missing_fail(tmp_path):
    res = _well_formed_results(16, True)
    res["tb_module"] = "tb_xyz"
    proj = _proj(
        tmp_path, res,
        rtl_files={"chip_top.v": "module chip_top(); endmodule"},
    )
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "TB_MODULE_FILE_MISSING" in r.stdout


def test_rtl_top_missing_fail(tmp_path):
    res = _well_formed_results(16, True)
    res["rtl_top"] = "no_such_top"
    proj = _proj(
        tmp_path, res,
        tb_files={"tb_full_stack.v": "module tb_full_stack; endmodule"},
    )
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "RTL_TOP_FILE_MISSING" in r.stdout


def test_no_evidence_fail(tmp_path):
    res = _well_formed_results(16, True)
    res.pop("input_doc_evidence")
    proj = _proj(
        tmp_path, res,
        tb_files={"tb_full_stack.v": "module tb_full_stack; endmodule"},
        rtl_files={"chip_top.v": "module chip_top(); endmodule"},
    )
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "INPUT_DOC_EVIDENCE_MISSING" in r.stdout


def test_no_results_skips(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS_SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    proj = _proj(
        tmp_path,
        {"pass": True, "distinct_non_padding_bytes": 14},
        waivers={
            "bit_level_oracle_skipped": (
                "FPGA-only project, oracle replaced by hardware "
                "attestation in fpga/attestation_log.json with "
                "scope-validated capture per L11 evidence chain."
            )
        },
    )
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WAIVER" in r.stdout


def test_help_works():
    r = subprocess.run(
        [sys.executable, str(PROG), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# v0.119.45 (Wave 13) — CRC cross-check enhancement tests.
# ---------------------------------------------------------------------------


def _reflect8(b: int) -> int:
    out = 0
    for i in range(8):
        if b & (1 << i):
            out |= 1 << (7 - i)
    return out


def _crc8_ref(prefix: list[int],
              poly: int,
              init: int,
              refin: bool,
              refout: bool) -> int:
    crc = init & 0xFF
    for byte in prefix:
        b = _reflect8(byte) if refin else byte
        crc ^= b & 0xFF
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    if refout:
        crc = _reflect8(crc)
    return crc


def _proj_with_l3_crc(tmp_path: Path,
                      l3_crc: dict | None,
                      vectors: list[dict],
                      waivers: dict | None = None) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(parents=True)
    sim = proj / "phase2" / "stage1" / "sim" / "sim_full_stack"
    sim.mkdir(parents=True)
    res = {
        "pass": True,
        "vectors_total": len(vectors),
        "vectors_passed": len(vectors),
        "vectors_failed": 0,
        "per_vector": vectors,
        "tb_module": "tb_full_stack",
        "rtl_top": "chip_top",
        "input_doc_evidence": "input/docs/cmd_table.md#opcodes",
        "sim_log_sha256": "deadbeef" * 8,
    }
    (sim / "results.json").write_text(json.dumps(res))
    (sim / "tb_full_stack.v").write_text("module tb_full_stack; endmodule")
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.v").write_text("module chip_top(); endmodule")
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    l3: dict = {"doc_id": "L3"}
    if l3_crc is not None:
        l3["crc_parameters"] = l3_crc
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3))
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


def test_crc_cross_check_pass(tmp_path):
    """L3 declares poly + init + bit_order; vectors carry CRC computed
    with those parameters → PASS (no CRC findings)."""
    poly, init = 0x07, 0xFF
    refin = refout = True
    prefix = [0x75, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00]
    crc = _crc8_ref(prefix, poly, init, refin, refout)
    vectors = []
    for i in range(16):
        vectors.append({
            "name": f"vec_{i:02d}",
            "expected_bytes": ",".join(f"{b:02X}" for b in prefix + [crc]),
            "actual_bytes": ",".join(f"{b:02X}" for b in prefix + [crc]),
            "match": True,
        })
    proj = _proj_with_l3_crc(
        tmp_path,
        {"polynomial_hex": "0x07", "init_hex": "0xFF",
         "bit_order": "lsb_first"},
        vectors,
    )
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CRC_VARIANT_MISMATCH_VS_L3" not in r.stdout
    assert "PASS" in r.stdout


def test_crc_mismatch_fail(tmp_path):
    """L3 says poly=0x07, init=0xFF, refin/refout=True; but TB used
    poly=0x07, init=0x00 (no reflect) → recomputed CRC differs from
    declared CRC → FAIL."""
    bad_poly, bad_init = 0x07, 0x00
    bad_refin = bad_refout = False
    prefix = [0x75, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00]
    bad_crc = _crc8_ref(prefix, bad_poly, bad_init, bad_refin, bad_refout)
    vectors = []
    for i in range(16):
        vectors.append({
            "name": f"vec_{i:02d}",
            "expected_bytes": ",".join(
                f"{b:02X}" for b in prefix + [bad_crc]),
            "actual_bytes": ",".join(
                f"{b:02X}" for b in prefix + [bad_crc]),
            "match": True,
        })
    proj = _proj_with_l3_crc(
        tmp_path,
        {"polynomial_hex": "0x07", "init_hex": "0xFF",
         "bit_order": "lsb_first"},
        vectors,
    )
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "CRC_VARIANT_MISMATCH_VS_L3" in r.stdout


def test_no_crc_params_warn(tmp_path):
    """L3 lacks crc_parameters block → cross-check WARNs but doesn't
    FAIL the gate."""
    prefix = [0x75, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00]
    vectors = []
    for i in range(16):
        vectors.append({
            "name": f"vec_{i:02d}",
            "expected_bytes": ",".join(
                f"{b:02X}" for b in prefix + [0xAA]),
            "actual_bytes": ",".join(
                f"{b:02X}" for b in prefix + [0xAA]),
            "match": True,
        })
    proj = _proj_with_l3_crc(tmp_path, None, vectors)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert ("L3_CRC_PARAMETERS_ABSENT" in r.stdout
            or "WARN" in r.stdout)


def test_crc_with_waiver_pass(tmp_path):
    """CRC mismatch + tb_crc_variant_intentional_mismatch waiver → PASS."""
    bad_poly, bad_init = 0x07, 0x00
    prefix = [0x75, 0x10, 0x00]
    bad_crc = _crc8_ref(prefix, bad_poly, bad_init, False, False)
    vectors = []
    for i in range(16):
        vectors.append({
            "name": f"vec_{i:02d}",
            "expected_bytes": ",".join(
                f"{b:02X}" for b in prefix + [bad_crc]),
            "actual_bytes": ",".join(
                f"{b:02X}" for b in prefix + [bad_crc]),
            "match": True,
        })
    proj = _proj_with_l3_crc(
        tmp_path,
        {"polynomial_hex": "0x07", "init_hex": "0xFF",
         "bit_order": "lsb_first"},
        vectors,
        waivers={
            "tb_crc_variant_intentional_mismatch": (
                "Reverse-engineering CRC variant pending host capture "
                "comparison; waived per JIRA IC-9903 with explicit "
                "rig-operator approval until oracle bytewise dump lands."
            )
        },
    )
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CRC_VARIANT_MISMATCH_VS_L3" not in r.stdout
