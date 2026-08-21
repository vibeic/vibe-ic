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

import json
import pathlib
import subprocess
import sys

import pytest

_TESTS = pathlib.Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent

# Every shipped `ppa_*.py`. Discovered, not listed: a fifteenth program added
# tomorrow is covered by this file the moment it lands, which is the only way a
# LAYER property stays a layer property.
PPA_PROGRAMS = sorted(p.name for p in _PROGRAMS.glob("ppa_*.py"))


def _run(args, timeout=120):
    return subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, timeout=timeout, cwd=str(_PROGRAMS))


def test_the_program_set_is_not_empty():
    """The denominator. An empty glob would make every parametrized arm below
    vacuously green, which is the defect this whole file is about."""
    assert len(PPA_PROGRAMS) >= 14, (
        f"expected the fourteen shipped ppa_* programs, found "
        f"{len(PPA_PROGRAMS)}: {PPA_PROGRAMS}")


# ---------------------------------------------------------------------------
# CROSS-OWNERSHIP PINS
# ---------------------------------------------------------------------------
# `docs/PPA_INTERFACES.md` §6: each lane owns its files exclusively, and a
# change needed in someone else's file is written down rather than made. These
# three defects are real, measured on `e36d81c0a`, and the one-line fix is in a
# file this branch does not own. They are pinned `xfail(strict=True)`, so the
# moment the owning lane lands its fix this file goes RED and the pin has to be
# removed -- a pin that could stay after the bug is gone is a second bug.
#
#   ppa_search_run.py         search lane        exits 2 on an unknown flag
#   ppa_feasibility_check.py  feasibility lane   exits 3 on --help
#   ppa_pareto_check.py       feasibility lane   exits 3 on --help
#
# The fix in all three is `_ppa/cli_exit.parse_or_refuse`, which ships in this
# branch and which the two feasibility programs' own hand-rolled
# `except SystemExit: return RC_BAD_INVOCATION` is the buggy half of.
_XFAIL_UNKNOWN_FLAG = {"ppa_search_run.py"}
_XFAIL_HELP = {"ppa_feasibility_check.py", "ppa_pareto_check.py"}


def _pin(prog, owned_by, what):
    return pytest.mark.xfail(
        strict=True,
        reason=f"cross-ownership: {prog} {what}; the file belongs to the "
               f"{owned_by} lane (PPA_INTERFACES §6) and is handed to the "
               f"lander in RESULT.md rather than edited here. This pin is "
               f"strict: it goes red the moment the fix lands.")


