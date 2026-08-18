"""Unit tests for module_port_audit.py.

Each test synthesizes Verilog snippets representing multi-module designs
and verifies the audit correctly detects port mismatches, unconnected ports,
width mismatches, and handles edge cases like .* and parameterized modules.

Covers the v0.36 failure pattern: DTOP integration module connecting ports
that don't exist in submodule definitions.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'module_port_audit.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import module_port_audit as mpa  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: parse modules from a string
# ---------------------------------------------------------------------------
def parse_from_string(sv_content: str, file_path: str = 'test.sv'):
    """Parse all modules from a Verilog string and return module defs dict."""
    src = mpa.strip_comments(sv_content)
    modules = mpa.parse_modules(src, file_path)
    return {m.name: m for m in modules}


def audit_from_string(sv_content: str, top_module: str = None):
    """Parse and audit a Verilog string, return findings."""
    defs = parse_from_string(sv_content)
    return mpa.audit_design(defs, top_module)


def run_cli(tmp_path, sv_files: dict, args_extra=None):
    """
    Write multiple .sv files to tmp_path, run CLI, return (result, report_dict).
    sv_files: dict of filename -> content
    """
    file_paths = []
    for name, content in sv_files.items():
        f = tmp_path / name
        f.write_text(content)
        file_paths.append(str(f))

    cmd = [sys.executable, str(SCRIPT),
           '--files'] + file_paths + [
           '--json', str(tmp_path / 'report.json')]
    if args_extra:
        cmd.extend(args_extra)

    res = subprocess.run(cmd, capture_output=True, text=True)
    report = {}
    report_file = tmp_path / 'report.json'
    if report_file.exists():
        report = json.loads(report_file.read_text())
    return res, report


# ===========================================================================
# Test 1: All ports match (clean design — no findings)
# ===========================================================================
class TestCleanDesign:
    def test_all_ports_match_no_findings(self):
        """When all instantiation ports match module definitions, 0 findings."""
        sv = """
module sub_a(
    input wire clk,
    input wire rst_n,
    output wire [7:0] data_out
);
    assign data_out = 8'hAB;
endmodule

module top(
    input wire clk,
    input wire rst_n,
    output wire [7:0] result
);
    sub_a u_sub_a (
        .clk(clk),
        .rst_n(rst_n),
        .data_out(result)
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        assert len(findings) == 0, f"Expected 0 findings, got: {findings}"

    def test_clean_design_cli(self, tmp_path):
        """CLI returns exit code 0 for clean design."""
        sv = """
module child(input wire a, output wire b);
    assign b = a;
endmodule

module parent(input wire x, output wire y);
    child u0 (.a(x), .b(y));
endmodule
"""
        res, report = run_cli(tmp_path, {'design.sv': sv},
                              args_extra=['--top-module', 'parent'])
        assert res.returncode == 0
        assert report['summary']['errors'] == 0
        assert report['summary']['mismatches'] == 0


# ===========================================================================
# Test 2: Missing port in instance (MISMATCH) — the v0.36 bug
# ===========================================================================
class TestMismatchMissingPort:
    def test_instance_references_nonexistent_port(self):
        """The exact v0.36 pattern: DTOP connects .sys_clk_5m but DCLK has no such port."""
        sv = """
module DCLK(
    input wire clk_in,
    input wire rst_n,
    output wire clk_5m
);
    assign clk_5m = clk_in;
endmodule

module DTOP(
    input wire clk,
    input wire rst_n,
    output wire sys_clk_5m
);
    wire clk_5m_internal;

    DCLK u_clk (
        .sys_clk_5m(clk_5m_internal),
        .rst_n(rst_n),
        .clk_5m(sys_clk_5m)
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='DTOP')
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) >= 1
        assert any(f.port == 'sys_clk_5m' for f in mismatches), \
            f"Expected mismatch on 'sys_clk_5m', got: {[f.port for f in mismatches]}"

    def test_mismatch_includes_available_ports(self):
        """Error message should list available ports for debugging."""
        sv = """
module sub(input wire a, output wire b);
    assign b = a;
endmodule

module top(input wire x, output wire y);
    sub u0 (.wrong_port(x), .b(y));
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) == 1
        assert 'wrong_port' in mismatches[0].port
        assert "'a'" in mismatches[0].message or "['a'" in mismatches[0].message


