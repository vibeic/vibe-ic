"""ORGANIC #711 — reused-IP interface RENAME reconcile gap + ip_catalog_pull
never emits SOURCE_MANIFEST.json.

DEFECT (round-10 v1.0.73 6-IC clean-room; bit-serial RISC-V catalog-glue SoC):
  (part 1) ip_catalog_pull.py writes plugin_output/declaration.json but NEVER
  phase2/stage1/rtl/SOURCE_MANIFEST.json — yet l9_rtl_pin_consistency_check /
  flow_compliance read ONLY the manifest. So no program emitted the file the
  reused-IP relaxations key on → the relaxations were dead code and every
  catalog-glue SoC hard-FAILed or needed a per-run waiver.
  (part 2) reconcile_reused_ip had only prefix-expansion + structural tie-off —
  a spec-permitted RENAMED interface (L9 typical `o_sram_addr/o_sram_data/
  o_sram_we` vs RTL split `o_sram_waddr/o_sram_raddr/o_sram_wdata/o_sram_wen/
  o_sram_ren`) cannot reconcile (a rename is not a prefix).

FIX (chip-AGNOSTIC):
  (1) pull_all_catalog_matches emits SOURCE_MANIFEST.json{reused_ip:true,
      ip_list:[...]} (merge-preserving) when ≥1 IP was pulled.
  (2) reconcile_reused_ip honours a manifest `renamed_interfaces:[{l9:[...],
      rtl:[...]}]` declaration: declared L9 names → advisory tie_off, declared
      RTL names → dropped from residual_rtl.

§4.05 NO-LEAK: an UNDECLARED rename still FAILs; the manifest emit only sets
  reused_ip=true when an IP was actually pulled and never clobbers a hand-
  authored tie_offs/flattened_buses block.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l9_rtl_pin_consistency_check as G  # noqa: E402


# ── part 2: RENAME reconcile ────────────────────────────────────────────────
_RENAME_MF = {
    "reused_ip": True,
    "renamed_interfaces": [{
        "l9": ["o_sram_addr", "o_sram_data", "o_sram_we"],
        "rtl": ["o_sram_waddr", "o_sram_raddr", "o_sram_wdata",
                "o_sram_wen", "o_sram_ren"],
    }],
}


def test_rename_reconcile_declared():
    """END-STATE: a manifest-declared renamed interface reconciles BOTH sides —
    the L9 illustrative names leave residual_l9 (advisory tie_off) and the RTL
    split names leave residual_rtl."""
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        ["o_sram_addr", "o_sram_data", "o_sram_we"],
        ["o_sram_waddr", "o_sram_raddr", "o_sram_wdata",
         "o_sram_wen", "o_sram_ren"],
        _RENAME_MF)
    assert res_l9 == [], res_l9
    assert res_rtl == [], res_rtl
    assert set(tied) == {"o_sram_addr", "o_sram_data", "o_sram_we"}
    assert any(lbl == "(renamed-interface)" for lbl, _ in pm)


def test_rename_noleak_undeclared_still_fails():
    """§4.05: an UNDECLARED rename (manifest has no renamed_interfaces) still
    surfaces both sides as residual FAILs."""
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        ["o_sram_addr"], ["o_sram_waddr"], {"reused_ip": True})
    assert res_l9 == ["o_sram_addr"]
    assert res_rtl == ["o_sram_waddr"]


def test_rename_noleak_partial_declaration():
    """§4.05: only the EXACT declared names reconcile — an RTL port outside the
    declared group still FAILs."""
    res_l9, res_rtl, tied, pm = G.reconcile_reused_ip(
        ["o_sram_addr", "o_sram_data", "o_sram_we"],
        ["o_sram_waddr", "o_sram_raddr", "o_sram_wdata",
         "o_sram_wen", "o_sram_ren", "o_undeclared_x"],
        _RENAME_MF)
    assert res_rtl == ["o_undeclared_x"], res_rtl


# ── part 1: SOURCE_MANIFEST emission ────────────────────────────────────────


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
