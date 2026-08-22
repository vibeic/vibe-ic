#!/usr/bin/env python3
"""Unit tests for programs/waiver_template_gen.py.

Pins the real anti-fabrication behavior of the waiver-template scaffolder:
  - emits ONE entry per MISSING step (FAIL steps excluded unless
    --include-fail), normalising step ids (A1/M1/P0/int)
  - the scaffold uses placeholder approver/reason that the waivers
    schema gate is GUARANTEED to reject (so it cannot ship as final)
  - REFUSES to overwrite an existing waivers.json (rc=1)
  - honest no-op (rc=0) when there is nothing to scaffold
  - rc=2 on unreadable/absent audit it cannot produce
Logic-pinned.
"""
from __future__ import annotations

import json
from pathlib import Path

import waiver_template_gen as mod


def _write_audit(project: Path, results: list) -> Path:
    audit = project / "reports" / "flow_compliance.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps({"results": results}))
    return audit


# ---------------------------------------------------------------------------
# PASS fixture: MISSING steps -> scaffold entries
# ---------------------------------------------------------------------------
def test_missing_steps_scaffolded(tmp_path):
    audit = _write_audit(tmp_path, [
        {"id": "A1", "status": "MISSING", "message": "no analog tool"},
        {"id": 5, "status": "PASS"},
        {"id": "P0", "status": "FAIL", "message": "real defect"},
    ])
    out = tmp_path / "waivers.json.template"
    rc = mod.generate(tmp_path, audit, out,
                      include_fail=False, quiet=True)
    assert rc == 0
    tmpl = json.loads(out.read_text())
    ids = [e["id"] for e in tmpl["waived_steps"]]
    # only the MISSING A1 — PASS dropped, FAIL excluded by default
    assert ids == ["A1"]


def test_scaffold_placeholders_are_schema_rejectable(tmp_path):
    audit = _write_audit(tmp_path, [
        {"id": 12, "status": "MISSING", "message": "spef tool commercial"},
    ])
    out = tmp_path / "waivers.json.template"
    mod.generate(tmp_path, audit, out, include_fail=False, quiet=True)
    entry = json.loads(out.read_text())["waived_steps"][0]
    # These are exactly the values the schema gate must reject.
    assert entry["approver"] == mod.PLACEHOLDER_APPROVER == "agent"
    assert entry["reason"] == mod.PLACEHOLDER_REASON == "TODO"
    assert entry["review_required"] is True
    assert entry["_evidence_hint"] == "spef tool commercial"
    # Cross-check against the live schema gate's reject predicates.
    import waivers_schema_check as wsc
    assert wsc._is_self_approver(entry["approver"]) is True
    assert wsc._is_placeholder(entry["reason"]) is True


def test_include_fail_also_scaffolds_fail(tmp_path):
    audit = _write_audit(tmp_path, [
        {"id": "A1", "status": "MISSING", "message": "m"},
        {"id": "P0", "status": "FAIL", "message": "f"},
    ])
    out = tmp_path / "waivers.json.template"
    mod.generate(tmp_path, audit, out, include_fail=True, quiet=True)
    ids = sorted(str(e["id"]) for e in
                 json.loads(out.read_text())["waived_steps"])
    assert ids == ["A1", "P0"]


# ---------------------------------------------------------------------------
# step-id normalisation
# ---------------------------------------------------------------------------
def test_step_id_normalisation_forms(tmp_path):
    audit = _write_audit(tmp_path, [
        {"id": "a3", "status": "MISSING", "message": "x"},     # -> A3
        {"id": "step_7_label", "status": "MISSING", "message": "x"},  # -> 7
        {"id": "p0", "status": "MISSING", "message": "x"},     # -> P0
        {"id": "13", "status": "MISSING", "message": "x"},     # -> 13
    ])
    out = tmp_path / "waivers.json.template"
    mod.generate(tmp_path, audit, out, include_fail=False, quiet=True)
    ids = [e["id"] for e in json.loads(out.read_text())["waived_steps"]]
    assert ids == ["A3", 7, "P0", 13]


# ---------------------------------------------------------------------------
# FAIL fixture: refuse to overwrite an existing waivers.json
# ---------------------------------------------------------------------------
def test_refuses_to_overwrite_real_waivers_json(tmp_path):
    audit = _write_audit(tmp_path, [
        {"id": 1, "status": "MISSING", "message": "m"},
    ])
    (tmp_path / "waivers.json").write_text("{}")
    rc = mod.generate(tmp_path, audit, tmp_path / "waivers.json",
                      include_fail=False, quiet=True)
    assert rc == 1


# ---------------------------------------------------------------------------
# honest no-op / edge cases
# ---------------------------------------------------------------------------
def test_no_candidates_is_noop_rc0(tmp_path):
    audit = _write_audit(tmp_path, [
        {"id": 1, "status": "PASS"},
        {"id": 2, "status": "PASS"},
    ])
    out = tmp_path / "waivers.json.template"
    rc = mod.generate(tmp_path, audit, out,
                      include_fail=False, quiet=True)
    assert rc == 0
    assert not out.exists()  # nothing scaffolded -> no file


def test_unparseable_audit_is_rc2(tmp_path):
    audit = tmp_path / "reports" / "flow_compliance.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text("{ this is not json")
    out = tmp_path / "waivers.json.template"
    rc = mod.generate(tmp_path, audit, out,
                      include_fail=False, quiet=True)
    assert rc == 2