# ===========================================================================
# Test 3: Extra port in instance (MISMATCH)
# ===========================================================================
class TestMismatchExtraPort:
    def test_extra_port_flagged(self):
        """Instance connects a port that was removed from the submodule."""
        sv = """
module sensor_if(
    input wire clk,
    input wire sda
);
endmodule

module controller(
    input wire clk,
    input wire data_line
);
    sensor_if u_sensor (
        .clk(clk),
        .sda(data_line),
        .debug_en(1'b0)
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='controller')
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) >= 1
        assert any(f.port == 'debug_en' for f in mismatches)


# ===========================================================================
# Test 4: Unconnected module port (UNCONNECTED)
# ===========================================================================
class TestUnconnected:
    def test_port_not_connected_in_any_instance(self):
        """Module has a port that is never connected anywhere."""
        sv = """
module uart(
    input wire clk,
    input wire rst_n,
    input wire tx_data,
    output wire rx_data,
    output wire irq
);
    assign rx_data = tx_data;
    assign irq = 1'b0;
endmodule

module soc(
    input wire clk,
    input wire rst_n,
    output wire serial_out
);
    uart u_uart (
        .clk(clk),
        .rst_n(rst_n),
        .tx_data(1'b1),
        .rx_data(serial_out)
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='soc')
        unconnected = [f for f in findings if f.rule == 'unconnected']
        assert len(unconnected) >= 1
        assert any(f.port == 'irq' for f in unconnected), \
            f"Expected unconnected 'irq', got: {[f.port for f in unconnected]}"

    def test_empty_connection_counts_as_unconnected(self):
        """A .port() with empty parentheses should count as unconnected."""
        sv = """
module sub(input wire a, output wire b);
    assign b = a;
endmodule

module top(input wire x, output wire y);
    sub u0 (.a(x), .b());
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        unconnected = [f for f in findings if f.rule == 'unconnected']
        assert any(f.port == 'b' for f in unconnected)


# ===========================================================================
# Test 5: Multi-module design (complex hierarchy)
# ===========================================================================
class TestMultiModule:
    def test_three_level_hierarchy(self):
        """DTOP -> DCLK + DRST + DCORE, each with their own ports."""
        sv = """
module DCLK(
    input wire clk_in,
    input wire rst_n,
    output wire clk_5m,
    output wire clk_div
);
    assign clk_5m = clk_in;
    assign clk_div = clk_in;
endmodule

module DRST(
    input wire clk,
    input wire pwr_on,
    output wire rst_out,
    output wire otp_done
);
    assign rst_out = pwr_on;
    assign otp_done = 1'b1;
endmodule

module DCORE(
    input wire clk,
    input wire rst_n,
    input wire [7:0] cfg,
    output wire [7:0] status
);
    assign status = cfg;
endmodule

module DTOP(
    input wire ext_clk,
    input wire ext_rst,
    output wire [7:0] top_status
);
    wire clk_5m, clk_div, rst_internal, otp_done;

    DCLK u_clk (
        .clk_in(ext_clk),
        .rst_n(ext_rst),
        .clk_5m(clk_5m),
        .clk_div(clk_div)
    );

    DRST u_rst (
        .clk(clk_5m),
        .pwr_on(ext_rst),
        .rst_out(rst_internal),
        .pwr_otp_auto_load_done_2p5m(otp_done)
    );

    DCORE u_core (
        .clk(clk_5m),
        .rst_n(rst_internal),
        .cfg(8'h00),
        .status(top_status)
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='DTOP')
        # DRST is connected with wrong port name: pwr_otp_auto_load_done_2p5m
        # but DRST has otp_done
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) >= 1
        assert any(f.port == 'pwr_otp_auto_load_done_2p5m' for f in mismatches)

        # otp_done should be flagged as unconnected (since wrong name was used)
        unconnected = [f for f in findings if f.rule == 'unconnected']
        assert any(f.port == 'otp_done' and f.module == 'DRST' for f in unconnected)


# ===========================================================================
# Test 6: Width mismatch detection
# ===========================================================================
class TestWidthMismatch:
    def test_8bit_port_connected_to_1bit_wire(self):
        """Connecting a scalar wire to an 8-bit port should warn."""
        sv = """
module data_proc(
    input wire clk,
    input wire [7:0] data_in,
    output wire [7:0] data_out
);
    assign data_out = data_in;
endmodule

module wrapper(
    input wire clk,
    input wire single_bit,
    output wire [7:0] result
);
    data_proc u0 (
        .clk(clk),
        .data_in(single_bit),
        .data_out(result)
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='wrapper')
        width_mm = [f for f in findings if f.rule == 'width-mismatch']
        assert len(width_mm) >= 1
        assert any(f.port == 'data_in' for f in width_mm)

    def test_matching_widths_no_warning(self):
        """Same width on both sides should produce no warning."""
        sv = """
module sub(input wire [3:0] d, output wire [3:0] q);
    assign q = d;
endmodule

module top(input wire [3:0] x, output wire [3:0] y);
    sub u0 (.d(x), .q(y));
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        width_mm = [f for f in findings if f.rule == 'width-mismatch']
        assert len(width_mm) == 0

    def test_part_select_width(self):
        """Connecting data[3:0] (4 bits) to an 8-bit port should warn."""
        sv = """
module sub(input wire [7:0] d, output wire q);
    assign q = d[0];
endmodule

module top(input wire [15:0] bus, output wire out);
    sub u0 (.d(bus[3:0]), .q(out));
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        width_mm = [f for f in findings if f.rule == 'width-mismatch']
        assert len(width_mm) >= 1
        assert any(f.port == 'd' for f in width_mm)


# ===========================================================================
# Test 7: .* implicit connection
# ===========================================================================
class TestImplicitConnection:
    def test_dotstar_no_mismatch(self):
        """SystemVerilog .* connects all ports by name — should not flag mismatch."""
        sv = """
module sub(input wire clk, input wire rst_n, output wire valid);
    assign valid = ~rst_n;
endmodule

module top(input wire clk, input wire rst_n, output wire valid);
    sub u0 (.*);
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) == 0

    def test_dotstar_mixed_with_explicit(self):
        """.*  with some explicit overrides — only check explicit connections."""
        sv = """
module sub(input wire clk, input wire rst_n, input wire en, output wire valid);
    assign valid = en & ~rst_n;
endmodule

module top(input wire clk, input wire rst_n, input wire enable, output wire valid);
    sub u0 (.en(enable), .*);
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) == 0

    def test_dotstar_marks_implicit(self):
        """Parser should mark .* instances as implicit."""
        sv = """
