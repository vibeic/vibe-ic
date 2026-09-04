#!/usr/bin/env python3
"""vibe-ic#440 — the published-evidence index, and the gate that keeps it honest.

WHAT IS PINNED
--------------
The index's whole value is that a reader can trust it without opening a JSON
per cell, and the only thing that can make it trustworthy is a gate that FAILS
when it stops describing the tree. So the load-bearing tests here are the
MUTATION CONTROLS: change a cell's audit verdict, leave the index alone, and
`--check` must go red.

The repo has already run the experiment for the ungated version.
`benchmark-data/BENCHMARK_IC_CAMPAIGN_STATUS.md` is hand-maintained, and all
three of its citations for the three cells that DID converge point at
directories that do not exist — the folders were renamed and the table was
not. `test_campaign_status_citations_are_stale_which_is_why_this_is_generated`
pins that as the measured justification rather than an assertion.

REAL-DATA CONTROL
-----------------
A gate justified only by its author's fixture has never judged a production
artefact. `test_real_tree_*` build the index from the actual published tree and
mutate a REAL audit verdict, so defect-in -> FAIL and defect-out -> PASS is
demonstrated on the same artefacts CI judges.

WHERE THAT TREE IS NOW
----------------------
The published cells moved to https://github.com/vibeic/benchmark-data. This
checkout still carries `benchmark-data/` — it holds the design INPUTS — so
`<repo>/benchmark-data/ic` is still a directory, and the old "not checked out"
guard therefore never fired; the four real-data tests below simply went red
about a corpus that had moved. `_published_corpus` answers the question the guard meant
to ask ("is a published CELL readable here?"), and `@needs_corpus` renders "I
could not look" as a SKIP naming the corpus rather than as a defect claim —
the same rule vibe-ic#1357 established for an absent TOOL. Where the corpus IS
readable these four run exactly as before and can still fail.

Fixture cells use deliberately synthetic names (`unit_one`, `unit_two/v0.0.1_procX`)
— no IC, PDK, vendor or SKU literal, per `source_chip_agnostic_check`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "benchmark_evidence_index.py"

sys.path.insert(0, str(PROGRAMS))
import benchmark_evidence_index as bei  # noqa: E402

from _published_corpus import corpus_root, needs_corpus  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Fixture construction
# ─────────────────────────────────────────────────────────────────────

def _cell(ic_root: Path, name: str, *, audit=None, steps=None,
          orch=None, result=None, corpus=True) -> Path:
    d = ic_root / name
    d.mkdir(parents=True, exist_ok=True)
    if audit is not None:
        p = d / bei.AUDIT_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        body = {"verdict": audit}
        if steps is not None:
            body["step_counts"] = steps
        p.write_text(json.dumps(body))
    if orch is not None:
        for key, verdict in orch.items():
            p = d / "reports" / "orchestrator" / f"{key}_one_shot.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"verdict": verdict}))
    if result is not None:
        (d / bei.RESULT_REL).write_text(result)
    if corpus:
        g = d / "phase1" / "generated_docs"
        g.mkdir(parents=True, exist_ok=True)
        (g / "L1_DATASHEET.json").write_text("{}")
    return d


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """A repo-shaped root with three cells, one per classification."""
    ic = tmp_path / bei.IC_SUBDIR
    ic.mkdir(parents=True)
    _cell(ic, "unit_one/v0.0.1_procX", audit="PASS_WITH_WAIVERS",
          steps={"PASS": 30, "FAIL": 0, "MISSING": 0, "WAIVED": 2},
          orch={"vibe_ic": "PASS_WITH_WAIVERS"},
          result="# r\n\nOVERALL: PASS_WITH_WAIVERS\n")
    _cell(ic, "unit_two", audit="FAIL",
          steps={"PASS": 2, "FAIL": 7, "MISSING": 27, "WAIVED": 0},
          orch={"vibe_ic": "FAIL"}, result="# r\n\n> STATUS: COMPLETE — done\n")
    _cell(ic, "unit_three/rerun_a", result="# r\n\nnarrative only\n",
          corpus=False)
    return tmp_path


def _run(root: Path, *args) -> subprocess.CompletedProcess:
    return _pr.run(
        [sys.executable, str(PROG), "--root", str(root), *args],
        capture_output=True, text=True)


# ─────────────────────────────────────────────────────────────────────
# Classification
# ─────────────────────────────────────────────────────────────────────

def test_three_states_are_kept_apart(tree: Path):
    """CONVERGED / RETAINED FAILURE / UNAUDITED are three states, not two.

    Folding "no audit ran" into either of the others is the same error as
    deleting the failures: it makes an absent result indistinguishable from a
    measured one.
    """
    text, findings = bei.build(tree)
    assert findings == []
    assert "| CONVERGED EVIDENCE | 1 |" in text
    assert "| RETAINED FAILURE | 1 |" in text
    assert "| UNAUDITED RECORD | 1 |" in text
    assert "`unit_one/v0.0.1_procX`" in text.split("## RETAINED FAILURE")[0]
    assert "`unit_three/rerun_a`" in text.split("## UNAUDITED RECORD")[1]


def test_step_counts_are_shown_because_one_fail_is_not_twentyseven_missing(tree):
    """Two cells both read FAIL; the magnitude is what distinguishes them."""
    text, _ = bei.build(tree)
    assert "P2 F7 M27 W0" in text


def test_a_cell_with_no_audit_shows_no_verdict_rather_than_a_default(tree):
    text, _ = bei.build(tree)
    row = [l for l in text.splitlines() if "`unit_three/rerun_a`" in l][0]
    assert "PASS" not in row and "FAIL" not in row


# ─────────────────────────────────────────────────────────────────────
# The contradiction the index exists to surface
# ─────────────────────────────────────────────────────────────────────

def test_declared_verdict_in_a_blockquote_is_still_a_declared_verdict():
    """Measured on the real tree: a cell opening `> STATUS: COMPLETE` read as
    UNSTATED purely because the line sat in a blockquote, hiding a RESULT.md
    that claims success next to an audit that says FAIL."""
    assert bei.result_verdict("> STATUS: COMPLETE — flow closed\n") == "COMPLETE"
    assert bei.result_verdict("- **OVERALL:** PRODUCTION-READY\n") == "PRODUCTION-READY"
    assert bei.result_verdict("**OVERALL: PRODUCTION-READY** (exit 0)\n") == "PRODUCTION-READY"


def test_prose_only_success_is_UNSTATED_not_guessed_as_PASS():
    """A token found anywhere in a narrative is not a declared verdict.

    An earlier draft fell back to "first PASS/FAIL token in the file" and
    reported a declared PASS for documents whose only match was the word
    inside an unrelated sentence. A guessed verdict inside the artefact built
    to stop guessed verdicts is worse than an honest UNSTATED.
    """
    doc = ("# result\n\nEvery suite reports `mismatches=0 -> PASS`, so the "
           "flow is demonstrated end to end.\n")
    assert bei.result_verdict(doc) == "UNSTATED"


def test_contradiction_is_rendered_side_by_side(tree: Path):
    text, _ = bei.build(tree)
    row = [l for l in text.splitlines() if "`unit_two`" in l][0]
    assert "FAIL" in row and "COMPLETE" in row


# ─────────────────────────────────────────────────────────────────────
# MUTATION CONTROLS — the gate must actually fire
# ─────────────────────────────────────────────────────────────────────

def test_MUTATION_audit_verdict_changes_and_the_row_does_not(tree: Path):
    """THE requirement from #440: a cell whose audit verdict changes while its
    index row does not is a FAIL."""
    assert _run(tree, "--write").returncode == 0
    assert _run(tree, "--check").returncode == 0, "clean tree must PASS first"

    audit = tree / bei.IC_SUBDIR / "unit_one/v0.0.1_procX" / bei.AUDIT_REL
    body = json.loads(audit.read_text())
    body["verdict"] = "FAIL"                      # converged -> failed
    audit.write_text(json.dumps(body))

    r = _run(tree, "--check")
    assert r.returncode == 1, "verdict flipped and the gate stayed green"
    assert "disagrees with the artefacts" in r.stdout

    # defect out -> green again, so the FAIL above is attributable
    body["verdict"] = "PASS_WITH_WAIVERS"
    audit.write_text(json.dumps(body))
    assert _run(tree, "--check").returncode == 0


def test_MUTATION_step_counts_change_while_the_verdict_does_not(tree: Path):
    """A FAIL that grows from one failed gate to twenty-seven missing steps is
    a different result reported by the same word."""
    assert _run(tree, "--write").returncode == 0
    audit = tree / bei.IC_SUBDIR / "unit_two" / bei.AUDIT_REL
    body = json.loads(audit.read_text())
    body["step_counts"]["MISSING"] = 3
    audit.write_text(json.dumps(body))
    assert _run(tree, "--check").returncode == 1


def test_MUTATION_new_cell_lands_with_no_row(tree: Path):
    assert _run(tree, "--write").returncode == 0
    _cell(tree / bei.IC_SUBDIR, "unit_four", audit="FAIL", result="x")
    assert _run(tree, "--check").returncode == 1


def test_MUTATION_cell_removed_but_row_remains(tree: Path):
    assert _run(tree, "--write").returncode == 0
    shutil.rmtree(tree / bei.IC_SUBDIR / "unit_two")
    r = _run(tree, "--check")
    assert r.returncode == 1


def test_MUTATION_hand_edit_of_the_generated_file(tree: Path):
    assert _run(tree, "--write").returncode == 0
    idx = tree / bei.IC_SUBDIR / bei.INDEX_NAME
    idx.write_text(idx.read_text().replace("RETAINED FAILURE — 1",
                                           "RETAINED FAILURE — 0"))
    assert _run(tree, "--check").returncode == 1


def test_missing_index_is_a_FAIL_not_a_silent_pass(tree: Path):
    r = _run(tree, "--check")
    assert r.returncode == 1
    assert "does not exist" in r.stdout


# ─────────────────────────────────────────────────────────────────────
# The curated sidecar
# ─────────────────────────────────────────────────────────────────────

def test_retention_note_is_rendered_into_the_row(tree: Path):
    (tree / bei.IC_SUBDIR / bei.RETENTION_NAME).write_text(json.dumps(
        {"retained_for": {"unit_two": "reproduction for #4242"}}))
    text, findings = bei.build(tree)
    assert findings == []
    row = [l for l in text.splitlines() if "`unit_two`" in l][0]
    assert "reproduction for #4242" in row


def test_retention_note_for_a_cell_that_does_not_exist_is_a_FINDING(tree: Path):
    """The failure mode that rotted the hand-maintained table: a citation that
    outlived the directory it names."""
    (tree / bei.IC_SUBDIR / bei.RETENTION_NAME).write_text(json.dumps(
        {"retained_for": {"unit_gone/v9.9.9_procZ": "why"}}))
    _text, findings = bei.build(tree)
    assert len(findings) == 1 and "unit_gone" in findings[0]
    assert _run(tree, "--write").returncode == 1


def test_a_multiline_curated_note_cannot_split_a_table_row(tree: Path):
    """A newline in a curated value would silently turn one row into two."""
    (tree / bei.IC_SUBDIR / bei.RETENTION_NAME).write_text(json.dumps(
        {"retained_for": {"unit_two": "line one\nline two | with a pipe"}}))
    text, _ = bei.build(tree)
    rows = [l for l in text.splitlines() if "line one" in l]
    assert len(rows) == 1
    assert "line one line two \\| with a pipe" in rows[0]
    assert rows[0].count("|") == rows[0].count("\\|") + 8  # 7 cells -> 8 pipes


def test_curated_notes_render(tree: Path):
    (tree / bei.IC_SUBDIR / bei.RETENTION_NAME).write_text(json.dumps(
        {"retained_for": {}, "notes": ["a citation nobody checked"]}))
    text, _ = bei.build(tree)
    assert "## Notes" in text and "a citation nobody checked" in text


# ─────────────────────────────────────────────────────────────────────
# Determinism — byte-equality is the mechanism, so nothing may drift
# ─────────────────────────────────────────────────────────────────────

def test_output_is_a_pure_function_of_the_tree(tree: Path):
    """No timestamp, no version stamp. A field that changes on every run makes
    byte-equality useless, and byte-equality is how drift is detected."""
    assert bei.build(tree)[0] == bei.build(tree)[0]
    assert _run(tree, "--write").returncode == 0
    first = (tree / bei.IC_SUBDIR / bei.INDEX_NAME).read_text()
    assert _run(tree, "--write").returncode == 0
    assert (tree / bei.IC_SUBDIR / bei.INDEX_NAME).read_text() == first


# ─────────────────────────────────────────────────────────────────────
# REAL-DATA controls — on the tree CI actually judges
# ─────────────────────────────────────────────────────────────────────

def _real_ic() -> Path:
    """The `ic/` root of the published corpus.

    Only ever reached from under `@needs_corpus`, so it does not need — and must
    not invent — a skip reason of its own.
    """
    return corpus_root() / "ic"


def _corpus_repo_root(tmp_path: Path) -> Path:
    """A repo-shaped root whose `benchmark-data/` IS the published corpus.

    `benchmark_evidence_index` addresses cells as `<root>/benchmark-data/ic/…`,
    while a clone of `vibeic/benchmark-data` carries `ic/…` at its top. One
    symlink restores the shape the program expects. Nothing is copied, and
    nothing under the corpus is written — every caller below passes `--check`.
    """
    root = tmp_path / "corpus_repo"
    root.mkdir()
    (root / "benchmark-data").symlink_to(corpus_root())
    return root


@needs_corpus
def test_real_tree_index_is_in_sync(tmp_path: Path):
    """The committed index describes the committed artefacts. This is the same
    assertion the CI hygiene gate makes; it is duplicated here so a cell landed
    without regenerating fails in pytest too, not only in CI."""
    r = _run(_corpus_repo_root(tmp_path), "--check")
    assert r.returncode == 0, r.stdout + r.stderr


@needs_corpus
def test_real_tree_still_holds_all_three_states(tmp_path: Path):
    """The frozen 8c4b608 publication population is represented exactly.

    The old assertion required a non-empty RETAINED FAILURE bucket.  That
    became a demand to republish a failing cell after benchmark-data bcf2f94
    deliberately withdrew all four non-converged result cells.  Classification
    still has three-state mutation coverage above.  The real published-cell
    population is now exactly the three named converged SPM specimens; design
    input directories are not published cells and must not be invented as
    UNAUDITED records merely to keep that bucket non-empty.
    """
    text, findings = bei.build(_corpus_repo_root(tmp_path))
    assert findings == []
    counts = {}
    for section in (bei.CONVERGED, bei.RETAINED_FAILURE, bei.UNAUDITED):
        line = [l for l in text.splitlines()
                if l.startswith(f"| {section} |")][0]
        counts[section] = int(line.rsplit("|", 2)[1].strip())
    assert counts == {
        bei.CONVERGED: 3,
        bei.RETAINED_FAILURE: 0,
        bei.UNAUDITED: 0,
    }, counts
    tracked = bei._published_tree.published_paths(_real_ic())
    assert bei.discover_cells(_real_ic(), tracked) == [
        "spm/v1.10.18_sky130A",
        "spm/v1.14.88_gf180mcuD",
        "spm/v1.5.65_sky130A",
    ]


@needs_corpus
def test_real_tree_MUTATION_a_real_verdict_flip_is_caught(tmp_path: Path):
    """Defect-in / defect-out on REAL artefacts.

    Copies only the verdict-bearing metadata of every real cell (audit,
    orchestrator, RESULT.md, one generated_docs marker) — a faithful stand-in
    that is cheap. The copy is not a git repo, so `_published_tree` reports
    "not a published tree" and the walk falls back to disk, which is the
    documented behaviour for a run tree handed over on its own.
    """
    real = _real_ic()
    dst_ic = tmp_path / bei.IC_SUBDIR
    tracked = bei._published_tree.published_paths(real)
    assert tracked, "expected a published tree"
    n = 0
    for rel in sorted(tracked):
        keep = (rel.endswith("/" + bei.AUDIT_REL)
                or rel.endswith("/" + bei.RESULT_REL)
                or "/reports/orchestrator/" in rel
                or f"/{bei.CORPUS_MARKER}" in rel)
        if not keep:
            continue
        d = dst_ic / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(real / rel, d)
        n += 1
    assert n > 50, f"expected a substantial real corpus, copied {n}"

    baseline, _ = bei.build(tmp_path)
    assert bei.CONVERGED in baseline

    # Flip a REAL converged verdict to FAIL.
    converged = [rel for rel in sorted(tracked)
                 if rel.endswith("/" + bei.AUDIT_REL)
                 and json.loads((real / rel).read_text()).get("verdict")
                 in bei.CONVERGED_VERDICTS]
    assert converged, "no converged cell on the real tree to mutate"
    victim = dst_ic / converged[0]
    body = json.loads(victim.read_text())
    body["verdict"] = "FAIL"
    victim.write_text(json.dumps(body))

    mutated, _ = bei.build(tmp_path)
    assert mutated != baseline, "a real verdict flip did not move the index"

    body["verdict"] = "PASS_WITH_WAIVERS"
    victim.write_text(json.dumps(body))
    assert bei.build(tmp_path)[0] == baseline, "not attributable to the flip"


@needs_corpus
def test_campaign_status_citations_are_stale_which_is_why_this_is_generated():
    """The measured justification for generating rather than writing.

    `BENCHMARK_IC_CAMPAIGN_STATUS.md` is the hand-maintained equivalent. Its
    rows for the converged cells cite `RESULT.md` paths under directory names
    that no longer exist. Pinned as a fact, not an opinion — if someone repairs
    that file, this test tells them to reconsider whether the generated index
    is still needed rather than letting the claim rot in a docstring.

    Needs the corpus even though it was GREEN without it, and that is the whole
    point: with no published cells every citation dangles, so the assertion
    "the hand-maintained table has rotted" passes for a reason that says nothing
    about the table. A pass produced by having nothing to look at is the exact
    false certificate this file exists to prevent.
    """
    root = corpus_root()
    status = root / "BENCHMARK_IC_CAMPAIGN_STATUS.md"
    if not status.is_file():
        pytest.skip("campaign status not checked out")
    import re
    cited = re.findall(r"`(ic/[A-Za-z0-9_./-]+\.md)`", status.read_text())
    assert cited, "expected the hand-maintained table to cite cell paths"
    dead = [c for c in cited if not (root / c).is_file()]
    assert dead, ("BENCHMARK_IC_CAMPAIGN_STATUS.md citations now all resolve; "
                  "re-read whether the generated index is still the answer")
