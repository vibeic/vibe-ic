"""A run's own top-level verdict may not contradict its own gate reports.

Two-armed by construction (vibe-ic#1028). The RED arm runs against
``ic/edge_llm_accel`` EXACTLY AS IT WAS PUBLISHED — the bytes are read out of
git history, not out of the working tree, so the arm keeps proving what it
claims after PR #1028 withdraws that root from the tree. A negative control
that evaporates when the corpus changes is the failure mode #1029/#1030 was
about (the suite wrote into the tree the next gate read); this test does not
repeat it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAMS = os.path.dirname(HERE)
REPO = subprocess.run(
    ["git", "-C", PROGRAMS, "rev-parse", "--show-toplevel"],
    capture_output=True, text=True).stdout.strip() or PROGRAMS
GATE = os.path.join(PROGRAMS, "published_verdict_self_consistency_check.py")

# The root the defect was measured on, and the verdict its RESULT.md declared.
PUBLISHED_ROOT = "benchmark-data/ic/edge_llm_accel"

sys.path.insert(0, PROGRAMS)
from published_verdict_self_consistency_check import (  # noqa: E402
    audit, declared_verdict, main)

FAIL_FIELDS = ("verdict", "overall", "overall_status", "status",
               "gate_status", "result", "pass_fail")


def _run(corpus):
    proc = subprocess.run(
        [sys.executable, GATE, "--corpus", str(corpus)],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


@pytest.fixture(scope="module")
def as_published(tmp_path_factory):
    """`ic/edge_llm_accel` as published, restored from git history."""
    rev = subprocess.run(
        ["git", "-C", REPO, "rev-parse", "--verify",
         f"origin/main:{PUBLISHED_ROOT}"],
        capture_output=True, text=True)
    if rev.returncode != 0:
        pytest.skip(f"{PUBLISHED_ROOT} not reachable from origin/main")
    dest = tmp_path_factory.mktemp("as_published")
    archive = subprocess.run(
        ["git", "-C", REPO, "archive", "origin/main", PUBLISHED_ROOT],
        capture_output=True)
    assert archive.returncode == 0, archive.stderr
    tar = subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout)
    assert tar.returncode == 0
    return dest


def _corrected(src, dst):
    """Same tree, every FAIL gate verdict corrected to PASS."""
    # The corpus carries tracked symlinks (cf. tracked_symlink_target_present_check).
    # Resolving them here would fail on the dangling ones and prove nothing.
    shutil.copytree(src, dst, symlinks=True, ignore_dangling_symlinks=True)
    corrected = 0
    for dirpath, _d, filenames in os.walk(dst):
        for name in filenames:
            if not name.endswith(".json"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    doc = json.load(fh)
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if not isinstance(doc, dict):
                continue
            changed = False
            for field in FAIL_FIELDS:
                value = doc.get(field)
                if isinstance(value, str) and value.strip().upper() == "FAIL":
                    doc[field] = "PASS"
                    changed = True
            if changed:
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, indent=2)
                corrected += 1
    return corrected


# --------------------------------------------------------------------------
# ARM 1 — RED on the corpus as it was actually published.
# --------------------------------------------------------------------------

def test_red_arm_the_published_root_is_refused(as_published):
    """edge_llm_accel shipped `STATUS: COMPLETE` over FAIL gate reports."""
    code, out = _run(as_published)
    assert code == 1, f"gate did not go RED on {PUBLISHED_ROOT}:\n{out}"
    assert "edge_llm_accel" in out
    bad = audit(str(as_published))
    assert len(bad) == 1
    _root, count, _items = bad[0]
    assert count >= 5, (
        f"expected the published root's own FAIL gate reports to be found; "
        f"got {count}")


def test_red_arm_names_the_contradicting_reports(as_published):
    """The finding is actionable: it names the files, not just a count."""
    _code, out = _run(as_published)
    assert "phase23_completion_audit.json" in out or "lec.json" in out, out


# --------------------------------------------------------------------------
# ARM 2 — GREEN, and non-vacuously so.
# --------------------------------------------------------------------------

def test_green_arm_same_root_once_its_reports_agree(as_published, tmp_path):
    """Correct the machine evidence and the SAME root passes."""
    dst = tmp_path / "corrected"
    corrected = _corrected(as_published, dst)
    assert corrected > 0, "fixture corrected nothing — arm proves nothing"
    code, out = _run(dst)
    assert code == 0, f"gate could not go GREEN:\n{out}"


def test_green_arm_is_not_vacuous(as_published, tmp_path):
    """A pass that examined zero roots is not a pass."""
    dst = tmp_path / "corrected_nv"
    _corrected(as_published, dst)
    proc = subprocess.run(
        [sys.executable, GATE, "--corpus", str(dst), "--json"],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["run_roots_examined"] >= 1, (
        "GREEN arm examined no run root — it would pass an empty tree "
        "identically, which proves nothing about the rule")
    assert payload["self_contradictory"] == []


# --------------------------------------------------------------------------
# The rule discriminates — it is not "any FAIL anywhere is bad".
# --------------------------------------------------------------------------

def test_a_root_that_admits_failure_is_not_the_defect(tmp_path):
    """RESULT.md saying FAIL over FAIL reports is honest, not contradictory."""
    root = tmp_path / "ic" / "honest"
    root.mkdir(parents=True)
    (root / "RESULT.md").write_text("# RESULT\n\n## VERDICT\n\nOverall: FAIL\n")
    (root / "gate.json").write_text(json.dumps({"verdict": "FAIL"}))
    code, out = _run(tmp_path)
    assert code == 0, f"an honest FAIL must not be flagged:\n{out}"


def test_waived_and_skipped_are_not_failures(tmp_path):
    """'filed no verdict' is not 'failed' — the whole PR turns on this."""
    root = tmp_path / "ic" / "waived"
    root.mkdir(parents=True)
    (root / "RESULT.md").write_text("# RESULT\n\nSTATUS: PASS\n")
    (root / "a.json").write_text(json.dumps({"verdict": "WAIVED"}))
    (root / "b.json").write_text(json.dumps({"verdict": "SKIP"}))
    (root / "c.json").write_text(json.dumps({"status": "N/A"}))
    code, out = _run(tmp_path)
    assert code == 0, f"WAIVED/SKIP/N-A must not read as FAIL:\n{out}"


def test_a_pass_headline_over_one_fail_report_is_refused(tmp_path):
    """The minimal positive case — one contradicting report is enough."""
    root = tmp_path / "ic" / "lying"
    root.mkdir(parents=True)
    (root / "RESULT.md").write_text("# RESULT\n\nSTATUS: COMPLETE — TESTS PASS\n")
    (root / "ok.json").write_text(json.dumps({"verdict": "PASS"}))
    (root / "bad.json").write_text(json.dumps({"verdict": "FAIL"}))
    code, out = _run(tmp_path)
    assert code == 1, f"a PASS headline over a FAIL report must be RED:\n{out}"
    assert "bad.json" in out


def test_non_gate_json_is_not_read_as_a_verdict(tmp_path):
    """A JSON with no verdict field is not a gate report."""
    root = tmp_path / "ic" / "plain"
    root.mkdir(parents=True)
    (root / "RESULT.md").write_text("# RESULT\n\nSTATUS: PASS\n")
    (root / "config.json").write_text(json.dumps({"note": "FAIL is a word"}))
    code, _out = _run(tmp_path)
    assert code == 0


@pytest.mark.parametrize("text,expected", [
    ("STATUS: COMPLETE — TESTS PASS", "PASS"),
    ("## VERDICT\n\nOverall: FAIL", "NOT_PASS"),
    ("# RESULT\n\nsome prose that passes no judgement", "UNDECLARED"),
])
def test_declared_verdict_reads_only_verdict_bearing_lines(text, expected):
    assert declared_verdict(text) == expected


def test_gate_is_blocking_not_advisory(as_published):
    """Declared BLOCKING — prove the non-zero exit actually happens."""
    assert main(["--corpus", str(as_published)]) == 1
