#!/usr/bin/env python3
"""Bidirectional tests for l22_coverage_goal_emit.py.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. The headline assertion runs
in BOTH directions against the REAL consumer gate
(`l22_verification_plan_measurable_check`):

    defect  — the design states a measurable coverage target, emitter
              NOT run                       => gate FAILs (rc 1,
                                               TARGET_OUTSIDE_CONSUMING_LAYER)
    fixed   — same fixture, emitter run     => gate PASSes (rc 0)

The write-LOCATION is asserted separately and deliberately. `l_doc_fields`
merges the nested `fields` payload OVER the top level, so writing
`coverage_goals` at the top level while `fields` carries its own empty
list is a silent no-op — the emitter reports success and the gate still
reads []. That was MEASURED during development, so it gets its own test.

All fixtures are SYNTHESIZED neutral data. No real design's files are
copied, and no design name, PDK name or vendor part number appears.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "l22_coverage_goal_emit.py"
_GATE = _HERE.parent / "l22_verification_plan_measurable_check.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


mod = _load(_PROG, "l22_coverage_goal_emit")
_gate = _load(_GATE, "l22_verification_plan_measurable_check") \
    if _GATE.is_file() else None
_needs_gate = pytest.mark.skipif(
    _gate is None, reason=f"consumer gate absent: {_GATE.name}")


# A stated, measurable, REQUIREMENT-FRAMED coverage target. The framing
# word ("must") is load-bearing: the gate deliberately ignores a bare
# percentage, which is usually a status report about somebody else's
# achieved coverage rather than a requirement for this design.
_DOC_WITH_TARGET = (
    "# Verification\n"
    "The block must reach at least 95% branch coverage on the random run.\n"
)
_DOC_WITH_TARGET_INFORMATIONAL = (
    "# Verification\n"
    "The block must reach at least 95% branch coverage on the random run "
    "(informational only; this is not a sign-off gate).\n"
)
_DOC_NO_TARGET = (
    "# Verification\n"
    "The block shall be verified against a golden model for all operands.\n"
)


def _mk(project: Path, doc_text: str, *, fields_payload=True,
        goals=None):
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    inner = {
        "coverage_goals": goals if goals is not None else [],
        "formal_properties": [],
        "verification_plan_present": "implicit",
        "verification_categories_derived_from_spec": ["a", "b"],
    }
    doc = {"doc_id": "L22", "doc_name": "L22_VERIFICATION_PLAN",
           "applicability": "APPLICABLE",
           "extraction_status": "NOT_YET_EXTRACTED"}
    if fields_payload:
        doc["fields"] = inner
    else:
        doc.update(inner)
    (gd / "L22_VERIFICATION_PLAN.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    d = project / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L7_verification.md").write_text(doc_text, encoding="utf-8")


def _effective_goals(project: Path):
    """Read goals exactly as the gate's l_doc_fields() would see them."""
    doc = json.loads((project / "phase1" / "generated_docs"
                      / "L22_VERIFICATION_PLAN.json").read_text(
        encoding="utf-8"))
    merged = {k: v for k, v in doc.items() if k != "fields"}
    if isinstance(doc.get("fields"), dict):
        merged.update(doc["fields"])
    return merged.get("coverage_goals")


# ============================================================ BIDIRECTIONAL
@_needs_gate
def test_defect_direction_gate_fails_without_emitter(tmp_path):
    _mk(tmp_path, _DOC_WITH_TARGET)
    v = _gate.inspect(tmp_path)
    assert v["verdict"] == "FAIL", v
    ids = [f["id"] for f in v["blocking_findings"]]
    assert "TARGET_OUTSIDE_CONSUMING_LAYER" in ids, v


@_needs_gate
def test_fixed_direction_gate_passes_after_emitter(tmp_path):
    _mk(tmp_path, _DOC_WITH_TARGET)
    rep = mod.run(tmp_path)
    assert rep["emitted_count"] == 1, rep
    v = _gate.inspect(tmp_path)
    assert v["verdict"] == "PASS", v
    assert v["blocking_findings"] == [], v


