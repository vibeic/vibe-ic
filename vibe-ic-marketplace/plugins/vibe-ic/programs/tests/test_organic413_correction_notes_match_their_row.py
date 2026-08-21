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


def test_the_published_corpus_is_clean_today():
    """The measurement #413 closes: 21 tracked ledgers, 50 corrected rows,
    zero notes claiming a repair their row did not receive."""
    rep = C.audit(_PROGRAMS.parents[3])
    assert rep["verdict"] == "PASS", rep["findings"][:10]
    assert rep["noted_rows"] >= 50, rep["noted_rows"]


def test_the_exit_code_is_1_on_a_real_finding(tmp_path, capsys):
    row = dict(_GOOD_BACKFILL, correction=_SHARED)
    assert C.main(["--repo", str(_repo(tmp_path, [row]))]) == 1
    assert "[FAIL]" in capsys.readouterr().out
