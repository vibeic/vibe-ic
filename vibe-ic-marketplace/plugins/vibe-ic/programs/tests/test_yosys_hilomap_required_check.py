"""Tests for yosys_hilomap_required_check.py.

Four branch-fixtures per the v0.69 spec:
  - clean
  - missing hilomap
  - hilomap-before-techmap (order violation)
  - hilomap-after-write_verilog (order violation)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "yosys_hilomap_required_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0


def test_missing_file_exits_2(tmp_path):
    code, _, err = _run(["--ys-file", str(tmp_path / "gone.ys")])
    assert code == 2


# ---- Fixture 1: clean ------------------------------------------------------
_CLEAN = """read_verilog -defer rtl/top.v
hierarchy -top top
proc
opt
techmap
opt
dfflibmap -liberty lib
abc -liberty lib
techmap
hilomap -hicell TIEHI Y -locell TIELO Y
clean
write_verilog out.v
"""


def test_clean_ordering_passes(tmp_path):
    f = tmp_path / "clean.ys"
    f.write_text(_CLEAN)
    code, out, _ = _run(["--ys-file", str(f)])
    assert code == 0
    assert "ok" in out.lower()


# ---- Fixture 2: missing hilomap -------------------------------------------
def test_missing_hilomap_fails(tmp_path):
    text = "\n".join(line for line in _CLEAN.splitlines() if "hilomap" not in line) + "\n"
    f = tmp_path / "nohilo.ys"
    f.write_text(text)
    code, _, err = _run(["--ys-file", str(f)])
    assert code == 1
    assert "MISSING hilomap" in err or "hilomap" in err.lower()


# ---- Fixture 3: hilomap before techmap ------------------------------------
_HILO_BEFORE_TECH = """read_verilog -defer rtl/top.v
hierarchy -top top
hilomap -hicell TIEHI Y -locell TIELO Y
techmap
abc -liberty lib
write_verilog out.v
"""


def test_hilomap_before_techmap_fails(tmp_path):
    f = tmp_path / "hilo_before_tech.ys"
    f.write_text(_HILO_BEFORE_TECH)
    code, _, err = _run(["--ys-file", str(f)])
    assert code == 1
    # Either the ordering error or the MISSING techmap-before-hilomap rule
    assert "hilomap_before_techmap" in err or "must follow techmap" in err


# ---- Fixture 4: hilomap AFTER write_verilog -------------------------------
_HILO_AFTER_WRITE = """read_verilog -defer rtl/top.v
hierarchy -top top
techmap
abc -liberty lib
write_verilog early_out.v
hilomap -hicell TIEHI Y -locell TIELO Y
"""


def test_hilomap_after_write_verilog_fails(tmp_path):
    f = tmp_path / "hilo_after_write.ys"
    f.write_text(_HILO_AFTER_WRITE)
    code, _, err = _run(["--ys-file", str(f)])
    assert code == 1
    assert "write_verilog_before_hilomap" in err or "BEFORE last `hilomap`" in err


# ---- v0.99 condition 3: abc between techmap and hilomap is forbidden ------
_ABC_BETWEEN = """read_verilog -defer rtl/top.v
hierarchy -top top
proc
opt
techmap
abc -liberty lib
hilomap -hicell TIEHI Y -locell TIELO Y
write_verilog out.v
"""


def test_abc_between_techmap_and_hilomap_fails(tmp_path):
    """BENCH-A run-4 finding: ABC after the last techmap, before hilomap, is
    silent at synth time but trips OpenROAD detailed_route DRT-0305."""
    f = tmp_path / "abc_between.ys"
    f.write_text(_ABC_BETWEEN)
    code, _, err = _run(["--ys-file", str(f)])
    assert code == 1
    assert "abc_between_techmap_and_hilomap" in err


# ---- comment-masked hilomap -----------------------------------------------
def test_commented_hilomap_is_not_counted(tmp_path):
    text = _CLEAN.replace("hilomap -hicell TIEHI Y -locell TIELO Y",
                          "# hilomap -hicell TIEHI Y -locell TIELO Y")
    f = tmp_path / "commented.ys"
    f.write_text(text)
    code, _, err = _run(["--ys-file", str(f)])
    assert code == 1
    assert "hilomap" in err.lower()


# NOTE: the former `test_v068_synth_ys_ordering_is_correct` integration test
# was removed — it was pinned to an external `$VIBE_IC_BENCHMARK_ROOT` build
# artifact absent from the repo (so it permanently skipped), and the synth.ys
# ordering contract it checked is already covered by the inline-fixture tests
# above (clean ordering, missing/mis-ordered/commented hilomap, abc placement).
