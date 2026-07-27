#!/usr/bin/env python3
"""Tell a gate's VERDICT apart from the caller's own invocation defect (#492).

WHY THIS MODULE EXISTS — the P0 structural umbrella in ``flow_compliance_check``
calls every registered structural gate as a subprocess and reads its exit code.
The repo's exit-code convention is:

    rc 0 -> PASS      rc 1 -> FAIL      rc 2 -> NOT CHECKED / VACUOUS

and rc 2 is documented in ``flow_compliance_check`` as "the input-missing skip":
the gate looked for the artefact it audits, did not find it, and said so.

But rc 2 is ALSO what ``argparse`` exits with when it rejects a command line.
So one exit code carried two unrelated meanings:

  (a) "there was no input to check"  — a verdict FROM the callee, benign;
  (b) "you called me wrongly"        — a defect IN the caller, never benign.

The umbrella recorded both as a benign skip. MEASURED at v1.7.68 with the
umbrella's own argv ``[sys.executable, <gate>.py, <project>]``: of the 241
registered structural gates (0 missing files), **39 never got past argument
parsing** — 35 rejected by argparse itself, 4 rejected by a hand-rolled check
for an option the umbrella does not supply. The same 39 came back from an EMPTY
directory and from a real project with RTL and Phase-1 docs, which is the proof
that this is a property of the CALL and not of any project's content.

The consequence is the one this repo keeps closing in other shapes: the umbrella
reported that all registered structural gates ran and found nothing wrong, while
39 of them had never been validly invoked. ``l9_completeness_check`` is the
sharpest example — a registered L9 declarative gate that has never examined an
L9 document in the flow, because the umbrella never passed it ``--l9-file``.

WHAT THIS MODULE DOES — it does NOT guess. It reads the callee's own error
protocol, and it is deliberately two narrow rules rather than one broad one:

RULE A — ``argparse``'s rejection is self-identifying. The stdlib always writes
a ``usage:`` block plus a ``<prog>: error: <what>`` line to stderr and exits 2.
Recognising that pair is reading a documented protocol, not pattern-guessing.

RULE B — a gate that hand-rolls its own required-argument check prints an
``error:`` line NAMING the option it wanted (``error: no masks supplied
(--masks or --mask)``). If that line names a long option the caller did not
supply, the caller did not invoke the gate validly. Scoped by the flags actually
passed, so a gate that names an option the caller DID pass is not misread.

MEASURED PRECISION over all 241 gates x {empty dir, real project}: rules A+B
select 35 + 4 = 39; the other 53 rc-2 results are genuine input-missing skips
and NONE of them names a long option; and neither rule fires on any rc-0 or
rc-1 result. The 4 that only Rule B catches are ``mask_application_check``,
``payload_bit_position_check``, ``periodic_signal_required_check`` and
``fpga_async_input_synchronizer_check`` — each verified by reading its source to
take the value ONLY from a flag, so under the umbrella's argv they are rc 2 no
matter what the project contains.

A NOTE ON WHAT WAS TRIED AND REJECTED — deriving each gate's CLI signature
statically with ``ast`` (count the positionals, collect ``required=True``
options) and predicting acceptance before running. Measured: it selected 135 of
241 against a ground truth of 35, i.e. 100 false positives. Two causes, both
fatal to the approach in this tree: positionals declared ``nargs="?"`` accept
the umbrella's argument perfectly well, and many gates build their parser in a
shared factory (``make_argparser`` in ``_analog_a_check_common``) where no
``add_argument`` call is visible in the gate's own source at all. The observed
error protocol is the reliable signal here; the static signature is not.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

__all__ = [
    "NOT_INVOCABLE_SENTINEL",
    "classify_not_invocable",
    "is_not_invocable_entry",
]

#: Prefix stamped onto the umbrella's report line for a gate that argument
#: parsing rejected. Greppable on purpose: a reader (and a test) can separate
#: "this gate found no input" from "this gate was never validly invoked"
#: without re-deriving the classification.
NOT_INVOCABLE_SENTINEL = "NOT INVOKED"

# argparse's rejection protocol: a `usage:` block AND a `<prog>: error: ...`
# line, both on stderr. Requiring BOTH is what keeps a gate that merely prints
# the word "error" out of this bucket.
_USAGE_BLOCK = re.compile(r"^usage:\s", re.M)
_ARGPARSE_ERROR = re.compile(r"^\S.*?:\s+error:\s", re.M)

# A hand-rolled required-argument complaint. Anchored at line start so a stray
# mid-sentence "error:" in a findings dump does not qualify.
_ERROR_LINE = re.compile(r"^[ \t]*(?:error|ERROR)\b.*$", re.M)

# Long options only. Short flags are too collision-prone to key a verdict on.
_LONG_OPTION = re.compile(r"--[A-Za-z][A-Za-z0-9-]+")


def classify_not_invocable(
    stdout: str,
    stderr: str,
    supplied_flags: Iterable[str] = (),
) -> Optional[str]:
    """Return WHY this rc-2 result is a caller defect, or ``None`` if it is a
    genuine input-missing skip.

    Call this ONLY for a result whose exit code is 2 — the two meanings of rc 2
    are what it separates, and it says nothing about any other exit code.

    ``supplied_flags`` is the set of option strings the caller actually put on
    the command line. Rule B ignores an error line that names one of those:
    if the caller DID pass ``--rtl-dir`` and the gate still complains about
    ``--rtl-dir``, that is the gate's verdict about the value, not a defect in
    the invocation.
    """
    supplied = {f for f in supplied_flags if f.startswith("--")}

    # Rule A — argparse rejected the command line itself.
    if _USAGE_BLOCK.search(stderr) and _ARGPARSE_ERROR.search(stderr):
        for line in stderr.splitlines():
            if ": error: " in line:
                return f"argparse rejected the umbrella's argv: {line.split(': error: ', 1)[1].strip()}"
        return "argparse rejected the umbrella's argv"

    # Rule B — the gate hand-rolled the check and named the option it wanted.
    for blob in (stderr, stdout):
        for line in _ERROR_LINE.findall(blob or ""):
            named = set(_LONG_OPTION.findall(line))
            if named and not (named & supplied):
                return (f"gate requires an option the umbrella does not "
                        f"supply: {line.strip()}")
    return None


def is_not_invocable_entry(entry: str) -> bool:
    """True when a P0 umbrella skip line records a never-validly-invoked gate.

    The umbrella keeps not-invocable gates in the same list as skips so the
    report shape and every existing consumer stay intact; this predicate is how
    a consumer separates the two populations without re-parsing prose.
    """
    return NOT_INVOCABLE_SENTINEL in (entry or "")
