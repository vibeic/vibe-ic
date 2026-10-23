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
import hashlib
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


def _enable_interface_encoding_p0(flow, monkeypatch):
    """Re-enable the historical P0 route with its complete CLI contract."""
    monkeypatch.setattr(
        flow, "_STRUCTURAL_RTL_GATES", ("interface_encoding_audit",))
    contracts = dict(flow._STRUCTURAL_GATE_INVOCATION_CONTRACTS)
    contracts["interface_encoding_audit"] = "interface-encoding"
    monkeypatch.setattr(flow, "_STRUCTURAL_GATE_INVOCATION_CONTRACTS", contracts)


@pytest.mark.parametrize('body', ["if (flag) seen <= 1'b1;", "if (!flag) seen <= 1'b1;",
                                "seen <= flag ? 1'b1 : 1'b0;",
                                "seen <= !flag ? 1'b1 : 1'b0;"])
def test_native_whole_scalar_predicate_is_encoding_invariant(tmp_path, body):
    files = _predicate_design(body)
    result, report = run_cli(tmp_path, files, 'top', extra=('-D', 'NATIVE_PREDICATE'))
    assert result.returncode == 0, result.stderr
    assert report['discovery']['complete'] is True
    edge = _predicate_edge(report)
    assert edge['status'] == 'MATCH', edge
    assert edge['producer_encoding'] == 'BIT_VALUE', edge
    assert 'data encoding is not inferred' in edge['producer_evidence']
    assert edge['consumer_encoding'] == 'PREDICATE', edge
    assert 'all references' in edge['consumer_evidence']
    assert '0,1,x,z' in edge['consumer_evidence']
    # The unrelated seed carrier is still UNKNOWN; no zero-mismatch PASS.
    assert report['summary']['total_interfaces'] == 4
    assert report['summary']['unknowns'] == 3
    assert report['summary']['verdict'] == 'INCONCLUSIVE'


@pytest.mark.parametrize('body,width,connection,native', [
    ("if (flag) seen <= 1'b1; assign escape = flag;", '', 'link', True),
    ("if (flag + 1) seen <= 1'b1;", '', 'link', True),
    ("if (flag == 1'b1) seen <= 1'b1;", '', 'link', True),
    ("if (flag[0]) seen <= 1'b1;", '[0:0]', 'link', True),
    ("if (flag) seen <= 1'b1;", '[1:0]', 'link', True),
    ("if (flag) seen <= 1'b1;", '[0:0]', 'link[0]', True),
    ("if (flag) seen <= 1'b1;", '', 'link', False),
    ("if (flag) seen <= 1'b1; if (flag & seed) seen <= 1'b0;", '', 'link', True),
    ("seen <= seed + flag ? 1'b1 : 1'b0;", '', 'link', True),
    ("seen <= seed == flag ? 1'b1 : 1'b0;", '', 'link', True),
    ("seen <= seed <= flag ? 1'b1 : 1'b0;", '', 'link', True),
    ("seen <= 1'bz ===\nflag ? 1'b1 : 1'b0;", '', 'link', True),
])
def test_predicate_proof_refuses_other_use_or_unbound_edge(tmp_path, body, width, connection, native):
    files = _predicate_design(body, width=width, connection=connection)
    result, report = run_cli(tmp_path, files, 'top',
                             extra=('-D', 'NATIVE_PREDICATE') if native else ())
    assert result.returncode == 0, result.stderr
    assert report['discovery']['complete'] is True
    edge = _predicate_edge(report)
    assert edge['status'] == 'UNKNOWN', edge
    assert edge['consumer_encoding'] != 'PREDICATE', edge
    assert report['summary']['total_interfaces'] == 4
    assert report['summary']['verdict'] == 'INCONCLUSIVE'


def _predicate_design(body, width='', connection='link'):
    return {'design.v': f'''
module producer(input {width} seed, output {width} flag);
  assign flag = ~seed;
endmodule
module consumer(input clk, input {width} flag, output reg seen);
  wire escape;
  wire seed = 1'b1;
  always @(posedge clk) begin
    {body.replace('assign escape = flag;', '')}
  end
  {'assign escape = flag;' if 'assign escape = flag;' in body else ''}
endmodule
module top(input clk, input {width} seed, output seen);
  wire {width} link;
  producer source(.seed(seed), .flag(link));
  consumer sink(.clk(clk), .flag({connection}), .seen(seen));
endmodule
'''}


