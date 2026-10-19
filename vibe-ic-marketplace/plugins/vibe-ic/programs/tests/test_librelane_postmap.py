"""Neutral transport fixtures, not EDA measurements. Native campaign is separate.

Parent synthesis is an admitted-fixture dependency. Child receipt, statistics,
selection and ordinary consumer refusal execute their real implementations.
"""
from pathlib import Path
import json
import pytest
import _plugin_tree  # noqa: F401
import librelane_contract as LC
import librelane_postmap as M
import synth_handoff_netlist_check as H
import synth_netlist_check as N
import phase3_one_shot_runner as R


def put(p, j):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(j) + "\n")
    return p


def fixture(tmp_path, monkeypatch):
    p = tmp_path / "project"
    put(p / "phase1/generated_docs/L9_INTEGRATION_SPEC.json", {"top_module": "top"})
    put(p / "phase3/librelane_switch.json", {"steps": {"9": "librelane"}, "post_map_repair": "pre_placement"})
    parent_folder = p / "phase3/librelane/02-yosys-synthesis"
    parent = parent_folder / "top.nl.v"
    parent.parent.mkdir(parents=True)
    parent.write_text("module top(input a, output y); BUF a0(.A(a),.Y(y)); endmodule\n")
    put(parent_folder / "state_out.json", {"nl": str(parent)})
    put(parent_folder / "vibeic_receipt.json", {"input": {"image": "tool"}})
    folder = p / "phase3/librelane/postmap/01-vibeic-postmaprepair"
    native = folder / "top.nl.v"; native.parent.mkdir(parents=True)
    native.write_text("module top(input a, output y); wire n; BUF b0(.A(a),.Y(n)); BUF b1(.A(n),.Y(y)); endmodule\n")
    source = p / "input/constraints/input.sdc"; source.parent.mkdir(parents=True)
    source.write_text("set_max_fanout 10 [current_design]\n")
    pdk = tmp_path / "pdk";pdk.mkdir();lib = pdk / "neutral.lib";lib.write_text("library(neutral){}\n")
    cfg = {"meta": {"step": M.STEP}, "DESIGN_NAME": "top", "PDK_ROOT": str(pdk),
           "PNR_SDC_FILE": str(source), "CELL_LIBS": {"c": [str(lib)]}}
    resolved = put(p / "phase3/librelane/postmap-config/resolved.json", cfg)
    sin = put(resolved.parent / "state_in.json", {"nl": str(parent)})
    fp = {"step": M.STEP, "image": "tool", "config": LC.digest(resolved), "state": LC.digest(sin),
          "state_files": {str(parent): LC.digest(parent)}, "config_files": LC.config_file_hashes(cfg, []),
          "plugin": LC._plugin_digests(M.STEP)}
    put(folder / "input_fingerprint.json", fp)
    put(folder / "config.json", cfg)
    put(folder / "pdk_root.json", {"cli_pdk_root": str(pdk), "mounts_under_it": [], "stated_by": "run_chain(pdk_root=...)"})
    put(folder / "state_out.json", {"nl": str(native), "metrics": {"design__instance__count": 2, "design__instance__area": 2.0}})
    put(folder / "reports/stat.json", {"modules": {"top": {"num_cells": 2, "area": 2.0}}})
    put(folder / "postmap.json", {"input_sha256": LC.digest(parent), "output_sha256": LC.digest(native)})
    (folder / "invocation.log").write_text("neutral native-transport fixture only\n")
    put(folder / "vibeic_receipt.json", {"input": fp, "sha256": {str(q.relative_to(folder)): LC.digest(q)
        for q in folder.rglob("*") if q.is_file()}})
    mapped = p / "phase2/stage2/synth/top_synth.v"; mapped.parent.mkdir(parents=True)
    mapped.write_bytes(native.read_bytes()); (mapped.parent / "netlist.v").write_bytes(native.read_bytes())
    stats = put(mapped.parent / "stats.json", {"cell_count": 2, "chip_area": 2.0, "netlist_sha256": "sha256:" + LC.digest(native)})
    child = {"schema": M.SCHEMA, "folder": str(folder.relative_to(p)), "resolved_config": str(resolved.relative_to(p)),
             "state_in": str(sin.relative_to(p)), "parent_sha256": LC.digest(parent), "netlist_sha256": LC.digest(native),
             "receipt_sha256": LC.digest(folder / "vibeic_receipt.json"), "stats_sha256": LC.digest(stats), "basis": M.basis(p)}
    binding = {"schema": "vibe-ic/librelane-synthesis-handoff/1", "folder": str(parent_folder.relative_to(p)),
               "mapped": str(mapped.relative_to(p)), "top": "top", "netlist_sha256": LC.digest(native),
               "receipt_sha256": LC.digest(parent_folder / "vibeic_receipt.json"), "post_map": child}
    sidecar = put(mapped.parent / "synth_inputs.json", {"netlist": mapped.name, "librelane_synthesis": binding})
    monkeypatch.setattr(H, "_native_synthesis", lambda *a, **k: (k.get("path_resolver", lambda x: Path(x))(str(parent)), {"SYNTH_TIEHI_CELL":"TIEH/Y", "SYNTH_TIELO_CELL":"TIEL/Y"}, {"verdict": "PASS", "findings": []}))
    return p, parent, native, mapped, folder, source, lib, stats, sidecar


