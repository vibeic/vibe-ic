#!/usr/bin/env python3
"""The rc-3 USAGE tier, for gates whose rc 2 already means VACUOUS.

WHY THIS MODULE EXISTS
======================
This repository's gate exit-code convention is settled and load-bearing::

    0  PASS      the gate examined its subject and found it correct
    1  FAIL      the gate examined its subject and found a violation
    2  VACUOUS   the gate examined NOTHING and says so   (`_vacuous_exit`)

``argparse`` exits **2** when it rejects a command line, so a gate that lets
the stdlib handle a bad invocation reports "I examined nothing" for "you called
me wrongly". ``_gate_invocation`` documents the cost of that collision with a
measurement: of 241 registered structural gates driven by the P0 umbrella, 39
never got past argument parsing and every one of them was recorded as a benign
input-missing skip.

``_gate_invocation`` recovers the distinction AFTER the fact, by reading the
callee's error protocol out of its stderr. That is the right instrument for the
1232 programs already in the tree, and it is not a reason for a program written
today to keep emitting the ambiguous code. A gate that can be unambiguous at
the source should be.

WHY 3 AND NOT ``EX_USAGE`` (64)
===============================
``_analog_producer_common`` faced the identical collision — its rc 2 is the
HONEST GAP tier — and moved usage errors to ``sysexits.h``'s ``EX_USAGE`` (64).
That is a producer contract, and a producer is invoked by a human or by one
wrapper. These are GATES, and a gate's exit code is read by
``flow_compliance_check._check_program_exit_zero``, which maps every code it
does not recognise onto FAIL. 64 and 3 are both FAIL there, so both are safe;
3 is chosen because it is the smallest code the gate tier already reserves
(``#651`` PASS_WITH_WAIVERS), and that reservation is explicitly conditional:

    "a bare rc=3 with no sentinel stays a FAIL (an unrelated program's exit 3
     is never silently waived)"                 — flow_compliance_check:3107

Nothing here emits the ``PASS_WITH_WAIVERS`` sentinel, so a usage error cannot
be mistaken for a waived pass. The two conventions share a number and cannot
collide, because the waiver tier is keyed on the sentinel and not on the code.

WHY ONE SHARED SITE
===================
``gate_discloses_denominator_check`` recorded that fourteen gates each carried
their own inline verdict print, so "there is no shared site to fix" and the
convention had been COPIED fifteen times. A usage-exit convention pasted into
five new programs would be that defect arriving fresh. This is the site.

chip-AGNOSTIC: argument-parser plumbing only. No design, PDK, vendor or SKU.
"""
from __future__ import annotations

import argparse
import sys
from typing import NoReturn, Optional

__all__ = ["RC_USAGE", "USAGE_STDOUT_SENTINEL", "GateArgumentParser",
           "usage_error"]

#: The command line was wrong, so the gate never examined its subject. NOT 2:
#: 2 is the gate's own verdict that there was nothing to examine.
RC_USAGE = 3

#: Line-start token, so a caller reading text rather than an exit code can tell
#: a usage error from a vacuous pass without re-deriving the classification.
#: Same shape as ``_vacuous_exit.VACUOUS_STDOUT_SENTINEL``.
USAGE_STDOUT_SENTINEL = "USAGE_ERROR:"


def usage_error(prog: str, message: str,
                stream=None) -> int:
    """Print the rc-3 disclosure line and return :data:`RC_USAGE`.

    For the hand-rolled checks a parser cannot express — "this option needs a
    positive integer", "this path is not a directory" — so those refusals carry
    the same token and the same code as the ones ``argparse`` raises.
    """
    print(f"{USAGE_STDOUT_SENTINEL} {prog}: {message}",
          file=stream if stream is not None else sys.stderr)
    print(f"{USAGE_STDOUT_SENTINEL} exit {RC_USAGE} — the command line was "
          f"rejected, so NOTHING was examined. This is not a vacuous pass "
          f"(exit 2), which is a verdict about the subject.",
          file=stream if stream is not None else sys.stderr)
    return RC_USAGE


class GateArgumentParser(argparse.ArgumentParser):
    """``argparse`` with the usage-error exit code moved off the vacuous tier.

    Both hooks are overridden deliberately. ``error()`` covers the common paths
    (unknown flag, missing positional, bad ``type=``); ``exit()`` catches every
    other place argparse raises status 2 internally, so the collision cannot
    return through a path this class did not enumerate.

    ``--help`` and ``--version`` still exit 0: those are successful
    invocations, and remapping them would make ``--help`` look like a failure
    to every wrapper that reads the code.
    """

    def error(self, message: str) -> NoReturn:      # noqa: D102
        self.print_usage(sys.stderr)
        usage_error(self.prog, message)
        sys.exit(RC_USAGE)

    def exit(self, status: int = 0,
             message: Optional[str] = None) -> NoReturn:   # noqa: D102
        if message:
            print(message, file=sys.stderr, end="")
        sys.exit(RC_USAGE if status == 2 else status)