def _predicate_edge(report):
    edges = [row for row in report['interfaces'] if row['wire_name'] == 'link'
             and row['producer_port'] == row['consumer_port'] == 'flag']
    assert len(edges) == 1, report
    return edges[0]


def test_predicate_four_state_branch_lemma_in_verilog(tmp_path):
    source = tmp_path / 'branch.v'
    source.write_text('''
module branch_lemma;
  reg b;
  wire g = b ^ (b >> 1);
  integer i, direct_yes, gray_yes, direct_no, gray_no;
  initial begin
    for (i=0; i<4; i=i+1) begin
      case(i) 0:b=1'b0; 1:b=1'b1; 2:b=1'bx; 3:b=1'bz; endcase
      #1;
      direct_yes=0; gray_yes=0; direct_no=0; gray_no=0;
      if(b) direct_yes=1;
      if(g) gray_yes=1;
      if(!b) direct_no=1;
      if(!g) gray_no=1;
      if(direct_yes !== (i==1) || direct_no !== (i==0)) $fatal(1,"bad native if semantics");
      if(direct_yes !== gray_yes || direct_no !== gray_no) $fatal(1,"not invariant");
      if((b ? 4'b1010 : 4'b1001) !== (g ? 4'b1010 : 4'b1001)) $fatal(1,"ternary not invariant");
      if((!b ? 4'b1010 : 4'b1001) !== (!g ? 4'b1010 : 4'b1001)) $fatal(1,"negative ternary not invariant");
    end
    $display("FOUR_NATIVE_BRANCH_CASES_PASS");
    $finish;
  end
endmodule
''')
    compile = subprocess.run(['iverilog', '-g2012', '-o', str(tmp_path / 'branch'), str(source)],
                             capture_output=True, text=True)
    assert compile.returncode == 0, compile.stderr
    sim = subprocess.run(['vvp', str(tmp_path / 'branch')], capture_output=True, text=True)
    assert sim.returncode == 0, sim.stdout + sim.stderr
    assert 'FOUR_NATIVE_BRANCH_CASES_PASS' in sim.stdout


def test_fixed_nested_bit_select_is_retained_as_unknown_interface(tmp_path):
    files = {'design.sv': r'''
module producer(input seed, output reg flag);
  always @* flag <= seed ^ (seed >> 1);
endmodule
module consumer(input flag, output seen);
  assign seen = (flag == 1'd1);
endmodule
module top;
  wire [1:0] bus [0:1];
  producer source(.seed(1'b0), .flag(bus[0][1]));
  consumer sink(.flag(bus[0][1]), .seen());
endmodule
'''}
    result, report = run_cli(tmp_path, files, 'top')
    assert result.returncode == 0, result.stderr
    assert report['discovery']['complete'] is True
    assert report['summary']['total_interfaces'] == 1
    assert report['summary']['unknowns'] == 1
    assert report['summary']['verdict'] == 'INCONCLUSIVE'
    assert report['producer_returncode'] == 0
    row = report['interfaces'][0]
    assert row['wire_name'] == 'bus[0][1]'
    assert row['producer_module'] == 'producer'
    assert row['producer_port'] == 'flag'
    assert row['consumer_module'] == 'consumer'
    assert row['consumer_port'] == 'flag'
    assert row['producer_encoding'] == row['consumer_encoding'] == 'UNKNOWN'
    assert 'unsupported fixed nested bit-select carrier' in row['producer_evidence']
    assert 'unsupported fixed nested bit-select carrier' in row['consumer_evidence']
    assert row['status'] == 'UNKNOWN'


_PREDICATE_ONLY_SOURCE = '''
`ifdef OMITTED
`endif
module producer(input seed, output flag);
  assign flag = ~seed;
endmodule
module consumer(input flag);
  always @* if(flag) begin end
endmodule
module neutral;
  wire link;
  producer source(.seed(1'b0), .flag(link));
  consumer sink(.flag(link));
endmodule
'''


