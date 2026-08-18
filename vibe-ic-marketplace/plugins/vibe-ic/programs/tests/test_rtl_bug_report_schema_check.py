"""Unit tests for rtl_bug_report_schema_check.py (v0.54 gate).

Forces RTL-bug claims to carry traceable spec evidence; prevents agents
self-attesting both the spec AND the bug.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'rtl_bug_report_schema_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import rtl_bug_report_schema_check as gate  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
def _make_project(tmp_path, with_doc=True):
    """Build a minimal project tree: <tmp>/input/docs/spec.txt."""
    if with_doc:
        (tmp_path / "input" / "docs").mkdir(parents=True)
        (tmp_path / "input" / "docs" / "spec.pdf").write_text("dummy spec")
    return tmp_path


def _good_bug(severity="warning", **overrides):
    bug = {
        "id": "B01",
        "severity": severity,
        "module": "mac.v",
        "observed": "RTL accepts E0 writes after lock-bit set; reaches ram128x8.",
        "expected": "Spec mandates rejection of any post-lock E0 write outside engineer mode.",
        "spec_evidence": {
            "doc": "input/docs/spec.pdf",
            "locator": "FRS §6.7 Table 14",
            "quote": "Once LK bit is asserted, subsequent writes to ID region MUST be rejected.",
            "interpretation": "Plain text mandates rejection; current RTL silently writes.",
        },
        "repro": "sim/tb/tb_otp_e0_write.v case 8",
    }
    if severity == "silicon-blocking":
        bug["expected_behaviour_unambiguous"] = True
        bug["independent_review"] = "spec FRS §6.7 reviewed with vendor on 2026-04-24"
    bug.update(overrides)
    return bug


def _write_bugs(tmp_path, bugs):
    p = tmp_path / "reports" / "phase2" / "rtl_bugs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bugs, indent=2))
    return p


# ---------------------------------------------------------------------------
# load_bugs — supports list and {bugs: [...]}
# ---------------------------------------------------------------------------
def test_load_bugs_flat_list(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps([{"id": "A"}, {"id": "B"}]))
    assert len(gate.load_bugs(p)) == 2


def test_load_bugs_object_with_bugs_key(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"bugs": [{"id": "A"}], "meta": "ignored"}))
    assert len(gate.load_bugs(p)) == 1


def test_load_bugs_unknown_shape_raises(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"not_bugs": []}))
    with pytest.raises(ValueError):
        gate.load_bugs(p)


# ---------------------------------------------------------------------------
# Single-entry validation
# ---------------------------------------------------------------------------
def test_well_formed_warning_passes(tmp_path):
    proj = _make_project(tmp_path)
    problems = gate.check_entry(0, _good_bug(), proj, allow_external=False)
    assert problems == []


def test_missing_top_field_caught(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug()
    del bug["module"]
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("module" in p for p in problems)


def test_invalid_severity_caught(tmp_path):
    proj = _make_project(tmp_path)
    problems = gate.check_entry(0, _good_bug(severity="catastrophic"),
                                proj, allow_external=False)
    assert any("severity" in p for p in problems)


def test_observed_too_short_caught(tmp_path):
    proj = _make_project(tmp_path)
    problems = gate.check_entry(0, _good_bug(observed="bad"),
                                proj, allow_external=False)
    assert any("observed" in p.lower() for p in problems)


def test_expected_too_short_caught(tmp_path):
    proj = _make_project(tmp_path)
    problems = gate.check_entry(0, _good_bug(expected="ok"),
                                proj, allow_external=False)
    assert any("expected" in p.lower() for p in problems)


# ---------------------------------------------------------------------------
# spec_evidence sub-block
# ---------------------------------------------------------------------------
def test_missing_spec_evidence_caught(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug()
    del bug["spec_evidence"]
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("spec_evidence" in p for p in problems)


def test_spec_evidence_must_be_object(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug()
    bug["spec_evidence"] = "see the PDF"  # string instead of dict
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("spec_evidence" in p and "object" in p for p in problems)


def test_quote_too_short_caught(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug()
    bug["spec_evidence"]["quote"] = "see spec"
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("quote" in p for p in problems)


def test_quote_just_ellipsis_caught(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug()
    bug["spec_evidence"]["quote"] = "..."
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("ellipsis" in p for p in problems)


def test_doc_path_missing_caught(tmp_path):
    proj = _make_project(tmp_path, with_doc=False)
    problems = gate.check_entry(0, _good_bug(), proj, allow_external=False)
    assert any("not found" in p for p in problems)


def test_allow_external_docs_skips_existence(tmp_path):
    proj = _make_project(tmp_path, with_doc=False)
    problems = gate.check_entry(0, _good_bug(), proj, allow_external=True)
    assert problems == []


def test_doc_existence_suggests_similar_path(tmp_path):
    """If the named doc isn't at the cited path but a same-named file
    exists in input/docs/, mention it."""
    proj = tmp_path
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "spec.pdf").write_text("ok")
    bug = _good_bug()
    bug["spec_evidence"]["doc"] = "weird/loc/spec.pdf"  # wrong path
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("similar file at" in p for p in problems)


def test_locator_empty_caught(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug()
    bug["spec_evidence"]["locator"] = "   "
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("locator" in p for p in problems)


def test_interpretation_empty_caught(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug()
    bug["spec_evidence"]["interpretation"] = ""
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("interpretation" in p for p in problems)


# ---------------------------------------------------------------------------
# Silicon-blocking extra requirements
# ---------------------------------------------------------------------------
def test_silicon_blocking_requires_unambiguous_flag(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug(severity="silicon-blocking")
    del bug["expected_behaviour_unambiguous"]
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("unambiguous" in p for p in problems)


def test_silicon_blocking_requires_secondary_signal(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug(severity="silicon-blocking")
    bug["expected_behaviour_unambiguous"] = True
    del bug["independent_review"]
    # No vendor_sample_test either
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("vendor_sample_test" in p for p in problems)


def test_silicon_blocking_well_formed_passes(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug(severity="silicon-blocking")
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert problems == []


# ---------------------------------------------------------------------------
# Repro field
# ---------------------------------------------------------------------------
def test_empty_repro_caught(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug(repro="   ")
    problems = gate.check_entry(0, bug, proj, allow_external=False)
    assert any("repro" in p for p in problems)


# ---------------------------------------------------------------------------
# Whole-file check + duplicate id
# ---------------------------------------------------------------------------
def test_check_pass_for_two_good_bugs(tmp_path):
    proj = _make_project(tmp_path)
    p = _write_bugs(tmp_path, [_good_bug(), _good_bug(id="B02")])
    rc, report = gate.check(proj, p, tmp_path / "out.json",
                            allow_external=False)
    assert rc == 0
    assert report["pass"] is True
    assert report["fail"] == 0


def test_check_catches_duplicate_id(tmp_path):
    proj = _make_project(tmp_path)
    p = _write_bugs(tmp_path, [_good_bug(), _good_bug()])  # both id=B01
    rc, report = gate.check(proj, p, tmp_path / "out.json",
                            allow_external=False)
    assert rc == 1
    assert any("duplicate" in pr for f in report["findings"]
               for pr in f["problems"])


def test_check_returns_2_on_missing_file(tmp_path):
    rc, report = gate.check(tmp_path, tmp_path / "absent.json",
                            tmp_path / "out.json", allow_external=False)
    assert rc == 2
    assert "not found" in report["error"]


def test_check_returns_2_on_invalid_json(tmp_path):
    p = tmp_path / "bugs.json"
    p.write_text("{not json")
    rc, report = gate.check(tmp_path, p, tmp_path / "out.json",
                            allow_external=False)
    assert rc == 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_pass(tmp_path):
    proj = _make_project(tmp_path)
    _write_bugs(tmp_path, [_good_bug()])
    rc = gate.main([str(proj)])
    assert rc == 0


def test_cli_fail_no_evidence(tmp_path):
    proj = _make_project(tmp_path)
    bug = _good_bug()
    del bug["spec_evidence"]
    _write_bugs(tmp_path, [bug])
    rc = gate.main([str(proj)])
    assert rc == 1


def test_cli_silicon_blocking_self_attested_fails(tmp_path):
    """Regression test for the v0.53 'silicon-blocking' over-claim.

    A single agent's reading of the spec is not enough for
    silicon-blocking severity; the gate must reject it."""
    proj = _make_project(tmp_path)
    bug = _good_bug(severity="silicon-blocking")
    # Strip the secondary-signal field to simulate the v0.53 pattern
    del bug["independent_review"]
    _write_bugs(tmp_path, [bug])
    rc = gate.main([str(proj)])
    assert rc == 1


def test_cli_allow_external_docs(tmp_path):
    proj = _make_project(tmp_path, with_doc=False)
    _write_bugs(tmp_path, [_good_bug()])
    rc = gate.main([str(proj), "--allow-external-docs"])
    assert rc == 0


def test_cli_nonexistent_project_returns_2(tmp_path):
    rc = gate.main([str(tmp_path / "missing")])
    assert rc == 2
