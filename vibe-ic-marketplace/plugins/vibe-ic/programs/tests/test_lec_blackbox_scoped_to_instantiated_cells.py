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


# ── the scan must read CODE, not the license header ──────────────────────────
#
# `_BLACKBOX_MODULE_RE` is `(?m)^\s*module\s+(...)` and `\s` spans NEWLINES, so
# a line inside a `/* ... */` header matches exactly as a declaration does. A
# PDK blackbox file opens with one. When that header narrates the cell the file
# holds -- and it is the file's own cell it narrates -- the phantom name equals
# a name the netlist may instantiate, `mods & instantiated` is true for a file
# the netlist never uses, and the narrowing above silently reverts to the
# pre-v1.12.74 behaviour that returned RUN_ERROR for every design on this PDK.
#
# Each case below is PAIRED with the same file minus the comment, so a "fix"
# that simply dropped more files cannot pass both.

_SRAM_BB_COMMENTED = """/*
 * Copyright 2022 GlobalFoundries PDK Authors. Apache License 2.0.
 *
 * This file provides the blackbox for
 module gf180mcu_fd_io__bi_t
 * which callers should not instantiate directly.
 */
(* blackbox *)
module gf180mcu_fd_ip_sram__sram128x8m8wm1 (CLK);
input CLK;
endmodule
"""


def test_subject_a_cell_named_only_in_a_license_header_does_not_keep_the_file(
        tmp_path, monkeypatch):
    """SUBJECT: prose ABOUT a cell is not that cell being declared.

    The netlist instantiates `gf180mcu_fd_io__bi_t`. The SRAM file DECLARES
    only the SRAM, and mentions the io cell in its header comment. Reading the
    raw text mints the io cell as an SRAM-file declaration and the file is
    kept -- which is the malformed file coming back."""
    nl = _netlist(tmp_path, "gate.v",
                  "  gf180mcu_fd_io__bi_t pad0 (.A(clk));\n")
    monkeypatch.setattr(p3, "_read_pdk_text",
                        lambda path, container=None:
                        _SRAM_BB_COMMENTED if path == _SRAM_P
                        else _BY_PATH.get(path))
    kept = p3._blackbox_scope_to_netlists(list(_HITS), "c", [nl], None)
    assert _SRAM_P not in kept, (
        "a cell named only inside a /* */ header kept a file the netlist never "
        f"instantiates -- the comment was read as a declaration. kept={kept}")
    assert _IO_P in kept, "the file that really declares the cell must be kept"


def test_control_the_same_cell_DECLARED_still_keeps_the_file(
        tmp_path, monkeypatch):
    """CONTROL -- the pair. Same cell name, same file, declared instead of
    narrated. It must be kept. This is what stops the subject above from being
    satisfied by a fix that has gone blind to real declarations."""
    declared = _SRAM_BB_COMMENTED.replace(
        " module gf180mcu_fd_io__bi_t\n", " the SRAM macro\n").replace(
        "module gf180mcu_fd_ip_sram__sram128x8m8wm1 (CLK);",
        "module gf180mcu_fd_io__bi_t (CLK);")
    assert "\nmodule gf180mcu_fd_io__bi_t (CLK);" in declared
    nl = _netlist(tmp_path, "gate.v",
                  "  gf180mcu_fd_io__bi_t pad0 (.A(clk));\n")
    monkeypatch.setattr(p3, "_read_pdk_text",
                        lambda path, container=None:
                        declared if path == _SRAM_P else _BY_PATH.get(path))
    assert _SRAM_P in p3._blackbox_scope_to_netlists(
        list(_HITS), "c", [nl], None), (
        "a REAL declaration below a comment was lost -- stripping has blinded "
        "the scan rather than sharpened it")


def test_a_file_whose_ONLY_module_is_commented_out_is_treated_as_declaring_none(
        tmp_path, monkeypatch):
    """The `no module -> keep` degrade must be reached through the comment.

    Pre-fix this file "declares" a module and is dropped; post-fix it declares
    none, and the documented degrade (cannot judge -> keep) applies."""
    nl = _netlist(tmp_path, "gate.v",
                  "  gf180mcu_fd_sc_mcu7t5v0__nand2_1 _1_ (.A(clk));\n")
    monkeypatch.setattr(p3, "_read_pdk_text",
                        lambda path, container=None:
                        "/*\nmodule retired_cell (A);\nendmodule\n*/\n"
                        if path == _SRAM_P else _BY_PATH.get(path))
    assert _SRAM_P in p3._blackbox_scope_to_netlists(
        list(_HITS), "c", [nl], None)
