"""Regression coverage for module-scope SystemVerilog ``logic`` state.

The reset-less power-up autofix's case (c) covers internal sequential state,
including state whose value reaches an output through combinational logic.
SystemVerilog ``logic`` is the variable counterpart of Verilog ``reg`` and
must receive the same conservative treatment without widening any of the
existing scope, net, memory, reset, or existing-initializer boundaries.
"""
from __future__ import annotations

import sys
import shutil
import subprocess
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import rtl_hygiene_lint as hygiene  # noqa: E402

IVERILOG = shutil.which("iverilog")


def _fix(tmp_path: Path, source: str):
    rtl = tmp_path / "dut.sv"
    rtl.write_text(source)
    result = hygiene.autofix_uninit_registered_output(rtl)
    return rtl, result


RESETLESS_LOGIC = """\
module dut(input logic clk, input logic d, output logic y);
  logic q;
  always_ff @(posedge clk) q <= d;
  always_comb y = q;
endmodule
"""


def test_resetless_module_scope_logic_state_is_initialized(tmp_path):
    rtl, result = _fix(tmp_path, RESETLESS_LOGIC)

    assert result == (1, ["q"])
    assert "    q = 0;" in rtl.read_text()
    if IVERILOG:
        compiled = subprocess.run(
            [IVERILOG, "-g2012", "-t", "null", str(rtl)],
            capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stderr


def test_logic_state_fix_is_idempotent(tmp_path):
    rtl, first = _fix(tmp_path, RESETLESS_LOGIC)
    fixed = rtl.read_text()

    second = hygiene.autofix_uninit_registered_output(rtl)

    assert first == (1, ["q"])
    assert second == (0, [])
    assert rtl.read_text() == fixed


def test_many_logic_states_remain_idempotent_past_old_scan_window(tmp_path):
    names = [f"q{i}" for i in range(24)]
    declaration = "logic " + ", ".join(names) + ";"
    updates = "\n".join(f"    {name} <= d;" for name in names)
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
  {declaration}
  always_ff @(posedge clk) begin
{updates}
  end
  always_comb y = q0;
endmodule
"""
    rtl, first = _fix(tmp_path, source)
    fixed = rtl.read_text()

    second = hygiene.autofix_uninit_registered_output(rtl)

    assert first == (len(names), names)
    assert second == (0, [])
    assert rtl.read_text() == fixed


@pytest.mark.parametrize(
    "declaration, setup",
    [
        ("logic q = 1'b0;", ""),
        ("logic q;", "initial q = 1'b0;"),
    ],
    ids=["declaration-initializer", "initial-block"],
)
def test_already_initialized_logic_state_is_not_modified(
        tmp_path, declaration, setup):
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
  {declaration}
  {setup}
  always_ff @(posedge clk) q <= d;
  always_comb y = q;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source


def test_existing_initial_assignment_beyond_old_scan_window_is_preserved(
        tmp_path):
    padding = "x" * 240
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
  logic q;
  initial begin
    // {padding}
    q = 1'b0;
  end
  always_ff @(posedge clk) q <= d;
  always_comb y = q;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source


def test_initial_relational_comparison_does_not_fake_initialization(tmp_path):
    source = """\
module dut(input logic clk, input logic d, output logic q);
  logic observed;
  initial begin
    observed = q <= d;
    if (q <= d)
      observed = 1'b1;
  end
  always_ff @(posedge clk) q <= d;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert hygiene._initially_assigned_signals(source) == {"observed"}
    assert result == (1, ["q"])
    assert "    q = 0;" in rtl.read_text()


@pytest.mark.parametrize(
    "initial_statement",
    [
        """\
initial if (d) begin
  q = 1'b0;
  r = 1'b0;
end else begin
  q = 1'b0;
  r = 1'b0;
end
""",
        """\
initial case (d)
  1'b0: begin q = 1'b0; r = 1'b0; end
  default: begin q = 1'b0; r = 1'b0; end
endcase
""",
        """\
initial fork
  q = 1'b0;
  r = 1'b0;
join
""",
    ],
    ids=["if-else", "case", "fork-join"],
)
def test_compound_initial_without_outer_begin_is_fully_scanned(
        tmp_path, initial_statement):
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
  logic q, r;
  {initial_statement}
  always_ff @(posedge clk) begin
    q <= d;
    r <= q;
  end
  always_comb y = q ^ r;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert hygiene._initially_assigned_signals(source) == {"q", "r"}
    assert result == (0, [])
    assert rtl.read_text() == source


def test_far_existing_initial_on_registered_output_is_preserved(tmp_path):
    padding = "x" * 240
    source = f"""\
module dut(input logic clk, input logic d, output logic q);
  initial begin
    // {padding}
    q = 1'b0;
  end
  always_ff @(posedge clk) q <= d;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source


def test_many_registered_outputs_remain_idempotent(tmp_path):
    names = [f"q{i}" for i in range(24)]
    declarations = "\n".join(f"  output logic {name};" for name in names)
    updates = "\n".join(f"    {name} <= d;" for name in names)
    source = f"""\
module dut(clk, d, {', '.join(names)});
  input logic clk;
  input logic d;
{declarations}
  always_ff @(posedge clk) begin
{updates}
  end
endmodule
"""
    rtl, first = _fix(tmp_path, source)
    fixed = rtl.read_text()

    second = hygiene.autofix_uninit_registered_output(rtl)

    assert first == (len(names), names)
    assert second == (0, [])
    assert rtl.read_text() == fixed


def test_wire_logic_net_is_not_initialized(tmp_path):
    source = """\
module dut(input logic d, output logic y);
  wire logic decoy, q;
  assign q = d;
  always_comb y = (q <= d);
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source
    if IVERILOG:
        compiled = subprocess.run(
            [IVERILOG, "-g2012", "-t", "null", str(rtl)],
            capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stderr


def test_logic_memory_is_not_scalar_initialized(tmp_path):
    source = """\
module dut(input logic clk, input logic [1:0] addr,
           input logic [7:0] d, output logic [7:0] y);
  logic [7:0] mem [0:3];
  always_ff @(posedge clk) mem[addr] <= d;
  always_comb y = mem[addr];
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source


def test_generate_scoped_logic_is_not_initialized_at_module_scope(tmp_path):
    source = """\
module dut(input logic clk, input logic d, output logic y);
  generate
    if (1) begin : g_state
      logic q;
      always_ff @(posedge clk) q <= d;
      always_comb y = q;
    end
  endgenerate
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source


@pytest.mark.parametrize(
    "generate_item",
    [
        """\
  if (1) begin : g_state
    logic q;
    always_ff @(posedge clk) q <= d;
    always_comb y = q;
  end
""",
        """\
  for (genvar i = 0; i < 1; i = i + 1) begin : g_state
    logic q;
    always_ff @(posedge clk) q <= d;
    always_comb y = q;
  end
""",
    ],
    ids=["implicit-if", "implicit-for-genvar"],
)
def test_implicit_generate_scoped_logic_is_not_initialized(
        tmp_path, generate_item):
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
{generate_item}endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source


def test_procedural_block_local_logic_is_not_initialized(tmp_path):
    source = """\
module dut(input logic clk, input logic d);
  always_ff @(posedge clk) begin : p_state
    logic q;
    q <= d;
  end
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source


def test_task_local_logic_is_not_initialized(tmp_path):
    helper = """\
  task update(input logic value);
    logic q;
    q <= value;
  endtask
"""
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
{helper}  always_ff @(posedge clk) y <= d;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (1, ["y"])
    assert "    q = 0;" not in rtl.read_text()
    if IVERILOG:
        compiled = subprocess.run(
            [IVERILOG, "-g2012", "-t", "null", str(rtl)],
            capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stderr


def test_function_local_logic_is_absent_from_module_state(tmp_path):
    helper = """\
  function automatic logic update(input logic value);
    logic q;
    q = value;
    update = q;
  endfunction
"""
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
{helper}  always_ff @(posedge clk) y <= d;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (1, ["y"])
    assert "q" not in hygiene._module_scope_scalar_state(source)
    assert "    q = 0;" not in rtl.read_text()
    if IVERILOG:
        compiled = subprocess.run(
            [IVERILOG, "-g2012", "-t", "null", str(rtl)],
            capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stderr


def test_partial_vector_initialization_does_not_credit_whole_signal(tmp_path):
    source = """\
module dut(input logic clk, input logic d, output logic y);
  logic [3:0] q;
  initial q[0] = 1'b0;
  always_ff @(posedge clk) q <= {4{d}};
  always_comb y = ^q;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (1, ["q"])
    assert "    q = 0;" in rtl.read_text()
    if IVERILOG:
        compiled = subprocess.run(
            [IVERILOG, "-g2012", "-t", "null", str(rtl)],
            capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stderr


def test_packed_struct_fields_are_not_initialized_as_module_variables(tmp_path):
    source = """\
module dut(input logic clk, input logic d, output logic y);
  struct packed {
    logic a;
    logic b;
  } q;
  always_ff @(posedge clk) q.a <= d;
  always_comb y = q.a;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source
    if IVERILOG:
        compiled = subprocess.run(
            [IVERILOG, "-g2012", "-t", "null", str(rtl)],
            capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stderr


@pytest.mark.parametrize("kind", ["reg", "logic"])
def test_attributed_module_state_remains_eligible(tmp_path, kind):
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
  (* keep = "true" *) {kind} q;
  always_ff @(posedge clk) q <= d;
  always_comb y = q;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (1, ["q"])
    assert "    q = 0;" in rtl.read_text()


@pytest.mark.parametrize("kind", ["reg", "logic"])
def test_explicit_static_module_state_remains_eligible(tmp_path, kind):
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
  static {kind} q;
  always_ff @(posedge clk) q <= d;
  always_comb y = q;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (1, ["q"])
    assert "    q = 0;" in rtl.read_text()


@pytest.mark.parametrize(
    "prior_scope",
    [
        """\
  task noop;
  endtask
""",
        """\
  generate
    if (0) begin : g_unused
      wire unused;
    end
  endgenerate
""",
    ],
    ids=["after-task", "after-generate"],
)
def test_module_state_after_masked_scope_remains_eligible(
        tmp_path, prior_scope):
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
{prior_scope}  logic q;
  always_ff @(posedge clk) q <= d;
  always_comb y = q;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (1, ["q"])
    assert "    q = 0;" in rtl.read_text()
    if IVERILOG:
        compiled = subprocess.run(
            [IVERILOG, "-g2012", "-t", "null", str(rtl)],
            capture_output=True, text=True)
        assert compiled.returncode == 0, compiled.stderr


@pytest.mark.parametrize("kind", ["reg", "logic"])
def test_module_state_after_completed_always_block_remains_eligible(
        tmp_path, kind):
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
  {kind} state0;
  always @(posedge clk) begin : p_state0
    state0 <= d;
  end : p_state0
  {kind} state1;
  always @(posedge clk) state1 <= state0;
  always @(*) y = state1;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (2, ["state0", "state1"])
    assert "    state0 = 0;" in rtl.read_text()
    assert "    state1 = 0;" in rtl.read_text()


@pytest.mark.parametrize("kind", ["reg", "logic"])
def test_module_state_after_completed_initial_block_remains_eligible(
        tmp_path, kind):
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
  logic observed;
  initial begin : p_observe
    observed = 1'b0;
  end : p_observe
  {kind} q;
  always @(posedge clk) q <= d;
  always @(*) y = q;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (1, ["q"])
    assert "    q = 0;" in rtl.read_text()


@pytest.mark.parametrize("kind", ["reg", "logic"])
@pytest.mark.parametrize(
    "empty_item",
    ["always @(*) begin end", "initial begin end"],
    ids=["empty-always", "empty-initial"],
)
def test_module_state_after_empty_completed_block_remains_eligible(
        tmp_path, kind, empty_item):
    source = f"""\
module dut(input logic clk, input logic d, output logic y);
  {empty_item}
  {kind} q;
  always @(posedge clk) q <= d;
  always @(*) y = q;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (1, ["q"])
    assert "    q = 0;" in rtl.read_text()


def test_relational_logic_operand_is_not_mistaken_for_nba_state(tmp_path):
    source = """\
module dut(input logic d, output logic y);
  logic q;
  always_comb begin
    if (q <= d) y = 1'b1;
    else y = 1'b0;
  end
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source


def test_reset_covered_logic_state_is_not_initialized(tmp_path):
    source = """\
module dut(input logic clk, input logic presetn, input logic d,
           output logic y);
  logic q;
  always_ff @(posedge clk or negedge presetn) begin
    if (!presetn) q <= 1'b0;
    else q <= d;
  end
  always_comb y = q;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (0, [])
    assert rtl.read_text() == source


def test_legacy_reg_state_is_still_initialized(tmp_path):
    source = """\
module dut(input clk, input d, output reg y);
  reg q;
  always @(posedge clk) q <= d;
  always @(*) y = q;
endmodule
"""
    rtl, result = _fix(tmp_path, source)

    assert result == (1, ["q"])
    assert "    q = 0;" in rtl.read_text()
