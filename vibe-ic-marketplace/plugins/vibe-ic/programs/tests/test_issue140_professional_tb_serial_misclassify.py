"""#140 — professional_tb_gen must NOT mis-classify a register-mapped / crypto
accelerator as a serial-multiply datapath.

Root cause: `_detect_stream_operator` false-fired `*` on L1 metadata (`product_*`
field names, "Product & Tapeout Metadata" title) and a crypto MAC acronym
("security MAC"), and `classify_dut` then read a memory-mapped register file
(address + write_data/read_data + cs/we + error) as (x*y) serial-multiply.

§4.05 no-leak: a genuine bit-serial multiplier (spm-shaped) must STILL classify
as serial_stream.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import professional_tb_gen as T  # noqa: E402


def _mk_sha256(tmp: Path) -> Path:
    """A register-mapped crypto accelerator: address bus + write/read data +
    cs/we control + error status. L1 carries the metadata tokens that used to
    false-fire the multiply operator (`product_*`, "security MAC")."""
    gd = tmp / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_module": "sha256",
        "top_ports": [
            {"name": "clk", "dir": "input", "width": 1},
            {"name": "reset_n", "dir": "input", "width": 1},
            {"name": "cs", "dir": "input", "width": 1},
            {"name": "we", "dir": "input", "width": 1},
            {"name": "address", "dir": "input", "width": 8},
            {"name": "write_data", "dir": "input", "width": 32},
            {"name": "read_data", "dir": "output", "width": 32},
            {"name": "error", "dir": "output", "width": 1}],
        "clocks": [{"name": "clk", "edge": "posedge", "period_ns": 10}],
        "reset_domains": [{"name": "reset_n", "polarity": "active_low"}]}}))
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"fields": {
        "title": "L1 — Product & Tapeout Metadata",
        "product_name": "sha256-core", "product_family": "crypto",
        "market": "IoT / security MAC"}}))
    rtl = tmp / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "sha256.v").write_text(
        "module sha256(input clk, reset_n, cs, we, input [7:0] address,"
        " input [31:0] write_data, output [31:0] read_data, output error);"
        "endmodule\n")
    return tmp


def _mk_spm(tmp: Path) -> Path:
    """A genuine bit-serial multiplier: parallel x bus + 1-bit serial y + 1-bit
    serial product p, prose declaring the multiply."""
    gd = tmp / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_module": "spm",
        "top_ports": [
            {"name": "clk", "dir": "input", "width": 1},
            {"name": "rst", "dir": "input", "width": 1},
            {"name": "x", "dir": "input"},              # parametric bus
            {"name": "y", "dir": "input", "width": 1},
            {"name": "p", "dir": "output", "width": 1}],
        "clocks": [{"name": "clk", "edge": "posedge", "period_ns": 10}],
        "reset_domains": [{"name": "rst", "polarity": "active_high"}]}}))
    (gd / "L2_FRS.json").write_text(json.dumps({"frs_sections": [
        {"title": "Function",
         "content": "serial-parallel multiplier p = (x * y) mod 2^N"}]}))
    rtl = tmp / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "spm.v").write_text(
        "module spm #(parameter size = 32)(input clk, rst,"
        " input [size-1:0] x, input y, output p); endmodule\n")
    return tmp


# ── the false-fire is gone ────────────────────────────────────────────────
def test_sha256_operator_not_detected_for_crypto(tmp_path):
    proj = _mk_sha256(tmp_path)
    # crypto_accelerator is a register-mapped/command-driven class → no operator
    assert T._detect_stream_operator(proj, "crypto_accelerator") is None
    # even mis-classed as unknown, the metadata tokens alone must not fire it
    assert T._detect_stream_operator(proj, "unknown_protocol_class") is None


def test_sha256_classifies_generic_not_serial(tmp_path):
    proj = _mk_sha256(tmp_path)
    shape, _ = T.classify_dut(proj, "crypto_accelerator")
    assert shape["kind"] == "generic"
    # structural guard is class-independent: even if the class detector is wrong
    shape_unk, _ = T.classify_dut(proj, "unknown_protocol_class")
    assert shape_unk["kind"] == "generic"


def test_register_map_signature_detected(tmp_path):
    ins = [{"name": "cs"}, {"name": "we"}, {"name": "address"},
           {"name": "write_data"}]
    outs = [{"name": "read_data"}, {"name": "error"}]
    assert T._is_register_mapped(ins, outs) is True
    # a bare datapath (x,y → p) is NOT register-mapped
    assert T._is_register_mapped([{"name": "x"}, {"name": "y"}],
                                 [{"name": "p"}]) is False


def test_ctrl_status_ports_excluded_as_serial_operands(tmp_path):
    for n in ("cs", "we", "error", "irq", "wr_en", "data_valid", "parity_err"):
        assert T._is_ctrl_status(n), n
    for n in ("x", "y", "p", "din", "mosi", "serial_in"):
        assert not T._is_ctrl_status(n), n


def test_multiplexer_does_not_false_fire(tmp_path):
    # a clock/data MULTIPLEXER is not a multiply datapath
    assert not T._STREAM_MUL_RE.search("a 4:1 clock multiplexer / mux tree")
    assert not T._STREAM_MUL_RE.search("product_name product_family metadata")
    assert not T._STREAM_MUL_RE.search("message authentication code (mac)")
    # genuine multiply evidence DOES fire
    assert T._STREAM_MUL_RE.search("bit-serial multiplier partial product")
    assert T._STREAM_MUL_RE.search("multiply-accumulate datapath")


# ── §4.05 no-leak: the genuine serial multiplier still classifies ─────────
def test_spm_still_serial_stream(tmp_path):
    proj = _mk_spm(tmp_path)
    assert T._detect_stream_operator(proj, "digital_arithmetic_primitive") == "*"
    shape, why = T.classify_dut(proj, "digital_arithmetic_primitive")
    assert shape is not None, why
    assert shape["kind"] == "serial_stream"
    assert shape["x_port"] == "x" and shape["y_port"] == "y"
    assert shape["p_port"] == "p" and shape["operator"] == "*"
