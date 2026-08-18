"""Unit tests for the two advisory WARN rules added to spec_conformance_check.py:

  • pipelined-width-not-parameterized
        ORGANIC-20260528-pipelined-adder-canonical-params
        Spec says "pipelined N-bit adder/multiplier" but the RTL hardcodes N
        with no module parameter → WARN to add `parameter DATA_WIDTH = N`.

  • onebased-port-range
        ORGANIC-20260528-spec-conformance-onebased-port-range
        Prompt references S[k] up to k == width while the port is declared
        zero-based [W-1:0] → WARN to declare [W:1] (1-based) instead.

Both are WARN severity (advisory): they never raise the exit code above 0.
Each rule is tested with a PASS path, a real FAIL (WARN-firing) path, and a
missing-data honesty case (no spec body / no RTL → vacuously nothing fires).
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / 'spec_conformance_check.py'
assert SCRIPT.exists()


def run(tmp_path, spec_text, sv, spec_ext='.md', *extra):
    spec = tmp_path / f'spec{spec_ext}'
    spec.write_text(spec_text)
    rtl = tmp_path / 'dut.sv'
    rtl.write_text(sv)
    jf = tmp_path / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--spec', str(spec),
         '--json', str(jf), *extra, str(rtl)],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text()) if jf.exists() else []
    return res, findings


def rules(findings):
    return {f['rule'] for f in findings}


def warns(findings):
    return {f['rule'] for f in findings if f['severity'] == 'WARN'}


# ===========================================================================
# Backlog 1: pipelined-width-not-parameterized
# ===========================================================================
# Prose-only spec (no NL port bullets) so the port-conformance ERRORs do not
# fire — this isolates the advisory WARN under test. The pipelined-width rule
# scans the prose body + the RTL port widths, never spec.ports.
SPEC_PIPELINED_ADDER = (
    "Design a 64-bit pipelined adder. The module accumulates two 64-bit "
    "operands across pipeline stages and registers the carry.\n"
)

# RTL hardcodes width 64 on every port, with NO module parameter.
RTL_PIPE_HARDCODED = """
module pipe_adder(
    input  clk,
    input  [63:0] a,
    input  [63:0] b,
    output reg [63:0] sum
);
  reg [63:0] s0;
  always @(posedge clk) begin s0 <= a + b; sum <= s0; end
endmodule
"""

# RTL parameterizes the width — already canonical → must NOT warn.
RTL_PIPE_PARAMETERIZED = """
module pipe_adder #(parameter DATA_WIDTH = 64, parameter STG_WIDTH = 16) (
    input  clk,
    input  [DATA_WIDTH-1:0] a,
    input  [DATA_WIDTH-1:0] b,
    output reg [DATA_WIDTH-1:0] sum
);
  reg [DATA_WIDTH-1:0] s0;
  always @(posedge clk) begin s0 <= a + b; sum <= s0; end
endmodule
"""


def test_pipelined_hardcoded_width_warns(tmp_path):
    res, f = run(tmp_path, SPEC_PIPELINED_ADDER, RTL_PIPE_HARDCODED)
    # WARN fires; advisory only → exit 0, never a hard FAIL.
    assert 'pipelined-width-not-parameterized' in warns(f)
    assert res.returncode == 0
    msg = next(x['message'] for x in f
               if x['rule'] == 'pipelined-width-not-parameterized')
    assert 'DATA_WIDTH = 64' in msg
    assert 'STG_WIDTH = 16' in msg   # 64 // 4


def test_pipelined_parameterized_does_not_warn(tmp_path):
    res, f = run(tmp_path, SPEC_PIPELINED_ADDER, RTL_PIPE_PARAMETERIZED)
    assert 'pipelined-width-not-parameterized' not in rules(f)
    assert res.returncode == 0


def test_pipelined_no_pipeline_word_does_not_warn(tmp_path):
    # A plain (non-pipelined) hardcoded adder must NOT warn — the rule is
    # scoped to the canonical *pipelined* arithmetic convention.
    spec = "Design a 64-bit adder that computes the sum of two operands.\n"
    res, f = run(tmp_path, spec, RTL_PIPE_HARDCODED)
    assert 'pipelined-width-not-parameterized' not in rules(f)
    assert res.returncode == 0


def test_pipelined_non_arithmetic_does_not_warn(tmp_path):
    # "pipelined" + a width but NO arithmetic noun → not the targeted class.
    spec = "A 64-bit pipelined data buffer that shifts data through stages.\n"
    res, f = run(tmp_path, spec, RTL_PIPE_HARDCODED)
    assert 'pipelined-width-not-parameterized' not in rules(f)


def test_pipelined_json_contract_no_warn(tmp_path):
    # JSON contracts carry no prose body → the prose-scan WARN must not fire
    # (honesty: no body to scan, so vacuously nothing, never a false WARN).
    spec = json.dumps({
        "module": "pipe_adder",
        "ports": [{"name": "clk", "direction": "input", "width": 1},
                  {"name": "a", "direction": "input", "width": 64},
                  {"name": "b", "direction": "input", "width": 64},
                  {"name": "sum", "direction": "output", "width": 64}],
    })
    res, f = run(tmp_path, spec, RTL_PIPE_HARDCODED, '.json')
    assert 'pipelined-width-not-parameterized' not in rules(f)
    assert res.returncode == 0


# ===========================================================================
# Backlog 2: onebased-port-range
# ===========================================================================
# Prompt references x[1]..x[4] (1-based, max index == width 4). The reference
# port should be [4:1]; declaring [3:0] shifts every index.
SPEC_ONEBASED = (
    "Implement a module named TopModule. The 4-bit input x feeds a K-map.\n"
    "The output f is a function of the four bits x[1], x[2], x[3], x[4].\n"
    " - input  x (4 bits)\n"
    " - output f\n"
)

RTL_X_ZEROBASED = """
module TopModule(input [3:0] x, output f);
  assign f = x[0] & x[1] & x[2] & x[3];
