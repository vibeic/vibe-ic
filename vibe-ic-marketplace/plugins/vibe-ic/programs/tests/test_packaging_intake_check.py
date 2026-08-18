#!/usr/bin/env python3
"""Tests for packaging_intake_check.py — Step 42 packaging-intake gate.

Two HIGH defects were fixed in this gate and are pinned here.

(1) d5 — SEARCH PATH.  The gate used to look under a bare
    ``manufacturing/`` prefix while flow/phase1_phase2_phase3.yaml step 42
    declares ``phase3/stage5_manufacturing/packaging_log.json``.  On a
    project laid out the way the flow specifies the gate returned
    ``verdict: SKIP`` rc=2 — mapped to VACUOUS_PASS and counted as a pass —
    so the gate could never return PASS on a compliant layout at all.
    Canonical path now wins; the legacy prefix stays as a fallback.

(2) d2 — SUBSTANCE.  rc=1 was mechanically unreachable: the gate PASSed on
    file presence alone, so a packaging log whose whole content was the
    token ``null`` certified packaging assembly.  The gate now reads the
    package type and the assembled-unit population step 42 exists to
    record.

NOTE ON A CORRECTED TEST: the previous ``test_pass_when_required_file_
present`` asserted PASS for ``{"lots": [1, 2, 3]}`` — a fixture that names
no package type — and therefore encoded defect (2) as expected behaviour.
It is replaced by ``test_lots_only_without_package_type_fails`` (that same
fixture must now FAIL) plus ``test_pass_when_packaging_log_has_real_facts``
(a realistic assembly log must still PASS).  The test was fixed, not
deleted.

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
_PROG = _HERE.parent / "packaging_intake_check.py"

_spec = importlib.util.spec_from_file_location("packaging_intake_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

# The path flow/phase1_phase2_phase3.yaml step 42 declares.
_CANONICAL = "phase3/stage5_manufacturing/packaging_log.json"
# The pre-v1.7.37 location, still accepted as a fallback.
_LEGACY = "manufacturing/packaging_log.json"

# Realistic, chip-agnostic assembly content.  No assembly-house schema is
# assumed — only a package type and a positive unit population.
_LOG_DOC = {"package_type": "QFN-48", "units": 1200, "lot_id": "ASM-7"}


def _run(project: Path):
    out = project / "report.json"
    rc = mod.main([str(project), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


def _write(project: Path, rel: str, doc):
    f = project / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(doc if isinstance(doc, str) else json.dumps(doc))


# ======================================================================
# DISCRIMINATORS — d5, the search path
# ======================================================================
def test_canonical_flow_declared_path_is_searched(tmp_path):
    """DISCRIMINATOR (d5). A packaging log at the path the flow declares
    must reach the gate.  Pre-fix: SKIP/rc=2 -> VACUOUS_PASS."""
    _write(tmp_path, _CANONICAL, _LOG_DOC)
    rc, rep = _run(tmp_path)
    assert rc == 0, f"canonical layout must not SKIP; got rc={rc} {rep}"
    assert rep["verdict"] == "PASS"
    assert rep["missing"] == []
    assert rep["found"] == [_CANONICAL]


def test_canonical_path_is_the_first_candidate(tmp_path):
    """DISCRIMINATOR (d5). A project carrying BOTH layouts is judged on the
    canonical one."""
    _write(tmp_path, _CANONICAL, _LOG_DOC)
    _write(tmp_path, _LEGACY, "null")           # garbage legacy copy
    rc, rep = _run(tmp_path)
    assert rc == 0 and rep["verdict"] == "PASS"
    assert rep["found"] == [_CANONICAL]


def test_missing_list_names_the_declared_path(tmp_path):
    """DISCRIMINATOR (d5). When the log is absent, the gate must report the
    path the flow actually declares, not a legacy one nobody produces."""
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["missing"] == [_CANONICAL]


# ======================================================================
# DISCRIMINATORS — d2, the substance predicate
# ======================================================================
def test_json_null_packaging_log_fails(tmp_path):
    """DISCRIMINATOR (d2). Measured on v1.7.36: this exact fixture returned
    PASS/rc=0.  Placed at the LEGACY path so the assertion isolates the
    substance defect from the path defect."""
    _write(tmp_path, _LEGACY, "null")
    rc, rep = _run(tmp_path)
    assert rc == 1, f"a JSON null must not certify packaging; got rc={rc}"
    assert rep["verdict"] == "FAIL"
    assert any(f["rule"] == "PACKAGING_LOG_NOT_OBJECT" for f in rep["findings"])


def test_unparseable_packaging_log_fails(tmp_path):
    """DISCRIMINATOR (d2)."""
    _write(tmp_path, _LEGACY, "not json at all -- garbage")
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert any(f["rule"] == "PACKAGING_LOG_UNPARSEABLE" for f in rep["findings"])


def test_zero_byte_packaging_log_fails(tmp_path):
    """DISCRIMINATOR (d2). A 0-byte file attests to nothing."""
    _write(tmp_path, _LEGACY, "")
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert any(f["rule"] == "PACKAGING_LOG_EMPTY" for f in rep["findings"])


def test_empty_object_packaging_log_fails(tmp_path):
    """DISCRIMINATOR (d2)."""
    _write(tmp_path, _LEGACY, {})
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert any(f["rule"] == "PACKAGING_LOG_EMPTY" for f in rep["findings"])


def test_lots_only_without_package_type_fails(tmp_path):
    """DISCRIMINATOR (d2).  THIS REPLACES the old ``test_pass_when_required_
    file_present``, which asserted PASS for exactly this fixture and
    therefore encoded the defect as expected behaviour.  ``{"lots":
    [1,2,3]}`` records a population but names no package — step 42 signs off
    an assembly process, so the package type is not optional."""
    _write(tmp_path, _LEGACY, {"lots": [1, 2, 3]})
    rc, rep = _run(tmp_path)
    assert rc == 1, "a packaging log naming no package type must not PASS"
    assert rep["verdict"] == "FAIL"
    rules = {f["rule"] for f in rep["findings"]}
    assert "PACKAGE_TYPE_MISSING" in rules
    # The lot list IS a valid population — only the package type is missing.
    assert "UNIT_COUNT_MISSING" not in rules


def test_no_unit_population_fails(tmp_path):
    """DISCRIMINATOR (d2). A package type with no population attests to no
    assembled parts."""
    _write(tmp_path, _LEGACY, {"package_type": "WLCSP-16"})
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert any(f["rule"] == "UNIT_COUNT_MISSING" for f in rep["findings"])


def test_zero_units_packaged_fails(tmp_path):
    """DISCRIMINATOR (d2). Zero assembled parts cannot be signed off — the
    same rule final_test_attestation_check applies to good-die counts."""
    _write(tmp_path, _LEGACY, {"package_type": "QFN-48", "units": 0})
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert any(f["rule"] == "ZERO_UNITS_PACKAGED" for f in rep["findings"])


def test_waiver_does_not_excuse_a_present_substanceless_artefact(tmp_path):
    """DISCRIMINATOR (d2). A waiver covers a step that did not run.  It must
    not launder a packaging log that IS there and says nothing."""
    _write(tmp_path, _LEGACY, "null")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{"id": "packaging_intake", "ticket": "TKT-101",
                          "reason": "deferred to assembly house"}]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"


# ======================================================================
# PASS paths — the gate must still certify genuine packaging data
# ======================================================================
def test_pass_when_packaging_log_has_real_facts(tmp_path):
    """DISCRIMINATOR (d5) + positive control for d2."""
    _write(tmp_path, _CANONICAL, _LOG_DOC)
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["parsed"]["package_type"] == "QFN-48"
    assert rep["parsed"]["unit_count"] == 1200


def test_nested_packaging_shape_accepted(tmp_path):
    """DISCRIMINATOR (d5). chip-AGNOSTIC: assembly houses nest differently.
    ``{"package": {"type": ...}}`` must read as a package type, and a
    non-empty lot list as the population."""
    _write(tmp_path, _CANONICAL,
           {"package": {"type": "FC-CSP"},
            "lots": [{"lot_id": "A"}, {"lot_id": "B"}]})
    rc, rep = _run(tmp_path)
    assert rc == 0, f"nested packaging shape must PASS; got {rep}"
    assert rep["verdict"] == "PASS"


def test_legacy_layout_still_accepted(tmp_path):
    """GUARD (direction-1). The legacy ``manufacturing/`` prefix keeps
    working, so no hand-built project layout regresses."""
    _write(tmp_path, _LEGACY, _LOG_DOC)
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["found"] == [_LEGACY]


# ======================================================================
# GUARDS (direction-1) — behaviour that must NOT change
# ======================================================================
def test_skip_when_required_file_missing(tmp_path):
    """GUARD. Absent artefact stays SKIP/rc=2 (the 'input not applicable'
    convention).  Pre-silicon runs must not start failing step 42; PR #455's
    ALL-of-N required_outputs rule downgrades that tier to MISSING."""
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"


def test_waived_when_step_waived(tmp_path):
    """GUARD. The waivers.json path for a genuinely absent artefact."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "packaging_intake",
            "ticket": "TKT-101",
            "reason": "packaging deferred to assembly house",
        }]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "WAIVED"
    assert rep["waiver"]["ticket"] == "TKT-101"


def test_waiver_matched_by_ticket_substring(tmp_path):
    """GUARD. _step_waived also matches if step_label appears in the ticket."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": "something_else",
            "ticket": "covers packaging_intake too",
            "reason": "bundled waiver",
        }]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "WAIVED"


def test_missing_project_dir(tmp_path):
    """GUARD. Project dir absent → operational rc 2."""
    rc = mod.main([str(tmp_path / "nope")])
    assert rc == 2


def test_malformed_waivers_json_falls_back_to_skip(tmp_path):
    """GUARD. Garbage waivers.json must not crash; _load_waivers swallows."""
    (tmp_path / "waivers.json").write_text("{ not valid json")
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"


def test_report_schema_keys_preserved(tmp_path):
    """GUARD. required_files / found / missing / waiver / verdict are the
    documented report keys; they must survive."""
    _write(tmp_path, _CANONICAL, _LOG_DOC)
    _rc, rep = _run(tmp_path)
    for key in ("gate", "verdict", "step_label", "required_files", "found",
                "missing", "waiver", "rationale_when_skipped", "findings"):
        assert key in rep, f"report lost key {key!r}"
