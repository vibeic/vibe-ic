#!/usr/bin/env python3
"""ORGANIC #778 — L3 doc-level explicit PIN-ALIAS reconciliation for
l9_rtl_pin_consistency_check.py.

DEFECT (subservient x sky130A / subservient x gf180mcuD, v1.5.60 fresh
flow_compliance_check runs — a processor_cpu-class reused-IP RISC-V core):
  The L3 external-interface doc documents a port under TWO accepted
  spellings via the backtick-quoted parenthetical grammar:
      `o_sram_data` (or `o_sram_wdata`)
      `i_sram_data` (or `i_sram_rdata`)
  meaning both spellings are authoritative labels for the SAME physical
  signal (a doc-author convenience). The Phase-1 L9 extractor promoted
  only ONE spelling of each pair into top_level_ports[] (`o_sram_data`,
  `i_sram_data`). The generated RTL top wrapper honoured BOTH documented
  spellings by exposing them as literal ports (tied together internally
  — the two write-data ports carry the same byte, the two read-data
  ports are OR-merged). l9_rtl_pin_consistency_check therefore hard-FAILed
  Step P0 with "RTL top has ports not in L9: ['i_sram_rdata',
  'o_sram_wdata']" — a false pin-drop finding; the RTL had not dropped or
  invented anything, it had faithfully exposed a doc-documented alias.

  This is a DIFFERENT root cause from ORGANIC #781 (reused-IP CONFIG-VARIANT
  surface reconciliation, keyed on a SOURCE_MANIFEST.json ip_list): this
  project's RTL carries NO SOURCE_MANIFEST.json (manifest=None), so #781's
  `_reused_ip_instantiated_surface` path never activates. The alias grammar
  is a property of the L3 INPUT DOC itself, not of reused-IP provenance.

FIX (chip-AGNOSTIC, #778): `_l3_doc_alias_groups()` scans the L3 doc for the
  backtick `` `a` (or `b`) `` grammar (order-independent — either spelling
  may be documented first) and `_reconcile_l3_doc_aliases()` drops a
  residual L9-only/RTL-only pin from the diff ONLY when (a) the OTHER
  member of its documented alias group is an ANCHOR — a name already
  present with AGREEING direction on both L9 and RTL — and (b) the
  residual pin's own direction agrees with that anchor's direction. This
  runs UNCONDITIONALLY (never gated on SOURCE_MANIFEST/manifest status),
  so it also covers a freshly-authored (non-catalog-glue) top.

§4.05 NO-LEAK:
  - A residual pin whose alias partner is NOT itself a matched anchor is
    NOT reconciled — still FAILs.
  - A residual pin whose OWN direction disagrees with the anchor's
    direction is NOT reconciled — still FAILs (a real direction defect
    can never hide behind an unrelated doc alias).
  - A genuinely dropped/invented pin with NO alias-group membership at
    all is completely unaffected by this pass — still FAILs, even in a
    project whose L3 doc happens to carry an (unrelated) alias pair.

Chip-AGNOSTIC fixture: generic `chip_top` / `core` naming (mirrors the
#781 test's `core_ip`/`chip_top` convention) — no chip/vendor/project
literal in either the program fix or this test.
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
    # Deliberately NO SOURCE_MANIFEST.json — this project is NOT reused-IP
    # per the manifest track; the #778 pass must NOT depend on it.
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


_L9_BASE = [
    {"name": "i_clk", "direction": "input"},
    {"name": "i_rst", "direction": "input"},
    {"name": "o_bus_data", "direction": "output"},
    {"name": "i_bus_data", "direction": "input"},
]

_CHIP_TOP_ALIAS_TMPL = """\
module chip_top (
    input  wire       i_clk,
    input  wire       i_rst,
    output wire [7:0] o_bus_data,
    input  wire [7:0] i_bus_data,
    output wire [7:0] o_bus_wdata,
    input  wire [7:0] i_bus_rdata{extra}
);
endmodule
"""


def test_pass_l3_doc_alias_reconciled(tmp_path):
    """RTL faithfully exposes BOTH doc-documented alias spellings
    (o_bus_data/o_bus_wdata, i_bus_data/i_bus_rdata) — the gate now PASSes
    and prints the reconciliation as an advisory, not a FAIL finding."""
    project = tmp_path / "p"; project.mkdir()
    _write_project(
        project, _CHIP_TOP_ALIAS_TMPL.format(extra=""), _L9_BASE,
        [
            "| `o_bus_data` (or `o_bus_wdata`) | 8-bit | output | write data |",
            "| `i_bus_data` (or `i_bus_rdata`) | 8-bit | input | read data |",
        ],
    )
    r = _run(project)
    assert r.returncode == 0, f"expected PASS, got:\n{r.stdout}\n{r.stderr}"
    assert "PASS" in r.stdout
    assert "o_bus_wdata" in r.stdout and "doc-aliased" in r.stdout
    assert "i_bus_rdata" in r.stdout and "doc-aliased" in r.stdout


def test_fail_unrelated_dropped_pin_still_fails_with_alias_doc_present(tmp_path):
    """§4.05 NO-LEAK: an L3 doc alias pair for one interface must NOT mask
    a genuinely-INVENTED, unrelated RTL port with no alias-group membership
    at all."""
    project = tmp_path / "p"; project.mkdir()
    chip_top = """\