def test_predicate_receipt_is_fresh_source_evidence_not_authored_pass(tmp_path):
    result, report = run_cli(tmp_path, {'neutral.v': _PREDICATE_ONLY_SOURCE}, 'neutral')
    assert result.returncode == 0, result.stderr
    assert report['summary']['total_interfaces'] == report['summary']['matches'] == 1
    assert report['interfaces'][0]['consumer_encoding'] == 'PREDICATE'
    assert _consume_encoding_receipt(tmp_path).state == 'PASS'
    report_bytes = (tmp_path / 'out/encoding_audit_report.json').read_bytes()
    source = tmp_path / 'rtl/neutral.v'
    source.write_text(source.read_text().replace('if(flag)', "if(flag == 1'b1)"))
    assert _consume_encoding_receipt(tmp_path).state == 'NOT_MEASURED'
    assert (tmp_path / 'out/encoding_audit_report.json').read_bytes() == report_bytes


def test_issue3368_scalar_applicability_replay_cannot_hide_current_mismatch(
        tmp_path, monkeypatch):
    import _rtl_audit_applicability as applicability
    import flow_compliance_check as flow

    scalar = '''
module source(input logic en, input logic rst, output logic ready);
  assign ready = en & ~rst;
endmodule
module sink(input logic ready, output logic accepted);
  assign accepted = ready;
endmodule
module neutral;
  logic ready;
  source a(.en(1'b1), .rst(1'b0), .ready(ready));
  sink b(.ready(ready), .accepted());
endmodule
'''
    result, report = run_cli(tmp_path, {'neutral.sv': scalar}, 'neutral')
    assert result.returncode == 0, result.stdout + result.stderr
    initial = _consume_encoding_receipt(tmp_path)
    if report['summary']['verdict'] == 'PASS':
        assert initial.state == 'PASS'
    else:
        assert report['summary']['verdict'] == 'INCONCLUSIVE'
        assert initial.state == 'NOT_MEASURED'

    current = (
        "module producer(output reg [5:0] count); initial count <= 6'd0; endmodule\n"
        "module consumer(input [5:0] count); "
        "always @* if(count == 6'b110000) begin end endmodule\n"
        "module neutral; wire [5:0] count; producer p(.count(count)); "
        "consumer c(.count(count)); endmodule\n")
    rtl = tmp_path / 'rtl'
    (rtl / 'neutral.sv').write_text(current)

    # Reproduce the old replay attempt: rewrite only the receipt's declared
    # source identity to match the current bytes.  The consumer must derive
    # applicability from the current hierarchy, not trust these declarations.
    current_source = applicability.source_census(rtl)
    report['source'] = current_source
    (tmp_path / 'out/encoding_audit_report.json').write_text(
        json.dumps(report, indent=2) + '\n')
    stale = _consume_encoding_receipt(tmp_path)
    assert stale.state == 'NOT_MEASURED', stale

    project = tmp_path / 'project'
    project_rtl = project / 'phase2/stage1/rtl'
    project_rtl.mkdir(parents=True)
    (project_rtl / 'neutral.v').write_text(current)
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(
        json.dumps({'top_module': 'neutral'}))
    _enable_interface_encoding_p0(flow, monkeypatch)
    records = []
    flow._run_structural_rtl_gates(project, records_out=records)
    assert len(records) == 1
    assert records[0]['verdict'] == 'FAIL', records
    assert records[0]['evidence']['exit_code'] == 1


def test_p0_consumes_the_native_predicate_proof_without_a_waiver(tmp_path, monkeypatch):
    import flow_compliance_check as flow
    project = tmp_path / 'project'
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'neutral.v').write_text(_PREDICATE_ONLY_SOURCE)
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'neutral'}))
    _enable_interface_encoding_p0(flow, monkeypatch)
    records = []
    flow._run_structural_rtl_gates(project, records_out=records)
    assert len(records) == 1
    assert records[0]['verdict'] == 'PASS', records
    assert records[0]['evidence']['exit_code'] == 0
    assert records[0]['evidence']['receipt_state'] == 'PASS'


_CONTEXT_BINDING_SOURCE = '''
`ifdef OMITTED
`endif
module producer(output reg [5:0] count);
 initial count <= 6'd0;
endmodule
module consumer(input [5:0] count);
 always @* if(count == 6'd3) begin end
endmodule
module neutral;
 wire [5:0] count;
 producer p(.count(count)); consumer c(.count(count));
endmodule
'''


