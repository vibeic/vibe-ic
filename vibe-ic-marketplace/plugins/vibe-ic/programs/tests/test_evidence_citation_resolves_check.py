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

import pytest
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
    a run but not stop one).

    Only meaningful on a CLEAN checkout: the shipped baseline describes the
    TRACKED tree, so a developer whose benchmark-data holds local run
    artifacts would see a mismatch that is theirs, not the repo's. Skipping
    loudly there is what keeps this test from being deleted by the first
    person it annoys; CI runs clean and enforces it for real."""
    r = subprocess.run([sys.executable, str(_PROG)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode == 2:
        pytest.skip("no benchmark-data tree in this checkout")
    root = next((b / E._DEFAULT_ROOT_REL for b in Path(_PROG).resolve().parents
                 if (b / E._DEFAULT_ROOT_REL).is_dir()), None)
    if root is not None and E._working_tree_dirt(root):
        pytest.skip("working tree under the scan root is dirty — the shipped "
                    "baseline describes the TRACKED tree; CI runs clean")
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


# ── the CI-vs-local divergence that shipped, and its two fixes ──────────────
# The first version judged plain filesystem existence and its baseline was
# generated from a working tree holding UNTRACKED artifacts: green locally,
# RED in CI (12 baseline entries "resolved", 9 new dangling). A gate whose
# verdict depends on what is lying in the author's tree is the false
# certificate this gate exists to remove.

def _git(root: Path, *args):
    subprocess.run(["git", "-C", str(root), *args],
                   capture_output=True, check=True, timeout=120)


def _repo(tmp_path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def test_untracked_artifact_does_not_satisfy_a_citation(tmp_path):
    """THE divergence: the proof exists on disk but the repo does not SHIP
    it. The question is 'does the repo ship the proof', not 'does this
    machine have it'."""
    root = _repo(tmp_path)
    _doc(root, "sub/EV.md", "see `proof.log`\n")
    _git(root, "add", "sub/EV.md")
    _git(root, "commit", "-q", "-m", "doc")
    (root / "sub" / "proof.log").write_text("log\n")     # present, UNtracked
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout
    assert "proof.log" in r.stdout
    # ...and tracking it clears the finding.
    _git(root, "add", "-f", "sub/proof.log")
    _git(root, "commit", "-q", "-m", "log")
    assert _run(root, tmp_path / "bl.json").returncode == 0


def test_untracked_document_is_not_scanned(tmp_path):
    """The other direction of the same drift: an untracked document's
    citations must not enter the register, or the baseline encodes the
    author's tree and every clean checkout disagrees with it."""
    root = _repo(tmp_path)
    _doc(root, "keep.md", "nothing cited here\n")
    _git(root, "add", "keep.md")
    _git(root, "commit", "-q", "-m", "keep")
    _doc(root, "scratch.md", "see `ghost.log`\n")        # untracked document
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    assert "ghost.log" not in r.stdout


def test_baseline_write_is_refused_from_a_dirty_tree(tmp_path):
    """The bug that shipped, now impossible: a baseline recorded from a tree
    with untracked/modified paths describes the author's laptop."""
    root = _repo(tmp_path)
    _doc(root, "EV.md", "see `a.log`\n")
    _git(root, "add", "EV.md")
    _git(root, "commit", "-q", "-m", "doc")
    (root / "dirt.txt").write_text("untracked\n")
    r = _run(root, tmp_path / "bl.json", "--write-baseline")
    assert r.returncode == 1, r.stdout
    assert "DIRTY tree" in r.stdout
    assert not (tmp_path / "bl.json").exists()


# ── JSON gate reports (#366) ─────────────────────────────────────────────────
# A report that declares a `verdict` AND names the artifact substantiating it
# makes the same promise a Markdown citation makes. Three spm PDK cells carry
# formal_evidence.json with verdict PASS and "substantiated by an elaboratable
# .sby + SymbiYosys PASS transcript" while no .sby and no transcript exist
# anywhere in the repo — the gate that wrote them verifies the paths before
# emitting PASS and they existed at run time; they simply could not be SHIPPED
# (`*.sby.log` matches .gitignore's repo-wide `*.log`; zero are tracked).

