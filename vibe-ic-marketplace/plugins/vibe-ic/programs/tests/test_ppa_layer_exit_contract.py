#!/usr/bin/env python3
"""The exit-code contract, over the PPA layer AS A LAYER.

`docs/PPA_INTERFACES.md` §1 fixes four codes for every `ppa_*.py`:

    0  PASS / VALID / ELIGIBLE
    1  FAIL / REFUSED — a finding about the DESIGN
    2  UNDETERMINED — I could not look
    3  BAD INVOCATION / INTERNAL ERROR — never a design FAIL

Fourteen programs honour it individually. Nothing checked that they honour it
TOGETHER, and the contract is only worth anything as a layer property: a caller
that dispatches to whichever `ppa_*` program a step names cannot special-case
which ones mean what by 2.

WHAT THIS FILE MEASURES, AND WHAT IT FOUND
==========================================
Measured on `e36d81c0a` (v1.11.33), before any change in this branch:

    BAD INVOKE   `--this-flag-does-not-exist`
                 12 of 14 exited 2. argparse's own convention is 2 and a
                 program that just calls `parse_args()` inherits it.

    --help       the 2 that had already fixed the above did it with a bare
                 `except SystemExit: return RC_BAD_INVOCATION`, so BOTH
                 exited 3 on `--help`. `--help` is not a bad invocation.

Those two are the same defect seen from both sides, which is why they are
tested together here rather than one per program: fixing either one alone
produces the other.

WHY 2-vs-3 IS NOT PEDANTRY
==========================
§1 says rc=2 must never be mapped to PASS, and the usual way a flow gate
honours that is to treat 2 as "not applicable here". A misspelled flag then
reads as a step that had nothing to check, and the run carries on green having
measured nothing. rc=3 cannot be read that way by anybody.

THE VACUOUS ARM
===============
`test_vacuous_input_is_undetermined_not_pass` is the one that matters most and
the one that gets skipped. A checker that returns 0 over an empty population is
the exact defect this repository exists to prevent. Every program is invoked
against input that is absent or empty and must answer 2 with a marker — never
0, and never 1, because "I could not look" is not a finding about silicon.

Each arm is parametrized BY PROGRAM NAME, so a failure names the program.
Counting reds tells you nothing; `-k ppa_search_run` tells you everything.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = pathlib.Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent

# Every shipped `ppa_*.py`. Discovered, not listed: a fifteenth program added
# tomorrow is covered by this file the moment it lands, which is the only way a
# LAYER property stays a layer property.
PPA_PROGRAMS = sorted(p.name for p in _PROGRAMS.glob("ppa_*.py"))


def _run(args, timeout=120):
    return _pr.run([sys.executable, *args], capture_output=True,
                          text=True, cwd=str(_PROGRAMS))


def test_the_program_set_is_not_empty():
    """The denominator. An empty glob would make every parametrized arm below
    vacuously green, which is the defect this whole file is about."""
    assert len(PPA_PROGRAMS) >= 14, (
        f"expected the fourteen shipped ppa_* programs, found "
        f"{len(PPA_PROGRAMS)}: {PPA_PROGRAMS}")


# ---------------------------------------------------------------------------
# THE CROSS-OWNERSHIP PINS, AND WHY THERE ARE NONE LEFT
# ---------------------------------------------------------------------------
# Three programs used to be pinned `xfail(strict=True)` here because their
# one-line fix sat in a file this branch did not own:
#
#   ppa_search_run.py         search lane        exited 2 on an unknown flag
#   ppa_feasibility_check.py  feasibility lane   exited 3 on --help
#   ppa_pareto_check.py       feasibility lane   exited 3 on --help
#
# All three were the same defect: each program did its own argv->rc mapping
# instead of going through `_ppa/cli_exit.parse_or_refuse`, the one seam that
# tells `--help` (SystemExit(0)) from a usage error (SystemExit(2)) by READING
# THE CODE rather than catching the type. The two feasibility programs caught
# SystemExit bare and returned 3 for both; the search program caught neither
# and inherited argparse's 2 for both.
#
# The fix landed: all three now call `parse_or_refuse`. The pins are gone with
# it -- a pin that could stay after the bug is gone is a second bug -- so the
# arms below are unconditional for every program in the set, which is the only
# state in which this file measures a LAYER property.


# ---------------------------------------------------------------------------
# BAD INVOKE  ->  rc=3
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("prog", PPA_PROGRAMS)
def test_unknown_flag_is_bad_invocation_not_undetermined(prog):
    """§1: a bad invocation is 3. argparse's default 2 means UNDETERMINED here,
    and a caller that skips on 2 would swallow the typo silently."""
    r = _run([prog, "--this-flag-does-not-exist"])
    assert r.returncode == 3, (
        f"{prog} exited {r.returncode} on an unknown flag; PPA_INTERFACES §1 "
        f"says a bad invocation is rc=3. rc=2 there is UNDETERMINED and a flow "
        f"gate that treats 2 as 'nothing to check' would pass over the typo.\n"
        f"stderr: {r.stderr[-400:]}")


@pytest.mark.parametrize("prog", PPA_PROGRAMS)
def test_bad_invocation_is_never_a_finding_about_silicon(prog):
    """rc=1 is a claim about a design. Nothing about argv can justify one."""
    r = _run([prog, "--this-flag-does-not-exist"])
    assert r.returncode != 1, (
        f"{prog} exited 1 on a bad invocation. §1: rc=1 is a finding about "
        f"the design; argv is not the design.")


# ---------------------------------------------------------------------------
# --help  ->  rc=0
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("prog", PPA_PROGRAMS)
def test_help_is_not_a_bad_invocation(prog):
    """The mirror of the arm above, and the trap its obvious fix walks into.

    `--help` raises SystemExit(0). A bare `except SystemExit: return 3` turns
    asking a program what its flags are into a bad invocation. Both shipped
    fixes did exactly that.
    """
    r = _run([prog, "--help"])
    assert r.returncode == 0, (
        f"{prog} exited {r.returncode} on --help. argparse exits 0 there; a "
        f"handler that catches SystemExit without reading `.code` converts "
        f"the help path into rc=3.\nstdout: {r.stdout[:200]}")
    assert "usage" in r.stdout.lower(), (
        f"{prog} --help exited 0 but printed no usage line, so the 0 does not "
        f"mean the help path ran.")


# ---------------------------------------------------------------------------
# VACUOUS  ->  rc=2 with a marker
# ---------------------------------------------------------------------------
# One invocation per program that names input which is NOT THERE. The paths are
# under a tmp_path that this file creates empty, so nothing on the machine can
# accidentally satisfy them.


#: PROGRAMS WHOSE DECLARED VACUOUS ANSWER IS NOT 2, WITH THE ARGUMENT FOR IT.
#: A DECLARATION, never an exemption: `returncode != 0` below is unconditional,
#: so nothing here can buy a vacuous pass. Only the choice BETWEEN 2 and 3 is
#: declarable, and `test_the_vacuous_rc_declaration_can_never_buy_a_pass` pins
#: that.
#:
#: THE FAMILY DOES NOT AGREE, AND THAT IS WHY IT IS WRITTEN DOWN. Handed a path
#: argument that does not resolve, two PPA programs answer differently and each
#: has a stated rationale:
#:
#:   ppa_pr_scope_check   `--changed-file not found` -> rc 2. An input that is
#:                        not there is something it could not look at.
#:   ppa_signoff_records  a `run` that is not a directory -> rc 3, and its own
#:                        test argues it: "3 and not 2: a path that is not
#:                        there is the caller's error, and a 2 would be
#:                        indistinguishable from 'I looked and could not
#:                        tell'."
#:
#: Both readings are defensible and PPA_INTERFACES §1 does not adjudicate
#: between them. Silently excluding the disagreement, or "fixing" one program
#: to match a rule its own test argues against, would each bury a real question
#: about the contract. It is recorded here, and in ppa-gate-audit/RESULT.md
#: Part 17, as something the contract's owner settles.
_VACUOUS_RC = {
    "ppa_signoff_records.py": 3,
}


def test_the_vacuous_rc_declaration_can_never_buy_a_pass():
    """The escape hatch's own guard.

    A per-program expected code is one careless edit from becoming a way to
    declare a vacuous PASS, which is the single thing this file exists to
    refuse. 0 is not declarable, and neither is 1.
    """
    assert 0 not in _VACUOUS_RC.values(), (
        "a program declared rc 0 as its vacuous answer; that is the vacuous "
        "pass this whole file exists to prevent and it is not declarable")
    assert 1 not in _VACUOUS_RC.values(), (
        "a program declared rc 1 as its vacuous answer; 1 is a finding about "
        "a design and nothing was measured")
    assert set(_VACUOUS_RC.values()) <= {2, 3}






# ---------------------------------------------------------------------------
# the mutation arm for the shared helper
# ---------------------------------------------------------------------------
def test_cli_exit_helper_tells_help_from_usage_error_by_code():
    """MUTATION ARM for `_ppa/cli_exit.parse_or_refuse`.

    Revert the helper to a bare `except SystemExit: return RC_BAD_INVOCATION`
    and this goes red on the first assertion, which is the exact regression
    the two already-"fixed" programs shipped.
    """
    import argparse
    sys.path.insert(0, str(_PROGRAMS))
    from _ppa import cli_exit

    ap = argparse.ArgumentParser(prog="probe", add_help=True)
    ap.add_argument("--x", required=True)

    # --help is SystemExit(0) and must stay 0.
    args, rc = cli_exit.parse_or_refuse(ap, ["--help"])
    assert args is None and rc == 0, (
        "parse_or_refuse turned --help (SystemExit(0)) into "
        f"rc={rc}; it must read exc.code, not just catch the type")

    # a usage error is SystemExit(2) and must become 3.
    args, rc = cli_exit.parse_or_refuse(ap, ["--nope"])
    assert args is None and rc == 3
    args, rc = cli_exit.parse_or_refuse(ap, [])
    assert args is None and rc == 3

    # a good parse is untouched.
    args, rc = cli_exit.parse_or_refuse(ap, ["--x", "1"])
    assert args is not None and args.x == "1" and rc == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
