#!/usr/bin/env python3
"""Smoke tests for l15_encoding_tables_contract_check, WITH NEGATIVE
CONTROL.

Both directions are asserted for every rule: an L15 gutted into a shape the
consumer cannot reconcile must FAIL, and a well-formed one must PASS.

The decisive test is `test_gutted_*_is_invisible_to_the_consumer`: the
gutted fixtures still CONTAIN the encoding — the codes are right there in
the rows — but `opcode_field_width_consistency_check` extracts nothing from
them and would print ALL_PASS after zero comparisons. That is the whole
point: a layer is complete when the requirement is present IN THE LAYER
THAT CONSUMES IT, in an actionable form, not when a token appears.

All fixtures are SYNTHESISED neutral data: invented mnemonics, invented
codes, no real design, PDK, vendor part or signal name.
"""
from __future__ import annotations

import importlib
import json

mod = importlib.import_module("l15_encoding_tables_contract_check")
consumer = importlib.import_module("opcode_field_width_consistency_check")


# --------------------------------------------------------------------------
# Fixtures — synthesised, neutral
# --------------------------------------------------------------------------
def well_formed():
    return {
        "doc_class": "L15",
        "extraction_status": "EXTRACTED",
        "fields": {
            "tables": [
                {"table_id": "T-1", "name": "request encoding", "line": 10,
                 "rows": [["0x01", "ALPHA"], ["0x02", "BETA"],
                          ["0x03", "GAMMA"]]},
            ],
        },
    }


def _rules(res, sev=None):
    return {f["rule"] for f in res["findings"]
            if sev is None or f["severity"] == sev}


def _sev(res, sev):
    return [f for f in res["findings"] if f["severity"] == sev]


# --------------------------------------------------------------------------
# POSITIVE controls
# --------------------------------------------------------------------------
def test_well_formed_passes():
    res = mod.check(well_formed())
    assert res["findings"] == [], res["findings"]
    assert res["code_bearing_tables"] == 1


def test_well_formed_is_actually_reconcilable_by_the_consumer():
    """Guards the guard: if the consumer could not read the PASS fixture,
    the whole test file would be measuring nothing."""
    pairs = list(consumer._iter_l15_name_hex(well_formed()["fields"]))
    assert {n for n, _v, _h in pairs} == {"alpha", "beta", "gamma"}


def test_non_encoding_table_is_not_demanded_to_reconcile():
    """A table with no code literals is not an encoding table; requiring a
    mnemonic/code pair from it would be a false alarm."""
    d = well_formed()
    d["fields"]["tables"] = [
        {"table_id": "T-2", "name": "environmental limits", "line": 20,
         "header_columns": ["parameter", "min", "max", "unit"],
         "rows": [["supply", "-7", "+12", "V"]]},
    ]
    d["extraction_status"] = "EXTRACTED"
    res = mod.check(d)
    assert _sev(res, "FAIL") == [], res["findings"]


def test_multi_code_row_passes_when_a_code_column_is_designated():
    """The remedy the FAIL message prescribes must actually clear the gate."""
    d = well_formed()
    d["fields"]["tables"] = [
        {"table_id": "T-3", "name": "request encoding", "line": 30,
         "rows": [{"name": "ALPHA", "code": "0x01"},
                  {"name": "BETA", "code": "0x02"}]},
    ]
    assert _sev(mod.check(d), "FAIL") == [], mod.check(d)["findings"]


# --------------------------------------------------------------------------
# NEGATIVE controls — the encoding is PRESENT but not ACTIONABLE
# --------------------------------------------------------------------------
def test_gutted_multi_code_row_is_invisible_to_the_consumer():
    """Rows carry several code cells and none is designated as THE code."""
    d = well_formed()
    d["fields"]["tables"] = [
        {"table_id": "T-1", "name": "request encoding", "line": 10,
         "rows": [["ALPHA", "0x01", "0xFF", "0x10"],
                  ["BETA", "0x02", "0xFE", "0x20"]]},
    ]
    res = mod.check(d)
    assert "l15_encoding_unreconcilable_by_consumer" in _rules(res, "FAIL"), \
        res["findings"]
    # and the consumer really does see nothing:
    assert list(consumer._iter_l15_name_hex(d["fields"])) == []


def test_gutted_unreadable_radix_is_invisible_to_the_consumer():
    """Codes written in a radix the reconciler does not read."""
    d = well_formed()
    d["fields"]["tables"] = [
        {"table_id": "T-1", "name": "request encoding", "line": 10,
         "rows": [["ALPHA", "0b0001"], ["BETA", "3'b010"]]},
    ]
    res = mod.check(d)
    assert "l15_encoding_unreconcilable_by_consumer" in _rules(res, "FAIL"), \
        res["findings"]
    assert list(consumer._iter_l15_name_hex(d["fields"])) == []


def test_nameless_numeric_map_is_out_of_scope_not_a_finding():
    """A table with codes but no mnemonic anywhere is a numeric map, not a
    mnemonic→code encoding. The reconciler keys on mnemonics, so demanding
    a pair here would demand the impossible — the rule must skip it."""
    d = well_formed()
    d["fields"]["tables"] = [
        {"table_id": "T-1", "name": "strap map", "line": 10,
         "rows": [["000", "0x01", "0x02"], ["001", "0x03", "0x04"]]},
    ]
    res = mod.check(d)
    assert _sev(res, "FAIL") == [], res["findings"]
    assert res["code_bearing_tables"] == 0


