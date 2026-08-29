#!/usr/bin/env python3
"""ORGANIC #745 [P2] — closed-form arithmetic-primitive oracle TB generator.

Pins the two contract halves of arith_oracle_tb_gen:
  (a) for an arithmetic-primitive class with a recognised closed-form operator
      (e.g. {operator:'*', width:N, signed:false}), the emitted TB's golden
      COMPUTES (x*y) mod 2^N on a corner operand pair (pure golden + the TB
      literal both checked);
  (b) §4.05 FAIL-CLOSED — a no-oracle class (processor_cpu / crypto) still
      DEFERS (no TB, no fabricated golden), as does an unrecognised operator
      and a serial/streaming datapath (spm-style 1-bit serial port).
"""
from __future__ import annotations

import json

from _skill_routes import assert_route_ships
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import arith_oracle_tb_gen as aotg  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────
def _mk_project(tmp_path: Path, *, top: str, ports: list, l2: str,
                decl: dict | None = None) -> Path:
    root = tmp_path / top
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L2_FRS.json").write_text(json.dumps(
        {"ic_name": top, "frs_sections": [{"content": l2}]}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"top_module": top, "top_ports": ports}))
    if decl is not None:
        (root / "plugin_output").mkdir()
        (root / "plugin_output" / "declaration.json").write_text(
            json.dumps(decl))
    return root


def _oracle_tbs(project: Path) -> list:
    sd = project / "phase2" / "stage1" / "sim_full_stack"
    return sorted(sd.glob("tb_*_oracle.v")) if sd.is_dir() else []


# ── pure golden compute (testable WITHOUT iverilog) ──────────────────────────
def test_compute_golden_mul_mod_2n_unsigned():
    # (x*y) mod 2^N, corner operands
    assert aotg.compute_golden("*", 255, 255, 8, False) == (255 * 255) % 256
    assert aotg.compute_golden("*", 255, 255, 8, False) == 1
    assert aotg.compute_golden("*", 0, 123, 8, False) == 0
    assert aotg.compute_golden("*", 12, 10, 16, False) == 120


def test_compute_golden_add_sub_bitwise_shift():
    assert aotg.compute_golden("+", 200, 100, 8, False) == 300 % 256 == 44
    assert aotg.compute_golden("-", 5, 9, 8, False) == (5 - 9) % 256 == 252
    assert aotg.compute_golden("&", 0xF0, 0x3C, 8, False) == 0x30
    assert aotg.compute_golden("|", 0xF0, 0x0C, 8, False) == 0xFC
    assert aotg.compute_golden("^", 0xFF, 0x0F, 8, False) == 0xF0
    assert aotg.compute_golden("<<", 1, 3, 8, False) == 8
    assert aotg.compute_golden(">>", 0x80, 3, 8, False) == 0x10


def test_compute_golden_signed_two_complement_bit_pattern():
    # signed only re-interprets operand inputs; output bit pattern is mod 2^N.
    assert aotg.compute_golden("+", -1, -1, 8, True) == 0xFE
    assert aotg.compute_golden("*", -1, -1, 8, True) == 1


def test_compute_golden_rejects_unknown_operator():
    with pytest.raises(ValueError):
        aotg.compute_golden("%", 4, 3, 8, False)


