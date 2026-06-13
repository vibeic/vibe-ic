"""Tests for yosys_tiecell_recipe_order_check.py.

Covers the two v0.1.98 load-bearing tie-cell recipe ordering rules:
  RULE 1 — `setundef -zero` BEFORE `hilomap`
  RULE 2 — no `opt_clean` / `clean -purge` AFTER `hilomap`

PASS, FAIL (both rules), and edge cases (missing file, non-synth script,
synth script without hilomap, json output).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "yosys_tiecell_recipe_order_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _write(tmp_path, body, name="synth.ys"):
    p = tmp_path / name
    p.write_text(body)
    return str(p)


# ---- the correct v0.1.98 recipe (PASS) ------------------------------------
_GOOD = """read_verilog -defer rtl/top.v
hierarchy -top top
proc
opt
techmap
dfflibmap -liberty lib
abc -liberty lib
techmap
setundef -zero
hilomap -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO
splitnets
clean
write_verilog out.v
"""

# ---- RULE 1 broken: no setundef -zero (the v0.1.95 insufficient recipe) ----
_NO_SETUNDEF = """read_verilog rtl/top.v
synth -top top
dfflibmap -liberty lib
abc -liberty lib
techmap
hilomap -hicell TIEHI HI -locell TIELO LO
splitnets
clean
write_verilog out.v
"""

# ---- RULE 1 broken: setundef present but missing -zero ---------------------
_SETUNDEF_NO_ZERO = """synth -top top
abc -liberty lib
techmap
setundef -undriven
hilomap -hicell TIEHI HI -locell TIELO LO
clean
write_verilog out.v
"""

# ---- RULE 1 broken: setundef -zero AFTER hilomap ---------------------------
_SETUNDEF_AFTER = """synth -top top
abc -liberty lib
techmap
hilomap -hicell TIEHI HI -locell TIELO LO
setundef -zero
clean
write_verilog out.v
"""

# ---- RULE 2 broken: opt_clean AFTER hilomap (the HDLC DRT-0305 bug) --------
_OPT_CLEAN_AFTER = """synth -top top
abc -liberty lib
techmap
setundef -zero
hilomap -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO
opt_clean
write_verilog out.v
"""

# ---- RULE 2 broken: clean -purge AFTER hilomap -----------------------------
_CLEAN_PURGE_AFTER = """synth -top top
abc -liberty lib
techmap
setundef -zero
hilomap -hicell TIEHI HI -locell TIELO LO
clean -purge
write_verilog out.v
"""

# ---- both rules broken -----------------------------------------------------
_BOTH_BROKEN = """synth -top top
abc -liberty lib
techmap
hilomap -hicell TIEHI HI -locell TIELO LO
opt_clean
write_verilog out.v
"""

# ---- non-synth script (should SKIP, exit 0) --------------------------------
_NON_SYNTH = """read_verilog flat.v
flatten
write_verilog flat_out.v
"""

# ---- synth script with no hilomap (SKIP_NO_HILOMAP, exit 0) ----------------
_NO_HILOMAP = """synth -top top
dfflibmap -liberty lib
abc -liberty lib
clean
write_verilog out.v
"""


def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0
    assert "tie-cell" in out.lower()


# ===== PASS =================================================================
def test_good_recipe_passes(tmp_path):
    f = _write(tmp_path, _GOOD)
    code, out, err = _run(["--ys-file", f])
    assert code == 0, err
    assert "CLEAN" in out


# ===== FAIL — RULE 1 ========================================================
def test_missing_setundef_zero_fails(tmp_path):
    f = _write(tmp_path, _NO_SETUNDEF)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE1_setundef_zero_before_hilomap" in err


def test_setundef_without_zero_fails(tmp_path):
    f = _write(tmp_path, _SETUNDEF_NO_ZERO)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE1_setundef_zero_before_hilomap" in err
    assert "-zero" in err


def test_setundef_zero_after_hilomap_fails(tmp_path):
    f = _write(tmp_path, _SETUNDEF_AFTER)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE1_setundef_zero_before_hilomap" in err
    assert "AFTER" in err


# ===== FAIL — RULE 2 ========================================================
def test_opt_clean_after_hilomap_fails(tmp_path):
    f = _write(tmp_path, _OPT_CLEAN_AFTER)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE2_no_opt_clean_after_hilomap" in err


def test_clean_purge_after_hilomap_fails(tmp_path):
    f = _write(tmp_path, _CLEAN_PURGE_AFTER)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE2_no_opt_clean_after_hilomap" in err


def test_both_rules_broken_reports_both(tmp_path):
    f = _write(tmp_path, _BOTH_BROKEN)
    code, out, err = _run(["--ys-file", f])
    assert code == 1
    assert "RULE1_setundef_zero_before_hilomap" in err
    assert "RULE2_no_opt_clean_after_hilomap" in err


# ===== EDGE =================================================================
def test_missing_file_exits_2(tmp_path):
    code, _, err = _run(["--ys-file", str(tmp_path / "gone.ys")])
    assert code == 2
    assert "MISSING" in err


def test_non_synth_script_skips(tmp_path):
    f = _write(tmp_path, _NON_SYNTH)
    code, out, err = _run(["--ys-file", f])
    assert code == 0
    assert "SKIP" in out


def test_synth_without_hilomap_skips(tmp_path):
    # Presence-of-hilomap is enforced by yosys_hilomap_required_check.py;
    # this program should not double-flag it.
    f = _write(tmp_path, _NO_HILOMAP)
    code, out, err = _run(["--ys-file", f])
    assert code == 0
    assert "SKIP_NO_HILOMAP" in out


def test_plain_clean_after_hilomap_is_ok(tmp_path):
    # plain `clean` (no -purge) after hilomap is the recommended recipe, OK.
    f = _write(tmp_path, _GOOD)
    code, out, err = _run(["--ys-file", f])
    assert code == 0


def test_json_report_written(tmp_path):
    f = _write(tmp_path, _OPT_CLEAN_AFTER)
    jpath = tmp_path / "rep.json"
    code, out, err = _run(["--ys-file", f, "--json", str(jpath)])
    assert code == 1
    data = json.loads(jpath.read_text())
    assert data["verdict"] == "VIOLATION"
    assert any(v["rule"] == "RULE2_no_opt_clean_after_hilomap"
               for v in data["violations"])


def test_comments_ignored(tmp_path):
    # An opt_clean mentioned only in a comment must NOT trigger RULE 2.
    body = """synth -top top
abc -liberty lib
techmap
setundef -zero
hilomap -hicell TIEHI HI -locell TIELO LO
# do NOT opt_clean here
clean
write_verilog out.v
"""
    f = _write(tmp_path, body)
    code, out, err = _run(["--ys-file", f])
    assert code == 0, err
    assert "CLEAN" in out
