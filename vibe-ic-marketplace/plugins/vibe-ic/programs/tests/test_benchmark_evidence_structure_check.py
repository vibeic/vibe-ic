#!/usr/bin/env python3
"""Tests for benchmark_evidence_structure_check.py.

All fixtures are chip-AGNOSTIC synthetic folders (generic IC/PDK tokens) built
under tmp_path — no dependency on benchmark-data (two-tree safe).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "benchmark_evidence_structure_check.py"

_GOOD_MANIFEST = ("top.gds 1180456B sha256:"
                  + "2915355c69e0162887e4c3e3e60855a0710a8bccb0e02f1b08191989ef392c8f")

_RESULT_PASS = "# RESULT\n\n## VERDICT\n\n**PASS_WITH_WAIVERS.** re-derived.\n"
_RESULT_FAIL = "# RESULT\n\n## VERDICT\n\n**FAIL.** did not converge.\n"


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def _make_conformant(base: Path, name: str = "v9.9.9_openpdkx") -> Path:
    d = base / name
    (d / "phase1" / "generated_docs").mkdir(parents=True)
    (d / "phase1" / "generated_docs" / "L1.json").write_text("{}")
    (d / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (d / "phase2" / "stage1" / "rtl" / "top.v").write_text("module top; endmodule\n")
    (d / "reports" / "phase3").mkdir(parents=True)
    (d / "reports" / "phase3" / "drc.json").write_text("{}")
    (d / "phase3" / "stage4" / "gds").mkdir(parents=True)
    (d / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt").write_text(_GOOD_MANIFEST + "\n")
    (d / "RESULT.md").write_text(_RESULT_PASS)
    return d


# --------------------------------------------------------------------------
# happy path
# --------------------------------------------------------------------------

def test_help():
    assert _run(["--help"]).returncode == 0


def test_conformant_passes(tmp_path):
    d = _make_conformant(tmp_path)
    r = _run([str(d)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_conformant_reports_phase3_or_phase3_reports(tmp_path):
    # phase3/reports variant (instead of reports/phase3) also satisfies the rule.
    d = _make_conformant(tmp_path)
    import shutil
    shutil.rmtree(d / "reports")
    (d / "phase3" / "reports").mkdir(parents=True)
    (d / "phase3" / "reports" / "sta.rpt").write_text("wns 0\n")
    assert _run([str(d)]).returncode == 0


# --------------------------------------------------------------------------
# the four mandated FAIL cases + more
# --------------------------------------------------------------------------

def test_clean_run_naming_fails(tmp_path):
    d = _make_conformant(tmp_path, name="clean_run_v9.9.9_openpdkx")
    r = _run([str(d)])
    assert r.returncode == 1
    assert "NAMING" in r.stdout and "clean_run" in r.stdout


def test_pass_prefix_naming_fails(tmp_path):
    d = _make_conformant(tmp_path, name="pass_v9.9.9_openpdkx")
    r = _run([str(d)])
    assert r.returncode == 1
    assert "NAMING" in r.stdout


def test_version_last_naming_fails(tmp_path):
    # PDK first, version last -> not v<ver>_<PDK>
    d = _make_conformant(tmp_path, name="openpdkx_v9.9.9")
    r = _run([str(d)])
    assert r.returncode == 1
    assert "NAMING" in r.stdout


def test_missing_gds_manifest_fails(tmp_path):
    d = _make_conformant(tmp_path)
    (d / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt").unlink()
    r = _run([str(d)])
    assert r.returncode == 1
    assert "GDS_MANIFEST" in r.stdout


def test_malformed_manifest_fails(tmp_path):
    d = _make_conformant(tmp_path)
    (d / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt").write_text("top.gds no-sha here\n")
    r = _run([str(d)])
    assert r.returncode == 1
    assert "GDS_MANIFEST" in r.stdout


def _sparse(p, size: int):
    """A file of `size` bytes that costs no disk — `st_size` is what the rule
    reads, and writing 51 real MB per test is a slow way to learn nothing."""
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as fh:
        fh.truncate(size)


def test_a_committed_gds_under_the_ceiling_is_accepted(tmp_path):
    """#419 — this test asserted the OPPOSITE until v1.6.61, and that is
    exactly why all three reference cells failed their own structure check
    while `.gitignore` accepted the files they carry. A 0.8 MB GDS is
    evidence a reviewer can open; refusing it by extension in order to avoid
    a 105 MB one is the wrong instrument."""
    d = _make_conformant(tmp_path)
    (d / "phase3" / "stage4" / "gds" / "top.gds").write_bytes(b"RAWGDS")
    r = _run([str(d)])
    assert r.returncode == 0, r.stdout
    assert "NO_RAW_GEOMETRY" not in r.stdout or "[PASS]" in r.stdout


def test_a_committed_gds_over_the_ceiling_still_fails(tmp_path):
    """The paired half. Above the ceiling the file cannot be committed at
    all, and the message has to say what to do instead."""
    d = _make_conformant(tmp_path)
    _sparse(d / "phase3" / "stage4" / "gds" / "big.gds", 51 * 1000 * 1000)
    r = _run([str(d)])
    assert r.returncode == 1
    assert "NO_RAW_GEOMETRY" in r.stdout
    assert "git-lfs" in r.stdout and "GDS_MANIFEST" in r.stdout


def test_committed_def_and_spef_under_the_ceiling_are_accepted(tmp_path):
    """`.spef`/`.oas` were never gitignored at all, so the three reference
    cells' .spef files needed no force-add — only this rule objected."""
    d = _make_conformant(tmp_path)
    (d / "phase2" / "stage1" / "rtl" / "x.def").write_text("DESIGN\n")
    (d / "reports" / "phase3" / "y.spef").write_text("*SPEF\n")
    r = _run([str(d)])
    assert r.returncode == 0, r.stdout