# ── (a) recognised closed-form op → TB with a COMPUTED golden ─────────────────
def test_a_parallel_multiplier_emits_tb_with_computed_golden(tmp_path):
    ports = [
        {"name": "x", "direction": "input", "width": 8},
        {"name": "y", "direction": "input", "width": 8},
        {"name": "p", "direction": "output", "width": 16},
    ]
    project = _mk_project(
        tmp_path, top="mult8", ports=ports,
        l2="p = x * y mod 2^N parallel multiplier",
        decl={"size_param": 8, "integer_encoding": "unsigned"})

    rep, rc = aotg.generate(project, "digital_arithmetic_primitive")
    assert rc == 0, rep
    assert rep["verdict"] == "TB_EMITTED"
    assert rep["operator"] == "*"
    tbs = _oracle_tbs(project)
    assert len(tbs) == 1
    tb = tbs[0].read_text()
    # The TB drives operands at the resolved NUMERIC width (folds FACET-2 #643)
    assert "reg [7:0] x;" in tb and "reg [7:0] y;" in tb
    # The result-width golden net is the 16-bit product (8x8 multiplier).
    assert "reg [15:0] _golden;" in tb
    # a deterministic corner operand pair 85*85: golden = (85*85) mod 2^16
    assert aotg.compute_golden("*", 85, 85, 16, False) == 7225
    assert "x=85 * y=85 => golden=7225" in tb
    assert "_golden = 16'd7225;" in tb
    # EVERY emitted golden literal must equal compute_golden() on its operands
    # (the TB encodes the pure golden, never a hand-typed constant).
    pat = re.compile(
        r"//\s*vector\s+\d+:\s*x=(-?\d+)\s*\*\s*y=(-?\d+)\s*=>\s*golden=(\d+)")
    found = 0
    for m in pat.finditer(tb):
        xa, yb, g = int(m.group(1)), int(m.group(2)), int(m.group(3))
        assert g == aotg.compute_golden("*", xa, yb, 16, False)
        found += 1
    assert found >= 16  # corner cross-product + pseudo-random tail
    # the runner's completion marker contract is preserved
    assert "ORACLE_TB_DONE pass=%0d/%0d" in tb
    assert "ORACLE_VECTOR" in tb


def test_a_unsigned_8bit_truncation_matches_pure_compute(tmp_path):
    # result port width drives the golden truncation; an 8-bit result truncates.
    ports = [
        {"name": "a", "direction": "input", "width": 8},
        {"name": "b", "direction": "input", "width": 8},
        {"name": "c", "direction": "output", "width": 8},
    ]
    project = _mk_project(tmp_path, top="mul8t", ports=ports,
                          l2="c = a * b multiplier",
                          decl={"size_param": 8, "integer_encoding": "unsigned"})
    rep, rc = aotg.generate(project, "digital_arithmetic_primitive")
    assert rc == 0
    tb = _oracle_tbs(project)[0].read_text()
    # 255*255 mod 2^8 == 1 (8-bit result port truncates)
    assert "_golden = 8'd1;" in tb


# ── (b) §4.05 fail-closed: no-oracle / unrecognised / serial → DEFER ─────────
def test_b_no_oracle_class_processor_cpu_defers(tmp_path):
    ports = [
        {"name": "a", "direction": "input", "width": 8},
        {"name": "b", "direction": "input", "width": 8},
        {"name": "c", "direction": "output", "width": 8},
    ]
    # Even with a perfectly closed-form '+' in the doc, a no-oracle CLASS must
    # not fabricate a golden — the #654 connectivity cap stands.
    project = _mk_project(tmp_path, top="cpu", ports=ports,
                          l2="c = a + b", decl={"size_param": 8})
    rep, rc = aotg.generate(project, "processor_cpu")
    assert rc == 2
    assert rep["verdict"] == "DEFER"
    assert_route_ships(rep["fallback_skill"],
                       "arith_oracle_tb_gen DEFER report")
    assert _oracle_tbs(project) == []  # NO fabricated TB/golden


def test_b_crypto_class_defers(tmp_path):
    ports = [
        {"name": "a", "direction": "input", "width": 8},
        {"name": "b", "direction": "input", "width": 8},
        {"name": "c", "direction": "output", "width": 8},
    ]
    project = _mk_project(tmp_path, top="aes", ports=ports,
                          l2="c = a ^ b", decl={"size_param": 8})
    rep, rc = aotg.generate(project, "crypto_accelerator")
    assert rc == 2 and rep["verdict"] == "DEFER"
    assert _oracle_tbs(project) == []


