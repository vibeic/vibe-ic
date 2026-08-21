"""#659 — 25 triage notes gave a reason whose premise is false for most of them.

`checker_execution_wiring_baseline.json` lists checkers that nothing but their
own unit test runs. 25 of its 31 entries were justified by a variant of

    rc=2 SKIPs / refuses without its input — [--json JSON]

The issue asks, per entry: is a missing input NORMAL, or is it the condition the
checker exists to detect? It is the right question — `pdk_consistency_check` is
the proof, since the run that lost its staged PDK removed the very input the
checker needed to notice.

MEASURED FIRST, by running each with no arguments and taking argparse's own list
of what it requires — from the PROGRAM, not from the note, since the note is the
thing under audit:

    needs ONLY the run's own context (project_dir, run_dir, target, ...)  24
    needs a SPECIFIC artefact that can be absent                           7

So for 24 the premise is FALSE. `project_dir` is the run's own directory; the
flow always has one. "Refuses without its input" describes running the program
bare from a shell, which is not a state the flow is ever in. Those checkers do
not lack an INPUT — they lack a CALLER, and the note had been standing in for
that, which is what made a known-and-triaged entry look handled.

The issue's question is real and applies to the OTHER seven. One of them,
`pdk_consistency_check`, is the case it was raised about — and the one already
answered, by #655/#656 replacing it with a question the defect cannot disable.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import tempfile

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "triage_note_answers_the_question_check",
    _PROGRAMS / "triage_note_answers_the_question_check.py")
T = importlib.util.module_from_spec(_spec)
sys.modules["triage_note_answers_the_question_check"] = T
try:
    _spec.loader.exec_module(T)
except SystemExit:
    pass

_BASELINE = _PROGRAMS / "checker_execution_wiring_baseline.json"


# ── the criterion, on its own ─────────────────────────────────────────────
def test_a_run_context_argument_is_not_a_missing_input():
    """The heart of it: a checker that needs only the run's own directory
    cannot lack its input in a real run."""
    assert T.input_can_be_absent(["project_dir"]) is False
    assert T.input_can_be_absent(["run_dir"]) is False
    assert T.input_can_be_absent([]) is False


def test_a_specific_artefact_can_genuinely_be_absent():
    assert T.input_can_be_absent(["--netlist", "--pdk-lib"]) is True
    assert T.input_can_be_absent(["--responses-dir"]) is True


def test_a_mix_counts_as_absent_capable():
    """One argument that can go missing is enough — the checker is disabled by
    its absence regardless of what else it takes."""
    assert T.input_can_be_absent(["project_dir", "--pdk-lib"]) is True


def test_undetermined_is_not_false():
    """A checker that could not be probed must not be recorded as 'its input is
    always there' — that is the absence-reads-as-a-pass shape again."""
    assert T.input_can_be_absent(None) is None


# ── what counts as a behaviour-only reason ────────────────────────────────
def test_the_old_notes_are_behaviour_only():
    assert T.asserts_behaviour_only("rc=2 SKIPs / refuses without its input")
    assert T.asserts_behaviour_only("refuses without a netlist")


def test_a_note_that_QUOTES_the_old_wording_to_correct_it_is_not(
):
    """LOAD-BEARING, and a defect the gate had against itself: the corrected
    note necessarily quotes the wording it replaces, and a substring match read
    that as repeating the claim. Quoted text is being DISCUSSED, not asserted —
    the same shape as an assertion that scans its own docstring."""
    corrected = ("unwired for lack of a CALLER, not for lack of an input — "
                 "requires only project_dir, which a real run always has. The "
                 "previous note said it 'skips without its input', which "
                 "describes running it bare from a shell.")
    assert not T.asserts_behaviour_only(corrected)


def test_an_answer_shaped_note_is_not_behaviour_only():
    assert not T.asserts_behaviour_only(
        "absence_is: normal — no analog blocks in most designs")


# ── the gate, in both directions ──────────────────────────────────────────
# Each `main(...)` here runs all 31 checkers as subprocesses (~54s for the file).
# That is well inside the 180s harness, but it is the reason these are one file:
# splitting them would re-probe the same 31 programs per file.
def test_the_corpus_as_committed_passes():
    assert T.main(["--baseline", str(_BASELINE)]) == 0


def test_a_reintroduced_behaviour_only_note_is_blocked(tmp_path):
    """THE DIRECTION THAT MAKES IT WORTH HAVING. The corrected notes could all
    drift back one at a time; this is what stops the first one."""
    d = json.loads(_BASELINE.read_text())
    victim = next(k for k, v in d["triage"].items()
                  if "lack of a CALLER" in v)
    d["triage"][victim] = "rc=2 SKIPs / refuses without its input"
    f = tmp_path / "b.json"
    f.write_text(json.dumps(d))
    assert T.main(["--baseline", str(f)]) == 1


def test_no_baseline_is_not_a_pass(tmp_path):
    assert T.main(["--baseline", str(tmp_path / "nope.json")]) == 2


def test_the_seven_that_the_question_actually_applies_to():
    """Recorded so the population is a fact, not a recollection: these are the
    entries whose input a real run can genuinely lack, and #659's question is
    for them."""
    d = json.loads(_BASELINE.read_text())
    left = sorted(k for k, v in d["triage"].items()
                  if "lack of a CALLER" not in v)
    assert "pdk_consistency_check.py" in left
    assert len(left) == 7, left
