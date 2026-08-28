"""An rc 2 must name the artefact it is WAITING FOR, not the one it read.

THE DEFECT, measured on this repository's own published corpus. Every one of
the 21 adjudicated candidate sets in `ppa-crosslayer` is UNDETERMINED on the
`em` axis, and the gate's `MISSING` line ended:

    cited artefact: reports/phase3/em.json

That file EXISTS in the campaign's run tree and is healthy -- it states
`"verdict": "MEASURED"` over 2431 analysed segments. A reader sent there by a
line that says a measurement is MISSING finds a perfectly good artefact and
learns nothing about what to produce. The file actually wanted is the
current-density SCREEN, which each record names itself, in its own
provenance, as `screen_artefact: reports/phase3/em_signoff.json` -- 42
occurrences across the corpus, and the gate had it in hand and did not print
it.

Naming the file you read, as the citation for the measurement you did not get,
is worse than naming nothing: nothing is a gap, and this is a misdirection.

WHAT THIS TEST DOES NOT DEMAND. It does not demand that the gate assert the
awaited file is ABSENT. This gate reads a PUBLISHED record and never the run
tree, so it cannot know -- and measured, `em_signoff.json` does exist; it
carries a report-authenticity audit and no current-density screen. What is
absent is the verdict, not necessarily the file, and a gate that claimed
otherwise would be asserting something it never looked at.

Chip-, PDK- and vendor-AGNOSTIC: the fixture names no foundry, node or SKU.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

RC_UNDETERMINED = 2

READ_ARTEFACT = "reports/solve_under_test.json"
AWAITED_ARTEFACT = "reports/screen_under_test.json"
#: Prose that happens to contain a slash. It must NEVER be mistaken for a path.
PROSE_WITH_A_SLASH = ("same solve as the count metric, as the worst J/Jmax "
                      "ratio rather than as a count")


def _run(argv):
    return _pr.run(
        [sys.executable, str(_PROGRAMS / "ppa_feasibility_check.py"),
         *[str(a) for a in argv]],
        capture_output=True, text=True, cwd=str(_PROGRAMS))


def _doc():
    view = {"stage": "post_route"}
    return {
        "schema": "vibeic.ppa.candidates.v1",
        "required_views_by_axis": {"em": [dict(view)]},
        "required_views": [dict(view)],
        "limits": {"reliability.em.worst_ratio": {"max": 1.0}},
        "allow_waivers": False,
        "candidates": [{
            "candidate_id": "cand_under_test",
            "metrics": [{
                "schema": "vibeic.ppa.metric.v1",
                "metric": "reliability.em.worst_ratio",
                "status": "NOT_MEASURED",
                "unit": "ratio",
                "scope": dict(view),
                "reason": "the screen states no worst utilisation",
                "provenance": {
                    "screen_artefact": AWAITED_ARTEFACT,
                    "stage_basis": PROSE_WITH_A_SLASH,
                    "margin": None,
                },
                "source": {"path": READ_ARTEFACT,
                           "sha256": "sha256:" + "0" * 64,
                           "tool": "TOOL_UNDER_TEST"},
            }],
            "waivers": [],
        }],
    }


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "candidates"
    (root / "trial").mkdir(parents=True)
    (root / "trial" / "candidates.json").write_text(
        json.dumps(_doc()), encoding="utf-8")
    return root


@pytest.fixture
def out(corpus):
    proc = _run(["--corpus", corpus])
    assert proc.returncode == RC_UNDETERMINED, proc.stdout + proc.stderr
    return proc.stdout + proc.stderr


def test_the_population_is_not_empty_and_the_verdict_really_is_rc_2(out):
    """The premise. A guard about rc 2 that never reaches rc 2 proves nothing."""
    assert "1 set(s)" in out, out
    assert "1 undetermined" in out, out


def test_the_awaited_artefact_is_named(out):
    assert AWAITED_ARTEFACT in out, (
        "the gate did not name the artefact the record's own provenance says "
        "it is waiting for. An rc 2 that names no missing input is the "
        "failure mode this layer exists to end:\n" + out)


def test_the_artefact_that_was_read_is_still_named_too(out):
    """Both, not one. The reader needs to know what WAS opened as well."""
    assert READ_ARTEFACT in out, out


def test_the_two_are_distinguishable_and_not_run_together(out):
    """Printing both as one undifferentiated list recreates the misdirection."""
    line = [ln for ln in out.splitlines() if AWAITED_ARTEFACT in ln]
    assert line, (
        "no line names the awaited artefact, so there is nothing to check for "
        "distinguishability:\n" + out)
    ln = line[0]
    assert ln.index(READ_ARTEFACT) < ln.index(AWAITED_ARTEFACT), (
        "the awaited artefact must be presented after, and distinctly from, "
        "the one that was read:\n" + ln)
    assert "AWAITED" in ln, (
        "nothing on the line marks which artefact is the one still owed:\n"
        + ln)


def test_the_gate_does_not_claim_the_awaited_file_is_absent(out):
    """It reads a record, never the run tree. Measured: the real corpus's
    `em_signoff.json` DOES exist. A presence claim would be unearned."""
    lines = [ln for ln in out.splitlines() if AWAITED_ARTEFACT in ln]
    assert lines, (
        "the awaited artefact is not named at all, so this assertion had "
        "nothing to inspect. That is a real failure and not a vacuous pass:\n"
        + out)
    line = lines[0]
    for forbidden in ("not present", "does not exist", "is absent",
                      "was never produced"):
        assert forbidden not in line.lower(), (
            "the gate asserted something about the FILESYSTEM that it never "
            "looked at (%r):\n%s" % (forbidden, line))


def test_prose_in_provenance_is_never_mistaken_for_an_artefact(out):
    """The shape rule earns its keep here.

    `stage_basis` holds a sentence containing `J/Jmax`. A rule that treated any
    value with a slash as a path would print a paragraph as a missing file.
    """
    assert PROSE_WITH_A_SLASH not in out, (
        "a prose provenance value was rendered as an awaited artefact:\n" + out)


def test_a_record_whose_provenance_names_nothing_new_gains_no_awaiting_clause(
        tmp_path):
    """The other direction: no invented waiting.

    When provenance names the SAME artefact that was read, there is nothing
    outstanding to point at, and a spurious `AWAITED` clause would send the
    reader to a file the gate already told them it opened.
    """
    doc = _doc()
    doc["candidates"][0]["metrics"][0]["provenance"] = {
        "screen_artefact": READ_ARTEFACT}
    root = tmp_path / "candidates"
    (root / "trial").mkdir(parents=True)
    (root / "trial" / "candidates.json").write_text(
        json.dumps(doc), encoding="utf-8")
    proc = _run(["--corpus", root])
    text = proc.stdout + proc.stderr
    assert proc.returncode == RC_UNDETERMINED, text
    assert "AWAITED" not in text, (
        "an `AWAITED` clause was emitted for the very artefact the gate had "
        "just reported reading:\n" + text)
