"""slot_pad_budget: a constant-expression port width is RESOLVED, and a
[CANNOT CHECK] is booked NOT_MEASURED, never NOT_APPLICABLE.

MEASURED on subservient x gf180mcuD (subic_ic_20260928, a DIE whose top is the
core), `reports/orchestrator/phase2_one_shot.json`:

    slot_pad_budget  NOT_APPLICABLE  exit_code 2
    detail/declared_by: "[CANNOT CHECK] slot_pad_budget_check: UNDECIDED | the
        width of 2 port(s) is parameterised and neither the command line nor
        the design's own plugin_output/declaration.json supplies a value:
        o_sram_addr, o_sram_waddr"

Two defects, one row:

  (1) THE GATE. The ports are `output wire [$clog2(memsize)-1:0] ...` and the
      top's own header says `parameter integer memsize = 1024` -- the gate's
      report even carried `params_from_top_module_defaults: {memsize: 1024}`.
      Every operand was known; only `NAME` and `NAME+-N` were ever evaluated,
      so the arithmetic was refused and the question never asked. The fix
      evaluates the bound through the tree's ONE width evaluator
      (`register_bus_driver_gen._int_expr`, the same one `_port_width` uses).
      An identifier nobody declared still refuses: UNDECIDED stays reachable.

  (2) THE RUNNER. `step_slot_pad_budget` booked EVERY rc 2 as NOT_APPLICABLE,
      and used the CANNOT-CHECK line itself as `declared_by`. rc 2 carries two
      sentences: a design-declared route with no slot (NOT_APPLICABLE /
      DESIGN_DECLARED_NA, which names its declaration) and "I could not look"
      (UNDECIDED). The second is NOT_MEASURED -- booking it N/A is an automatic
      downgrade. The gate's own report now decides which sentence was spoken,
      and a missing report is NOT_MEASURED too.

Fixtures are synthetic Verilog in the measured SHAPE; nothing here names a
design in logic.
"""
import json
import sys
import tempfile
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import slot_pad_budget_check as S                                  # noqa: E402
import test_r0915101_a_die_budgets_against_its_own_pad_ring as D   # noqa: E402
import test_slot_pad_budget_check as T                             # noqa: E402

_TOP = D._TOP

#: The measured shape: the address width is `$clog2` of a parameter whose
#: value the top's OWN header states as an integer literal.
_RTL_CLOG2_OF_A_LITERAL_DEFAULT = (
    "module %s #(\n"
    "    parameter integer memsize = 1024\n"
    ") (input wire i_clk, input wire i_rst,\n"
    "  output wire [$clog2(memsize)-1:0] o_sensor_addr,\n"
    "  output wire [7:0] o_sensor_data,\n"
    "  input wire [7:0] i_sensor_data, output wire o_sensor_we,\n"
    "  output wire o_sensor_cyc, output wire o_gpio);\n"
    "endmodule\n") % _TOP

#: The header default is itself an EXPRESSION, which the defaults reader
#: deliberately does not evaluate (`test_r34 ::
#: test_an_expression_default_stays_unresolved`). The only place the value is
#: stated as a number is the design's own declaration.
_RTL_CLOG2_OF_AN_EXPRESSION_DEFAULT = (
    "module %s #(\n"
    "    parameter integer WORDS = 256,\n"
    "    parameter integer memsize = WORDS * 4\n"
    ") (input wire i_clk, input wire i_rst,\n"
    "  output wire [$clog2(memsize)-1:0] o_sensor_addr,\n"
    "  output wire [7:0] o_sensor_data,\n"
    "  input wire [7:0] i_sensor_data, output wire o_sensor_we,\n"
    "  output wire o_sensor_cyc, output wire o_gpio);\n"
    "endmodule\n") % _TOP

_GATE_REPORT = "reports/phase2/gates/slot_pad_budget.json"




def _declare(project: Path, values: dict) -> None:
    out = project / "plugin_output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "declaration.json").write_text(json.dumps(values))


def _width(ports, name):
    return next(p["width"] for p in ports if p["name"] == name)


# --------------------------------------------------------------------------- #
# (b) the gate resolves a `$clog2(PARAM)` width from declared values, and decides
# --------------------------------------------------------------------------- #
def test_a_clog2_bound_over_the_tops_own_literal_default_is_ten_bits():
    """RED on main: None (unresolved) although `memsize` = 1024 was read."""
    d = S.top_parameter_defaults(_RTL_CLOG2_OF_A_LITERAL_DEFAULT, _TOP)
    assert d == {"memsize": 1024}
    ports = S.parse_top_ports(_RTL_CLOG2_OF_A_LITERAL_DEFAULT, _TOP, d)
    assert _width(ports, "o_sensor_addr") == 10


