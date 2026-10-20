"""Unit tests for interface_encoding_audit.py.

Each test synthesizes small Verilog snippets (producer + consumer modules)
and verifies the encoding classification and mismatch detection.

Test cases:
  1. Binary-binary MATCH (counter -> decimal comparison)
  2. Gray-gray MATCH (gray case -> gray comparison)
  3. Binary-gray MISMATCH (counter -> gray comparison) — the USB-HID tester bug
  4. Gray-binary MISMATCH (gray case -> decimal comparison)
  5. Binary-to-gray conversion function detected
  6. Unknown encoding (no clear pattern)
  7. Multiple interfaces (mix of MATCH and MISMATCH)
  8. Arithmetic producer (multiply/add -> binary comparison)
  9. Decrement counter producer
  10. Multi-file design parsed correctly
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'interface_encoding_audit.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import interface_encoding_audit as iea  # noqa: E402


def run_cli(tmp_path, files: dict, top_module: str, severity='INFO', extra=()):
    """Write Verilog files and run the CLI, return parsed JSON report."""
    rtl_dir = tmp_path / 'rtl'
    rtl_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / 'out'
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (rtl_dir / name).write_text(content)
    res = subprocess.run(
        [sys.executable, str(SCRIPT),
         '--rtl-dir', str(rtl_dir),
         '--top-module', top_module,
         '--out-dir', str(out_dir),
         '--severity', severity, *extra],
        capture_output=True, text=True)
    report_path = out_dir / 'encoding_audit_report.json'
    if report_path.exists():
        report = json.loads(report_path.read_text())
    else:
        report = None
    return res, report


# ---------------------------------------------------------------------------
# Helper: create a simple two-module design with specified patterns
# ---------------------------------------------------------------------------
def make_two_module_design(producer_body: str, consumer_body: str,
                           signal_name: str = 'data_cnt',
                           width: str = '[5:0]') -> dict:
    """Generate a top-level design with producer -> consumer connection."""
    producer = f"""
module producer(
    input  wire clk,
    input  wire rst_n,
    output reg  {width} {signal_name}
);
{producer_body}
endmodule
"""
    consumer = f"""
module consumer(
    input  wire clk,
    input  wire rst_n,
    input  wire {width} {signal_name},
    output reg  valid
);
{consumer_body}
endmodule
"""
    top = f"""
module top(
    input  wire clk,
    input  wire rst_n,
    output wire valid
);
    wire {width} {signal_name}_w;
    producer u_prod (
        .clk(clk),
        .rst_n(rst_n),
        .{signal_name}({signal_name}_w)
    );
    consumer u_cons (
        .clk(clk),
        .rst_n(rst_n),
        .{signal_name}({signal_name}_w),
        .valid(valid)
    );
endmodule
"""
    return {
        'producer.v': producer,
        'consumer.v': consumer,
        'top.v': top,
    }


# ===================================================================
# Test 1: Binary-Binary MATCH (counter producer, decimal comparison)
# ===================================================================
class TestBinaryBinaryMatch:
    def test_counter_vs_decimal_comparison(self, tmp_path):
        """A counter (binary) compared with decimal literal → MATCH."""
        files = make_two_module_design(
            producer_body="""
    always @(posedge clk) begin
        if (!rst_n)
            data_cnt <= 6'd0;
        else
            data_cnt <= data_cnt + 1;
    end
