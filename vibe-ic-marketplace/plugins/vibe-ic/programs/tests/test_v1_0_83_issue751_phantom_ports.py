"""ORGANIC #751 [P1] — _specrtl_common.extract_spec_contract fabricated PHANTOM
ports scraped from prose, producing an unclearable spec_coverage_check --strict
BLOCK on spec-faithful RTL.

TWO defects in programs/_specrtl_common.py:

  DEFECT A — the fallback `elif re.search(r'\\bmodule\\b', clean): parse_rtl_ports`
  fired on the bare English WORD 'module' anywhere in prose ("Design a GP
  module", "Modify the existing module"), so the ENTIRE natural-language spec was
  scanned as Verilog and _PORT_DECL harvested English phrases as phantom ports
  ('1-bit input signal'->'signal', 'output of that'->'of', 'output every
  clock'->'every', 'valid input data'->'data', 'output bit stream'->'bit').
  FIX: gate the fallback on a genuine `module\\s+\\w+ ... endmodule` FENCE (which
  prose never has) instead of the bare word 'module'.

  DEFECT B — `_NL_PORT` was not end-anchored, so ordinary prose bullets matched:
  '- Input ports:' -> Port('ports'), '- Output all zeros (...)' -> Port('all'),
  '- Output latency is 1 clock cycle.' -> Port('latency'), '- Input
  coefficients `[..]`' -> Port('coefficients'). FIX: end-anchor `_NL_PORT` with
  `[ \\t]*$` so only true `- input <name> [(N bits)]` bullets match.

§4.05 no-leak: a real NL port bullet, a real md-table port, and a real non-ANSI
module-FENCE extraction must ALL still work after the fix.

chip-AGNOSTIC: pure grammar fixes, no design / vendor / SKU literal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import _specrtl_common as SRC  # noqa: E402


def _ports(spec: str):
    return [p.name for p in SRC.extract_spec_contract(spec, confirm=False).ports]


# ── DEFECT A: bare-word 'module' in prose must NOT scrape phantom ports ──────
def test_bare_word_module_in_prose_yields_no_phantom_ports():
    """The issue's verbatim prose 現象: 'Design a GP module' + 'Modify the
    existing module' + 'input signal' / 'output of that' / 'output every clock'
    used to harvest signal/of/every/data/bit as phantom ports."""
    prose = (
        "Design a GP module that takes a 1-bit input signal and produces an\n"
        "output of that signal on every clock. The valid input data drives an\n"
        "output bit stream. Modify the existing module accordingly.\n"
    )
    names = _ports(prose)
    assert names == [], names
    for phantom in ("signal", "of", "every", "data", "bit"):
        assert phantom not in names, (phantom, names)


def test_complete_this_module_skeleton_prose_no_phantom():
    """A 'complete this module' skeleton mention (bare word 'module', no fence)
    must not trigger the prose-as-Verilog scan."""
    prose = (
        "Complete the following module. The module should accept a request and\n"
        "return a response. Implement the module body below.\n"
    )
    assert _ports(prose) == []


# ── DEFECT B: un-anchored _NL_PORT matched prose bullets ─────────────────────
def test_prose_bullets_not_scraped_as_ports():
    """The issue's verbatim bullet 現象: heading-style bullets and trailing-prose
    bullets used to yield ports/coefficients/all/latency."""
    bullets = (
        "Interface:\n"
        "- Input ports:\n"
        "- Output ports:\n"
        "- Input coefficients `[1, 2, 3]`\n"
        "- Output all zeros (when idle)\n"
        "- Output latency is 1 clock cycle.\n"
    )
    names = _ports(bullets)
    assert names == [], names
    for phantom in ("ports", "coefficients", "all", "latency"):
        assert phantom not in names, (phantom, names)


# ── §4.05 NO-LEAK: real extraction paths still work ─────────────────────────
def test_real_nl_port_bullets_still_extracted():
    """A genuine `- input clk` / `- input d (8 bits)` bullet block still parses
    to real ports with correct direction + width."""
    spec = (
        "Interface:\n"
        "- input clk\n"
        "- input d (8 bits)\n"
        "- output q\n"
    )
    ports = {p.name: (p.direction, p.width)
             for p in SRC.extract_spec_contract(spec, confirm=False).ports}
    assert ports == {"clk": ("input", 1),
                     "d": ("input", 8),
                     "q": ("output", 1)}, ports


def test_real_md_table_ports_still_extracted():
    """A real datasheet markdown interface table still yields its ports."""
    spec = (
        "| Signal | Dir   | Width | Description |\n"
        "|--------|-------|-------|-------------|\n"
        "| clk    | input | 1     | clock       |\n"
        "| d      | in    | [7:0] | data        |\n"
        "| q      | output| 1     | result      |\n"
    )
    names = set(_ports(spec))
    assert {"clk", "d", "q"} <= names, names


def test_real_nonansi_module_fence_still_extracted():
    """A genuine non-ANSI `module ... endmodule` FENCE (the path the new guard
    deliberately keeps) still extracts its real ports."""
    spec = (
        "The reference design is:\n"
        "module TopModule;\n"
        "  input clk;\n"
        "  input rst_n;\n"
        "  output reg [3:0] cnt;\n"
        "endmodule\n"
    )
    names = set(_ports(spec))
    assert {"clk", "rst_n", "cnt"} <= names, names
    # and none of the prose-leak phantoms slipped in
    for phantom in ("signal", "of", "every", "data", "bit",
                    "ports", "coefficients", "latency"):
        assert phantom not in names, (phantom, names)


# ── END-STATE through spec_coverage_check (the issue's consumer) ─────────────
def test_endstate_speccov_no_phantom_block(tmp_path):
    """END-STATE: a spec-faithful design whose prose contains 'module' and prose
    bullets no longer derives phantom `port` checklist items, so a TB driving the
    real ports is not blocked by an un-coverable phantom port."""
    import spec_coverage_check as SCC  # noqa: E402

    spec = (
        "Design a GP module.\n"
        "- Input ports:\n"
        "- input clk\n"
        "- input d\n"
        "- output q\n"
        "Output latency is 1 clock cycle.\n"
    )
    rtl = "module dut(input clk, input d, output q);\nendmodule\n"
    tb = ("module tb; reg clk, d; wire q;\n"
          "  initial begin clk=0; d=1; #5 clk=1; @(posedge clk); end\n"
          "endmodule\n")
    report = SCC.run({"user_prompt": spec}, rtl, tb, None, True)
    port_tokens = [it["coverage_tokens"][0]
                   for it in report["items"] if it["kind"] == "port"]
    # only the THREE real ports — no 'ports'/'latency'/etc phantom
    assert set(port_tokens) <= {"clk", "d", "q"}, port_tokens
    for phantom in ("ports", "latency", "all", "coefficients", "signal"):
        assert phantom not in port_tokens, (phantom, port_tokens)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_751_endstate_no_phantom_via_program(tmp_path):
    """#478 defect-artifact + end-state: a prose spec that mentions 'module' and
    'Input ports:' produces NO phantom-port checklist item — invoked through the
    real spec_coverage_check.py program (not just the parser)."""
    import subprocess
    spec = tmp_path / "spec.txt"
    rtl = tmp_path / "dut.sv"
    spec.write_text("Design a GP module.\n- Input ports:\n- input clk\n"
                    "- output q result output\n")
    rtl.write_text("module dut(input clk, output q); endmodule\n")
    prog = _PROGRAMS / "spec_coverage_check.py"
    cp = subprocess.run([sys.executable, str(prog), "--spec", str(spec),
                         "--rtl", str(rtl)], capture_output=True, text=True)
    assert cp.returncode in (0, 1)
    # phantom 'ports' must NOT appear as a required port item.
    assert "'ports'" not in cp.stdout and "port 'ports'" not in cp.stdout