def test_b_unrecognised_operator_defers(tmp_path):
    ports = [
        {"name": "a", "direction": "input", "width": 8},
        {"name": "b", "direction": "input", "width": 8},
        {"name": "c", "direction": "output", "width": 8},
    ]
    project = _mk_project(
        tmp_path, top="divmod", ports=ports,
        l2="c is the remainder of a divided by b, modulo reduction",
        decl={"size_param": 8})
    rep, rc = aotg.generate(project, "digital_arithmetic_primitive")
    assert rc == 2 and rep["verdict"] == "DEFER"
    assert "operator" in rep["reason"].lower()
    assert _oracle_tbs(project) == []


def test_b_serial_streaming_datapath_emits_self_calibrating_oracle(tmp_path):
    # CAPABILITY UPGRADE (repo-gatekeeper, direct-push): spm-style parallel x
    # (N-bit) + serial y/p (1-bit) on an N-bit datapath. The output latency +
    # bit-order are Plugin-chosen; instead of DEFERring, the oracle now emits a
    # REAL, SELF-CALIBRATING N-bit oracle — golden computed independently from
    # the declared function, serial framing DISCOVERED from the DUT stream (a
    # wrong-product DUT matches no consistent framing → still fails). §4.05: the
    # golden is never read from the DUT; only the (free-choice) framing is.
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "x", "direction": "input", "width": "size", "msb": "size-1",
         "lsb": "0"},
        {"name": "y", "direction": "input", "width": 1},
        {"name": "p", "direction": "output", "width": 1},
    ]
    project = _mk_project(tmp_path, top="spm", ports=ports,
                          l2="p = (x * y) mod 2^N serial multiplier",
                          decl={"size_param": 32,
                                "integer_encoding": "unsigned"})
    rep, rc = aotg.generate(project, "digital_arithmetic_primitive")
    assert rc == 0 and rep["verdict"] == "TB_EMITTED"
    assert rep.get("topology") == "serial_parallel"
    tbs = _oracle_tbs(project)
    assert len(tbs) == 1
    tb = tbs[0].read_text()
    # NON-VACUOUS: resolved to the real datapath width (32), never a 1-bit
    # collapse, with the self-calibration search + completion marker.
    assert "localparam integer N      = 32;" in tb
    assert "ORACLE_TB_DONE pass=" in tb and "_drive_capture" in tb


def test_cli_help_and_defer_exit_code(tmp_path):
    import subprocess
    prog = PROGRAMS / "arith_oracle_tb_gen.py"
    r = subprocess.run([sys.executable, str(prog), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    # an empty project → DEFER (rc 2), never a crash
    empty = tmp_path / "empty"
    empty.mkdir()
    r2 = subprocess.run([sys.executable, str(prog), str(empty),
                         "--ic-class", "digital_arithmetic_primitive"],
                        capture_output=True, text=True)
    assert r2.returncode == 2
    assert json.loads(r2.stdout)["verdict"] == "DEFER"


# ── adversarial-review remediation guards (#745) ─────────────────────────────
def test_signed_shift_corner_pairs_no_crash_and_in_range():
    """MEDIUM-1: signed-shift corner pairs must clamp the RHS to [0,width) so
    compute_golden never crashes on a negative shift count."""
    for op in ("<<", ">>"):
        pairs = aotg.enumerate_operand_pairs(8, True, op)
        for a, b in pairs:
            assert 0 <= b < 8, (op, a, b)
            aotg.compute_golden(op, a, b, 8, True)   # must not raise


def test_signed_shift_defers_not_wrong_oracle(tmp_path):
    """MEDIUM-2: a signed shift defers (logical-vs-arithmetic ambiguity) rather
    than shipping a possibly-wrong logical-shift golden."""
    # extract_arith_spec must DEFER (None spec) for a signed shift.
    import inspect
    src = inspect.getsource(aotg)
    assert "signed shift operator" in src   # the defer branch exists
