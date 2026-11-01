"""Owner review is separate from native PERC measurements and binds current files."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

import perc_signoff_check as gate


def _write(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return path


@pytest.fixture
def project(tmp_path):
    _write(tmp_path, "reports/phase3/perc_equivalent.json", {
        "verdict": "PERC_EQUIV_PASS", "categories": [
            {"category": "Measured electrical rule", "status": "AUTOMATED", "result": "PASS"},
            {"category": "Device review", "status": "MANUAL_REVIEW", "result": "MANUAL_REVIEW",
             "checklist": [{"item": "Rated device", "confirmed": None},
                           {"item": "Rated connections", "confirmed": None}]}]})
    _write(tmp_path, "reports/phase3/perc_equivalent.rpt", "OVERALL VERDICT: PERC_EQUIV_PASS\n")
    _write(tmp_path, "reports/phase3/PERC_SIGNOFF_MEMO.md", "**Overall verdict:** `PERC_EQUIV_PASS`\n")
    _write(tmp_path, "reports/phase3/native-device.rpt", "native device and connection evidence\n")
    return tmp_path


def _entries(project):
    relative = "reports/phase3/native-device.rpt"
    basis = [{"path": relative, "sha256": hashlib.sha256((project / relative).read_bytes()).hexdigest()}]
    return [{"category": "Device review", "item": item, "verdict": "ACCEPT",
             "reviewer": "Owner-delegated reliability reviewer", "basis": copy.deepcopy(basis)}
            for item in ("Rated device", "Rated connections")]


def _review(project, entries):
    return _write(project, "input/perc_manual_review.json", {"reviews": entries})


def test_no_review_file_preserves_the_existing_open_category(project):
    rep = gate.audit(project)
    assert (rep["verdict"], rep["rc"]) == ("PASS_WITH_OPEN_ITEMS", 0)
    assert rep["open_items"] == ["MANUAL_REVIEW: Device review"]
    assert "manual_review" not in rep


def test_every_item_accepts_current_native_basis_without_editing_generated_reports(project):
    native = {p: p.read_bytes() for p in (project / "reports/phase3").iterdir()}
    _review(project, _entries(project))
    rep = gate.audit(project)
    assert (rep["verdict"], rep["rc"]) == ("PASS", 0)
    assert rep["open_items"] == []
    assert rep["manual_review"]["closed_categories"] == ["Device review"]
    assert all(p.read_bytes() == raw for p, raw in native.items())


def test_partial_category_stays_open_and_names_the_unreviewed_item(project):
    _review(project, _entries(project)[:1])
    rep = gate.audit(project)
    assert rep["verdict"] == "PASS_WITH_OPEN_ITEMS"
    missing = next(r for r in rep["manual_review"]["items"] if r["item"] == "Rated connections")
    assert missing["status"] == "OPEN"
    assert missing["reason"] == "PERC_MANUAL_REVIEW_ACCEPT_MISSING"


@pytest.mark.parametrize("damage,code", [
    ("no-reviewer", "REVIEWER_EMPTY"), ("blank-reviewer", "REVIEWER_EMPTY"),
    ("empty-basis", "BASIS_EMPTY"), ("missing-basis", "BASIS_EMPTY"),
    ("missing-hash", "BASIS_INVALID"), ("stale-hash", "BASIS_STALE"),
    ("missing-file", "BASIS_MISSING"), ("absolute-path", "BASIS_OUTSIDE_PROJECT"),
    ("escape", "BASIS_OUTSIDE_PROJECT"), ("symlink-escape", "BASIS_OUTSIDE_PROJECT"),
    ("bad-verdict", "VERDICT_INVALID"), ("second-basis-stale", "BASIS_STALE"),
])
def test_incomplete_or_stale_review_cannot_accept_and_names_the_reason(project, damage, code):
    entries = _entries(project)
    entry = entries[0]
    if damage == "no-reviewer":
        entry.pop("reviewer")
    elif damage == "blank-reviewer":
        entry["reviewer"] = " \t "
    elif damage == "empty-basis":
        entry["basis"] = []
    elif damage == "missing-basis":
        entry.pop("basis")
    elif damage == "missing-hash":
        entry["basis"][0].pop("sha256")
    elif damage == "stale-hash":
        entry["basis"][0]["sha256"] = "0" * 64
    elif damage == "missing-file":
        entry["basis"][0]["path"] = "reports/phase3/absent.rpt"
    elif damage == "absolute-path":
        entry["basis"][0]["path"] = str(project / entry["basis"][0]["path"])
    elif damage in ("escape", "symlink-escape"):
        outside = project.parent / (project.name + "-outside.rpt")
        outside.write_text("foreign report\n")
        if damage == "escape":
            entry["basis"][0]["path"] = "../" + outside.name
        else:
            link = project / "reports/phase3/foreign.rpt"
            link.symlink_to(outside)
            entry["basis"][0]["path"] = str(link.relative_to(project))
    elif damage == "bad-verdict":
        entry["verdict"] = "PASS"
    else:
        entry["basis"].append({"path": "reports/phase3/native-device.rpt", "sha256": "0" * 64})
    _review(project, entries)
    rep = gate.audit(project)
    assert rep["verdict"] == "PASS_WITH_OPEN_ITEMS"
    assert "Device review" not in rep["manual_review"]["closed_categories"]
    assert "PERC_MANUAL_REVIEW_" + code in [f["code"] for f in rep["manual_review"]["findings"]]


@pytest.mark.parametrize("field,code", [("category", "UNKNOWN_CATEGORY"), ("item", "UNKNOWN_ITEM")])
def test_unmatched_names_are_findings_instead_of_being_silently_dropped(project, field, code):
    entries = _entries(project)
    entries[0][field] += " different"
    _review(project, entries)
    rep = gate.audit(project)
    assert rep["verdict"] == "PASS_WITH_OPEN_ITEMS"
    assert rep["manual_review"]["findings"][0]["code"] == "PERC_MANUAL_REVIEW_" + code


@pytest.mark.parametrize("unknown", [False, True])
def test_any_reject_is_conclusive_and_cli_returns_one(project, unknown, capsys):
    entry = _entries(project)[0]
    entry["verdict"] = "REJECT"
    if unknown:
        entry = {"category": "Unknown category", "item": "Unknown item", "verdict": "REJECT"}
    _review(project, [entry])
    assert gate.audit(project)["rc"] == 1
    assert gate.main([str(project)]) == 1
    assert '"verdict": "FAIL"' in capsys.readouterr().out


@pytest.mark.parametrize("result", ["FAIL", "INCOMPLETE"])
def test_review_cannot_override_automated_fail_or_incomplete_including_cvc(project, result):
    path = project / "reports/phase3/perc_equivalent.json"
    doc = json.loads(path.read_text())
    doc["categories"][0].update(category="Native CVC electrical rules", result=result)
    path.write_text(json.dumps(doc))
    entries = _entries(project)
    entries.append(dict(entries[0], category="Native CVC electrical rules"))
    _review(project, entries)
    original = path.read_bytes()
    rep = gate.audit(project)
    assert rep["verdict"] == ("FAIL" if result == "FAIL" else "PASS_WITH_OPEN_ITEMS")
    if result == "INCOMPLETE":
        assert "INCOMPLETE: Native CVC electrical rules" in rep["open_items"]
    assert path.read_bytes() == original
    assert any(f["code"] == "PERC_MANUAL_REVIEW_NON_MANUAL_CATEGORY"
               for f in rep["manual_review"]["findings"])


def test_a_category_without_checklist_items_cannot_close_vacuously(project):
    path = project / "reports/phase3/perc_equivalent.json"
    doc = json.loads(path.read_text())
    doc["categories"][1].pop("checklist")
    path.write_text(json.dumps(doc))
    _review(project, [])
    rep = gate.audit(project)
    assert rep["verdict"] == "PASS_WITH_OPEN_ITEMS"
    assert rep["manual_review"]["items"][0]["reason"] == "PERC_MANUAL_REVIEW_CHECKLIST_ABSENT"


@pytest.mark.parametrize("text", ["broken JSON", "[]", '{"reviews": {}}'])
def test_malformed_review_input_is_a_named_open_finding(project, text):
    _write(project, "input/perc_manual_review.json", text)
    rep = gate.audit(project)
    assert rep["verdict"] == "PASS_WITH_OPEN_ITEMS"
    assert rep["manual_review"]["findings"][0]["code"] == "PERC_MANUAL_REVIEW_INPUT_INVALID"


def test_review_cannot_turn_zero_automated_measurements_into_pass(project):
    path = project / "reports/phase3/perc_equivalent.json"
    doc = json.loads(path.read_text())
    doc["categories"] = doc["categories"][1:]
    path.write_text(json.dumps(doc))
    _review(project, _entries(project))
    assert gate.audit(project)["rc"] == 2


def test_incomplete_native_manual_category_cannot_be_closed_by_review(project):
    path = project / "reports/phase3/perc_equivalent.json"
    doc = json.loads(path.read_text())
    doc["categories"][1]["result"] = "INCOMPLETE"
    path.write_text(json.dumps(doc))
    _review(project, _entries(project))
    rep = gate.audit(project)
    assert rep["verdict"] == "PASS_WITH_OPEN_ITEMS"
    assert rep["manual_review"]["closed_categories"] == []
    assert any(f["code"] == "PERC_MANUAL_REVIEW_INCOMPLETE_CATEGORY"
               for f in rep["manual_review"]["findings"])


def test_reject_still_fails_when_native_aggregate_is_absent(project):
    (project / "reports/phase3/perc_equivalent.json").unlink()
    _review(project, [dict(_entries(project)[0], verdict="REJECT")])
    assert gate.audit(project)["rc"] == 1


def test_writer_directs_manual_review_to_the_input_not_its_generated_report(tmp_path):
    from _hostpaths import require_repo
    from test_phase3_signoff_chain_organic import (
        TestPercEquivalent, _mk_project, _DEF_PADRING, _fake_pdk, runner)

    registry = json.loads(require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                                     "flow", "flow109.json").read_text())
    row = next(row for row in registry["rows"] if row["id"] == "D66")
    output = next(p for p in row["profiles"][0]["dispatch"]["native_required_outputs"]
                  if p.endswith("perc_equivalent.json"))
    project = _mk_project(tmp_path, _DEF_PADRING)
    TestPercEquivalent()._seed_subreports(project)
    assert runner._emit_perc_equivalent(project, "chip_top", _fake_pdk(), "", [])
    doc = json.loads((project / output).read_text())
    criteria = [cat["review_criteria"] for cat in doc["categories"] if cat.get("review_criteria")]
    assert criteria
    assert all("input/perc_manual_review.json" in c["record_to"] for c in criteria)
    assert all(item["confirmed"] is None for cat in doc["categories"]
               for item in cat.get("checklist", []))
