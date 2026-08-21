#!/usr/bin/env python3
"""v0.2.95 — #467: foundry handoff must read populated upstream facts.

The audited rot: foundry_handoff_pack_gen wrote design_top='chip_top',
pdk=null, process_node_nm=null even when the upstream spec docs already
carried those facts:
  * L1_DATASHEET.json[ic_name]                  → the real design top;
  * L19_CONSTRAINTS_PDK.json[fields][pdk_target]→ the target PDK;
  * L1_DATASHEET.json[tapeout_metadata]         → fallback PDK statement.

Pins the 建議修法 fallback chains:
  design_top  <- L1 ic_name → --top argument → RTL-derived top (legacy);
  pdk         <- L19 pdk_target → L1 tapeout PDK statement → PDK files;
  process_nm  <- PDK-file derivation → node parsed from the spec PDK text.

CORPUS-SWEEP guard: a project genuinely missing every upstream value
still gets an honest null (no fabrication). PENDING_FOUNDRY_* unchanged.

chip-AGNOSTIC: synthetic fixtures with generic names.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import foundry_handoff_pack_gen as FH  # noqa: E402


def _gen_docs(project: Path) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_l1(project: Path, ic_name=None, tapeout_metadata=None):
    payload = {}
    if ic_name is not None:
        payload["ic_name"] = ic_name
    if tapeout_metadata is not None:
        payload["tapeout_metadata"] = tapeout_metadata
    (_gen_docs(project) / "L1_DATASHEET.json").write_text(
        json.dumps(payload))


def _write_l19(project: Path, pdk_target=None):
    (_gen_docs(project) / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": {"pdk_target": pdk_target}}))


def _mask(project: Path) -> dict:
    return json.loads(
        (project / "phase3/stage4/foundry_handoff/mask_spec.json").read_text())


def _audit(project: Path) -> dict:
    return json.loads(
        (project / "reports/phase3/foundry_handoff_audit.json").read_text())


# ─────────────────────────── the fixed path ────────────────────────────

def test_design_top_from_l1_ic_name(tmp_path):
    """L1 ic_name populated → design_top is that name, NOT 'chip_top'."""
    p = tmp_path / "proj"
    _write_l1(p, ic_name="acme_crypto_core")
    assert FH.main([str(p)]) == 0
    assert _mask(p)["design_top"] == "acme_crypto_core"
    assert _audit(p)["design_facts"]["top"] == "acme_crypto_core"


def test_pdk_from_l19_pdk_target(tmp_path):
    """L19 pdk_target populated → pdk is that value, NOT null."""
    p = tmp_path / "proj"
    _write_l19(p, pdk_target="examplepdk130")
    assert FH.main([str(p)]) == 0
    m = _mask(p)
    assert m["pdk"] == "examplepdk130"
    assert _audit(p)["design_facts"]["pdk"] == "examplepdk130"


def test_process_node_parsed_from_l19_pdk_target(tmp_path):
    """No PDK files, but L19 names a node → process_node_nm derived."""
    p = tmp_path / "proj"
    _write_l19(p, pdk_target="generic 130nm bulk CMOS")
    FH.main([str(p)])
    assert _mask(p)["process_node_nm"] == 130


def test_pdk_falls_back_to_l1_tapeout_metadata(tmp_path):
    """No L19 pdk_target → L1 tapeout_metadata's foundry/process statement."""
    p = tmp_path / "proj"
    _write_l1(p, tapeout_metadata={"foundry": "ExampleFab", "process_node": "0.18um"})
    FH.main([str(p)])
    m = _mask(p)
    assert m["pdk"] == "ExampleFab"          # foundry preferred over node
    assert m["process_node_nm"] == 180       # 0.18um -> 180nm


def test_l19_pdk_target_wins_over_l1_tapeout(tmp_path):
    """Both present → L19 pdk_target wins (issue's primary source)."""
    p = tmp_path / "proj"
    _write_l19(p, pdk_target="primary_pdk")
    _write_l1(p, tapeout_metadata={"foundry": "fallback_fab"})
    FH.main([str(p)])
    assert _mask(p)["pdk"] == "primary_pdk"


def test_design_top_falls_back_to_top_arg(tmp_path):
    """L1 ic_name is the not-found sentinel → --top argument used."""
    p = tmp_path / "proj"
    _write_l1(p, ic_name="UNKNOWN_IC")
    assert FH.main([str(p), "--top", "supplied_top"]) == 0
    assert _mask(p)["design_top"] == "supplied_top"


def test_l1_ic_name_wins_over_top_arg(tmp_path):
    """Real ic_name pre-empts the --top fallback."""
    p = tmp_path / "proj"
    _write_l1(p, ic_name="real_top")
    FH.main([str(p), "--top", "supplied_top"])
    assert _mask(p)["design_top"] == "real_top"


def test_pdk_files_used_when_no_spec_facts(tmp_path):
    """No L19/L1 PDK facts, but PDK liberty present → derived from files
    (prior #446 behaviour preserved)."""
    p = tmp_path / "proj"
    lib = p / "input" / "pdk" / "liberty"
    lib.mkdir(parents=True)
    (lib / "examplepdk_sc_hd__tt_025C_130.lib").write_text("library(x){}")
    FH.main([str(p)])
    m = _mask(p)
    assert m["pdk"] == "examplepdk_sc_hd"
    assert m["process_node_nm"] == 130


# ──────────────────────── corpus-sweep regression guard ─────────────────

def test_honest_null_when_all_upstream_empty(tmp_path):
    """CORPUS-SWEEP guard: no L1 ic_name, no L19 pdk_target, no tapeout
    metadata, no PDK files → pdk/process_node_nm stay null (NOT fabricated)
    and design_top falls to the legacy RTL default. PENDING_FOUNDRY_*
    semantics unchanged."""
    p = tmp_path / "proj"
    p.mkdir()  # project ran the flow but carries no upstream PDK/name facts
    assert FH.main([str(p)]) == 0
    m = _mask(p)
    assert m["pdk"] is None
    assert m["process_node_nm"] is None
    assert m["design_top"] == "chip_top"      # legacy honest default
    # #449 namespace unchanged
    assert "PENDING_FOUNDRY_mask_layers" in m
    assert not any(k.startswith("TODO_") for k in m)


def test_sentinel_ic_name_does_not_block_null(tmp_path):
    """ic_name='UNKNOWN_IC' with no --top and no RTL → honest legacy
    default, NOT the literal sentinel string."""
    p = tmp_path / "proj"
    _write_l1(p, ic_name="UNKNOWN_IC")
    FH.main([str(p)])
    assert _mask(p)["design_top"] == "chip_top"


def test_empty_l19_pdk_target_keeps_null(tmp_path):
    """pdk_target=null in L19 must not be treated as a populated value."""
    p = tmp_path / "proj"
    _write_l19(p, pdk_target=None)
    FH.main([str(p)])
    assert _mask(p)["pdk"] is None