# ======================================================== WRITE LOCATION
def test_writes_into_the_payload_the_consumer_reads(tmp_path):
    """`fields` shadows the top level — writing there is a silent no-op."""
    _mk(tmp_path, _DOC_WITH_TARGET, fields_payload=True)
    mod.run(tmp_path)
    eff = _effective_goals(tmp_path)
    assert eff and len(eff) == 1, (
        "goal did not land where l_doc_fields() reads: %r" % eff)
    assert eff[0]["target_pct"] == 95.0


def test_flat_doc_without_fields_is_also_supported(tmp_path):
    _mk(tmp_path, _DOC_WITH_TARGET, fields_payload=False)
    mod.run(tmp_path)
    eff = _effective_goals(tmp_path)
    assert eff and eff[0]["target_pct"] == 95.0, eff


# ================================================================= CONTENT
def test_emits_comparable_numeric_target_and_name(tmp_path):
    _mk(tmp_path, _DOC_WITH_TARGET)
    g = mod.run(tmp_path)["emitted"][0]
    assert g["target_pct"] == 95.0
    assert "coverage" in g["name"]
    assert g["evidence"]


def test_signoff_qualifier_is_preserved(tmp_path):
    """A target the design marks informational must NOT become blocking."""
    _mk(tmp_path, _DOC_WITH_TARGET_INFORMATIONAL)
    g = mod.run(tmp_path)["emitted"][0]
    assert g["signoff_gate"] is False, g


def test_unqualified_target_defaults_to_signoff(tmp_path):
    _mk(tmp_path, _DOC_WITH_TARGET)
    g = mod.run(tmp_path)["emitted"][0]
    assert g["signoff_gate"] is True, g


# ================================================================ REFUSALS
def test_refuses_when_design_states_no_target(tmp_path):
    """No stated target => emit nothing. A fabricated goal would turn a
    real gap into a false PASS."""
    _mk(tmp_path, _DOC_NO_TARGET)
    rep = mod.run(tmp_path)
    assert rep["emitted_count"] == 0, rep
    assert _effective_goals(tmp_path) == []


def test_never_modifies_an_existing_goal(tmp_path):
    pre = [{"name": "functional coverage", "target_pct": 80.0}]
    _mk(tmp_path, _DOC_WITH_TARGET, goals=pre)
    mod.run(tmp_path)
    eff = _effective_goals(tmp_path)
    assert eff[0] == pre[0], eff


def test_is_idempotent(tmp_path):
    _mk(tmp_path, _DOC_WITH_TARGET)
    mod.run(tmp_path)
    n1 = len(_effective_goals(tmp_path))
    mod.run(tmp_path)
    n2 = len(_effective_goals(tmp_path))
    assert n1 == n2 == 1


def test_dry_run_writes_nothing(tmp_path):
    _mk(tmp_path, _DOC_WITH_TARGET)
    rep = mod.run(tmp_path, dry_run=True)
    assert rep["emitted_count"] == 1
    assert rep["doc_written"] is None
    assert _effective_goals(tmp_path) == []


def test_missing_l22_is_a_skip_not_a_crash(tmp_path):
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    rep = mod.run(tmp_path)
    assert rep["status"] == "SKIPPED"
    assert rep["emitted_count"] == 0


# =============================================================== HELPERS
@pytest.mark.parametrize("text,want", [
    ("95% branch coverage", "branch coverage"),
    ("toggle coverage of 90%", "toggle coverage"),
    ("statement coverage 88%", "statement coverage"),
    ("coverage 70%", "coverage"),
    ("no vocabulary here", None),
])
def test_metric_name_extraction(text, want):
    assert mod._metric_name(text) == want


@pytest.mark.parametrize("text,want", [
    ("at least 95%", 95.0), ("99.5 %", 99.5), ("100%", 100.0),
    ("no percent", None), ("140%", None),
])
def test_percentage_extraction(text, want):
    assert mod._pct(text) == want