# ---------------------------------------------------------------------------
# BAD INVOKE  ->  rc=3
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("prog", PPA_PROGRAMS)
def test_unknown_flag_is_bad_invocation_not_undetermined(prog, request):
    """§1: a bad invocation is 3. argparse's default 2 means UNDETERMINED here,
    and a caller that skips on 2 would swallow the typo silently."""
    if prog in _XFAIL_UNKNOWN_FLAG:
        request.node.add_marker(_pin(prog, "search",
                                     "exits 2 on an unknown flag"))
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
def test_help_is_not_a_bad_invocation(prog, request):
    """The mirror of the arm above, and the trap its obvious fix walks into.

    `--help` raises SystemExit(0). A bare `except SystemExit: return 3` turns
    asking a program what its flags are into a bad invocation. Both shipped
    fixes did exactly that.
    """
    if prog in _XFAIL_HELP:
        request.node.add_marker(_pin(prog, "feasibility", "exits 3 on --help"))
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
def _vacuous_argv(prog: str, absent: pathlib.Path, emptydir: pathlib.Path):
    a = str(absent)
    d = str(emptydir)
    table = {
        "ppa_area_threshold_check.py": ["--original", a, "--optimized", a,
                                        "--top", "nothing"],
        "ppa_closure_run.py":          [d, "--edge", "32"],
        "ppa_contract_build.py":       ["--declaration", a, "--root", d,
                                        "--out", str(absent.parent / "o.json")],
        "ppa_contract_check.py":       ["--contract", a],
        # The design-for-ECO producer. Its vacuous input is a spare plan that
        # is not there, and the point of the arm for THIS program is sharper
        # than the general one: a producer that read a missing plan as
        # "0 spares" would emit a measured zero, and a measured zero below a
        # declared floor is INFEASIBLE at the gate -- convicting a run nobody
        # looked at. rc=2 is the only honest answer and its records carry no
        # `value` key at all.
        "ppa_eco_spare_records.py":    ["--spare-plan", a, "--stage",
                                        "post_route"],
        "ppa_feasibility_check.py":    ["--candidates", a],
        "ppa_head_to_head_check.py":   [a],
        "ppa_measurement_check.py":    ["--coverage", a, "--expect", a],
        "ppa_metric_extract.py":       ["--records", a],
        "ppa_page_claim_check.py":     [a, "--claims", a],
        "ppa_pareto_check.py":         ["--candidates", a],
        # The search-space lane's producer. `--verify <absent>` names a subject
        # that is not there AND `--programs-dir <empty>` gives it no runner to
        # measure, so BOTH of its inputs are vacuous and neither can be
        # satisfied by anything that happens to be on the machine.
        "ppa_pnr_search_space.py":     ["--verify", a, "--programs-dir", d],
        "ppa_predict_aggregate.py":    ["--cell-count", "0"],
        "ppa_problem_integrity_check.py": ["--baseline", a, "--candidate", a],
        "ppa_report_gen.py":           [a],
        "ppa_search_run.py":           [a],
    }
    return table.get(prog)


@pytest.mark.parametrize("prog", PPA_PROGRAMS)
def test_vacuous_input_is_undetermined_not_pass(prog, tmp_path):
    """Nothing to look at must be rc=2, never rc=0.

    This is the arm the contract's own §7 calls "not paperwork": a gate whose
    declared invocation exits 0 on absent input can never fail, and this
    repository has shipped that twice.
    """
    argv = _vacuous_argv(prog, tmp_path / "absent.json", tmp_path)
    if argv is None:
        pytest.fail(f"{prog} has no vacuous invocation in this file's table. "
                    f"A new ppa_* program must declare how it is invoked with "
                    f"nothing to look at, or its vacuous arm is untested.")
    r = _run([prog, *argv])
    assert r.returncode != 0, (
        f"{prog} exited 0 with nothing to look at (argv: {argv!r}). A checker "
        f"that passes over an empty population is the defect this codebase "
        f"exists to prevent.\nstdout: {r.stdout[:400]}")
    assert r.returncode == 2, (
        f"{prog} exited {r.returncode} with nothing to look at; §1 says an "
        f"absent input is UNDETERMINED (2). 1 would be a finding about a "
        f"design nobody measured.\nstderr: {r.stderr[-400:]}")


@pytest.mark.parametrize("prog", PPA_PROGRAMS)
def test_vacuous_refusal_is_marked(prog, tmp_path):
    """§1: print `[CANNOT CHECK]` or `[REFUSE]` so a 2 can never be read as a
    silent skip. A 2 with no marker is indistinguishable from an argparse
    usage error, which is how the two got confused in the first place."""
    argv = _vacuous_argv(prog, tmp_path / "absent.json", tmp_path)
    if argv is None:
        pytest.skip("no vacuous invocation declared; the arm above fails")
    r = _run([prog, *argv])
    if r.returncode != 2:
        pytest.skip("the rc arm above already reports this program")
    blob = r.stdout + r.stderr
    assert ("[CANNOT CHECK]" in blob) or ("[REFUSE]" in blob), (
        f"{prog} exited 2 with no marker. §1 requires one so that a 2 is "
        f"never read as a silent skip.\nstdout: {r.stdout[:300]}\n"
        f"stderr: {r.stderr[:300]}")


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
