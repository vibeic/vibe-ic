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
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))





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
    r = _pr.run([tclsh, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "new 100x50" in r.stdout
    assert "old 100x50" in r.stdout
