#!/usr/bin/env python3
"""tests/test_v0_3_2_issue491r2_multitable.py
ORGANIC-20260606 #491 ROUND-2 — upstream L1 multi-pipe-table extractor.

WHY THIS FILE EXISTS (the round-1 self-test gap the field agent named)
======================================================================
The #491 round-1 self-test (`test_v0_2_102_...`) pre-STUFFED the three
ports into `L1.pin_table` via `_seed_l1(...)` and then only verified the
DOWNSTREAM promoter row-loop + the gate. It was 15/15 green while a clean
rerun on REAL docs still FAILed:

    FAIL — RTL top has ports not in L9: [<GPIO-style port>]

ROOT CAUSE (UPSTREAM, in phase1_doc_one_shot_runner.py, NOT the gate):
the per-row interface-table regex family (`_RE_L1_L9_RST_IFACE_4COL` /
`_DIR2` / `_2COL` / `_3COL` / `_NCOL_SUFFIX`) hard-codes the column ORDER
and anchors every row on a leading `^|` (and most require a trailing
`|`). An interface doc that carries TWO pipe tables — a MAIN port-group
table (clk / reset / GPIO) and a memory-block SUB-port table — surfaces
with only one table's rows when the tables differ in column order or use
the BORDERLESS GFM form, so the whole main table is dropped and the
remaining table's rows can end up direction-less.

FIX (v0.3.2): a universal multi-table header-role pin walker
(`_v0_3_2_emit_pins_from_gfm_tables`) that walks EVERY name+direction
pipe-table in the doc (bordered AND borderless), resolves each table's
direction column from its OWN header (so per-table direction parsing is
independent — the second table is never direction=None just because the
first differs), and is bounded to each table block so SDC / stdcell-
library lines elsewhere in the doc cannot leak in.

THESE TESTS CLOSE THE GAP by driving the REAL phase1 extraction layer
end-to-end from REAL-shaped dual-table markdown fixtures (NO pre-stuffing
of L1.pin_table), then running the REAL l9_rtl_pin_consistency_check.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
for _p in (str(PROGRAMS), str(PLUGIN_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase1_doc_one_shot_runner as DOC  # noqa: E402

DOC_RUNNER = PROGRAMS / "phase1_doc_one_shot_runner.py"
GATE_PROG = PROGRAMS / "l9_rtl_pin_consistency_check.py"
_GEN = Path("phase1") / "generated_docs"
_RTL = Path("phase2") / "stage1" / "rtl"


# ── helpers ────────────────────────────────────────────────────────
def _run_doc_runner(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DOC_RUNNER), str(project)],
        capture_output=True, text=True, timeout=60,
    )


def _run_gate(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE_PROG), str(project)],
        capture_output=True, text=True, timeout=60,
    )


def _l1(project: Path) -> dict:
    return json.loads(
        (project / _GEN / "L1_DATASHEET.json").read_text())


def _l9(project: Path) -> dict:
    return json.loads(
        (project / _GEN / "L9_INTEGRATION_SPEC.json").read_text())


def _l1_names(project: Path) -> set:
    return {p.get("name") for p in (_l1(project).get("pin_table") or [])}


def _l9_names(project: Path) -> set:
    return {p.get("name") for p in (_l9(project).get("top_ports") or [])}


def _write_doc(project: Path, name: str, body: str) -> Path:
    docs = project / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    fp = docs / name
    fp.write_text(body)
    return fp


def _write_rtl_top(project: Path, name: str, port_lines: list[str]) -> None:
    rtl = project / _RTL
    rtl.mkdir(parents=True, exist_ok=True)
    body = ",\n  ".join(port_lines)
    (rtl / f"{name}.sv").write_text(
        f"module {name} (\n  {body}\n);\nendmodule\n")


# ════════════════════════════════════════════════════════════════════
# UNIT — the new header-role walker handles MULTIPLE tables, per-table
# direction roles, bordered + borderless, with no cross-table latch.
# ════════════════════════════════════════════════════════════════════
def test_unit_borderless_gfm_single_table():
    """A BORDERLESS GFM pipe table (no outer `|`) — the canonical
    Markdown form the order-locked per-row regexes all miss because
    they anchor on `^|`."""
    text = (
        "Signal | Direction | Width | Description\n"
        "------ | --------- | ----- | -----------\n"
        "clk | input | 1 | system clock\n"
        "reset_n | input | 1 | reset\n"
        "gpio_out | output | 8 | gpio bus\n"
    )
    rows = list(DOC._v0_3_2_emit_pins_from_gfm_tables(text))
    got = {(r["name"], r["direction"]) for r in rows}
    assert got == {
        ("clk", "input"), ("reset_n", "input"), ("gpio_out", "output")}


def test_unit_two_tables_both_walked_no_latch():
    """TWO tables in ONE doc → BOTH are walked. Neither is latched /
    dropped in favour of the other (the #491 R2 root-cause shape)."""
    text = (
        "## Top-Level Ports\n\n"
        "| Port | Direction | Width | Description |\n"
        "|------|-----------|-------|-------------|\n"
        "| clk | input | 1 | clk |\n"
        "| gpio_out | output | 8 | gpio |\n\n"
        "## SRAM Sub-Ports\n\n"
        "| Pin | Direction | Width | Description |\n"
        "|-----|-----------|-------|-------------|\n"
        "| mem_addr | input | 10 | addr |\n"
        "| mem_rdata | output | 32 | data |\n"
    )
    rows = list(DOC._v0_3_2_emit_pins_from_gfm_tables(text))
    got = {r["name"] for r in rows}
    assert got == {"clk", "gpio_out", "mem_addr", "mem_rdata"}, got


def test_unit_second_table_different_column_order_direction_not_none():
    """Per-table direction parsing is INDEPENDENT: the second table's
    direction column sits in a DIFFERENT position than the first, and it
    is resolved correctly (never None)."""
    text = (
        "| Signal | Direction | Width | Description |\n"
        "|--------|-----------|-------|-------------|\n"
        "| clk | input | 1 | clk |\n\n"
        "| Pin | Width | Direction | Description |\n"   # dir is col 2
        "|-----|-------|-----------|-------------|\n"
        "| mem_q | 32 | output | data |\n"
    )
    rows = list(DOC._v0_3_2_emit_pins_from_gfm_tables(text))
    by_name = {r["name"]: r["direction"] for r in rows}
    assert by_name == {"clk": "input", "mem_q": "output"}, by_name
    # The decisive #491-R2 assertion: the SECOND table's direction is a
    # real direction, NOT None.
    assert by_name["mem_q"] is not None
    assert by_name["mem_q"] == "output"


def test_unit_non_direction_column_does_not_fabricate_direction():
    """A table whose only matchable column is a `Type` column with
    non-direction body values (`Clock` / `Data`) must NOT emit rows with
    a fabricated / null direction — it emits nothing."""
    text = (
        "| Pin | Type | Function |\n"
        "|-----|------|----------|\n"
        "| clk | Clock | system clock |\n"
        "| dbus | Data | data bus |\n"
    )
    rows = list(DOC._v0_3_2_emit_pins_from_gfm_tables(text))
    assert rows == [], rows


def test_unit_block_bounded_no_sdc_or_library_leak():
    """The walker is bounded to each table block: SDC directive lines
    and a stdcell-library token sitting OUTSIDE the tables never leak in
    as pins (#475 noise families)."""
    text = (
        "| Signal | Direction | Width | Description |\n"
        "|--------|-----------|-------|-------------|\n"
        "| clk | input | 1 | clk |\n"
        "| gpio_out | output | 8 | gpio |\n\n"
        "set_input_delay 2.0 -clock clk [all_inputs]\n"
        "create_clock -name clk -period 10\n"
        "The design uses the demo_fd_sc_hdll library.\n"
    )
    names = {r["name"] for r in DOC._v0_3_2_emit_pins_from_gfm_tables(text)}
    assert names == {"clk", "gpio_out"}, names
    assert not (names & {"set_input_delay", "create_clock",
                         "demo_fd_sc_hdll"}), names


# ════════════════════════════════════════════════════════════════════
# FULL END-TO-END through the REAL phase1_doc runner (NO pre-stuffing of
# L1.pin_table — this is the layer the round-1 self-test skipped).
# ════════════════════════════════════════════════════════════════════
# A real-shaped dual-table interface doc:
#   - a MAIN top-level port-group table (clk / reset / GPIO),
#   - a memory-block SUB-port table in a DIFFERENT column order,
#   - SDC constraint lines + a stdcell-library mention OUTSIDE the
#     tables (the #475 noise families that must stay rejected),
#   - the tables are written in the BORDERLESS GFM form the order-locked
#     per-row regexes drop entirely.
_DUAL_TABLE_DOC = """# Foundry Handoff — External Interface & Constraints

## Top-Level Port Group

The chip exposes the following top-level ports.

Signal | Direction | Width | Description
------ | --------- | ----- | -----------
clk | input | 1 | system clock
reset_n | input | 1 | active-low asynchronous reset
gpio_out | output | 8 | general-purpose output bus
gpio_oe | output | 8 | general-purpose output enable

## Timing Constraints

```
create_clock -name clk -period 10.0 [get_ports clk]
set_input_delay 2.0 -clock clk [all_inputs]
set_output_delay 2.0 -clock clk [all_outputs]
```

The design targets the demo_fd_sc_hdll standard cell library.

## SRAM Macro Sub-Ports

The integrated SRAM macro exposes these block-level sub-ports
(note the DIFFERENT column order — Width precedes Direction):

Pin | Width | Direction | Description
--- | ----- | --------- | -----------
mem_addr | 10 | input | memory address
mem_wdata | 32 | input | memory write data
mem_rdata | 32 | output | memory read data
"""

_ALL_PORTS = {
    "clk", "reset_n", "gpio_out", "gpio_oe",
    "mem_addr", "mem_wdata", "mem_rdata",
}


def test_e2e_dual_table_all_rows_reach_l1_and_l9(tmp_path):
    """ACCEPTANCE — the field agent's failing 場景, replayed verbatim:
    the dual-table fixture is regenerated through the REAL phase1_doc
    runner; L1.pin_table AND L9.top_ports must carry ALL rows from BOTH
    tables (with directions), and the #475 SDC/library noise must NOT
    appear."""
    proj = tmp_path / "proj"
    _write_doc(proj, "foundry_handoff_interface.md", _DUAL_TABLE_DOC)

    r = _run_doc_runner(proj)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]

    # L1 — every row from BOTH tables, with directions.
    l1_pins = {p.get("name"): p.get("mode")
               for p in (_l1(proj).get("pin_table") or [])}
    assert set(l1_pins) == _ALL_PORTS, (
        f"L1 dropped rows: missing {_ALL_PORTS - set(l1_pins)}")
    for nm, md in l1_pins.items():
        assert md in {"input", "output", "inout"}, (nm, md)

    # L9 — the canonical key carries ALL rows under the canonical key.
    assert _l9_names(proj) == _ALL_PORTS, (
        f"L9 dropped rows: missing {_ALL_PORTS - _l9_names(proj)}")

    # #475 noise families never leak.
    leak = (set(l1_pins) | _l9_names(proj)) & {
        "set_input_delay", "set_output_delay", "create_clock",
        "demo_fd_sc_hdll", "get_ports", "all_inputs", "all_outputs"}
    assert not leak, f"SDC/library noise leaked: {leak}"


