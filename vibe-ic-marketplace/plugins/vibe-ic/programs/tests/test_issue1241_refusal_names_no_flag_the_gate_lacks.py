#!/usr/bin/env python3
"""A refusal must not instruct the reader to pass a flag that gate does not have.

WHY (vibe-ic#1241). `_corpus_location.refuse` is the one seam every corpus gate
refuses through, and it named `--corpus-may-be-absent` unconditionally:

    ... Point VIBE_IC_BENCHMARK_DATA at a clone of the published-corpus
    repository, or pass --corpus-may-be-absent if this repo need not carry one.

That is true for the three callers that offer the flag. #1241 added two that
deliberately do NOT — `ppa_contract_check --corpus` and
`ppa_feasibility_check --corpus`. The rc 0 NO_CORPUS outcome the flag buys is a
gate printing a pass over a population it never opened, which is the one thing
those gates are wired through this channel to avoid, so the flag is absent ON
PURPOSE and passing it exits 2 as an argparse usage error.

An instruction the reader cannot follow is worse than no instruction: it sends
them to debug their own invocation instead of the corpus. Both halves are pinned
below — the callers that offer the flag must still be told about it, and the
callers that do not must not be.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

import _corpus_location as CL  # noqa: E402

FLAG = "--corpus-may-be-absent"

#: Which programs offer the opt-in, checked against the source rather than
#: restated here, so a program that gains or loses it cannot leave this stale.
OFFERS = ("ppa_head_to_head_check.py", "l_doc_field_producer_check.py",
          "evidence_citation_resolves_check.py")
OFFERS_NOT = ("ppa_contract_check.py", "ppa_feasibility_check.py")


def _refusal_text(capsys, **kw) -> str:
    CL.refuse("G", Path("/nope"), Path("/nope"), CL.NAMED, False, "thing(s)",
              **kw)
    return capsys.readouterr().err


def test_the_default_message_is_unchanged(capsys):
    """Every pre-existing caller passes no `opt_in_flag`, so the seam must be
    byte-compatible for them or this repair breaks three other gates."""
    assert FLAG in _refusal_text(capsys)


def test_a_gate_with_no_opt_in_is_not_told_to_use_one(capsys):
    """RED WITHOUT THE FIX: the seam named the flag unconditionally."""
    text = _refusal_text(capsys, opt_in_flag=None)
    assert FLAG not in text
    assert "offers no way to call an absent corpus a pass" in text


def test_the_set_and_wrong_branch_also_stops_naming_it(capsys):
    """The other line that named the flag. A pointer that is SET AND WRONG is
    still UNDETERMINED either way — only the sentence changes."""
    rc = CL.refuse("G", Path("/nope"), Path("/nope"), CL.ENV, False, "thing(s)",
                   opt_in_flag=None)
    text = capsys.readouterr().err
    assert rc == 2
    assert FLAG not in text
    assert "nothing excuses it" in text


def test_dropping_the_flag_never_changes_the_verdict(capsys):
    """The repair is a SENTENCE. If it moved an rc it would be a behaviour
    change wearing a wording change's clothes."""
    for origin in (CL.NAMED, CL.ENV, CL.REFUSED):
        with_flag = CL.refuse("G", Path("/nope"), Path("/nope"), origin, False,
                              "thing(s)")
        capsys.readouterr()
        without = CL.refuse("G", Path("/nope"), Path("/nope"), origin, False,
                            "thing(s)", opt_in_flag=None)
        capsys.readouterr()
        assert with_flag == without == 2, origin


def test_no_program_tells_the_reader_to_pass_a_flag_it_does_not_have():
    """THE ONE THIS FILE IS FOR, asserted against the real programs.

    ONE DIRECTION ONLY, and the other direction is not a defect. A gate that
    OFFERS the flag and does not mention it may simply have it already in
    effect: `l_doc_field_producer_check` and `evidence_citation_resolves_check`
    both take the rc 0 NO_CORPUS branch on an absent corpus, which is a
    different sentence that correctly names no flag. Asserting the converse
    would have failed both of them for behaving correctly — measured, it did,
    which is why the clause is gone rather than the programs being "fixed".

    What is always wrong is advertising an option the program would reject.
    """
    wrong = []
    for prog in OFFERS + OFFERS_NOT:
        path = PROGRAMS / prog
        if not path.is_file():                     # pragma: no cover
            continue
        helptext = subprocess.run(
            [sys.executable, str(path), "--help"], capture_output=True,
            text=True, timeout=120).stdout
        out = subprocess.run(
            [sys.executable, str(path), "--corpus", "/nonexistent-xyz"],
            capture_output=True, text=True, timeout=120)
        if FLAG in (out.stderr + out.stdout) and FLAG not in helptext:
            wrong.append(f"{prog} tells the reader to pass {FLAG} and its "
                         f"--help does not offer it")
    assert wrong == [], "\n  ".join([""] + wrong)


def test_the_gate_that_does_offer_the_flag_still_names_it():
    """The positive control that keeps the test above from passing vacuously.

    `ppa_head_to_head_check` offers the flag and does NOT default it on, so its
    absent-corpus refusal is the rc 2 branch — the one that names the flag. If
    the repair had simply deleted the sentence everywhere, this goes red.
    """
    out = subprocess.run(
        [sys.executable, str(PROGRAMS / "ppa_head_to_head_check.py"),
         "--corpus", "/nonexistent-xyz"], capture_output=True, text=True,
        timeout=120)
    assert out.returncode == 2
    assert FLAG in out.stderr