def test_same_product_reaches_native_copy_and_pnr(tmp_path, monkeypatch):
    p, parent, native, mapped, *_ = fixture(tmp_path, monkeypatch)
    report = H.bound_handoff(p)
    assert report["verdict"] == "PASS", report
    assert report["native"] == str(native)
    assert report["parent"] == str(parent)
    assert N.tool_emitted_netlist(mapped.parent / "netlist.v") == native
    assert R.pnr_input_netlist(p, "top")[0] == mapped
    assert parent.read_bytes() != mapped.read_bytes()


@pytest.mark.parametrize("damage", ["native", "mapped", "canonical", "parent", "source", "library", "stat", "missing_child", "mode_removed", "bad_mode", "code", "receipt", "state", "resolved", "observation"])
def test_stale_or_missing_child_refuses_and_restores(tmp_path, monkeypatch, damage):
    p, parent, native, mapped, folder, source, lib, stats, sidecar = fixture(tmp_path, monkeypatch)
    assert H.bound_handoff(p)["verdict"] == "PASS"
    target = {"native": native, "mapped": mapped, "canonical": mapped.parent / "netlist.v", "parent": parent,
              "source": source, "library": lib, "stat": stats, "receipt": folder / "vibeic_receipt.json",
              "state": p / "phase3/librelane/postmap-config/state_in.json",
              "resolved": p / "phase3/librelane/postmap-config/resolved.json", "observation": folder / "postmap.json"}.get(damage)
    if target:
        original = target.read_bytes(); target.write_bytes(original + b" ")
    elif damage in ("missing_child",):
        target = sidecar;original = target.read_bytes();doc = json.loads(original);del doc["librelane_synthesis"]["post_map"];put(target, doc)
    elif damage in ("mode_removed", "bad_mode"):
        target = p / "phase3/librelane_switch.json";original = target.read_bytes();doc = json.loads(original);doc["post_map_repair"] = "off" if damage == "mode_removed" else True;put(target, doc)
    else:
        real = LC._plugin_digests;monkeypatch.setattr(LC, "_plugin_digests", lambda *_: {})
    assert H.bound_handoff(p)["verdict"] == "FAIL", damage
    with pytest.raises(ValueError):
        R.pnr_input_netlist(p, "top")
    if target: target.write_bytes(original)
    else:monkeypatch.setattr(LC, "_plugin_digests", real)
    assert H.bound_handoff(p)["verdict"] == "PASS"


def test_published_stats_rehash_cannot_mask_wrong_native_count(tmp_path, monkeypatch):
    p, _, _, _, _, _, _, stats, sidecar = fixture(tmp_path, monkeypatch)
    x=json.loads(stats.read_text());x["cell_count"]=1;put(stats,x)
    doc=json.loads(sidecar.read_text());doc["librelane_synthesis"]["post_map"]["stats_sha256"]=LC.digest(stats);put(sidecar,doc)
    report=H.bound_handoff(p)
    assert report["verdict"] == "FAIL"
    assert "LL_STAT_MISMATCH" in str(report)


def test_no_request_retains_parent_selection(tmp_path):
    parent=tmp_path/"raw.v";parent.write_text("module top;endmodule\n")
    assert M.selected(tmp_path, {}, parent, tmp_path)==(parent,None)


def test_staged_reader_uses_issued_bytes_with_original_project_offline(tmp_path, monkeypatch):
    import shutil
    p, _, _, _, _, _, _, _, _ = fixture(tmp_path, monkeypatch)
    staged=tmp_path / "staged";shutil.copytree(p,staged)
    offline=tmp_path/"offline";p.rename(offline)
    try:
        report=H.bound_handoff(staged)
        assert report["verdict"]=="PASS",report
        assert str(staged) in report["native"]
    finally:offline.rename(p)
