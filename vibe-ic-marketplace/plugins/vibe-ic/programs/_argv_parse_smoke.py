#!/usr/bin/env python3
"""Run a program only as far as its ARGUMENT PARSER, and report what happened.

WHY A SHIM AND NOT A STATIC READ OF THE SIGNATURE
=================================================
`_gate_invocation`'s docstring already measured the static approach in this
tree and rejected it: deriving each gate's CLI signature with `ast` (count the
positionals, collect `required=True`) selected 135 of 241 against a ground
truth of 35 — 100 false positives — because `nargs="?"` positionals accept an
argument perfectly well and many gates build their parser in a shared factory
where no `add_argument` call is visible in the gate's own source at all.

So the parser has to be BUILT, which means the program's own code has to run.
What must NOT happen is that it runs any further: this repo's gates take
minutes, and `_gate_dispatch.sh`'s corpus-write guard exists because gates
write into the tree they audit. The shim therefore stops the process at the
first completed `parse_*` call over the process argv, before the gate's first
statement of real work.

WHAT IT REPORTS, AND WHY TWO CHANNELS
=====================================
An exit code alone is not enough: a program that never reaches a parser is
free to exit with any status it likes, including the one this shim would use,
and the reader could not tell "the parser accepted the argv" from "the gate
ran and happened to exit 97". So acceptance is announced on BOTH channels —
rc `RC_PARSER_ACCEPTED` **and** the `ACCEPTED_SENTINEL` line on stderr — and a
caller must require both. This is the same two-channel rule
`gate_skip_routing_check` reads out of `flow_compliance_check`, applied to a
much smaller claim.

Rejection is NOT reported by this shim. argparse already has a rejection
protocol (rc 2 + a `usage:` block + a `<prog>: error:` line) and this repo
already owns exactly one reader of it, `_gate_invocation.classify_not_invocable`.
Re-deriving it here would be the second predicate that the drift check spent a
version removing — it re-typed Rule A, never had Rule B, and was blind to four
gates for as long as it existed. The shim stays out of the way and lets
argparse's own exit reach the caller unchanged.

THE PARSE MUST BE OF THE PROCESS ARGV
=====================================
Programs parse more than once: a sub-parser is driven with a slice, a helper
builds a throwaway parser and calls `parse_args([])`. Stopping at the FIRST
parse of any kind would report "accepted" for an argv that was never examined —
a vacuous pass in the one program whose whole job is to detect them. So the
stop fires only when the parsed list IS the process argv (`None`, argparse's
own default, or a list equal to `sys.argv[1:]`), and only at the outermost
call: `parse_args` delegates to `parse_known_args` and then performs the
leftover-argument check, so raising inside the inner call would skip exactly
the check that catches an argv with a stale extra flag in it.

chip-AGNOSTIC: it reasons about Python's argument parser and process exit
codes. No design, PDK or vendor literal appears here.

Usage:
    python3 _argv_parse_smoke.py <program.py> [args...]
"""
from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

#: rc when the program's parser accepted the argv. Paired with the sentinel
#: below — see "WHY TWO CHANNELS". Chosen outside the 0/1/2 verdict vocabulary
#: this repo uses so it cannot be mistaken for a gate's own answer.
RC_PARSER_ACCEPTED = 97

#: Written to stderr immediately before exiting with `RC_PARSER_ACCEPTED`.
ACCEPTED_SENTINEL = "__ARGV_PARSE_SMOKE__ parser accepted the argv"

#: Depth of the current `parse_*` nesting. `parse_args` calls
#: `parse_known_args`, and a sub-parser calls it again; only the OUTERMOST
#: completed call has done the whole job.
_depth = 0


def _same_as_process_argv(args) -> bool:
    """Was this parse driven by the argv the caller handed the process?

    `None` is argparse's own default and means `sys.argv[1:]` — unambiguous.
    An explicit list is COMPARED, and the comparison has exactly one degenerate
    case: when the process was given NO arguments at all, a throwaway
    `parse_args([])` is byte-identical to the real one, so this answers YES to
    the first of them.

    Refusing to answer yes there was measured and REJECTED: three shipped
    declarations pass no arguments and reach their parser through
    `main(sys.argv[1:])`, so a rule that skipped an explicit empty list left
    them unmeasured AND ran them to completion — one reads 3690 files — inside
    a check whose whole safety claim is that no gate body runs.

    The degenerate case is closed by the CALLER instead, without giving that
    up: `gate_declared_argv_parses_check.probe` drives an argument-less
    declaration a second time with a token no parser knows, which makes the
    lists differ and forces the real parse. See "THE ARGUMENT-LESS
    DECLARATION" there.
    """
    if args is None:                      # argparse's own default: sys.argv[1:]
        return True
    try:
        return [str(a) for a in args] == list(sys.argv[1:])
    except TypeError:                     # not iterable — not our argv
        return False


def _stop_after(original):
    def wrapper(self, args=None, namespace=None):
        global _depth
        _depth += 1
        try:
            result = original(self, args, namespace)
        finally:
            _depth -= 1
        if _depth == 0 and _same_as_process_argv(args):
            print(ACCEPTED_SENTINEL, file=sys.stderr)
            raise SystemExit(RC_PARSER_ACCEPTED)
        return result
    return wrapper


def install() -> None:
    """Patch argparse so the first full parse of the process argv ends it."""
    argparse.ArgumentParser.parse_args = _stop_after(
        argparse.ArgumentParser.parse_args)
    argparse.ArgumentParser.parse_known_args = _stop_after(
        argparse.ArgumentParser.parse_known_args)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: _argv_parse_smoke.py <program.py> [args...]",
              file=sys.stderr)
        return 2
    program = argv[0]
    # The target is executed the way `python3 <program>` executes it: its OWN
    # directory is `sys.path[0]`, not this shim's. Leaving `programs/` at the
    # front would let a sibling module shadow a stdlib name for a target that
    # lives outside `programs/`, and the failure would be attributed to the
    # target's parser.
    sys.path[0] = str(Path(program).resolve().parent)
    sys.argv = argv
    install()
    runpy.run_path(program, run_name="__main__")
    # Fell off the end without ever parsing the process argv. Say nothing about
    # acceptance — the caller reads the absence of the sentinel.
    return 0


if __name__ == "__main__":
    sys.exit(main())
