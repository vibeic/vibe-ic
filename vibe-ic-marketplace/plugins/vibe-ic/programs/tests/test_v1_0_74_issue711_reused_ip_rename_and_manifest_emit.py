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
import ip_catalog_pull as IPC  # noqa: E402


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
def _run_pull_emit(project: Path, audits):
    """Drive ONLY the manifest-emit half of pull_all_catalog_matches by calling
    it with a monkeypatched pull_catalog_ip that returns canned audits."""
    import unittest.mock as mock
    matches = [object() for _ in audits]  # opaque; pull_catalog_ip is patched
    it = iter(audits)
    with mock.patch.object(IPC, "pull_catalog_ip",
                           side_effect=lambda m, p: next(it)):
        IPC.pull_all_catalog_matches(project, matches)


def test_source_manifest_emitted_on_pull(tmp_path):
    """END-STATE: a successful catalog pull writes phase2/stage1/rtl/
    SOURCE_MANIFEST.json{reused_ip:true, ip_list:[...]} — the keystone the gate
    relaxations read."""
    _run_pull_emit(tmp_path, [
        {"ip_name": "serv", "status": "PASS", "license": "Apache-2.0"},
        {"ip_name": "shared_sram_rf", "status": "PARTIAL", "license": "Apache-2.0"},
    ])
    mf_path = tmp_path / "phase2" / "stage1" / "rtl" / "SOURCE_MANIFEST.json"
    assert mf_path.is_file()
    mf = json.loads(mf_path.read_text())
    assert mf["reused_ip"] is True
    assert mf["ip_list"] == ["serv", "shared_sram_rf"]
    # the gate's loader accepts it (reused_ip=true gate)
    assert G.load_source_manifest(tmp_path) is not None


def test_manifest_emit_merge_preserving(tmp_path):
    """§4.05: emission MERGES — a hand-authored tie_offs / renamed_interfaces
    block is preserved, not clobbered."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps({
        "reused_ip": True,
        "tie_offs": ["edn_i"],
        "renamed_interfaces": [{"l9": ["o_sram_addr"], "rtl": ["o_sram_waddr"]}],
    }))
    _run_pull_emit(tmp_path, [
        {"ip_name": "serv", "status": "PASS", "license": "Apache-2.0"}])
    mf = json.loads((rtl / "SOURCE_MANIFEST.json").read_text())
    assert mf["ip_list"] == ["serv"]
    assert mf["tie_offs"] == ["edn_i"]                # preserved
    assert mf["renamed_interfaces"][0]["rtl"] == ["o_sram_waddr"]  # preserved


def test_manifest_not_emitted_when_no_ip_pulled(tmp_path):
    """§4.05: if every IP was REJECTED/FAILED (none pulled), NO manifest is
    written — we never assert reused_ip=true on a design with no integrated IP."""
    _run_pull_emit(tmp_path, [
        {"ip_name": "x", "status": "REJECTED", "reason": "license"}])
    mf_path = tmp_path / "phase2" / "stage1" / "rtl" / "SOURCE_MANIFEST.json"
    assert not mf_path.is_file()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
