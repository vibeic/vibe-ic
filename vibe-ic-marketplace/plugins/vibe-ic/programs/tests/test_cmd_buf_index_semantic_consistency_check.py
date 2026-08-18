"""tests/test_cmd_buf_index_semantic_consistency_check.py
Wave 37 (v0.119.69) — BACKLOG v0.119.70 Item 2.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "cmd_buf_index_semantic_consistency_check.py"
)


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make_aid_l_docs(project: Path,
                      payload_semantics_offset: int = 1) -> None:
    """Write minimal L1/L2/L3/L9 with an opcode 0xE2 whose
    payload_semantics places `addr` at byte_offset = `payload_semantics_offset`."""
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "interface": "EXAMPLE_PROTOCOL single-wire half-duplex",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "protocol_type": "single_wire_half_duplex",
    }))
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "physical_layer": "EXAMPLE_PROTOCOL half-duplex single-wire",
        "opcodes": [
            {
                "hex": "0xE2",
                "name": "WRITE",
                "payload_semantics": [
                    {"byte_offset": 0, "value": "0xE2",
                     "description": "opcode"},
                    {"byte_offset": payload_semantics_offset,
                     "source": "argument", "field": "addr"},
                    {"byte_offset": 3 - payload_semantics_offset,
                     "source": "argument", "field": "len"},
                ],
            },
            {
                "hex": "0x74",
                "name": "GET_ID",
                "payload_semantics": [
                    {"byte_offset": 0, "value": "0x74",
                     "description": "opcode"},
                ],
            },
        ],
    }))
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "fsm_states": [{"name": "IDLE"}],
    }))


def _main_fsm_with_buf_read(addr_idx: int = 1, len_idx: int = 2) -> str:
    return f"""
module main_fsm(
    input clk, input rst,
    input [7:0] op,
    input [7:0] cmd_buf [0:7],
    output reg [7:0] addr,
    output reg [7:0] len,
    output reg [3:0] state
);
    localparam S_IDLE = 4'd0;
    localparam S_RX_DATA = 4'd1;
    always_ff @(posedge clk) begin
        if (rst) state <= S_IDLE;
        else case (op)
            8'hE2: begin
                addr <= cmd_buf[{addr_idx}];
                len  <= cmd_buf[{len_idx}];
                state <= S_RX_DATA;
            end
            default: state <= S_IDLE;
        endcase
    end
