#!/usr/bin/env python3
"""control_substance_check.py — how many of a change's pre-fix control tests
actually OBSERVED A VALUE, and how many only noticed that something was absent.

The standard control in this repo is: copy the change's new test file onto
clean `main`, run it, show it FAILS. This program reads the evidence that
control produced and splits it three ways:

    (a) did not COLLECT   — pytest never imported the module. No test body ran,
                            no assertion executed. Zero information.
    (b) presence-only     — a test ran and failed, but the assertion pins no
                            VALUE. It can only tell present from absent.
    (c) observed value    — a test ran, executed an assertion over a concrete
                            observed value, and that value was wrong.

Only (c) is a substantive control. **The count of (c) is the number this
program exists to report.**

WHY (measured 2026-08-05 on two live PRs)
-----------------------------------------
PR #856's control was reported as "the tests fail pre-fix". Re-run here on
`main` (b85d68ac) it produced::

    E   ModuleNotFoundError: No module named 'per_source_record_merge_check'
    ERROR programs/tests/test_empty_record_cannot_erase.py
    !!!! Interrupted: 1 error during collection !!!!
    1 error in 0.38s

551 lines of new test. Zero tests collected, zero assertions executed. The
control "failed" exactly as the rule demands, and it failed *because the
module the fix introduces does not exist yet* — which is true of every new
file ever written. Rendered in a PR body as "the tests fail pre-fix" it is
indistinguishable from a control that ran and caught the defect.

PR #862 is the subtler half. Its author reported "4 of 4 behavioural, 0
missing-symbol" — true, by exception TYPE. Re-run here with the new module in
place and only the MODIFIED program reverted (`4 failed, 28 passed`), the four
messages were::

    assert None                        +  where None = _sha({...})
    assert '0.119.62' == '1.9.79'
    assert (None is not None)           +  where None = _sha({...})
    assert (None is not None)           +  where None = _sha({...})

Three of the four fail on the presence of a field the fix introduces. Wrapping
the access in `.get()` is what turned `KeyError` into `AssertionError`; it
renamed the exception and proved nothing more. **Substance is not the exception
class.** Exactly ONE of those four — the version that read `0.119.62` where the
plugin was at `1.9.79` — observed a wrong value. `1 of 4`, not `4 of 4`, is
what a reviewer needed to be told.

WHAT MAKES THIS DECIDABLE
-------------------------
pytest already distinguishes these, in its own machine-readable report, and
nothing downstream reads it:

  * a collection error is a `<testcase><error message="collection failure">`,
    NOT a `<failure>`. Note the trap this closes: on a collection error the
    JUnit `<testsuite>` still says `tests="1"`, because the collection error is
    reported as one synthetic testcase. Counting `tests` credits a run that
    executed nothing.
  * a rewritten assertion prints the COMPARED VALUES. `assert None is not None`
    and `assert '0.119.62' == '1.9.79'` are different sentences, and the
    difference is precisely (b) vs (c).

So (a) is decided exactly, and (b)/(c) are decided from the text pytest itself
wrote about the failure.

WHERE IT CANNOT DECIDE, AND WHY — read this before trusting a count
-------------------------------------------------------------------
Undecidable cases go to `undecided` and are NEVER counted as substantive. The
one that matters most:

    assert None == 'abc123'

Measured, both of these produce that exact line:

    d = {}                  -> assert None == 'abc123'   # field absent  = (b)
    def parse(s): return None
    assert parse(x) == 7    -> assert None == 7          # genuinely None = (c)

The `+ where` line names the source expression, and in the two samples above it
differs (`{}.get` vs a function) — but that is not a rule: PR #862's own helper
`_sha(d)` is a plain function whose body is `d.get("design_sha256")`, so the
where-line reads like a computation and is an absence. **From the failure text
alone, "the field is missing" and "the function genuinely returned None" are
the same input, and this program does not guess between them.** What would
decide it: the assertion's own source AST plus the pre-fix definition of the
callable named in the where-line — neither is in the pytest report, so neither
is in this program.

The known FALSE NEGATIVE runs the other way. `KeyError` is read as "the key
the fix introduces is absent", which is what it means when the TEST does the
lookup. When the KeyError comes out of the program under test — pre-fix code
that crashes on a key the fix teaches it to handle — that is a real behavioural
control and this program under-credits it as presence-only. It errs toward
under-crediting on purpose: a control wrongly called substantive is the failure
being retired here, and one wrongly called presence-only costs the author a
sentence of rebuttal. The same caution applies to `AttributeError` and
`TypeError` raised from inside the program rather than from the test's own
access.

Also undecided, each with a named reason: bare truthiness on a non-`None` value
(`assert False + where False = r.ok` — the attribute exists and is False, which
is an observed value; `+ where False = hasattr(o,'x')` is not), `SystemExit: 2`
(an argparse unrecognised-flag exit and a gate's own verdict exit are the same
two characters), `Failed: DID NOT RAISE`, and any failure whose text carries no
recoverable assertion.

MEASURED OVER THIS REPO'S OWN HISTORY BEFORE SHIPPING
-----------------------------------------------------
`programs/tests/_control_corpus_replay.py` replays the standard control over
45 real non-merge commits that added a test file (check out the parent, drop
in the added tests, run, classify). All 45 produced a usable report:

    7  of 45 commits (16 %)  TAUTOLOGICAL — zero substantive controls
    5  of 45 commits (11 %)  collected NOTHING — the PR #856 shape exactly
    22 of 45 commits (49 %)  under half their failing control tests were
                             substantive; median per-commit share 0.50

Per failing test case the split was 197 substantive / 759 presence-only /
45 undecided / 6 not-collected. **Do not quote the raw 75 % presence-only.**
One heavily parametrised commit contributes 497 of those 759 on its own, so
the per-case ratio measures that commit more than it measures the repo; the
per-COMMIT figures above are the ones that survive re-weighting.

TEXT MODE IS WEAKER AND THE PROGRAM SAYS SO
-------------------------------------------
`--junit` is exact. `--text` parses a pasted console log, where pytest gives
only the FIRST line of each crash, terminal-truncated with `...`. Every
custom-message assertion (`assert x == y, "why"`) loses its assert line to the
message, and every long repr loses its right-hand side. Text mode therefore
reports MORE undecided than the same run's XML, and this program measures that
gap rather than asserting it is small (see `--compare-modes`).

chip-AGNOSTIC: pytest report structure and Python exception text only. No
design, PDK, vendor or part-number literal.

USAGE
-----
    # capture the control (junitxml is pytest core; it survives autoload=0)
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest <the PR's new tests> \\
        -q -p no:cacheprovider --junitxml=/tmp/control.xml

    control_substance_check.py --junit /tmp/control.xml [--json OUT] [-v]
    control_substance_check.py --text  /tmp/control.txt
    control_substance_check.py --junit X.xml --text X.txt --compare-modes

EXIT CODES
----------
    0 = at least one substantive (c) control, or --advisory
    1 = TAUTOLOGICAL: zero substantive controls among the failures
    2 = no evidence could be read
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Buckets. Only OBSERVED_VALUE is substantive.
# ---------------------------------------------------------------------------
NOT_COLLECTED = "not_collected"      # (a) no test body ran
NOT_RUN = "not_run"                  # (a') collected, setup/teardown died
PRESENCE_ONLY = "presence_only"      # (b) pins no value
OBSERVED_VALUE = "observed_value"    # (c) substantive
UNDECIDED = "undecided"              # named, never credited
PASSED = "passed"                    # already green pre-fix: not a control
SKIPPED = "skipped"

ORDER = [OBSERVED_VALUE, PRESENCE_ONLY, NOT_COLLECTED, NOT_RUN, UNDECIDED,
         PASSED, SKIPPED]

# Container reprs that mean "there was nothing to look in".
_EMPTY_REPRS = {"{}", "[]", "()", "''", '""', "set()", "frozenset()",
                "dict()", "list()", "tuple()", "b''", 'b""'}

# Where-line sources that are symbol/artefact PRESENCE predicates: they answer
# "is it there", never "what is it". Listed explicitly so the rule is audit-
# able rather than a regex that grew.
# `isinstance(` is deliberately NOT here: it observes a TYPE, which is a
# property of a value, not the presence of a name. It falls through to the
# bare-truthiness branch and is reported undecided.
_PRESENCE_PREDICATES = ("hasattr(", ".exists()", "os.path.exists(",
                        ".is_file()", ".is_dir()")

# Exception types whose message proves a NAME was not found. These are (b) no
# matter which class pytest happened to raise.
_ABSENCE_EXC_PATTERNS: Tuple[Tuple[str, str, str], ...] = (
    ("ModuleNotFoundError", r"No module named", "module does not exist yet"),
    ("ImportError", r"cannot import name", "name not exported yet"),
    ("ImportError", r"No module named", "module does not exist yet"),
    ("AttributeError", r"has no attribute", "attribute does not exist yet"),
    ("KeyError", r".", "key absent from the mapping"),
    ("NameError", r"is not defined", "name does not exist yet"),
    ("TypeError", r"unexpected keyword argument", "parameter not accepted yet"),
    ("TypeError", r"missing \d+ required positional argument",
     "signature does not take that argument yet"),
    ("TypeError", r"takes \d+ positional argument", "signature arity differs"),
)


# ---------------------------------------------------------------------------
# Assertion-text parsing
# ---------------------------------------------------------------------------
def error_block(text: str) -> str:
    """The LAST contiguous run of pytest's ``E``-prefixed lines.

    That block is the crash pytest actually reported; earlier blocks are
    chained "during handling of the above" context. Returns "" if there is
    none.
    """
    blocks: List[List[str]] = []
    cur: List[str] = []
    for raw in (text or "").splitlines():
        m = re.match(r"^E(?:\s(.*))?$", raw)
        if m:
            cur.append((m.group(1) or "").rstrip())
        else:
            if cur:
                blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return "\n".join(blocks[-1]) if blocks else ""


_EXC_SUFFIXES = ("Error", "Exit", "Exception", "Failed", "Warning",
                 "Interrupted")


def split_exception(first_line: str) -> Tuple[Optional[str], str]:
    """``("KeyError", "'k'")`` / ``(None, "assert 0 > 0")``.

    The suffix test is applied to the WHOLE captured name, because pytest's own
    ``Failed: DID NOT RAISE`` is a name that is nothing but its suffix — an
    earlier form of this regex required at least one character before the
    suffix and silently dropped every ``pytest.raises`` outcome into the
    generic bucket.
    """
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*)\s*:\s?(.*)$", first_line)
    if m and m.group(1).endswith(_EXC_SUFFIXES):
        return m.group(1), m.group(2)
    return None, first_line


def _strip_outer_parens(expr: str) -> str:
    while expr.startswith("(") and expr.endswith(")"):
        depth = 0
        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i != len(expr) - 1:
                    return expr
        expr = expr[1:-1].strip()
    return expr


_OPS = ("not in", "is not", "in", "is", "==", "!=", ">=", "<=", ">", "<")


def split_comparison(expr: str) -> Optional[Tuple[str, str, str]]:
    """Top-level ``(lhs, op, rhs)``, or None when the expression is bare.

    Walks once, tracking string quotes, bracket depth, and ``<...>`` object
    reprs (entered only on ``<`` immediately followed by a non-space, which is
    how a repr looks and how a ``2 < 3`` comparison does not). Operators are
    matched only when space-delimited at depth 0 — that is exactly how pytest's
    rewriter formats them.
    """
    i, n = 0, len(expr)
    depth = 0
    quote: Optional[str] = None
    angle = 0
    while i < n:
        ch = expr[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            continue
        if angle:
            if ch == ">":
                angle -= 1
            elif ch == "<" and i + 1 < n and not expr[i + 1].isspace():
                angle += 1
            i += 1
            continue
        if ch in "([{":
            depth += 1
            i += 1
            continue
        if ch in ")]}":
            depth -= 1
            i += 1
            continue
        if ch == "<" and i + 1 < n and not expr[i + 1].isspace():
            angle += 1
            i += 1
            continue
        if depth == 0 and (i == 0 or expr[i - 1] == " "):
            for op in _OPS:
                if expr.startswith(op + " ", i) and i > 0:
                    lhs = expr[: i - 1].strip()
                    rhs = expr[i + len(op) + 1:].strip()
                    if lhs and rhs:
                        return lhs, op, rhs
        i += 1
    return None


def parse_where(lines: List[str]) -> List[Tuple[str, str]]:
    """``+  where None = _sha({...})`` -> ``[("None", "_sha({...})")]``."""
    out: List[Tuple[str, str]] = []
    for ln in lines:
        m = re.match(r"^\+\s*(?:where|and)\s+(.*?)\s*=\s*(.*)$", ln.strip())
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def _is_len_of_empty(repr_: str, wheres: List[Tuple[str, str]]) -> bool:
    for value, source in wheres:
        if value == repr_ and re.match(r"^len\((\{\}|\[\]|\(\)|''|\"\"|"
                                       r"set\(\)|b''|b\"\")\)$", source):
            return True
    return False


def _presence_predicate(wheres: List[Tuple[str, str]]) -> Optional[str]:
    for _value, source in wheres:
        for pred in _PRESENCE_PREDICATES:
            if pred in source:
                return pred
    return None


def classify_failure(block: str) -> Dict[str, str]:
    """Classify one failure from pytest's own rendering of it.

    ``block`` is the ``E``-line text (or the JUnit ``message`` attribute).
    Returns ``{"bucket": ..., "reason": ..., "assert": ...}``.
    """
    # pytest's `E   ` marker keeps the source's own indentation after it, so
    # every line is left-stripped before matching. Nothing below depends on
    # indentation.
    lines = [ln.strip() for ln in (block or "").splitlines() if ln.strip()]
    if not lines:
        return {"bucket": UNDECIDED, "reason": "empty failure text",
                "assert": ""}

    exc, rest = split_exception(lines[0])

    # ---- non-assertion exceptions -----------------------------------------
    is_assertion = (exc == "AssertionError") or (
        exc is None and rest.lstrip().startswith("assert "))
    if not is_assertion:
        whole = "\n".join(lines)
        for want_exc, pat, why in _ABSENCE_EXC_PATTERNS:
            if exc == want_exc and re.search(pat, rest or whole):
                return {"bucket": PRESENCE_ONLY,
                        "reason": f"{exc}: {why}", "assert": ""}
        if exc == "SystemExit":
            return {"bucket": UNDECIDED,
                    "reason": "SystemExit: an argparse exit for a flag the fix "
                              "introduces and a gate's own non-zero verdict "
                              "produce the same text",
                    "assert": ""}
        if exc == "Failed" and "DID NOT RAISE" in whole:
            return {"bucket": UNDECIDED,
                    "reason": "pytest.raises did not raise: the pre-fix code "
                              "ran and returned; whether that is a wrong value "
                              "or a check the fix introduces is not in this "
                              "text",
                    "assert": ""}
        return {"bucket": UNDECIDED,
                "reason": f"{exc or 'unrecognised'}: not a known "
                          f"absence shape and pins no compared value",
                "assert": ""}

    # ---- assertion: find the rewritten `assert ...` line -------------------
    cands: List[str] = []
    if rest.lstrip().startswith("assert "):
        cands.append(rest.strip())
    for ln in lines[1:]:
        if ln.strip().startswith("assert "):
            cands.append(ln.strip())
    if not cands:
        return {"bucket": UNDECIDED,
                "reason": "AssertionError carries a custom message but no "
                          "rewritten assertion (raise AssertionError(...), or "
                          "a truncated console log)",
                "assert": ""}

    expr = _strip_outer_parens(cands[0][len("assert "):].strip())
    wheres = parse_where(lines)
    out = {"assert": f"assert {expr}"}

    pred = _presence_predicate(wheres)
    cmp_ = split_comparison(expr)

    if cmp_ is None:
        # bare truthiness
        if expr.strip() == "None":
            return {**out, "bucket": PRESENCE_ONLY,
                    "reason": "bare truthiness observed None: the assertion "
                              "names no expected value, so it separates only "
                              "absent/null from present"}
        if pred:
            return {**out, "bucket": PRESENCE_ONLY,
                    "reason": f"bare truthiness over the presence predicate "
                              f"{pred!r}"}
        return {**out, "bucket": UNDECIDED,
                "reason": "bare truthiness over a non-None value: the value "
                          "was observed, but the assertion pins no expected "
                          "value to compare it against"}

    lhs, op, rhs = cmp_

    if op == "is not" and rhs == "None":
        return {**out, "bucket": PRESENCE_ONLY,
                "reason": "`is not None` failed, so the value is None: the "
                          "assertion separates only absent/null from present"}
    if op == "is" and rhs == "None":
        return {**out, "bucket": UNDECIDED,
                "reason": "`is None` failed, so something concrete was "
                          "observed, but the only expectation named is the "
                          "None sentinel"}
    if pred:
        return {**out, "bucket": PRESENCE_ONLY,
                "reason": f"compares the presence predicate {pred!r}"}
    if op in ("in", "not in"):
        if rhs in _EMPTY_REPRS:
            return {**out, "bucket": PRESENCE_ONLY,
                    "reason": f"membership in the empty container {rhs}: "
                              f"there was nothing to look in"}
        return {**out, "bucket": OBSERVED_VALUE,
                "reason": f"membership tested against observed content "
                          f"({len(rhs)} chars of it)"}
    if lhs == "None" or rhs == "None":
        return {**out, "bucket": UNDECIDED,
                "reason": "one side is the None sentinel: from this text a "
                          "field the fix introduces being absent and a "
                          "callable that genuinely returns None are the same "
                          "input"}
    if _is_len_of_empty(lhs, wheres):
        if op in (">", "<", ">=", "<="):
            # `len(x) > 0` passes for ANY non-empty result. It pins no value.
            return {**out, "bucket": PRESENCE_ONLY,
                    "reason": "a length threshold over an empty container: "
                              "any non-empty result would satisfy it, so it "
                              "pins no value"}
        # `len(x) == 27` DOES pin a value — 26 would still fail — but the
        # observed 0 is also exactly what absence looks like. Same shape as
        # the None sentinel above, and refused for the same reason.
        return {**out, "bucket": UNDECIDED,
                "reason": "an equality over a length that observed 0: the "
                          "expected count is pinned, but 0 is also exactly "
                          "what an absent/empty field looks like"}
    return {**out, "bucket": OBSERVED_VALUE,
            "reason": f"observed {_clip(lhs)} where the test requires "
                      f"{op} {_clip(rhs)}"}


def _clip(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Evidence readers
# ---------------------------------------------------------------------------
def read_junit(path: Path) -> List[Dict]:
    """One record per testcase. Raises OSError/ET.ParseError to the caller."""
    root = ET.parse(str(path)).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    cases: List[Dict] = []
    for suite in suites:
        for tc in suite.findall("testcase"):
            cls = (tc.attrib.get("classname") or "").strip()
            nm = (tc.attrib.get("name") or "").strip()
            ident = f"{cls}::{nm}" if cls else nm
            err = tc.find("error")
            fail = tc.find("failure")
            skip = tc.find("skipped")
            if err is not None:
                msg = (err.attrib.get("message") or "").lower()
                body = err.text or ""
                if "collection" in msg:
                    # The trap: the suite still counts this as tests="1".
                    cases.append({
                        "test": ident, "bucket": NOT_COLLECTED,
                        "reason": _clip(
                            error_block(body).splitlines()[-1]
                            if error_block(body) else msg, 120),
                        "assert": ""})
                else:
                    cases.append({
                        "test": ident, "bucket": NOT_RUN,
                        "reason": f"{msg or 'error'}: the test body never ran",
                        "assert": ""})
            elif fail is not None:
                body = fail.text or ""
                block = error_block(body) or (fail.attrib.get("message") or "")
                cases.append({"test": ident, **classify_failure(block)})
            elif skip is not None:
                cases.append({"test": ident, "bucket": SKIPPED,
                              "reason": _clip(
                                  skip.attrib.get("message") or "skipped"),
                              "assert": ""})
            else:
                cases.append({"test": ident, "bucket": PASSED,
                              "reason": "already green before the fix — this "
                                        "test is not a control",
                              "assert": ""})
    return cases


_TXT_FAILED = re.compile(r"^FAILED\s+(\S+)(?:\s+-\s+(.*))?$")
_TXT_ERROR = re.compile(r"^ERROR\s+(\S+)(?:\s+-\s+(.*))?$")
_TXT_COLLECT = re.compile(r"error[s]? during collection|ERROR collecting|"
                          r"Interrupted:", re.IGNORECASE)


def read_text(path: Path) -> List[Dict]:
    """Best-effort read of a pasted console log. Documented as weaker."""
    raw = path.read_text(errors="replace")
    collection_broke = bool(_TXT_COLLECT.search(raw))
    cases: List[Dict] = []
    for line in raw.splitlines():
        line = line.rstrip()
        m = _TXT_ERROR.match(line)
        if m:
            cases.append({"test": m.group(1), "bucket": NOT_COLLECTED,
                          "reason": _clip(m.group(2) or
                                          "reported as ERROR, not FAILED"),
                          "assert": ""})
            continue
        m = _TXT_FAILED.match(line)
        if m:
            msg = (m.group(2) or "").rstrip()
            if not msg:
                cases.append({"test": m.group(1), "bucket": UNDECIDED,
                              "reason": "console log carries no crash text",
                              "assert": ""})
            elif msg.endswith("...") or msg.endswith("…"):
                cases.append({"test": m.group(1), "bucket": UNDECIDED,
                              "reason": "console line is terminal-truncated; "
                                        "re-run with --junitxml",
                              "assert": ""})
            else:
                cases.append({"test": m.group(1), **classify_failure(msg)})
    if collection_broke and not cases:
        cases.append({"test": "<collection>", "bucket": NOT_COLLECTED,
                      "reason": "collection failed; no test was collected",
                      "assert": ""})
    return cases


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def tally(cases: List[Dict]) -> Dict[str, int]:
    counts = {b: 0 for b in ORDER}
    for c in cases:
        counts[c["bucket"]] = counts.get(c["bucket"], 0) + 1
    return counts


def audit(cases: List[Dict], source: str = "junit") -> Dict:
    counts = tally(cases)
    failures = (counts[OBSERVED_VALUE] + counts[PRESENCE_ONLY] +
                counts[UNDECIDED] + counts[NOT_COLLECTED] + counts[NOT_RUN])
    return {
        "source": source,
        "cases": cases,
        "counts": counts,
        "total_testcases": len(cases),
        "failures_reported": failures,
        "substantive": counts[OBSERVED_VALUE],
        "tautological": counts[OBSERVED_VALUE] == 0 and failures > 0,
        "no_evidence": len(cases) == 0,
    }


def render(rep: Dict, verbose: bool = False) -> List[str]:
    c = rep["counts"]
    out = [
        f"control_substance_check ({rep['source']}): "
        f"{rep['substantive']} of {rep['failures_reported']} reported "
        f"failures observed a VALUE",
        f"   (c) observed value  : {c[OBSERVED_VALUE]}   <- the only "
        f"substantive control",
        f"   (b) presence-only   : {c[PRESENCE_ONLY]}",
        f"   (a) did not collect : {c[NOT_COLLECTED]}"
        + ("   <- no test body ran" if c[NOT_COLLECTED] else ""),
        f"   (a) collected, body never ran : {c[NOT_RUN]}",
        f"   undecided (never credited)    : {c[UNDECIDED]}",
        f"   passed on the control (not a control) : {c[PASSED]}"
        f"   skipped: {c[SKIPPED]}",
    ]
    if verbose or rep["tautological"]:
        for case in rep["cases"]:
            if case["bucket"] in (PASSED, SKIPPED) and not verbose:
                continue
            out.append(f"     [{case['bucket']}] {case['test']}")
            out.append(f"         {case['reason']}")
            if case.get("assert"):
                out.append(f"         {_clip(case['assert'], 100)}")
    if rep["tautological"]:
        out += [
            "   TAUTOLOGICAL CONTROL: every reported failure is explained by "
            "something being absent before the fix.",
            "   'The tests fail pre-fix' is true here and carries no "
            "information: a test file that imports a module the fix "
            "introduces cannot do anything else on main.",
            "   What would carry information: a control in which the module "
            "exists and only the CHANGED behaviour is reverted, so an "
            "assertion executes over an observed value and that value is "
            "wrong.",
        ]
    return out


def compare_modes(xml_rep: Dict, txt_rep: Dict) -> List[str]:
    """Measure, do not assert, how much text mode loses."""
    xs, ts = xml_rep["counts"], txt_rep["counts"]
    return [
        "mode comparison (measured, not assumed):",
        f"   substantive: junit={xs[OBSERVED_VALUE]}  text={ts[OBSERVED_VALUE]}",
        f"   undecided  : junit={xs[UNDECIDED]}  text={ts[UNDECIDED]}",
        f"   text mode lost {max(0, xs[OBSERVED_VALUE] - ts[OBSERVED_VALUE])} "
        f"substantive verdict(s) to truncation/custom messages",
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--junit", action="append", default=[],
                    help="pytest --junitxml output (exact; preferred)")
    ap.add_argument("--text", action="append", default=[],
                    help="pytest console log (best-effort; weaker)")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--compare-modes", action="store_true",
                    help="report how much text mode loses vs the same "
                         "run's XML")
    ap.add_argument("--advisory", action="store_true",
                    help="report only; exit 0 even on a tautological control")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    if not a.junit and not a.text:
        print("[ERROR] control_substance_check: pass --junit and/or --text",
              file=sys.stderr)
        return 2

    xml_cases: List[Dict] = []
    txt_cases: List[Dict] = []
    unreadable: List[str] = []
    for p in a.junit:
        try:
            xml_cases += read_junit(Path(p))
        except (OSError, ET.ParseError) as exc:
            unreadable.append(f"{p}: {exc}")
    for p in a.text:
        try:
            txt_cases += read_text(Path(p))
        except OSError as exc:
            unreadable.append(f"{p}: {exc}")

    primary = audit(xml_cases, "junit") if a.junit else audit(txt_cases, "text")
    lines = render(primary, a.verbose)
    reports = {"primary": primary}
    if a.compare_modes and a.junit and a.text:
        txt_rep = audit(txt_cases, "text")
        reports["text"] = txt_rep
        lines += compare_modes(primary, txt_rep)
    for u in unreadable:
        lines.append(f"   [unreadable] {u}")

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(reports, indent=2) + "\n")
    print("\n".join(lines))

    if primary["no_evidence"]:
        print("[ERROR] control_substance_check: no testcase found in the "
              "evidence — the control produced nothing to classify",
              file=sys.stderr)
        return 2
    if a.advisory:
        return 0
    return 1 if primary["tautological"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