def test_code_wider_than_the_width_the_table_declares_fails():
    d = well_formed()
    d["fields"]["tables"] = [
        {"table_id": "T-1", "name": "request encoding", "line": 10,
         "bit_width": 4,
         "rows": [["0x01", "ALPHA"], ["0x11", "BETA"]]},
    ]
    res = mod.check(d)
    assert "l15_code_exceeds_declared_width" in _rules(res, "FAIL"), \
        res["findings"]
    # …and the same table with an in-range code passes.
    d["fields"]["tables"][0]["rows"] = [["0x01", "ALPHA"], ["0x0F", "BETA"]]
    assert _sev(mod.check(d), "FAIL") == []


def test_column_scoped_width_catches_overflow_in_its_own_column():
    d = well_formed()
    d["fields"]["tables"] = [
        {"table_id": "T-1", "name": "request encoding", "line": 10,
         "header_columns": ["name", "SEL[3:0]", "note"],
         "rows": [{"name": "ALPHA", "sel_3_0": "0x11", "note": "idle"}]},
    ]
    assert "l15_code_exceeds_declared_width" in _rules(mod.check(d), "FAIL")
    # …and the same table with an in-range code passes clean.
    d["fields"]["tables"][0]["rows"] = [
        {"name": "ALPHA", "sel_3_0": "0x01", "note": "idle"}]
    assert _sev(mod.check(d), "FAIL") == [], mod.check(d)["findings"]


def test_a_columns_width_does_not_govern_a_different_column():
    """A narrow header column must not condemn a wide code that lives in a
    different column — that is exactly how a well-formed multi-column table
    gets falsely flagged, and it was observed on real runs before the rule
    was scoped."""
    table = {"table_id": "T-1", "name": "request encoding",
             "header_columns": ["name", "SEL[3:0]", "byte"],
             "rows": [{"name": "ALPHA", "sel_3_0": "0x01", "byte": "0xE1"}]}
    scoped = mod.width_scoped_codes(table)
    assert [(w, c) for w, c, _v, _s in scoped] == [(4, "0x01")], scoped
    # A table that declares no width at all binds nothing.
    assert mod.width_scoped_codes(
        {"header_columns": ["name", "byte"],
         "rows": [["ALPHA", "0xE1"]]}) == []


def test_unparseable_layer_fails():
    assert "l15_parseable" in _rules(mod.check(None), "FAIL")


# --------------------------------------------------------------------------
# Advisory tier
# --------------------------------------------------------------------------
def test_caption_only_table_entry_is_flagged_as_name_without_encoding():
    d = well_formed()
    d["fields"]["tables"] = ["T-1 request encoding", "T-2 response encoding"]
    res = mod.check(d)
    assert "l15_table_caption_without_rows" in _rules(res, "WARN"), \
        res["findings"]
    assert _sev(res, "FAIL") == []


def test_status_contradicting_content_is_flagged():
    d = well_formed()
    d["extraction_status"] = "EXTRACTION_FOUND_NOTHING"
    assert "l15_status_contradicts_content" in _rules(mod.check(d), "WARN")


def test_vacuous_l3_reconciliation_is_flagged():
    """L3 declares hex opcodes, L15 exposes mnemonics, and the two sets do
    not meet — the downstream consistency check runs zero comparisons."""
    l3 = {"opcodes": [{"name": "DELTA", "hex": "0x07"},
                      {"name": "EPSILON", "hex": "0x08"}]}
    res = mod.check(well_formed(), l3)
    assert "l15_l3_reconciliation_vacuous" in _rules(res, "WARN"), \
        res["findings"]
    # …and when they DO meet, no advisory.
    l3ok = {"opcodes": [{"name": "ALPHA", "hex": "0x01"}]}
    assert "l15_l3_reconciliation_vacuous" not in _rules(
        mod.check(well_formed(), l3ok))


# --------------------------------------------------------------------------
# CLI blocking semantics, both directions
# --------------------------------------------------------------------------
def _project(tmp_path, l15, name="p", l3=None):
    gd = tmp_path / name / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L15_ENCODING_TABLES.json").write_text(json.dumps(l15))
    if l3 is not None:
        (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3))
    return tmp_path / name


def test_cli_blocks_on_fail_and_passes_on_well_formed(tmp_path):
    assert mod.main([str(_project(tmp_path, well_formed(), "good"))]) == 0

    gutted = well_formed()
    gutted["fields"]["tables"] = [
        {"table_id": "T-1", "name": "request encoding", "line": 10,
         "rows": [["ALPHA", "0x01", "0xFF"], ["BETA", "0x02", "0xFE"]]}]
    assert mod.main([str(_project(tmp_path, gutted, "bad"))]) == 1  # BLOCKS


def test_cli_advisory_tier_does_not_block_without_strict(tmp_path):
    d = well_formed()
    d["extraction_status"] = "EXTRACTION_FOUND_NOTHING"
    proj = _project(tmp_path, d, "advisory")
    assert mod.main([str(proj)]) == 0
    assert mod.main([str(proj), "--strict"]) == 1


def test_cli_skips_when_layer_absent(tmp_path):
    (tmp_path / "empty").mkdir()
    assert mod.main([str(tmp_path / "empty")]) == 2
