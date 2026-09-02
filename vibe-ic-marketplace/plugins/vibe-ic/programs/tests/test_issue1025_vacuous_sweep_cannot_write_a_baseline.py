"""A sweep that examined nothing may neither PASS nor rewrite the record.

vibe-ic#1025, the two halves that were guarded only by prose.

MEASURED on `947547716` before the fix, with the real baseline copied to a
temp file so the repo's own record was never at risk::

    before: findings_total=7 runs_swept=17 per_run=4
    $ step_internal_fail_bubble_up_check.py \
        --corpus <empty> --baseline <copy> --write-baseline
    rc=0    wrote <copy> (findings_total=0)
    after:  findings_total=0 runs_swept=0  per_run=0

`--write-baseline` sat 14 lines ABOVE the `runs_with_reports == 0` check and
returned 0 before reaching it, so a sweep with zero reach rewrote the ratchet to
zero and called it success. The issue names exactly this danger and refuses to
run the command by hand — but nothing stopped anyone else from running it, and
"MAY ONLY SHRINK" is *satisfied* by that write, which is what makes it silent.

The second half is the verdict tier: a vacuous sweep must not return the same rc
as a sweep that examined everything and found nothing. That is fixed on main and
was likewise unpinned; a test lives here so it cannot regress quietly.

NOTHING HERE TOUCHES THE REPO'S BASELINE. Every case runs against a copy in
`tmp_path`, which is also what makes the destructive case safe to assert.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN_ROOT / "programs"
GATE = PROGRAMS / "step_internal_fail_bubble_up_check.py"
REAL_BASELINE = PROGRAMS / "step_internal_fail_bubble_up_baseline.json"

RC_VACUOUS = 2


def _empty_corpus(tmp_path: Path) -> Path:
    """A corpus with no published run tree — the zero-reach condition."""
    corpus = tmp_path / "empty_corpus"
    (corpus / "ic").mkdir(parents=True)
    return corpus


def _reaching_corpus(tmp_path: Path) -> Path:
    """A corpus the sweep DOES reach: two run trees, one of them with a real
    unacknowledged FAIL.

    Built here rather than read out of `benchmark-data/` (vibe-ic#1357 shape):
    the published result cells now live in `vibeic/benchmark-data`, so a test
    rooted at the in-repo corpus measured "which cells happen to be checked in"
    and not the property. The property is the gate's own — a sweep WITH reach
    still writes — and it is stated entirely by this fixture:

      * `ic/demo_dirty/.../reports/phase3/ir_drop.json` declares `FAIL` with no
        waiver and no bubble-up, so the sweep must find exactly ONE finding.
        Without it `findings_total` and `per_run` would both be empty and the
        arithmetic assertion below would hold vacuously.
      * `ic/demo_clean/...` is a second tree with a `reports/` tree and nothing
        wrong, so `runs_swept` exceeds the number of runs with findings and the
        denominator is genuinely more than one.

    MEASURED on this fixture: runs_swept=2, runs_with_reports=2,
    findings_total=1, per_run={'ic/demo_dirty/v0.0.1_demopdk': 1}.

    `tmp_path` is outside any git work tree, which is the case
    `_published_run_trees` documents as "tracked-ness is not a question that
    applies and the disk is the honest answer" — so the sweep walks the disk
    and this fixture is the whole population.
    """
    corpus = tmp_path / "reaching_corpus"
    clean = corpus / "ic" / "demo_clean" / "v0.0.1_demopdk" / "reports" / "phase2"
    clean.mkdir(parents=True)
    (clean / "lint.json").write_text(json.dumps({"verdict": "PASS"}))
    dirty = corpus / "ic" / "demo_dirty" / "v0.0.1_demopdk" / "reports" / "phase3"
    dirty.mkdir(parents=True)
    (dirty / "ir_drop.json").write_text(json.dumps({"verdict": "FAIL"}))
    return corpus


def _seeded_baseline(tmp_path: Path) -> Path:
    """A baseline with a KNOWN non-zero `findings_total`, written by the gate.

    THIS USED TO COPY THE SHIPPED `step_internal_fail_bubble_up_baseline.json`,
    and the destroy-to-zero it exists to catch became invisible the moment that
    record reached zero. It is at zero now, and honestly so: the file records
    `previous_findings_total: 1` and a `shrink_reason` naming vibe-ic#2000 --
    a publication withdrawal, itemised in `_population_shrink`. So the test was
    measuring HOW MUCH DEBT THE TREE HAPPENS TO CARRY TODAY, and the three
    obvious repairs are all worse than the red:

      * write a non-zero `findings_total` into the shipped baseline -> FORGE
        the ratchet ledger, which is this repo's account of unacknowledged
        FAILs and the single least forgeable file in it;
      * delete the premise assertion -> destroy-to-zero is invisible again,
        which is #1025 put back;
      * relax it to `>= 0` -> the same, one step removed.

    So the subject is synthesised, the way `_reaching_corpus` above already
    synthesises its corpus for exactly this reason (vibe-ic#1357: reading
    `benchmark-data/` measured "which cells happen to be checked in" and not
    the property).

    NOT HAND-TYPED. The seed is written BY THE GATE from `_reaching_corpus`,
    whose one planted unacknowledged FAIL makes `findings_total` 1 by
    construction -- so the shape is the gate's own and cannot drift from what
    it reads back. MEASURED: seed rc 0, findings_total 1,
    corpus_population `reaching_corpus`; the destroy sweep against it then
    refuses for VACUITY (`reached 0 published run tree(s) ... examined
    NOTHING`), not for a population mismatch.
    """
    dst = tmp_path / "baseline.json"
    r = _run("--corpus", str(_reaching_corpus(tmp_path)),
             "--baseline", str(dst), "--write-baseline")
    assert r.returncode == 0, f"could not seed the subject\n{r.stdout}{r.stderr}"
    return dst


def _run(*args: str) -> subprocess.CompletedProcess:
    return _pr.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True)


def test_write_baseline_refuses_a_sweep_that_examined_nothing(tmp_path):
    """The destroy, asserted as refused — and the file proved unchanged.

    Both halves matter: an rc alone could be returned *after* writing.
    """
    bl = _seeded_baseline(tmp_path)
    before = bl.read_bytes()
    assert json.loads(before)["findings_total"] > 0, (
        "fixture premise: the subject baseline must record a non-zero total, "
        "otherwise a destroy-to-zero would be invisible here")

    r = _run("--corpus", str(_empty_corpus(tmp_path)),
             "--baseline", str(bl), "--write-baseline")

    assert r.returncode == RC_VACUOUS, (
        f"expected rc {RC_VACUOUS} (vacuous), got {r.returncode}\n"
        f"{r.stdout}{r.stderr}")
    assert bl.read_bytes() == before, (
        "the baseline was REWRITTEN by a sweep that examined nothing — this "
        "is the #1025 destroy, byte-compared, not inferred from the rc")
    out = r.stdout + r.stderr
    assert "REFUSED" in out, out
    # The refusal must be for VACUITY. rc 2 is also this gate's answer to a
    # population mismatch, and a test that accepted either would pass while
    # the #1025 path went unexercised.
    assert "examined NOTHING" in out, (
        "rc 2 and REFUSED, but not for zero reach — this run did not "
        f"exercise the #1025 path:\n{out}")


def test_the_shipped_ratchet_is_still_a_readable_record(tmp_path):
    """The shipped baseline is no longer this file's SUBJECT, so it is asserted
    to be a readable ratchet here instead of being silently dropped.

    Nothing about its VALUE is asserted -- a ratchet whose number a test
    demands is a ratchet a test can be made to forge. What is asserted is that
    it parses, carries the ratchet keys the gate reads, and that a fall is
    accounted for: `findings_total` below `previous_findings_total` requires a
    written `shrink_reason`, which is the rule vibe-ic#1202 landed and the
    reason today's zero is legible instead of suspicious.
    """
    doc = json.loads(REAL_BASELINE.read_text(encoding="utf-8"))
    for key in ("findings_total", "corpus_population", "runs_swept",
                "runs_with_reports", "per_run"):
        assert key in doc, f"the shipped ratchet has no {key!r}"
    assert isinstance(doc["findings_total"], int) and doc["findings_total"] >= 0
    prev = doc.get("previous_findings_total")
    if isinstance(prev, int) and doc["findings_total"] < prev:
        assert str(doc.get("shrink_reason") or "").strip(), (
            "findings_total fell below previous_findings_total with no "
            "shrink_reason — a ratchet whose number can fall without anyone "
            "saying why is a record of nothing (vibe-ic#1202)")


def test_a_vacuous_sweep_does_not_return_the_pass_code(tmp_path):
    """Part 2: rc must distinguish 'examined nothing' from 'found nothing'."""
    r = _run("--corpus", str(_empty_corpus(tmp_path)))
    assert r.returncode == RC_VACUOUS, (
        f"a sweep with zero reach returned rc={r.returncode}; rc 0 would be "
        f"indistinguishable from a sweep that examined the whole corpus and "
        f"found no findings\n{r.stdout}{r.stderr}")
    assert "VACUOUS_PASS" in (r.stdout + r.stderr)


def test_write_baseline_still_works_when_the_sweep_actually_reaches(tmp_path):
    """The paired half — the refusal must not become a ban.

    A guard that refuses everything passes the test above while removing the
    command. This pins that a sweep WITH reach still writes.
    """
    bl = tmp_path / "written.json"
    r = _run("--corpus", str(_reaching_corpus(tmp_path)), "--baseline", str(bl),
             "--write-baseline")
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    assert bl.is_file(), "reachable sweep did not write a baseline"
    written = json.loads(bl.read_text())
    assert written["runs_with_reports"] > 0, (
        "wrote a baseline whose own record says it examined nothing — the "
        "refusal above is then not measuring the condition it claims to")
    # The fixture plants exactly one unacknowledged FAIL, so this arithmetic is
    # load-bearing rather than 0 == sum(()). A refusal that had quietly become a
    # ban, or a sweep that reached the trees and audited none of them, fails here.
    assert written["findings_total"] == 1, (
        f"the sweep reached the fixture but did not AUDIT it: expected the one "
        f"planted unacknowledged FAIL, got {written['findings_total']}\n"
        f"{r.stdout}{r.stderr}")
    assert written["per_run"] == {"ic/demo_dirty/v0.0.1_demopdk": 1}, written
    assert written["findings_total"] == sum(written["per_run"].values())
