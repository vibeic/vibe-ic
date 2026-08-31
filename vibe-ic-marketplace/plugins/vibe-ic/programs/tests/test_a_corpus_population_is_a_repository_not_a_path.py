#!/usr/bin/env python3
"""A count's POPULATION is the corpus repository, not the path that reached it.

vibe-ic#1223 established that an integer is meaningless without the set it was
counted over, so every corpus ratchet records `corpus_population` and refuses
to hold a count from one population against a sweep of another. That refusal is
right. What decided WHICH population a sweep had was a path spelling, and a
path spelling identifies neither the corpus repository nor its state:

    `_corpus_location.population_key` normalised to the canonical name ONLY
    when the corpus arrived through $VIBE_IC_BENCHMARK_DATA. A caller who
    NAMED the very same tree got the git-relative path instead.

MEASURED on main at `e9ec0ce1c1`, on a host carrying a clone of the published
corpus at `~/benchmark-data`, against `step_internal_fail_bubble_up_baseline`
(`corpus_population: benchmark-data/ic`, one recorded run):

    step_internal_fail_bubble_up_check --corpus ~/benchmark-data/ic
        rc 2 NOT CHECKED — "measured over 'benchmark-data/ic' and this sweep
        covered 'ic' — a count over one population is not a line to hold over
        another"
      ... printed one line ABOVE its own measurement of
        "4 published run tree(s), 4 with a reports/ tree, 1 unacknowledged
         step-internal FAIL(s)"
      which is the recorded `runs_swept`, `runs_with_reports` and
      `findings_total`, exactly. The sweep was standing on the entry the
      register names and refused to examine it.

    VIBE_IC_BENCHMARK_DATA=~/benchmark-data ... same cells
        rc 0, and the entry EXAMINED: "u_hawaii_adc/...: 1".

Two verdicts over one population, decided by how the caller spelled it — and
`--corpus <root>/benchmark-data/ic` is the spelling `tools/ci/repo_hygiene_gates.sh`
uses, so it is the refused one.

BOTH DIRECTIONS. A key derived from a repository could also collapse genuinely
different populations into one, which would be strictly worse than the defect:
so every widening below is asserted with the narrowing that must survive it —
a tree that is NOT a clone of the published corpus still keys by its path, a
narrower root inside the clone still keys narrower, and a non-repository
directory is unchanged.

All fixtures are SYNTHESIZED. No design, vendor or PDK name appears.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "step_internal_fail_bubble_up_check.py"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _corpus_location as CL          # noqa: E402
import step_internal_fail_bubble_up_check as M   # noqa: E402


# ─────────────────────────────────────────────────────────── fixtures
def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


def _clone_of(tmp_path: Path, dirname: str, origin: str) -> Path:
    """A git checkout named `dirname` whose `origin` remote is `origin`.

    The directory name and the remote are varied INDEPENDENTLY on purpose:
    that is the whole question. `git clone <corpus> /tmp/x` and
    `git clone <corpus> ~/benchmark-data` are one repository, and the only
    thing on disk that says so is the remote.
    """
    root = tmp_path / dirname
    (root / "ic" / "design" / "v1_0_pdkA" / "reports" / "phase3").mkdir(
        parents=True)
    (root / "ic" / "design" / "v1_0_pdkA" / "reports" / "phase3"
     / "gate.json").write_text(json.dumps({"verdict": "PASS"}))
    _git(root.parent, "init", "-q", dirname)
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "remote", "add", "origin", origin)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "corpus")
    return root


CANON = f"https://example.invalid/vibeic/{CL.CANONICAL_CORPUS_NAME}.git"
OTHER = "https://example.invalid/vibeic/some-other-repo.git"


# ────────────────────────────────────────────────────────── the defect
def test_the_same_corpus_keys_the_same_however_the_caller_reached_it(tmp_path):
    """THE HEADLINE. One checkout, two origins of the resolution, one key."""
    corpus = _clone_of(tmp_path, "any-clone-name", CANON) / "ic"
    named = CL.population_key(corpus, CL.NAMED)
    via_env = CL.population_key(corpus, CL.ENV)
    assert named == via_env == f"{CL.CANONICAL_CORPUS_NAME}/ic", (named, via_env)


def test_the_clone_directory_name_does_not_decide_the_population(tmp_path):
    """The other half of the same fact: two clones of one repository, checked
    out under different names, are one population."""
    a = _clone_of(tmp_path, "benchmark-data", CANON) / "ic"
    b = _clone_of(tmp_path, "_matrix_scratch_dir", CANON) / "ic"
    assert (CL.population_key(a, CL.NAMED)
            == CL.population_key(b, CL.NAMED)
            == f"{CL.CANONICAL_CORPUS_NAME}/ic")


def test_a_named_sweep_of_the_recorded_population_examines_the_entry(tmp_path):
    """END TO END, and the sentence the shard red turned on.

    The register names one run and records the population it was measured
    over. Sweeping that population BY PATH must examine that run — not report
    it as a count that fell, and not refuse to look at all.
    """
    clone = _clone_of(tmp_path, "corpus-clone", CANON)
    d = clone / "ic" / "design" / "v1_0_pdkA" / "reports" / "phase3"
    (d / "unack.json").write_text(json.dumps(
        {"verdict": "FAIL", "detail": "synthetic unacknowledged fail"}))
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "one unacknowledged fail")

    base = tmp_path / "baseline.json"
    rec = subprocess.run(
        [sys.executable, str(GATE), "--corpus", str(clone / "ic"),
         "--baseline", str(base), "--write-baseline"],
        capture_output=True, text=True)
    assert rec.returncode == 0, rec.stderr
    doc = json.loads(base.read_text())
    assert doc["findings_total"] == 1
    assert doc["corpus_population"] == f"{CL.CANONICAL_CORPUS_NAME}/ic", doc
    assert list(doc["per_run"]) == ["design/v1_0_pdkA"], doc["per_run"]

    got = subprocess.run(
        [sys.executable, str(GATE), "--corpus", str(clone / "ic"),
         "--baseline", str(base)], capture_output=True, text=True)
    assert got.returncode == 0, (got.returncode, got.stdout, got.stderr)
    assert "design/v1_0_pdkA: 1" in got.stdout, got.stdout
    assert "not a line to hold over another" not in got.stderr


# ──────────────────────────────────── the widening is bounded (both ways)
def test_a_tree_that_is_not_the_published_corpus_still_keys_by_its_path(
        tmp_path):
    """THE PAIRED GUARD, and the one that matters most.

    A key that canonicalised every git checkout would make two genuinely
    different corpora ratchet against each other — the exact failure #1223
    exists to prevent, arrived at from the other side.
    """
    other = _clone_of(tmp_path, "benchmark-data-lookalike", OTHER) / "ic"
    assert CL.population_key(other, CL.NAMED) == "ic"


def test_a_checkout_with_no_origin_keeps_the_previous_rule(tmp_path):
    """A repository identity that is sometimes absent may narrow a key, never
    widen one — so a checkout that does not say what it is a clone of must
    behave exactly as it did before."""
    root = tmp_path / "no-remote"
    (root / "ic").mkdir(parents=True)
    (root / "ic" / "f.txt").write_text("x")
    _git(root.parent, "init", "-q", "no-remote")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "c")
    assert CL.population_key(root / "ic", CL.NAMED) == "ic"
    assert (CL.population_key(root / "ic", CL.ENV)
            == f"{CL.CANONICAL_CORPUS_NAME}/ic")


def test_a_narrower_root_inside_the_clone_still_keys_narrower(tmp_path):
    """`--corpus` keeps meaning what it says. A key that ignored where it was
    pointed would let a sweep of one design ratchet against the whole corpus."""
    clone = _clone_of(tmp_path, "corpus-clone", CANON)
    assert (CL.population_key(clone / "ic" / "design", CL.NAMED)
            == f"{CL.CANONICAL_CORPUS_NAME}/ic/design")
    assert (CL.population_key(clone, CL.NAMED)
            == CL.CANONICAL_CORPUS_NAME)


def test_a_directory_that_is_not_a_repository_is_unchanged(tmp_path):
    loose = tmp_path / "loose" / "ic"
    loose.mkdir(parents=True)
    assert CL.population_key(loose, CL.NAMED) == "ic"


# ───────────────────────────────────────────── the identity probe itself
def test_the_repo_name_is_read_from_the_remote_not_from_the_directory(
        tmp_path):
    clone = _clone_of(tmp_path, "not-the-repo-name", CANON)
    assert CL.corpus_repo_name(clone) == CL.CANONICAL_CORPUS_NAME


def test_the_repo_name_is_none_when_the_checkout_does_not_say(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    assert CL.corpus_repo_name(loose) is None


def test_the_repo_name_handles_the_scp_style_remote(tmp_path):
    clone = _clone_of(
        tmp_path, "scp-clone",
        f"git@example.invalid:vibeic/{CL.CANONICAL_CORPUS_NAME}.git")
    assert CL.corpus_repo_name(clone) == CL.CANONICAL_CORPUS_NAME
    assert (CL.population_key(clone / "ic", CL.NAMED)
            == f"{CL.CANONICAL_CORPUS_NAME}/ic")


# ─────────── a stale checkout and a withdrawal look identical, and the
# ─────────── advised remedy is destructive for exactly one of them
def test_an_absent_run_tree_names_the_stale_checkout_before_the_re_record(
        tmp_path):
    """`--write-baseline` is right for a withdrawal and DESTRUCTIVE for a
    clone that is merely behind: it ratchets the register down to whatever
    that tree carries, and seals it. The population key names the corpus
    REPOSITORY, not the commit, so both readings arrive at this branch — and
    an operator who is handed only one of them will run the wrong command
    over whichever tree they happened to have.
    """
    clone = _clone_of(tmp_path, "corpus-clone", CANON)
    d = clone / "ic" / "design" / "v1_0_pdkA" / "reports" / "phase3"
    (d / "unack.json").write_text(json.dumps(
        {"verdict": "FAIL", "detail": "synthetic unacknowledged fail"}))
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "one unacknowledged fail")
    base = tmp_path / "baseline.json"
    assert subprocess.run(
        [sys.executable, str(GATE), "--corpus", str(clone / "ic"),
         "--baseline", str(base), "--write-baseline"],
        capture_output=True, text=True).returncode == 0

    # The SAME repository at an earlier state: `design/v1_0_pdkA` had not been
    # published yet, so the run tree the register names is not under it at all.
    behind = _clone_of(tmp_path, "corpus-clone-behind", CANON)
    _git(behind, "rm", "-r", "-q", "ic/design/v1_0_pdkA")
    older = behind / "ic" / "other_design" / "v0_9_pdkA" / "reports" / "phase3"
    older.mkdir(parents=True)
    (older / "gate.json").write_text(json.dumps({"verdict": "PASS"}))
    _git(behind, "add", "-A")
    _git(behind, "commit", "-qm", "an earlier corpus state")
    got = subprocess.run(
        [sys.executable, str(GATE), "--corpus", str(behind / "ic"),
         "--baseline", str(base)], capture_output=True, text=True)
    text = got.stdout + got.stderr
    assert got.returncode == 1, text
    assert "not in the swept corpus at all" in text, text
    assert "FIRST CHECK THE CHECKOUT" in text, (
        "the destructive reading of the advised remedy is unnamed")


def test_a_withdrawal_inside_the_corpus_is_not_told_to_check_the_checkout(
        tmp_path):
    """THE PAIRED GUARD. A run still under the corpus that stopped publishing
    reports IS a withdrawal, `--write-baseline` is the right remedy, and an
    unconditional 'check your checkout' would train a reader to ignore it."""
    clone = _clone_of(tmp_path, "corpus-clone", CANON)
    d = clone / "ic" / "design" / "v1_0_pdkA" / "reports" / "phase3"
    (d / "unack.json").write_text(json.dumps(
        {"verdict": "FAIL", "detail": "synthetic unacknowledged fail"}))
    # A second run that keeps its reports throughout, so the withdrawal below
    # is a WITHDRAWAL and not an empty sweep — a vacuous corpus is a third
    # outcome and would not exercise this branch at all.
    other = clone / "ic" / "design_b" / "v1_0_pdkA" / "reports" / "phase3"
    other.mkdir(parents=True)
    (other / "gate.json").write_text(json.dumps({"verdict": "PASS"}))
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "one unacknowledged fail")
    base = tmp_path / "baseline.json"
    assert subprocess.run(
        [sys.executable, str(GATE), "--corpus", str(clone / "ic"),
         "--baseline", str(base), "--write-baseline"],
        capture_output=True, text=True).returncode == 0

    # The run stays published; only its reports/ tree goes.
    _git(clone, "rm", "-r", "-q", "ic/design/v1_0_pdkA/reports")
    kept = clone / "ic" / "design" / "v1_0_pdkA"
    kept.mkdir(parents=True, exist_ok=True)
    (kept / "keep.txt").write_text("still here")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "reports withdrawn")
    got = subprocess.run(
        [sys.executable, str(GATE), "--corpus", str(clone / "ic"),
         "--baseline", str(base)], capture_output=True, text=True)
    text = got.stdout + got.stderr
    assert got.returncode == 1, text
    assert "FIRST CHECK THE CHECKOUT" not in text, text