module child(input wire a, output wire b);
    assign b = a;
endmodule

module parent(input wire a, output wire b);
    child u0 (.*);
endmodule
"""
        defs = parse_from_string(sv)
        parent = defs['parent']
        assert len(parent.instances) == 1
        assert parent.instances[0].is_implicit is True

    def test_dotstar_suppresses_unconnected(self):
        """.* connections should suppress UNCONNECTED warnings."""
        sv = """
module sub(input wire a, input wire b, output wire c);
    assign c = a & b;
endmodule

module top(input wire a, input wire b, output wire c);
    sub u0 (.*);
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        unconnected = [f for f in findings if f.rule == 'unconnected']
        assert len(unconnected) == 0


# ===========================================================================
# Test 8: Parameterized module
# ===========================================================================
class TestParameterized:
    def test_parameterized_instantiation(self):
        """Module with parameter override #(.WIDTH(16)) should parse correctly."""
        sv = """
module fifo #(
    parameter WIDTH = 8,
    parameter DEPTH = 16
)(
    input wire clk,
    input wire rst_n,
    input wire [WIDTH-1:0] data_in,
    input wire wr_en,
    output wire [WIDTH-1:0] data_out,
    output wire full,
    output wire empty
);
    assign data_out = data_in;
    assign full = 1'b0;
    assign empty = 1'b1;
endmodule

module top(
    input wire clk,
    input wire rst_n,
    input wire [15:0] din,
    output wire [15:0] dout
);
    fifo #(.WIDTH(16), .DEPTH(32)) u_fifo (
        .clk(clk),
        .rst_n(rst_n),
        .data_in(din),
        .wr_en(1'b1),
        .data_out(dout),
        .full(),
        .empty()
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) == 0, \
            f"Parameterized module should parse cleanly, got: {mismatches}"

    def test_parameterized_with_wrong_port(self):
        """Parameterized module with a wrong port should still be caught."""
        sv = """