def test_a_DIE_with_a_clog2_width_decides_exactly_like_its_literal_twin():
    """The measured DIE shape, end to end through the gate's `main`.

    RED on main: UNDECIDED / rc 2, `unresolved_width_ports: [o_sensor_addr]`.
    GREEN: the same verdict and the same arithmetic as the RTL that writes the
    width as `[9:0]` -- `$clog2(1024)` is 10, not an estimate of it."""
    rc, rep = D._run(D._project(rtl=_RTL_CLOG2_OF_A_LITERAL_DEFAULT))
    rc_lit, rep_lit = D._run(D._project())
    assert rep is not None and rep_lit is not None
    assert "unresolved_width_ports" not in rep, rep.get("reason")
    assert rep["verdict"] == rep_lit["verdict"] == "FITS", rep.get("reason")
    assert rc == rc_lit == 0
    assert rep["own_ring_arithmetic"]["signal_pads_owed"] == 29
    assert (rep["own_ring_arithmetic"]
            == rep_lit["own_ring_arithmetic"])


def test_a_value_declared_only_in_the_designs_declaration_resolves_clog2():
    """The declaration is the only numeric source: the RTL default is an
    expression the defaults reader does not evaluate. `declaration.json`
    `memsize: 1024` -> 10 bits -> the gate decides (rc 0, not rc 2)."""
    p = D._project(rtl=_RTL_CLOG2_OF_AN_EXPRESSION_DEFAULT)
    _declare(p, {"memsize": 1024})
    rc, rep = D._run(p)
    assert rep is not None
    assert "unresolved_width_ports" not in rep, rep.get("reason")
    assert rep["verdict"] == "FITS", rep.get("reason")
    assert rc == 0
    assert rep["own_ring_arithmetic"]["signal_pads_owed"] == 29


def test_a_nested_core_parameter_is_the_declared_elaboration_value():
    """The declaration schema used by a die puts the value under
    core_parameters. The unrelated memsize_bytes field cannot substitute for
    a named RTL parameter."""
    p = D._project(rtl=_RTL_CLOG2_OF_AN_EXPRESSION_DEFAULT)
    _declare(p, {"memsize_bytes": 1024,
                 "core_parameters": {"memsize": 1024}})
    rc, rep = D._run(p)
    assert S._design_declared_params(str(p))["memsize"] == 1024
    assert rc == 0 and rep["verdict"] == "FITS", rep.get("reason")
    assert rep["own_ring_arithmetic"]["signal_pads_owed"] == 29


def test_a_slot_budget_counts_the_resolved_clog2_width():
    """The operator-slot branch reads the same port parse: the resolved width
    reaches `declared_signal_bits` as 10 + 10 + 8 + 8 + 3, not a smaller sum."""
    d = Path(tempfile.mkdtemp(prefix="u12slot_"))
    s = d / "input" / "submission_template" / "slots"
    s.mkdir(parents=True)
    (s / "slot_1x1.json").write_text(json.dumps(T._slot_ingested()))
    r = d / "phase2" / "stage1" / "rtl"
    r.mkdir(parents=True)
    (r / "chip_top.v").write_text(
        "module chip_top #(parameter integer memsize = 1024) (\n"
        "  input wire clk, input wire rst_n,\n"
        "  output wire [$clog2(memsize)-1:0] o_raddr,\n"
        "  output wire [$clog2(memsize)-1:0] o_waddr,\n"
        "  output wire [7:0] o_wdata, input wire [7:0] i_rdata,\n"
        "  output wire o_we, output wire o_ren, output wire o_cyc);\n"
        "endmodule\n")
    rc = S.main([str(d), "--json", _GATE_REPORT])
    rep = json.loads((d / _GATE_REPORT).read_text())
    assert rep["verdict"] != "UNDECIDED", rep.get("reason")
    assert rep["declared_signal_bits"] == 10 + 10 + 8 + 8 + 3
    assert rc in (0, 1)


# --------------------------------------------------------------------------- #
# (c) control: an UNDECLARED parameter still cannot be checked
# --------------------------------------------------------------------------- #
def test_an_undeclared_parameter_still_answers_CANNOT_CHECK():
    """Same RTL as above with NO declaration: `memsize` is an expression the
    gate does not evaluate and nothing else states it. The evaluator must not
    invent it -- UNDECIDED, rc 2, the port named."""
    rc, rep = D._run(D._project(rtl=_RTL_CLOG2_OF_AN_EXPRESSION_DEFAULT))
    assert rc == 2
    assert rep["verdict"] == "UNDECIDED"
    assert rep["unresolved_width_ports"] == ["o_sensor_addr"]


# --------------------------------------------------------------------------- #
# (a) the runner books a CANNOT CHECK as NOT_MEASURED, never NOT_APPLICABLE
# --------------------------------------------------------------------------- #
