#!/usr/bin/env python3
"""Tests for pdk_udp_synth_shim_gen.py — foundry UDP → synth shim.

Pins the REAL transform behavior (the silicon bug it fixes: a
specify-only / NOTIFIER-only library that simulates as "Q stays X" in
iverilog and "Stuck at GND" in Quartus):
  * PASS — a `primitive udp_dff ... endprimitive` becomes a synthesisable
    `module udp_dff (...) ... endmodule` whose ports are byte-identical;
    `specify` blocks are stripped; `reg NOTIFIER;` becomes `supply0`.
  * dwire-assign insertion — `wire dX;` driven only by $setuphold gets a
    continuous `assign dX = X;` so X is no longer floating.
  * unknown-UDP handling — an unknown primitive is preserved as a
    PASS-THROUGH by default, or scaffolded with --scaffold-unknown, and
    is recorded in the --unknowns-json report.
  * Edge — main() exit code 0 on success; output header records counts.

Runs through main(argv) like the CLI; chip-AGNOSTIC.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "pdk_udp_synth_shim_gen.py"

_spec = importlib.util.spec_from_file_location("pdk_udp_synth_shim_gen", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# A known UDP (udp_dff) with a specify block + NOTIFIER reg.
_KNOWN_LIB = """\
`celldefine
primitive udp_dff (out, in, clk, clr_, set_, NOTIFIER);
  output out;
  input  in, clk, clr_, set_, NOTIFIER;
  reg    out;
  table
    // truth table omitted for the test
  endtable
endprimitive
`endcelldefine

module DFF_CELL (Q, D, CK, RB, SB);
  output Q;
  input  D, CK, RB, SB;
  wire   dD;
  reg    NOTIFIER;
  udp_dff u0 (Q, dD, CK, RB, SB, NOTIFIER);
  specify
    $setuphold(posedge CK, dD, 0, 0, NOTIFIER);
  endspecify
endmodule
"""


def _run(tmp_path, src, extra=None, unknowns_json=False):
    in_v = tmp_path / "lib.v"
    out_v = tmp_path / "shim.v"
    in_v.write_text(src)
    argv = [str(in_v), str(out_v)]
    if extra:
        argv += extra
    uj = None
    if unknowns_json:
        uj = tmp_path / "unknowns.json"
        argv += ["--unknowns-json", str(uj)]
    rc = mod.main(argv)
    return rc, out_v, uj


# ----------------------------------------------------------------------
# PASS — known UDP rewritten + specify stripped + NOTIFIER tied
# ----------------------------------------------------------------------
def test_known_udp_becomes_module_specify_stripped(tmp_path):
    rc, out_v, _ = _run(tmp_path, _KNOWN_LIB)
    assert rc == 0
    text = out_v.read_text()
    # The primitive is gone; the synth module body is present.
    assert "primitive udp_dff" not in text
    assert "module udp_dff (out, in, clk, clr_, set_, NOTIFIER);" in text
    # specify timing block removed entirely.
    assert "specify" not in text
    assert "$setuphold" not in text
    # `reg NOTIFIER;` rewritten to a low-tied supply0.
    assert "reg    NOTIFIER;" not in text
    assert "supply0 NOTIFIER;" in text


def test_dwire_assign_inserted(tmp_path):
    """`wire dD;` was driven only via the now-removed $setuphold; the
    shim must add `assign dD = D;` so D is no longer floating (the real
    'Q stays X' fix)."""
    rc, out_v, _ = _run(tmp_path, _KNOWN_LIB)
    assert rc == 0
    text = out_v.read_text()
    assert "assign dD = D;" in text


def test_header_records_primitive_count(tmp_path):
    rc, out_v, _ = _run(tmp_path, _KNOWN_LIB)
    assert rc == 0
    text = out_v.read_text()
    assert "Primitives encountered: 1" in text
    assert "Specify blocks stripped: 1" in text


# ----------------------------------------------------------------------
# unknown-UDP handling — the real "needs human truth table" path
# ----------------------------------------------------------------------
_UNKNOWN_LIB = """\
primitive udp_weird_cell (out, a, b);
  output out;
  input  a, b;
  table
    0 0 : 1;
  endtable
endprimitive
"""


def test_unknown_udp_passthrough_by_default(tmp_path):
    rc, out_v, _ = _run(tmp_path, _UNKNOWN_LIB)
    assert rc == 0
    text = out_v.read_text()
    # default: preserved as a PASS-THROUGH (no synth template).
    assert "PASS-THROUGH (no synth template for udp_weird_cell)" in text
    assert "Unknowns (need synth template): 1 ['udp_weird_cell']" in text


def test_unknown_udp_scaffold_mode(tmp_path):
    rc, out_v, _ = _run(tmp_path, _UNKNOWN_LIB, extra=["--scaffold-unknown"])
    assert rc == 0
    text = out_v.read_text()
    assert "SCAFFOLD: no synth template for udp_weird_cell" in text
    assert "module udp_weird_cell (out, a, b);" in text
    # PASS-THROUGH must NOT be emitted in scaffold mode.
    assert "PASS-THROUGH" not in text


def test_unknowns_json_report(tmp_path):
    rc, _out_v, uj = _run(tmp_path, _UNKNOWN_LIB, unknowns_json=True)
    assert rc == 0
    report = json.loads(uj.read_text())
    assert report["unknown_count"] == 1
    assert report["unknowns"][0]["name"] == "udp_weird_cell"
    assert "raw_snippet" in report["unknowns"][0]


# ----------------------------------------------------------------------
# helper-level pin — UDP_SYNTH catalog ports match the source header
# ----------------------------------------------------------------------
def test_udp_synth_catalog_is_synthesisable_module():
    """Every catalog entry is a `module ... endmodule` (not a primitive),
    so the shim never re-emits non-synthesisable UDP idioms."""
    assert "udp_dff" in mod.UDP_SYNTH
    for name, body in mod.UDP_SYNTH.items():
        assert body.startswith(f"module {name} ")
        assert body.rstrip().endswith("endmodule")
        assert "primitive" not in body
