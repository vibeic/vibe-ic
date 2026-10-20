"""Issue #3378: predicate admission needs producer-owned word-domain proof."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


PROGRAM = Path(__file__).resolve().parents[1] / "interface_encoding_audit.py"


def _run(tmp_path: Path, source: str) -> dict:
    rtl = tmp_path / "rtl"
    out = tmp_path / "out"
    rtl.mkdir()
    (rtl / "neutral.v").write_text(source)
    result = subprocess.run(
        [sys.executable, str(PROGRAM), "--rtl-dir", str(rtl),
         "--top-module", "neutral", "-I", str(rtl),
         "--out-dir", str(out)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((out / "encoding_audit_report.json").read_text())


def _edge(report: dict) -> dict:
    rows = [row for row in report["interfaces"]
            if row["wire_name"] == "link"
            and row["producer_module"] == "producer"
            and row["consumer_module"] == "consumer"]
    assert len(rows) == 1, report
    return rows[0]


def _serial_source(expression: str) -> str:
    return f"""
module producer(input [2:0] data, input [1:0] phase, output flag);
  wire [2:0] gray = data ^ (data >> 1);
  assign flag = {expression};
endmodule
module consumer(input clk, rst, flag, input [1:0] phase,
                output reg [2:0] value);
  always @(posedge clk) begin
    if (rst) value <= 3'b000;
    else if (flag) value[phase] <= 1'b1;
    else value[phase] <= 1'b0;
  end
endmodule
module neutral(input clk, rst, input [2:0] data, input [1:0] phase,
               output [2:0] value);
  wire link;
  producer source(.data(data), .phase(phase), .flag(link));
  consumer sink(.clk(clk), .rst(rst), .flag(link), .phase(phase), .value(value));
endmodule
"""


@pytest.mark.parametrize("expression", [
    "gray[phase]",
    "(gray >> phase) & 1'b1",
    "(phase == 0) ? gray[0] : (phase == 1) ? gray[1] : gray[2]",
    "(gray[phase] == 1'b1)",
])
def test_bit_serial_word_cannot_be_promoted_from_consumer_syntax(tmp_path, expression):
    row = _edge(_run(tmp_path, _serial_source(expression)))
    assert row["producer_encoding"] == "UNKNOWN", row
    assert row["consumer_encoding"] != "PREDICATE", row
    assert row["status"] == "UNKNOWN", row


def test_actual_one_bit_source_domain_keeps_predicate_proof(tmp_path):
    report = _run(tmp_path, """
module producer(input seed, output flag);
  assign flag = ~seed;
endmodule
module consumer(input flag, output reg seen);
  always @* if (flag) seen = 1'b1;
endmodule
module neutral(input seed, output seen);
  wire link;
  producer source(.seed(seed), .flag(link));
  consumer sink(.flag(link), .seen(seen));
endmodule
""")
    row = _edge(report)
    assert row["producer_encoding"] == "BIT_VALUE", row
    assert "one-bit source domain" in row["producer_evidence"], row
    assert row["consumer_encoding"] == "PREDICATE", row
    assert row["status"] == "MATCH", row
