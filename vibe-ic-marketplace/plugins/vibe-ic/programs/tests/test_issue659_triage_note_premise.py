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








# ── what counts as a behaviour-only reason ────────────────────────────────






# ── the gate, in both directions ──────────────────────────────────────────
# Each `main(...)` here runs all 31 checkers as subprocesses (~54s for the file).
# That is well inside the 180s harness, but it is the reason these are one file:
# splitting them would re-probe the same 31 programs per file.






#: The note each family of triage entry opens with, so this file selects on the
#: family it means instead of on the ABSENCE of another one.
#:
#: THE PREDICATE BELOW USED TO BE `"lack of a CALLER" not in v`, and it was
#: correct for exactly as long as the baseline held two families. It held three
#: from 8029bb31a (2026-08-19, #1347), which added
#:
#:     agent_report_presence_check.py   "vibe-ic#1347. Never wired; ..."
#:     eda_log_check.py                 "vibe-ic#1347. Never wired; ..."
#:     sv_compat_check.py               "vibe-ic#1347. Never wired; ..."
#:
#: — checkers nothing has ever executed, which had been counted as wired because
#: a sibling's error message contained the name. Those three are NOT entries
#: "whose input a real run can genuinely lack": their input is beside the point,
#: nothing calls them at all. Selecting them by not-being-the-other-family swept
#: them into a population the docstring below describes, and 7 became 10.
#:
#: So the count is unchanged at 7 and the SELECTOR is corrected. The families are
#: named here rather than inline so a fourth one fails `test_every_triage_entry_
#: belongs_to_a_named_family` instead of silently landing in whichever bucket is
#: expressed as a negation.
_FAMILY_NO_CALLER = "lack of a CALLER"
_FAMILY_INPUT_ABSENT = "rc=2 SKIPs / refuses without its input"
_FAMILY_NEVER_WIRED = "Never wired"


def _family(note: str) -> str:
    if _FAMILY_NO_CALLER in note:
        return _FAMILY_NO_CALLER
    if note.startswith(_FAMILY_INPUT_ABSENT):
        return _FAMILY_INPUT_ABSENT
    if _FAMILY_NEVER_WIRED in note:
        return _FAMILY_NEVER_WIRED
    return ""


def test_every_triage_entry_belongs_to_a_named_family():
    """The premise of the selection below, asserted rather than assumed.

    An unrecognised note shape is how the count above went wrong: it did not
    fail anywhere, it just landed in the bucket that was spelled as a negation.
    A new family now fails HERE, next to the list it has to join.
    """
    d = json.loads(_BASELINE.read_text())
    unknown = sorted(k for k, v in d["triage"].items() if not _family(v))
    assert not unknown, (
        "triage entr(ies) whose note matches no named family; add the family "
        "to _FAMILY_* above and say which population it belongs to:\n"
        + "\n".join(f"    {k}: {d['triage'][k][:80]}" for k in unknown))


#: The population as measured when #659 was answered. It is a CEILING, not a
#: target: the register these are drawn from may only shrink, so the live set is
#: a subset of this and gets smaller every time one of them is wired.
