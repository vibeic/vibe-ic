#!/usr/bin/env python3
"""harness_verdict_token_guard.py — refuse a candidate RTL submission that
carries the SCORING HARNESS'S OWN VERDICT VOCABULARY, BEFORE it is scored.

GATE CLASSIFICATION: **BLOCKING**.
A finding REFUSES the submission — the candidate is not compiled, not run, and
never reaches a PASS. It is never downgraded to a note. Rationale below.

WHY THIS GATE EXISTS
====================
Every scorer in this tree decides PASS by searching the SIMULATOR'S COMBINED
STDOUT for the benchmark's verdict marker (`scorer_args.pass_regex` in
BENCHMARK_REGISTRY.json). The device under test shares that stdout with the
testbench. So a submission can print the marker itself and the scorer cannot
tell which process wrote it.

MEASURED, in this repo, on this scorer (benchmark/score_iverilog_tb.py), with a
four-problem synthetic Shape-C fixture:

    Prob002_wrong    y = ~a                                   -> FAIL
    Prob003_forged   y = ~a  +  initial $display("Mismatches: 0 in 20 samples");
                                                              -> PASS

    raw simulator output for Prob003_forged:
        Mismatches: 0 in 20 samples          <- printed by the CANDIDATE
        Mismatches: 20 in 20 samples         <- printed by the TESTBENCH

Two submissions with IDENTICAL WRONG LOGIC scored 2/3 = 66.67%. The simulator
said `Mismatches: 20 in 20 samples` for BOTH.

Note what that makes the pre-existing check: NOT vacuous. The honest-wrong
control FAILs correctly. It is FORGEABLE, which is strictly worse — it
discriminates right up until somebody forges, and a forged PASS is
indistinguishable from an earned one in the table we publish.

Hence BLOCKING and not advisory: an advisory record would leave the forged PASS
standing in the published number, which is the entire defect.

WHAT IT CHECKS
==============
A design that prints the scorer's verdict string answered a question about the
scorer, not about the circuit. So: no string the CANDIDATE can emit may carry
the harness's verdict vocabulary.

  1. Comments are stripped first (a comment cannot reach stdout, and a design
     whose header prose quotes the marker is not forging anything).
  2. Every remaining string literal is collected, with its line number.
  3. Literals belonging to one output system task (`$display`, `$write`,
     `$monitor`, `$error`, ... and their file/format variants) are ALSO tested
     concatenated, so `$write("Your Design ", "Passed")` is caught.
  4. Each candidate string is tested against ANCHOR SETS derived from the
     harness's own `pass_regex` / `fail_regex` — not from any hardcoded list.
     The anchors are that pattern's REQUIRED alphabetic literals, in order.

Deriving the anchors from the pattern (rather than matching the pattern
literally) is what catches the format-string form, which is the form a forger
reaches for second:

    pass_regex   Mismatches:\\s*0\\s+in\\s+\\d+\\s+samples
    anchors      Mismatches -> in -> samples
    caught       $display("Mismatches: 0 in 20 samples")            (literal)
    caught       $display("Mismatches: %0d in %0d samples", 0, 20)  (format)

Digit literals inside the pattern are deliberately NOT anchors: in a verdict
marker a digit is the reported VALUE, and a forger supplies it at run time
through a format specifier. Dropping them makes the guard catch strictly more,
never less.

WHAT IT DOES NOT CATCH — the honest boundary
============================================
This is a STATIC scan of the submitted source. A submission that assembles the
marker at run time without ever writing it down — character arithmetic, a
computed `$write("%c", ...)` loop — is NOT detected here, and no static string
scan can detect it. That residual channel is DISCLOSED, never papered over:
`scan_report()` reports `dut_output_task_count`, the number of output system
tasks the candidate contains at all, so a reader can see whether a cleared
submission writes to the simulator's stdout for any reason.

CORPUS SWEEP — a gate that fires on legitimate RTL is a bug in the gate
=====================================================================
Swept over 315 real candidate/RTL files before landing: the 156 + 156 candidate
samples of two completed VerilogEval-suite runs, plus the repo's own checked-in
canonical samples and protocol testbench. Every registry verdict pattern
(`Mismatches: 0 in N samples`, `Your Design Passed`, `Test failed|Your Design
Failed`) was applied to every file at once — the strictest configuration, not
the per-benchmark one.

    REFUSED     : 0
    NOT_CHECKED : 0
    files containing >= 1 output system task : 1, and it is a TESTBENCH.

Zero of the 312 real candidate samples write to stdout for any reason, which is
what makes this gate cheap to satisfy: legitimate candidate RTL does not talk.

COVERAGE LIMIT, stated rather than implied: the sweep covers the two
VerilogEval suites. No completed Shape-B run corpus was available on the sweep
host, so the Shape-B vocabulary is exercised by synthesized fixtures and by the
registry-driven test, not by a real run. NOT DETERMINED for Shape B at corpus
scale.

Bench-AGNOSTIC and chip-AGNOSTIC: every token comes from the caller's own
`patterns` mapping (in practice BENCHMARK_REGISTRY.json). This file contains no
benchmark's verdict string, no design name, no PDK and no vendor literal.

DEGRADE LOUDLY
==============
There is no silent clear. If no usable pattern is supplied, or a pattern is too
complex to extract required anchors from, the verdict is `NOT_CHECKED` with a
named reason and exit 2 — never `CLEAR`.

Exit codes
==========
    0  CLEAR       — no candidate string carries the harness's verdict vocabulary
    1  REFUSED     — at least one does; the submission must not be scored
    2  NOT_CHECKED — the guard could not run (no pattern / unsupported pattern /
                     unreadable file). NOT a pass.

Usage
=====
    harness_verdict_token_guard.py --rtl cand.sv --bench verilogeval-v2
    harness_verdict_token_guard.py --rtl cand.v \\
        --pattern "pass_regex=Your Design Passed" --json report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

VERDICT_CLEAR = "CLEAR"
VERDICT_REFUSED = "REFUSED"
VERDICT_NOT_CHECKED = "NOT_CHECKED"

#: The reason string a caller can key on when refusing a submission.
REFUSAL_REASON = "harness_verdict_token_forgery"

#: Verilog / SystemVerilog system tasks that put text on the simulator's stdout
#: (or into a string a design can later put there). Language-level, not
#: benchmark-level: this list is the same for every design ever scored.
_OUTPUT_TASKS = (
    "display", "displayb", "displayo", "displayh",
    "write", "writeb", "writeo", "writeh",
    "strobe", "strobeb", "strobeo", "strobeh",
    "monitor", "monitorb", "monitoro", "monitorh",
    "fdisplay", "fwrite", "fstrobe", "fmonitor",
    "swrite", "swriteb", "swriteo", "swriteh",
    "sformat", "sformatf", "psprintf",
    "info", "warning", "error", "fatal",
)
_OUTPUT_TASK_RE = re.compile(
    r"\$(" + "|".join(sorted(_OUTPUT_TASKS, key=len, reverse=True)) + r")\s*\(")

#: Guard against a pathological pattern whose alternations explode. Exceeding it
#: is reported as NOT_CHECKED, never as CLEAR.
_MAX_ALTERNATIVES = 64


# --------------------------------------------------------------------------- #
# (1) source scanning — comments out, string literals (with line numbers) in
# --------------------------------------------------------------------------- #
def strip_comments_and_collect_literals(
        text: str) -> Tuple[str, List[Tuple[int, int, str]]]:
    """Return ``(comment_free_text, literals)``.

    ``literals`` is ``[(line_no, char_offset_in_comment_free_text, content), ...]``
    for every double-quoted string literal OUTSIDE a comment. The comment-free
    text keeps the original character count (comment bytes become spaces, and
    newlines are preserved) so offsets and line numbers stay meaningful.

    A single left-to-right scan, because the three contexts are mutually
    exclusive: a ``//`` inside a string opens no comment, and a quote inside a
    comment opens no string.
    """
    out: List[str] = []
    literals: List[Tuple[int, int, str]] = []
    i, n, line = 0, len(text), 1
    while i < n:
        ch = text[i]
        if ch == "\n":
            out.append(ch)
            line += 1
            i += 1
        elif ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out.append(" ")
                i += 1
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            out.append("  ")
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                if text[i] == "\n":
                    out.append("\n")
                    line += 1
                else:
                    out.append(" ")
                i += 1
            if i < n:
                out.append("  ")
                i += 2
        elif ch == '"':
            start_line, start_off = line, len(out)
            buf: List[str] = []
            out.append(ch)
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i:i + 2])
                    out.append(text[i:i + 2])
                    if text[i + 1] == "\n":
                        line += 1
                    i += 2
                    continue
                if text[i] == "\n":       # unterminated literal — stop at EOL
                    break
                buf.append(text[i])
                out.append(text[i])
                i += 1
            if i < n and text[i] == '"':
                out.append('"')
                i += 1
            literals.append((start_line, start_off, "".join(buf)))
        else:
            out.append(ch)
            i += 1
    return "".join(out), literals


def _mask_string_contents(clean: str) -> str:
    """`clean` with every string literal's CONTENT replaced by spaces, quotes and
    length preserved.

    Structure is read off this masked view so that punctuation a design PRINTS
    cannot be mistaken for punctuation a design WRITES: `$display("(")` must not
    unbalance the argument scan, and the text `$display(` inside a literal must
    not look like a call. Offsets stay valid against the unmasked text because
    the length is unchanged.
    """
    out, i, n = [], 0, len(clean)
    while i < n:
        c = clean[i]
        out.append(c)
        i += 1
        if c != '"':
            continue
        while i < n and clean[i] != '"':
            if clean[i] == "\\" and i + 1 < n:
                out.append("  ")
                i += 2
                continue
            out.append("\n" if clean[i] == "\n" else " ")
            i += 1
        if i < n:
            out.append('"')
            i += 1
    return "".join(out)


def _balanced_arg_span(text: str, open_paren_idx: int) -> Optional[Tuple[int, int]]:
    """Return ``(start, end)`` of the argument text inside the parentheses that
    open at ``open_paren_idx``, or None if they never close. `text` is expected
    to be the string-masked view (see :func:`_mask_string_contents`)."""
    depth, i, n = 0, open_paren_idx, len(text)
    while i < n:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return open_paren_idx + 1, i
        i += 1
    return None


def output_task_literal_groups(
        clean: str, literals: List[Tuple[int, int, str]]) -> List[Tuple[int, str]]:
    """Return ``[(line_no, concatenated_literals), ...]``, one entry per output
    system task call whose argument list contains at least two string literals.

    Only multi-literal calls are returned: a single-literal call is already
    covered by the per-literal scan, and returning it twice would double-report
    the same line.
    """
    groups: List[Tuple[int, str]] = []
    masked = _mask_string_contents(clean)
    for m in _OUTPUT_TASK_RE.finditer(masked):
        span = _balanced_arg_span(masked, m.end() - 1)
        if span is None:
            continue
        lo, hi = span
        inside = [(ln, txt) for (ln, off, txt) in literals if lo <= off < hi]
        if len(inside) >= 2:
            groups.append((inside[0][0], "".join(t for _, t in inside)))
    return groups


def count_output_tasks(clean: str) -> int:
    """How many output system tasks the candidate contains at all (disclosure of
    the residual run-time-assembly channel; never a verdict on its own)."""
    return sum(1 for _ in _OUTPUT_TASK_RE.finditer(_mask_string_contents(clean)))


# --------------------------------------------------------------------------- #
# (2) anchor extraction — the REQUIRED alphabetic literals of a verdict pattern
# --------------------------------------------------------------------------- #
class UnsupportedPattern(ValueError):
    """The pattern's required literals could not be extracted. The caller MUST
    surface this as NOT_CHECKED — never treat it as 'nothing found'."""


def _split_alternatives(pattern: str) -> List[str]:
    """Split on top-level ``|`` only (escapes, groups and classes respected)."""
    parts, buf, depth, i, n = [], [], 0, 0, len(pattern)
    in_class = False
    while i < n:
        c = pattern[i]
        if c == "\\" and i + 1 < n:
            buf.append(pattern[i:i + 2])
            i += 2
            continue
        if in_class:
            buf.append(c)
            if c == "]":
                in_class = False
            i += 1
            continue
        if c == "[":
            in_class = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def _required_literal_runs(branch: str) -> List[str]:
    """Return the literal character runs a match of ``branch`` MUST contain.

    Everything that is not a required literal character — escapes with a class
    meaning (``\\s`` ``\\d`` ``\\w`` ...), character classes, ``.``, anchors,
    group delimiters — terminates the current run. A literal followed by a
    quantifier that permits zero occurrences (``*``, ``?``, ``{0...``) is not
    required, so it is dropped and the run is split there.
    """
    runs: List[str] = []
    cur: List[str] = []

    def flush() -> None:
        if cur:
            runs.append("".join(cur))
            cur.clear()

    i, n = 0, len(branch)
    while i < n:
        c = branch[i]
        nxt = branch[i + 1] if i + 1 < n else ""
        if c == "\\" and nxt:
            if nxt.isalpha():          # \s \d \w \b ... — a class, not a literal
                flush()
            else:                      # \. \+ \( ... — an escaped literal char
                cur.append(nxt)
            i += 2
            continue
        if c in "*?+":                 # quantifier on the preceding literal
            if c in "*?" and cur:
                cur.pop()              # zero occurrences allowed -> not required
            flush()
            i += 1
            continue
        if c == "{":
            close = branch.find("}", i)
            if close == -1:
                cur.append(c)
                i += 1
                continue
            if re.fullmatch(r"\{0(,\d*)?\}", branch[i:close + 1]) and cur:
                cur.pop()
            flush()
            i = close + 1
            continue
        if c == "[":
            close, depth = i + 1, 0
            while close < n and (branch[close] != "]" or depth):
                if branch[close] == "\\":
                    close += 1
                close += 1
            flush()
            i = close + 1
            continue
        if c in "().^$":
            flush()
            i += 1
            continue
        cur.append(c)
        i += 1
    flush()
    return runs


def _first_top_level_group(branch: str) -> Optional[Tuple[int, int]]:
    """Return ``(open_idx, close_idx)`` of the first depth-0 group, or None.
    Escapes and character classes are skipped, so ``\\(`` and ``[(]`` are not
    mistaken for a group."""
    i, n, in_class = 0, len(branch), False
    while i < n:
        c = branch[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
            i += 1
            continue
        if c == "[":
            in_class = True
            i += 1
            continue
        if c == "(":
            depth, j = 0, i
            while j < n:
                if branch[j] == "\\":
                    j += 2
                    continue
                if branch[j] == "(":
                    depth += 1
                elif branch[j] == ")":
                    depth -= 1
                    if depth == 0:
                        return i, j
                j += 1
            raise UnsupportedPattern("unbalanced '(' in pattern")
        i += 1
    return None


def _expand_branch(branch: str) -> List[str]:
    """Expand every group in one alternation-free-at-top-level branch into the
    flat strings it can produce. A group that permits zero occurrences also
    yields the empty string, so an optional literal never becomes a required
    anchor."""
    found = _first_top_level_group(branch)
    if found is None:
        return [branch]
    lo, hi = found
    inner, prefix, suffix = branch[lo + 1:hi], branch[:lo], branch[hi + 1:]
    if inner.startswith("?"):
        if inner.startswith("?:"):
            inner = inner[2:]
        else:                       # lookaround / named / conditional group
            raise UnsupportedPattern(
                f"unsupported group construct '({inner[:3]}...'")
    opts = _expand_alternations(inner)
    if suffix[:1] in ("*", "?"):
        opts = opts + [""]
        suffix = suffix[1:]
    elif suffix[:1] == "+":
        suffix = suffix[1:]
    out: List[str] = []
    for tail in _expand_branch(suffix):
        for o in opts:
            out.append(prefix + o + tail)
            if len(out) > _MAX_ALTERNATIVES:
                raise UnsupportedPattern(
                    f"pattern expands to more than {_MAX_ALTERNATIVES} "
                    "alternatives")
    return out


def _expand_alternations(pattern: str) -> List[str]:
    """Every flat string ``pattern`` can produce, alternations expanded at ALL
    depths. Over-constraining a nested alternation would silently turn a real
    forgery into a clear, so nesting is expanded rather than flattened."""
    out: List[str] = []
    for br in _split_alternatives(pattern):
        out.extend(_expand_branch(br))
        if len(out) > _MAX_ALTERNATIVES:
            raise UnsupportedPattern(
                f"pattern expands to more than {_MAX_ALTERNATIVES} alternatives")
    return out


def verdict_anchor_sets(pattern: str) -> List[List[str]]:
    """Return one ordered ALPHABETIC anchor list per alternative of ``pattern``.

    Raises :class:`UnsupportedPattern` when no alternative yields an anchor, or
    when the pattern cannot be expanded — either way the guard reports
    NOT_CHECKED rather than a clear it has not earned.
    """
    sets: List[List[str]] = []
    for flat in _expand_alternations(pattern):
        anchors: List[str] = []
        for run in _required_literal_runs(flat):
            anchors.extend(re.findall(r"[A-Za-z]+", run))
        if anchors and anchors not in sets:
            sets.append(anchors)
    if not sets:
        raise UnsupportedPattern(
            "no required alphabetic literal could be extracted from the pattern")
    return sets


def _anchor_regex(anchors: List[str]) -> "re.Pattern[str]":
    return re.compile(r".*?".join(r"\b" + re.escape(a) + r"\b" for a in anchors),
                      re.DOTALL)


# --------------------------------------------------------------------------- #
# (3) the scan
# --------------------------------------------------------------------------- #
def unusable_patterns(patterns: Dict[str, str]) -> Dict[str, str]:
    """``{pattern_name: why}`` for every supplied pattern the guard could NOT
    turn into anchors.

    A pattern set can be PARTLY usable — one marker analysable, another not.
    Scanning only the analysable half and saying nothing would be a silent
    partial decline, so the unusable half is named in every report.
    """
    out: Dict[str, str] = {}
    for name, pat in patterns.items():
        if not pat:
            out[name] = "empty pattern"
            continue
        try:
            verdict_anchor_sets(pat)
        except UnsupportedPattern as exc:
            out[name] = str(exc)
    return out


def scan(rtl_text: str, patterns: Dict[str, str]) -> List[dict]:
    """Return the findings for ``rtl_text`` against ``patterns``
    (``{pattern_name: regex}``, e.g. the registry's pass_regex / fail_regex).

    Raises :class:`UnsupportedPattern` if EVERY supplied pattern is unusable.
    """
    usable: List[Tuple[str, List[List[str]]]] = []
    for name, pat in patterns.items():
        if not pat:
            continue
        try:
            usable.append((name, verdict_anchor_sets(pat)))
        except UnsupportedPattern:
            continue                 # named by unusable_patterns(), not dropped
    if not usable:
        problems = unusable_patterns(patterns)
        raise UnsupportedPattern(
            "; ".join(f"{k}: {v}" for k, v in problems.items())
            or "no pattern supplied")

    clean, literals = strip_comments_and_collect_literals(rtl_text)
    candidates: List[Tuple[int, str, str]] = [
        (ln, txt, "string_literal") for (ln, _off, txt) in literals]
    candidates += [(ln, txt, "output_task_concat")
                   for (ln, txt) in output_task_literal_groups(clean, literals)]

    findings: List[dict] = []
    for name, anchor_sets in usable:
        for anchors in anchor_sets:
            rx = _anchor_regex(anchors)
            for line, text, kind in candidates:
                m = rx.search(text)
                if m:
                    findings.append({
                        "reason": REFUSAL_REASON,
                        "pattern_name": name,
                        "anchors": list(anchors),
                        "line": line,
                        "kind": kind,
                        "matched_text": m.group(0)[:200],
                    })
    findings.sort(key=lambda f: (f["line"], f["pattern_name"], f["kind"]))
    return findings


def scan_report(rtl_text: str, patterns: Dict[str, str],
                source: str = "<memory>") -> dict:
    """Full report for one candidate: verdict + findings + the disclosed
    residual-channel count. Never raises — an unusable pattern set becomes an
    explicit NOT_CHECKED record."""
    clean, _ = strip_comments_and_collect_literals(rtl_text)
    base = {
        "source": source,
        "gate": "harness_verdict_token_guard",
        "enforcement": "BLOCKING",
        "dut_output_task_count": count_output_tasks(clean),
        "static_scan_only": True,
        "patterns_checked": sorted(
            k for k in patterns if k not in unusable_patterns(patterns)),
        "patterns_not_checked": unusable_patterns(patterns),
        "undetectable_channel": (
            "a marker assembled at run time without appearing as a source "
            "string (character arithmetic / computed $write) is outside a "
            "static scan"),
    }
    try:
        findings = scan(rtl_text, patterns)
    except UnsupportedPattern as exc:
        base.update({"verdict": VERDICT_NOT_CHECKED,
                     "not_checked_reason": str(exc), "findings": []})
        return base
    base.update({
        "verdict": VERDICT_REFUSED if findings else VERDICT_CLEAR,
        "findings": findings,
    })
    return base


def refuse_or_none(rtl_text: str, patterns: Dict[str, str]) -> Optional[str]:
    """One-line refusal reason for a candidate, or None if it is CLEAR.

    The convenience form for callers that grade a candidate by searching the
    simulator's stdout and have nowhere to put a structured report. NOT_CHECKED
    is a refusal here too: a submission nobody checked has not been shown to be
    honest, and returning None for it would reintroduce the silent clear this
    gate exists to remove.
    """
    report = scan_report(rtl_text, patterns)
    if report["verdict"] == VERDICT_REFUSED:
        return refusal_summary(report)
    if report["verdict"] == VERDICT_NOT_CHECKED:
        return (f"harness_verdict_token_guard_not_checked — "
                f"{report['not_checked_reason']}; a submission nobody checked "
                f"is not a submission that passed")
    return None


def refusal_summary(report: dict) -> str:
    """One line naming WHERE and WHAT, for a scorer result row."""
    f = report.get("findings") or []
    if not f:
        return ""
    first = f[0]
    return (f"{REFUSAL_REASON} — the submitted RTL emits the harness's own "
            f"{first['pattern_name']} vocabulary "
            f"({' -> '.join(first['anchors'])}) at line {first['line']}: "
            f"{first['matched_text']!r}")


# --------------------------------------------------------------------------- #
# (4) registry lookup + CLI
# --------------------------------------------------------------------------- #
def registry_patterns(bench: str,
                      registry: Optional[Path] = None) -> Dict[str, str]:
    """Pull the verdict patterns for ``bench`` out of BENCHMARK_REGISTRY.json.

    Returns ``{}`` when the benchmark or its scorer_args are absent — the caller
    turns that into NOT_CHECKED, never into a clear.
    """
    reg = registry or (Path(__file__).resolve().parent.parent
                       / "benchmark" / "BENCHMARK_REGISTRY.json")
    try:
        entry = json.loads(Path(reg).read_text()).get(
            "benchmarks", {}).get(bench) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    sa = entry.get("scorer_args") or {}
    return {k: sa[k] for k in ("pass_regex", "fail_regex") if sa.get(k)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rtl", action="append", required=True, type=Path,
                    help="candidate RTL file to scan (repeatable)")
    ap.add_argument("--bench", default="",
                    help="benchmark key in BENCHMARK_REGISTRY.json — supplies "
                         "the verdict patterns")
    ap.add_argument("--registry", type=Path, default=None)
    ap.add_argument("--pattern", action="append", default=[],
                    metavar="NAME=REGEX",
                    help="verdict pattern, repeatable; overrides --bench")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the full report here")
    a = ap.parse_args(argv)

    patterns: Dict[str, str] = {}
    if a.bench:
        patterns.update(registry_patterns(a.bench, a.registry))
    for spec in a.pattern:
        name, sep, rx = spec.partition("=")
        if not sep:
            print(f"harness_verdict_token_guard: --pattern needs NAME=REGEX, "
                  f"got {spec!r}", file=sys.stderr)
            return 2
        patterns[name.strip()] = rx

    reports = []
    for path in a.rtl:
        try:
            text = path.read_text(errors="replace")
        except OSError as exc:
            reports.append({"source": str(path),
                            "gate": "harness_verdict_token_guard",
                            "enforcement": "BLOCKING",
                            "verdict": VERDICT_NOT_CHECKED,
                            "not_checked_reason": f"unreadable: {exc}",
                            "findings": []})
            continue
        reports.append(scan_report(text, patterns, source=str(path)))

    doc = {"gate": "harness_verdict_token_guard", "enforcement": "BLOCKING",
           "patterns": patterns, "reports": reports}
    if a.json:
        # vibe-ic#1082: a declared report destination is written atomically, so
        # a reader never sees a half-written verdict record.
        from _atomic_artefact import write_json
        write_json(a.json, doc)

    rc = 0
    for rep in reports:
        if rep["verdict"] == VERDICT_REFUSED:
            print(f"REFUSED  {rep['source']}: {refusal_summary(rep)}")
            rc = max(rc, 1)
        elif rep["verdict"] == VERDICT_NOT_CHECKED:
            print(f"NOT_CHECKED  {rep['source']}: {rep['not_checked_reason']} "
                  "— this is NOT a pass")
            rc = max(rc, 2)
        else:
            print(f"CLEAR  {rep['source']}  "
                  f"(output system tasks in candidate: "
                  f"{rep['dut_output_task_count']})")
        for name, why in (rep.get("patterns_not_checked") or {}).items():
            print(f"    ⚠ pattern '{name}' was NOT checked against this "
                  f"candidate: {why}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