def test_e2e_dual_table_then_real_gate_pass(tmp_path):
    """ACCEPTANCE (continued) — run the REAL l9_rtl_pin_consistency_check
    against a matching RTL top → PASS. Pre-fix the borderless main table
    was dropped → gpio_out absent from L9 →
    'RTL top has ports not in L9: gpio_out' FAIL."""
    proj = tmp_path / "proj"
    _write_doc(proj, "foundry_handoff_interface.md", _DUAL_TABLE_DOC)
    r = _run_doc_runner(proj)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]

    # Point the gate at chip_top + author a matching RTL top.
    l9 = _l9(proj)
    l9["top_module"] = "chip_top"
    (proj / _GEN / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(l9, indent=2))
    _write_rtl_top(proj, "chip_top", [
        "input  wire clk",
        "input  wire reset_n",
        "output wire [7:0]  gpio_out",
        "output wire [7:0]  gpio_oe",
        "input  wire [9:0]  mem_addr",
        "input  wire [31:0] mem_wdata",
        "output wire [31:0] mem_rdata",
    ])

    g = _run_gate(proj)
    assert g.returncode == 0, g.stdout
    assert "PASS" in g.stdout, g.stdout
    assert "SKIP" not in g.stdout, g.stdout
    # clk / reset_n are implicit-stripped; the 5 functional pins remain.
    # #591 — the evidence line now reports compared/total + named skips
    # (the dual-key-mirror duplicates from the #490 multi-key L9 write).
    assert "agree on 5/" in g.stdout, g.stdout


# ════════════════════════════════════════════════════════════════════
# REGRESSION — single-table docs unchanged; bordered GFM still works.
# ════════════════════════════════════════════════════════════════════
_SINGLE_TABLE_DOC = """# Simple Interface

## Ports

| Port | Direction | Width | Description |
|------|-----------|-------|-------------|
| clk | input | 1 | clock |
| data_in | input | 8 | input bus |
| data_out | output | 8 | output bus |
"""


def test_e2e_single_table_unchanged(tmp_path):
    """A single bordered-GFM port table still extracts exactly its rows
    (the new walker coexists with the per-row regexes; `_add_pin`
    score-merge dedups so no duplicates appear)."""
    proj = tmp_path / "proj"
    _write_doc(proj, "interface.md", _SINGLE_TABLE_DOC)
    r = _run_doc_runner(proj)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    pins = _l1(proj).get("pin_table") or []
    names = [p.get("name") for p in pins]
    assert set(names) == {"clk", "data_in", "data_out"}, names
    # No duplicate entries from the two coexisting extractors.
    assert len(names) == len(set(names)), f"dup entries: {names}"
