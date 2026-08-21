#!/usr/bin/env python3
"""ORGANIC #413 — a correction note claimed a repair the row never received.

`e025ba351` fixed two real defects in published provenance ledgers and then
stamped ONE SHARED note on every row it touched, asserting BOTH repairs. The
files hold two kinds of row and each kind got only one:

  * in-runner rows      — `superseded_fields.version` (the entrypoint banner);
                          never had a `duration_ms`, and some carry a real
                          measured `duration_s`;
  * back-filled rows    — `superseded_fields.duration_ms: 0`; never had a
                          `version` at all.

So half of every note described a repair that row did not get. On in-runner
rows it told a reader the duration was an unmeasured zero that had been
nulled, when that row held the only real measurement in the file. Measured
when found: 50 of 54 noted rows across nine ledgers.

THE PROSE IS DELIBERATELY NOT PARSED except for one fingerprint. A CORRECT
note has to name the other repair in order to say the row did not receive it,
and to withdraw the earlier false claim — so mention-counting false-FAILs the
fixed shape. What is checked instead is the structure the claims rest on.

TRACKED LEDGERS ONLY. Scanning the working tree found 62 violations in
untracked `clean_run_*` directories that no clone can see; tracked-ness, not
local presence, is what makes something a published claim.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from _corpus_repo_view import corpus_repo
from _published_corpus import needs_corpus

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import provenance_correction_note_check as C  # noqa: E402

_SHARED = ("vibe-ic#381/#365: `version` captured the container entrypoint "
           "banner, not the tool version, and `duration_ms` was written as 0 "
           "without ever being measured. Both corrected to null (unknown / "
           "not measured) rather than guessed; originals kept in "
           "`superseded_fields`.")


def _repo(tmp_path: Path, rows) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    p = tmp_path / "benchmark-data" / "ic" / "x" / "provenance.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f",
                    "benchmark-data/ic/x/provenance.jsonl"], check=True)
    return tmp_path


_GOOD_BACKFILL = {
    "tool": "openroad", "reconstructed": True,
    "duration_ms": None, "duration_s": None,
    "duration_unmeasured_reason": "NOT MEASURED — back-filled.",
    "superseded_fields": {"duration_ms": 0},
    "correction": "…`duration_ms` on THIS row was written as 0…",
}
_GOOD_INRUNNER = {
    "tool": "yosys", "version": None, "duration_s": 39.083,
    "superseded_fields": {"version": "[INFO] Final PATH variable: /foss/…"},
    "correction": "…`version` on THIS row captured the banner…",
}


def test_the_fixed_shape_passes(tmp_path):
    rep = C.audit(_repo(tmp_path, [_GOOD_BACKFILL, _GOOD_INRUNNER]))
    assert rep["verdict"] == "PASS", rep["findings"]
    assert rep["noted_rows"] == 2


def test_the_shared_note_is_caught(tmp_path):
    """The concrete regression: the exact text e025ba351 stamped everywhere."""
    row = dict(_GOOD_BACKFILL, correction=_SHARED)
    rep = C.audit(_repo(tmp_path, [row]))
    assert any("SHARED_NOTE" in f for f in rep["findings"]), rep["findings"]


def test_a_correction_with_nothing_replaced_is_caught(tmp_path):
    row = {"tool": "yosys", "correction": "we fixed something"}
    rep = C.audit(_repo(tmp_path, [row]))
    assert any("CORRECTION_WITHOUT_REPAIR" in f for f in rep["findings"])


def test_a_banner_that_was_not_actually_removed_is_caught(tmp_path):
    row = dict(_GOOD_INRUNNER, version="[INFO] Final PATH variable: /foss/…")
    rep = C.audit(_repo(tmp_path, [row]))
    assert any("VERSION_NOT_NULLED" in f for f in rep["findings"])


def test_a_duration_left_in_either_key_is_caught(tmp_path):
    """Both keys, because leaving one populated is how the next reader
    concludes the row WAS measured."""
    for k in ("duration_ms", "duration_s"):
        row = dict(_GOOD_BACKFILL)
        row[k] = 0
        rep = C.audit(_repo(tmp_path / k, [row]))
        assert any("DURATION_NOT_EMPTY" in f and k in f
                   for f in rep["findings"]), (k, rep["findings"])


def test_a_nulled_duration_with_no_reason_is_caught(tmp_path):
    row = dict(_GOOD_BACKFILL)
    del row["duration_unmeasured_reason"]
    rep = C.audit(_repo(tmp_path, [row]))
    assert any("NO_UNMEASURED_REASON" in f for f in rep["findings"])


def test_an_uncorrected_row_is_not_judged(tmp_path):
    """The paired half: rows without a `correction` are untouched by any of
    this, and flagging them would fire on every ledger from day one."""
    rep = C.audit(_repo(tmp_path, [{"tool": "yosys", "duration_ms": 0}]))
    assert rep["verdict"] == "PASS" and rep["noted_rows"] == 0


def test_untracked_ledgers_are_not_judged(tmp_path):
    """Local run directories are not published claims. Including them
    reported 62 violations invisible to any clone."""
    repo = _repo(tmp_path, [_GOOD_BACKFILL])
    u = repo / "benchmark-data" / "ic" / "x" / "clean_run_local"
    u.mkdir(parents=True)
    (u / "provenance.jsonl").write_text(
        json.dumps(dict(_GOOD_BACKFILL, correction=_SHARED)) + "\n")
    rep = C.audit(repo)
    assert rep["verdict"] == "PASS", rep["findings"]
    assert rep["ledgers"] == 1


def test_git_refusing_to_list_is_an_ERROR_not_a_PASS(tmp_path, capsys):
    (tmp_path / "nope").mkdir()
    assert C.main(["--repo", str(tmp_path / "nope")]) == 2
    out = capsys.readouterr().out
    assert "NOT a clean result" in out and "[PASS]" not in out


@needs_corpus
def test_the_published_corpus_is_clean_today(tmp_path):
    """The published corpus: 22 tracked ledgers, 36 corrected rows, zero
    notes claiming a repair their row did not receive.

    THE CLEANLINESS HALF HAS ALWAYS HELD. `verdict == "PASS"` with zero
    findings, here and at every commit checked — the corpus is clean and that
    is what #413 closes.

    THE FLOOR DESCRIBED A DIFFERENT CORPUS. It read `>= 50` against "21
    tracked ledgers, 50 corrected rows", and this repository has never held
    those numbers. Measured on `a38902d16`: 22 tracked ledgers, 36 corrected
    rows, counted twice — once through `C.audit` and once by reading every
    tracked `provenance.jsonl` directly.

    It is not drift. This file has exactly ONE commit in its history,
    `50aedbdd` ("Merge pull request #918 from vibeic/eda-fork-sync-2026-08-10"),
    so it arrived vendored rather than authored here — and running this test AT
    `50aedbdd` fails the same way, on the same 22/36. **It has never passed in
    this repository**, and the tracked `provenance.jsonl` files are byte-identical
    between that commit and `a38902d16`, so nothing was withdrawn: the pin was
    measured against the fork's corpus.

    WHY 36 IS NOT A WEAKENING. The floor exists so the PASS above cannot be
    earned over an empty or collapsed population — it is a non-vacuity guard,
    not a target. A floor of 50 over a population of 36 does not guard that
    property harder; it fails unconditionally, which guards nothing and trains
    a reader to ignore the file. Pinned at the measured 36, a single corrected
    row disappearing from the shipped corpus fires it, which is the property
    the floor was written for.

    The composition, so a future shrink can be attributed rather than guessed:

        8  ic/edge_llm_accel                     2  ic/subservient
        7  ic/spm/v1.5.58_ihp-sg13g2             1  ic/opentitan_aes
        7  ic/sha256/clean_run_v1427_20260715
        6  ic/sha256/clean_run_v1422_20260715
        5  ic/caravel_user_project

    WHERE THE LEDGERS ARE READ FROM (the 2026-08 split). The corrected rows are
    a property of the PUBLISHED cells, and those moved to
    `vibeic/benchmark-data`. `C.audit` enumerates with
    `git ls-files benchmark-data`, so it can only be aimed at a repository that
    TRACKS the cells under that prefix — `corpus_repo` supplies one, either the
    checkout itself when it still carries them or a zero-copy view of the clone
    named by `$VIBE_IC_BENCHMARK_DATA`. Aiming it at this checkout after the
    split enumerated nothing and failed on `noted_rows == 0`, which reads as
    "the corpus lost 36 corrected rows" — a defect claim about data that was
    simply not here to read. The floors below are unchanged, so an empty or
    partial corpus still FAILS rather than passing vacuously; measured against
    the published corpus today: 22 ledgers, 36 noted rows, zero findings.
    """
    rep = C.audit(corpus_repo(tmp_path))
    assert rep["verdict"] == "PASS", rep["findings"][:10]
    assert rep["noted_rows"] >= 36, rep["noted_rows"]
    # The ledger count is pinned too: 36 corrected rows spread over FEWER
    # ledgers would satisfy the row floor while the corpus had quietly lost
    # published runs, and that is the shrink this test is here to notice.
    assert rep["ledgers"] >= 22, rep["ledgers"]


def test_PAIRED_the_row_counter_tracks_the_population_not_a_constant(tmp_path):
    """The floor above is only a guard if `noted_rows` MOVES with the corpus.

    Were it a constant — or were corrected rows counted from something other
    than the ledgers — `>= 36` would hold no matter what the corpus lost, and
    the assertion would be decoration. Two populations, two answers.
    """
    one = C.audit(_repo(tmp_path / "a", [dict(_GOOD_BACKFILL)]))
    assert one["noted_rows"] == 1, one

    none = C.audit(_repo(tmp_path / "b", [{"tool": "yosys", "duration_ms": 0}]))
    assert none["noted_rows"] == 0, none
    assert none["verdict"] == "PASS", none["findings"]


def test_the_exit_code_is_1_on_a_real_finding(tmp_path, capsys):
    row = dict(_GOOD_BACKFILL, correction=_SHARED)
    assert C.main(["--repo", str(_repo(tmp_path, [row]))]) == 1
    assert "[FAIL]" in capsys.readouterr().out
