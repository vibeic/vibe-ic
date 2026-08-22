#!/usr/bin/env python3
"""vibe-ic — a sky130 cell was the clock-buffer default for every PDK (#561).

Two instances of that issue's shape — a text or default proxy standing in for the
property being checked — sat three lines apart in `step_pnr`:

    clk_buf = pdk.clk_buf or "sky130_fd_sc_hd__clkbuf_4"
    ...
    if pdk.clk_buf is None and pdk.name.startswith("custom"):
        ... scan the Liberty for CLKBUF / BUF ...

`clk_buf` comes from `reg.get("clk_buf_cell")`, so a PDK added without that key
gets a cell that exists in no other library — and the recovery that would have
found the real one was gated on the PDK's NAME.

The block is exercised by extracting and executing it, because it lives inside a
900-line function that needs a container, a netlist and a floorplan to call. The
extraction is anchored on source markers that this test asserts still exist, so a
refactor that moves the block fails here rather than silently testing nothing.
"""
from __future__ import annotations

import pathlib
import sys
import textwrap

import pytest

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

_SRC = (PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
_BEGIN = "    clk_buf = pdk.clk_buf\n"
_END = "    pnr_tcl = out_dir /"


def _block() -> str:
    assert _SRC.count(_BEGIN) == 1, "the clk_buf block moved; this test is blind"
    assert _SRC.count(_END) == 1, "the end anchor moved; this test is blind"
    return textwrap.dedent(_SRC[_SRC.index(_BEGIN):_SRC.index(_END)])


class _Pdk:
    def __init__(self, name, clk_buf=None, clk_buf_root=None, liberty="/nonexistent"):
        self.name = name
        self.clk_buf = clk_buf
        self.clk_buf_root = clk_buf_root
        self.liberty = liberty


def _run(pdk):
    ns = {"pdk": pdk, "Path": pathlib.Path, "List": list, "sys": sys}
    exec(_block(), ns)          # noqa: S102 - executing the block under test
    return ns


def test_a_registry_pdk_keeps_its_own_cell():
    ns = _run(_Pdk("gf180mcuD", clk_buf="gf180mcu_fd_sc_mcu7t5v0__clkbuf_4"))
    assert ns["clk_buf"] == "gf180mcu_fd_sc_mcu7t5v0__clkbuf_4"
    assert ns["_clk_buf_note"] == "", "a resolved PDK must not carry a guess note"


def test_a_pdk_without_a_clk_buf_is_not_silently_given_sky130s():
    """THE defect. Before the fix this returned the sky130 cell with nothing said,
    on a PDK whose Liberty does not contain it."""
    ns = _run(_Pdk("ihp-sg13g2"))
    assert "sky130" in ns["clk_buf"]
    assert ns["_clk_buf_note"], "the guess was made silently"
    assert "UNRESOLVED" in ns["_clk_buf_note"]
    assert "ihp-sg13g2" in ns["_clk_buf_note"], "the note must name the PDK"


def test_the_note_says_what_will_go_wrong():
    """A disclosure a reader cannot act on gets skimmed. This one names the
    consequence: CTS will ask for a cell the library does not contain."""
    note = _run(_Pdk("ihp-sg13g2"))["_clk_buf_note"]
    assert "CTS" in note and "does not contain" in note


def test_the_liberty_scan_is_no_longer_gated_on_the_pdk_NAME(tmp_path):
    """The second proxy. A non-registry PDK not named `custom*` used to skip the
    scan entirely; now the scan is what decides, so a PDK called anything at all
    resolves its own cell."""
    lib = tmp_path / "x.lib"
    lib.write_text(
        "library (x) {\n"
        "  cell (foo_clkbuf_1) { }\n"
        "  cell (foo_clkbuf_8) { }\n"
        "}\n", encoding="utf-8")
    ns = _run(_Pdk("acme_130nm", liberty=str(lib)))   # NOT named custom*
    assert ns["clk_buf"] == "foo_clkbuf_1", ns["clk_buf"]
    assert ns["clk_buf_root"] == "foo_clkbuf_8", ns["clk_buf_root"]
    assert ns["_clk_buf_note"] == "", "a scan that succeeded must not warn"


def test_a_custom_named_pdk_still_scans(tmp_path):
    """The path that always worked must keep working — the gate was removed, not
    inverted."""
    lib = tmp_path / "x.lib"
    lib.write_text("library (x) {\n  cell (BUFX2) { }\n}\n", encoding="utf-8")
    ns = _run(_Pdk("custom_auto_detect", liberty=str(lib)))
    assert ns["clk_buf"] == "BUFX2"


def test_an_unreadable_liberty_falls_back_and_says_so():
    """The scan is wrapped in `except Exception: pass`, so a missing Liberty must
    reach the disclosed guess rather than crash the PnR step."""
    ns = _run(_Pdk("acme_130nm", liberty="/no/such/file.lib"))
    assert "sky130" in ns["clk_buf"] and ns["_clk_buf_note"]


def test_the_root_buffer_never_stays_none():
    """`clk_buf_root` is emitted into the TCL; a None there would render as the
    string 'None' and CTS would ask for a cell by that name."""
    for pdk in (_Pdk("gf180mcuD", clk_buf="x__clkbuf_4"),
                _Pdk("ihp-sg13g2"),
                _Pdk("acme", liberty="/no/such/file.lib")):
        ns = _run(pdk)
        assert ns["clk_buf_root"], f"{pdk.name}: root buffer unset"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
