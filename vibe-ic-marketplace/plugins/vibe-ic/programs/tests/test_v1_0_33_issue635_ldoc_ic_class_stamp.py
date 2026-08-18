"""Regression for ORGANIC #635 — a per-L-doc ic_class stamp can diverge from
the detected/persisted class, and the canonical ic_class consistency gate never
cross-checked the L14-L23 skeleton ic_class field.

現象 (round-2 v1.0.22 6-IC clean-room): a data-converter IC whose authoritative
ic_class is only resolved/persisted in phase2 (reports/ic_class.json). The
L14-L23 (L19-L23) skeletons are stamped during phase1 BEFORE that persist, when
`canonical_ic_class()` reads an absent file → "unknown" and a mid-emission
fallback resolves a wrong class (digital_arithmetic_primitive). The frozen
wrong stamp survives to disk; `ic_class_consistency_check.py` only re-ran
detect_ic_class() vs facts.yaml and NEVER read the per-L-doc stamp, so the
drift PASSed uncaught.

Fix (two chip-agnostic parts):
  (1) ORDERING — `phase1_post_process.restamp_l_doc_skeletons(project)`
      re-stamps any L*.json whose top-level ic_class diverges from the now-
      authoritative reports/ic_class.json; wired into the phase2 authoritative
      detect step (right after reports/ic_class.json is re-persisted).
  (2) GATE — `ic_class_consistency_check.inspect()` now iterates
      phase1/generated_docs/L*.json and FAILs when a stamped ic_class diverges
      from the inferred/persisted class (the canonical gate now enforces the
      L-doc stamp it claims to own).

NEGATIVE no-leak: (a) a matching stamp PASSes (no false fire); (b) a doc that
omits ic_class (or carries a non-string/empty value) is SKIPped; (c) re-stamp
is a no-op when the authoritative class is unknown (cannot prove drift) or when
nothing diverges; (d) re-stamp never ADDS the field to a doc that omits it.

chip-AGNOSTIC: structural field comparison; no chip/vendor/SKU literal.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_post_process as PP  # noqa: E402

_GATE = _PROGRAMS / "ic_class_consistency_check.py"


def _project(tmp_path, authoritative, stamps):
    """Defect-artifact fixture: a project whose reports/ic_class.json says
    `authoritative` and whose L*.json docs carry `stamps` ({filename: doc})."""
    p = tmp_path / "proj"
    (p / "reports").mkdir(parents=True)
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (p / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": authoritative, "has_analog": True}))
    for fname, doc in stamps.items():
        (gd / fname).write_text(json.dumps(doc))
    return p


def _gate(project):
    return subprocess.run([sys.executable, str(_GATE), str(project)],
                          capture_output=True, text=True)


# ── (2) GATE: catches a divergent per-L-doc stamp ────────────────────────────

def test_gate_fails_on_divergent_stamp(tmp_path):
    p = _project(tmp_path, "data_converter", {
        "L19_CONSTRAINTS_PDK.json":
            {"ic_class": "digital_arithmetic_primitive"},
        "L21_POWER_INTENT.json":
            {"ic_class": "digital_arithmetic_primitive"}})
    r = _gate(p)
    assert r.returncode == 1
    assert "diverged from the authoritative class" in r.stdout


def test_gate_passes_on_matching_stamp_NOLEAK(tmp_path):
    p = _project(tmp_path, "data_converter", {
        "L19_CONSTRAINTS_PDK.json": {"ic_class": "data_converter"}})
    assert _gate(p).returncode == 0


def test_gate_skips_doc_omitting_ic_class_NOLEAK(tmp_path):
    """A doc that legitimately omits ic_class (or has empty/non-string) must
    NOT trigger a false FAIL."""
    p = _project(tmp_path, "data_converter", {
        "L5_ADI_SPEC.json": {"analog_blocks": []},          # omits ic_class
        "L7.json": {"ic_class": ""},                        # empty string
        "L8.json": {"ic_class": 123}})                      # non-string
    assert _gate(p).returncode == 0


# ── (1) RE-STAMP: fixes the divergent docs at the phase2 boundary ────────────

def test_restamp_rewrites_only_divergent(tmp_path):
    p = _project(tmp_path, "data_converter", {
        "L19.json": {"ic_class": "digital_arithmetic_primitive"},
        "L20.json": {"ic_class": "data_converter"},          # matching
        "L5.json": {"analog_blocks": []}})                   # omits
    rewritten = {s.split("/")[-1] for s in PP.restamp_l_doc_skeletons(p)}
    assert rewritten == {"L19.json"}
    # the divergent doc is now the authoritative class
    d19 = json.loads((p / "phase1/generated_docs/L19.json").read_text())
    assert d19["ic_class"] == "data_converter"
    # the omitting doc was NOT given an ic_class field
    d5 = json.loads((p / "phase1/generated_docs/L5.json").read_text())
    assert "ic_class" not in d5


def test_restamp_then_gate_passes(tmp_path):
    p = _project(tmp_path, "data_converter", {
        "L19.json": {"ic_class": "digital_arithmetic_primitive"}})
    assert _gate(p).returncode == 1          # diverged before
    PP.restamp_l_doc_skeletons(p)
    assert _gate(p).returncode == 0          # fixed after


def test_restamp_noop_on_matching_NOLEAK(tmp_path):
    p = _project(tmp_path, "data_converter", {
        "L19.json": {"ic_class": "data_converter"}})
    assert PP.restamp_l_doc_skeletons(p) == []


def test_restamp_noop_when_authoritative_unknown_NOLEAK(tmp_path):
    """When the authoritative class is `unknown` (not yet resolved) the
    re-stamp cannot prove drift and must be a no-op."""
    p = _project(tmp_path, "unknown", {
        "L19.json": {"ic_class": "digital_arithmetic_primitive"}})
    assert PP.restamp_l_doc_skeletons(p) == []
    # the stamp is left untouched
    assert json.loads((p / "phase1/generated_docs/L19.json").read_text())[
        "ic_class"] == "digital_arithmetic_primitive"


def test_restamp_none_project_NOLEAK():
    assert PP.restamp_l_doc_skeletons(None) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
