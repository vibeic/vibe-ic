"""v0.2.72 — #441 residual: stub/fallback SDF never satisfies the gate.

v0.2.67 already escalated NO_SDF_REF→ERROR and stopped the runner
recycling the RTL pass.flag (sdf_sim_skipped.json + step-28 cap-gap).
This closes the remaining hole the issue names: `_emit_sdf` wrote a
syntactically-valid EMPTY DELAYFILE ("fallback ... NOT a real SDF")
when write_sdf failed, and the gate counted any *.sdf presence as
sdf_found — a fabricated artifact satisfying a sign-off input.

Pins:
  * runner: no stub SDF on write_sdf failure — a plainly-named
    sdf_emit_failed.txt note instead (source pin);
  * gate: a self-marked fallback SDF is excluded (STUB_SDF ERROR) and
    does not count as sdf_found.

chip-AGNOSTIC: structural/marker rules only.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROG = PLUGIN / "programs" / "post_layout_sim_check.py"
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()

_STUB_SDF = """\
// OpenROAD write_sdf — fallback (rc=1). NOT a real SDF.
(DELAYFILE
  (SDFVERSION "3.0")
  (DESIGN "top")
  (PROGRAM "openroad write_sdf (fallback)")
)
"""

_GOOD_LOG = 'Using $sdf_annotate("timing.sdf")\nAll tests passed\n'


def _run(tmp_path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path),
         "--json", str(tmp_path / "out.json")],
        capture_output=True, text=True)


def test_stub_sdf_does_not_count_as_sdf(tmp_path):
    sim = tmp_path / "phase3" / "stage3" / "sim_postlayout"
    sim.mkdir(parents=True)
    (sim / "top.sdf").write_text(_STUB_SDF)
    (sim / "results.log").write_text(_GOOD_LOG)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "out.json").read_text())
    assert rep["summary"]["sdf_found"] is False
    assert any(f["category"] == "STUB_SDF" for f in rep["findings"])


def test_real_sdf_still_passes(tmp_path):
    sim = tmp_path / "phase3" / "stage3" / "sim_postlayout"
    sim.mkdir(parents=True)
    (sim / "top.sdf").write_text(
        '(DELAYFILE (SDFVERSION "3.0") (DESIGN "top")\n'
        ' (CELL (CELLTYPE "buf") (INSTANCE u1)\n'
        '  (DELAY (ABSOLUTE (IOPATH A X (0.1) (0.1))))))\n')
    (sim / "results.log").write_text(_GOOD_LOG)
    r = _run(tmp_path)
    assert r.returncode == 0


def test_runner_no_longer_writes_stub_sdf():
    assert "NOT a real SDF" not in _P3_SRC
    i = _P3_SRC.index("sdf_emit_failed.txt")
    window = _P3_SRC[i - 900:i + 600]
    assert "NO stub SDF" in window
    assert "#441" in window
