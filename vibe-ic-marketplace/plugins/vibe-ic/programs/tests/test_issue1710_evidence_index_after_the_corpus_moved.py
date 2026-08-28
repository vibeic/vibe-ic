#!/usr/bin/env python3
"""The published-evidence INDEX after the corpus moved to its own repository.

WHY THIS FILE EXISTS
====================
`benchmark_evidence_index.py --check --root <repo>` addressed the corpus as the
hardcoded relative `benchmark-data/ic`. The published cells moved to
`vibeic/benchmark-data` (v1.10.56), so in this repo that directory is gone and
the gate answered:

    [benchmark_evidence_index] no such directory: <repo>/benchmark-data/ic
    rc = 1

rc=1 in that program MEANS "the index disagrees with the artefacts it
describes". No index disagreed with anything — the tree had moved and the gate
had not been told. A gate that reports a defect it never measured is the same
false certificate as one that reports a pass it never measured, aimed the other
way, and it costs the same thing: the finding is noise, so the gate stops being
read.

THE THREE OUTCOMES, WHICH MUST NOT COLLAPSE INTO TWO (the #1710 shape)
======================================================================
    pointer set + broken            -> UNDETERMINED (rc=2). Never excused, with or
                                       without --corpus-may-be-absent.
    nothing set + nothing local
      + the caller said so          -> NO_CORPUS (rc=0). Nothing scanned, no index
                                       generated, no index compared — and nothing
                                       CLAIMED to have been.
    nothing set + nothing local
      + nobody said so              -> UNDETERMINED (rc=2). Unchanged.

The dangerous row is the middle one: an rc=0 for a scan that did not happen is
the false-certificate shape this repo keeps closing. It is safe only because it
cannot be reached while a pointer exists, it is opt-in AT THE CALL SITE, and it
prints NO_CORPUS rather than PASS.

AND ONE MORE, WHICH IS THIS GATE'S OWN
======================================
This program does not only decide; it WRITES A DOCUMENT PEOPLE READ. So an
INDEX.md with empty sections must tell its reader which emptiness it is —
"walked, and nothing is in this classification" or "there was no corpus" — in
the file itself, without knowing how it was produced. Under NO_CORPUS no index
is written at all, which is the strongest available form of that distinction.

EVERY CASE HERE IS PAIRED. A file that only proved "it stopped blocking" would
pass against a gate that had been deleted.

Fixture cells use synthetic names (`unit_one`, `v0.0.1_procX`) — no IC, PDK,
vendor or SKU literal, per `source_chip_agnostic_check`.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
PROG = PROGRAMS / "benchmark_evidence_index.py"
ENV = "VIBE_IC_BENCHMARK_DATA"

AUDIT_REL = "reports/audit/phase23_completion_audit.json"


# 60 s, not 180 (vibe-ic#1711). 180 was the WHOLE pytest session budget, and
# with `--timeout-method=thread` a bound that large can never fire as a TEST
# failure: pytest kills the SESSION first, `--maxfail` stops applying, and every
# other file in the subset loses its verdict. 60 s is the ceiling
# `ci_harness_timeout_ceiling_check` resolves (180 // 3) and the bound 464 other
# call sites in this corpus already use. MEASURED here: 9 passed in 0.77 s,
# slowest item 0.07 s — 60 s is ~850x that, so it cannot fire on passing work.
def _run(*args: str, env_tree: str | None = None):
    env = dict(os.environ)
    env.pop(ENV, None)
    if env_tree is not None:
        env[ENV] = env_tree
    out = _pr.run([sys.executable, str(PROG), *args],
                         capture_output=True, text=True, env=env)
    return out.returncode, (out.stdout + out.stderr)


@pytest.fixture()
def repo_without_corpus(tmp_path: Path) -> Path:
    """A repo root that carries no `benchmark-data/` at all — this repo's state."""
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _corpus(root: Path, *, verdict: str = "FAIL") -> Path:
    """A clone-shaped corpus: `<root>/ic/<design>/v<semver>_<pdk>/`.

    Built from the naming rule the program documents rather than a stand-in for
    it, so the fixture exercises the real discovery predicate.
    """
    cell = root / "ic" / "unit_one" / "v0.0.1_procX"
    (cell / "reports" / "audit").mkdir(parents=True)
    (cell / AUDIT_REL).write_text(json.dumps(
        {"verdict": verdict,
         "step_counts": {"PASS": 20, "FAIL": 1, "MISSING": 0, "WAIVED": 2}}))
    (cell / "RESULT.md").write_text("# result\nOVERALL: PRODUCTION-READY\n")
    return root


