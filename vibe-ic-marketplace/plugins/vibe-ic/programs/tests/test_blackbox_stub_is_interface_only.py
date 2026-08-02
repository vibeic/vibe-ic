"""A hard-macro blackbox stub must be INTERFACE-ONLY.

`(* blackbox *)` is applied by the frontend AFTER it has parsed the module, so
attributing a vendor behavioural model without dropping its body leaves every
unsynthesizable construct in that body fatal to the read. The whole
`read_verilog` then aborts, no miter is built, and the equivalence step reports
"no evidence" for what is really an unparsed stub.

These tests pin the shape, not any particular vendor model: a behavioural body
carrying `realtime` / `time` declarations, delays and system tasks must not
survive into the stub, while the port INTERFACE (including widths that
reference preprocessor macros) must.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _hardmacro_stage import emit_blackbox_stub  # noqa: E402


# Non-ANSI header + macro-parameterised widths + a body full of constructs a
# synthesis frontend rejects. Shape-only: no vendor / chip / PDK literal.
_NON_ANSI_MODEL = """\
`define W_ADDR 7
`define W_DATA 8

module MACRO_A( ADDR,
                DIN,
                DOUT,
                WE,
                VDDX,
                VSSX );
parameter mem_file = "image.dat";
input  [`W_ADDR - 1:0] ADDR;
input  [`W_DATA - 1:0] DIN;
output [`W_DATA - 1:0] DOUT;
input                  WE;
input                  VDDX;
input                  VSSX;

reg [`W_DATA-1:0] core [0:(1<<`W_ADDR)-1];
realtime          rd_up_time;
realtime          rd_pulse_width;
time              power_up_time;

always @(posedge WE) begin
    #1 core[ADDR] <= DIN;
    $display("write %h", DIN);
end
specify
    (ADDR => DOUT) = (1.0, 1.0);
endspecify
endmodule
"""

_ANSI_MODEL = """\
module MACRO_B (input wire CK, input wire [3:0] A, output reg [7:0] Q);
  realtime t_acc;
  always @(posedge CK) #2 Q <= A;
endmodule
"""

_TWO_MODULES = _NON_ANSI_MODEL + "\n" + _ANSI_MODEL


def _emit(tmp_path: Path, text: str, name: str = "MACRO_A") -> str:
    src = tmp_path / "model.v"
    src.write_text(text)
    return emit_blackbox_stub(src, name, tmp_path / "bb").read_text()


def test_body_constructs_are_dropped(tmp_path: Path) -> None:
    out = _emit(tmp_path, _NON_ANSI_MODEL)
    for banned in ("realtime", "time ", "always", "$display", "specify",
                   "endspecify", "reg [", "parameter mem_file"):
        assert banned not in out, f"body construct {banned!r} survived into stub"


def test_interface_survives(tmp_path: Path) -> None:
    out = _emit(tmp_path, _NON_ANSI_MODEL)
    assert "(* blackbox *)" in out
    assert re.search(r"\bmodule\s+MACRO_A\b", out)
    assert out.rstrip().endswith("endmodule")
    for port in ("ADDR", "DIN", "DOUT", "WE", "VDDX", "VSSX"):
        assert re.search(rf"\b{port}\b", out), f"port {port} lost"
    # Widths reference macros, so the `define lines must be hoisted with them.
    assert "`define W_ADDR" in out and "`define W_DATA" in out
    assert "`W_ADDR - 1:0" in out and "`W_DATA - 1:0" in out


def test_ansi_header_keeps_its_inline_directions(tmp_path: Path) -> None:
    out = _emit(tmp_path, _ANSI_MODEL, name="MACRO_B")
    assert "realtime" not in out and "always" not in out
    assert "input wire CK" in out and "output reg [7:0] Q" in out
    # An ANSI port list already carries directions — they must not be doubled.
    assert out.count("input wire CK") == 1


def test_every_module_in_a_multi_module_model_is_stubbed(tmp_path: Path) -> None:
    out = _emit(tmp_path, _TWO_MODULES)
    assert out.count("(* blackbox *)") == 2
    assert re.search(r"\bmodule\s+MACRO_A\b", out)
    assert re.search(r"\bmodule\s+MACRO_B\b", out)
    assert "realtime" not in out and "$display" not in out


def test_unrecognised_shape_falls_back_to_attribute_only(tmp_path: Path) -> None:
    """No parseable module header → keep the previous behaviour rather than
    emitting an empty file (an input that worked before must not regress)."""
    text = "// nothing but a comment\n"
    out = _emit(tmp_path, text)
    assert out == text


@pytest.mark.skipif(not __import__("shutil").which("yosys"),
                    reason="yosys not on PATH")
def test_stub_actually_parses_in_yosys(tmp_path: Path) -> None:
    """The point of the change: the frontend must get through the stub. The
    un-stubbed model is checked too, so this fails loudly if the fixture stops
    reproducing the condition."""
    bb = tmp_path / "bb" / "MACRO_A.bb.v"
    _emit(tmp_path, _NON_ANSI_MODEL)

    ok = subprocess.run(["yosys", "-p", f"read_verilog {bb}"],
                        capture_output=True, text=True)
    assert ok.returncode == 0, f"stub did not parse:\n{ok.stderr[-2000:]}"

    raw = tmp_path / "model.v"
    bad = subprocess.run(["yosys", "-p", f"read_verilog {raw}"],
                         capture_output=True, text=True)
    assert bad.returncode != 0, (
        "fixture no longer reproduces the condition: the raw behavioural model "
        "parsed cleanly, so this test would pass even without the fix")
