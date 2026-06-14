"""Regression for ORGANIC #637 — RTL top-port parsers return zero ports when an
`import pkg::*;` clause sits between `module <name>` and the `#(...)` parameter
block (import-before-param header ordering).

現象 (round-2 v1.0.22 6-IC clean-room): a REUSED-IP / IP-integration-wrapper
top is declared with the standard SystemVerilog ordering
`module chip_top import tlul_pkg::*; import top_pkg::*; #(params) (ports);`.
Two header parsers broke on it:
  * l9_rtl_pin_consistency_check.parse_rtl_top_ports — `_strip_param_block`
    only strips a `#(...)` block immediately following `module <name>` (its
    `#(` test is anchored there), so an intervening `import ...;` clause lets
    the param block survive; the main port-list regex then never matches and
    returns ZERO ports → the sole strict structural pin gate false-FAILs
    "parsed zero ports".
  * reset_clock_variant_alias._module_header — after `module <name>` it tests
    for `#`/`(` but finds `import`, returning None → the clock/reset alias
    emitter (and parse_module_ports, reused by #629's TB reconciliation) is
    silently disabled / sees zero ports.

Fix: both parsers consume any number of `import ...;` clauses between the
module name and the `#(...)`/`(...)` regions before locating the port list, so
the header scan is order-independent across module / imports* / optional
#(...) / (ports).

NEGATIVE no-leak: the other three orderings (import-only, param-only, plain)
keep returning the correct ports; a malformed header still yields [] (no
fabricated ports).

chip-AGNOSTIC: pure SV header structure; no chip / vendor / SKU literal.
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l9_rtl_pin_consistency_check as L9  # noqa: E402
import reset_clock_variant_alias as RCV    # noqa: E402


def _top(pre_ports: str) -> str:
    """A chip_top module whose pre-port-list region is `pre_ports` (imports /
    params in some ordering), with three ANSI ports."""
    return ("module chip_top\n" + pre_ports +
            "  input  logic clk_i,\n"
            "  input  logic rst_ni,\n"
            "  output logic [7:0] q\n"
            ");\n  assign q = '0;\nendmodule\n")


_ORDERINGS = {
    "import+param": "  import tlul_pkg::*;\n  import top_pkg::*;\n"
                    "#(\n  parameter int W = 8\n) (\n",
    "import_only": "  import tlul_pkg::*;\n (\n",
    "param_only": "#(parameter int W = 8) (\n",
    "plain": " (\n",
}


@pytest.mark.parametrize("ordering", sorted(_ORDERINGS))
def test_l9_parse_rtl_top_ports_all_orderings(ordering, tmp_path):
    p = tmp_path / "chip_top.sv"
    p.write_text(_top(_ORDERINGS[ordering]))
    names = [d["name"] for d in L9.parse_rtl_top_ports(p)]
    assert names == ["clk_i", "rst_ni", "q"], (ordering, names)


@pytest.mark.parametrize("ordering", sorted(_ORDERINGS))
def test_rcv_parse_module_ports_all_orderings(ordering):
    txt = _top(_ORDERINGS[ordering])
    names = [n for _d, _w, n in RCV.parse_module_ports(txt, "chip_top")]
    assert names == ["clk_i", "rst_ni", "q"], (ordering, names)
    assert RCV._module_header(txt, "chip_top") is not None


def test_full_pin_gate_passes_on_import_before_param(tmp_path):
    """End state: the full l9_rtl_pin_consistency_check gate no longer
    false-FAILs 'parsed zero ports' on a valid package-importing top whose L9
    matches."""
    proj = tmp_path / "proj"
    rtl = L9._pl.rtl_dir(proj)
    rtl.mkdir(parents=True)
    (rtl / "chip_top.sv").write_text(_top(_ORDERINGS["import+param"]))
    gd = L9._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "clk_i", "direction": "input"},
            {"name": "rst_ni", "direction": "input"},
            {"name": "q", "direction": "output"},
        ]}))
    rc = L9.main(["l9_rtl_pin_consistency_check.py", str(proj)])
    assert rc == 0, "gate false-FAILed on a valid import-before-param top"


def test_multiple_imports_then_param(tmp_path):
    """Repeatable import clauses (the OpenTitan-style 2+ imports) are all
    consumed."""
    pre = ("  import tlul_pkg::*;\n  import top_pkg::*;\n  import a_pkg::*;\n"
           "#(parameter int W = 8) (\n")
    p = tmp_path / "chip_top.sv"
    p.write_text(_top(pre))
    names = [d["name"] for d in L9.parse_rtl_top_ports(p)]
    assert names == ["clk_i", "rst_ni", "q"]


# ── NEGATIVE no-leak ─────────────────────────────────────────────────────────

def test_malformed_header_yields_no_ports_NOLEAK(tmp_path):
    """A truncated header (no closing port paren) must still yield [] — the
    fix must not fabricate ports."""
    p = tmp_path / "chip_top.sv"
    p.write_text("module chip_top import x_pkg::*; #(parameter W=8)\n"
                 "  // no port list, no ;\n")
    assert L9.parse_rtl_top_ports(p) == []
    assert RCV._module_header(
        "module chip_top import x_pkg::*; #(parameter W=8)\n", "chip_top") \
        is None


def test_param_default_with_function_call_still_parses(tmp_path):
    """The #474 balanced-paren guard still holds WITH an import clause: a
    `$clog2(...)` default inside the param block does not truncate the strip."""
    pre = ("  import x_pkg::*;\n#(\n  parameter int AW = $clog2(MEMSIZE)\n) (\n")
    p = tmp_path / "chip_top.sv"
    p.write_text(_top(pre))
    names = [d["name"] for d in L9.parse_rtl_top_ports(p)]
    assert names == ["clk_i", "rst_ni", "q"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