module chip_top (
    input  wire       i_clk,
    input  wire       i_rst,
    output wire [7:0] o_bus_data,
    input  wire [7:0] i_bus_data,
    output wire [7:0] o_bus_wdata,
    input  wire [7:0] i_bus_rdata,
    output wire       o_mystery_invented
);
endmodule
"""
    _write_project(
        project, chip_top, _L9_BASE,
        [
            "| `o_bus_data` (or `o_bus_wdata`) | 8-bit | output | write data |",
            "| `i_bus_data` (or `i_bus_rdata`) | 8-bit | input | read data |",
        ],
    )
    r = _run(project)
    assert r.returncode == 1, f"expected FAIL, got:\n{r.stdout}\n{r.stderr}"
    assert "o_mystery_invented" in r.stdout
    # The legitimate aliases must still be reconciled (not co-blamed).
    assert "o_bus_wdata" not in _extract_only_rtl_line(r.stdout)
    assert "i_bus_rdata" not in _extract_only_rtl_line(r.stdout)


def test_fail_direction_mismatch_not_masked_by_alias_doc(tmp_path):
    """§4.05 NO-LEAK: if the alias-partner port's OWN RTL direction
    disagrees with the anchor's direction, that is a real defect (e.g. the
    wrapper coded the alias as the wrong direction) — must NOT reconcile."""
    project = tmp_path / "p"; project.mkdir()
    chip_top = """\
module chip_top (
    input  wire       i_clk,
    input  wire       i_rst,
    output wire [7:0] o_bus_data,
    input  wire [7:0] i_bus_data,
    input  wire [7:0] o_bus_wdata,
    input  wire [7:0] i_bus_rdata
);
endmodule
"""
    _write_project(
        project, chip_top, _L9_BASE,
        [
            "| `o_bus_data` (or `o_bus_wdata`) | 8-bit | output | write data |",
            "| `i_bus_data` (or `i_bus_rdata`) | 8-bit | input | read data |",
        ],
    )
    r = _run(project)
    assert r.returncode == 1, f"expected FAIL, got:\n{r.stdout}\n{r.stderr}"
    assert "o_bus_wdata" in r.stdout


def test_no_reconcile_when_anchor_never_matched(tmp_path):
    """When NEITHER alias-group member is a matched anchor (e.g. the L9 doc
    never declared either spelling), the #778 pass is a no-op — normal
    only_l9 / only_rtl FAIL behaviour is unaffected."""
    project = tmp_path / "p"; project.mkdir()
    chip_top = """\
module chip_top (
    input  wire       i_clk,
    input  wire       i_rst,
    output wire [7:0] o_bus_wdata,
    input  wire [7:0] i_bus_rdata
);
endmodule
"""
    l9_no_bus = [
        {"name": "i_clk", "direction": "input"},
        {"name": "i_rst", "direction": "input"},
    ]
    _write_project(
        project, chip_top, l9_no_bus,
        [
            "| `o_bus_data` (or `o_bus_wdata`) | 8-bit | output | write data |",
            "| `i_bus_data` (or `i_bus_rdata`) | 8-bit | input | read data |",
        ],
    )
    r = _run(project)
    assert r.returncode == 1, f"expected FAIL, got:\n{r.stdout}\n{r.stderr}"
    assert "o_bus_wdata" in r.stdout and "i_bus_rdata" in r.stdout


def _extract_only_rtl_line(stdout: str) -> str:
    for line in stdout.splitlines():
        if "has ports not in L9" in line:
            return line
    return ""
