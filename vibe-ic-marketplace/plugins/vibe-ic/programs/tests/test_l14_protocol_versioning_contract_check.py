#!/usr/bin/env python3
"""Smoke tests for l14_protocol_versioning_contract_check, WITH NEGATIVE
CONTROL.

Both directions are asserted for every rule: a gutted L14 must FAIL and a
well-formed one must PASS. Also pins the ADVISORY verdict semantics — L14
has no downstream consumer, so the gate must NOT block by default, and
MUST block under --strict.

All fixtures are SYNTHESISED neutral data — generic version labels and
generic feature names, nothing copied from a real design or a real spec.
"""
from __future__ import annotations

import importlib
import json

mod = importlib.import_module("l14_protocol_versioning_contract_check")


def well_formed():
    return {
        "doc_class": "L14",
        "extraction_status": "EXTRACTED",
        "fields": {
            "versions": [
                {"version": "r1", "delta": "initial release",
                 "line": 12, "quote": "r1 — initial release"},
                {"version": "r2",
                 "delta": "widened the transfer-count field",
                 "page": 4, "table": "revision history"},
            ],
            "deprecated_features": [
                {"feature": "legacy_side_channel",
                 "quote": "the legacy side channel is deprecated",
                 "line": 90},
            ],
            "backward_compat_traps": [
                {"trap_name": "transfer_count_width",
                 "trap": "an r1 initiator can never request the longer "
                         "transfer an r2 target advertises",
                 "line": 91},
            ],
        },
        "evidence": [
            {"line": 12, "quote": "r1 — initial release"},
            {"line": 13, "quote": "r2 — widened the transfer-count field"},
        ],
    }


def well_formed_empty():
    """Nothing found is a perfectly good L14 — as long as it says so."""
    return {
        "doc_class": "L14",
        "extraction_status": "EXTRACTION_FOUND_NOTHING",
        "fields": {"versions": [], "deprecated_features": [],
                   "backward_compat_traps": []},
        "evidence": [],
    }


def _rules(res):
    return {f["rule"] for f in res["findings"]}


# --------------------------------------------------------------------------
# POSITIVE controls
# --------------------------------------------------------------------------
def test_well_formed_passes():
    res = mod.check(well_formed())
    assert res["findings"] == [], res["findings"]


def test_well_formed_empty_passes():
    res = mod.check(well_formed_empty())
    assert res["findings"] == [], res["findings"]


def test_prose_shaped_rows_pass():
    """A trap or deprecation expressed as a sentence, and a differential
    trap whose sides live under version-named keys, are both legitimate."""
    d = well_formed()
    d["fields"]["backward_compat_traps"] = [
        "mixing an r1 initiator with an r2 target is unsupported",
        {"trap_name": "count_width", "gen_r1": "4-bit count.",
         "gen_r2": "8-bit count."},
    ]
    d["fields"]["deprecated_features"] = [
        "legacy side channel — deprecated."]
    assert mod.check(d)["findings"] == [], mod.check(d)["findings"]


# --------------------------------------------------------------------------
# NEGATIVE controls
# --------------------------------------------------------------------------
def test_status_says_found_nothing_while_rows_present_fails():
    d = well_formed()
    d["extraction_status"] = "EXTRACTION_FOUND_NOTHING"
    assert "l14_status_matches_content" in _rules(mod.check(d))


def test_status_says_extracted_while_empty_fails():
    d = well_formed_empty()
    d["extraction_status"] = "EXTRACTED"
    assert "l14_status_matches_content" in _rules(mod.check(d))


def test_version_row_without_delta_fails():
    d = well_formed()
    d["fields"]["versions"] = [{"version": "r2", "line": 12}]
    d["evidence"] = [{"line": 12, "quote": "r2"}]
    assert "l14_version_row_actionable" in _rules(mod.check(d))


def test_version_row_that_is_a_bare_token_fails():
    d = well_formed()
    d["fields"]["versions"] = ["r2"]
    assert "l14_version_row_actionable" in _rules(mod.check(d))


def test_version_row_without_provenance_fails():
    d = well_formed()
    d["fields"]["versions"] = [{"version": "r2", "delta": "widened a field"}]
    d["evidence"] = []
    assert "l14_version_row_provenance" in _rules(mod.check(d))


def test_deprecated_feature_stub_fails():
    d = well_formed()
    d["fields"]["deprecated_features"] = ["x"]
    assert "l14_deprecated_feature_actionable" in _rules(mod.check(d))


def test_trap_named_but_never_described_fails():
    d = well_formed()
    d["fields"]["backward_compat_traps"] = [{"trap_name": "count_width"}]
    assert "l14_backward_compat_trap_actionable" in _rules(mod.check(d))


def test_unparseable_layer_fails():
    assert "l14_parseable" in _rules(mod.check(None))


# --------------------------------------------------------------------------
# Verdict semantics: ADVISES by default, BLOCKS under --strict
# --------------------------------------------------------------------------
def _project(tmp_path, doc, name="p"):
    gd = tmp_path / name / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L14_PROTOCOL_VERSIONING.json").write_text(json.dumps(doc))
    return tmp_path / name


def test_cli_advises_by_default_and_blocks_under_strict(tmp_path):
    gutted = well_formed()
    gutted["extraction_status"] = "EXTRACTION_FOUND_NOTHING"
    proj = _project(tmp_path, gutted, "gutted")
    assert mod.main([str(proj)]) == 0            # advisory: no block
    assert mod.main([str(proj), "--strict"]) == 1  # blocks on demand

    good = _project(tmp_path, well_formed(), "good")
    assert mod.main([str(good)]) == 0
    assert mod.main([str(good), "--strict"]) == 0


def test_cli_skips_when_layer_absent(tmp_path):
    (tmp_path / "empty").mkdir()
    assert mod.main([str(tmp_path / "empty")]) == 2
