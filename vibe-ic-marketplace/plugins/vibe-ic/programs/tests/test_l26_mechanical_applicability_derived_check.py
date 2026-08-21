#!/usr/bin/env python3
"""Smoke tests for l26_mechanical_applicability_derived_check.py — batch-8.

NEGATIVE CONTROL IS THE POINT OF THIS FILE. Every rule is asserted in BOTH
directions: a deliberately-gutted layer must FAIL, and the well-formed
counterpart must PASS.

All fixtures are SYNTHESIZED neutral data. No real design's files are copied,
and no real design/PDK/vendor token appears here.

ONE BRANCH NEEDS AN IN-PROCESS TEST, DELIBERATELY
-------------------------------------------------
The FALSE-N/A branch (taxonomy says APPLICABLE, layer asserts N/A) is the most
important rule in the gate, but it is UNREACHABLE through the subprocess today:
``l_doc_taxonomy.is_applicable(cls, "L26")`` is False for every registered
class and for the unknown fallback, because L26 is OPT-IN-ONLY and no MEMS
class exists yet (``test_l24_l27_completeness.py`` pins that invariant). So it
is exercised in-process with ``is_applicable`` monkeypatched to simulate the
future MEMS class. That is stated openly rather than skipped — an untested
rule that only fires on a design class nobody has built yet is exactly the
kind of code that rots into a false clean bill of health.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
PROG = _PROGRAMS / "l26_mechanical_applicability_derived_check.py"

sys.path.insert(0, str(_PROGRAMS))
gate = importlib.import_module("l26_mechanical_applicability_derived_check")

_FAIL = 1
_PASS = 0
_SKIP = 2

_SYNTH_CLASS = "synthetic_block_class_alpha"
_OTHER_CLASS = "synthetic_block_class_beta"


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make(tmp_path, l26=None, siblings=True, ic_class=_SYNTH_CLASS,
          persisted_class=None, name="synthetic_project") -> Path:
    proj = tmp_path / name
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    if l26 is not None:
        (gd / "L26_MECHANICAL_TRANSDUCTION.json").write_text(
            json.dumps(l26, indent=2))
    if siblings:
        # The run's own class premise, as sibling L-docs record it.
        for stem in ("L1_DATASHEET", "L2_FRS"):
            (gd / f"{stem}.json").write_text(json.dumps({
                "doc_id": stem.split("_")[0], "doc_name": stem,
                "applicability": "APPLICABLE", "ic_class": ic_class,
                "fields": {}, "extraction_evidence": {},
            }))
    if persisted_class is not None:
        rp = proj / "reports"
        rp.mkdir(parents=True, exist_ok=True)
        (rp / "ic_class.json").write_text(
            json.dumps({"ic_class": persisted_class}))
    return proj


def _good_na_l26(ic_class=_SYNTH_CLASS) -> dict:
    """The shape 24/24 sampled real Phase-1 runs actually emit, and the
    correct one: an honest, derived N/A stub."""
    return {
        "doc_id": "L26",
        "doc_name": "L26_MECHANICAL_TRANSDUCTION",
        "applicability": "N/A",
        "ic_class": ic_class,
        "rationale": "No MEMS/mechanical transduction in this class",
        "extraction_evidence": {},
        "emitted_by": "l_doc_taxonomy.na_stub",
    }


# ===========================================================================
# POSITIVE DIRECTION — a derived, honest verdict must PASS
# ===========================================================================
class TestWellFormedPasses:
    def test_derived_na_stub_passes(self, tmp_path):
        proj = _make(tmp_path, l26=_good_na_l26())
        r = _run(proj)
        assert r.returncode == _PASS, r.stdout + r.stderr
        assert "[PASS]" in r.stdout

    def test_passes_when_premise_comes_from_persisted_ic_class(self, tmp_path):
        proj = _make(tmp_path, l26=_good_na_l26(),
                     persisted_class=_SYNTH_CLASS)
        r = _run(proj)
        assert r.returncode == _PASS, r.stdout
        assert "reports/ic_class.json" in r.stdout

    def test_gate_does_not_mutate_the_run_it_audits(self, tmp_path):
        """A gate that persists an ic_class inference changes the run's own
        premise. Must never happen."""
        proj = _make(tmp_path, l26=_good_na_l26())
        assert not (proj / "reports" / "ic_class.json").exists()
        r = _run(proj)
        assert r.returncode == _PASS, r.stdout
        assert not (proj / "reports" / "ic_class.json").exists(), \
            "the gate wrote reports/ic_class.json — it mutated the run"


# ===========================================================================
# NEGATIVE CONTROL — subprocess-reachable gutted variants must FAIL
# ===========================================================================
class TestGuttedLayerFails:
    def test_applicability_asserted_against_the_taxonomy(self, tmp_path):
        """Opt-in-only L26 opting in for a class that does not want it —
        the empty-skeleton-on-a-non-MEMS-chip case _OPT_IN_ONLY_CODES exists
        to prevent."""
        doc = _good_na_l26()
        doc["applicability"] = "APPLICABLE"
        doc.pop("rationale")
        proj = _make(tmp_path, l26=doc)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "OPT-IN-ONLY" in r.stdout

    def test_stale_premise_class_mismatch(self, tmp_path):
        """The verdict was computed against a different class than the run's."""
        doc = _good_na_l26(ic_class=_OTHER_CLASS)
        proj = _make(tmp_path, l26=doc, ic_class=_SYNTH_CLASS)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "stale premise" in r.stdout

    def test_persisted_class_wins_over_sibling_docs(self, tmp_path):
        doc = _good_na_l26(ic_class=_SYNTH_CLASS)
        proj = _make(tmp_path, l26=doc, ic_class=_SYNTH_CLASS,
                     persisted_class=_OTHER_CLASS)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "stale premise" in r.stdout

    def test_layer_with_no_ic_class_is_unfalsifiable(self, tmp_path):
        doc = _good_na_l26()
        doc.pop("ic_class")
        proj = _make(tmp_path, l26=doc)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "unfalsifiable" in r.stdout

    def test_na_without_rationale_is_a_silent_stub(self, tmp_path):
        doc = _good_na_l26()
        doc.pop("rationale")
        proj = _make(tmp_path, l26=doc)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "rationale" in r.stdout

    def test_uninterpretable_applicability_verdict(self, tmp_path):
        doc = _good_na_l26()
        doc["applicability"] = "probably not relevant"
        proj = _make(tmp_path, l26=doc)
        r = _run(proj)
        assert r.returncode == _FAIL, r.stdout
        assert "uninterpretable" in r.stdout


