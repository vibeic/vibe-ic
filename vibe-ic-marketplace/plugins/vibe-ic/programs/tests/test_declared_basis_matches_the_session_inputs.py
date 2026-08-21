"""A report's claimed stage must be the stage its own session measured.

WHY
===
MEASURED: a power report headed post-layout whose session linked the pre-layout
netlist and loaded no parasitics published 0.306 mW against the post-route
session's 0.573 mW — 46.6 % understated — and reported the entire CLOCK GROUP as
0.000 mW where the real measurement puts 33.7 % of total power there. An absent
input read as a measured zero.

THE SESSION IS GROUND TRUTH
===========================
The reds below are built the way the defect was: the header keeps its
post-layout claim while `read_spef` is removed. Only the session changes, and
the verdict must follow the session, not the label.

ONE READER, NOT A SIXTH COPY
============================
`_sta_basis.declared_basis` is imported rather than re-implemented; that module
records five copies of the stamp reader disagreeing on 7 of a 24-stamp corpus.
`test_the_stamp_is_read_through_the_one_reader` pins the import.

chip-AGNOSTIC: flow-stage vocabulary. `/foss/pdks/sky130A` is an open kit root.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "declared_basis_matches_the_session_inputs.py"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location("dbmtsi", _TOOL)
dbmtsi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dbmtsi)

_POST = (
    'read_liberty /foss/pdks/sky130A/libs.ref/a/lib/a__tt_025C_1v80.lib\n'
    'read_verilog design_pnr.v\n'
    'link_design top\n'
    'read_spef design.spef\n'
    'read_sdc constraint.sdc\n'
    'report_power\n')
_PRE = _POST.replace('read_spef design.spef\n', '')
_RPT_STAMPED_POST = "# STA_BASIS: POST_ROUTE_SPEF\nTotal 5.73e-04\n"
_RPT_STAMPED_PRE = "# STA_BASIS: PRE_LAYOUT_ESTIMATE\nTotal 3.06e-04\n"


def _run(root):
    cp = subprocess.run([sys.executable, str(_TOOL), str(root)],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


def _pair(tmp_path, script, report, stem="power_postroute"):
    d = tmp_path / "diag"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.tcl").write_text(script)
    (d / f"{stem}.rpt").write_text(report)
    return d


# ------------------------------------------------------------------ unit

def test_session_with_parasitics_is_post_route():
    assert dbmtsi.session_basis(_POST) == "POST_ROUTE"


def test_session_without_parasitics_is_pre_layout():
    assert dbmtsi.session_basis(_PRE) == "PRE_LAYOUT"


def test_the_stamp_is_read_through_the_one_reader():
    import _sta_basis
    assert dbmtsi._sta_basis is _sta_basis
    claim, how = dbmtsi.claimed_basis(_RPT_STAMPED_POST, "x.rpt")
    assert claim == "POST_ROUTE" and how == "STA_BASIS stamp"


def test_an_unstamped_report_declares_nothing():
    claim, how = dbmtsi.claimed_basis("Total 1.0\n", "power.rpt")
    assert claim is None and how == "nothing"


# ------------------------------------------------------------ red control

def test_post_layout_claim_over_a_session_with_no_parasitics_goes_red(tmp_path):
    """THE NEGATIVE CONTROL — the defect exactly as measured."""
    _pair(tmp_path, _PRE, _RPT_STAMPED_POST)
    rc, out = _run(tmp_path)
    assert rc == 1, f"the defect did not go red:\n{out}"
    assert "claims POST_ROUTE" in out
    assert "measured PRE_LAYOUT" in out
    assert "cannot move when the layout moves" in out


def test_the_same_report_over_a_real_post_route_session_passes(tmp_path):
    """BIDIRECTIONAL: restore `read_spef` and the identical claim goes green."""
    _pair(tmp_path, _POST, _RPT_STAMPED_POST)
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_a_pre_layout_claim_over_a_post_route_session_goes_red(tmp_path):
    """The rule is symmetric — it is not a one-directional ban."""
    _pair(tmp_path, _POST, _RPT_STAMPED_PRE, stem="power_prelayout")
    rc, out = _run(tmp_path)
    assert rc == 1, out


def test_the_file_name_is_a_claim_when_there_is_no_stamp(tmp_path):
    _pair(tmp_path, _PRE, "Total 3.06e-04\n")
    rc, out = _run(tmp_path)
    assert rc == 1, out
    assert "file name" in out


# -------------------------------------------------------------- verdicts

def test_an_undeclared_report_is_disclosed_not_passed(tmp_path):
    _pair(tmp_path, _POST, "Total 5.73e-04\n", stem="power")
    rc, out = _run(tmp_path)
    assert "UNDECLARED" in out
    assert "1 declare no stage" in out


def test_a_session_that_publishes_no_number_is_not_a_pair(tmp_path):
    d = tmp_path / "diag"
    d.mkdir()
    (d / "setup.tcl").write_text("read_liberty a.lib\nlink_design top\n")
    (d / "setup.rpt").write_text("# STA_BASIS: POST_ROUTE_SPEF\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out


def test_empty_population_is_not_checked(tmp_path):
    (tmp_path / "readme.md").write_text("x\n")
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_absent_root_is_bad_invocation(tmp_path):
    rc, out = _run(tmp_path / "nope")
    assert rc == 3, out


def test_repository_itself_is_clean():
    rc, out = _run(_PROGRAMS.parents[3])
    assert rc == 0, out
