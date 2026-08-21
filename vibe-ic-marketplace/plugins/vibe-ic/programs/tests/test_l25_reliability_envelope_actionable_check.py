#!/usr/bin/env python3
"""Smoke tests for l25_reliability_envelope_actionable_check.py — batch-8.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. Every rule is asserted in BOTH
directions: a deliberately-gutted layer must FAIL, and the well-formed
counterpart must PASS.

All fixtures are SYNTHESIZED neutral data. No real design's files are copied;
no real design, PDK or vendor token appears anywhere in this file. The
"qualification standard" strings below are invented placeholders on purpose —
the gate never matches a standards name, it only requires traceability.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l25_reliability_envelope_actionable_check.py")

_FAIL = 1
_PASS = 0
_SKIP = 2

_SYNTH_CLASS = "synthetic_block_class_alpha"
_SRC = "phase1/input_doc/synthetic_reliability_section.txt"

# Synthesized source text — the only place any figure legitimately comes from.
_SRC_TEXT = (
    "SYNTHETIC RELIABILITY SECTION (neutral fixture)\n"
    "operating temperature range: -40 degC to 125 degC\n"
    "qualification programme: SYNTH-QUAL-REV-B\n"
    "electromigration budget: 1.2 mA/um\n"
    "aging margin allowance: 8 %\n"
    "mission: continuous duty, key-on/key-off cycling\n"
)


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make(tmp_path, l25=None, src_text=_SRC_TEXT, extra_docs=None,
          name="synthetic_project") -> Path:
    proj = tmp_path / name
    (proj / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    if src_text is not None:
        p = proj / _SRC
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src_text)
    if l25 is not None:
        (proj / "phase1" / "generated_docs"
         / "L25_RELIABILITY_MISSION_PROFILE.json").write_text(
            json.dumps(l25, indent=2))
    for fname, doc in (extra_docs or {}).items():
        (proj / "phase1" / "generated_docs" / fname).write_text(json.dumps(doc))
    return proj


def _good_l25() -> dict:
    return {
        "doc_id": "L25",
        "doc_name": "L25_RELIABILITY_MISSION_PROFILE",
        "applicability": "APPLICABLE",
        "ic_class": _SYNTH_CLASS,
        "fields": {
            "mission_profile": "continuous duty, key-on/key-off cycling",
            "temp_range": "-40 degC to 125 degC",
            "qual_standard": "SYNTH-QUAL-REV-B",
            "em_budget": "1.2 mA/um",
            "aging_margin": "8 %",
        },
        "extraction_status": "EXTRACTED",
        "extraction_evidence": {
            _SRC: [
                {"literal": "operating temperature range: -40 degC to 125 degC",
                 "label": "temp_range"},
                {"literal": "qualification programme: SYNTH-QUAL-REV-B",
                 "label": "qual_standard"},
                {"literal": "electromigration budget: 1.2 mA/um",
                 "label": "em_budget"},
                {"literal": "aging margin allowance: 8 %",
                 "label": "aging_margin"},
                {"literal": "mission: continuous duty, key-on/key-off cycling",
                 "label": "mission_profile"},
            ],
        },
    }


def _inert_l25() -> dict:
    """The shape 24/24 sampled real Phase-1 runs actually emit."""
    return {
        "doc_id": "L25",
        "doc_name": "L25_RELIABILITY_MISSION_PROFILE",
        "applicability": "APPLICABLE",
        "ic_class": _SYNTH_CLASS,
        "fields": {
            "mission_profile": None, "temp_range": None,
            "qual_standard": None, "em_budget": None, "aging_margin": None,
        },
        "extraction_status": "NOT_YET_EXTRACTED",
        "extraction_evidence": {},
    }


# ===========================================================================
# POSITIVE DIRECTION
# ===========================================================================
class TestWellFormedPasses:
    def test_actionable_and_traceable_layer_passes(self, tmp_path):
        proj = _make(tmp_path, l25=_good_l25())
        r = _run(proj)
        assert r.returncode == _PASS, r.stdout + r.stderr
        assert "[PASS]" in r.stdout

    def test_typed_dict_margin_form_also_passes(self, tmp_path):
        doc = _good_l25()
        doc["fields"]["aging_margin"] = {"value": 8, "unit": "%"}
        proj = _make(tmp_path, l25=doc)
        r = _run(proj)
        assert r.returncode == _PASS, r.stdout

    def test_envelope_covering_the_designs_own_temps_passes(self, tmp_path):
        """Cross-layer consistency, satisfied."""
        sibling = {"doc_id": "L19", "doc_name": "L19_CONSTRAINTS_PDK",
                   "ic_class": _SYNTH_CLASS,
                   "fields": {"corner_temp_max": "125 degC",
                              "corner_temp_min": "-40 degC"}}
        proj = _make(tmp_path, l25=_good_l25(),
                     extra_docs={"L19_CONSTRAINTS_PDK.json": sibling})
        r = _run(proj)
        assert r.returncode == _PASS, r.stdout


# ===========================================================================
# NEGATIVE CONTROL
# ===========================================================================
class TestGuttedLayerFails:
    def test_margin_with_number_but_no_unit(self, tmp_path):
        doc = _good_l25()
        doc["fields"]["aging_margin"] = "8"
        proj = _make(tmp_path, l25=doc)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "no unit" in r.stdout

    def test_margin_that_is_narrative_only(self, tmp_path):
        doc = _good_l25()
        doc["fields"]["em_budget"] = "adequate for the intended lifetime"
        proj = _make(tmp_path, l25=doc)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "no number" in r.stdout

    def test_envelope_with_only_one_bound(self, tmp_path):
        doc = _good_l25()
        doc["fields"]["temp_range"] = "up to 125 degC"
        proj = _make(tmp_path, l25=doc)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "TWO bounds" in r.stdout

    def test_envelope_bounds_without_a_unit(self, tmp_path):
        doc = _good_l25()
        doc["fields"]["temp_range"] = "-40 to 125"
        doc["extraction_evidence"][_SRC][0]["literal"] = "-40 to 125"
        proj = _make(tmp_path, l25=doc,
                     src_text=_SRC_TEXT + "\nraw envelope -40 to 125\n")
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "no unit" in r.stdout

    def test_populated_but_untraceable(self, tmp_path):
        """An un-sourced qualification figure reads authoritative and is a
        hallucination risk."""
        doc = _good_l25()
        doc["extraction_evidence"] = {}
        proj = _make(tmp_path, l25=doc)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "NO source evidence" in r.stdout

    def test_evidence_literal_absent_from_the_cited_source(self, tmp_path):
        doc = _good_l25()
        doc["extraction_evidence"][_SRC][3]["literal"] = \
            "aging margin allowance: 40 %"
        proj = _make(tmp_path, l25=doc)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "does not occur in the file" in r.stdout

    def test_envelope_narrower_than_the_designs_own_declared_temps(self, tmp_path):
        """The certificate is for a different chip than the one being built."""
        doc = _good_l25()
        doc["fields"]["temp_range"] = "0 degC to 70 degC"
        doc["extraction_evidence"][_SRC][0]["literal"] = \
            "commercial envelope 0 degC to 70 degC"
        sibling = {"doc_id": "L19", "doc_name": "L19_CONSTRAINTS_PDK",
                   "ic_class": _SYNTH_CLASS,
                   "fields": {"corner_temp_max": "125 degC"}}
        proj = _make(
            tmp_path, l25=doc,
            src_text=_SRC_TEXT + "\ncommercial envelope 0 degC to 70 degC\n",
            extra_docs={"L19_CONSTRAINTS_PDK.json": sibling})
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "does NOT cover" in r.stdout
        assert "certifies a different chip" in r.stdout

    def test_na_stub_without_rationale_fails(self, tmp_path):
        proj = _make(tmp_path, l25={
            "doc_id": "L25", "doc_name": "L25_RELIABILITY_MISSION_PROFILE",
            "applicability": "N/A", "ic_class": _SYNTH_CLASS,
            "extraction_evidence": {}})
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "rationale" in r.stdout


# ===========================================================================
# No-false-positive direction
# ===========================================================================
class TestRealRunShapeIsSilent:
    def test_inert_layer_skips(self, tmp_path):
        proj = _make(tmp_path, l25=_inert_l25())
        r = _run(proj)
        assert r.returncode == _SKIP, r.stdout
        assert "inert" in r.stdout

    def test_missing_layer_skips(self, tmp_path):
        proj = _make(tmp_path)
        r = _run(proj)
        assert r.returncode == _SKIP

    def test_na_stub_with_rationale_skips(self, tmp_path):
        proj = _make(tmp_path, l25={
            "doc_id": "L25", "doc_name": "L25_RELIABILITY_MISSION_PROFILE",
            "applicability": "N/A", "ic_class": _SYNTH_CLASS,
            "rationale": "Reliability budget is per-implementation, not "
                         "protocol-level",
            "extraction_evidence": {}})
        r = _run(proj)
        assert r.returncode == _SKIP, r.stdout

    def test_ambiguous_unit_temps_never_trigger_the_cross_check(self, tmp_path):
        """A bare number under a temp-named key could be Kelvin. Guessing
        would manufacture a false positive, so it must be ignored."""
        sibling = {"doc_id": "L19", "ic_class": _SYNTH_CLASS,
                   "fields": {"junction_temp_limit": 400,
                              "ambient_temp_note": "400"}}
        proj = _make(tmp_path, l25=_good_l25(),
                     extra_docs={"L19_CONSTRAINTS_PDK.json": sibling})
        r = _run(proj)
        assert r.returncode == _PASS, r.stdout


# ===========================================================================
# Both directions on the SAME layer.
# ===========================================================================
def test_negative_control_both_directions_on_the_same_layer(tmp_path):
    good = _make(tmp_path, l25=_good_l25(), name="good")
    gutted_doc = _good_l25()
    gutted_doc["fields"]["aging_margin"] = "significant"
    gutted_doc["fields"]["em_budget"] = "10"
    gutted = _make(tmp_path, l25=gutted_doc, name="gutted")

    r_good = _run(good)
    r_gutted = _run(gutted)

    assert r_good.returncode == _PASS, f"well-formed must PASS: {r_good.stdout}"
    assert r_gutted.returncode == _FAIL, f"gutted must FAIL: {r_gutted.stdout}"
    assert r_good.returncode != r_gutted.returncode


def test_gate_declares_itself_advisory_in_its_failure_output(tmp_path):
    """The docstring says ADVISES; the operator-facing output must say so too,
    otherwise 'advisory' is a claim only the source code makes."""
    doc = _good_l25()
    doc["fields"]["aging_margin"] = "significant"
    proj = _make(tmp_path, l25=doc)
    r = _run(proj)
    assert r.returncode == _FAIL
    assert "ADVISORY" in r.stdout