module fifo #(parameter DEPTH = 16)(
    input wire clk,
    input wire [7:0] wdata,
    output wire [7:0] rdata
);
    assign rdata = wdata;
endmodule

module top(input wire clk, input wire [7:0] d, output wire [7:0] q);
    fifo #(.DEPTH(8)) u_fifo (
        .clk(clk),
        .write_data(d),
        .rdata(q)
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) >= 1
        assert any(f.port == 'write_data' for f in mismatches)


# ===========================================================================
# Test 9: Module parser correctness
# ===========================================================================
class TestParser:
    def test_parse_ansi_ports(self):
        """Correctly parse ANSI-style port list."""
        sv = """
module test_mod(
    input wire clk,
    input wire rst_n,
    input wire [7:0] data,
    output reg [15:0] result,
    inout wire sda
);
endmodule
"""
        defs = parse_from_string(sv)
        assert 'test_mod' in defs
        ports = defs['test_mod'].ports
        assert len(ports) == 5
        assert ports['clk'].direction == 'input'
        assert ports['clk'].width == 1
        assert ports['data'].direction == 'input'
        assert ports['data'].width == 8
        assert ports['result'].direction == 'output'
        assert ports['result'].width == 16
        assert ports['sda'].direction == 'inout'

    def test_parse_non_ansi_ports(self):
        """Correctly parse non-ANSI (Verilog-95) port declarations."""
        sv = """
module old_style(clk, rst, data, out);
    input clk;
    input rst;
    input [7:0] data;
    output [7:0] out;
    assign out = data;
endmodule

module wrapper(input wire clk, input wire rst, input wire [7:0] d, output wire [7:0] q);
    old_style u0 (.clk(clk), .rst(rst), .data(d), .out(q));
endmodule
"""
        findings = audit_from_string(sv, top_module='wrapper')
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) == 0

    def test_parse_multiple_instances(self):
        """Multiple instances of the same module should be parsed correctly."""
        sv = """
module buf_cell(input wire a, output wire y);
    assign y = a;
endmodule

module top(input wire [3:0] in, output wire [3:0] out);
    buf_cell u0 (.a(in[0]), .y(out[0]));
    buf_cell u1 (.a(in[1]), .y(out[1]));
    buf_cell u2 (.a(in[2]), .y(out[2]));
    buf_cell u3 (.a(in[3]), .y(out[3]));
endmodule
"""
        defs = parse_from_string(sv)
        top = defs['top']
        assert len(top.instances) == 4
        assert all(inst.module_name == 'buf_cell' for inst in top.instances)

    def test_comments_stripped(self):
        """Comments should not interfere with port parsing."""
        sv = """
module sub(
    input wire clk,       // system clock
    /* active-low reset */
    input wire rst_n,
    output wire valid     // data valid
);
    assign valid = ~rst_n;
endmodule

module top(input wire clk, input wire rst_n, output wire v);
    sub u0 (
        .clk(clk),        // connect clock
        .rst_n(rst_n),    // connect reset
        .valid(v)         // connect valid
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) == 0


# ===========================================================================
# Test 10: CLI output format
# ===========================================================================
class TestCLI:
    def test_cli_rtl_dir_mode(self, tmp_path):
        """Test --rtl-dir mode with files in a subdirectory."""
        rtl_dir = tmp_path / 'rtl'
        rtl_dir.mkdir(parents=True, exist_ok=True)
        (rtl_dir / 'sub.v').write_text("""
