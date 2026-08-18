"""Unit tests for sv_compat_check.py.

Each test synthesizes small Verilog/SystemVerilog snippets and verifies the
checker correctly identifies (or ignores) SV constructs requiring -sv flag.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'sv_compat_check.py'
assert SCRIPT.exists()

sys.path.insert(0, str(SCRIPT.parent))
import sv_compat_check as svc  # noqa: E402


def run_cli(tmp_path, files: dict, extra_args=None):
    """Write files to tmp_path/rtl/, run CLI, return (result, report_dict)."""
    rtl_dir = tmp_path / 'rtl'
    rtl_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (rtl_dir / name).write_text(content)
    out_dir = tmp_path / 'out'
    cmd = [sys.executable, str(SCRIPT), '--rtl-dir', str(rtl_dir),
           '--out-dir', str(out_dir)]
    if extra_args:
        cmd.extend(extra_args)
    res = subprocess.run(cmd, capture_output=True, text=True)
    report_path = out_dir / 'sv_compat_report.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else None
    return res, report


class TestPureVerilog:
    """Pure Verilog-2001 files should PASS (exit 0)."""

    def test_simple_module(self, tmp_path):
        sv = """\
module counter(
    input wire clk,
    input wire rst_n,
    output reg [7:0] count
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            count <= 8'd0;
        else
            count <= count + 8'd1;
    end
endmodule
"""
        res, report = run_cli(tmp_path, {'counter.v': sv})
        assert res.returncode == 0, f"Expected exit 0, got {res.returncode}: {res.stderr}"
        assert report['needs_sv'] is False
        assert report['recommendation'] == 'Plain Verilog OK'
        assert len(report['sv_constructs_found']) == 0

    def test_assign_and_wire(self, tmp_path):
        sv = """\
module mux(input wire a, input wire b, input wire sel, output wire y);
    assign y = sel ? a : b;
endmodule
"""
        res, report = run_cli(tmp_path, {'mux.v': sv})
        assert res.returncode == 0
        assert report['needs_sv'] is False


class TestLogicType:
    """Files using `logic` type need -sv."""

    def test_logic_port(self, tmp_path):
        sv = """\
module top(
    input logic clk,
    input logic rst_n,
    output logic [7:0] data_out
);
    always_ff @(posedge clk)
        data_out <= 8'd0;
endmodule
"""
        res, report = run_cli(tmp_path, {'top.sv': sv})
        assert res.returncode == 1
        assert report['needs_sv'] is True
        constructs = [f['construct'] for f in report['sv_constructs_found']]
        assert 'logic_type' in constructs

    def test_logic_declaration(self, tmp_path):
        sv = """\
module m(input wire clk);
    logic [3:0] state;
endmodule
"""
        res, report = run_cli(tmp_path, {'m.v': sv})
        assert res.returncode == 1
        assert any(f['construct'] == 'logic_type'
                   for f in report['sv_constructs_found'])


class TestAlwaysFF:
    """Files using always_ff / always_comb need -sv."""

    def test_always_ff(self, tmp_path):
        sv = """\
module ff(input wire clk, input wire d, output reg q);
    always_ff @(posedge clk)
        q <= d;
endmodule
"""
        res, report = run_cli(tmp_path, {'ff.v': sv})
        assert res.returncode == 1
        constructs = [f['construct'] for f in report['sv_constructs_found']]
        assert 'always_ff' in constructs

    def test_always_comb(self, tmp_path):
        sv = """\
module comb(input wire [1:0] sel, output reg [3:0] y);
    always_comb begin
        case (sel)
            2'b00: y = 4'd1;
            2'b01: y = 4'd2;
            default: y = 4'd0;
        endcase
    end
endmodule
"""
        res, report = run_cli(tmp_path, {'comb.v': sv})
        assert res.returncode == 1
        assert any(f['construct'] == 'always_comb'
                   for f in report['sv_constructs_found'])


class TestLocalDeclaration:
    """Local declarations of SV types inside always blocks need -sv."""

    def test_logic_inside_always(self, tmp_path):
        sv = """\
module m(input wire clk);
    reg [7:0] count;
    always @(posedge clk) begin
        logic [7:0] temp;
        temp = count + 1;
        count <= temp;
    end
endmodule
"""
        res, report = run_cli(tmp_path, {'m.v': sv})
        assert res.returncode == 1
        constructs = [f['construct'] for f in report['sv_constructs_found']]
        # Should detect both `logic` type and local declaration
        assert any('local_' in c for c in constructs) or 'logic_type' in constructs

    def test_int_inside_initial(self, tmp_path):
        sv = """\
module tb;
    initial begin
        int i;
        for (i = 0; i < 10; i = i + 1) begin
            $display("i=%0d", i);
        end
    end
endmodule
"""
        res, report = run_cli(tmp_path, {'tb.v': sv})
        assert res.returncode == 1
        constructs = [f['construct'] for f in report['sv_constructs_found']]
        assert any('local_int' in c for c in constructs)


class TestMixedFiles:
    """Directory with mix of plain Verilog and SystemVerilog files."""

    def test_mixed_directory(self, tmp_path):
        pure_v = """\
module simple(input wire a, output wire b);
    assign b = ~a;
endmodule
"""
        sv_file = """\
module complex(input logic clk, output logic [7:0] out);
    always_ff @(posedge clk) out <= out + 1;
endmodule
"""
        res, report = run_cli(tmp_path, {
            'simple.v': pure_v,
            'complex.sv': sv_file,
        })
        assert res.returncode == 1
        assert report['needs_sv'] is True
        # Only the SV file should have findings
        files_with_findings = {f['file'] for f in report['sv_constructs_found']}
        assert any('complex.sv' in f for f in files_with_findings)
        # simple.v should have no findings
        assert not any(
            'simple.v' in f['file'] and f['construct'] in ('logic_type', 'always_ff')
            for f in report['sv_constructs_found']
        )


class TestEmptyDirectory:
    """Empty directory should report plain Verilog OK."""

    def test_empty_dir(self, tmp_path):
        res, report = run_cli(tmp_path, {})
        assert res.returncode == 0
        assert report['needs_sv'] is False
        assert len(report['sv_constructs_found']) == 0


class TestAdditionalConstructs:
    """Test detection of typedef, enum, struct, union, import, unique case."""

    def test_typedef_enum(self, tmp_path):
        sv = """\
module fsm(input wire clk, input wire rst_n);
    typedef enum logic [1:0] {
        IDLE  = 2'b00,
        BUSY  = 2'b01,
        DONE  = 2'b10
    } state_t;
    state_t state;
endmodule
"""
        res, report = run_cli(tmp_path, {'fsm.sv': sv})
        assert res.returncode == 1
        constructs = [f['construct'] for f in report['sv_constructs_found']]
        assert 'typedef' in constructs
        assert 'enum' in constructs

    def test_import_package(self, tmp_path):
        sv = """\
import my_pkg::*;
module m(input wire clk);
endmodule
"""
        res, report = run_cli(tmp_path, {'m.sv': sv})
        assert res.returncode == 1
        constructs = [f['construct'] for f in report['sv_constructs_found']]
        assert 'import_package' in constructs

    def test_unique_case(self, tmp_path):
        sv = """\
module m(input wire [1:0] sel, output reg y);
    always @(*) begin
        unique case (sel)
            2'b00: y = 1'b0;
            2'b01: y = 1'b1;
            default: y = 1'b0;
        endcase
    end
endmodule
"""
        res, report = run_cli(tmp_path, {'m.v': sv})
        assert res.returncode == 1
        constructs = [f['construct'] for f in report['sv_constructs_found']]
        assert 'unique_case' in constructs

    def test_comments_ignored(self, tmp_path):
        """SV constructs inside comments should not be detected."""
        sv = """\
module m(input wire clk, output reg q);
    // always_ff is not used here
    /* logic foo; */
    always @(posedge clk) q <= 1'b0;
endmodule
"""
        res, report = run_cli(tmp_path, {'m.v': sv})
        assert res.returncode == 0
        assert report['needs_sv'] is False


class TestScanFileAPI:
    """Test the scan_file function directly."""

    def test_scan_nonexistent_file(self, tmp_path):
        findings = svc.scan_file(tmp_path / 'nonexistent.v')
        assert findings == []

    def test_build_report_empty(self):
        report = svc.build_report([])
        assert report['needs_sv'] is False
        assert report['total_constructs'] == 0
