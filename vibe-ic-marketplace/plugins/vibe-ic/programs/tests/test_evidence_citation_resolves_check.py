#!/usr/bin/env python3
"""#361 — a cited evidence artifact must EXIST.

An evidence document that says "see `foo.log`" and ships no `foo.log` is
unverifiable, and the failure is SILENT: the sentence reads identically
whether the artifact is there or not.

Found by hitting it twice in one review — a PR supplying the artifact behind
an unverifiable proof claim cited a log it did not itself ship. Root cause is
structural, not carelessness: `.gitignore` ignores `*.log` repo-wide, so
shipping a proof log needs `git add -f`.

Every control below was run by hand against the program before being written
down, so each is a measured discriminator rather than a restatement of the
code.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import evidence_citation_resolves_check as E  # noqa: E402

_PROG = _PROGRAMS / "evidence_citation_resolves_check.py"


def _run(root: Path, baseline: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_PROG), str(root), "--baseline", str(baseline),
         *extra],
        capture_output=True, text=True, timeout=120)


def _doc(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


# ── the defect itself ────────────────────────────────────────────────────────

def test_dangling_citation_fails(tmp_path):
    """THE defect: the document points at a proof it does not ship."""
    _doc(tmp_path, "sub/EV.md", "see `proof.log` for the run\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout
    assert "proof.log" in r.stdout


def test_present_artifact_passes(tmp_path):
    """NO-LEAK for the test above: the same document passes once the artifact
    it cites actually exists, so the check is judging existence and not the
    citation's mere presence."""
    _doc(tmp_path, "sub/EV.md", "see `proof.log` for the run\n")
    (tmp_path / "sub" / "proof.log").write_text("log\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout


# ── the resolver ladder — load-bearing, see the module docstring ────────────

def test_ic_root_relative_citation_resolves(tmp_path):
    """Citations in this tree are written relative to EITHER the document or
    the IC root. A document-directory-only resolver reports ~30% more
    findings, all false — that error was made and corrected while building
    this gate, so it is pinned here."""
    _doc(tmp_path, "deep/a/b/EV.md", "see `sub/proof.log`\n")
    (tmp_path / "sub").mkdir(parents=True)
    (tmp_path / "sub" / "proof.log").write_text("log\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout


def test_resolution_never_escapes_the_scan_root(tmp_path):
    """The ladder must stop AT the root: resolving against ancestors above it
    would let a file outside the tree satisfy a citation inside it."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "proof.log").write_text("log\n")
    root = tmp_path / "root"
    _doc(root, "EV.md", "see `proof.log`\n")
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout


# ── templates are not citations ──────────────────────────────────────────────

def test_template_and_glob_tokens_are_not_judged(tmp_path):
    """`<name>.log` / `*.log` never claimed a specific file exists. Judging
    them would manufacture findings against text that promised nothing."""
    _doc(tmp_path, "EV.md",
         "pattern `*.log`, placeholder `<run>.log`, brace `{x}.log`\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    assert "citation(s) checked" in r.stdout


# ── the baseline is a debt register, not a waiver list ───────────────────────

def test_baseline_admits_known_debt_but_blocks_a_new_hole(tmp_path):
    _doc(tmp_path, "sub/EV.md", "see `a.log`\n")
    assert _run(tmp_path, tmp_path / "bl.json", "--write-baseline").returncode == 0
    assert _run(tmp_path, tmp_path / "bl.json").returncode == 0   # known debt
    _doc(tmp_path, "sub/EV.md", "see `a.log`\nand `b.log`\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout                            # NEW hole
    assert "b.log" in r.stdout


def test_baseline_refuses_to_grow(tmp_path):
    """The one control that keeps this from becoming a rubber stamp: a
    baseline that can be regenerated upward turns every regression into an
    accepted fact."""
    _doc(tmp_path, "sub/EV.md", "see `a.log`\n")
    _run(tmp_path, tmp_path / "bl.json", "--write-baseline")
    _doc(tmp_path, "sub/EV.md", "see `a.log`\nand `b.log`\n")
    r = _run(tmp_path, tmp_path / "bl.json", "--write-baseline")
    assert r.returncode == 1, r.stdout
    assert "refusing to GROW" in r.stdout
    kept = json.loads((tmp_path / "bl.json").read_text())["unresolved"]
    assert len(kept) == 1, "the refused write must not have landed"


def test_paid_debt_must_be_removed_from_the_baseline(tmp_path):
    """A baseline entry that now RESOLVES is stale. Left in place the register
    slowly turns into standing permission, so it FAILs until shrunk."""
    _doc(tmp_path, "sub/EV.md", "see `a.log`\n")
    _run(tmp_path, tmp_path / "bl.json", "--write-baseline")
    (tmp_path / "sub" / "a.log").write_text("log\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout
    assert "now RESOLVE" in r.stdout
    # ...and shrinking it is accepted.
    assert _run(tmp_path, tmp_path / "bl.json",
                "--write-baseline").returncode == 0
    assert _run(tmp_path, tmp_path / "bl.json").returncode == 0


# ── shipped state ────────────────────────────────────────────────────────────

def test_shipped_baseline_matches_the_shipped_tree():
    """The gate must be GREEN on main as landed — a gate that ships red is
    the failure mode it exists to remove (#306: 62 of 72 gates could describe
    a run but not stop one)."""
    r = subprocess.run([sys.executable, str(_PROG)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode == 2:
        return  # no benchmark-data tree in this checkout — honest SKIP
    assert r.returncode == 0, r.stdout + r.stderr


def test_out_of_scope_tree_is_disclosed_not_silently_dropped():
    """The default scope excludes a tree; that narrowing must be VISIBLE with
    its measured size, or 'not scanned' reads as 'clean'."""
    assert E._DISCLOSED_OUT_OF_SCOPE[0]
    assert "unresolved" in E._DISCLOSED_OUT_OF_SCOPE[1]
    r = subprocess.run([sys.executable, str(_PROG)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 2:
        assert "NOT scanned" in r.stdout


def test_baseline_never_stores_the_paths_it_lists(tmp_path):
    """The register must not publish what it lists. Some benchmark-data
    directory names embed a commercial foundry product name, and a landed
    diff is permanent public content — `nda_diff_scan_check` caught exactly
    that on this gate's first attempt to land. Entries are digests; the
    paths stay visible to whoever RUNS the gate."""
    _doc(tmp_path, "sub/EV.md", "see `secret_vendor_name_run/a.log`\n")
    bl = tmp_path / "bl.json"
    _run(tmp_path, bl, "--write-baseline")
    raw = bl.read_text()
    assert "secret_vendor_name_run" not in raw
    assert "a.log" not in raw
    entries = json.loads(raw)["unresolved"]
    assert entries and all(len(e) == 32 and e.isalnum() for e in entries)
    # ...and it still functions as a register: the known debt does not fire.
    assert _run(tmp_path, bl).returncode == 0