# ---------------------------------------------------------------------------
# 1. NOTHING ANYWHERE + the caller said so -> NO_CORPUS, rc 0, and it SAYS
#    nothing was scanned. This is the case that unblocks the removal.
# ---------------------------------------------------------------------------
def test_no_corpus_with_the_flag_is_rc0_and_says_it_scanned_nothing(repo_without_corpus):
    rc, out = _run("--check", "--root", str(repo_without_corpus),
                   "--corpus-may-be-absent")
    assert rc == 0, out
    assert "NO_CORPUS" in out, out
    assert "NOTHING WAS SCANNED" in out, "an rc=0 must not read as a scan that happened"
    assert "PASS" not in out, "a scan that did not happen must never be spelled PASS"
    # and it names what it did not look at, which is the whole remedy
    assert "benchmark-data/ic" in out, out
    assert ENV in out, "it must say how to make the gate check something"


# ---------------------------------------------------------------------------
# 2. …AND WITHOUT THE FLAG IT STILL REFUSES. The half that makes case 1 mean
#    something: the relaxation is opt-in, not the new default.
# ---------------------------------------------------------------------------
def test_no_corpus_without_the_flag_is_still_undetermined(repo_without_corpus):
    rc, out = _run("--check", "--root", str(repo_without_corpus))
    assert rc == 2, f"the relaxation must be opt-in\n{out}"
    assert "UNDETERMINED" in out, out
    assert "NO_CORPUS" not in out, out


# ---------------------------------------------------------------------------
# 3. A BROKEN POINTER IS NEVER EXCUSED — not even with the flag. "Somebody said
#    where the corpus is and was wrong" is a different event from "there is none".
# ---------------------------------------------------------------------------
def test_a_broken_pointer_is_undetermined_even_with_the_flag(tmp_path, repo_without_corpus):
    rc, out = _run("--check", "--root", str(repo_without_corpus),
                   "--corpus-may-be-absent", env_tree=str(tmp_path / "nowhere"))
    assert rc == 2, f"a set-and-wrong pointer must never be waved through\n{out}"
    assert "UNDETERMINED" in out, out
    assert ENV in out, "the refusal must name the pointer it followed"
    assert "NO_CORPUS" not in out, "a broken pointer was laundered as an absent corpus"


# ---------------------------------------------------------------------------
# 4. THE POINTER IS FOLLOWED, AND ANNOUNCED. An index re-derived from a tree
#    other than the one the command line names, in silence, is how a stale index
#    would be certified fresh against whatever tree happened to be handy.
# ---------------------------------------------------------------------------
def test_the_pointer_overrides_the_repo_path_and_says_so(tmp_path, repo_without_corpus):
    root = _corpus(tmp_path / "clone")
    rc, out = _run("--write", "--root", str(repo_without_corpus), env_tree=str(root))
    assert f"{ENV} overrides" in out, out
    assert str(root / "ic") in out, "the tree actually walked must be named"
    assert (root / "ic" / "INDEX.md").is_file(), (
        f"the index was not written beside the corpus it describes\n{out}")


# ---------------------------------------------------------------------------
# 5. A REAL POINTED-AT CORPUS IS ACTUALLY EXAMINED. Without this, cases 1-4 are
#    all compatible with a gate that never walks anything.
# ---------------------------------------------------------------------------
def test_a_pointed_at_corpus_is_really_examined(tmp_path, repo_without_corpus):
    root = _corpus(tmp_path / "clone")
    rc, _ = _run("--write", "--root", str(repo_without_corpus), env_tree=str(root))
    assert rc == 0
    rc, out = _run("--check", "--root", str(repo_without_corpus),
                   "--corpus-may-be-absent", env_tree=str(root))
    assert rc == 0, out
    assert "NO_CORPUS" not in out and "UNDETERMINED" not in out, out
    assert "1 cell row" in out, f"the gate reported no denominator\n{out}"
    assert "v0.0.1_procX" in (root / "ic" / "INDEX.md").read_text(), (
        "the cell it was pointed at does not appear in what it generated")