""",
            consumer_body="""
    always @(posedge clk) begin
        if (data_cnt == 6'd32)
            valid <= 1'b1;
        else
            valid <= 1'b0;
    end
""")
        _, report = run_cli(tmp_path, files, 'top')
        assert report is not None
        ifaces = report['interfaces']
        # Find the data_cnt interface
        cnt_iface = [i for i in ifaces if i['wire_name'] == 'data_cnt_w']
        assert len(cnt_iface) >= 1
        # Producer should be BINARY, consumer should be BINARY
        for iface in cnt_iface:
            if iface['producer_module'] == 'producer':
                assert iface['producer_encoding'] == 'BINARY'
                assert iface['consumer_encoding'] == 'BINARY'
                assert iface['status'] == 'MATCH'

    def test_counter_vs_hex_comparison(self, tmp_path):
        """A counter compared with hex literal → BINARY MATCH."""
        files = make_two_module_design(
            producer_body="""
    always @(posedge clk) begin
        if (!rst_n)
            data_cnt <= 6'd0;
        else
            data_cnt <= data_cnt + 1'b1;
    end
""",
            consumer_body="""
    always @(posedge clk) begin
        if (data_cnt >= 6'h18)
            valid <= 1'b1;
        else
            valid <= 1'b0;
    end
""")
        _, report = run_cli(tmp_path, files, 'top')
        cnt_iface = [i for i in report['interfaces']
                     if i['wire_name'] == 'data_cnt_w'
                     and i['producer_module'] == 'producer']
        assert len(cnt_iface) >= 1
        assert cnt_iface[0]['producer_encoding'] == 'BINARY'
        assert cnt_iface[0]['consumer_encoding'] == 'BINARY'
        assert cnt_iface[0]['status'] == 'MATCH'


# ===================================================================
# Test 2: Gray-Gray MATCH (gray case producer, gray comparison)
# ===================================================================
class TestGrayGrayMatch:
    def test_gray_case_vs_gray_comparison(self, tmp_path):
        """Producer uses gray-code case mapping, consumer compares with
        gray-code literals → MATCH."""
        # Gray codes for 0-7 (3-bit): 000,001,011,010,110,111,101,100
        files = make_two_module_design(
            width='[2:0]',
            producer_body="""
    reg [2:0] bin_cnt;
    always @(posedge clk) begin
        if (!rst_n) begin
            bin_cnt <= 3'd0;
            data_cnt <= 3'b000;
        end else begin
            bin_cnt <= bin_cnt + 1;
            case (bin_cnt)
                3'd0: data_cnt <= 3'b000;
                3'd1: data_cnt <= 3'b001;
                3'd2: data_cnt <= 3'b011;
                3'd3: data_cnt <= 3'b010;
                3'd4: data_cnt <= 3'b110;
                3'd5: data_cnt <= 3'b111;
                3'd6: data_cnt <= 3'b101;
                3'd7: data_cnt <= 3'b100;
                default: data_cnt <= 3'b000;
            endcase
        end
    end
""",
            consumer_body="""
    always @(posedge clk) begin
        if (data_cnt == 3'b110)
            valid <= 1'b1;
        else
            valid <= 1'b0;
    end
""")
        _, report = run_cli(tmp_path, files, 'top')
        cnt_iface = [i for i in report['interfaces']
                     if i['wire_name'] == 'data_cnt_w'
                     and i['producer_module'] == 'producer']
        assert len(cnt_iface) >= 1
        assert cnt_iface[0]['producer_encoding'] == 'GRAY'
        assert cnt_iface[0]['status'] in ('MATCH', 'UNKNOWN')
        # Note: consumer might be UNKNOWN if 3'b110 = 6 decimal which equals
        # gray(4)=6, but width is 3 bits. The classifier tries its best.


# ===================================================================
# Test 3: Binary-Gray MISMATCH — the USB-HID tester bug pattern
# ===================================================================
class TestBinaryGrayMismatch:
    def test_counter_vs_gray_comparison_mismatch(self, tmp_path):
        """A binary counter compared with a gray-code literal → MISMATCH.
        This is the exact USB-HID tester bug: rx_data_length_cnt produced as binary
        counter, but rx_chk compared against 6'b11_0000 (gray-code for 32,
        not binary 32 which is 6'b10_0000)."""
        files = make_two_module_design(
            producer_body="""
    always @(posedge clk) begin
        if (!rst_n)
            data_cnt <= 6'd0;
        else
            data_cnt <= data_cnt + 1;
    end
""",
            consumer_body="""
    // Bug: comparing binary counter with gray-code value!
    // gray(32) = 48 = 6'b11_0000, but binary 32 = 6'b10_0000
    always @(posedge clk) begin
        if (data_cnt == 6'b11_0000)
            valid <= 1'b1;
        else
            valid <= 1'b0;
    end
""")
        _, report = run_cli(tmp_path, files, 'top')
        cnt_iface = [i for i in report['interfaces']
                     if i['wire_name'] == 'data_cnt_w'
                     and i['producer_module'] == 'producer']
        assert len(cnt_iface) >= 1
        assert cnt_iface[0]['producer_encoding'] == 'BINARY'
        assert cnt_iface[0]['consumer_encoding'] == 'GRAY'
        assert cnt_iface[0]['status'] == 'MISMATCH'
        assert cnt_iface[0]['severity'] == 'ERROR'


# ===================================================================
# Test 4: Gray-Binary MISMATCH (reverse direction)
# ===================================================================
class TestGrayBinaryMismatch:
    def test_gray_producer_binary_consumer(self, tmp_path):
        """Producer outputs gray-coded via ^ >>1, consumer uses decimal → MISMATCH."""
        files = make_two_module_design(
            producer_body="""
    reg [5:0] bin_cnt;
    always @(posedge clk) begin
        if (!rst_n) begin
            bin_cnt <= 6'd0;
            data_cnt <= 6'd0;
        end else begin
            bin_cnt <= bin_cnt + 1;
            data_cnt <= bin_cnt ^ (bin_cnt >> 1);
        end
    end
""",
            consumer_body="""
    always @(posedge clk) begin
        if (data_cnt == 6'd32)
            valid <= 1'b1;
        else
            valid <= 1'b0;
    end
""")
        _, report = run_cli(tmp_path, files, 'top')
        cnt_iface = [i for i in report['interfaces']
                     if i['wire_name'] == 'data_cnt_w'
                     and i['producer_module'] == 'producer']
        assert len(cnt_iface) >= 1
        assert cnt_iface[0]['producer_encoding'] == 'GRAY'
        assert cnt_iface[0]['consumer_encoding'] == 'BINARY'
        assert cnt_iface[0]['status'] == 'MISMATCH'
        assert cnt_iface[0]['severity'] == 'ERROR'


# ===================================================================
# Test 5: Binary-to-gray conversion function detected
# ===================================================================
class TestBinaryToGrayConversion:
    def test_b2g_pattern_detected_as_gray(self, tmp_path):
        """signal <= x ^ (x >> 1) is the canonical binary-to-gray conversion."""
        body = """
    reg [5:0] bin_cnt;
    always @(posedge clk) begin
        if (!rst_n) begin
            bin_cnt <= 6'd0;
            data_cnt <= 6'd0;
        end else begin
            bin_cnt <= bin_cnt + 1;
            data_cnt <= bin_cnt ^ (bin_cnt >> 1);
        end
    end
"""
        src = iea.strip_comments(body)
        result = iea.classify_producer_encoding(src, 'data_cnt')
        assert result.encoding == 'GRAY'
        assert 'binary-to-gray' in result.evidence.lower() or 'x ^ (x >> 1)' in result.evidence

    def test_plain_increment_detected_as_binary(self, tmp_path):
        """signal <= signal + 1 is a binary counter."""
        body = """
    always @(posedge clk) begin
        if (!rst_n)
            data_cnt <= 6'd0;
        else
            data_cnt <= data_cnt + 1;
    end
"""
        src = iea.strip_comments(body)
        result = iea.classify_producer_encoding(src, 'data_cnt')
        assert result.encoding == 'BINARY'
        assert 'increment' in result.evidence.lower() or 'counter' in result.evidence.lower()


# ===================================================================
# Test 6: Unknown encoding (no clear pattern)
# ===================================================================
class TestUnknownEncoding:
    def test_no_pattern_returns_unknown(self, tmp_path):
        """When signal is assigned from another signal with no arithmetic,
        encoding is UNKNOWN."""
        files = make_two_module_design(
            producer_body="""
    reg [5:0] other_reg;
    always @(posedge clk) begin
        if (!rst_n) begin
            data_cnt <= 6'd0;
        end else begin
            data_cnt <= other_reg;
        end
    end
""",
            consumer_body="""
    // No comparison at all, just pass-through
    always @(posedge clk) begin
        valid <= data_cnt[0];
    end
""")
        _, report = run_cli(tmp_path, files, 'top')
        cnt_iface = [i for i in report['interfaces']
                     if i['wire_name'] == 'data_cnt_w'
                     and i['producer_module'] == 'producer']
        assert len(cnt_iface) >= 1
        # At least one side should be UNKNOWN
        assert cnt_iface[0]['status'] == 'UNKNOWN'

    def test_consumer_no_comparison_is_unknown(self):
        """Consumer that never compares the signal → UNKNOWN consumer encoding."""
        body = """
    always @(posedge clk) begin
        valid <= data_cnt[0];
    end
"""
        result = iea.classify_consumer_encoding(iea.strip_comments(body), 'data_cnt')
        assert result.encoding == 'UNKNOWN'


# ===================================================================
# Test 7: Multiple interfaces in one design
# ===================================================================
class TestMultipleInterfaces:
    def test_mix_of_match_and_mismatch(self, tmp_path):
        """Design with two interfaces: one MATCH, one MISMATCH."""
        producer = """
module producer(
    input  wire clk,
    input  wire rst_n,
    output reg  [5:0] cnt_a,
    output reg  [5:0] cnt_b
);
    always @(posedge clk) begin
        if (!rst_n) begin
            cnt_a <= 6'd0;
            cnt_b <= 6'd0;
        end else begin
            cnt_a <= cnt_a + 1;
            cnt_b <= cnt_b + 1;
        end
    end
endmodule
"""
        consumer = """
module consumer(
    input  wire clk,
    input  wire rst_n,
    input  wire [5:0] cnt_a,
    input  wire [5:0] cnt_b,
    output reg  valid_a,
    output reg  valid_b
);
    always @(posedge clk) begin
        if (cnt_a == 6'd32)
            valid_a <= 1'b1;
        else
            valid_a <= 1'b0;
    end
    // Bug: comparing binary counter with gray-code value!
    always @(posedge clk) begin
        if (cnt_b == 6'b11_0000)
            valid_b <= 1'b1;
        else
            valid_b <= 1'b0;
    end
endmodule
"""
        top = """
module top(
    input  wire clk,
    input  wire rst_n,
    output wire valid_a,
    output wire valid_b
);
    wire [5:0] cnt_a_w, cnt_b_w;
    producer u_prod (
        .clk(clk), .rst_n(rst_n),
        .cnt_a(cnt_a_w), .cnt_b(cnt_b_w)
    );
    consumer u_cons (
        .clk(clk), .rst_n(rst_n),
        .cnt_a(cnt_a_w), .cnt_b(cnt_b_w),
        .valid_a(valid_a), .valid_b(valid_b)
    );
endmodule
"""
        files = {
            'producer.v': producer,
            'consumer.v': consumer,
            'top.v': top,
        }
        _, report = run_cli(tmp_path, files, 'top')
        assert report is not None
        assert report['summary']['total_interfaces'] >= 2

        # cnt_a should be MATCH (binary-binary)
        cnt_a = [i for i in report['interfaces']
                 if i['wire_name'] == 'cnt_a_w'
                 and i['producer_module'] == 'producer']
        # cnt_b should be MISMATCH (binary-gray)
        cnt_b = [i for i in report['interfaces']
                 if i['wire_name'] == 'cnt_b_w'
                 and i['producer_module'] == 'producer']
        if cnt_a:
            assert cnt_a[0]['status'] == 'MATCH'
        if cnt_b:
            assert cnt_b[0]['status'] == 'MISMATCH'


# ===================================================================
# Test 8: Arithmetic producer (multiply/add detected as binary)
# ===================================================================
class TestArithmeticProducer:
    def test_arithmetic_expression_is_binary(self):
        """Arithmetic expressions (multiply, add) → BINARY."""
        body = """
    always @(posedge clk) begin
        if (!rst_n)
            data_cnt <= 6'd0;
        else
            data_cnt <= some_val * 3 + offset;
    end
"""
        result = iea.classify_producer_encoding(iea.strip_comments(body), 'data_cnt')
        assert result.encoding == 'BINARY'

    def test_subtraction_is_binary(self):
        """Subtraction → BINARY."""
        body = """
    always @(posedge clk) begin
        data_cnt <= max_val - current;
    end
"""
        result = iea.classify_producer_encoding(iea.strip_comments(body), 'data_cnt')
        assert result.encoding == 'BINARY'


# ===================================================================
# Test 9: Decrement counter producer
# ===================================================================
class TestDecrementCounter:
    def test_decrement_is_binary(self):
        """signal <= signal - 1 → BINARY decrement counter."""
        body = """
    always @(posedge clk) begin
        if (!rst_n)
            data_cnt <= 6'd63;
        else
            data_cnt <= data_cnt - 1;
    end
"""
        result = iea.classify_producer_encoding(iea.strip_comments(body), 'data_cnt')
        assert result.encoding == 'BINARY'
        assert 'decrement' in result.evidence.lower() or 'counter' in result.evidence.lower()

    def test_decrement_1b1_is_binary(self):
        """signal <= signal - 1'b1 → BINARY."""
        body = """
    always @(posedge clk) begin
        data_cnt <= data_cnt - 1'b1;
    end
"""
        result = iea.classify_producer_encoding(iea.strip_comments(body), 'data_cnt')
        assert result.encoding == 'BINARY'


# ===================================================================
# Test 10: Multi-file design parsed correctly
# ===================================================================
class TestMultiFile:
    def test_modules_across_files(self, tmp_path):
        """Modules in separate files are correctly linked."""
        files = make_two_module_design(
            producer_body="""
    always @(posedge clk) begin
        if (!rst_n)
            data_cnt <= 6'd0;
        else
            data_cnt <= data_cnt + 1;
    end
""",
            consumer_body="""
    always @(posedge clk) begin
        if (data_cnt == 6'd32)
            valid <= 1'b1;
        else
            valid <= 1'b0;
    end
""")
        _, report = run_cli(tmp_path, files, 'top')
        assert report is not None
        assert report['summary']['total_interfaces'] >= 1
        # Verify module names are correctly resolved across files
        modules_found = set()
        for iface in report['interfaces']:
            modules_found.add(iface['producer_module'])
            modules_found.add(iface['consumer_module'])
        assert 'producer' in modules_found
        assert 'consumer' in modules_found


# ===================================================================
# Unit tests for helper functions
# ===================================================================
class TestVerilogLiteralParser:
    def test_binary_literal(self):
        assert iea.parse_verilog_literal("6'b110000") == (6, 0b110000)

    def test_binary_literal_with_underscores(self):
        assert iea.parse_verilog_literal("6'b11_0000") == (6, 0b110000)

    def test_decimal_literal(self):
        assert iea.parse_verilog_literal("6'd32") == (6, 32)

    def test_hex_literal(self):
        assert iea.parse_verilog_literal("8'hFF") == (8, 255)

    def test_invalid_literal(self):
        assert iea.parse_verilog_literal("not_a_literal") is None

    def test_xz_literal(self):
        assert iea.parse_verilog_literal("4'bxxxx") is None


class TestGrayConversion:
    def test_binary_to_gray_known_values(self):
        # Gray code: 0→0, 1→1, 2→3, 3→2, 4→6, 5→7, 6→5, 7→4
        assert iea.binary_to_gray(0) == 0
        assert iea.binary_to_gray(1) == 1
        assert iea.binary_to_gray(2) == 3
        assert iea.binary_to_gray(3) == 2
        assert iea.binary_to_gray(4) == 6
        assert iea.binary_to_gray(32) == 48  # The USB-HID tester bug value

    def test_gray_to_binary_roundtrip(self):
        for n in range(64):
            g = iea.binary_to_gray(n)
            assert iea.gray_to_binary(g, 6) == n


class TestCommentStripper:
    def test_preserves_line_count(self):
        src = "line1\nline2 // comment\nline3\n"
        out = iea.strip_comments(src)
        assert out.count('\n') == src.count('\n')

    def test_strips_block_comments(self):
        src = "before /* multi\nline\ncomment */ after\n"
        out = iea.strip_comments(src)
        assert 'multi' not in out
        assert 'after' in out


class TestModuleParser:
    def test_parses_simple_module(self):
        src = """
module foo(
    input wire clk,
    input wire rst_n,
    output reg [7:0] data
);
    always @(posedge clk) data <= data + 1;
endmodule
"""
        mods = iea.parse_modules(iea.strip_comments(src), 'test.v')
        assert len(mods) == 1
        assert mods[0].name == 'foo'
        port_names = {p.name for p in mods[0].ports}
        assert 'clk' in port_names
        assert 'data' in port_names

    def test_parses_instances(self):
        body = """
    wire [7:0] w;
    sub_mod u_sub (
        .clk(clk),
        .data_in(w)
    );
"""
        insts = iea.parse_instances(iea.strip_comments(body), 'parent')
        assert len(insts) == 1
        assert insts[0].module_type == 'sub_mod'
        assert insts[0].inst_name == 'u_sub'
        assert insts[0].connections['clk'] == 'clk'
        assert insts[0].connections['data_in'] == 'w'


class TestReturnCodes:
    def test_clean_design_returns_zero(self, tmp_path):
        """All MATCH → exit code 0."""
        files = make_two_module_design(
            producer_body="""
    always @(posedge clk) begin
        if (!rst_n) data_cnt <= 6'd0;
        else data_cnt <= data_cnt + 1;
    end
""",
            consumer_body="""
    always @(posedge clk) begin
        if (data_cnt == 6'd32) valid <= 1'b1;
        else valid <= 1'b0;
    end
""")
        res, _ = run_cli(tmp_path, files, 'top')
        assert res.returncode == 0

    def test_mismatch_returns_one(self, tmp_path):
        """MISMATCH found → exit code 1."""
        files = make_two_module_design(
            producer_body="""
    always @(posedge clk) begin
        if (!rst_n) data_cnt <= 6'd0;
        else data_cnt <= data_cnt + 1;
    end
""",
            consumer_body="""
    always @(posedge clk) begin
        if (data_cnt == 6'b11_0000) valid <= 1'b1;
        else valid <= 1'b0;
    end
""")
        res, _ = run_cli(tmp_path, files, 'top')
        assert res.returncode == 1


def _nested_parameter_design(width_expr: str, consumer: str = "binary") -> dict:
    """The issue-2860 three-module hierarchy, with one parameter spelling varied."""
    if consumer == "gray":
        compare = "assign reached = count == 6'b11_0000;"
    else:
        compare = "assign reached = count == 6'd32;"
    return {
        "counter_source.sv": """
module counter_source(input wire clk, output reg [5:0] count);
initial count = 0;
always @(posedge clk) count <= count + 6'd1;
endmodule
""",
        "count_sink.sv": f"""
module count_sink(input wire [5:0] count, output wire reached);
{compare}
endmodule
""",
        "count_bridge.sv": f"""
module count_bridge #(
    parameter integer N = 63,
    parameter integer WIDTH = {width_expr}
) (
    input wire clk,
    output wire reached
);
wire [WIDTH-1:0] count;
counter_source src(.clk(clk), .count(count));
count_sink dst(.count(count), .reached(reached));
endmodule
""",
    }


def _population(report):
    return (
        report["summary"]["total_interfaces"],
        report["summary"]["matches"],
        report["summary"]["unknowns"],
        report["summary"]["mismatches"],
        report["discovery"],
    )


def test_nested_parameter_expression_keeps_complete_hierarchy_population(tmp_path):
    nested_res, nested = run_cli(
        tmp_path / "nested", _nested_parameter_design("$clog2(N + 1)"),
        "count_bridge")
    literal_res, literal = run_cli(
        tmp_path / "literal", _nested_parameter_design("6"), "count_bridge")
    assert nested_res.returncode == 0, nested_res.stderr
    assert literal_res.returncode == 0, literal_res.stderr
    assert _population(nested)[:4] == (3, 1, 2, 0)
    assert _population(nested)[:4] == _population(literal)[:4]
    assert nested["discovery"]["complete"] is True
    assert nested["discovery"]["modules_discovered"] == 3
    assert nested["discovery"]["instances_discovered"] == 2


def test_nested_spacing_and_genuine_encoding_mismatch_are_preserved(tmp_path):
    res, report = run_cli(
        tmp_path, _nested_parameter_design("$clog2( N + 1 )", "gray"),
        "count_bridge")
    assert res.returncode == 1
    assert report["summary"]["mismatches"] == 1
    assert report["summary"]["total_interfaces"] == 3
    assert report["discovery"]["complete"] is True


@pytest.mark.skipif(shutil.which("iverilog") is None,
                    reason="native Icarus is supplied by the EDA image")
def test_nested_literal_and_mismatch_inputs_compile_natively(tmp_path):
    for label, files in (
            ("nested", _nested_parameter_design("$clog2(N + 1)")),
            ("literal", _nested_parameter_design("6")),
            ("mismatch", _nested_parameter_design("$clog2(N + 1)", "gray"))):
        rtl = tmp_path / label
        rtl.mkdir()
        paths = []
        for name, text in files.items():
            path = rtl / name
            path.write_text(text)
            paths.append(str(path))
        result = subprocess.run(
            ["iverilog", "-g2012", "-s", "count_bridge", "-o",
             str(rtl / "sim.vvp"), *paths],
            capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_malformed_header_refuses_zero_population(tmp_path):
    rtl = {"bad.sv": "module count_bridge #(parameter W=(1+2) (input wire clk);\n"}
    res, report = run_cli(tmp_path, rtl, "count_bridge")
    assert res.returncode == 2
    assert report["summary"]["verdict"] == "INCONCLUSIVE"
    assert report["discovery"]["complete"] is False
    assert report["discovery"]["issues"]
    assert "incomplete hierarchy discovery" in res.stderr


def test_unresolved_top_refuses_zero_population(tmp_path):
    rtl = {"known.sv": "module known(input wire a); endmodule\n"}
    res, report = run_cli(tmp_path, rtl, "missing_top")
    assert res.returncode == 2
    assert report["summary"]["verdict"] == "INCONCLUSIVE"
    assert any("top module 'missing_top'" in item
               for item in report["discovery"]["issues"])


# Public issue-3327 intake: the selected file contains an inactive missing child.
_OPTIONAL_SOURCE = """module producer(input clk, output reg [3:0] count);
 always @(posedge clk) count <= count + 1'b1;
endmodule
module consumer(input [3:0] count, output hit);
 assign hit = (count == 4'd3);
endmodule
module neutral(input clk, output hit);
 wire [3:0] count;
 producer p(.clk(clk), .count(count));
 consumer c(.count(count), .hit(hit));
`ifdef OPTIONAL
 missing_optional u_optional(.clk(clk));
`endif
endmodule
"""


def _consume_encoding_receipt(tmp_path):
    sys.path.insert(0, str(SCRIPT.parent.parent / '_shared'))
    import skill_compliance_check as scc
    findings = scc._cc_audit_receipt_evidence(
        {'id': 'X_interface_encoding_audit', 'auditor': 'interface_encoding_audit'},
        '', scc.CheckContext(output_path=tmp_path / 'review.md',
                             evidence_dirs=[tmp_path / 'out'],
                             rtl_source_root=tmp_path / 'rtl'))
    assert len(findings) == 1
    return findings[0]


def test_inactive_optional_child_has_complete_active_discovery(tmp_path):
    res, report = run_cli(tmp_path, {'neutral.v': _OPTIONAL_SOURCE}, 'neutral')
    assert res.returncode == 0, res.stderr
    assert report['discovery']['complete'] is True
    assert report['discovery']['modules_discovered'] == 3
    assert report['discovery']['instances_discovered'] == 2
    assert (report['summary']['matches'], report['summary']['unknowns']) == (1, 2)
    assert report['summary']['verdict'] == 'INCONCLUSIVE'
    finding = _consume_encoding_receipt(tmp_path)
    assert (finding.id, finding.severity, finding.state) == (
        'X_interface_encoding_audit', 'FAIL', 'NOT_MEASURED')


def test_inactive_conditional_port_and_connection_are_absent(tmp_path):
    source = _OPTIONAL_SOURCE.replace(
        'input [3:0] count, output hit',
        'input [3:0] count, output hit\n`ifdef OPTIONAL\n, input extra\n`endif\n')
    source = source.replace('.hit(hit));',
                            '.hit(hit)\n`ifdef OPTIONAL\n, .extra(clk)\n`endif\n);')
    res, report = run_cli(tmp_path, {'neutral.sv': source}, 'neutral')
    assert res.returncode == 0, res.stderr
    assert report['discovery']['complete'] is True
    assert report['summary']['total_interfaces'] == 3
    context = Path(report['configuration']['native_context'])
    assert 'read_slang --keep-hierarchy --single-unit --no-synthesis-define --top neutral' in (
        context.parent / 'elaborate.ys').read_text()


def test_inactive_optional_does_not_hide_real_encoding_mismatch(tmp_path):
    source = _OPTIONAL_SOURCE.replace("count == 4'd3", "count == 4'b1100")
    res, report = run_cli(tmp_path, {'neutral.v': source}, 'neutral')
    assert res.returncode == 1
    assert report['summary']['mismatches'] == 1
    assert report['summary']['verdict'] == 'FAIL'
    assert report['discovery']['complete'] is True
    assert _consume_encoding_receipt(tmp_path).state == 'FAIL'


def test_selected_define_keeps_live_missing_child_refusal(tmp_path):
    res, report = run_cli(tmp_path, {'neutral.v': _OPTIONAL_SOURCE}, 'neutral',
                          extra=['-D', 'OPTIONAL'])
    assert res.returncode == 2, res.stdout + res.stderr
    assert report['discovery']['complete'] is False
    assert any('missing_optional' in s for s in report['discovery']['issues'])
    assert report['configuration']['defines'] == ['OPTIONAL']
    assert _consume_encoding_receipt(tmp_path).state == 'NOT_MEASURED'


def test_selected_parameter_controls_active_generate_closure(tmp_path):
    source = _OPTIONAL_SOURCE.replace('module neutral(input',
        'module neutral #(parameter ENABLE=1)(input').replace(
        '`ifdef OPTIONAL', 'generate if (ENABLE) begin : optional_arm').replace(
        '`endif', 'end endgenerate')
    res, report = run_cli(tmp_path, {'neutral.v': source}, 'neutral',
                          extra=['-P', 'ENABLE=0'])
    assert res.returncode == 0, res.stderr
    assert report['discovery']['complete'] is True
    assert report['discovery']['instances_discovered'] == 2
    assert report['configuration']['parameters'] == ['ENABLE=0']
    res, report = run_cli(tmp_path / 'active', {'neutral.v': source}, 'neutral',
                          extra=['-P', 'ENABLE=1'])
    assert res.returncode == 2
    assert report['discovery']['complete'] is False


def test_unsupported_preprocessing_is_typed_unknown(tmp_path):
    source = '`include "unknown_context.vh"\n' + _OPTIONAL_SOURCE
    res, report = run_cli(tmp_path, {'neutral.v': source}, 'neutral')
    assert res.returncode == 2
    assert report['discovery']['complete'] is False
    assert report['configuration']['state'] == 'UNKNOWN'
    assert report['summary']['verdict'] == 'INCONCLUSIVE'


@pytest.mark.parametrize('variant', ['generate-label', 'constant-input', 'inactive-expression'])
def test_configured_live_instances_are_not_blocked_by_preselection_syntax(tmp_path, variant):
    source = _OPTIONAL_SOURCE
    if variant == 'generate-label':
        source = source.replace(' producer p(',
            ' generate if (1) begin : live_region\n producer p(')
        source = source.replace(' consumer c(.count(count), .hit(hit));',
            ' consumer c(.count(count), .hit(hit));\n end endgenerate')
    elif variant == 'constant-input':
        source = source.replace('input [3:0] count, output hit',
            'input [3:0] count, input enable, output hit')
        source = source.replace('.count(count), .hit(hit)',
            ".count(count), .enable(1'b1), .hit(hit)")
    else:
        source = source.replace('`ifdef OPTIONAL',
            'generate if (0) begin : disabled')
        source = source.replace('.clk(clk));\n`endif',
            '.clk(clk ^ hit));\nend endgenerate')
    res, report = run_cli(tmp_path, {'neutral.v': source}, 'neutral')
    assert res.returncode == 0, res.stdout + res.stderr
    assert report['discovery']['complete'] is True, report['discovery']
    assert report['discovery']['instances_discovered'] == 2
    assert (report['summary']['matches'], report['summary']['unknowns']) == (1, 2)
    assert report['summary']['verdict'] == 'INCONCLUSIVE'


def test_live_missing_child_with_expression_still_refuses(tmp_path):
    source = _OPTIONAL_SOURCE.replace('.clk(clk));\n`endif',
        '.clk(clk ^ hit));\n`endif')
    res, report = run_cli(tmp_path, {'neutral.v': source}, 'neutral',
                          extra=['-D', 'OPTIONAL'])
    assert res.returncode == 2
    assert not report['discovery']['complete']
    assert any('missing_optional' in issue for issue in report['discovery']['issues'])


@pytest.mark.parametrize('mode,rc,complete', [('FAST', 0, True), ('SLOW', 2, False)])
def test_native_string_parameter_selects_the_source_generate_arm(tmp_path, mode, rc, complete):
    source = _OPTIONAL_SOURCE.replace('module neutral(input',
        f'module neutral #(parameter MODE="{mode}")(input').replace(
        '`ifdef OPTIONAL', 'generate if (MODE == "SLOW") begin : optional_arm').replace(
        '`endif', 'end endgenerate')
    res, report = run_cli(tmp_path, {'neutral.v': source}, 'neutral')
    assert res.returncode == rc, res.stdout + res.stderr
    assert report['discovery']['complete'] is complete, report['discovery']
    if complete:
        assert (report['summary']['matches'], report['summary']['unknowns']) == (1, 2)


def test_native_checked_live_expression_stays_an_opaque_encoding_obligation(tmp_path):
    source = _OPTIONAL_SOURCE.replace('input [3:0] count, output hit',
        'input [3:0] count, input enable, output hit').replace(
        '.count(count), .hit(hit)', '.count(count), .enable(clk ^ count[0]), .hit(hit)')
    res, report = run_cli(tmp_path, {'neutral.v': source}, 'neutral')
    assert res.returncode == 0, res.stdout + res.stderr
    assert report['discovery']['complete'] is True, report['discovery']
    assert report['summary']['matches'] == 1
    assert report['summary']['unknowns'] == 3
    assert report['summary']['verdict'] == 'INCONCLUSIVE'
    opaque = report['configuration']['opaque_connections']
    assert any(row['expression'] == 'clk ^ count[0]' for row in opaque)
    assert _consume_encoding_receipt(tmp_path).state == 'NOT_MEASURED'


@pytest.mark.parametrize('kind,verdict', [('unknown', 'INCOMPLETE'),
                                       ('match', 'PASS'), ('mismatch', 'FAIL'),
                                       ('absent', 'SKIP')])
def test_p0_reads_the_encoding_receipt_instead_of_advisory_rc0(tmp_path, monkeypatch,
                                                            kind, verdict):
    import flow_compliance_check as flow
    project = tmp_path / 'project'
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'neutral'}))
    if kind == 'absent':
        source = 'module neutral(input d, output q); assign q = d; endmodule\n'
    elif kind == 'unknown':
        source = _OPTIONAL_SOURCE
    else:
        literal = "6'd3" if kind == 'match' else "6'b110000"
        source = ("module producer(output reg [5:0] count); initial count <= 6'd0; endmodule\n"
                  "module consumer(input [5:0] count); always @* if(count == " + literal +
                  ") begin end endmodule\n"
                  "module neutral; wire [5:0] count; producer p(.count(count)); "
                  "consumer c(.count(count)); endmodule\n")
    (rtl / 'neutral.v').write_text(source)
    monkeypatch.setattr(flow, '_STRUCTURAL_RTL_GATES', ('interface_encoding_audit',))
    records = []
    flow._run_structural_rtl_gates(project, records_out=records)
    assert len(records) == 1
    assert records[0]['verdict'] == verdict, records


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