@pytest.mark.parametrize('damage', [
    'prior_context_correct_hash', 'outside_context_correct_hash',
    'embedded_context_disagrees', 'native_json_changed', 'prior_script_replay',
    'input_hash_forged', 'boolean_native_rc',
    'coherent_foreign_top', 'coherent_foreign_define', 'coherent_foreign_parameter',
])
def test_current_encoding_native_proof_refuses_context_replay(tmp_path, damage):
    prior = tmp_path / 'prior'
    current = tmp_path / 'current'
    for root in (prior, current):
        result, report = run_cli(root, {'neutral.v': _CONTEXT_BINDING_SOURCE}, 'neutral')
        assert result.returncode == 0, result.stdout + result.stderr
        assert report['summary']['matches'] == report['summary']['total_interfaces'] == 1
        assert _consume_encoding_receipt(root).state == 'PASS'
    path = current / 'out/encoding_audit_report.json'
    original = {p: p.read_bytes() for p in (current / 'out').rglob('*') if p.is_file()}
    payload = json.loads(path.read_text())
    old_payload = json.loads((prior / 'out/encoding_audit_report.json').read_text())
    cfg = payload['configuration']
    context = Path(cfg['native_context'])
    native = json.loads(context.read_text())
    try:
        if damage == 'prior_context_correct_hash':
            cfg['native_context'] = old_payload['configuration']['native_context']
            cfg['native_context_sha256'] = old_payload['configuration']['native_context_sha256']
        elif damage == 'outside_context_correct_hash':
            outside = tmp_path / 'outside-context.json'
            outside.write_bytes(context.read_bytes())
            cfg['native_context'] = str(outside)
            cfg['native_context_sha256'] = hashlib.sha256(outside.read_bytes()).hexdigest()
        elif damage == 'embedded_context_disagrees':
            cfg['native']['top'] = 'different_top'
        elif damage == 'native_json_changed':
            (context.parent / 'design.json').write_text('{}\n')
        elif damage == 'prior_script_replay':
            script = context.parent / 'elaborate.ys'
            script.write_bytes(Path(old_payload['configuration']['native_script']['path']).read_bytes())
            cfg['native_script']['text'] = script.read_text()
            cfg['native_script']['sha256'] = hashlib.sha256(script.read_bytes()).hexdigest()
        elif damage.startswith('coherent_foreign_'):
            if damage == 'coherent_foreign_top':
                cfg['top'] = native['top'] = payload['summary']['top_module'] = 'producer'
            elif damage == 'coherent_foreign_define':
                cfg['defines'] = native['defines'] = ['NOT_IN_THE_NATIVE_COMMAND']
            else:
                cfg['parameters'] = native['parameters'] = ['NOT_IN_THE_NATIVE_COMMAND=1']
            cfg['native'] = native
            context.write_text(json.dumps(native,indent=2)+'\n')
            cfg['native_context_sha256'] = hashlib.sha256(context.read_bytes()).hexdigest()
        else:
            if damage == 'input_hash_forged':
                native['input_sha256'] = {k: '0' * 64 for k in native['input_sha256']}
            else:
                native['native_returncode'] = False
            cfg['native'] = native
            context.write_text(json.dumps(native, indent=2) + '\n')
            cfg['native_context_sha256'] = hashlib.sha256(context.read_bytes()).hexdigest()
        path.write_text(json.dumps(payload, indent=2) + '\n')
        finding = _consume_encoding_receipt(current)
    finally:
        for p, data in original.items():
            p.write_bytes(data)
    assert _consume_encoding_receipt(current).state == 'PASS'
    assert finding.state == 'NOT_MEASURED', finding


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


