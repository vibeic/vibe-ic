"""vibe-ic#1076 — the PDK gate's wiring is a DECISION, and nothing pinned it.

WHAT #1076 REPORTS, AND WHAT THE TREE ACTUALLY SAYS
====================================================
#1076 reports `input-doc claims vs installed PDK` as "wired with the wrong
argument": it passes no `--container`, so it takes its vacuous early return and
reports NOT_CHECKED over 0 documents, where the pinned EDA image would give it
134 documents and a FAIL with 2 contradictions.

Every one of those numbers is right. The framing is not: this is not a
mis-wiring. `tools/ci/repo_hygiene_gates.sh` carries ~60 lines above the call
site recording that the `--container` wiring was CONSIDERED and REJECTED,
measured 2026-08-11, and it names the reason:

    a container in CI — REJECTED ... it comes back rc 1: 134 documents, 7
    candidate claims, 2 CONTRADICTED / 1 CORROBORATED / 4 UNDECIDED. Those two
    contradictions are TRUE — the documents really do deny a corner library the
    image really does ship — and both live under benchmark-data/**/input/,
    which #904 forbade editing and which this campaign forbids editing. Wiring
    it blocking would turn main red on files nobody is permitted to correct.

and concludes:

    NOT_CHECKED in the roll-up is the correct state and is deliberately left in
    place.

So the artefacts really are covered by nothing automatic — that half of #1076
stands — but the repair is not to flip the argument.

THE REAL DEFECT, AND IT IS THE ONE #1076 ASKS ABOUT LAST
=========================================================
"whether ANY test would have caught the mis-wiring."

MEASURED on origin/main: no. `test_input_doc_pdk_claim_vs_installed_pdk.py`
drives the checker's LOGIC over 41 synthetic fixtures and never reads the call
site. Nothing anywhere asserts how the gate is WIRED. So:

  * adding `--container` — reversing a documented decision and turning main red
    on files nobody may edit — would have been silent, and
  * deleting the wiring entirely would ALSO have been silent.

A decision this deliberate, recorded only in a comment, is one edit away from
being lost. This file makes the wiring a pinned fact, so changing it in either
direction is a loud, reviewable act rather than an accident.

WHAT THIS FILE DELIBERATELY DOES NOT DO
=======================================
It does not assert that NOT_CHECKED is the RIGHT answer forever — that is a
maintainer's call and #1076 is a legitimate place to re-open it. It asserts
only that the current answer is the one the tree documents, so the next change
to it is deliberate.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_REPO = _PROGRAMS.parents[3]
_SCRIPT = _REPO / "tools" / "ci" / "repo_hygiene_gates.sh"
_CHECKER = _PROGRAMS / "input_doc_pdk_claim_vs_installed_pdk_check.py"

_LABEL = "input-doc claims vs installed PDK"


def _wiring_line() -> str:
    """The call site for this gate, read out of the script itself."""
    text = _SCRIPT.read_text(encoding="utf-8")
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if _LABEL in ln and ("run " in ln or "run_tolerating" in ln):
            # the wrapper plus its continuation lines
            out = [ln]
            while out[-1].rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                out.append(lines[i])
            return "\n".join(out)
    pytest.fail(f"no call site for {_LABEL!r} in {_SCRIPT}")


def test_the_gate_is_still_wired_at_all():
    """The whole decision is moot if the gate stopped being invoked."""
    assert _LABEL in _SCRIPT.read_text(encoding="utf-8"), (
        f"{_LABEL!r} is no longer wired in {_SCRIPT.name} — the gate that #1076 "
        f"is about is not being invoked at all")


def test_it_is_wired_tolerating_uncheckable_not_blocking():
    """rc 2 must reach the roll-up as NOT_CHECKED, not as a red run.

    `run` would make every PDK-less host red for a reason about the host;
    treating rc 2 as PASS would be the lie. `run_tolerating_uncheckable` is the
    one wrapper that keeps rc 2 in its own tier.
    """
    line = _wiring_line()
    assert "run_tolerating_uncheckable" in line, (
        f"the PDK gate is no longer wired through run_tolerating_uncheckable, "
        f"so its rc 2 no longer lands in the NOT_CHECKED tier:\n{line}")


def test_the_container_backend_is_still_deliberately_NOT_wired():
    """The pin #1076 asks for.

    Adding `--container` reverses a decision the script records with its
    measurement: it returns rc 1 over two TRUE contradictions in files under
    `benchmark-data/**/input/` that #904 forbids editing. That may be the right
    call one day; it must never be an accident.
    """
    line = _wiring_line()
    assert "--container" not in line, (
        "`--container` has been added to the PDK gate's wiring.\n\n"
        "That is not necessarily wrong, but it is a REVERSAL of a decision the "
        "script documents above this very call site, measured 2026-08-11: with "
        "a container the gate returns rc 1 over 2 TRUE contradictions, both in "
        "files under benchmark-data/**/input/ that #904 forbids editing — so "
        "main goes red on files nobody is permitted to correct.\n\n"
        "If the reversal is intended, update the comment block that records "
        "the rejection and change this test in the same commit, so the new "
        "state is documented rather than merely current.\n"
        f"call site:\n{line}")


def test_the_rejection_rationale_is_still_recorded_next_to_the_wiring():
    """A decision recorded only in a reviewer's memory is not recorded.

    The comment block IS the artefact that makes the wiring legible. If it is
    deleted, the next reader sees a gate that reports NOT_CHECKED for no stated
    reason and 'fixes' it.
    """
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "a container in CI — REJECTED" in text, (
        "the recorded rationale for not wiring --container is gone from "
        "repo_hygiene_gates.sh; the wiring is now unexplained")
    assert "NOT_CHECKED in the roll-up is the correct state" in text, (
        "the script no longer states that NOT_CHECKED is the intended state "
        "for this gate")


def test_the_checker_still_offers_the_container_backend_it_declines_to_use():
    """The rejected path must remain available and covered, not rot.

    The decision is 'we do not wire it in CI', not 'it does not work'. If the
    flag disappeared, the measurements the comment block quotes could never be
    reproduced by hand either.
    """
    src = _CHECKER.read_text(encoding="utf-8")
    assert "--container" in src, (
        f"{_CHECKER.name} no longer accepts --container, so the by-hand "
        f"measurement the wiring decision rests on cannot be reproduced")


def test_rc2_is_what_the_wired_invocation_actually_returns():
    """Prove the documented state by RUNNING it, not by reading about it.

    Skipped rather than asserted-away on a host that happens to carry a
    populated /foss/pdks: there the gate legitimately answers, and pinning rc 2
    would be pinning this host rather than the wiring.
    """
    proc = subprocess.run(
        [sys.executable, str(_CHECKER), str(_REPO)],
        capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    if proc.returncode != 2:
        pytest.skip(
            f"this host answers the PDK gate (rc {proc.returncode}); the "
            f"wired-vacuous state is not reproducible here")
    assert "installed_pdk_root_unreadable" in out, out
    assert "container backend was NOT exercised" in out, (
        f"rc 2 no longer names the backend that never ran — the disclosure "
        f"#981 added is gone:\n{out}")
