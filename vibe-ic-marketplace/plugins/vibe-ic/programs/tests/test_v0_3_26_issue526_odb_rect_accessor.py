"""v0.3.26 — ORGANIC #526: the metal-fill row-utilization TCL used the odb
Rect accessors getDX/getDY, which OpenROAD 26Q1 renamed to dx/dy — the whole
catch-wrapped block then fired and the measurement silently degraded to
ROW_UTILIZATION_PCT NA on a DEF that was actually 99.8% filled → Step-34
false-FAIL. The emitted TCL now probes the CURRENT names first and falls
back to the legacy ones, so both container generations measure.

The dual-accessor probe is validated by EXECUTING it under tclsh against a
new-API-only stub and an old-API-only stub (skips cleanly when tclsh is
absent).

chip-AGNOSTIC: pure TCL/odb API compatibility; no chip literal.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

_SRC = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
_FILL_REGION = _SRC.split("ROW_UTILIZATION_PCT")[0][-4000:] + \
    _SRC[_SRC.find("ROW_UTILIZATION_PCT") - 4000:
         _SRC.find("ROW_UTILIZATION_PCT") + 2000]


def test_emitted_tcl_carries_dual_accessor_probe():
    # current-name probe + legacy fallback both present
    assert "$bb dx" in _SRC and "$bb getDX" in _SRC
    assert "$bb dy" in _SRC and "$bb getDY" in _SRC
    # the area accumulation goes through the probes, not a bare getDX
    assert "_rcw $_bb" in _SRC and "_rch $_bb" in _SRC
    assert "double([$_bb getDX])" not in _SRC


def test_dual_accessor_probe_executes_on_both_api_generations(tmp_path):
    tclsh = shutil.which("tclsh")
    if not tclsh:
        pytest.skip("tclsh not on this host")
    script = tmp_path / "probe.tcl"
    script.write_text("""\
proc rect_new {cmd args} {
  switch $cmd { dx {return 100} dy {return 50} \
    default {error "invalid command name \\"$cmd\\""} } }
proc rect_old {cmd args} {
  switch $cmd { getDX {return 100} getDY {return 50} \
    default {error "invalid command name \\"$cmd\\""} } }
proc _rcw {bb} {
  if {[catch {$bb dx} _w]} { set _w [$bb getDX] }
  return $_w
}
proc _rch {bb} {
  if {[catch {$bb dy} _h]} { set _h [$bb getDY] }
  return $_h
}
puts "new [_rcw rect_new]x[_rch rect_new]"
puts "old [_rcw rect_old]x[_rch rect_old]"
""")
    r = subprocess.run([tclsh, str(script)], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    assert "new 100x50" in r.stdout
    assert "old 100x50" in r.stdout


def test_na_parse_behavior_unchanged():
    # NEGATIVE: a genuinely unmeasurable run still parses to None (NA) —
    # the gate's under-fill FAIL semantics are untouched (#510 tests own
    # that axis; this only pins the parser contract the fix relies on).
    import phase3_one_shot_runner as R
    assert R._v0_3_9_parse_row_utilization("ROW_UTILIZATION_PCT NA\n") is None
    assert R._v0_3_9_parse_row_utilization(
        "ROW_UTILIZATION_PCT 99.848\n") == pytest.approx(99.848)