def _counter_projection_design(kind):
    whole = kind in ('whole', 'literal_fsm', 'reset_spelling')
    width = 5 if whole else 3
    projected = 'state' if whole else 'state[6:4]'
    updates = "if (rst) state <= 5'd0; else state <= state + {4'd0, en};"
    if kind == 'xor':
        projected = 'state[6:4] ^ (state[6:4] >> 1)'
    elif kind == 'masked':
        projected = "state[6:4] & 3'd3"
    elif kind == 'mixed':
        updates = "if (rst) state <= 5'd0; else if (en) state <= state ^ (state >> 1); else state <= state + 5'd1;"
    elif kind == 'partial':
        updates += ' state[2] <= en;'
    elif kind == 'constant':
        updates = "if (rst) state <= 5'd0; else state <= 5'd4;"
    elif kind == 'computed_slice':
        projected = 'state[6-0:4]'
    elif kind == 'concat_write':
        updates += ' {state[6:4],state[3:2]} <= {state[6:4] ^ (state[6:4] >> 1),state[3:2]};'
    elif kind == 'reset_spelling':
        updates = ("if (rst && en) state <= 5'd0; else if (rst) state <= 5'h00; "
                   "else state <= state + {4'd0,en};")
    elif kind == 'literal_fsm':
        # A Gray state table remains a table even with a numeric fallback.
        updates = """if (rst) state <= 5'd0; else if (en) begin
case(state)
5'd0: state <= 5'd1;
5'd1: state <= 5'd3;
5'd3: state <= 5'd2;
5'd2: state <= 5'd6;
5'd6: state <= 5'd7;
5'd7: state <= 5'd5;
5'd5: state <= 5'd4;
5'd4: state <= 5'd0;
default: state <= state + 5'd1;
endcase
end"""
    return {'design.v': f'''
module counter_source(input clk, rst, en, output [{width-1}:0] value);
reg [6:2] state;
always @(posedge clk) begin {updates} end
assign value = {projected};
endmodule
module count_sink(input [{width-1}:0] value, output reached);
assign reached = (value == {width}'d4);
endmodule
module counter_projection(input clk, rst, en, output reached);
wire [{width-1}:0] observed;
counter_source src(.clk(clk), .rst(rst), .en(en), .value(observed));
count_sink dst(.value(observed), .reached(reached));
endmodule
'''}


@pytest.mark.parametrize('kind', ['whole', 'slice', 'reset_spelling'])
def test_binary_counter_alias_and_fixed_slice_keep_numeric_encoding(tmp_path, kind):
    res, report = run_cli(tmp_path, _counter_projection_design(kind), 'counter_projection')
    assert res.returncode == 0, res.stderr
    row, = [x for x in report['interfaces'] if x['wire_name'] == 'observed']
    assert (row['producer_encoding'], row['consumer_encoding'], row['status']) == ('BINARY', 'BINARY', 'MATCH')
    assert report['discovery']['complete'] is True


@pytest.mark.parametrize('kind', ['xor', 'masked', 'mixed', 'partial', 'constant', 'computed_slice', 'concat_write', 'literal_fsm'])
def test_counter_projection_does_not_invent_encoding_for_other_dataflows(tmp_path, kind):
    res, report = run_cli(tmp_path, _counter_projection_design(kind), 'counter_projection')
    assert res.returncode == 0, res.stderr
    row, = [x for x in report['interfaces'] if x['wire_name'] == 'observed']
    assert (row['producer_encoding'], row['status']) == ('UNKNOWN', 'UNKNOWN')


