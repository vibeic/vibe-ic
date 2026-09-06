#!/usr/bin/env python3
"""ORGANIC #778 round-2 — the CROSS-SIDE doc pin-alias pair.

DEFECT (measured 2026-09-06, subservient x gf180mcuD, front-door run on
v1.17.64, image 0.3.46).  The L3 external-interface doc documents a port
under TWO accepted spellings via the backtick parenthetical grammar:

    `o_sram_data` (or `o_sram_wdata`)
    `i_sram_data` (or `i_sram_rdata`)

Round-1 (#778) reconciled this ONLY when the RTL top exposed BOTH
spellings as literal ports, because it cancels a residual only against an
ANCHOR — the same spelling present, with agreeing direction, on BOTH the
L9 side and the RTL side.

That leaves the ORDINARY reading of the grammar uncovered.  "`a` (or `b`)"
means the designer may pick ONE.  When Phase-1's L9 extractor promotes
spelling `a` and the authored RTL top carries spelling `b`, NEITHER name is
on both sides, so `anchor` is None, the group is skipped, and the gate
reports the very same physical pin twice — once as an L9 pin missing from
the RTL and once as an RTL port missing from L9:

    FAIL - L9 declares pins missing from RTL top: ['i_sram_data', 'o_sram_data']
         - RTL top has ports not in L9:           ['i_sram_rdata', 'o_sram_wdata']

The flow refused a design for taking an alternative its OWN input doc
authorised.  That FAIL is one of exactly two structural gates that gate
`final_audit` in Phase-2 strict-structural mode, so it halted the run.

FIX: when no member of a documented group is an anchor, but EXACTLY ONE
member is an unmatched L9 residual and the OTHER member is an unmatched RTL
residual, and their DIRECTIONS agree, they are one pin under the two
spellings the doc authorised — both cancel, and the reconciliation is
printed as an advisory rather than performed silently.

§4.05 NO-LEAK — each of these still FAILs:
  * directions disagree (an input/output swap under two documented names);
  * the alias partner is absent from the other side entirely (a genuinely
    missing pin, or a genuinely invented port);
  * the port is not a member of any documented alias group;
  * the design's docs declare no alias grammar at all.

Chip-AGNOSTIC fixture: generic `chip_top` / `bus` naming, matching the
round-1 test's convention — no chip, vendor, PDK or project literal.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "l9_rtl_pin_consistency_check.py"
)


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _write_project(project: Path, chip_top_v: str, l9_ports: list,
                   l3_doc_lines: list) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.v").write_text(chip_top_v)
    # Deliberately NO SOURCE_MANIFEST.json: this project is not reused-IP, so
    # the #711-r2 auto-derive (which lives inside the manifest branch) cannot
    # fire.  The cross-side pass must stand on the doc grammar alone.
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "layer": "L9",
        "ic_name": "TEST",
        "top_module": "chip_top",
        "top_level_ports": l9_ports,
    }, indent=2))
    docs = project / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_external_interface.md").write_text(
        "# External Interface\n\n"
        "| Port | Width | Dir | Description |\n"
        "|---|---|---|---|\n"
        + "\n".join(l3_doc_lines) + "\n"
    )


# L9 promoted the FIRST spelling of each documented pair.
_L9_FIRST_SPELLING = [
    {"name": "i_clk", "direction": "input"},
    {"name": "i_rst", "direction": "input"},
    {"name": "o_bus_data", "direction": "output"},
    {"name": "i_bus_data", "direction": "input"},
]

# The authored RTL top took the OTHER documented spelling of each pair.
_CHIP_TOP_SECOND_SPELLING = """\
module chip_top (
    input  wire       i_clk,
    input  wire       i_rst,
    output wire [7:0] o_bus_wdata,
    input  wire [7:0] i_bus_rdata
);
endmodule
"""

_ALIAS_DOC = [
    "| `o_bus_data` (or `o_bus_wdata`) | 8-bit | output | write data |",
    "| `i_bus_data` (or `i_bus_rdata`) | 8-bit | input | read data |",
]


def test_cross_side_alias_pair_reconciles(tmp_path):
    """THE DEFECT: L9 carries spelling `a`, the RTL top carries spelling `b`,
    directions agree.  One pin, two authorised names — must PASS, and must
    say so."""
    project = tmp_path / "p"; project.mkdir()
    _write_project(project, _CHIP_TOP_SECOND_SPELLING,
                   _L9_FIRST_SPELLING, _ALIAS_DOC)
    r = _run(project)
    assert r.returncode == 0, f"expected PASS, got:\n{r.stdout}\n{r.stderr}"
    assert "PASS" in r.stdout
    # The reconciliation is DISCLOSED, not silent.
    assert "doc-aliased pair" in r.stdout, r.stdout
    assert "o_bus_data" in r.stdout and "o_bus_wdata" in r.stdout
    assert "i_bus_data" in r.stdout and "i_bus_rdata" in r.stdout


def test_cross_side_pair_still_fails_without_the_alias_grammar(tmp_path):
    """NEGATIVE CONTROL / re-reddening: the SAME L9 and the SAME RTL, with
    the documented alternative removed from the doc.  Nothing about the
    design changed; only the authorisation went away.  Must FAIL, naming
    both residuals."""
    project = tmp_path / "p"; project.mkdir()
    _write_project(project, _CHIP_TOP_SECOND_SPELLING, _L9_FIRST_SPELLING,
                   ["| `o_bus_data` | 8-bit | output | write data |",
                    "| `i_bus_data` | 8-bit | input | read data |"])
    r = _run(project)
    assert r.returncode == 1, f"expected FAIL, got:\n{r.stdout}\n{r.stderr}"
    assert "o_bus_wdata" in r.stdout and "o_bus_data" in r.stdout


def test_cross_side_direction_disagreement_still_fails(tmp_path):
    """§4.05 NO-LEAK: the documented alias names the same SIGNAL, not a
    licence to flip its direction.  `o_bus_data` is an output in L9; the RTL
    declares its documented alias `o_bus_wdata` as an INPUT.  Must FAIL."""
    project = tmp_path / "p"; project.mkdir()
    chip_top = """\