def test_gate_report_citing_a_missing_artifact_fails(tmp_path):
    root = _repo(tmp_path)
    (root / "reports").mkdir()
    (root / "reports" / "formal_evidence.json").write_text(json.dumps(
        {"verdict": "PASS", "sby": "formal/proof.sby",
         "sby_log": "formal/proof.sby.log"}))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "report")
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout
    assert "proof.sby" in r.stdout


def test_gate_report_with_its_artifacts_passes(tmp_path):
    root = _repo(tmp_path)
    (root / "reports").mkdir()
    (root / "formal").mkdir()
    (root / "formal" / "proof.sby").write_text("[tasks]\n")
    (root / "formal" / "proof.sby.log").write_text("PASS\n")
    (root / "reports" / "formal_evidence.json").write_text(json.dumps(
        {"verdict": "PASS", "sby": "formal/proof.sby",
         "sby_log": "formal/proof.sby.log"}))
    _git(root, "add", "-Af")
    _git(root, "commit", "-q", "-m", "report+evidence")
    assert _run(root, tmp_path / "bl.json").returncode == 0


def test_json_without_a_verdict_is_data_not_a_claim(tmp_path):
    """Only a report that DECLARES a verdict is making a promise. Judging
    every JSON string that ends in .log would manufacture findings against
    configuration and inventory files."""
    root = _repo(tmp_path)
    (root / "cfg.json").write_text(json.dumps({"log_path": "nowhere/x.log"}))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "cfg")
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    assert "nowhere/x.log" not in r.stdout


def test_absolute_path_never_substantiates_anything(tmp_path):
    """An absolute path can only resolve on the machine that wrote it, so it
    substantiates nothing for any other reader — and it would make the gate's
    verdict host-dependent, the exact divergence that already bit this gate
    once."""
    root = _repo(tmp_path)
    real = root / "real.log"
    real.write_text("log\n")
    (root / "r.json").write_text(json.dumps(
        {"verdict": "PASS", "source": str(real.resolve())}))
    _git(root, "add", "-Af")
    _git(root, "commit", "-q", "-m", "abs")
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout


# ── scope expansion is a recorded act, not a bypass ─────────────────────────
# Widening what the gate LOOKS AT legitimately grows the register (62 -> 141
# when JSON gate reports were added). That is pre-existing debt becoming
# VISIBLE, not new debt being admitted — but shrink-only cannot tell the two
# apart, so the distinction must be declared and stored rather than assumed.

