#!/usr/bin/env python3
"""The post-layout LEC loaded EVERY blackbox Verilog the PDK ships.

`_discover_blackbox_verilog` globs `libs.ref/*/verilog/*blackbox*.v`. Its own
docstring says the job is models for "physical-only cells ... on a routed
netlist" -- cells the netlist CONTAINS -- but the glob has no netlist in it, so
it also hands yosys the io and SRAM families of a design that instantiates
neither.

MEASURED 2026-08-29, spm x gf180mcuD (v1.12.65): the routed netlist instantiates
39 distinct masters, ALL `gf180mcu_fd_sc_mcu7t5v0__*`; 0 io cells, 0 SRAM cells.
The glob still fed yosys six io/SRAM files, and one of them,
`gf180mcu_fd_ip_sram__sram128x8m8wm1__blackbox.v`, declares `inout VDD;` /
`inout VSS;` in the module BODY while its header port list names neither. That
is illegal Verilog-2005 (IEEE 1364-2005 s12.3), so yosys correctly refuses it:

    ...__blackbox.v:43: ERROR: Module port `\\VDD' is not declared in module
    header

yosys exit 1 -> post-layout LEC verdict RUN_ERROR -> `canonicalize_artefacts`
FAIL. Not a property of the design: it fires for ANY design on this PDK.

Falsified on the real artefacts, same recipe, only the six unused reads removed:
yosys rc 1 -> rc 0, "Equivalence successfully proven!", 429/429 $equiv cells.

These tests drive `_blackbox_scope_to_netlists` directly with FILE CONTENT, so
they need no container and no PDK install.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402

# Real shapes, trimmed. The SRAM header is the one that kills yosys.
_SRAM_BB = """(* blackbox *)
module gf180mcu_fd_ip_sram__sram128x8m8wm1 (
\tCLK, CEN, GWEN, WEN, A, D, Q
);
input CLK;
inout\t\tVDD;
inout\t\tVSS;
endmodule
"""
_IO_BB = """(* blackbox *)
module gf180mcu_fd_io__bi_t (A);
input A;
endmodule
"""
_SRAM_P = "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/s__blackbox.v"
_IO_P = "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/verilog/io__blackbox.v"
_HITS = [_IO_P, _SRAM_P]
_BY_PATH = {_IO_P: _IO_BB, _SRAM_P: _SRAM_BB}


def _netlist(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text("module spm (input clk);\n" + body + "endmodule\n")
    return p


def _scoped(monkeypatch, netlists, notes=None):
    monkeypatch.setattr(p3, "_read_pdk_text",
                        lambda path, container=None: _BY_PATH.get(path))
    return p3._blackbox_scope_to_netlists(list(_HITS), "c", netlists, notes)


def test_subject_unused_families_are_dropped(tmp_path, monkeypatch):
    """SUBJECT: a std-cell-only netlist keeps NEITHER file."""
    nl = _netlist(tmp_path, "gate.v",
                  "  gf180mcu_fd_sc_mcu7t5v0__nand2_1 _1_ (.A(clk));\n"
                  "  gf180mcu_fd_sc_mcu7t5v0__filltie _2_ (.A(clk));\n")
    notes: list = []
    assert _scoped(monkeypatch, [nl], notes) == []
    assert notes and "skipped 2 PDK blackbox file(s)" in notes[0]


def test_control_a_needed_family_is_never_dropped(tmp_path, monkeypatch):
    """CONTROL -- the input the fix must NOT change.

    A netlist that DOES instantiate an io cell must keep the io blackbox. The
    assertion is CONTAINMENT, not equality, so it is green on BOTH sides of the
    fix -- pre-fix keeps it among everything, post-fix keeps it because it is
    needed -- and goes red only for an over-broad fix. Without it, a bare
    `return []` satisfies the subject case."""
    nl = _netlist(tmp_path, "gate.v",
                  "  gf180mcu_fd_sc_mcu7t5v0__nand2_1 _1_ (.A(clk));\n"
                  "  gf180mcu_fd_io__bi_t pad0 (.A(clk));\n")
    assert _IO_P in _scoped(monkeypatch, [nl])


def test_gold_netlist_also_counts(tmp_path, monkeypatch):
    """Both sides of the equivalence are scanned, not just the gate."""
    gate = _netlist(tmp_path, "gate.v",
                    "  gf180mcu_fd_sc_mcu7t5v0__nand2_1 _1_ (.A(clk));\n")
    gold = _netlist(tmp_path, "gold.v",
                    "  gf180mcu_fd_io__bi_t pad0 (.A(clk));\n")
    assert _IO_P in _scoped(monkeypatch, [gate, gold])


def test_degrades_to_the_full_set_when_no_netlist_is_readable(monkeypatch):
    """No evidence to narrow with -> pre-fix behaviour, never a smaller set."""
    assert _scoped(monkeypatch, [Path("/nonexistent/gate.v")]) == _HITS


def test_degrades_when_a_blackbox_file_cannot_be_read(tmp_path, monkeypatch):
    """An unreadable blackbox file is KEPT: it cannot be judged."""
    nl = _netlist(tmp_path, "gate.v",
                  "  gf180mcu_fd_sc_mcu7t5v0__nand2_1 _1_ (.A(clk));\n")
    monkeypatch.setattr(p3, "_read_pdk_text",
                        lambda path, container=None:
                        None if path == _SRAM_P else _BY_PATH.get(path))
    assert _SRAM_P in p3._blackbox_scope_to_netlists(
        list(_HITS), "c", [nl], None)


def test_a_file_declaring_no_module_is_kept(tmp_path, monkeypatch):
    """Nothing to match on -> keep, rather than silently drop a needed model."""
    nl = _netlist(tmp_path, "gate.v",
                  "  gf180mcu_fd_sc_mcu7t5v0__nand2_1 _1_ (.A(clk));\n")
    monkeypatch.setattr(p3, "_read_pdk_text",
                        lambda path, container=None:
                        "// no module here\n" if path == _SRAM_P
                        else _BY_PATH.get(path))
    assert _SRAM_P in p3._blackbox_scope_to_netlists(
        list(_HITS), "c", [nl], None)


def test_discover_without_netlists_is_unchanged(monkeypatch):
    """The legacy 2-arg call keeps its exact meaning: no scoping applied."""
    monkeypatch.setattr(p3, "_container_ls_paths",
                        lambda c, e, m, timeout=20: list(_HITS))

    class _Pdk:
        tech_lef = "/foss/pdks/gf180mcuD/libs.ref/x/techlef/y.tlef"
    assert p3._discover_blackbox_verilog(_Pdk(), "c") == _HITS
