#!/usr/bin/env python3
"""tests/test_self_rx_mask_check_alias_chain.py — v1.6.92

Closes issue #24 — _find_oe_signals / proximity scan walks
wire-alias chains so `~<alias>` and `~<literal>` both count as
evidence of masking.

The phase2 emitter oscillated across v1.6.88 - v1.6.91 between
writing the literal OE name (`id_bus_drive_low`) and a wire alias
of it (`id_bus_oe = id_bus_drive_low;` then `~id_bus_oe` in the
mask). The gate's one-directional canonicalization meant whichever
form the gate picked as canonical, the other would never satisfy
the proximity scan — producing a 4-iteration fixture flip with no
durable PASS.

v1.6.92 builds an alias equivalence class from `wire <a> = <b>;`
(and `assign <a> = <b>;`) declarations and accepts `~<x>` for any
`x` in the OE's class.
"""
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[2]))
PROG_DIR = PLUGIN_ROOT / "programs"
sys.path.insert(0, str(PROG_DIR))

import importlib  # noqa: E402

self_rx_mask_check = importlib.import_module("self_rx_mask_check")


def _seed_rtl(tmp_path: Path, rtl_text: str) -> Path:
    """Drop a single RTL file under a layout the gate accepts (rtl/
    excluded from the testbench-exclusion deny-list)."""
    rtl_dir = tmp_path / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "chip_top.sv").write_text(rtl_text)
    return tmp_path


def _audit(project: Path, pair: str = "id_bus"):
    """Invoke the gate's library entry and return (errors, findings)."""
    findings = self_rx_mask_check.audit(project, [pair])
    errors = [f for f in findings if f.severity == "ERROR"]
    return errors, findings


# ---------------------------------------------------------------------------
# Bug-1 reject-test pairs.
# ---------------------------------------------------------------------------

def test_alias_walk_accepts_literal_form_with_alias_present(tmp_path):
    """v1.6.91 fail mode: alias declared but mask uses LITERAL.
    Gate must walk the alias and accept ~id_bus_drive_low."""
    rtl = """
    module chip_top(input clk, input rst_n, inout id_bus);
        wire id_bus_drive_low;
        wire id_bus_oe = id_bus_drive_low;     // alias for human readability
        wire id_bus_rx = id_bus;
        wire id_bus_rx_masked = id_bus_rx & ~id_bus_drive_low;  // literal in mask
        reg [7:0] shift;
        always @(posedge clk) shift <= {shift[6:0], id_bus_rx_masked};
    endmodule
    """
    project = _seed_rtl(tmp_path, rtl)
    errors, findings = _audit(project)
    assert not errors, (
        "v1.6.92: gate must accept literal-form mask when alias is "
        f"declared. findings={[(f.rule, f.message) for f in findings]}"
    )


def test_alias_walk_accepts_alias_form_with_literal_declared(tmp_path):
    """v1.6.88/89 fail mode: literal declared but mask uses ALIAS.
    Gate must walk the alias and accept ~id_bus_oe."""
    rtl = """
    module chip_top(input clk, input rst_n, inout id_bus);
        wire id_bus_drive_low;
        wire id_bus_oe = id_bus_drive_low;
        wire id_bus_rx = id_bus;
        wire id_bus_rx_masked = id_bus_rx & ~id_bus_oe;  // alias in mask
        reg [7:0] shift;
        always @(posedge clk) shift <= {shift[6:0], id_bus_rx_masked};
    endmodule
    """
    project = _seed_rtl(tmp_path, rtl)
    errors, findings = _audit(project)
    assert not errors, (
        "v1.6.92: gate must accept alias-form mask when literal is "
        f"declared. findings={[(f.rule, f.message) for f in findings]}"
    )


def test_alias_walk_multi_hop_chain(tmp_path):
    """3-name chain: ground_drive → id_bus_drive_low → id_bus_oe.
    Mask uses the chain root; gate must walk both hops."""
    rtl = """
    module chip_top(input clk, input rst_n, inout id_bus);
        wire ground_drive;
        wire id_bus_drive_low = ground_drive;
        wire id_bus_oe = id_bus_drive_low;
        wire id_bus_rx = id_bus;
        wire id_bus_rx_masked = id_bus_rx & ~ground_drive;  // root in mask
        reg [7:0] shift;
        always @(posedge clk) shift <= {shift[6:0], id_bus_rx_masked};
    endmodule
    """
    project = _seed_rtl(tmp_path, rtl)
    errors, findings = _audit(project)
    assert not errors, (
        "v1.6.92: gate must walk multi-hop alias chains. "
        f"findings={[(f.rule, f.message) for f in findings]}"
    )


def test_alias_walk_negative_no_mask_anywhere(tmp_path):
    """Negative control: aliases declared but NO mask in any form.
    Gate must FAIL — alias-walking must not cause spurious PASS."""
    rtl = """
    module chip_top(input clk, input rst_n, inout id_bus);
        wire id_bus_drive_low;
        wire id_bus_oe = id_bus_drive_low;
        wire id_bus_rx = id_bus;
        wire id_bus_rx_passthrough = id_bus_rx;  // NO mask
        reg [7:0] shift;
        always @(posedge clk) shift <= {shift[6:0], id_bus_rx_passthrough};
    endmodule
    """
    project = _seed_rtl(tmp_path, rtl)
    errors, _ = _audit(project)
    assert errors, (
        "v1.6.92: gate must FAIL when no mask in any form, even with "
        "alias chain present (no spurious PASS from alias walking)."
    )
    assert any(e.rule == "self_rx_not_masked" for e in errors), (
        f"expected self_rx_not_masked finding; got {[e.rule for e in errors]}"
    )


# ---------------------------------------------------------------------------
# Direct unit test of the alias-equivalence helper.
# ---------------------------------------------------------------------------

def test_build_alias_equivalence_directly():
    """Helper-level: chain `a = b`, `b = c` collapses into one class;
    `d = e` is a separate class; unmentioned `f` is alone."""
    rtl = """
        wire a = b;
        wire b = c;
        wire d = e;
    """
    eq = self_rx_mask_check._build_alias_equivalence(rtl)
    assert self_rx_mask_check._names_in_class("a", eq) == {"a", "b", "c"}
    assert self_rx_mask_check._names_in_class("b", eq) == {"a", "b", "c"}
    assert self_rx_mask_check._names_in_class("c", eq) == {"a", "b", "c"}
    assert self_rx_mask_check._names_in_class("d", eq) == {"d", "e"}
    # `f` was never declared: name is its own singleton class.
    assert self_rx_mask_check._names_in_class("f", eq) == {"f"}


def test_build_alias_equivalence_assign_form():
    """`assign x = y;` form should also seed the equivalence class —
    the emitter sometimes uses assign instead of `wire <x> = <y>;`."""
    rtl = """
        wire id_bus_drive_low;
        wire id_bus_oe;
        assign id_bus_oe = id_bus_drive_low;
    """
    eq = self_rx_mask_check._build_alias_equivalence(rtl)
    assert self_rx_mask_check._names_in_class(
        "id_bus_oe", eq) == {"id_bus_oe", "id_bus_drive_low"}
