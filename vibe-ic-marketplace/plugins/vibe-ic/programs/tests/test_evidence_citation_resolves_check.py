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

from _published_corpus import corpus_root, needs_corpus

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import evidence_citation_resolves_check as E  # noqa: E402

_PROG = _PROGRAMS / "evidence_citation_resolves_check.py"


def _run(root: Path, baseline: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_PROG), str(root), "--baseline", str(baseline),
         *extra],
        capture_output=True, text=True, timeout=60)


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

@needs_corpus
def test_shipped_baseline_matches_the_shipped_tree():
    """The gate must be GREEN on main as landed — a gate that ships red is
    the failure mode it exists to remove (#306: 62 of 72 gates could describe
    a run but not stop one).

    Only meaningful on a CLEAN checkout: the shipped baseline describes the
    TRACKED tree, so a developer whose benchmark-data holds local run
    artifacts would see a mismatch that is theirs, not the repo's. Skipping
    loudly there is what keeps this test from being deleted by the first
    person it annoys; CI runs clean and enforces it for real.

    THE TREE IT MEANS IS THE PUBLISHED CORPUS, WHEREVER THAT IS. The gate's
    default root is `<checkout>/benchmark-data/ic` and its baseline lives with
    the DATA it describes (`root.parent/evidence_citation_baseline.json`, see
    `_BASELINE_NAME`), so when the cells moved to vibeic/benchmark-data both
    moved together. Running the default here would compare THAT register
    against a directory holding only the design inputs and report 135 debts
    "paid" — a number about nothing. The scan root is therefore resolved to
    the corpus this run actually has, and where there is none the honest answer
    is that the shipped tree could not be looked at (skip), not that it is
    green (pass) and not that it is broken (fail)."""
    root = corpus_root() / "ic"
    r = subprocess.run([sys.executable, str(_PROG), str(root)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 2:
        pytest.skip("no benchmark-data tree in this checkout")
    if E._working_tree_dirt(root):
        pytest.skip("working tree under the scan root is dirty — the shipped "
                    "baseline describes the TRACKED tree; CI runs clean")
    assert r.returncode == 0, r.stdout + r.stderr


def test_out_of_scope_tree_is_disclosed_not_silently_dropped():
    """The default scope excludes a tree; that narrowing must be VISIBLE with
    its measured size, or 'not scanned' reads as 'clean'."""
    assert E._DISCLOSED_OUT_OF_SCOPE[0]
    assert "unresolved" in E._DISCLOSED_OUT_OF_SCOPE[1]
    r = subprocess.run([sys.executable, str(_PROG)],
                       capture_output=True, text=True, timeout=60)
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
                   capture_output=True, check=True, timeout=60)


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


def test_a_report_that_discloses_absent_evidence_is_not_penalised(tmp_path):
    """#381 aftermath. Three reports were corrected from an unbacked PASS to
    a disclosed UNSUBSTANTIATED with `evidence_present: false` — and this
    gate kept flagging them for the path string they honestly still name.

    The defect this gate exists for is a verdict RESTING on evidence nobody
    can open. A report that names its evidence AND states the evidence is
    absent is disclosing that, not claiming it. Counting it would penalise
    the exact correction that fixes the defect, which is how a gate ends up
    pushing authors to delete the disclosure instead."""
    root = _repo(tmp_path)
    (root / "r.json").write_text(json.dumps(
        {"verdict": "UNSUBSTANTIATED", "evidence_present": False,
         "sby": "formal/gone.sby"}))
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "disclosed")
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    assert "gone.sby" not in r.stdout


