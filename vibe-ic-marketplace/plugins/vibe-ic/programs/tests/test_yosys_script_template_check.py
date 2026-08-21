"""Tests for yosys_script_template_check.py.

Audits a Yosys .ys script for -sv / -flatten / hilomap. Fallback auditor when
the plugin doesn't ship a canonical synth template (LLM emits one per run).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "yosys_script_template_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0


def test_missing_file_exits_2(tmp_path):
    code, _, err = _run(["--ys-file", str(tmp_path / "nope.ys")])
    assert code == 2
    assert "not found" in err.lower()


# ---- good template ---------------------------------------------------------
_GOOD_YS = """# canonical synth template
read_verilog -sv -defer rtl/top.sv
hierarchy -top top
synth -flatten
dfflibmap -liberty pdk/cells.lib
abc -liberty pdk/cells.lib
hilomap -hicell TIEHI Y -locell TIELO Y
clean
write_verilog netlist.v
"""


def test_good_template_passes(tmp_path):
    f = tmp_path / "good.ys"
    f.write_text(_GOOD_YS)
    code, out, _ = _run(["--ys-file", str(f)])
    assert code == 0
    assert "ok" in out.lower()


# ---- missing each token independently -------------------------------------
def test_missing_sv_fails(tmp_path):
    f = tmp_path / "nosv.ys"
    f.write_text(_GOOD_YS.replace("-sv ", ""))
    code, _, err = _run(["--ys-file", str(f)])
    assert code == 1
    assert "-sv" in err


def test_missing_flatten_fails(tmp_path):
    f = tmp_path / "noflat.ys"
    text = _GOOD_YS.replace("synth -flatten", "synth")
    f.write_text(text)
    code, _, err = _run(["--ys-file", str(f)])
    assert code == 1
    assert "-flatten" in err or "flatten" in err


def test_missing_hilomap_fails(tmp_path):
    f = tmp_path / "nohilo.ys"
    text = "\n".join(
        line for line in _GOOD_YS.splitlines() if "hilomap" not in line
    ) + "\n"
    f.write_text(text)
    code, _, err = _run(["--ys-file", str(f)])
    assert code == 1
    assert "hilomap" in err


# ---- --allow-no-sv waiver -------------------------------------------------
def test_allow_no_sv_waives_only_sv_requirement(tmp_path):
    """Plain Verilog-2001 case: -sv not needed but flatten + hilomap still are."""
    text = _GOOD_YS.replace("-sv ", "")
    f = tmp_path / "v2001.ys"
    f.write_text(text)
    code, _, _ = _run(["--ys-file", str(f), "--allow-no-sv"])
    assert code == 0


def test_allow_no_sv_does_not_waive_hilomap(tmp_path):
    text = _GOOD_YS.replace("-sv ", "")
    text = "\n".join(
        line for line in text.splitlines() if "hilomap" not in line
    ) + "\n"
    f = tmp_path / "v2001_nohilo.ys"
    f.write_text(text)
    code, _, err = _run(["--ys-file", str(f), "--allow-no-sv"])
    assert code == 1
    assert "hilomap" in err


# ---- --simulation-only waives hilomap only --------------------------------
def test_simulation_only_waives_hilomap(tmp_path):
    text = "\n".join(
        line for line in _GOOD_YS.splitlines() if "hilomap" not in line
    ) + "\n"
    f = tmp_path / "sim.ys"
    f.write_text(text)
    code, _, _ = _run(["--ys-file", str(f), "--simulation-only"])
    assert code == 0


# ---- comments don't mask tokens -------------------------------------------
def test_token_inside_comment_is_ignored(tmp_path):
    # hilomap appears only in a comment; the .ys therefore fails.
    text = _GOOD_YS.replace("hilomap -hicell", "# hilomap -hicell")
    f = tmp_path / "commented.ys"
    f.write_text(text)
    code, _, err = _run(["--ys-file", str(f)])
    assert code == 1
    assert "hilomap" in err


# NOTE: the former `test_v068_synth_ys_passes_with_allow_no_sv` integration
# test was removed — it pointed at a hard-coded external path
# (~/AI_IC_design/1st_benchmark_example/.../synth.ys) absent from the repo (so
# it permanently skipped), and the --allow-no-sv / hilomap contract it checked
# is already covered by the inline-fixture tests above
# (test_allow_no_sv_*, test_good_template_passes, test_missing_*).