module chip_top (
    input  wire       i_clk,
    input  wire       i_rst,
    input  wire [7:0] o_bus_wdata,
    input  wire [7:0] i_bus_rdata
);
endmodule
"""
    _write_project(project, chip_top, _L9_FIRST_SPELLING, _ALIAS_DOC)
    r = _run(project)
    assert r.returncode == 1, f"expected FAIL, got:\n{r.stdout}\n{r.stderr}"
    assert "o_bus_wdata" in r.stdout or "o_bus_data" in r.stdout


def test_missing_pin_with_no_partner_on_the_other_side_still_fails(tmp_path):
    """§4.05 NO-LEAK: an L9 pin whose documented alias partner is absent from
    the RTL ENTIRELY is a genuinely missing pin.  The alias grammar is
    present and must not cancel it."""
    project = tmp_path / "p"; project.mkdir()
    chip_top = """\
module chip_top (
    input  wire       i_clk,
    input  wire       i_rst,
    input  wire [7:0] i_bus_rdata
);
endmodule
"""
    _write_project(project, chip_top, _L9_FIRST_SPELLING, _ALIAS_DOC)
    r = _run(project)
    assert r.returncode == 1, f"expected FAIL, got:\n{r.stdout}\n{r.stderr}"
    assert "o_bus_data" in r.stdout


def test_invented_port_outside_any_alias_group_still_fails(tmp_path):
    """§4.05 NO-LEAK: a cross-side alias pair being reconciled must not
    co-absolve an unrelated invented port."""
    project = tmp_path / "p"; project.mkdir()
    chip_top = """\
module chip_top (
    input  wire       i_clk,
    input  wire       i_rst,
    output wire [7:0] o_bus_wdata,
    input  wire [7:0] i_bus_rdata,
    output wire       o_mystery_invented
);
endmodule
"""
    _write_project(project, chip_top, _L9_FIRST_SPELLING, _ALIAS_DOC)
    r = _run(project)
    assert r.returncode == 1, f"expected FAIL, got:\n{r.stdout}\n{r.stderr}"
    assert "o_mystery_invented" in r.stdout