# ===========================================================================
# No-false-positive direction
# ===========================================================================
class TestRealRunShapeIsSilent:
    def test_missing_layer_skips(self, tmp_path):
        proj = _make(tmp_path)
        r = _run(proj)
        assert r.returncode == _SKIP

    def test_no_ic_class_premise_anywhere_skips_rather_than_guesses(self, tmp_path):
        proj = _make(tmp_path, l26=_good_na_l26(), siblings=False)
        r = _run(proj)
        assert r.returncode == _SKIP, r.stdout
        assert "no ic_class premise recorded by the run" in r.stdout

    def test_nonexistent_project_dir_skips(self, tmp_path):
        r = _run(tmp_path / "no_such_dir")
        assert r.returncode == _SKIP


# ===========================================================================
# The FALSE-N/A branch — the rule that matters most, exercised in-process
# because no MEMS class exists yet (see module docstring).
# ===========================================================================
class TestFalseNaBranch:
    def test_false_na_fails_when_taxonomy_says_applicable(self, tmp_path,
                                                          monkeypatch):
        proj = _make(tmp_path, l26=_good_na_l26())
        layer = (proj / "phase1" / "generated_docs"
                 / "L26_MECHANICAL_TRANSDUCTION.json")

        monkeypatch.setattr(gate.tx, "is_applicable",
                            lambda cls, code: True)
        verdict, msgs = gate._check_one(proj, layer)
        assert verdict == "FAIL", msgs
        joined = " ".join(msgs)
        assert "FALSE N/A" in joined
        assert _SYNTH_CLASS in joined

    def test_same_layer_passes_when_taxonomy_says_not_applicable(self, tmp_path):
        """The other direction on the SAME fixture — proves the FAIL above is
        caused by the derivation, not by the fixture."""
        proj = _make(tmp_path, l26=_good_na_l26())
        layer = (proj / "phase1" / "generated_docs"
                 / "L26_MECHANICAL_TRANSDUCTION.json")
        verdict, _msgs = gate._check_one(proj, layer)
        assert verdict == "PASS"

    def test_applicable_but_inert_layer_fails(self, tmp_path, monkeypatch):
        """An APPLICABLE layer that hands its consumer nothing is the exact
        shape of the defect this batch exists to prevent."""
        doc = _good_na_l26()
        doc["applicability"] = "APPLICABLE"
        doc.pop("rationale")
        doc["fields"] = {"movable_structure_geometry": None,
                         "transduction_principle": None}
        doc["extraction_status"] = "NOT_YET_EXTRACTED"
        proj = _make(tmp_path, l26=doc)
        layer = (proj / "phase1" / "generated_docs"
                 / "L26_MECHANICAL_TRANSDUCTION.json")

        monkeypatch.setattr(gate.tx, "is_applicable", lambda cls, code: True)
        verdict, msgs = gate._check_one(proj, layer)
        assert verdict == "FAIL", msgs
        assert "APPLICABLE-but-inert" in " ".join(msgs)

    def test_applicable_with_narrative_geometry_fails(self, tmp_path,
                                                      monkeypatch):
        doc = _good_na_l26()
        doc["applicability"] = "APPLICABLE"
        doc.pop("rationale")
        doc["fields"] = {
            "movable_structure_geometry": "a thin suspended plate",
            "transduction_principle": "capacitive",
        }
        proj = _make(tmp_path, l26=doc)
        layer = (proj / "phase1" / "generated_docs"
                 / "L26_MECHANICAL_TRANSDUCTION.json")

        monkeypatch.setattr(gate.tx, "is_applicable", lambda cls, code: True)
        verdict, msgs = gate._check_one(proj, layer)
        assert verdict == "FAIL", msgs
        assert "no number bound to a unit" in " ".join(msgs)

    def test_applicable_without_transduction_principle_fails(self, tmp_path,
                                                             monkeypatch):
        doc = _good_na_l26()
        doc["applicability"] = "APPLICABLE"
        doc.pop("rationale")
        doc["fields"] = {
            "movable_structure_geometry": "suspended plate 220 um x 220 um, "
                                          "gap 2.0 um",
        }
        proj = _make(tmp_path, l26=doc)
        layer = (proj / "phase1" / "generated_docs"
                 / "L26_MECHANICAL_TRANSDUCTION.json")

        monkeypatch.setattr(gate.tx, "is_applicable", lambda cls, code: True)
        verdict, msgs = gate._check_one(proj, layer)
        assert verdict == "FAIL", msgs
        assert "transduction principle" in " ".join(msgs)

    def test_well_formed_applicable_layer_passes(self, tmp_path, monkeypatch):
        """The POSITIVE control for the whole APPLICABLE branch."""
        doc = _good_na_l26()
        doc["applicability"] = "APPLICABLE"
        doc.pop("rationale")
        doc["fields"] = {
            "movable_structure_geometry": "suspended plate 220 um x 220 um, "
                                          "gap 2.0 um, thickness 1.5 um",
            "transduction_principle": "capacitive differential sensing",
            "package_mechanical_stress": "40 MPa",
        }
        doc["extraction_status"] = "EXTRACTED"
        proj = _make(tmp_path, l26=doc)
        layer = (proj / "phase1" / "generated_docs"
                 / "L26_MECHANICAL_TRANSDUCTION.json")

        monkeypatch.setattr(gate.tx, "is_applicable", lambda cls, code: True)
        verdict, msgs = gate._check_one(proj, layer)
        assert verdict == "PASS", msgs


