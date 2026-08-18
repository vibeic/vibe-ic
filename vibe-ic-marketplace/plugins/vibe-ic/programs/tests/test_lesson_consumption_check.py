#!/usr/bin/env python3
"""Tests for programs/lesson_consumption_check.py (ORGANIC: staged != consumed).

Covers, per the capture skill's Bucket-A requirement (PASS + the real defect it
guards + honest FAIL/SKIP on missing data):
  * the REAL DEFECT this gate exists to catch — a digest section that matches the
    design genre is left unacknowledged;
  * acknowledgement satisfies it, and `applied: false` is a LEGITIMATE answer;
  * selectivity — an unrelated prompt must NOT drag in a strong match;
  * ISF behaviour — a term present in every section carries no signal;
  * honest handling of missing/degenerate data (no sections, unreadable ack).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GATE = PROGRAMS / "lesson_consumption_check.py"

sys.path.insert(0, str(PROGRAMS))
from lesson_consumption_check import (  # noqa: E402
    parse_digest, match_sections, check_acknowledgement,
)

# A miniature digest: one section whose genre is distinctive, plus decoys that
# share only generic vocabulary (so ISF must push them to ~0).
# A realistic-scale digest. Tiny digests are deliberately a low-confidence
# regime for this gate (ISF cannot discriminate), so the strict-mode tests must
# exercise the real regime: >= _MIN_SECTIONS_FOR_STRICT sections, with decoys
# that share ordinary vocabulary rather than owning distinctive words.
DIGEST = """
### Skill: hysteresis level-controller — held flag polarity

For thermometer sensor level controllers whose supplemental valve flow output
depends on the previous level, the boundary anchors outrank the relative
direction sentence. Reset equivalence pins the bottom band.

### Skill: barrel shifter — rotate versus shift

A barrel rotate reuses the wrapped bits; a shift inserts zeros. Honor the
declared output width and the direction the spec names.

### Skill: output register discipline

Register the output on the clock. Reset the output. Assign the output in every
branch so the output never infers a latch.

### Skill: combinational branch coverage

Assign the output in every branch of the case. Register nothing here. The
output must not infer a latch when a branch is missing.

### Skill: reset polarity and synchronicity

Match the stated reset polarity. Register the output on the clock edge the spec
names. Assign the reset value in every branch.

### Skill: counter wraparound versus saturation

A counter wraps to zero unless the spec says it holds. Register the count on
the clock and reset the count in every branch.

### Skill: multiplexer selection style

Select the output from the inputs with a case. Assign the output in every
branch. Register nothing unless the spec names a clock.

### Skill: encoder priority ordering

Scan the inputs in the stated priority order and assign the output. Register
the output only when the spec names a clock edge.

### Skill: shift register load and enable

Load the register when the enable is asserted, otherwise shift. Register the
output on the clock and reset in every branch.

### Skill: comparator output width

