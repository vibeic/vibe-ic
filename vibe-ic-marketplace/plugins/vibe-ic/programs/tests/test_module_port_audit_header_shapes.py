"""SystemVerilog header shapes `module_port_audit` used to drop ports from.

Found by sweeping the gate over the 107 tracked rtl directories while triaging
#559. Three real designs reported hundreds of "port does not exist in module"
errors against code that is upstream-clean — opentitan_aes alone reported 920 —
and every one of those was the parser losing the port, not the design losing it.

A dropped port is invisible in exactly the wrong direction. The gate does not
say "I could not parse this header"; it says the instantiation names a port the
module does not have, which reads as a finding about the design.

Three causes, each with a fixture below. A fourth I believed in and removed:
comments inside the port list DO break `parse_port_list_ansi`, but no production
caller reaches it with comments present — `scan_rtl_directory` and
`scan_rtl_files` strip them from the whole file first. Ablation put that fix at
exactly zero effect (ibex 1 -> 1, opentitan 241 -> 241); the "ibex lost 8 ports
to comments" story came from my probe calling the function on raw text. The
coupling is pinned by a test below instead of duplicated in the code.

  module-level import   `module aes_core \\n import aes_pkg::*; \\n #( ... )`
                        The header was taken as text up to the first `;`, and
                        that semicolon is the import's. Header = 2 lines, zero
                        ports, so every instantiated port "did not exist".
  package-qualified type
                        `input ibex_pkg::pc_sel_e pc_mux_i` — the type
                        alternation allowed only wire/reg/logic/signed/unsigned.
  unpacked dimension    `input logic [33:0] imd_val_d_ex_i[2]` — the anchor
                        required the name to end the fragment.

Measured over the corpus after the fix, with no project's count rising:
ibex 43 -> 1 error, opentitan_aes 920 -> 241. Attribution by ablation, one fix
removed at a time:

    removed              ibex   opentitan
    (none)                  1         241
    unpacked dimension     13         245
    package-qualified      35         336
    module-level import     1         911

241 and 368 (subservient) remained, and the guess recorded here — that they were
parser limits rather than design defects — held. Two more shapes closed them,
with tests at the bottom of this file:

    module-line import   `module aes_cipher_control_fsm import aes_pkg::*;`
                         The clause above was recognised only when it OPENED a
                         line, so this placement truncated the header to the
                         module line: zero ports, and every connection to it
                         reported `Available ports: []`. 81 corpus files.
    multi-dim packed     `input logic [3:0][3:0][7:0] data_i` — the packed
                         group took ONE bracket, so aes_sub_bytes lost its 5
                         multi-dimensional ports and kept its 7 scalar ones.

RE-MEASURED end to end, both arms over the SAME population — 101 directories
matching `benchmark-data/**/phase2/stage1/rtl/*.{v,sv}`, the pre-fix arm taken
from `git show HEAD:` rather than by editing the tree:

    after the whitespace fix alone      rc=1 on 8 of 101
    after these two                     rc=1 on 0 of 101

The earlier 7/5 figures in `test_issue559_port_type_without_space.py` are over a
DIFFERENT 107-directory population and are not comparable to these; each chain
is only valid against its own denominator.

Zero is also what a parser that accepted everything would report, so the number
is not the evidence. Injecting a real defect into a copy of the corpus — the
declaration of the now-visible `aes_sub_bytes.data_i` renamed — takes the gate
back to rc=1 on exactly that port.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "module_port_audit", _PROGRAMS / "module_port_audit.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["module_port_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()


def _ports(src: str):
    return set(M.parse_port_list_ansi(src, "fixture.sv", 1))


PLAIN = "module m (\n  input logic clk_i,\n  input logic rst_ni\n);"
LEADING_COMMENT = ("module m (\n  // Clock and Reset\n"
                   "  input logic clk_i,\n  input logic rst_ni\n);")
TRAILING_COMMENT = ("module m (\n  input logic clk_i, // the clock\n"
                    "  input logic rst_ni\n);")
BLOCK_COMMENT = ("module m (\n  /* clocks */ input logic clk_i,\n"
                 "  input logic rst_ni\n);")
UNPACKED = "module m (\n  input logic [33:0] v[2],\n  input logic clk_i\n);"
PKG_TYPE = "module m (\n  input pkg::sel_e s,\n  input logic clk_i\n);"


def test_plain_ports():
    """The control. Without it, a parser returning everything scores full marks."""
    assert _ports(PLAIN) == {"clk_i", "rst_ni"}


@pytest.mark.parametrize("src", [LEADING_COMMENT, TRAILING_COMMENT, BLOCK_COMMENT])
def test_comments_are_the_callers_job_and_the_callers_do_it(src):
    """Pins the coupling instead of duplicating the strip.

    `parse_port_list_ansi` genuinely drops ports when a comment survives into a
    comma-split fragment. It is never handed one: both production entry points
    run `strip_comments` over the file first. Asserting BOTH halves is the
    point — if a future caller stops stripping, the first assertion documents
    what it will silently lose.
    """
    assert _ports(src) != {"clk_i", "rst_ni"}, (
        "raw comments no longer break the parser; if that is deliberate, this "
        "test and the note in the module docstring are both stale")
    assert _ports(M.strip_comments(src)) == {"clk_i", "rst_ni"}


def test_unpacked_dimension_after_the_name():
    assert _ports(UNPACKED) == {"v", "clk_i"}


def test_package_qualified_port_type():
    assert _ports(PKG_TYPE) == {"s", "clk_i"}


def test_module_level_import_does_not_end_the_header(tmp_path):
    """The 920-error case, end to end through the file scanner.

    Asserted through the whole-file path rather than `parse_port_list_ansi`,
    because the defect was in locating the header, not in parsing it.
    """
    src = (
        "module aes_core\n"
        "  import aes_pkg::*;\n"
        "  import aes_reg_pkg::*;\n"
        "#(\n"
        "  parameter bit AES192Enable = 1\n"
        ") (\n"
        "  input  logic clk_i,\n"
        "  input  logic rst_ni,\n"
        "  output logic idle_o\n"
        ");\n"
        "endmodule\n"
    )
    f = tmp_path / "aes_core.sv"
    f.write_text(src, encoding="utf-8")
    mods = M.parse_modules(M.strip_comments(f.read_text(encoding="utf-8")), str(f))
    assert mods, "no module parsed at all"
    core = next((m for m in mods if m.name == "aes_core"), None)
    assert core is not None, [m.name for m in mods]
    names = set(core.ports)
    assert {"clk_i", "rst_ni", "idle_o"} <= names, (
        f"module-level import truncated the header; parsed ports: {sorted(names)}")


def test_a_genuinely_absent_port_is_still_reported(tmp_path):
    """The accept/reject boundary.

    Every fix above makes the parser see MORE ports. If it saw everything the
    gate would stop finding real mismatches — and the sha256 finding this sweep
    surfaced (a testbench wiring `.reset_n` and `.rst_n` to a DUT whose only
    reset port is `reset`) must still fail.
    """
    (tmp_path / "dut.v").write_text(
        "module sha256 (\n  input wire clk,\n  input wire reset,\n"
        "  output wire ready\n);\nendmodule\n", encoding="utf-8")
    (tmp_path / "tb.v").write_text(
        "module tb;\n  sha256 u_dut (\n    .clk(clk),\n"
        "    .reset_n(reset_n),\n    .ready(ready)\n  );\nendmodule\n",
        encoding="utf-8")
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(_PROGRAMS / "module_port_audit.py"),
         "--rtl-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=45)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined[:500]
    assert "reset_n" in combined


# ── two further shapes, found by carrying the same sweep to zero ─────────────
def test_an_import_on_the_module_line_does_not_end_the_header(tmp_path):
    """The same defect with the clause moved up one line.

    The multi-line form above was recognised by a regex anchored at the start
    of the line, so this equally legal placement was not:

        module aes_cipher_control_fsm import aes_pkg::*;

    The header ended on the module line, which declares no ports, and every
    connection in every instantiation of it reported

        does not exist in module '…' port declarations. Available ports: []

    An EMPTY parse rendering as a wall of design findings. 81 files in the
    tracked corpus open this way. The predicate now decides on the import
    CLAUSE rather than on the line, so placement stops mattering.
    """
    src = (
        "module aes_cipher_control_fsm import aes_pkg::*;\n"
        "#(\n"
        "  parameter bit SecMasking = 0\n"
        ") (\n"
        "  input  logic clk_i,\n"
        "  input  logic rst_ni,\n"
        "  output logic out_valid_o\n"
        ");\n"
        "endmodule\n"
    )
    f = tmp_path / "fsm.sv"
    f.write_text(src, encoding="utf-8")
    mods = M.parse_modules(M.strip_comments(src), str(f))
    fsm = next((m for m in mods if m.name == "aes_cipher_control_fsm"), None)
    assert fsm is not None, [m.name for m in mods]
    assert {"clk_i", "rst_ni", "out_valid_o"} <= set(fsm.ports), (
        f"header truncated at the import's semicolon; parsed: {sorted(fsm.ports)}")


def test_the_comma_list_import_form_is_covered_too():
    """`import a::*, b::pkg;` is one clause, and a predicate matching only the
    single-package form would reopen the same hole on the next design."""
    assert not M.header_ends_on("module m import a::*, b::pkg;")
    assert M.header_ends_on("module m import p::*; #(parameter X=1) (input a);")


def test_multi_dimensional_packed_ports_are_parsed():
    """`input logic [3:0][3:0][7:0] data_i` — a 128-bit port on aes_sub_bytes.

    The packed group accepted ONE bracket, so the anchored match failed and the
    port vanished: that module's 5 multi-dimensional ports all read as "does
    not exist" while its 7 scalar ones parsed clean.
    """
    src = ("module m (\n"
           "  input  logic [3:0][3:0][7:0] data_i,\n"
           "  input  logic clk_i\n);")
    assert _ports(src) == {"data_i", "clk_i"}


def test_the_width_is_the_product_not_the_first_dimension():
    """Load-bearing, and the reason the width evaluator moved with the pattern.

    Accepting the extra dimensions without multiplying them would carry a
    128-bit port at 4 bits — trading a false "does not exist" for a false width
    mismatch. Same bogus finding, different message.
    """
    assert M.eval_width_expr("[3:0][3:0][7:0]") == 128
    assert M.eval_width_expr("[7:0]") == 8
    assert M.eval_width_expr("") == 1


def test_one_unresolvable_dimension_makes_the_whole_width_unknown():
    """A parameterized dimension must not be silently dropped from the product;
    -1 (unknown) is the honest answer, a partial product is a wrong number that
    looks like a measured one."""
    assert M.eval_width_expr("[3:0][WIDTH-1:0]") == -1
    assert M.eval_width_expr("[WIDTH-1:0]") == -1


def test_the_multi_dimensional_port_is_the_one_a_real_mismatch_is_caught_on(tmp_path):
    """The accept/reject boundary for THIS fix specifically.

    The general absent-port test above uses scalar ports, so it would pass even
    if multi-dimensional ports were being accepted unconditionally. This drives
    a mismatch on the multi-dimensional port itself — the one that used to be
    invisible.
    """
    (tmp_path / "sub.sv").write_text(
        "module sub (\n  input logic [3:0][3:0][7:0] data_i,\n"
        "  input logic clk_i\n);\nendmodule\n", encoding="utf-8")
    (tmp_path / "core.sv").write_text(
        "module core;\n  sub u_sub (\n    .data_iX(x),\n    .clk_i(clk_i)\n  );\n"
        "endmodule\n", encoding="utf-8")
    import subprocess
    r = subprocess.run([sys.executable, str(_PROGRAMS / "module_port_audit.py"),
                        "--rtl-dir", str(tmp_path)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "data_iX" in r.stdout, r.stdout


# ── fallout of making the multi-dimensional ports visible ────────────────────
def test_an_index_select_on_an_unknown_base_is_not_claimed_to_be_one_bit():
    """`signal[3]` was 1 bit unconditionally, which is only true when `signal`
    is a one-dimensional packed vector.

    Surfaced by the fix above: with `aes_sub_bytes.data_i` finally parsed at
    128 bits, its correct connection `state_q[0]` — one share of
    `logic [3:0][3:0][7:0] state_q [NumShares]` — was reported as a 1-bit width
    mismatch. The same false finding was already on main at
    `ibex_cs_registers:1168`, where `.counter_val_o(mhpmcounter[2])` connects an
    element of `logic [63:0] mhpmcounter [32]` to a 64-bit port.

    This parser does not carry local signal declarations, so for a base it
    cannot look up the honest answer is UNKNOWN. Returning 1 by assumption
    states a number nobody measured, in a form indistinguishable from a
    measured one.
    """
    parent = M.ModuleDef(name="p", ports={}, parameters=[], instances=[],
                          file="f.sv", line=1)
    assert M._infer_connection_width("state_q[0]", parent) == -1


def test_an_index_select_on_a_known_scalar_vector_is_still_one_bit():
    """The accept case. Dropping the inference entirely would lose every real
    bit-select finding, which is a worse trade than the one being fixed."""
    parent = M.ModuleDef(name="p", ports={}, parameters=[], instances=[],
                          file="f.sv", line=1)
    parent.ports["v"] = M.PortDecl(name="v", direction="input", width=8,
                                   width_expr="[7:0]", line=1, file="f.sv")
    assert M._infer_connection_width("v[3]", parent) == 1


def test_an_index_select_on_a_known_multi_dim_port_is_the_element_width():
    """`m[0]` where `m` is `[3:0][3:0][7:0]` selects 32 bits, not 1 and not
    128 — the total divided by the outermost dimension."""
    parent = M.ModuleDef(name="p", ports={}, parameters=[], instances=[],
                          file="f.sv", line=1)
    parent.ports["m"] = M.PortDecl(name="m", direction="input", width=128,
                                   width_expr="[3:0][3:0][7:0]", line=1,
                                   file="f.sv")
    assert M._infer_connection_width("m[0]", parent) == 32


def test_a_part_select_is_untouched():
    """`sig[7:0]` states its own width and never needed the base declaration."""
    parent = M.ModuleDef(name="p", ports={}, parameters=[], instances=[],
                          file="f.sv", line=1)
    assert M._infer_connection_width("sig[7:0]", parent) == 8