module sub(input wire a, output wire b);
    assign b = a;
endmodule
""")
        (rtl_dir / 'top.v').write_text("""
module top(input wire x, output wire y);
    sub u0 (.a(x), .wrong_b(y));
endmodule
""")
        out_dir = tmp_path / 'output'
        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--rtl-dir', str(rtl_dir),
             '--top-module', 'top',
             '--out-dir', str(out_dir)],
            capture_output=True, text=True)
        assert res.returncode == 1  # has errors
        report_file = out_dir / 'module_port_audit_report.json'
        assert report_file.exists()
        report = json.loads(report_file.read_text())
        assert report['summary']['mismatches'] >= 1
        assert report['top_module'] == 'top'

    def test_cli_severity_filter(self, tmp_path):
        """--severity ERROR should suppress WARN findings."""
        sv = """
module sub(input wire a, input wire b, output wire c);
    assign c = a;
endmodule

module top(input wire x, output wire y);
    sub u0 (.a(x), .c(y));
endmodule
"""
        # Port 'b' is unconnected (WARN), no mismatches (ERROR)
        res, report = run_cli(tmp_path, {'design.sv': sv},
                              args_extra=['--top-module', 'top', '--severity', 'ERROR'])
        # With ERROR filter, only mismatches should appear
        assert report['summary']['errors'] == 0

    def test_json_report_structure(self, tmp_path):
        """Verify the JSON report has the expected structure."""
        sv = """
module a(input wire x, output wire y);
    assign y = x;
endmodule
module b(input wire i, output wire o);
    a u0 (.x(i), .y(o));
endmodule
"""
        _, report = run_cli(tmp_path, {'test.sv': sv},
                            args_extra=['--top-module', 'b'])
        assert 'tool' in report
        assert report['tool'] == 'module_port_audit'
        assert 'summary' in report
        assert 'modules' in report
        assert 'findings' in report
        assert 'a' in report['modules']
        assert 'b' in report['modules']


# ===========================================================================
# Test 11: External/unknown modules (should not crash)
# ===========================================================================
class TestExternalModules:
    def test_instance_of_undefined_module_ignored(self):
        """Instantiation of a module not in the design should be silently skipped."""
        sv = """
module top(input wire clk, output wire y);
    external_ip u_ext (
        .clk(clk),
        .out(y)
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='top')
        # Should not crash, and no mismatch (can't verify external modules)
        mismatches = [f for f in findings if f.rule == 'mismatch']
        assert len(mismatches) == 0