# ===========================================================================
# Both directions on the SAME layer, through the real subprocess.
# ===========================================================================
def test_negative_control_both_directions_on_the_same_layer(tmp_path):
    good = _make(tmp_path, l26=_good_na_l26(), name="good")

    gutted_doc = _good_na_l26()
    gutted_doc.pop("rationale")
    gutted_doc["ic_class"] = _OTHER_CLASS
    gutted = _make(tmp_path, l26=gutted_doc, ic_class=_SYNTH_CLASS,
                   name="gutted")

    r_good = _run(good)
    r_gutted = _run(gutted)

    assert r_good.returncode == _PASS, f"well-formed must PASS: {r_good.stdout}"
    assert r_gutted.returncode == _FAIL, f"gutted must FAIL: {r_gutted.stdout}"
    assert r_good.returncode != r_gutted.returncode


def test_taxonomy_invariant_this_gate_depends_on_still_holds():
    """If a MEMS class is ever added, L26 stops being N/A-for-everything and
    the FALSE-N/A branch becomes subprocess-reachable. Assert the current
    invariant so that change is noticed here, not discovered in the field."""
    tx = importlib.import_module("l_doc_taxonomy")
    for cls in list(tx.IC_CLASS_APPLICABILITY) + ["unknown", _SYNTH_CLASS]:
        assert tx.is_applicable(cls, "L26") is False, (
            f"{cls} now declares L26 applicable — the FALSE-N/A branch of "
            f"l26_mechanical_applicability_derived_check is now reachable "
            f"through the subprocess and should get a subprocess test")
