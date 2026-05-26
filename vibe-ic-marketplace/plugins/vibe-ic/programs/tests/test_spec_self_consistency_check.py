"""Unit tests for spec_self_consistency_check.py (pre-RTL spec self-consistency lint).

Anchored to two real benchmark misses this lint exists to catch — from the spec ALONE,
before any RTL exists:
  • VerilogEval-v2 Prob099: interface declares Y1,Y3 but the body says "Y2 and Y4"
    (garbled spec). `body-port-gap`.
  • CVDP arbiter: a spec asserting both synchronous and asynchronous reset.
    `reset-mode-contradiction`.
And the key NON-finding: Prob085-style "async areset + synchronous load/enable" must
NOT trip the reset contradiction (synchronous qualifies a control signal, not the reset).
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / 'spec_self_consistency_check.py'
assert SCRIPT.exists()


def run(tmp_path, spec_text, ext='.md', *extra):
    spec = tmp_path / f'spec{ext}'
    spec.write_text(spec_text)
    jf = tmp_path / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--json', str(jf), *extra, str(spec)],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text())['findings'] if jf.exists() else []
    return res, findings


def codes(findings):
    return {f['code'] for f in findings}


# ---- body-port-gap : the Prob099 garbled-spec signature, pre-RTL -----------
PROB099 = """\
Implement a module named TopModule with the following interface.
 - input  y (6 bits)
 - input  w
 - output Y1
 - output Y3
Consider the state machine shown below ... The module should implement the
next-state signals Y2 and Y4.
"""


def test_body_port_gap_fires_on_garbled_spec(tmp_path):
    res, f = run(tmp_path, PROB099)
    assert 'body-port-gap' in codes(f)
    # it is a WARN, so without --strict the gate still PASSes (exit 0)
    assert res.returncode == 0
    msg = next(x['message'] for x in f if x['code'] == 'body-port-gap')
    assert 'Y2' in msg and 'Y4' in msg


def test_body_port_gap_strict_fails(tmp_path):
    res, f = run(tmp_path, PROB099, '.md', '--strict')
    assert res.returncode == 1  # WARN fails under --strict


def test_body_port_gap_quiet_when_self_consistent(tmp_path):
    # numbered family Y1,Y2,Y3 all declared and only those referenced → no gap
    spec = """\
 - input  clk
 - output Y1
 - output Y2
 - output Y3
Drive Y1, Y2 and Y3 from the state vector.
"""
    res, f = run(tmp_path, spec)
    assert 'body-port-gap' not in codes(f)
    assert res.returncode == 0


# ---- reset-mode-contradiction : the CVDP lesson ----------------------------
def test_reset_mode_contradiction_fires(tmp_path):
    spec = """\
 - input clk
 - input reset
 - output q
The design uses a synchronous reset. Note elsewhere: the reset is asynchronous.
"""
    res, f = run(tmp_path, spec)
    assert 'reset-mode-contradiction' in codes(f)
    assert res.returncode == 1  # ERROR fails the gate


def test_reset_polarity_contradiction_fires(tmp_path):
    spec = """\
 - input clk
 - input reset
 - output q
An active-high reset is used here, but the reset is active-low per the table.
"""
    res, f = run(tmp_path, spec)
    assert 'reset-polarity-contradiction' in codes(f)


# ---- the critical NON-finding: Prob085 (async reset + synchronous load) ----
def test_async_reset_with_synchronous_load_is_not_a_contradiction(tmp_path):
    spec = """\
 - input  areset
 - input  load
asynchronous positive edge triggered areset, synchronous active high
signals load, and enable.
  (1) areset: Resets shift register to zero.
  (2) load: Loads shift register with data[3:0] instead of shifting.
"""
    res, f = run(tmp_path, spec)
    assert 'reset-mode-contradiction' not in codes(f)
    assert res.returncode == 0


# ---- duplicate declared port ----------------------------------------------
def test_duplicate_port(tmp_path):
    spec = """\
 - input  clk
 - output q
 - output q
"""
    res, f = run(tmp_path, spec)
    assert 'duplicate-port' in codes(f)


# ---- clean spec passes -----------------------------------------------------
def test_clean_spec_passes(tmp_path):
    spec = """\
Implement TopModule.
 - input  a
 - input  b
 - output out
out is the AND of a and b.
"""
    res, f = run(tmp_path, spec)
    assert f == []
    assert res.returncode == 0


# ---- no spec file -> exit 2 ------------------------------------------------
def test_missing_spec_exits_2(tmp_path):
    res = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / 'nope.md')],
                         capture_output=True, text=True)
    assert res.returncode == 2