endmodule
"""


# -------------------------------------------------------------------
# 1. Positive PASS — RTL index matches L3 byte_offset
# -------------------------------------------------------------------
def test_pass_index_matches(tmp_path: Path):
    project = tmp_path / "aid_pass"
    project.mkdir(parents=True, exist_ok=True)
    _make_aid_l_docs(project, payload_semantics_offset=1)
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "main_fsm.sv").write_text(_main_fsm_with_buf_read(1, 2))
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# -------------------------------------------------------------------
# 2. Positive FAIL — RTL reads cmd_buf[2] for addr but L3 says addr
#    is at byte_offset 1 (a real swap; lhs=addr, idx=2 vs L3=1).
# -------------------------------------------------------------------
def test_fail_index_swap(tmp_path: Path):
    project = tmp_path / "aid_fail"
    project.mkdir(parents=True, exist_ok=True)
    _make_aid_l_docs(project, payload_semantics_offset=1)
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    # RTL drives addr from cmd_buf[2] but L3 says addr is byte 1.
    (rtl / "main_fsm.sv").write_text(_main_fsm_with_buf_read(2, 1))
    r = _run(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "byte_offset" in r.stdout


# -------------------------------------------------------------------
# 3. SKIP for non-applicable IC (pure_analog)
# -------------------------------------------------------------------
def test_skip_pure_analog(tmp_path: Path):
    project = tmp_path / "pmic"
    project.mkdir(parents=True, exist_ok=True)
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "PMIC-X", "interface": "pure analog",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "PMIC-X", "interface": "pure analog",
    }))
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "ic_name": "PMIC-X",
        "analog_blocks": [{"name": "BANDGAP_REF"}],
    }))
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# -------------------------------------------------------------------
# 4. SKIP — L3 has no payload_semantics typed
# -------------------------------------------------------------------
def test_skip_l3_no_payload_semantics(tmp_path: Path):
    project = tmp_path / "aid_no_sem"
    project.mkdir(parents=True, exist_ok=True)
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "interface": "EXAMPLE_PROTOCOL single-wire half-duplex",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "protocol_type": "single_wire_half_duplex",
    }))
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "physical_layer": "EXAMPLE_PROTOCOL half-duplex single-wire",
        "opcodes": [{"hex": "0xE2", "name": "WRITE"}],  # no payload_semantics
    }))
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "fsm_states": [{"name": "IDLE"}],
    }))
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "main_fsm.sv").write_text(_main_fsm_with_buf_read(2, 1))
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# -------------------------------------------------------------------
# 5. Edge — autodetect when L9 omits cmd_buffer_signal_name
# -------------------------------------------------------------------
def test_pass_autodetect_buf_name(tmp_path: Path):
    project = tmp_path / "aid_auto"
    project.mkdir(parents=True, exist_ok=True)
    _make_aid_l_docs(project, payload_semantics_offset=1)
    # L9 does NOT carry cmd_buffer_signal_name; auto-detect must
    # pick cmd_buf from the reg array decl.
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "main_fsm.sv").write_text(
        "module main_fsm(input clk, input [7:0] op);\n"
        "    reg [7:0] cmd_buf [0:7];\n"
        "    reg [7:0] addr;\n"
        "    reg [7:0] len;\n"
        "    reg [3:0] state;\n"
        "    always_ff @(posedge clk) case (op)\n"
        "        8'hE2: begin\n"
        "            addr <= cmd_buf[1];\n"
        "            len  <= cmd_buf[2];\n"
        "            state <= 4'd1;\n"
        "        end\n"
        "    endcase\n"
        "endmodule\n"
    )
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# -------------------------------------------------------------------
# 6. Comment vs code disagreement
# -------------------------------------------------------------------
def test_fail_comment_vs_code(tmp_path: Path):
    project = tmp_path / "aid_cmt_swap"
    project.mkdir(parents=True, exist_ok=True)
    _make_aid_l_docs(project, payload_semantics_offset=1)
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    # Code reads cmd_buf[1] for addr (matches L3=1, OK), AND has
    # comment claiming `cmd_buf[2] = addr` (contradicts L3=1).
    (rtl / "main_fsm.sv").write_text(
        "module main_fsm(input clk, input [7:0] op,\n"
        "                input [7:0] cmd_buf [0:7]);\n"
        "    reg [7:0] addr; reg [7:0] len;\n"
        "    reg [3:0] state;\n"
        "    always_ff @(posedge clk) case (op)\n"
        "        8'hE2: begin\n"
        "            // cmd_buf[2]=addr, cmd_buf[1]=len  (note swap)\n"
        "            addr <= cmd_buf[1];\n"
        "            len  <= cmd_buf[2];\n"
        "            state <= 4'd1;\n"
        "        end\n"
        "    endcase\n"
        "endmodule\n"
    )
    r = _run(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "swap" in r.stdout.lower()


# -------------------------------------------------------------------
# 7. SKIP no main_fsm
# -------------------------------------------------------------------
def test_skip_no_main_fsm(tmp_path: Path):
    project = tmp_path / "aid_no_fsm"
    project.mkdir(parents=True, exist_ok=True)
    _make_aid_l_docs(project, payload_semantics_offset=1)
    # No RTL files
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# -------------------------------------------------------------------
# 8. Wave 42 / MF1 — unknown class with cmd_buf semantic mismatch
#    must NOT auto-SKIP on ic_class.
# -------------------------------------------------------------------
def test_unknown_class_fail_closed_when_evidence_present(tmp_path: Path):
    """L3 has typed payload_semantics + RTL reads cmd_buf with swapped
    indices, but ic_class detection returns `unknown` (no L1/L2). Gate
    must fall through to FAIL — not auto-SKIP on ic_class."""
    project = tmp_path / "unknown_evidence"
    project.mkdir(parents=True, exist_ok=True)
    # Strip L1/L2 → unknown class.
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    # Only L3 present (typed) and L9 absent — detect_ic_class returns
    # bare_fpga or unknown depending on presence flags. We only assert
    # the SKIP message line for ic_class=unknown not in applicable set
    # is absent.
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "ic_name": "Unknown-X",
        "opcodes": [
            {
                "hex": "0xE2", "name": "WRITE",
                "payload_semantics": [
                    {"byte_offset": 0, "value": "0xE2"},
                    {"byte_offset": 1, "source": "argument",
                     "field": "addr"},
                    {"byte_offset": 2, "source": "argument",
                     "field": "len"},
                ],
            },
        ],
    }))
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "main_fsm.sv").write_text(_main_fsm_with_buf_read(2, 1))
    r = _run(project)
    out = r.stdout + r.stderr
    # The pre-Wave-42 vulnerability would have printed
    # "SKIP — ic_class=unknown not in applicable set".
    assert "SKIP — ic_class=unknown not in applicable set" not in out, (
        f"MF1 broken: unknown class auto-SKIPped\n{out}")
