#!/usr/bin/env python3
r"""testbench_verdict.py — read a simulator run and say what it MEANT.

A testbench prints; it does not return a verdict. Turning "Mismatches: 0 in 100
samples" or a silent log or a timeout into PASS / FAIL / INCONCLUSIVE is a
judgement with a wrong answer available in both directions: reading a
never-ran log as FAIL invents a defect, and reading it as PASS ships one.

RESCUED, and the rescue is the lesson. This shipped inside
`rtllm_tier_pipeline` and was deleted with it, on the strength of a check that
grepped for `^def _emit_|^def solve_` and found nothing — a NARROW pattern whose
zero result was read as "this file holds no capability". The capability was
here the whole time under a name the pattern did not match. Thirty-seven lines,
zero dataset coupling, and no equivalent anywhere else in the tree.

An audit that asks "does this file contain X" must enumerate what it found, not
report the absence of one spelling as an absence of the thing.

WHY THE READERS ARE A TABLE. As rescued, this knew exactly one simulator's
vocabulary — the banner and counted line RTLLM's harness prints. A passing
cocotb run (`** TESTS=3 PASS=3 FAIL=0 **`) and a passing VerilogEval run
(`Mismatches: 0 in 100 samples`) both fell through to "no recognisable verdict",
i.e. to NOT-A-PASS. Fail-safe in direction, but a false negative all the same:
a correct design read as broken. Each simulator states its verdict in its own
form, so the forms belong in a table one entry wide, not in the control flow.

ZERO FAILURES OVER ZERO CASES IS NOT A PASS. `TESTS=0 PASS=0 FAIL=0` and
"0 out of 0 samples" both count no failures because they compared nothing.
A counted reader that knows its denominator must say so there, which is why the
table carries the total alongside the failure count.
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional, Tuple

# --- structured verdict readers -------------------------------------------
# (name, reader) where reader(text) -> None if the form is absent, else
# (failures, compared) with compared=None when the form states no denominator.
# A reader recognises ONE simulator's summary line. Add a simulator by adding
# a reader; nothing below this block needs to know how many there are.

_RE_RTLLM = re.compile(
    r"Test\s+completed\s+with\s+(\d+)\s*(?:/\s*(\d+)\s*)?(?:failure|error)s?", re.I)

_RE_COCOTB = re.compile(
    r"\*{2,}\s*TESTS\s*=\s*(\d+)\s+PASS\s*=\s*(\d+)\s+FAIL\s*=\s*(\d+)", re.I)

_RE_VE_HINT = re.compile(
    r"Total\s+mismatched\s+samples\s+is\s+(\d+)\s+out\s+of\s+(\d+)", re.I)

_RE_VE_COUNT = re.compile(
    r"Mismatch(?:es|ed)?\s*[:=]\s*(\d+)\s+(?:in|of|out\s+of)\s+(\d+)", re.I)

_RE_UVM = re.compile(r"^\s*UVM_(ERROR|FATAL)\s*[:=]\s*(\d+)\s*$", re.I | re.M)

_RE_ERRCOUNT = re.compile(
    r"^[\s#*-]*(?:number\s+of|total|#\s*of)\s+errors?\s*[:=]\s*(\d+)\s*$", re.I | re.M)


def _read_rtllm(t: str):
    m = _RE_RTLLM.search(t)
    if not m:
        return None
    return int(m.group(1)), (int(m.group(2)) if m.group(2) else None)


def _read_cocotb(t: str):
    m = _RE_COCOTB.search(t)
    if not m:
        return None
    tests, _passed, failed = (int(m.group(i)) for i in (1, 2, 3))
    return failed, tests


def _read_ve_hint(t: str):
    m = _RE_VE_HINT.search(t)
    return None if not m else (int(m.group(1)), int(m.group(2)))


def _read_ve_count(t: str):
    m = _RE_VE_COUNT.search(t)
    return None if not m else (int(m.group(1)), int(m.group(2)))


def _read_uvm(t: str):
    """UVM prints ERROR and FATAL on separate summary lines; both are failures,
    and the summary does not state how many checks ran."""
    hits = _RE_UVM.findall(t)
    if not hits:
        return None
    return sum(int(n) for _kind, n in hits), None


def _read_errcount(t: str):
    m = _RE_ERRCOUNT.search(t)
    return None if not m else (int(m.group(1)), None)


READERS: List[Tuple[str, Callable[[str], Optional[Tuple[int, Optional[int]]]]]] = [
    ("rtllm_counted", _read_rtllm),
    ("cocotb_summary", _read_cocotb),
    ("verilogeval_hint", _read_ve_hint),
    ("verilogeval_count", _read_ve_count),
    ("uvm_summary", _read_uvm),
    ("error_count", _read_errcount),
]

# --- prose verdict statements ---------------------------------------------

_BANNER_PASS_RE = re.compile(r"={3,}\s*Your\s+Design\s+Passed\s*={3,}", re.I)

_BANNER_FAIL_RE = re.compile(r"={3,}\s*(?:Error|Failed)\s*={3,}", re.I)

_LINE_FAIL_RE = re.compile(
    r"^[\s=*#-]*(?:test\s+)?(?:failed|failure|error)\b\s*[:@]|"
    r"^[\s=*#-]*failed\s+at\b|"
    r"\bassertion\s+(?:failed|error)\b|"
    r"\bUVM_(?:ERROR|FATAL)\s*@", re.I | re.M)

_LINE_PASS_RE = re.compile(
    r"^[\s=*#-]*(?:all\s+)?(?:tests?|simulation|design)?\s*"
    r"\bpass(?:ed)?\b[\s=*!.-]*$", re.I | re.M)


def read_counts(out: str) -> List[Tuple[str, int, Optional[int]]]:
    """Every structured verdict the transcript states, as
    (reader_name, failures, compared). For callers that must show their work."""
    found = []
    for name, fn in READERS:
        try:
            got = fn(out or "")
        except Exception:
            continue
        if got is not None:
            found.append((name, got[0], got[1]))
    return found


def testbench_verdict(out: str, returncode: Optional[int] = None) -> Tuple[bool, str]:
    """(passed, reason) from a simulation transcript, decided on the TB's own
    verdict statement. FAIL-SAFE: anything unrecognised is NOT a pass.

    Order: a non-zero simulator exit is never a pass -> the STRUCTURED counted
    lines -> an anchored failure statement/banner -> an anchored pass banner or
    whole-line pass token -> no recognisable verdict (not a pass)."""
    out = out or ""
    if returncode is not None and returncode != 0:
        return False, f"simulator exited {returncode} (abnormal termination)"
    if not out.strip():
        return False, "no simulation output (silent transcript)"

    counted = read_counts(out)
    fail_stmt = _BANNER_FAIL_RE.search(out) or _LINE_FAIL_RE.search(out)
    pass_stmt = _BANNER_PASS_RE.search(out) or _LINE_PASS_RE.search(out)

    # (1) structured counts are authoritative when present. ANY reader counting
    # a failure fails the run — two summaries disagreeing is not a tie to break.
    if counted:
        failing = [c for c in counted if c[1] > 0]
        if failing:
            name, n, _ = failing[0]
            return False, f"testbench reported {n} failure(s) ({name})"
        # Zero failures. A reader that knows its denominator must have compared
        # something; zero-of-zero counted nothing and proves nothing.
        with_scope = [c for c in counted if c[2] is not None]
        if with_scope and all(c[2] == 0 for c in with_scope):
            return False, (f"0 failures over 0 cases — nothing was compared "
                           f"({with_scope[0][0]})")
        if fail_stmt:
            return False, "0-failure count contradicted by a failure statement"
        name, _, compared = counted[0]
        scope = f" over {compared} case(s)" if compared else ""
        return True, f"testbench reported 0 failures{scope} ({name})"

    # (2) any anchored failure statement wins over a co-occurring pass token.
    if fail_stmt:
        return False, f"testbench failure statement: {fail_stmt.group(0).strip()[:60]}"

    # (3) an anchored pass statement.
    if pass_stmt:
        return True, f"testbench pass statement: {pass_stmt.group(0).strip()[:60]}"

    # (4) FAIL-SAFE — no verdict the contract recognises.
    return False, "no recognisable testbench verdict in transcript"
