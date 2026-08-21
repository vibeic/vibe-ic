"""A generated deck identifies a configuration, not the directory it ran in.

WHY
===
A deck is the identity of a measurement. When the generator writes the absolute
path of the run directory, two runs of one configuration produce different decks
and the cross-run identity check drops the script instead of comparing it — so a
configuration silently stops being comparable to itself.

THE EXCLUSION IS ASSERTED, NOT ASSUMED
======================================
This rule PASSES on the repository partly because published run records are
disclosed rather than counted. That exclusion is load-bearing, so it is tested
from both sides: a record path must be disclosed and must not be a finding, and
the identical file OUTSIDE a record tree must go red. If the exclusion ever grows
to cover live scripts, `test_a_live_script_still_goes_red` fails.

chip-AGNOSTIC: path shapes only. `/foss/pdks/...` is an open process kit root.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "emitted_script_paths_are_project_relative.py"

_spec = importlib.util.spec_from_file_location("espapr", _TOOL)
espapr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(espapr)

_DECK = ('read_liberty /foss/pdks/sky130A/libs.ref/x/lib/x__tt_025C_1v80.lib\n'
         'read_verilog {netlist}\n'
         'read_spef {spef}\n')


def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


# ----------------------------------------------------------------- unit

def test_tool_root_is_not_a_finding():
    assert espapr.offending_paths(
        "read_liberty /foss/pdks/sky130A/libs.ref/a/lib/b__tt_025C_1v80.lib\n") == []


def test_system_root_is_not_a_finding():
    assert espapr.offending_paths("source /usr/share/openroad/x.tcl\n") == []


def test_run_directory_is_a_finding():
    hits = espapr.offending_paths("read_verilog /home/u/run/trials/z1/a.v\n")
    assert hits == [(1, "/home/u/run/trials/z1/a.v")]


def test_a_comment_is_not_a_finding():
    assert espapr.offending_paths("# was /home/u/run/trials/z1/a.v\n") == []


def test_tmp_is_a_run_directory():
    assert espapr.offending_paths("read_verilog /tmp/run42/a.v\n")


# ---------------------------------------------------------- red control

def test_a_live_script_still_goes_red(tmp_path):
    """THE NEGATIVE CONTROL. Reintroduce the defect in a LIVE script."""
    d = tmp_path / "phase3" / "diagnostics"
    d.mkdir(parents=True)
    (d / "power.tcl").write_text(
        _DECK.format(netlist="/home/u/run/trials/z23/phase3/pnr/top.v",
                     spef="/home/u/run/trials/z23/phase3/ext/top.spef"))
    rc, out = _run(tmp_path)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "run directory" in out


def test_the_relative_form_of_the_same_deck_passes(tmp_path):
    """BIDIRECTIONAL: the corrected deck must go green."""
    d = tmp_path / "phase3" / "diagnostics"
    d.mkdir(parents=True)
    (d / "power.tcl").write_text(
        _DECK.format(netlist="phase3/pnr/top.v", spef="phase3/ext/top.spef"))
    rc, out = _run(tmp_path)
    assert rc == 0, out


# ------------------------------------------- the exclusion, from both sides

def test_a_record_path_is_disclosed_not_a_finding(tmp_path):
    d = tmp_path / "ppa-e2e" / "diag"
    d.mkdir(parents=True)
    (d / "power.tcl").write_text(
        _DECK.format(netlist="/home/u/run/trials/t028/a.v",
                     spef="/home/u/run/trials/t028/a.spef"))
    live = tmp_path / "live.tcl"
    live.write_text("read_verilog phase3/pnr/top.v\n")
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "disclosed and not counted" in out
    assert "2 run-directory path(s) in published records" in out, out


def test_the_disclosure_count_is_never_silently_zero(tmp_path):
    """A PASS bought by an exclusion must state the exclusion's size."""
    d = tmp_path / "ppa-crosslayer" / "records" / "trials" / "z1"
    d.mkdir(parents=True)
    (d / "p.tcl").write_text("read_verilog /home/u/run/trials/z1/a.v\n")
    (tmp_path / "live.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "1 run-directory path(s) in published records" in out


# ------------------------------------------------------------- verdicts

def test_empty_population_is_not_checked(tmp_path):
    (tmp_path / "readme.md").write_text("nothing here\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_only_records_present_is_not_checked(tmp_path):
    """Records alone are not a population: 0 live scripts is NOT a pass."""
    d = tmp_path / "ppa-e2e" / "diag"
    d.mkdir(parents=True)
    (d / "p.tcl").write_text("read_verilog /home/u/run/a.v\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out


def test_a_symlinked_directory_is_not_followed(tmp_path):
    """A checkout carrying a link to a corpus elsewhere must not enlarge the
    population — the verdict is about the tree that was named."""
    outside = tmp_path / "outside"
    (outside / "diag").mkdir(parents=True)
    (outside / "diag" / "p.tcl").write_text("read_verilog /home/u/run/a.v\n")
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "live.tcl").write_text("read_verilog phase3/pnr/top.v\n")
    (tree / "linked").symlink_to(outside, target_is_directory=True)
    rc, out = _run(tree)
    assert rc == 0, out
    assert "examined 1 live" in out, out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out


def test_repository_itself_is_clean():
    rc, out = _run(_PROGRAMS.parents[3])
    assert rc == 0, out