def test_the_exemption_requires_an_EXPLICIT_false(tmp_path):
    """NO-LEAK: only an explicit `evidence_present: false` exempts. A missing
    field, or a truthy one, must still be judged — otherwise the exemption
    becomes a way to opt out by saying nothing."""
    root = _repo(tmp_path)
    (root / "a.json").write_text(json.dumps(
        {"verdict": "PASS", "sby": "formal/gone.sby"}))            # silent
    (root / "b.json").write_text(json.dumps(
        {"verdict": "PASS", "evidence_present": True,
         "sby": "formal/also_gone.sby"}))                          # claims yes
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "not exempt")
    r = _run(root, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout
    assert "gone.sby" in r.stdout and "also_gone.sby" in r.stdout


# ── #1044: the notation the extractor could not see ──────────────────────────

def test_a_dangling_BRACE_citation_reddens(tmp_path):
    """THE PAIRED GUARD. `{setup,hold}_ss.rpt` names two specific artifacts,
    and before #1044 the token did not match `_CITE_RE` at all — `{`, `}` and
    `,` were outside its character class — so it was never judged, never
    counted, and never reported. The gate ran and said PASS.

    Measured over the default scope on the day this landed: 284 brace tokens
    across 36 of 328 documents, expanding to 608 paths, 12 of them carrying an
    evidence extension and NONE resolving. `benchmark-data/ic/METHODOLOGY.md`
    is squarely in scope and contributed ZERO citations.
    """
    _doc(tmp_path, "EV.md", "corners `sta/{setup,hold}_ss.rpt`\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout
    assert "sta/setup_ss.rpt" in r.stdout and "sta/hold_ss.rpt" in r.stdout, r.stdout


def test_a_brace_citation_whose_artifacts_EXIST_passes(tmp_path):
    """The other direction, without which the guard above is satisfied by a
    gate that simply reddens on every brace."""
    _doc(tmp_path, "EV.md", "corners `sta/{setup,hold}_ss.rpt`\n")
    for name in ("setup_ss.rpt", "hold_ss.rpt"):
        p = tmp_path / "sta" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout


def test_a_dangling_NON_EVIDENCE_citation_is_disclosed_not_dropped(tmp_path):
    """THE OUTERMOST LAYER OF #1044, and the same shape as the inner two.

    The brace fix stopped tokens being invisible to the PATTERN. `_DOCUMENT_EXT`
    moved directory-bearing `.md` from unseen to ruled-on. A token can STILL be
    invisible to the OUTPUT: matched, expanded, naming one specific artifact,
    pointing at nothing — and dropped by `_is_citation` with a bare `continue`
    because it falls outside the judged set. Not counted, not printed,
    indistinguishable from a token that was judged and cleared.

    THE FIXTURE IS `.v`/`.py` ON PURPOSE. It was `notes/DESIGN.md` when this
    guard shipped alone, which the `_DOCUMENT_EXT` half now JUDGES — so the
    fixture would have tested the judged path while claiming to test the
    unjudged one. Re-pointed at a class that is still genuinely unjudged, which
    is where the disclosure has to keep working: measured over the default
    scope, `.py` x188, `.json` x183 and `.v` sit behind that line.
    """
    _doc(tmp_path, "EV.md", "see `src/top.v` and `scripts/build.py`\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert "SEEN not judged" in r.stdout, r.stdout
    assert "src/top.v" in r.stdout, r.stdout


def test_the_disclosure_does_NOT_change_the_verdict(tmp_path):
    """Widening past the judged set is a scope change #1044 explicitly does not
    propose, and one this PR does not make unilaterally. A disclosure that
    quietly reddened the tree would BE that scope change, arrived at by the
    back door.

    This is also the guard that the `_DOCUMENT_EXT` widening did not swallow
    the disclosure channel whole: something is still both SEEN and unjudged,
    and it is still green."""
    _doc(tmp_path, "EV.md", "see `src/top.v`\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    assert "SEEN not judged" in r.stdout, r.stdout


def test_a_NON_EVIDENCE_citation_that_RESOLVES_is_not_disclosed(tmp_path):
    """The inverse, without which the guard above is satisfied by a gate that
    lists every non-evidence token it ever saw. Only the DANGLING ones are the
    finding; a path that points at something has nothing to disclose."""
    _doc(tmp_path, "EV.md", "see `src/top.v`\n")
    p = tmp_path / "src" / "top.v"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    assert "SEEN not judged" not in r.stdout, r.stdout


def test_a_JUDGED_citation_is_never_ALSO_disclosed_as_unjudged(tmp_path):
    """THE SEAM BETWEEN THE TWO HALVES OF THIS PR, which neither half could
    have a guard for on its own.

    `_DOCUMENT_EXT` judges a directory-bearing `.md`; `unjudged_dangling_ext`
    discloses what is not judged. If the second kept its own copy of the
    extension rule — as it did before these were composed — the SAME dangling
    token would be counted twice: once as a finding and once as "seen, not
    ruled on". The populations must PARTITION, so the disclosure asks
    `_is_citation`, the very predicate the verdict is computed from.
    """
    _doc(tmp_path, "M.md", "see `ic_alpha/RESULT.md`\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout            # judged, and it reddens
    assert "ic_alpha/RESULT.md" in r.stdout, r.stdout
    # ...and it is NOT also in the not-judged channel.
    assert "SEEN not judged" not in r.stdout, r.stdout


def test_a_COMMA_LESS_brace_is_still_a_template(tmp_path):
    """`{run}.log` names no particular file and a shell does not expand it
    either: `echo {x}.log` prints `{x}.log`. Expanding it would manufacture a
    finding against text that promised nothing — the failure mode the template
    rule exists to prevent. The comma is the discriminator, not the brace."""
    _doc(tmp_path, "EV.md", "placeholder `{run}.log` and `pre_{x}_post.rpt`\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout


def test_the_gate_states_how_many_documents_yielded_NOTHING(tmp_path):
    """The denominator #1044 asks for. A gate that says PASS without saying
    over what is unfalsifiable (`gate_zero_denominator_refuses_check` ruled on
    this), and this is the specific number that would have exposed the brace
    blindness the day it appeared: a document in scope, read, contributing no
    citation, and indistinguishable in the output from one that was checked
    and cleared."""
    _doc(tmp_path, "HAS.md", "see `a.log`\n")
    (tmp_path / "a.log").write_text("x")
    _doc(tmp_path, "NONE.md", "prose with no citation at all\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    assert "contributed 0  : 1 of 2 document(s)" in r.stdout, r.stdout


def test_an_unbounded_expansion_is_disclosed_not_dropped(tmp_path):
    """A bound that truncates in silence reads as 'covered everything'. This
    one announces what it declined to expand."""
    huge = "`" + "/".join("{a,b}" for _ in range(8)) + ".log`"
    _doc(tmp_path, "EV.md", f"see {huge}\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert "NOT expanded" in r.stdout, r.stdout
    assert str(E._MAX_EXPANSIONS) in r.stdout, r.stdout


# ── #1044 second half: the DOCUMENT a reader is sent to ──────────────────────

def test_a_dangling_document_citation_with_a_directory_reddens(tmp_path):
    """THE PAIRED GUARD for the second half of #1044.

    The issue's consequence line is about `.md` artefacts, not logs: "#1028
    deletes four artefacts `METHODOLOGY.md` cites, and the gate still reports
    PASS". Teaching the brace NOTATION alone did not fix that — all four are
    `.md`, and `_EVIDENCE_EXT` did not include it, so the gate saw them and
    still declined to judge them. Measured on
    `origin/withdraw/nonpassing-published-runs`: 11 of 11 expansions seen, 11 of
    11 dangling, 0 judged.
    """
    _doc(tmp_path, "M.md", "see `ic_alpha/RESULT.md`\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 1, r.stdout
    assert "ic_alpha/RESULT.md" in r.stdout, r.stdout


def test_a_document_citation_whose_target_EXISTS_passes(tmp_path):
    """Without this the guard above is satisfied by a gate that reddens on
    every `.md` token it sees."""
    _doc(tmp_path, "M.md", "see `ic_alpha/RESULT.md`\n")
    _doc(tmp_path, "ic_alpha/RESULT.md", "the result\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout


def test_a_BARE_document_name_is_prose_not_a_citation(tmp_path):
    """`RESULT.md` names a KIND of document — every run ships one, and
    "each run ships a RESULT.md" claims no particular file exists.
    `ic_alpha/RESULT.md` names ONE. Measured over the default scope: 56 of the
    108 unresolved `.md` tokens are bare, so judging them would fire on 56
    legitimately-complete documents. A gate that fires on a complete design is
    a bug in the gate, not a finding."""
    _doc(tmp_path, "M.md", "every run ships a `RESULT.md` and a `SOURCE_MANIFEST.md`\n")
    r = _run(tmp_path, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout


def test_a_citation_resolving_ABOVE_the_scan_root_is_disclosed_not_judged(tmp_path):
    """The artefact EXISTS; it lives above this gate's root, and the resolution
    ladder stops at the root on purpose (`test_resolution_never_escapes_the_
    scan_root`). Calling it dangling would be the gate reporting its own scope
    as the document's defect — which is the shape #1044 is about. Measured: 7
    such citations in the real corpus."""
    scope = tmp_path / "scope"
    scope.mkdir()
    (tmp_path / "PUBLISHING.md").write_text("policy\n")
    _doc(scope, "M.md", "see `PUBLISHING.md` at `outer/PUBLISHING.md`\n")
    (tmp_path / "outer").mkdir()
    (tmp_path / "outer" / "PUBLISHING.md").write_text("policy\n")
    r = _run(scope, tmp_path / "bl.json")
    assert r.returncode == 0, r.stdout
    assert "OUT OF SCOPE" in r.stdout, r.stdout


def test_a_file_above_the_corpus_root_does_not_silence_a_dangling_citation(tmp_path):
    """The scope walk must not reach past the corpus root.

    It used to climb FOUR ancestors of the scan root, so an unrelated file that
    merely shared the cited basename, sitting up to four levels above, was
    enough to report a genuinely dangling citation as OUT OF SCOPE and PASS.

    MEASURED with a stray proof-log file directly in /tmp: an identical fixture
    gave opposite verdicts purely by DEPTH -- 2..4 levels below /tmp reported
    rc 0 OUT OF SCOPE, 5+ levels rc 1 FAIL. pytest's tmp_path sits 3 levels
    down, which is why four of this module's own controls were red on main for
    247+ commits.

    The two arms here differ ONLY in whether the decoy exists.
    """
    deep = tmp_path / "a" / "b" / "c"
    scan = deep / "corpus"
    (scan / "sub").mkdir(parents=True)
    (scan / "sub" / "EV.md").write_text("see `proof.log` for the run\n",
                                        encoding="utf-8")

    clean = _run(scan, tmp_path / "bl1.json")
    assert clean.returncode == 1, clean.stdout
    assert "proof.log" in clean.stdout

    # the decoy: same basename, two levels above the scan root, unrelated file
    (deep.parent / "proof.log").write_text("not the cited artifact\n",
                                           encoding="utf-8")
    with_decoy = _run(scan, tmp_path / "bl2.json")
    assert with_decoy.returncode == 1, (
        "a file above the corpus root silenced a real dangling citation:\n"
        + with_decoy.stdout)
    assert "OUT OF SCOPE" not in with_decoy.stdout, with_decoy.stdout