endmodule
"""

RTL_X_ONEBASED = """
module TopModule(input [4:1] x, output f);
  assign f = x[1] & x[2] & x[3] & x[4];
endmodule
"""


def test_onebased_index_with_zerobased_port_warns(tmp_path):
    res, f = run(tmp_path, SPEC_ONEBASED, RTL_X_ZEROBASED)
    assert 'onebased-port-range' in warns(f)
    assert res.returncode == 0   # advisory only
    msg = next(x['message'] for x in f if x['rule'] == 'onebased-port-range')
    assert '[4:1]' in msg and '[3:0]' in msg


def test_onebased_index_with_onebased_port_no_warn(tmp_path):
    # RTL already declares [4:1] → no shift, no warning.
    res, f = run(tmp_path, SPEC_ONEBASED, RTL_X_ONEBASED)
    assert 'onebased-port-range' not in rules(f)
    assert res.returncode == 0


def test_zerobased_index_does_not_warn(tmp_path):
    # The conservative guard: a width-100 signal referenced up to in[99] is a
    # legitimate zero-based signal (maxidx == width-1) → must NOT warn.
    spec = (
        "Implement a module named TopModule. The 100-bit input in is examined:\n"
        "the MSB in[99] and the LSB in[0] are special.\n"
        " - input  in (100 bits)\n - output out\n"
    )
    rtl = """
module TopModule(input [99:0] in, output out);
  assign out = in[99] ^ in[0];
endmodule
"""
    res, f = run(tmp_path, spec, rtl, '.txt')
    assert 'onebased-port-range' not in rules(f)
    assert res.returncode == 0


def test_onebased_partial_select_does_not_warn(tmp_path):
    # maxidx must be EXACTLY the bit-count; here x is 8-bit but only x[4] is
    # referenced (maxidx 4 != 8) → no warn (not a clean 1-based signal).
    spec = (
        "Implement a module named TopModule. Bit x[4] of the 8-bit input x is "
        "the parity bit.\n - input  x (8 bits)\n - output f\n"
    )
    rtl = """
module TopModule(input [7:0] x, output f);
  assign f = x[4];
endmodule
"""
    res, f = run(tmp_path, spec, rtl, '.txt')
    assert 'onebased-port-range' not in rules(f)
    assert res.returncode == 0


def test_onebased_json_contract_no_warn(tmp_path):
    # Honesty: JSON contract has no prose body to scan for x[k] → no WARN.
    spec = json.dumps({
        "module": "TopModule",
        "ports": [{"name": "x", "direction": "input", "width": 4},
                  {"name": "f", "direction": "output", "width": 1}],
    })
    res, f = run(tmp_path, spec, RTL_X_ZEROBASED, '.json')
    assert 'onebased-port-range' not in rules(f)
    assert res.returncode == 0


# ===========================================================================
# Missing-data honesty: no RTL files / no spec → tool FAILs honestly (exit 2),
# never a vacuous PASS, and certainly never a spurious WARN.
# ===========================================================================
def test_missing_rtl_fails_honestly(tmp_path):
    spec = tmp_path / 'spec.md'
    spec.write_text(SPEC_PIPELINED_ADDER)
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--spec', str(spec)],
        capture_output=True, text=True)
    assert res.returncode == 2
    assert 'no RTL files found' in res.stderr


def test_missing_spec_fails_honestly(tmp_path):
    rtl = tmp_path / 'dut.sv'
    rtl.write_text(RTL_PIPE_HARDCODED)
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--spec', str(tmp_path / 'nope.md'),
         str(rtl)],
        capture_output=True, text=True)
    assert res.returncode == 2
    assert 'spec not found' in res.stderr
