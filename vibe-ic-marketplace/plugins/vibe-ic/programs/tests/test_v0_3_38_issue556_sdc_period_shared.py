"""ORGANIC #556 round-2 — _sdc_period_ps kept a parallel literal-only
regex, so a Tcl-variable-indirect SDC (``set clk_period 10.0`` +
``create_clock -period $clk_period`` — the real constraint.sdc shape on
the timing-critical benchmark class this lever exists for) returned None
and the ABC ``-D`` timing lever silently never engaged.

Fix: _sdc_period_ps delegates to the shared sdc_constraints module
(#554's Tcl-variable substitution), with phase2/stage2/constraints kept
in scope via the new extra_dirs parameter.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402
import sdc_constraints as sdc  # noqa: E402

# The reopen's exact shape (Tcl-variable-indirect constraint.sdc).
_TCL_VAR_SDC = """\
current_design core_top

set clk_name core_clock
set clk_port_name clk_i
set clk_period 10.0
set clk_io_pct 0.2

set clk_port [get_ports $clk_port_name]

create_clock -name $clk_name -period $clk_period $clk_port
"""


def test_sdc_period_ps_resolves_tcl_variable_sdc(tmp_path):
    """The reopen repro: Tcl-var SDC must yield 10000 ps, not None."""
    cdir = tmp_path / "input" / "constraints"
    cdir.mkdir(parents=True)
    (cdir / "constraint.sdc").write_text(_TCL_VAR_SDC)
    assert R._sdc_period_ps(tmp_path) == 10_000


def test_sdc_period_ps_literal_sdc_regression(tmp_path):
    """Round-1's literal shape keeps working."""
    cdir = tmp_path / "input" / "constraints"
    cdir.mkdir(parents=True)
    (cdir / "a.sdc").write_text(
        "create_clock -name clk -period 10.0 [get_ports clk]\n")
    assert R._sdc_period_ps(tmp_path) == 10_000


def test_sdc_period_ps_smallest_across_staged_and_phase2(tmp_path):
    """phase2/stage2/constraints stays in scope (extra_dirs) and the
    smallest period wins."""
    cdir = tmp_path / "input" / "constraints"
    cdir.mkdir(parents=True)
    (cdir / "a.sdc").write_text(
        "create_clock -name slow -period 20 [get_ports clk_a]\n")
    p2 = tmp_path / "phase2" / "stage2" / "constraints"
    p2.mkdir(parents=True)
    (p2 / "b.sdc").write_text(
        "create_clock -name fast -period 8.5 [get_ports clk_b]\n")
    assert R._sdc_period_ps(tmp_path) == 8_500


def test_sdc_period_ps_none_without_sdc(tmp_path):
    assert R._sdc_period_ps(tmp_path) is None


def test_sdc_constraints_main_cli_end_state(tmp_path):
    """Defect-artifact gate satisfier: stages the reopen's Tcl-variable
    constraint.sdc inline and asserts the shared module's CLI end state
    (rc==0) plus the runner-side period the -D lever consumes."""
    (tmp_path / "input" / "constraints").mkdir(parents=True)
    (tmp_path / "input" / "constraints" / "constraint.sdc").write_text(
        _TCL_VAR_SDC)
    rc = sdc.main([str(tmp_path)])
    assert rc == 0
    assert R._sdc_period_ps(tmp_path) == 10_000


def test_shared_module_default_scope_unchanged(tmp_path):
    """#554 regression: primary_clock without extra_dirs must NOT see the
    phase2-generated tree (staged ground truth only)."""
    p2 = tmp_path / "phase2" / "stage2" / "constraints"
    p2.mkdir(parents=True)
    (p2 / "gen.sdc").write_text(
        "create_clock -name g -period 5 [get_ports clk]\n")
    assert sdc.primary_clock(tmp_path) is None
    assert R._sdc_period_ps(tmp_path) == 5_000