# ===========================================================================
# Test 12: v0.36 exact failure reproduction
# ===========================================================================
class TestV036Reproduction:
    def test_dtop_dclk_drst_exact_scenario(self):
        """
        Reproduce the exact v0.36 failure:
        - DTOP connected .sys_clk_5m but DCLK has .clk_5m
        - DTOP connected .pwr_otp_auto_load_done_2p5m but DRST has .otp_done
        Both should be flagged as MISMATCH.
        """
        sv = """
module DCLK(
    input wire clk_50m,
    input wire rst_n,
    output wire clk_5m,
    output wire clk_2p5m
);
    reg [3:0] div_cnt;
    always @(posedge clk_50m or negedge rst_n)
        if (!rst_n) div_cnt <= 0;
        else div_cnt <= div_cnt + 1;
    assign clk_5m = div_cnt[3];
    assign clk_2p5m = div_cnt[2];
endmodule

module DRST(
    input wire clk,
    input wire pwr_on_rst_n,
    output wire sys_rst_n,
    output wire otp_done
);
    reg [1:0] sync;
    always @(posedge clk or negedge pwr_on_rst_n)
        if (!pwr_on_rst_n) sync <= 2'b00;
        else sync <= {sync[0], 1'b1};
    assign sys_rst_n = sync[1];
    assign otp_done = sync[1];
endmodule

module DCORE(
    input wire clk,
    input wire rst_n,
    input wire [7:0] config_reg,
    output wire [7:0] status_reg
);
    assign status_reg = config_reg;
endmodule

module DTOP(
    input wire clk_50m,
    input wire pwr_on_rst_n,
    output wire [7:0] status
);
    wire sys_clk_5m, sys_clk_2p5m;
    wire sys_rst_n, otp_auto_done;

    // Agent 1 generated DCLK with port names clk_5m, clk_2p5m
    // Agent 4 generated DTOP with port names sys_clk_5m, sys_clk_2p5m
    DCLK u_clk (
        .clk_50m(clk_50m),
        .rst_n(pwr_on_rst_n),
        .sys_clk_5m(sys_clk_5m),
        .sys_clk_2p5m(sys_clk_2p5m)
    );

    // Agent 2 generated DRST with port otp_done
    // Agent 4 generated DTOP with port pwr_otp_auto_load_done_2p5m
    DRST u_rst (
        .clk(sys_clk_5m),
        .pwr_on_rst_n(pwr_on_rst_n),
        .sys_rst_n(sys_rst_n),
        .pwr_otp_auto_load_done_2p5m(otp_auto_done)
    );

    DCORE u_core (
        .clk(sys_clk_5m),
        .rst_n(sys_rst_n),
        .config_reg(8'h00),
        .status_reg(status)
    );
endmodule
"""
        findings = audit_from_string(sv, top_module='DTOP')

        mismatches = [f for f in findings if f.rule == 'mismatch']
        mismatch_ports = {f.port for f in mismatches}

        # Must catch both v0.36 bugs
        assert 'sys_clk_5m' in mismatch_ports, \
            f"Failed to detect sys_clk_5m mismatch. Found: {mismatch_ports}"
        assert 'sys_clk_2p5m' in mismatch_ports, \
            f"Failed to detect sys_clk_2p5m mismatch. Found: {mismatch_ports}"
        assert 'pwr_otp_auto_load_done_2p5m' in mismatch_ports, \
            f"Failed to detect pwr_otp_auto_load_done_2p5m mismatch. Found: {mismatch_ports}"

        # Original ports should be flagged as unconnected
        unconnected = [f for f in findings if f.rule == 'unconnected']
        unconnected_ports = {(f.module, f.port) for f in unconnected}
        assert ('DCLK', 'clk_5m') in unconnected_ports
        assert ('DCLK', 'clk_2p5m') in unconnected_ports
        assert ('DRST', 'otp_done') in unconnected_ports


# ===========================================================================
# Test 13: strip_comments edge cases
# ===========================================================================
class TestStripComments:
    def test_preserves_line_count(self):
        src = "line1\nline2 // comment\nline3\n"
        out = mpa.strip_comments(src)
        assert out.count('\n') == src.count('\n')

    def test_block_comment_preserves_lines(self):
        src = "a\n/* multi\nline\ncomment */\nb\n"
        out = mpa.strip_comments(src)
        assert out.count('\n') == src.count('\n')
        assert 'multi' not in out
        assert 'b' in out

    def test_string_literal_not_stripped(self):
        src = 'wire x; // real comment\nassign msg = "hello // world";\n'
        out = mpa.strip_comments(src)
        assert 'real comment' not in out
        assert '"hello // world"' in out


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
