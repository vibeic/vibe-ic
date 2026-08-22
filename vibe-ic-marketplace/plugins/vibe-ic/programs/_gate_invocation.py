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
    "NOT_INVOCABLE_HEADING_SENTINEL",
    "classify_not_invocable",
    "rule_b_named_options",
    "format_not_invocable_entry",
    "format_not_invocable_heading",
    "is_not_invocable_entry",
    "is_not_invocable_heading",
    "is_not_invocable_disclosure",
]

#: Prefix stamped onto the umbrella's report line for a gate that argument
#: parsing rejected. Greppable on purpose: a reader (and a test) can separate
#: "this gate found no input" from "this gate was never validly invoked"
#: without re-deriving the classification.
NOT_INVOCABLE_SENTINEL = "NOT INVOKED"

#: Opening token of the heading the umbrella puts above the disclosure block.
NOT_INVOCABLE_HEADING_SENTINEL = "NEVER VALIDLY INVOKED"

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


def _rule_b_hits(stdout: str, stderr: str, supplied: set):
    """Every hand-rolled error line that NAMES a long option the caller did not
    supply, as ``(line, named_options)``.

    Factored out because two callers need the same two regexes applied the same
    way: `classify_not_invocable`, which wants the LINE (it is the evidence in
    the disclosure), and `rule_b_named_options`, which wants the OPTIONS (they
    are what decides whether an umbrella could have driven the gate). Re-typing
    either regex at the second caller is how the writer and the readers drifted
    the first time — see the block comment below.
    """
    for blob in (stderr, stdout):
        for line in _ERROR_LINE.findall(blob or ""):
            named = set(_LONG_OPTION.findall(line))
            # `not (named & supplied)`, NOT `named - supplied`: a line that
            # mentions ANY flag the caller did pass is the gate judging that
            # VALUE, and a line naming both a supplied and an unsupplied flag is
            # ambiguous. The conservative reading is the shipped one and is
            # deliberately preserved here — widening it would manufacture
            # NOT_INVOCABLE verdicts in the umbrella, which is a verdict change.
            if named and not (named & supplied):
                yield line, named


def rule_b_named_options(
    stdout: str,
    stderr: str,
    supplied_flags: Iterable[str] = (),
) -> list:
    """The long options a Rule-B gate asked for and the caller did not supply.

    A gate rejected under RULE A can be interrogated through argparse's own
    ``the following arguments are required:`` line. A gate rejected under RULE B
    never reaches that machinery, so its needs are recoverable ONLY from the
    error line it wrote itself — the same line Rule B keyed on. Callers that
    classify the un-invocable population (which need are mechanical wiring, and
    which are a fact about the design?) must have this, or every Rule-B gate
    reads as "requirements unknown" and lands in whichever pile that maps to.

    Empty when the result is not a Rule-B rejection. Valid for rc-2 results
    only, exactly like `classify_not_invocable`.
    """
    supplied = {f for f in supplied_flags if f.startswith("--")}
    for _line, named in _rule_b_hits(stdout, stderr, supplied):
        return sorted(named)
    return []


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
    for line, _named in _rule_b_hits(stdout, stderr, supplied):
        return (f"gate requires an option the umbrella does not "
                f"supply: {line.strip()}")
    return None


# ── the disclosure block's vocabulary: written and read in ONE place ─────────
#
# WHY THE FORMATTERS LIVE HERE. The #492 disclosure is written by the P0
# umbrella into ``StepResult.reasons`` and read back by four separate consumers
# in ``flow_compliance_check`` that scrape that list line by line. When the
# writer owned the format string and the readers owned their own idea of what a
# disclosure looks like, the two drifted on day one: the readers had never been
# told the shape existed, so every disclosure line was scraped as a FAILING
# GATE NAME. Keeping ``format_*`` and ``is_*`` adjacent — and making the
# umbrella call the formatters rather than inline an f-string — is what makes
# that class of drift impossible: change the wording here and every recogniser
# follows, because they are derived from the same tokens.
#
# The recognisers are ANCHORED rather than substring tests. A gate's own first
# output line can contain any words at all, including these; anchoring on the
# shape the formatter emits (`<gate_name> (NOT INVOKED:` at the start of the
# line, after an optional report bullet) is what stops a GENUINE failure whose
# message happens to mention the phrase from being silently dropped from the
# failing-gate list. Dropping a real failure would be the same false-clean bug
# in the opposite direction.

#: Tail of a per-gate disclosure line. Shared by the formatter and by the
#: end-to-end test that asserts the umbrella still explains itself.
_ENTRY_TAIL = ("this gate returned NO verdict; the umbrella has not checked "
               "what it audits")

_ENTRY_RE = re.compile(
    r"^\s*(?:[-*•]\s+)?[\w.]+\s+\("
    + re.escape(NOT_INVOCABLE_SENTINEL) + r":")

_HEADING_RE = re.compile(
    r"^\s*(?:[-*•]\s+)?" + re.escape(NOT_INVOCABLE_HEADING_SENTINEL)
    + r"\b")


def format_not_invocable_entry(gate_name: str, why: str) -> str:
    """The umbrella's report line for one never-validly-invoked gate.

    ``why`` is the string ``classify_not_invocable`` returned — the callee's
    own error text, which is the evidence for the claim.
    """
    return (f"{gate_name} ({NOT_INVOCABLE_SENTINEL}: {why} — "
            f"{_ENTRY_TAIL})")


def format_not_invocable_heading(n_not_invocable: int,
                                 n_registered: int) -> str:
    """The heading the umbrella puts above the disclosure block."""
    return (f"{NOT_INVOCABLE_HEADING_SENTINEL} ({n_not_invocable} of "
            f"{n_registered} registered gates) — argument parsing rejected "
            f"the umbrella's argv, so these gates returned no verdict and "
            f"what they audit is UNCHECKED:")


def is_not_invocable_entry(entry: str) -> bool:
    """True when a P0 umbrella report line records a never-validly-invoked gate.

    The umbrella keeps not-invocable gates in the same list as skips so the
    report shape and every existing consumer stay intact; this predicate is how
    a consumer separates the two populations without re-parsing prose.

    Tolerates the leading ``  - `` bullet the reasons-list composition adds, so
    the same predicate works on the raw skip payload AND on the composed reason
    line — the two places this has to be recognised.
    """
    return bool(_ENTRY_RE.match(entry or ""))


def is_not_invocable_heading(entry: str) -> bool:
    """True for the heading line that introduces the disclosure block."""
    return bool(_HEADING_RE.match(entry or ""))


def is_not_invocable_disclosure(entry: str) -> bool:
    """True for ANY line of the disclosure block — heading or per-gate entry.

    This is the predicate a reasons-list consumer wants. A disclosure line is
    not a verdict: the gate it names produced none. Treating it as one is what
    turned 37 unrun gates into 37 reported failures.
    """
    return is_not_invocable_entry(entry) or is_not_invocable_heading(entry)
