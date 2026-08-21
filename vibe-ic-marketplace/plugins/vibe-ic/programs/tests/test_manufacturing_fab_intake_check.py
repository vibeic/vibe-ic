#!/usr/bin/env python3
"""Tests for manufacturing_fab_intake_check.py — Step 40 fab-intake gate.

Two HIGH defects were fixed in this gate and are pinned here.

(1) d5 — SEARCH PATH.  The gate used to look under a bare
    ``manufacturing/`` prefix while flow/phase1_phase2_phase3.yaml step 40
    declares ``phase3/stage5_manufacturing/``.  A project laid out the way
    the flow specifies got ``verdict: SKIP`` rc=2, which
    flow_compliance_check maps to VACUOUS_PASS and counts as a pass.
    Canonical path now wins; the legacy prefix stays as a fallback.

(2) d2 — SUBSTANCE.  rc=1 was mechanically unreachable: the gate PASSed
    on file presence alone, so an unparseable blob and a 0-byte file
    certified fab intake.  The gate now reads the mask-set identity, the
    wafer-lot identity and the foundry status the step exists to record.

NOTE ON A CORRECTED TEST: the previous ``test_pass_when_both_present``
asserted PASS for two files whose entire content was ``{"received": true}``
— i.e. it encoded defect (2) as the expected behaviour.  It is replaced by
``test_presence_without_identity_fails`` (that same fixture must now FAIL)
plus ``test_pass_when_both_present_with_real_intake_facts`` (a realistic
intake artefact must still PASS).  The test was fixed, not deleted.

Test taxonomy
-------------
  DISCRIMINATOR — must FAIL against the pre-fix program (mutant proof).
  GUARD (direction-1) — behaviour that must NOT change; passes on both
  the pre-fix and post-fix program.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "manufacturing_fab_intake_check.py"

_spec = importlib.util.spec_from_file_location(
    "manufacturing_fab_intake_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

# The paths flow/phase1_phase2_phase3.yaml step 40 declares.
_CANONICAL = ["phase3/stage5_manufacturing/mask_set_received.json",
              "phase3/stage5_manufacturing/wafer_lot_received.json"]
# The pre-v1.7.37 locations, still accepted as a fallback.
_LEGACY = ["manufacturing/mask_set_received.json",
           "manufacturing/wafer_lot_received.json"]

# Realistic, chip-agnostic intake content: a mask-set identity, a wafer-lot
# identity and a foundry status.  No vendor schema is assumed.
_MASK_SET_DOC = {"mask_set_id": "MS-2026-042", "revision": "A1",
                 "foundry": "IHP"}
_WAFER_LOT_DOC = {"lot_id": "LOT-9911", "wafer_count": 25,
                  "foundry_status": "shipped"}


def _run(project: Path):
    out = project / "report.json"
    rc = mod.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


def _write(project: Path, rel: str, doc):
    f = project / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(doc if isinstance(doc, str) else json.dumps(doc))


def _write_pair(project: Path, rels, mask=_MASK_SET_DOC, lot=_WAFER_LOT_DOC):
    _write(project, rels[0], mask)
    _write(project, rels[1], lot)


# ======================================================================
# DISCRIMINATORS — d5, the search path
# ======================================================================
def test_canonical_flow_declared_path_is_searched(tmp_path):
    """DISCRIMINATOR (d5). Intake data at the path the flow declares must
    reach the gate. Pre-fix this returned SKIP/rc=2 -> VACUOUS_PASS."""
    _write_pair(tmp_path, _CANONICAL)
    rc, rep = _run(tmp_path)
    assert rc == 0, f"canonical layout must not SKIP; got rc={rc} {rep}"
    assert rep["verdict"] == "PASS"
    assert rep["missing"] == []
    assert set(rep["found"]) == set(_CANONICAL)


def test_canonical_path_is_the_first_candidate(tmp_path):
    """DISCRIMINATOR (d5). The flow-declared prefix must be preferred, so a
    project carrying BOTH layouts is judged on the canonical one."""
    _write_pair(tmp_path, _CANONICAL)
    # Legacy copies carry garbage; they must never be the ones read.
    _write(tmp_path, _LEGACY[0], "not json at all")
    _write(tmp_path, _LEGACY[1], "")
    rc, rep = _run(tmp_path)
    assert rc == 0 and rep["verdict"] == "PASS"
    assert set(rep["found"]) == set(_CANONICAL)


def test_missing_list_names_the_declared_path(tmp_path):
    """DISCRIMINATOR (d5). When intake is absent, the gate must report the
    path the flow actually declares, not a legacy one nobody produces."""
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert set(rep["missing"]) == set(_CANONICAL)


# ======================================================================
# DISCRIMINATORS — d2, the substance predicate
# ======================================================================
def test_unparseable_intake_fails(tmp_path):
    """DISCRIMINATOR (d2). Measured on v1.7.36: this exact fixture returned
    PASS/rc=0.  Placed at the LEGACY path so the assertion isolates the
    substance defect from the path defect."""
    _write(tmp_path, _LEGACY[0], "not json at all -- garbage")
    _write(tmp_path, _LEGACY[1], json.dumps(_WAFER_LOT_DOC))
    rc, rep = _run(tmp_path)
    assert rc == 1, f"unparseable intake must FAIL; got rc={rc}"
    assert rep["verdict"] == "FAIL"
    assert any(f["rule"] == "INTAKE_JSON_UNPARSEABLE" for f in rep["findings"])


def test_zero_byte_intake_fails(tmp_path):
    """DISCRIMINATOR (d2). A 0-byte file attests to nothing."""
    _write(tmp_path, _LEGACY[0], json.dumps(_MASK_SET_DOC))
    _write(tmp_path, _LEGACY[1], "")
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert any(f["rule"] == "INTAKE_JSON_EMPTY" for f in rep["findings"])


def test_non_object_intake_fails(tmp_path):
    """DISCRIMINATOR (d2). A JSON array / null is not an intake record."""
    _write(tmp_path, _LEGACY[0], "null")
    _write(tmp_path, _LEGACY[1], json.dumps(_WAFER_LOT_DOC))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert any(f["rule"] == "INTAKE_JSON_NOT_OBJECT" for f in rep["findings"])


def test_presence_without_identity_fails(tmp_path):
    """DISCRIMINATOR (d2).  THIS REPLACES the old ``test_pass_when_both_
    present``, which asserted PASS for exactly this fixture and therefore
    encoded the defect as expected behaviour.  ``{"received": true}`` names
    no mask set, no wafer lot and no foundry — step 40 exists to record
    precisely those three facts."""
    _write(tmp_path, _LEGACY[0], {"received": True})
    _write(tmp_path, _LEGACY[1], {"received": True})
    rc, rep = _run(tmp_path)
    assert rc == 1, "presence-only intake must not certify fab intake"
    assert rep["verdict"] == "FAIL"
    rules = {f["rule"] for f in rep["findings"]}
    assert "MASK_SET_IDENTITY_MISSING" in rules
    assert "WAFER_LOT_IDENTITY_MISSING" in rules
    assert "FOUNDRY_STATUS_MISSING" in rules


def test_missing_mask_set_identity_fails(tmp_path):
    """DISCRIMINATOR (d2). Lot + foundry present, mask set unnamed."""
    _write(tmp_path, _LEGACY[0], {"note": "mask set arrived"})
    _write(tmp_path, _LEGACY[1], _WAFER_LOT_DOC)
    rc, rep = _run(tmp_path)
    assert rc == 1
    rules = {f["rule"] for f in rep["findings"]}
    assert "MASK_SET_IDENTITY_MISSING" in rules
    assert "WAFER_LOT_IDENTITY_MISSING" not in rules


def test_missing_foundry_status_fails(tmp_path):
    """DISCRIMINATOR (d2). Both identities present, no foundry/fab status."""
    _write(tmp_path, _LEGACY[0], {"mask_set_id": "MS-1"})
    _write(tmp_path, _LEGACY[1], {"lot_id": "L-1", "wafer_count": 25})
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert any(f["rule"] == "FOUNDRY_STATUS_MISSING" for f in rep["findings"])


def test_waiver_does_not_excuse_a_present_substanceless_artefact(tmp_path):
    """DISCRIMINATOR (d2). A waiver covers a step that did not run.  It must
    not launder a fab-intake artefact that IS there and says nothing."""
    _write(tmp_path, _LEGACY[0], "not json")
    _write(tmp_path, _LEGACY[1], "not json")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{"id": "manufacturing_fab_intake",
                          "ticket": "FAB-7", "reason": "external tracker"}]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"


# ======================================================================
# PASS paths — the gate must still certify genuine intake data
# ======================================================================
def test_pass_when_both_present_with_real_intake_facts(tmp_path):
    """DISCRIMINATOR (d5) + positive control for d2: a realistic intake
    record at the declared path PASSes and the parsed facts are reported."""
    _write_pair(tmp_path, _CANONICAL)
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["parsed"]["mask_set_id"] == "MS-2026-042"
    assert rep["parsed"]["lot_id"] == "LOT-9911"
    assert rep["parsed"]["foundry_status"] is not None


def test_nested_intake_shape_accepted(tmp_path):
    """DISCRIMINATOR (d5). chip-AGNOSTIC: foundries nest differently.
    ``{"mask_set": {"id": ...}}`` must read as a mask-set identity."""
    _write(tmp_path, _CANONICAL[0], {"mask_set": {"id": "RETICLE-7"}})
    _write(tmp_path, _CANONICAL[1],
           {"lot": {"number": "B-14"}, "fab": {"name": "GF", "status": "shipped"}})
    rc, rep = _run(tmp_path)
    assert rc == 0, f"nested intake shape must PASS; got {rep}"
    assert rep["verdict"] == "PASS"


def test_legacy_layout_still_accepted(tmp_path):
    """GUARD (direction-1). The legacy ``manufacturing/`` prefix keeps
    working, so no hand-built project layout regresses."""
    _write_pair(tmp_path, _LEGACY)
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert set(rep["found"]) == set(_LEGACY)


# ======================================================================
# GUARDS (direction-1) — behaviour that must NOT change
# ======================================================================
def test_skip_when_all_missing(tmp_path):
    """GUARD. Absent artefacts stay SKIP/rc=2 (the 'input not applicable'
    convention).  Pre-silicon runs must not start failing step 40; PR #455's
    ALL-of-N required_outputs rule downgrades that tier to MISSING."""
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"


def test_skip_when_one_of_two_missing(tmp_path):
    """GUARD. One of two artefacts present is still SKIP, never PASS."""
    _write(tmp_path, _LEGACY[0], _MASK_SET_DOC)
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"
    assert _LEGACY[0] in rep["found"]


def test_waived_when_step_waived(tmp_path):
    """GUARD. The waivers.json path for a genuinely absent artefact."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "manufacturing_fab_intake",
            "ticket": "FAB-7",
            "reason": "fab handles intake tracking externally",
        }]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "WAIVED"
    assert rep["waiver"]["ticket"] == "FAB-7"


def test_waiver_matched_by_ticket_substring(tmp_path):
    """GUARD. _step_waived also matches the step label inside the ticket."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{"id": "other", "ticket": "covers "
                          "manufacturing_fab_intake too", "reason": "bundled"}]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "WAIVED"


def test_malformed_waivers_json_falls_back_to_skip(tmp_path):
    """GUARD. Garbage waivers.json must not crash the gate."""
    (tmp_path / "waivers.json").write_text("{ not valid json")
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"


def test_missing_project_dir(tmp_path):
    """GUARD. Project dir absent → operational rc 2."""
    rc = mod.main([str(tmp_path / "nope")])
    assert rc == 2


def test_report_schema_keys_preserved(tmp_path):
    """GUARD. required_files / found / missing / waiver / verdict are the
    documented report keys; they must survive."""
    _write_pair(tmp_path, _CANONICAL)
    _rc, rep = _run(tmp_path)
    for key in ("gate", "verdict", "step_label", "required_files", "found",
                "missing", "waiver", "rationale_when_skipped", "findings"):
        assert key in rep, f"report lost key {key!r}"
