"""The third form: a `<stem>.py` inside a plain string still certified wiring.

vibe-ic#1012 stopped a COMMENT from counting as an invocation. The docstring set
in `_py_evidence` stops a DOCSTRING. A plain string literal was left standing,
so an argparse `help=`, a print message or a JSON description still counted as a
call.

The measured instance, verbatim:

    programs/perc_corpus_sweep.py:337
        help="write {rows, reach} here — the document
              `sweep_reach_check.py --report` consumes"

That one line was `sweep_reach_check`'s ONLY non-comment referrer in the whole
repository, and on the strength of it three separate wiring auditors certified a
REACHABILITY INSTRUMENT as wired. With the rule fixed,
`checker_execution_wiring_audit` names it immediately:

    [FAIL] 1 checker(s) that NOTHING but their own test runs:
       sweep_reach_check.py

THE PREDICATE IS A GRAMMAR TEST, NOT A VOCABULARY. A string is also how an argv
is written, and token shape cannot separate `python3 tools/x.py --root .` from
`run gate_x_check.py to reproduce` — every word in both is path-shaped. What
separates them is FUNCTION WORDS: a command line has none, a sentence about a
command cannot avoid them. The word list is closed and English-only on purpose,
so it carries no chip, protocol or project term.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))


def _prose(v: str) -> bool:
    from checker_execution_wiring_audit import _is_prose_string
    return _is_prose_string(v)


# ── a sentence is not a call ────────────────────────────────────────────────
def test_the_measured_instance_is_prose():
    """The exact string, from the file and line that caused this."""
    assert _prose("write {rows, reach} here — the document "
                  "`sweep_reach_check.py --report` consumes")


def test_a_print_message_is_prose():
    assert _prose("run gate_x_check.py to reproduce")


def test_a_json_description_is_prose():
    assert _prose("the gate_x_check.py program refuses on a finding")


def test_a_why_note_is_prose():
    """The commonest shape in this tree: a string explaining why something is
    NOT wired. Counting that as wiring inverts the sentence's meaning."""
    assert _prose("gate_x_check.py is not wired here and that is deliberate")


# ── a command line still is one ─────────────────────────────────────────────
def test_a_bare_path_is_not_prose():
    """An argv element — the shape a real invocation is written in."""
    assert not _prose("foo_check.py")
    assert not _prose("programs/y_check.py")
    assert not _prose("$PG/gate_x_check.py")


def test_a_full_command_written_as_one_string_is_not_prose():
    assert not _prose("python3 tools/x_check.py --root .")
    assert not _prose("x_check.py --json reports/x.json --strict")


def test_a_shell_run_declaration_is_not_prose():
    """The leading word of a shell declaration is its COMMAND, not English —
    `run "label" "$ROOT" python3 ...`. The first word is therefore excluded
    from the test. Prose does not put its only function word first and nothing
    else after."""
    assert not _prose('run "label" "$ROOT" python3 "$PG/y_check.py" --strict')


def test_a_leading_verb_in_real_prose_still_reads_as_prose():
    """The first-word exclusion must not blind the test to a sentence that
    opens with a verb — the rest of the sentence still carries function
    words."""
    assert _prose("see gate_x_check.py for the reason")


def test_a_two_word_string_is_never_prose():
    """Below three words there is no sentence to find, and refusing there
    keeps the safe direction: an accusation over-credits rather than
    over-accuses."""
    assert not _prose("run x_check.py")


# ── the rule fires where it was measured ────────────────────────────────────
def test_the_sweep_no_longer_certifies_its_consumer():
    """`perc_corpus_sweep`'s help text must stop being an invocation of
    `sweep_reach_check`. Asserted against the REAL file, so the day someone
    rewords that help string this test says whether the credit came back."""
    import ast
    from checker_execution_wiring_audit import _py_evidence
    src = (_PROGRAMS / "perc_corpus_sweep.py").read_text(errors="replace")
    invoked, _ = _py_evidence(ast.parse(src))
    assert "sweep_reach_check" not in invoked, (
        "a sentence in perc_corpus_sweep is being read as a call again")


def test_the_function_word_list_carries_no_domain_term():
    """A grammar test, not a vocabulary. If a chip, protocol or project term
    ever lands in this list it stops being general."""
    from checker_execution_wiring_audit import _PROSE_FUNCTION_WORDS
    domain = {"spi", "i2c", "uart", "rtl", "gds", "drc", "lvs", "sta",
              "vibe", "ic", "opcode", "netlist", "pdk", "fpga"}
    assert not (_PROSE_FUNCTION_WORDS & domain)
    assert all(w.isalpha() for w in _PROSE_FUNCTION_WORDS)