Compare the two inputs and assign the output. The output width follows the
declared port, not the operand width.
"""

LEVEL_PROMPT = """
Three sensors are placed vertically in a water reservoir. When the level is
below the lowest sensor the flow rate should be maximum, with both the nominal
valve and the supplemental valve opened. The supplemental flow depends on the
level previous to the last sensor change.
"""

UNRELATED_PROMPT = """
Implement a module named TopModule with an output named out. Assign the output
to the logical AND of the two inputs. Register the output on the clock.
"""


def run(args):
    cp = subprocess.run([sys.executable, str(GATE), *args],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout, cp.stderr


def _files(td: Path, prompt=LEVEL_PROMPT, ack=None):
    (td / "digest.md").write_text(DIGEST)
    (td / "prompt.txt").write_text(prompt)
    args = ["--prompt", str(td / "prompt.txt"), "--digest", str(td / "digest.md")]
    if ack is not None:
        (td / "ack.json").write_text(json.dumps(ack))
        args += ["--ack", str(td / "ack.json")]
    return args


# ---- unit level: the GENERAL CORE is pure strings in, evidence out ----

def test_parse_digest_splits_sections():
    secs = parse_digest(DIGEST)
    assert len(secs) == 10
    assert "hysteresis" in secs[0]["title"]


def test_matches_the_right_section_for_the_genre():
    secs = parse_digest(DIGEST)
    m = match_sections(LEVEL_PROMPT, secs)
    strong = [x for x in m if x["strong"]]
    assert len(strong) == 1
    assert "hysteresis" in strong[0]["section"]
    # evidence is emitted for the dual-track cross-check
    assert strong[0]["distinctive_terms"]


def test_generic_terms_carry_no_signal():
    """'output' appears in nearly every section so ISF drives it to zero, and
    function words like 'with' are removed outright — a prompt made only of
    generic vocabulary must not produce a strong match."""
    secs = parse_digest(DIGEST)
    strong = [x for x in match_sections(UNRELATED_PROMPT, secs) if x["strong"]]
    assert strong == []


# ---- THE REAL DEFECT this gate guards ----

def test_real_defect_unacknowledged_strong_match_is_caught():
    """A genre-matching lesson left in silence — the exact 57%-mismatch failure
    mode that motivated this gate."""
    with tempfile.TemporaryDirectory() as td:
        args = _files(Path(td))
        rc, out, err = run(args + ["--strict"])
        assert rc == 1
        assert "UNACKNOWLEDGED" in out
        assert "hysteresis" in out


def test_acknowledged_applied_true_passes():
    with tempfile.TemporaryDirectory() as td:
        args = _files(Path(td), ack={"lessons_applied": [
            {"section": "hysteresis level-controller", "applied": True,
             "note": "boundary anchors chosen over the literal sentence"}]})
        rc, out, err = run(args + ["--strict"])
        assert rc == 0
        assert "acknowledged" in out


def test_applied_false_is_a_legitimate_acknowledgement():
    """The digest's own rule is 'apply UNLESS the spec states otherwise', so a
    considered rejection must satisfy the gate. Only SILENCE is forbidden."""
    with tempfile.TemporaryDirectory() as td:
        args = _files(Path(td), ack={"lessons_applied": [
            {"section": "hysteresis level-controller", "applied": False,
             "note": "spec states the opposite explicitly"}]})
        rc, out, err = run(args + ["--strict"])
        assert rc == 0


def test_unrelated_prompt_does_not_fire():
    with tempfile.TemporaryDirectory() as td:
        args = _files(Path(td), prompt=UNRELATED_PROMPT)
        rc, out, err = run(args + ["--strict"])
        assert rc == 0
        assert "PASS" in out


# ---- advisory vs strict ----

def test_advisory_mode_reports_but_does_not_block():
    with tempfile.TemporaryDirectory() as td:
        args = _files(Path(td))
        rc, out, err = run(args)          # no --strict
        assert rc == 0
        assert "WARN" in out


# ---- honest handling of missing / degenerate data ----

def test_digest_without_sections_is_a_notice_not_a_failure():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "digest.md").write_text("no skill sections here at all\n")
        (td / "prompt.txt").write_text(LEVEL_PROMPT)
        rc, out, err = run(["--prompt", str(td / "prompt.txt"),
                            "--digest", str(td / "digest.md"), "--strict"])
        assert rc == 0
        assert "NOTICE" in out


def test_missing_input_file_is_io_error_not_a_verdict():
    rc, out, err = run(["--prompt", "/nonexistent/p.txt",
                        "--digest", "/nonexistent/d.md", "--strict"])
    assert rc == 2


def test_unreadable_ack_is_io_error_not_a_silent_pass():
    """A corrupt acknowledgement must never be read as 'nothing to acknowledge'."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "digest.md").write_text(DIGEST)
        (td / "prompt.txt").write_text(LEVEL_PROMPT)
        (td / "ack.json").write_text("{not json")
        rc, out, err = run(["--prompt", str(td / "prompt.txt"),
                            "--digest", str(td / "digest.md"),
                            "--ack", str(td / "ack.json"), "--strict"])
        assert rc == 2


def test_json_evidence_report_written():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        args = _files(td)
        out_json = td / "ev.json"
        rc, out, err = run(args + ["--json", str(out_json)])
        data = json.loads(out_json.read_text())
        assert data["gate"] == "lesson_consumption_check"
        assert data["strong_matches"] == 1
        assert data["evidence"]           # dual-track: raw evidence attached


def test_function_words_are_never_distinctive():
    """A closed-class function word must carry no signal even when it is rare in
    the corpus — ISF alone cannot be trusted to down-weight it on a small digest."""
    from lesson_consumption_check import _terms
    assert "with" not in _terms("a module with an output")
    assert "output" in _terms("a module with an output")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