def test_growth_still_refused_without_a_declared_expansion(tmp_path):
    root = _repo(tmp_path)
    _doc(root, "EV.md", "see `a.log`\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "a")
    _run(root, tmp_path / "bl.json", "--write-baseline")
    _doc(root, "EV.md", "see `a.log`\nand `b.log`\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "b")
    r = _run(root, tmp_path / "bl.json", "--write-baseline")
    assert r.returncode == 1 and "refusing to GROW" in r.stdout


def test_expansion_requires_a_real_reason(tmp_path):
    """A one-word reason is a bypass wearing a flag's clothes."""
    root = _repo(tmp_path)
    _doc(root, "EV.md", "see `a.log`\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "a")
    r = _run(root, tmp_path / "bl.json", "--write-baseline",
             "--scope-expanded", "because")
    assert r.returncode == 1, r.stdout
    assert not (tmp_path / "bl.json").exists()


def test_declared_expansion_is_allowed_and_recorded(tmp_path):
    root = _repo(tmp_path)
    _doc(root, "EV.md", "see `a.log`\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "a")
    _run(root, tmp_path / "bl.json", "--write-baseline")
    _doc(root, "EV.md", "see `a.log`\nand `b.log`\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "b")
    reason = ("the gate now also judges JSON gate reports, so pre-existing "
              "debt became visible")
    r = _run(root, tmp_path / "bl.json", "--write-baseline",
             "--scope-expanded", reason)
    assert r.returncode == 0, r.stdout
    d = json.loads((tmp_path / "bl.json").read_text())
    assert len(d["unresolved"]) == 2
    assert d["scope_expansion"]["previous_size"] == 1
    assert reason in d["scope_expansion"]["reason"]


# ── the symlink divergence that made CI and local disagree ──────────────────
# benchmark-data/ic carries 787 symlinks. Identity built with `Path.resolve()`
# FOLLOWS them, so a tracked file's identity became its target — which exists
# on the author's machine and not in a fresh checkout. The gate enumerated 440
# documents locally and 422 in CI on the SAME commit, and the baseline written
# in one place could never match the other. Identity is now the LOGICAL path
# from the git index, so the verdict is a pure function of the index.

def test_symlinked_directory_does_not_change_the_verdict(tmp_path):
    root = _repo(tmp_path)
    (root / "real").mkdir()
    _doc(root, "real/EV.md", "see `proof.log`\n")
    (root / "real" / "proof.log").write_text("log\n")
    (root / "link").symlink_to("real")          # tracked symlink, as in the tree
    _git(root, "add", "-Af")
    _git(root, "commit", "-q", "-m", "tree with a symlink")
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    # the document is counted ONCE — enumeration comes from the index, not a
    # filesystem walk that would descend through the symlink as well.
    assert "1 citation(s) checked" in r.stdout, r.stdout


def test_verdict_is_a_pure_function_of_the_index(tmp_path):
    """Untracked files must not move the verdict in EITHER direction — that
    property is what makes a baseline written on one machine valid on
    another."""
    root = _repo(tmp_path)
    _doc(root, "EV.md", "see `a.log`\n")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "doc")
    before = _run(root, tmp_path / "bl.json").stdout
    (root / "a.log").write_text("untracked artifact\n")      # would "fix" it
    _doc(root, "extra.md", "see `b.log`\n")                  # would add debt
    after = _run(root, tmp_path / "bl.json").stdout
    assert before.split("unresolved now")[1] == after.split("unresolved now")[1]


def test_tracked_symlinks_are_not_documents_and_not_evidence(tmp_path):
    """THE divergence, root cause. 121 of the 122 tracked symlinks under
    benchmark-data/ic point at ABSOLUTE paths outside the repository: they
    resolve on the machine that made them and dangle for everyone else.
    Reading through them made this gate count 440 documents locally and 422
    in CI on the same commit. The index's file MODE decides — a symlink's
    blob is a path string, not document content, and it ships no content."""
    ext = tmp_path / "external"          # genuinely outside the repo
    ext.mkdir()
    root = _repo(tmp_path / "repo")
    _doc(root, "real.md", "see `there.log`\n")
    (root / "there.log").write_text("log\n")
    outside = ext / "outside.md"
    outside.write_text("see `ghost.log`\n")
    (root / "linked.md").symlink_to(outside)     # absolute, outside the repo
    _git(root, "add", "-Af")
    _git(root, "commit", "-q", "-m", "tree with an outward symlink")
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    # the symlink contributed NO citation, on this machine or any other
    assert "ghost.log" not in r.stdout
    assert "1 citation(s) checked" in r.stdout, r.stdout


def test_a_citation_pointing_at_a_symlink_is_not_shipped_content(tmp_path):
    """A tracked symlink is a pointer, not content — so it cannot
    substantiate a claim either."""
    ext = tmp_path / "external"
    ext.mkdir()
    root = _repo(tmp_path / "repo")
    real = ext / "elsewhere.log"
    real.write_text("log\n")
    _doc(root, "EV.md", "see `proof.log`\n")
    (root / "proof.log").symlink_to(real)
    _git(root, "add", "-Af")
    _git(root, "commit", "-q", "-m", "symlinked evidence")
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout
    assert "proof.log" in r.stdout
