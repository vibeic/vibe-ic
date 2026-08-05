"""#822 — the duplicate-`pattern` check, at the one chokepoint where it can fire.

A detector EXISTING is not a detector being ON THE PATH. The prototype built
during the #796/#799 work was correct and would never have fired: it was
proposed for `backlog_sanitize_check`, and every caller of that gate in this
repo drives it `--file <one yaml>` — community-backlog-submit SKILL.md Step 4,
field-agent-loop SKILL.md, phase1-coverage-loop SKILL.md, with no `--dir`
caller anywhere. A one-element list cannot contain a duplicate group, so it
would have reported "0 duplicates" on every real run while reading as coverage.

`enhancement_emit.main()` holds the whole batch in one process. So EVERY test
below drives the real entry point as a subprocess with a records JSON on disk
and `--records/--out-dir` argv — the way production input arrives. None of them
call the checker function directly; a direct call would prove the function
works and say nothing about whether anything runs it.

WHAT EACH TEST IS WORTH (pre-fix = enhancement_emit at e3aa9b126)
----------------------------------------------------------------
BEHAVIOURAL — the verdict flips through the CLI, no new symbol involved:
    two records sharing a pattern        pre rc 0 + both YAMLs written
                                         -> post rc 1 + nothing written
    whitespace/case variants of one text  same flip
    the pair split across bucket C and T  same flip

NO-LEAK — pass on pre AND post; they exist because a gate that refused every
batch would satisfy the flips above:
    a batch of distinct patterns still emits, at rc 0
    one record alone is never a duplicate
    bucket B is deliberately out of scope

ORDER-INDEPENDENT BY CONSTRUCTION: the blank-pattern case asserts only that
THIS gate stays silent, never on the exit code — `pattern` becomes a hard
refusal at the write site on the unlanded branch
`fix/pattern-is-required-at-emit-not-only-downstream`, which would change that
rc without changing anything this file is about.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "enhancement_emit.py"
assert SCRIPT.exists(), f"missing program: {SCRIPT}"

_WHY = "no deterministic program can judge whether the wording is honest"

#: Two patterns that are genuinely about different defect classes.
_PATTERN_A = ("A required field that is defaulted at its write site but "
              "demanded by a downstream gate: the write succeeds, the record "
              "looks complete, and the refusal lands on whoever reads it next.")
_PATTERN_B = ("A checker that validates something adjacent to the claim rather "
              "than the claim itself: the evidence it reads is real, and it "
              "does not answer the question that was asked.")


def _rec(slug: str, title: str, pattern: str, bucket: str = "C") -> dict:
    rec = {
        "bucket": bucket,
        "step": "phase2.rtl_gen",
        "design": "sha256",
        "why_not_bucket_a": _WHY,
        "title": title,
        "pattern": pattern,
        "suggested_fix": "Make the gate refuse the input it accepts today.",
        "backlog_slug": slug,
        "backlog_type": "bug",
        "severity": "P2",
        "component": "programs",
        "session_context": "a batch carrying more than one record",
    }
    if bucket == "T":
        rec.update({
            "tool": "yosys",
            "problem": "the tool reports success on an input it did not read.",
            "tool_enhancement": "refuse the input instead of reporting success.",
            "golden_sample": "none — not captured in this batch",
        })
    return rec


def _emit(tmp_path: Path, records: list) -> subprocess.CompletedProcess:
    """The production entry point, driven the production way."""
    rec_file = tmp_path / "recoveries.json"
    rec_file.write_text(json.dumps(records))
    out_dir = tmp_path / "candidates"
    return subprocess.run(
        [sys.executable, str(SCRIPT),
         "--records", str(rec_file), "--out-dir", str(out_dir)],
        capture_output=True, text=True, timeout=60)


# ── BEHAVIOURAL: the flips ──────────────────────────────────────────────────

def test_two_records_sharing_a_pattern_are_refused_through_main(tmp_path):
    """pre rc 0 -> post rc 1. #796's shape: byte-identical text on two records
    of one batch."""
    proc = _emit(tmp_path, [
        _rec("gate-accepts-what-it-should-refuse", "A gate accepts what it "
             "should refuse", _PATTERN_A),
        _rec("verdict-survives-its-evidence", "A verdict outlives the evidence "
             "it rests on", _PATTERN_A),
    ])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "DUPLICATE-PATTERN GATE FAILED" in proc.stderr, proc.stderr
    # Both offenders are NAMED — a count alone does not tell an author which
    # two records to look at.
    assert "record[0]" in proc.stderr and "record[1]" in proc.stderr, proc.stderr


def test_a_refused_batch_writes_nothing_at_all(tmp_path):
    """pre: two YAMLs and a summary.json on disk -> post: no output dir.

    The check sits with the pre-flight gates, before `out.mkdir`. Raising it
    mid-emit would abort after some artifacts were written and leave a
    half-populated directory, which is the failure mode the Bucket-A routing
    loop already carries a comment about.
    """
    proc = _emit(tmp_path, [
        _rec("gate-accepts-what-it-should-refuse", "A gate accepts what it "
             "should refuse", _PATTERN_A),
        _rec("verdict-survives-its-evidence", "A verdict outlives the evidence "
             "it rests on", _PATTERN_A),
    ])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert not (tmp_path / "candidates").exists(), sorted(
        p.name for p in (tmp_path / "candidates").iterdir())


def test_a_whitespace_or_case_variant_is_the_same_pattern(tmp_path):
    """pre rc 0 -> post rc 1. A copy that gained a newline and a capital is
    the same defect; matching on bytes alone would let it through."""
    variant = "  " + _PATTERN_A.replace(" ", "\n  ").upper() + "\n"
    proc = _emit(tmp_path, [
        _rec("gate-accepts-what-it-should-refuse", "A gate accepts what it "
             "should refuse", _PATTERN_A),
        _rec("verdict-survives-its-evidence", "A verdict outlives the evidence "
             "it rests on", variant),
    ])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "DUPLICATE-PATTERN GATE FAILED" in proc.stderr, proc.stderr


def test_the_pair_is_caught_across_the_two_backlog_emitting_buckets(tmp_path):
    """pre rc 0 -> post rc 1. Bucket C and bucket T both go through
    `emit_backlog` and both write a `pattern:` block, so the population is
    "records that emit a backlog", not "bucket C"."""
    proc = _emit(tmp_path, [
        _rec("gate-accepts-what-it-should-refuse", "A gate accepts what it "
             "should refuse", _PATTERN_A),
        _rec("tool-reports-success-it-did-not-earn", "A tool reports success "
             "it did not earn", _PATTERN_A, bucket="T"),
    ])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "DUPLICATE-PATTERN GATE FAILED" in proc.stderr, proc.stderr


def test_three_records_on_one_pattern_name_all_three(tmp_path):
    """A group is reported once, with every member named — not as two pairs
    and not as a bare count."""
    proc = _emit(tmp_path, [
        _rec("gate-accepts-what-it-should-refuse", "A gate accepts what it "
             "should refuse", _PATTERN_A),
        _rec("verdict-survives-its-evidence", "A verdict outlives the evidence "
             "it rests on", _PATTERN_A),
        _rec("count-reads-as-coverage", "A count reads as coverage", _PATTERN_A),
    ])
    assert proc.returncode == 1, proc.stdout + proc.stderr
    dup_lines = [ln for ln in proc.stderr.splitlines()
                 if "share ONE `pattern`" in ln]
    assert len(dup_lines) == 1, proc.stderr
    for i in range(3):
        assert f"record[{i}]" in dup_lines[0], dup_lines[0]


# ── NO-LEAK: satisfied by pre AND post ──────────────────────────────────────

def test_a_batch_of_distinct_patterns_still_emits(tmp_path):
    """The accept case, end to end. A gate that refuses every batch satisfies
    every flip above and destroys the tool."""
    proc = _emit(tmp_path, [
        _rec("gate-accepts-what-it-should-refuse", "A gate accepts what it "
             "should refuse", _PATTERN_A),
        _rec("verdict-survives-its-evidence", "A verdict outlives the evidence "
             "it rests on", _PATTERN_B),
    ])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads((tmp_path / "candidates" / "summary.json").read_text())
    assert len(summary["bucket_C_files"]) == 2, summary
    written = sorted(p.name for p in
                     (tmp_path / "candidates" / "bucket_C_backlogs").iterdir())
    assert len(written) == 2, written


def test_one_record_alone_is_never_a_duplicate(tmp_path):
    """The arithmetic the `--file` call site could never escape, from the other
    side: a batch of one emits."""
    proc = _emit(tmp_path, [
        _rec("gate-accepts-what-it-should-refuse", "A gate accepts what it "
             "should refuse", _PATTERN_A)])
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_bucket_b_records_sharing_a_pattern_are_deliberately_not_flagged(tmp_path):
    """The stated scope, pinned so widening it is a visible act.

    Two Bucket-B records at different steps route to DIFFERENT skill files on
    purpose, and one general pattern captured at two steps is a defensible
    authoring choice rather than a copy. Flagging it would be a guess dressed
    as a finding.
    """
    b = {"bucket": "B", "step": "phase2.rtl_gen", "design": "sha256",
         "why_not_bucket_a": _WHY, "skill_title": "A gate accepts what it "
         "should refuse", "pattern": _PATTERN_A,
         "when": "reviewing a gate that has never gone red",
         "what": "prove it can refuse before trusting that it accepts",
         "example": "a gate whose input is always one element",
         "generality": "applies to any gate with a single call shape"}
    b2 = dict(b, step="phase3.pnr_setup_repair")
    proc = _emit(tmp_path, [b, b2])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DUPLICATE-PATTERN" not in proc.stderr, proc.stderr


def test_blank_patterns_are_not_grouped_with_each_other(tmp_path):
    """A missing `pattern` is a DIFFERENT defect, owned by the write site.

    Grouping the blanks would report them as duplicates of each other, name
    the wrong bug and bury the real one. Asserted on THIS gate's message only,
    never on the exit code: the branch
    `fix/pattern-is-required-at-emit-not-only-downstream` turns a blank
    `pattern` into a hard refusal at `emit_backlog`, which changes the rc here
    and nothing this file is about.
    """
    proc = _emit(tmp_path, [
        _rec("gate-accepts-what-it-should-refuse", "A gate accepts what it "
             "should refuse", ""),
        _rec("verdict-survives-its-evidence", "A verdict outlives the evidence "
             "it rests on", "   "),
    ])
    assert "DUPLICATE-PATTERN" not in proc.stderr, proc.stderr


def test_bucket_d_discards_are_not_in_the_population(tmp_path):
    """Bucket D writes no backlog and no `pattern` block, so it carries no
    claim two records could duplicate."""
    d = {"bucket": "D", "step": "phase2.rtl_gen", "design": "sha256",
         "pattern": _PATTERN_A, "why_discard": "already covered upstream"}
    proc = _emit(tmp_path, [d, dict(d)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DUPLICATE-PATTERN" not in proc.stderr, proc.stderr
