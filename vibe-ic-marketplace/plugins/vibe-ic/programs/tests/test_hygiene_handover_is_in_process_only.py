#!/usr/bin/env python3
"""The hygiene handover is in-process only, and RENAMING IT DOES NOT HELP.

WHAT THIS FILE IS FOR, AND WHY THE ONE BESIDE IT WAS NOT ENOUGH
==============================================================
`test_issue538_merge_gate_covers_ci_hygiene.test_the_cli_offers_no_way_to_skip
_the_hygiene_set` asserts that three literal strings — `--hygiene`,
`--skip-hygiene`, `--no-hygiene` — do not appear in `--help`. v1.11.67 grew
`--hygiene-record-in` and that test caught it, which is the whole reason this
branch exists.

But the cheapest way to make that red go away is to spell the flag
`--gate-record-in`, keep `dest="hygiene_record_in"`, and pass `--help`. The
gate would then be exactly as skippable and every assertion in the repo would
be green. So this file binds to the SEAM instead of to the spelling: no
command-line option of `gatekeeper_review.py`, whatever it is called, may
reach the keyword arguments of `review()` that substitute a record for running
the set.

WHY THE SEAM MAY NOT BE ON THE COMMAND LINE — MEASURED, NOT ASSERTED
====================================================================
`hygiene_gate_from_record` checks four things about a supplied record: it
exists, it parses, an exit status came with it, and it names exactly the
labels this tree declares. Every one of those is a check of the record's
SHAPE, and a shape is not a provenance. `test_a_record_naming_every_declared
_label_is_believed` below builds such a record from the tree's own `--list`
output and shows the gate returning rc 0 green over a set that never ran; on
the real tree that is 86 labels and about six kilobytes of JSON, produced in
under a second.

That is not an argument against the function — it is checked as well as a
record can be checked, and an in-process caller has already run the set it
describes. It is an argument about WHO may hand it over. A caller who can
type a path can type that one.
"""
from __future__ import annotations

import argparse
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import gatekeeper_review as R  # noqa: E402

REPO = PROGRAMS.parents[3]


class _Stop(Exception):
    """Raised in place of `parse_args` so `main()` builds the parser and stops."""


def _real_parsers() -> list:
    """EVERY parser `main()` builds, CAPTURED rather than restated.

    A restated copy of the option list would go on passing after the program's
    own copy grew one more, which is the drift this repo removes from gates one
    at a time. Plural because capturing only the first `parse_args` would let a
    pre-parser in front of the real one hide the option: this collects every
    parser reached before the first one stops, and the callers check all of
    them.
    """
    captured = []
    original = argparse.ArgumentParser.parse_args

    def spy(self, args=None, namespace=None):
        captured.append(self)
        raise _Stop

    argparse.ArgumentParser.parse_args = spy
    try:
        R.main([])
    except _Stop:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original
    assert captured, "main() did not build an ArgumentParser"
    # Anything constructed but not yet parsed is reachable too — a parser whose
    # `parse_known_args` runs first would not appear above.
    return captured


def _handover_kwargs() -> set:
    """The `review()` keywords that substitute a record for running the set."""
    names = {p for p in inspect.signature(R.review).parameters
             if p.startswith("hygiene_record")}
    assert names, (
        "review() no longer takes the handover keywords this file polices. If "
        "the seam was removed, delete this file; if it was RENAMED, rename it "
        "here too — do not let the rename be what makes this test vacuous")
    return names


# ═════════════════════════════════════ 1. THE SEAM, NOT THE SPELLING


def test_no_command_line_option_can_supply_a_hygiene_result():
    """THE POINT. Bound to `dest`, so `--gate-record-in` fails just as hard."""
    banned = _handover_kwargs()
    for parser in _real_parsers():
        for action in parser._actions:
            assert action.dest not in banned, (
                f"{action.option_strings or action.dest!r} reaches "
                f"review({action.dest}=...), which hands the hygiene gate a "
                f"substitute for running it. Renaming the flag does not stop "
                f"it being a skip button on the one gate whose entire purpose "
                f"is that it cannot be forgotten")


def test_main_never_hands_the_review_a_record():
    """The other end of the same wire: whatever `argv` says, `main()` must not
    pass the handover on. A parser can stay clean while the call site invents
    a value from somewhere else."""
    banned = _handover_kwargs()
    src = inspect.getsource(R.main)
    # The CALL, not every mention of the word — the comment above the parser
    # names these keywords on purpose, to say they are not on the command line.
    marker = "v = review("
    assert marker in src, (
        "main() no longer calls review() in the shape this test reads; find "
        "the new call site rather than deleting the check")
    call = src[src.index(marker):]
    for name in banned:
        assert f"{name}=" not in call, (
            f"main() passes {name}= to review(); the parser being clean is "
            f"then beside the point")


@pytest.mark.parametrize("flag", ["--hygiene-record-in", "--gate-record-in",
                                  "--hygiene-record-rc", "--gate-record-rc"])
def test_the_flag_is_rejected_by_the_shipped_program(flag):
    """Behavioural, through the real CLI, for the spelling that shipped and for
    the rename that would have made the string check green."""
    # `--base`/`--head` are required, and argparse reports a missing required
    # argument BEFORE it reports an unrecognized one — without them this test
    # would pass on a tree that accepts the flag.
    out = subprocess.run(
        [sys.executable, str(PROGRAMS / "gatekeeper_review.py"),
         "--base", "origin/main", "--head", "HEAD", flag, "/dev/null"],
        capture_output=True, text=True, timeout=60)
    assert out.returncode != 0
    assert "unrecognized arguments" in (out.stderr + out.stdout), (
        f"{flag} was accepted: {out.stderr[:300]}")


# ═════════════════════════════════════ 2. WHY, MEASURED


def test_a_record_naming_every_declared_label_is_believed(tmp_path):
    """The reason the ban is on the CHANNEL and not on the checks.

    Not a regression test — this passes before and after the flag was removed,
    because the function is doing exactly what it says. It is here so that the
    next reader who proposes a CLI seam has to walk past a green test showing
    what a caller gets for the price of one `--list` run.
    """
    labels = R._declared_labels(REPO)
    if not labels:
        pytest.skip("this tree declares no hygiene gate set to forge against")
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps({
        "declared": len(labels),
        "gates": [{"label": l, "state": "PASS", "seconds": 1} for l in labels]}),
        encoding="utf-8")
    g = R.hygiene_gate_from_record(REPO, forged, 0)
    assert g.green and g.rc == 0, g.summary
    assert f"{len(labels)} declared gate(s) matched" in g.summary
    # Said plainly: not one of those gates ran.
    assert "adjudicated from the caller's record" in g.summary
