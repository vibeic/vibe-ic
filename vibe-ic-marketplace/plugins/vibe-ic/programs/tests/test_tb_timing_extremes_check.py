#!/usr/bin/env python3
"""Tests for tb_timing_extremes_check.py (LL-6)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "tb_timing_extremes_check.py"


def _run(tmp_path: Path, strict: bool = False):
    cmd = [sys.executable, str(PROG), str(tmp_path),
           "--json", str(tmp_path / "rep.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_l2(tmp_path: Path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
    }))


def _write_tb(tmp_path: Path, body: str):
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "tb_full_stack.sv").write_text(body)


def test_tb_only_max_warns(tmp_path):
    _make_l2(tmp_path)
    _write_tb(tmp_path, """\
module tb;
  initial host_idle(22000);  // only ibt_max
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "TB_TIMING_EXTREMES_NOT_COVERED"
               for f in rep["findings"])


def test_tb_only_min_warns(tmp_path):
    _make_l2(tmp_path)
    _write_tb(tmp_path, """\
module tb;
  initial host_idle(20000);  // only ibt_min
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1


def test_tb_both_extremes_passes(tmp_path):
    _make_l2(tmp_path)
    _write_tb(tmp_path, """\
module tb;
  initial begin
    host_idle(20000);  // ibt_min
    host_idle(22000);  // ibt_max
  end
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_no_l2_skipped(tmp_path):
    _write_tb(tmp_path, "module tb; endmodule")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_no_tb_skipped(tmp_path):
    _make_l2(tmp_path)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0  # no TB → skip


def test_huge_span_class_skipped(tmp_path):
    """BOR class (500us-999999us) span ratio = 1999. Should be skipped
    automatically — testing the 999999us extreme is impractical."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
        "pulse_classes": [
            {"class_name": "BIT0", "min_us": 3.6, "max_us": 9.4},
            {"class_name": "BOR", "min_us": 500.0, "max_us": 999999.0},
        ],
    }))
    _write_tb(tmp_path, """\
module tb;
  initial begin
    host_idle(20000);
    host_idle(22000);
    host_low(3600);
    host_low(9400);
  end
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any("BOR" in c for c in rep["summary"]["skipped_classes"])
    # ibt + BIT0 covered, BOR auto-skipped → PASS
    assert "BOR" not in rep["summary"]["l2_ranges"]


def test_waiver_skips(tmp_path):
    _make_l2(tmp_path)
    _write_tb(tmp_path, "module tb; initial host_idle(22000); endmodule")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "tb_timing_extremes_override",
            "rationale": "TB at one extreme; compliance tested via FPGA only",
        }],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# The layer the flow ACTUALLY emits (L8_TIMING_WAVEFORM.json).
#
# Every fixture above hand-writes `L2_TIMING_WAVEFORM.json`. No program in this
# plugin has ever written that file: over the published benchmark corpus it
# occurs 0 times and `L8_TIMING_WAVEFORM.json` occurs 175 times. So the suite
# above was green while `_l2_ranges` returned `{}` on every real run and the
# gate answered PASS unconditionally — including under `--strict`.
#
# These tests are written against the file a producer fills. They are red
# against the program as it stood before that source was added.
# ---------------------------------------------------------------------------


def _make_l8(tmp_path: Path, windows):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "schema_version": "1",
        "doc_class": "timing_waveform",
        "timing_windows": windows,
        "timing_constants": [],
        "waveforms": [],
    }))


def test_l8_ranged_window_uncovered_extreme_fires(tmp_path):
    """The flaw the gate exists to catch, stated in the live layer."""
    _make_l8(tmp_path, [{"name": "bit_cell", "min_us": 20.0, "max_us": 22.0}])
    _write_tb(tmp_path, """\
module tb;
  initial host_idle(22000);  // only the max end of [20, 22]us
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["passed"] is False
    assert any(f["rule"] == "TB_TIMING_EXTREMES_NOT_COVERED"
               for f in rep["findings"]), rep["findings"]
    cov = rep["summary"]["extremes_covered"]["bit_cell"]
    assert cov["near_min"] is False and cov["near_max"] is True


def test_l8_ranged_window_both_extremes_covered_passes(tmp_path):
    """Same live layer, TB driving both ends: the gate must NOT fire."""
    _make_l8(tmp_path, [{"name": "bit_cell", "min_us": 20.0, "max_us": 22.0}])
    _write_tb(tmp_path, """\
module tb;
  initial begin
    host_idle(20000);
    host_idle(22000);
  end
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["findings"] == []
    # The range was READ, not skipped. Before the fix this dict was empty and
    # `skipped_reason` said "no L2 timing ranges to verify".
    assert rep["summary"]["l2_ranges"]["bit_cell"] == [20.0, 22.0]
    assert rep["summary"]["skipped_reason"] == ""


def test_l8_window_bounds_in_different_units_pair_up(tmp_path):
    """min stated in ns, max stated in us — one range, normalised to us."""
    _make_l8(tmp_path, [{"name": "gap", "min_ns": 20000.0, "max_us": 22.0}])
    _write_tb(tmp_path, """\
module tb;
  initial host_idle(22000);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["summary"]["l2_ranges"]["gap"] == [20.0, 22.0]


def test_l8_single_bound_window_is_not_a_range(tmp_path):
    """A window with only a max is not a range and must not be reported as
    one — the gate stays silent rather than inventing a minimum of zero."""
    _make_l8(tmp_path, [{"name": "setup", "max_ns": 10.0}])
    _write_tb(tmp_path, """\
module tb;
  initial host_idle(5000);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["summary"]["l2_ranges"] == {}
    assert rep["summary"]["skipped_reason"] == "no L2 timing ranges to verify"


def test_l8_unnamed_window_still_yields_a_range(tmp_path):
    """A ranged window with no `name` is still a range; it is keyed by index
    rather than dropped."""
    _make_l8(tmp_path, [{"min_us": 20.0, "max_us": 22.0}])
    _write_tb(tmp_path, """\
module tb;
  initial host_idle(22000);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert "timing_windows[0]" in rep["summary"]["l2_ranges"]


def test_legacy_l2_layer_still_read_when_present(tmp_path):
    """The live layer is a UNION with the legacy one, not a replacement:
    nothing that used to be measurable stops being measurable."""
    _make_l2(tmp_path)
    _make_l8(tmp_path, [{"name": "gap", "min_us": 30.0, "max_us": 33.0}])
    _write_tb(tmp_path, """\
module tb;
  initial host_idle(22000);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, r.stdout + r.stderr
    rep = json.loads((tmp_path / "rep.json").read_text())
    ranges = rep["summary"]["l2_ranges"]
    assert ranges["ibt_us"] == [20.0, 22.0]
    assert ranges["gap"] == [30.0, 33.0]