def test_an_oversized_spef_fails_like_an_oversized_gds(tmp_path):
    """The rule is about size, not about which of the four extensions it is."""
    d = _make_conformant(tmp_path)
    _sparse(d / "reports" / "phase3" / "huge.spef", 51 * 1000 * 1000)
    r = _run([str(d)])
    assert r.returncode == 1
    assert "NO_RAW_GEOMETRY" in r.stdout


def test_non_converged_result_fails(tmp_path):
    d = _make_conformant(tmp_path)
    (d / "RESULT.md").write_text(_RESULT_FAIL)
    r = _run([str(d)])
    assert r.returncode == 1
    assert "CONVERGED" in r.stdout


def test_missing_result_fails(tmp_path):
    d = _make_conformant(tmp_path)
    (d / "RESULT.md").unlink()
    r = _run([str(d)])
    assert r.returncode == 1
    assert "RESULT_PRESENT" in r.stdout


def test_missing_phase1_docs_fails(tmp_path):
    d = _make_conformant(tmp_path)
    import shutil
    shutil.rmtree(d / "phase1")
    r = _run([str(d)])
    assert r.returncode == 1
    assert "PHASE1_DOCS" in r.stdout


def test_missing_phase2_fails(tmp_path):
    d = _make_conformant(tmp_path)
    import shutil
    shutil.rmtree(d / "phase2")
    r = _run([str(d)])
    assert r.returncode == 1
    assert "PHASE2" in r.stdout


def test_missing_phase3_reports_fails(tmp_path):
    d = _make_conformant(tmp_path)
    import shutil
    shutil.rmtree(d / "reports")
    r = _run([str(d)])
    assert r.returncode == 1
    assert "PHASE3_REPORTS" in r.stdout


# --------------------------------------------------------------------------
# tree mode + json + missing path
# --------------------------------------------------------------------------

def test_tree_mode_discovers_and_flags_misnamed(tmp_path):
    root = tmp_path / "benchmark-data"
    ic = root / "ic" / "widgetmul"
    ic.mkdir(parents=True)
    _make_conformant(ic, name="v9.9.9_openpdkx")            # good
    _make_conformant(ic, name="clean_run_v9.9.8_openpdky")  # misnamed -> flagged
    (ic / "input" / "docs").mkdir(parents=True)             # shared input skipped
    (ic / "input" / "docs" / "L1.md").write_text("# spec\n")
    r = _run(["--tree", str(root)])
    assert r.returncode == 1                                # the misnamed one fails
    assert "clean_run" in r.stdout
    # exactly two evidence folders discovered (input/ excluded)
    assert r.stdout.count("v9.9.9_openpdkx") >= 1


def test_json_output(tmp_path):
    d = _make_conformant(tmp_path)
    out = tmp_path / "out.json"
    r = _run([str(d), "--json", str(out)])
    assert r.returncode == 0
    data = json.loads(out.read_text())
    assert data["conformant"] == 1 and data["nonconformant"] == 0
    assert data["folders"][0]["verdict"] == "PASS_WITH_WAIVERS"


def test_missing_path_is_error(tmp_path):
    r = _run([str(tmp_path / "nope")])
    assert r.returncode == 1  # nonconformant (PATH failure), not a crash


def test_no_targets_is_usage_error():
    assert _run([]).returncode == 2


# --------------------------------------------------------------------------
# --changed-since (CI diff-scoping): grandfather pre-existing folders
# --------------------------------------------------------------------------

def _git(repo: Path, *args):
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "HOME": str(repo)}
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True, env={**env}, check=False)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo


def test_changed_since_grandfathers_legacy_and_flags_new(tmp_path):
    repo = _init_repo(tmp_path)
    ic = repo / "benchmark-data" / "ic" / "widgetmul"
    ic.mkdir(parents=True)
    # a pre-existing MALFORMED folder committed at base (legacy)
    _make_conformant(ic, name="clean_run_v9.9.0_legacy")  # bad name
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base with legacy")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # now ADD a new nonconformant folder (missing manifest)
    newd = _make_conformant(ic, name="v9.9.9_openpdkx")
    (newd / "phase3" / "stage4" / "gds" / "GDS_MANIFEST.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add new bad publish")

    r = _run(["--tree", str(repo / "benchmark-data"), "--changed-since", base])
    assert r.returncode == 1                       # the NEW folder fails
    assert "v9.9.9_openpdkx" in r.stdout
    assert "clean_run_v9.9.0_legacy" not in r.stdout  # legacy grandfathered


def test_changed_since_no_changes_passes(tmp_path):
    repo = _init_repo(tmp_path)
    ic = repo / "benchmark-data" / "ic" / "widgetmul"
    ic.mkdir(parents=True)
    _make_conformant(ic, name="clean_run_v9.9.0_legacy")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # a commit that does NOT touch any evidence folder
    (repo / "README.md").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "unrelated")

    r = _run(["--tree", str(repo / "benchmark-data"), "--changed-since", base])
    assert r.returncode == 0                       # legacy not re-checked
    assert "nothing to enforce" in r.stdout or "no evidence folders changed" in r.stdout
