"""Self-contained regressions for the subservient catalog/pad contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

_L3 = """# External Interface

## Port Table

| Port | Width | Direction | Description |
|---|---:|---|---|
| `i_clk` | 1-bit | input | clock |
| `i_rst` | 1-bit | input | reset |
| `o_sram_data` (or `o_sram_wdata`) | 8-bit | output | write data |
| `i_sram_data` (or `i_sram_rdata`) | 8-bit | input | read data |
| `o_sram_addr` | 10-bit | output | address |
| `o_sram_we` | 1-bit | output | write enable |
| `o_sram_cyc` | 1-bit | output | cycle valid |
| `o_gpio` | 1-bit | output | gpio output |
| `i_gpio` | 1-bit | input | gpio input |

## Physical Pad Placement

| Side | Signals |
|---|---|
| **North (N)** | SRAM data bus |
| **South (S)** | SRAM address control we cyc |
| **East (E)** | `i_clk` / `i_rst` |
| **West (W)** | `o_gpio` / `i_gpio` |
"""

_RTL = """module chip_top (
  input wire i_clk,
  input wire i_rst,
  output wire [7:0] o_sram_data,
  input wire [7:0] i_sram_data,
  output wire [9:0] o_sram_addr,
  output wire o_sram_we,
  output wire o_sram_cyc,
  output wire o_gpio,
  input wire i_gpio,
  output wire [7:0] o_sram_wdata,
  input wire [7:0] i_sram_rdata
);
endmodule
"""


def _top_ports():
    return [
        {"name": "i_clk", "direction": "input", "width": 1},
        {"name": "i_rst", "direction": "input", "width": 1},
        {"name": "o_sram_data", "direction": "output", "width": 8,
         "msb": 7, "lsb": 0},
        {"name": "i_sram_data", "direction": "input", "width": 8,
         "msb": 7, "lsb": 0},
        {"name": "o_sram_addr", "direction": "output", "width": 10,
         "msb": 9, "lsb": 0},
        {"name": "o_sram_we", "direction": "output", "width": 1},
        {"name": "o_sram_cyc", "direction": "output", "width": 1},
        {"name": "o_gpio", "direction": "output", "width": 1},
        {"name": "i_gpio", "direction": "input", "width": 1},
        {"name": "o_sram_wdata", "direction": "output", "width": 8,
         "msb": 7, "lsb": 0},
        {"name": "i_sram_rdata", "direction": "input", "width": 8,
         "msb": 7, "lsb": 0},
    ]


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "run"
    (project / "input/docs").mkdir(parents=True)
    (project / "phase1/generated_docs").mkdir(parents=True)
    (project / "phase2/stage1/rtl").mkdir(parents=True)
    answers = {
        key: "NOT_DETERMINED"
        for key in (
            "deliverable", "top_cell", "die_area_um", "core_area_um",
            "fp_sizing", "die_origin_um", "macro_area_um",
            "macro_origin_um", "database_unit_um", "pad_order_by_side",
            "pad_site_name", "pad_corner_site_name", "pad_edge_spacing_um",
            "pad_rotations", "pad_corner_master", "pad_fillers",
            "pad_signal_map", "seal_ring_required", "seal_ring_script",
            "seal_ring_marker_layer",
        )
    }
    answers["deliverable"] = "DIE"
    route = {
        "schema": "vibe-ic/tapeout_declaration/1",
        "answers": answers,
        "forbidden_layers": "NOT_DETERMINED",
        "synthesis_area_budget": "NOT_DETERMINED",
        "answer_provenance": {
            "deliverable": {
                "answered_by": "owner",
                "citation": "self-contained fixture",
            },
        },
    }
    (project / "input/step_0_5ic_answers.json").write_text(
        json.dumps({
            **route,
            "operator_template": {
                "path": None,
                "slot": None,
                "absent_reason": "self-contained fixture",
            },
        }, indent=2) + "\n", encoding="utf-8")
    slots = project / "input/submission_template/slots"
    slots.mkdir(parents=True)
    pads = [f"bidir[{i}].pad" for i in range(32)]
    (slots / "self_contained.json").write_text(
        json.dumps({"PAD_NORTH": pads[:16], "PAD_SOUTH": pads[16:]}),
        encoding="utf-8")
    (project / "input/submission_template/tapeout_declaration.json").write_text(
        json.dumps(route, indent=2) + "\n", encoding="utf-8")
    (project / "input/docs/L3_external_interface.md").write_text(
        _L3, encoding="utf-8")
    (project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"schema_version": 1, "top_module": "chip_top",
                    "top_ports": _top_ports()}, indent=2) + "\n",
        encoding="utf-8")
    (project / "phase2/stage1/rtl/chip_top.v").write_text(
        _RTL, encoding="utf-8")
    (project / "phase2/stage1/rtl/SOURCE_MANIFEST.json").write_text(
        json.dumps({"reused_ip": True,
                    "rtl_strategy": "catalog_lookup_plus_ai_glue",
                    "renamed_interfaces": [],
                    "derived_pad_pairs": []}, indent=2) + "\n",
        encoding="utf-8")
    return project


def _catalog_project(tmp_path: Path) -> Path:
    project = tmp_path / "catalog"
    (project / "phase1/generated_docs").mkdir(parents=True)
    (project / "phase2/stage1/rtl").mkdir(parents=True)
    (project / "phase1/generated_docs/L2_FRS.json").write_text(
        json.dumps({"cpu_isa": "rv32i", "cpu_arch": "bit-serial",
                    "description":
                    "The design reuses the serv core from the IP catalog."}),
        encoding="utf-8")
    (project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "chip_top", "top_ports": []}),
        encoding="utf-8")
    (project / "phase2/stage1/rtl/chip_top.v").write_text(
        "module chip_top(input wire clk, output wire q); assign q = clk; endmodule\n",
        encoding="utf-8")
    return project


def test_base_catalog_gate_is_red_and_missing_declaration_is_fail_closed(tmp_path):
    import catalog_synth_safe_params_check as catalog
    import design_one_shot_runner as runner

    project = _catalog_project(tmp_path)
    rc, report = catalog.run(project, None)
    assert rc == 1
    assert "CATALOG_REUSE_DECLARED_NOT_INSTANTIATED" in report["failure_codes"]
    assert report["reached_ips"] == []



def test_explicit_alias_pair_resolves_the_sixteen_unmatched_bits(tmp_path):
    import renamed_interface_derive as derive
    import slot_pad_budget_check as pad

    project = _make_project(tmp_path)
    manifest_path = project / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = derive.apply_to_manifest(project, manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")
    pairs = manifest["derived_pad_pairs"]
    assert {tuple(p["rtl"]) for p in pairs} == {
        ("i_sram_rdata",), ("o_sram_wdata",)}
    assert derive.check(project, {}, derived=pairs)["verdict"] == "PASS"
    out = project / "reports/slot-focused.json"
    rc = pad.main([str(project), "--json", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0, report
    assert report["verdict"] == "FITS"
    arith = report["own_ring_arithmetic"]
    assert arith["signal_pads_placed_by_the_ring"] == arith["signal_pads_owed"]
    assert arith["signal_pads_owed_with_no_pad"] == 0


def test_alias_mutations_remain_fail_closed(tmp_path):
    import renamed_interface_derive as derive

    for mutation in ("missing", "width", "direction"):
        project = _make_project(tmp_path / mutation)
        doc = project / "input/docs/L3_external_interface.md"
        text = doc.read_text(encoding="utf-8")
        if mutation == "missing":
            text = text.replace(" (or `o_sram_wdata`)", "")
            text = text.replace(" (or `i_sram_rdata`)", "")
        elif mutation == "width":
            text = text.replace("| 8-bit | output | write data", "| 16-bit | output | write data")
            text = text.replace("| 8-bit | input | read data", "| 16-bit | input | read data")
        else:
            text = text.replace("| 8-bit | input | read data", "| 8-bit | output | read data")
            text = text.replace("| 8-bit | output | write data", "| 8-bit | input | write data")
        doc.write_text(text, encoding="utf-8")
        result = derive.derive(project)
        assert result["pairs"] == [], mutation
        assert {u["port"] for u in result["unresolved"]} == {
            "i_sram_rdata", "o_sram_wdata"}, mutation


def test_persisted_derived_pairs_rederive_against_every_current_record(tmp_path):
    import renamed_interface_derive as derive

    mutations = ("swap", "side", "evidence", "placement", "width",
                 "direction")
    for mutation in mutations:
        project = _make_project(tmp_path / mutation)
        manifest_path = project / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = derive.apply_to_manifest(project, manifest)
        pairs = json.loads(json.dumps(manifest["derived_pad_pairs"]))
        if mutation == "swap":
            pairs[0]["l9"], pairs[1]["l9"] = pairs[1]["l9"], pairs[0]["l9"]
            pairs[0]["rtl"], pairs[1]["rtl"] = pairs[1]["rtl"], pairs[0]["rtl"]
        elif mutation == "side":
            pairs[0]["side"] = "S"
        elif mutation == "evidence":
            pairs[0]["evidence"][0]["evidence_source"] = "forged.md:1"
        else:
            doc = project / "input/docs/L3_external_interface.md"
            text = doc.read_text(encoding="utf-8")
            if mutation == "placement":
                text = text.replace("SRAM data bus", "GPIO")
            elif mutation == "width":
                text = text.replace("| 8-bit | output | write data", "| 16-bit | output | write data")
                text = text.replace("| 8-bit | input | read data", "| 16-bit | input | read data")
            else:
                text = text.replace("| 8-bit | input | read data", "| 8-bit | output | read data")
                text = text.replace("| 8-bit | output | write data", "| 8-bit | input | write data")
            doc.write_text(text, encoding="utf-8")
        manifest["derived_pad_pairs"] = pairs
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                                 encoding="utf-8")
        verdicts = derive.verify(project, pairs, authored=False,
                                 key=derive.DERIVED_KEY)
        assert verdicts and any(v["verdict"] == "REFUSED" for v in verdicts), mutation
        checked = derive.check(project, {}, derived=pairs)
        assert checked["verdict"] == "FAIL", mutation


def test_duplicate_r3_is_rejected_by_pad_consumer_and_slot_budget(tmp_path):
    import _l_doc_pad_placement as placement
    import renamed_interface_derive as derive
    import slot_pad_budget_check as pad

    project = _make_project(tmp_path)
    manifest_path = project / "phase2/stage1/rtl/SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = derive.apply_to_manifest(project, manifest)
    r3 = [p for p in manifest["derived_pad_pairs"]
           if p.get("rule") == "R3_explicit_document_alias"]
    assert r3
    manifest["derived_pad_pairs"].append(json.loads(json.dumps(r3[0])))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")

    top, l9_ports = derive._l9(project)
    implemented, _source = derive._implemented_ports(project, top, l9_ports)
    accepted, rejected = placement.accepted_renames(project, implemented)
    assert accepted == []
    assert any("does not exactly match" in reason
               for item in rejected for reason in item.get("reasons", []))

    ring = placement.derive_own_ring(project, implemented)
    assert ring["renamed_interfaces"] == []
    assert ring["renamed_interfaces_rejected"]
    out = project / "reports/slot-duplicate-r3.json"
    rc = pad.main([str(project), "--json", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert rc != 0, report
    assert report["verdict"] != "FITS", report
