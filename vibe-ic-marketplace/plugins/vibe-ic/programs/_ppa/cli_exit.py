#!/usr/bin/env python3
"""`_ppa/cli_exit.py` — the one place a `ppa_*` CLI turns argv into an exit code.

WHY THIS FILE EXISTS
====================
`docs/PPA_INTERFACES.md` §1 gives four exit codes and two of them are easy to
confuse in exactly the way that matters:

    2  UNDETERMINED / I COULD NOT LOOK
    3  BAD INVOCATION / INTERNAL ERROR

`argparse` exits **2** on a usage error. That is its own long-standing
convention and it predates this contract, so every CLI that calls
`parser.parse_args()` and does nothing else reports a typo'd flag with the same
code it uses for "the artefact was not there". Measured on `e36d81c0a`
(v1.11.33), across the fourteen shipped `ppa_*` programs:

    12 of 14 exited 2 on `--this-flag-does-not-exist`

The confusion is not cosmetic. §1 also says rc=2 must never be mapped to PASS
by a flow gate — which is right — and the usual way a caller honours that is to
treat 2 as "not applicable here, carry on". A misspelled flag then reads as a
step that had nothing to check, and the run continues green having measured
nothing. A 3 cannot be read that way by anyone.

THE OPPOSITE MISTAKE, WHICH IS THE ONE THE FIX INVITES
======================================================
The obvious repair is

    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return RC_BAD_INVOCATION

and it is wrong, because `--help` also raises `SystemExit` — with code 0.
Measured on the same commit: the two programs that had already applied that
repair (`ppa_feasibility_check.py`, `ppa_pareto_check.py`) both exited **3** on
`--help`. Asking a program what its flags are is not a bad invocation, and a
harness that checks `--help` to decide whether a program is runnable would have
concluded that neither of them is.

So the code is read, not the exception type: argparse exits 0 for `--help` and
`--version`, and 2 for everything it rejects.

USAGE
=====
    args, rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return rc

and, for a usage error discovered after parsing (the `ap.error(...)` case,
which also exits 2):

    return cli_exit.refuse(ap.prog, "give --records PATH or --backend TOOL")
"""
from __future__ import annotations

import argparse
import sys
from typing import Any, Optional, Sequence, Tuple

__all__ = ["RC_OK", "RC_FINDING", "RC_UNDETERMINED", "RC_BAD_INVOCATION",
           "MARK_REFUSE", "MARK_CANNOT_CHECK", "parse_or_refuse", "refuse"]

# docs/PPA_INTERFACES.md §1. Named, so that a caller reading `return 3` in a
# diff can see which of the four it meant.
RC_OK = 0
RC_FINDING = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

MARK_REFUSE = "[REFUSE]"
MARK_CANNOT_CHECK = "[CANNOT CHECK]"


def parse_or_refuse(parser: argparse.ArgumentParser,
                    argv: Optional[Sequence[str]] = None,
                    ) -> Tuple[Optional[argparse.Namespace], int]:
    """`(args, 0)` on success; `(None, rc)` when argparse exited on its own.

    The two exits argparse can take are told apart by their CODE, not by their
    type — `--help` and a usage error are both `SystemExit`:

        SystemExit(0)     --help / --version   -> rc 0, argparse already printed
        SystemExit(2)     usage error          -> rc 3, a BAD INVOCATION

    A `SystemExit` carrying anything else (a string, some other integer) is
    treated as a bad invocation too: it is not a finding about a design, and
    §1 reserves 1 for findings about silicon.
    """
    try:
        return parser.parse_args(argv), RC_OK
    except SystemExit as exc:
        code: Any = exc.code
        if code in (0, None):
            # argparse has already written the help text to stdout and this is
            # a successful invocation of `--help`. Honouring its 0 is the whole
            # reason this helper reads the code instead of the exception type.
            return None, RC_OK
        return None, RC_BAD_INVOCATION


def refuse(prog: str, message: str, *, stream: Any = None) -> int:
    """A usage error found after parsing. rc=3, marked, on stderr.

    `argparse.ArgumentParser.error` exits 2 and cannot be told to do otherwise
    without subclassing it, so a CLI that discovers a bad argument combination
    after `parse_args` returns calls this instead.
    """
    print(f"{MARK_REFUSE} {prog}: {message} rc={RC_BAD_INVOCATION} "
          f"(bad invocation, NOT a finding about any design).",
          file=stream if stream is not None else sys.stderr)
    return RC_BAD_INVOCATION
