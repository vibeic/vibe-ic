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

241 and 368 (subservient) remain and are still very likely parser limits, not
design defects. This is a large improvement, not a clean gate.
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
