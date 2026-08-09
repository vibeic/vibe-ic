"""Unit tests for spec_rtl_port_fidelity_check.py.

Covers the prompt/spec port-fidelity gap behind VerilogEval-v2 Prob099
(garbled spec → wrong ports) and the L9↔RTL exact-match contract.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import spec_rtl_port_fidelity_check as fidelity  # noqa: E402 (conftest sys.path)

SCRIPT = Path(__file__).parent.parent / 'spec_rtl_port_fidelity_check.py'
assert SCRIPT.exists()


def run(tmp_path, sv, *extra):
    f = tmp_path / 'dut.v'
    f.write_text(sv)
    jf = tmp_path / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--json', str(jf), *extra, str(f)],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text()) if jf.exists() else []
    return res, findings


def rules(f):
    return {x['rule'] for x in f}


# --- the CALLER shape -------------------------------------------------------
# `eda_rtl_audit` (mcp-eda/src/index.js) spawns this program as
#     python3 spec_rtl_port_fidelity_check.py <rtl_dir>
# — one positional directory, NO --spec, NO --strict. Everything below that
# claims to be about the caller uses exactly that argv.

def run_dir(tmp_path, sources, *extra):
    """Run the program the way its only programmatic caller runs it."""
    d = tmp_path / 'rtl'
    d.mkdir(exist_ok=True)
    for name, txt in sources.items():
        (d / name).write_text(txt)
    return subprocess.run([sys.executable, str(SCRIPT), *extra, str(d)],
                          capture_output=True, text=True)


def findings_of(tmp_path, res_args, sources):
    jf = tmp_path / 'findings.json'
    run_dir(tmp_path, sources, '--json', str(jf), *res_args)
    return json.loads(jf.read_text()) if jf.exists() else []


_DROPPED_ENUM_PORT = """
module top(input a, input b, output y1, output y3);
  assign y1 = a & b; assign y3 = a | b;
endmodule
"""


def test_dropped_enumerated_port_fails_in_the_caller_shape(tmp_path):
    """FAIL must be REACHABLE with no --spec and no --strict.

    Regression for the unreachable-verdict defect: every standalone rule used
    to be WARN-only, so `errs` was empty by construction and the caller-shaped
    invocation could only ever exit 0 / print PASS — including on the exact
    dropped-port signature this program exists to detect.
    """
    res = run_dir(tmp_path, {'dut.v': _DROPPED_ENUM_PORT})
    assert res.returncode == 1, res.stdout + res.stderr
    assert 'FAIL' in res.stdout
    assert '(1 error' in res.stdout

    f = findings_of(tmp_path, (), {'dut.v': _DROPPED_ENUM_PORT})
    errs = [x for x in f if x['severity'] == 'ERROR']
    assert [x['rule'] for x in errs] == ['port-index-gap']
    assert errs[0]['symbol'] == 'y'
    assert 'y2' in errs[0]['message']


# A value-encoding numeric suffix (`out_8` / `out_16`) is NOT an enumeration:
# it starts at 8 and leaves a hole (9..15) far larger than the family. It stays
# an advisory WARN, so a run carrying only this shape stays green.
_VALUE_SUFFIX_PORTS = """
module top(input clk, input d0, input d1, input d2,
           output out_8, output out_16);
  assign out_8 = d0 & d1; assign out_16 = d2 | clk;
endmodule
"""


def test_advisory_gap_and_clean_enumeration_still_pass(tmp_path):
    """PASS must stay REACHABLE — the fix must not make the gate always-fail.

    Two shapes in one module: a contiguous enumeration (`d0,d1,d2`, no finding
    at all) and a value-encoding suffix family (`out_8,out_16`, WARN). Neither
    may produce an ERROR, and the run must exit 0 / print PASS.
    """
    res = run_dir(tmp_path, {'dut.v': _VALUE_SUFFIX_PORTS})
    assert res.returncode == 0, res.stdout + res.stderr
    assert 'PASS' in res.stdout
    assert 'FAIL' not in res.stdout

    f = findings_of(tmp_path, (), {'dut.v': _VALUE_SUFFIX_PORTS})
    assert not [x for x in f if x['severity'] == 'ERROR']
    warns = [x for x in f if x['rule'] == 'port-index-gap']
    assert warns and warns[0]['severity'] == 'WARN'
    assert warns[0]['symbol'] == 'out_'
    assert not [x for x in f if x['symbol'] == 'd']   # contiguous → no finding


def test_index_gap_severity_split_is_arithmetic():
    """The ERROR/WARN split is decided by the family's own integers only."""
    sev = fidelity.index_gap_severity
    assert sev([1, 3], [2]) == 'ERROR'            # dropped member, 1-based
    assert sev([0, 1, 3], [2]) == 'ERROR'         # dropped member, 0-based
    assert sev([8, 16], list(range(9, 16))) == 'WARN'   # value suffix
    assert sev([0, 32], list(range(1, 32))) == 'WARN'   # hole >> family
    # A deliberately SPARSE tap family (several disjoint holes) is not an
    # omission — this shape occurs in a currently-green module of the corpus
    # and must stay advisory.
    assert sev([0, 1, 2, 3, 7, 11, 12], [4, 5, 6, 8, 9, 10]) == 'WARN'


def test_contiguous_indices_clean(tmp_path):
    sv = """
module top(input a, output Y1, output Y2, output Y3);
  assign Y1=a; assign Y2=a; assign Y3=a;
endmodule
"""
    _, f = run(tmp_path, sv)
    assert 'port-index-gap' not in rules(f)


def test_duplicate_port_is_warn(tmp_path):
    sv = "module top(input a, input a, output y); assign y=a; endmodule\n"
    _, f = run(tmp_path, sv)
    assert 'duplicate-port' in rules(f)


def test_spec_compare_missing_and_extra_error(tmp_path):
    sv = """
module top(input a, input b, output Y1, output Y3);
  assign Y1=a; assign Y3=b;
endmodule
"""
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps([
        {"name": "a", "direction": "input", "width": 1},
        {"name": "b", "direction": "input", "width": 1},
        {"name": "Y1", "direction": "output", "width": 1},
        {"name": "Y2", "direction": "output", "width": 1},
    ]))
    res, f = run(tmp_path, sv, '--spec', str(spec))
    assert res.returncode == 1
    assert 'port-missing' in rules(f)     # spec Y2 absent in RTL
    assert 'port-extra' in rules(f)       # RTL Y3 absent in spec


def test_spec_compare_exact_match_pass(tmp_path):
    sv = """
module top(input clk, input [7:0] d, output [7:0] q);
  assign q = d;
endmodule
"""
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps([
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "d", "direction": "input", "width": 8},
        {"name": "q", "direction": "output", "width": 8},
    ]))
    res, f = run(tmp_path, sv, '--spec', str(spec))
    assert res.returncode == 0
    assert not any(x['severity'] == 'ERROR' for x in f)


def test_width_and_direction_mismatch_error(tmp_path):
    sv = """
module top(input clk, input [3:0] d, output [7:0] q);
  assign q = d;
endmodule
"""
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps([
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "d", "direction": "input", "width": 8},   # RTL is 4
        {"name": "q", "direction": "input", "width": 8},   # RTL is output
    ]))
    res, f = run(tmp_path, sv, '--spec', str(spec))
    assert res.returncode == 1
    assert 'port-width-mismatch' in rules(f)
    assert 'port-direction-mismatch' in rules(f)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