@pytest.mark.parametrize('kind,rc', [('whole', 0), ('slice', 0), ('xor', 1), ('literal_fsm', 1)])
def test_counter_projection_native_values_and_gray_transform_control(tmp_path, kind, rc):
    rtl = tmp_path / 'rtl'
    rtl.mkdir()
    source = rtl / 'design.v'
    source.write_text(_counter_projection_design(kind)['design.v'])
    shift = 0 if kind in ('whole', 'literal_fsm') else 2
    tb = tmp_path / 'probe.v'
    tb.write_text(f'''
module probe;
reg clk=0, rst=1, en=0;
wire reached;
integer expected=0, i;
counter_projection dut(.clk(clk), .rst(rst), .en(en), .reached(reached));
task tick;
begin
 #5; clk=1; #1;
 if (rst) expected=0; else expected=(expected+en)&31;
 if (dut.observed !== (expected >> {shift}))
   $fatal(1, "PROJECTION_VALUE expected=%0d observed=%0d", expected >> {shift}, dut.observed);
 if (reached !== ((expected >> {shift}) == 4)) $fatal(1, "consumer value mismatch");
 #4; clk=0;
end
endtask
initial begin
 tick();
 for (i=0;i<256;i=i+1) begin rst=(i%37==0); en=(i%3!=0); tick(); end
 $display("PROJECTION_NATIVE_PASS 257"); $finish;
end
endmodule
''')
    executable = tmp_path / 'probe.vvp'
    compile_result = subprocess.run(['iverilog', '-g2012', '-s', 'probe', '-o',
                                     str(executable), str(source), str(tb)], capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stderr
    actual = subprocess.run(['vvp', str(executable)], capture_output=True, text=True)
    (tmp_path / 'native.stdout').write_text(actual.stdout)
    (tmp_path / 'native.stderr').write_text(actual.stderr)
    (tmp_path / 'native.receipt.json').write_text(json.dumps({
        'compile_rc': compile_result.returncode, 'native_rc': actual.returncode,
        'argv': ['vvp', str(executable)]}, indent=2))
    assert actual.returncode == rc, actual.stdout + actual.stderr
    assert ('PROJECTION_NATIVE_PASS 257' in actual.stdout) == (rc == 0)
    assert ('PROJECTION_VALUE expected=2 observed=3' in actual.stdout) == (kind in ('xor', 'literal_fsm'))


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


def test_receipt_consumer_refuses_unknown_rows_dropped_from_population(tmp_path):
    res, report = run_cli(tmp_path, {'neutral.v': _OPTIONAL_SOURCE}, 'neutral')
    assert res.returncode == 0, res.stderr
    assert (report['summary']['total_interfaces'], report['summary']['unknowns']) == (3, 2)
    retained = [row for row in report['interfaces'] if row['status'] == 'MATCH']
    assert len(retained) == 1
    report['interfaces'] = retained
    report['summary'].update(total_interfaces=1, matches=1, mismatches=0,
                             unknowns=0, verdict='PASS')
    # Keep every redundant count internally consistent so this mutation tests
    # the population binding itself, not the earlier generic count validator.
    report['semantic_coverage'].update(
        complete=True, total_interfaces=1, decided=1,
        not_applicable=0, unknown=0)
    report['producer_returncode'] = 0
    (tmp_path / 'out/encoding_audit_report.json').write_text(json.dumps(report))
    finding = _consume_encoding_receipt(tmp_path)
    assert finding.state == 'NOT_MEASURED'
    assert 'interface_population_binding_mismatch' in finding.detail


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
    _enable_interface_encoding_p0(flow, monkeypatch)
    records = []
    flow._run_structural_rtl_gates(project, records_out=records)
    assert len(records) == 1
    assert records[0]['verdict'] == verdict, records


@pytest.mark.parametrize('literal,verdict', [("6'd3", 'PASS'), ("6'b110000", 'FAIL')])
def test_p0_encoding_receipt_survives_dispatch_and_storage_gate(tmp_path, monkeypatch,
                                                               literal, verdict):
    import flow_compliance_check as flow
    project = tmp_path / 'project'
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'neutral'}))
    (rtl / 'neutral.v').write_text(
        "module producer(output reg [5:0] count); initial count <= 6'd0; endmodule\n"
        "module consumer(input [5:0] count); always @* if(count == " + literal +
        ") begin end endmodule\n"
        "module neutral; wire [5:0] count; generate if (1) begin : active "
        "producer p(.count(count)); consumer c(.count(count)); end endgenerate endmodule\n")
    _enable_interface_encoding_p0(flow, monkeypatch)
    records = []
    flow._run_structural_rtl_gates(project, records_out=records)
    assert records[0]['verdict'] == verdict
    # This is the normal persisted consumer record, after worker cleanup.
    report = project / 'reports/phase2/gates/stage1_compliance.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'steps': [{'step': 'P0', 'gate_records': records}]}))
    stored = subprocess.run([sys.executable, str(SCRIPT.parent / 'project_outputs_in_tree_check.py'),
                             str(project)], capture_output=True, text=True)
    assert stored.returncode == 0, stored.stdout + stored.stderr
    receipts = list((project / '.vibeic-state/audit_receipts').rglob('encoding_audit_report.json'))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    context = Path(receipt['configuration']['native_context'])
    assert context.is_file()
    assert context.resolve().is_relative_to(project.resolve())
    if verdict == 'PASS':
        assert receipts[0].as_posix() in records[0]['evidence']['receipt_detail']


def test_p0_encoding_receipt_refuses_outside_project_state_alias(tmp_path, monkeypatch):
    import flow_compliance_check as flow
    project = tmp_path / 'project'
    rtl = project / 'rtl'
    rtl.mkdir(parents=True)
    (rtl / 'neutral.v').write_text('module neutral(input d, output q); assign q=d; endmodule\n')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (project / '.vibeic-state').symlink_to(outside, target_is_directory=True)
    _enable_interface_encoding_p0(flow, monkeypatch)
    with pytest.raises(ValueError, match='AUDIT_RECEIPT_OUTSIDE_PROJECT'):
        flow._run_structural_rtl_gates(project, records_out=[])
    assert list(outside.iterdir()) == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
