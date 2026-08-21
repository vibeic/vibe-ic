#!/usr/bin/env python3
"""A sibling L-doc must be LINE-scoped, because that is what the contract says.

THE DEFECT (vibe-ic#476)
========================
`framed_hits()` and `signoff_qualifier()` both document themselves as
LINE-SCOPED — that scoping is the correction that made "proximity is not
membership" true for them. `_hit_line` implements it by scanning for newlines.

But `sibling_l_doc_texts` serialised with a COMPACT `json.dumps`, which emits no
newline at all. On that path "the line the match sits on" was the WHOLE
DOCUMENT, so one unrelated field saying `informative` anywhere in the blob
disclaimed every requirement in it.

MEASURED on the tracked corpus, before the fix:

    sibling texts, 106 projects, L1..L27      2448
    single-line                               2448   (100%)
    longest "line" `_hit_line` could return   1_420_065 characters

After serialising with `indent=2` the longest line is 3_490 characters.

TWO POPULATIONS, deliberately stated separately, because they answer different
questions:

  * the DEFECT's population is 2448 of 2448 — every sibling text on the path was
    document-scoped;
  * the population where a FINDING visibly changes is 1 of 106 projects, and it
    is a disclosure that was being suppressed: l23 gains
    `REQUIREMENT_OUTSIDE_CONSUMING_LAYER` (ADVISE) where it previously emitted
    no advisory at all. Zero verdicts flip, in any of the three gates.

A one-project finding delta is NOT the vibe-ic#439 "population of one" case: this
is not a new detector, it is a repair of a documented contract that was silently
violated on 100% of the path. The #439 floor is about inventing a check for a
shape that happens once; here the shape is universal and only its observable
consequence is rare.

`indent=2` IS LOAD-BEARING, not cosmetic. The test below pins that, so nobody
"tidies" it back to a compact dump.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import l_doc_consumer_contract as C  # noqa: E402

_REPO = _PROGRAMS.parents[3]
_CODES = [f"L{i}" for i in range(1, 28)]


def _write(project: Path, code: str, doc: dict) -> None:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{code}_X.json").write_text(json.dumps(doc), encoding="utf-8")


# ── the contract ───────────────────────────────────────────────────────────
def test_a_sibling_doc_is_serialised_with_newlines(tmp_path):
    """THE LOAD-BEARING CASE. Without newlines `_hit_line` cannot be
    line-scoped at all — the implementation scans for '\\n'."""
    _write(tmp_path, "L3", {"a": "one", "b": "two", "c": {"d": "three"}})
    texts = C.sibling_l_doc_texts(tmp_path, _CODES)
    assert texts, "fixture produced no sibling text"
    for _p, t in texts:
        assert "\n" in t, "a compact dump makes every hit's line the whole document"


def test_a_disclaimer_on_one_field_does_not_reach_another(tmp_path):
    """PAIRED HALF — the behaviour the scoping exists for. Two fields, one
    disclaimed; the OTHER must not inherit the disclaimer."""
    _write(tmp_path, "L3", {
        "note": "this section is informative only",
        "requirement": "the device shall enforce a secure boot check",
    })
    texts = C.sibling_l_doc_texts(tmp_path, _CODES)
    blob = texts[0][1]
    i = blob.index("secure boot")
    lo = blob.rfind("\n", 0, i) + 1
    hi = blob.find("\n", i)
    line = blob[lo:] if hi == -1 else blob[lo:hi]
    assert "informative" not in line, (
        "the requirement's own line must not carry a neighbour's disclaimer")
    assert "secure boot" in line


def test_the_line_is_bounded_not_the_whole_document(tmp_path):
    """The failure was one of SIZE as much as of scoping: `_hit_line` returned
    up to 1.4 MB. Pin that a line stays a line."""
    big = {f"k{i}": f"value number {i} with some prose attached" for i in range(400)}
    _write(tmp_path, "L3", big)
    _p, t = C.sibling_l_doc_texts(tmp_path, _CODES)[0]
    longest = max(len(l) for l in t.split("\n"))
    assert longest < len(t) / 10, (longest, len(t))


# ── real data ──────────────────────────────────────────────────────────────
def test_every_sibling_text_on_the_tracked_corpus_is_multi_line():
    """The measurement that motivated this, re-run as a guard. Before the fix
    this was 2448 single-line of 2448."""
    if not (_REPO / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "ls-files", "benchmark-data"], cwd=_REPO,
                             capture_output=True, text=True).stdout.split()
    projects = sorted({p.split("/phase1/")[0] for p in tracked
                       if "/phase1/generated_docs/L" in p})
    if not projects:
        pytest.skip("published corpus not checked out")
    single = total = 0
    for rel in projects:
        for _p, t in C.sibling_l_doc_texts(_REPO / rel, _CODES):
            total += 1
            if "\n" not in t:
                single += 1
    assert total > 100, f"only {total} sibling text(s) examined — not a real scan"
    assert single == 0, f"{single} of {total} sibling text(s) are still one line"