# ---------------------------------------------------------------------------
# 6. AND IT CAN STILL FAIL, WITH THE FLAG SET. This change hands the gate an
#    escape hatch, so the escape hatch must not reach the case where there IS a
#    corpus and the index has stopped describing it.
# ---------------------------------------------------------------------------
def test_a_drifted_index_still_fails_while_the_flag_is_set(tmp_path, repo_without_corpus):
    root = _corpus(tmp_path / "clone", verdict="FAIL")
    assert _run("--write", "--root", str(repo_without_corpus),
                env_tree=str(root))[0] == 0

    # PLANT THE DEFECT: a real verdict flips, the index is left alone.
    audit = root / "ic" / "unit_one" / "v0.0.1_procX" / AUDIT_REL
    d = json.loads(audit.read_text())
    d["verdict"] = "PASS_WITH_WAIVERS"
    audit.write_text(json.dumps(d))

    rc, out = _run("--check", "--root", str(repo_without_corpus),
                   "--corpus-may-be-absent", env_tree=str(root))
    assert rc == 1, (
        f"a cell whose verdict changed while its index row did not was passed "
        f"while --corpus-may-be-absent was set — the flag reached a case it must "
        f"never reach\n{out}")
    assert "NO_CORPUS" not in out, out
    assert "stale" in out, out


# ---------------------------------------------------------------------------
# 7. AN EMPTY-BUT-PRESENT CORPUS IS A DETERMINATION, NOT AN ABSENCE — and the
#    DOCUMENT says which one it is. "I looked, there is nothing" collapsed into
#    "there was nowhere to look" is the same error in the other direction, and
#    the reader of INDEX.md is the one who pays for it.
# ---------------------------------------------------------------------------
def test_an_empty_but_present_corpus_is_measured_and_says_so(tmp_path, repo_without_corpus):
    root = tmp_path / "clone"
    (root / "ic").mkdir(parents=True)
    rc, out = _run("--write", "--root", str(repo_without_corpus), env_tree=str(root))
    assert rc == 0, out
    assert "NO_CORPUS" not in out, (
        f"a corpus that WAS read and publishes nothing was reported as absent\n{out}")
    text = (root / "ic" / "INDEX.md").read_text()
    assert "Zero published cells were discovered" in text, text[:2000]
    assert "MEASUREMENT" in text, (
        "an index with three empty sections must tell its reader that the corpus "
        "was walked, not that it was missing")


# ---------------------------------------------------------------------------
# 8. UNDER NO_CORPUS NOTHING IS WRITTEN. An index of empty sections left on disk
#    by a run that walked nothing would be a document asserting, in the repo's
#    own generated voice, that the corpus published nothing.
# ---------------------------------------------------------------------------
def test_write_under_no_corpus_generates_no_document(repo_without_corpus):
    rc, out = _run("--write", "--root", str(repo_without_corpus),
                   "--corpus-may-be-absent")
    assert rc == 0, out
    assert "NO_CORPUS" in out, out
    assert not (repo_without_corpus / "benchmark-data").exists(), (
        f"an index was generated over a corpus that does not exist\n{out}")


# ---------------------------------------------------------------------------
# 9. THE SHIPPED CALL SITE CARRIES THE FLAG. Everything above tests the program;
#    this tests the only thing that invokes it in CI. Without it the program
#    could be perfect and the hygiene lane still red.
# ---------------------------------------------------------------------------
def test_the_hygiene_lane_actually_passes_the_flag():
    gates = PROGRAMS.parents[3] / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not gates.is_file():
        pytest.skip(f"{gates} not present in this checkout")
    lines = [ln for ln in gates.read_text().splitlines()
             if "benchmark_evidence_index.py" in ln
             and not ln.strip().startswith("#")]
    assert lines, "the hygiene lane no longer invokes this program at all"
    assert all("--corpus-may-be-absent" in ln for ln in lines), (
        "the hygiene lane invokes the gate without the flag, so a repo with no "
        "corpus is still red:\n" + "\n".join(lines))
