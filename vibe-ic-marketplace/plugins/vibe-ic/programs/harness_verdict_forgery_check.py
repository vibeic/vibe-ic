#!/usr/bin/env python3
"""harness_verdict_forgery_check.py — refuse to score a candidate that can PRINT
the scorer's own PASS verdict (vibe-ic#1745).

THE DEFECT (measured, on this repo's own scoring paths)
=======================================================
Every functional benchmark number this plugin publishes is read off a SHARED
simulation transcript: the harness testbench prints its verdict line to stdout,
the scorer regexes that line, and the DUT — the thing being measured — writes to
the SAME stdout. So the submission can print the verdict the scorer reads.

Reproduced at head 397b3f25f with two candidates carrying IDENTICAL wrong logic
(`assign out = a | b` where the spec says `a & b`); the second adds only

    initial $display("Mismatches: 0 in 20 samples");

    scorer                                        honest-wrong   forged-wrong
    benchmark/score_iverilog_tb.py (Shape C)      FAIL           PASS
    programs/verilogeval_tier_pipeline.py         FAIL           PASS

The simulation itself reported `Mismatches: 10 in 20 samples` for BOTH. The
honest-wrong control FAILs, so the scorer is not vacuous — it is FORGEABLE,
which is worse: it discriminates correctly right up until someone forges it.

THE RULE
========
A design that prints the scorer's verdict string is not a design that passed —
it is a design that answered the question about the SCORER instead of the
question about the CIRCUIT. So: before scoring a candidate, scan the candidate's
own transcript-writing system tasks. If any text it can emit would satisfy the
scorer's PASS pattern, the candidate is not scoreable on that transcript.

The caller supplies its OWN pass pattern(s) — the same regex it will later run
over the transcript. Nothing about a benchmark, a design, a PDK or a vendor is
encoded here (§4.05 chip-AGNOSTIC): the gate only asks whether the candidate can
produce text that the caller's own recognizer will read as a pass.

WHAT IS FLAGGED (two kinds, both BLOCKING, reported separately)
==============================================================
  forged_pass       a rendering of one of the candidate's own $display/$write/...
                    format strings MATCHES the caller's pass pattern. This is the
                    demonstrated attack; it needs no interpretation.
  unbounded_format  the candidate emits a `%s`-class specifier (%s %m %l %p %v),
                    whose expansion is DUT-controlled data — i.e. the candidate
                    can write ARBITRARY text onto the channel the verdict is read
                    from, so no rendering search can bound what it may print.

Both are BLOCKING because in both cases the transcript no longer attributes the
verdict to the harness. A plain `$display("hello")` — no verdict text, no
unbounded specifier — is NOT flagged: honest debug output stays scoreable.

HOW THE SCAN WORKS (and what it does not see)
=============================================
1. A string-aware lexer walks the candidate once, tracking line comments, block
   comments and string literals with escapes. So a COMMENTED-OUT `$display` is
   not a finding, and — the case a naive comment-strip gets backwards — a `//`
   INSIDE a string literal does not truncate the live call that follows it.
2. Output-task calls are collected with their string-literal arguments, in file
   order. `$display`/`$strobe`/`$monitor`/`$info`/`$warning`/`$error`/`$fatal`
   are newline-terminated; `$write`/`$fwrite` are not. `$fdisplay`/`$fwrite` are
   included because the scorer reads stdout AND stderr, and both are file
   descriptors a design can name.
3. Each format string is RENDERED: every `%…` conversion is replaced by specimen
   values (full cartesian product while the specifier count is small, otherwise a
   bounded one-at-a-time sweep — which is DISCLOSED as a `bounded_search` note,
   never silently narrowed). Every rendering is matched against the pass pattern.
4. The concatenation of every emission, in file order, is rendered and matched
   the same way — so splitting the verdict across several `$write` calls does not
   evade the check.

NOT SEEN (stated, not silently assumed away): a verdict assembled through
`` `include ``/macro text this scanner does not expand; a verdict split ACROSS
the DUT and the harness's own output; a candidate that writes to a file the
scorer later reads. Those need a different instrument, not a wider regex here.

Exit codes (house convention)
    0  CLEAN   — nothing the candidate can print satisfies the pass pattern
    1  FORGERY — at least one blocking finding
    2  NOT CHECKED — usage / unreadable input / no pattern supplied
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Transcript-writing system tasks. The value is True when the task terminates its
# output with a newline (which matters only for the concatenation pass).
OUTPUT_TASKS: Dict[str, bool] = {
    "display": True, "displayb": True, "displayo": True, "displayh": True,
    "write": False, "writeb": False, "writeo": False, "writeh": False,
    "strobe": True, "strobeb": True, "strobeo": True, "strobeh": True,
    "monitor": True, "monitorb": True, "monitoro": True, "monitorh": True,
    "fdisplay": True, "fdisplayb": True, "fdisplayo": True, "fdisplayh": True,
    "fwrite": False, "fwriteb": False, "fwriteo": False, "fwriteh": False,
    "fstrobe": True, "fmonitor": True,
    "info": True, "warning": True, "error": True, "fatal": True,
}

# A `%s`-class conversion expands to DUT-controlled text: the candidate can put
# ANY bytes on the transcript through it, so no bounded rendering search can
# prove it harmless.
_UNBOUNDED_CONV = set("smlpvSMLPV")

# Specimen expansions per conversion letter. Chosen so the PASS direction is
# REACHABLE (a "0" is always among them — a forged pass is almost always a zero
# count), not so the render is faithful to any one simulator's padding.
_SPECIMENS: Dict[str, Tuple[str, ...]] = {
    "d": ("0", "1", "20", "200000"),
    "b": ("0", "1", "1010"),
    "o": ("0", "1", "7"),
    "h": ("0", "1", "f"),
    "x": ("0", "1", "f"),
    "c": ("0", "A"),
    "f": ("0", "0.000000", "1.5"),
    "e": ("0", "0.000000e+00"),
    "g": ("0", "1.5"),
    "t": ("0", "1000"),
    "u": ("0", "1"),
    "z": ("0", "x"),
}
_DEFAULT_SPECIMENS: Tuple[str, ...] = ("0", "1")

# The conversion grammar: '%' flags/width/precision then one letter.
_CONV_RE = re.compile(r"%(?:-?\d*(?:\.\d+)?)([a-zA-Z%])")

# Full cartesian product is used while the specifier count is at or below this;
# above it the search degrades to a one-at-a-time sweep AND says so.
_CARTESIAN_MAX_SPECS = 6
_CARTESIAN_MAX_RENDERS = 8192


class Emission:
    """One transcript-writing call the candidate makes."""

    __slots__ = ("task", "fmt", "line", "newline")

    def __init__(self, task: str, fmt: str, line: int, newline: bool):
        self.task = task
        self.fmt = fmt
        self.line = line
        self.newline = newline

    def as_dict(self) -> dict:
        return {"task": "$" + self.task, "format": self.fmt, "line": self.line}


# --------------------------------------------------------------------------- #
# (1) string-aware lexing
# --------------------------------------------------------------------------- #
def _lex(text: str) -> List[Tuple[str, str, int]]:
    """Split `text` into ('code'|'str', payload, line) segments, dropping
    comments. A `//` or `/*` inside a string literal is TEXT, not a comment —
    getting that backwards is how a comment-stripping scanner blinds itself to
    the live call on the same line."""
    segs: List[Tuple[str, str, int]] = []
    i, n, line = 0, len(text), 1
    buf: List[str] = []
    buf_line = 1

    def flush_code() -> None:
        nonlocal buf, buf_line
        if buf:
            segs.append(("code", "".join(buf), buf_line))
            buf = []
        buf_line = line

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            flush_code()
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and nxt == "*":
            flush_code()
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                if text[i] == "\n":
                    line += 1
                i += 1
            i = min(i + 2, n)
            buf_line = line
            continue
        if c == '"':
            flush_code()
            start_line = line
            i += 1
            lit: List[str] = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    esc = text[i + 1]
                    lit.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(esc, esc))
                    if esc == "\n":
                        line += 1
                    i += 2
                    continue
                if text[i] == "\n":
                    line += 1
                lit.append(text[i])
                i += 1
            i = min(i + 1, n)
            segs.append(("str", "".join(lit), start_line))
            buf_line = line
            continue
        if c == "\n":
            line += 1
        buf.append(c)
        i += 1
    flush_code()
    return segs


_TASK_RE = re.compile(r"\$([A-Za-z_]\w*)")


def emissions(rtl_text: str) -> List[Emission]:
    """Every transcript-writing call in `rtl_text`, in file order, with the
    string literals it passes. A call with no string literal argument (e.g.
    `$display(x)`) contributes an empty format — it can print a value but no
    verdict WORDING, so it can only match a pattern that is pure conversions."""
    out: List[Emission] = []
    active: Optional[str] = None
    active_line = 0
    parts: List[str] = []
    depth = 0
    opened = False

    def close() -> None:
        nonlocal active, parts, depth, opened
        if active is not None:
            out.append(Emission(active, "".join(parts), active_line,
                                OUTPUT_TASKS.get(active, True)))
        active, parts, depth, opened = None, [], 0, False

    for kind, payload, ln in _lex(rtl_text):
        if kind == "str":
            if active is not None:
                parts.append(payload)
            continue
        pos = 0
        while pos < len(payload):
            ch = payload[pos]
            if active is None:
                m = _TASK_RE.search(payload, pos)
                if not m:
                    break
                name = m.group(1).lower()
                if name in OUTPUT_TASKS:
                    # the segment's line is where the CHUNK started; the call may
                    # sit several lines into it.
                    active = name
                    active_line = ln + payload[:m.start()].count("\n")
                    parts, depth, opened = [], 0, False
                pos = m.end()
                continue
            if ch == "(":
                depth += 1
                opened = True
            elif ch == ")":
                depth -= 1
                if opened and depth <= 0:
                    pos += 1
                    close()
                    continue
            elif ch == ";" and depth <= 0:
                pos += 1
                close()
                continue
            pos += 1
    close()
    return out


# --------------------------------------------------------------------------- #
# (2) rendering a format string
# --------------------------------------------------------------------------- #
def conversions(fmt: str) -> List[str]:
    """The conversion letters in `fmt`, in order; `%%` is a literal, not one."""
    return [m.group(1) for m in _CONV_RE.finditer(fmt) if m.group(1) != "%"]


def has_unbounded_conversion(fmt: str) -> bool:
    return any(c in _UNBOUNDED_CONV for c in conversions(fmt))


def renderings(fmt: str) -> Tuple[List[str], bool]:
    """(candidate texts this format can print, bounded_search).

    `bounded_search` is True when the specifier count forced the one-at-a-time
    sweep instead of the full product — the caller DISCLOSES it rather than
    letting a narrowed search read as an exhaustive clean."""
    convs = conversions(fmt)
    if not convs:
        return [fmt.replace("%%", "%")], False
    specimen_sets = [_SPECIMENS.get(c.lower(), _DEFAULT_SPECIMENS) for c in convs]
    total = 1
    for s in specimen_sets:
        total *= len(s)
    bounded = not (len(convs) <= _CARTESIAN_MAX_SPECS and total <= _CARTESIAN_MAX_RENDERS)
    if not bounded:
        combos: Iterable[Sequence[str]] = itertools.product(*specimen_sets)
    else:
        defaults = [s[0] for s in specimen_sets]
        combos = [tuple(defaults)]
        for idx, s in enumerate(specimen_sets):
            for v in s[1:]:
                row = list(defaults)
                row[idx] = v
                combos.append(tuple(row))
    out: List[str] = []
    for combo in combos:
        it = iter(combo)
        out.append(_CONV_RE.sub(
            lambda m: "%" if m.group(1) == "%" else next(it), fmt))
    return out, bounded


# --------------------------------------------------------------------------- #
# (3) the scan
# --------------------------------------------------------------------------- #
def scan(rtl_text: str, pass_patterns: Sequence[str]) -> dict:
    """Findings for `rtl_text` against the caller's own PASS pattern(s).

    Returns {"forged": bool, "findings": [...], "notes": [...], "emissions": N}.
    `forged` True means: do not score this candidate a PASS on a transcript this
    pattern is read from."""
    compiled: List[Tuple[str, "re.Pattern[str]"]] = []
    for p in pass_patterns:
        compiled.append((p, re.compile(p, re.MULTILINE)))
    ems = emissions(rtl_text)
    findings: List[dict] = []
    notes: List[str] = []

    for em in ems:
        if has_unbounded_conversion(em.fmt):
            findings.append({
                "kind": "unbounded_format", "line": em.line, "task": "$" + em.task,
                "format": em.fmt,
                "detail": ("emits a DUT-controlled `%s`-class conversion onto the "
                           "channel the verdict is read from — what it prints "
                           "cannot be bounded"),
            })
            continue
        rends, bounded = renderings(em.fmt)
        if bounded:
            notes.append(f"line {em.line}: bounded_search "
                         f"({len(conversions(em.fmt))} conversions)")
        for src, rx in compiled:
            for r in rends:
                if rx.search(r):
                    findings.append({
                        "kind": "forged_pass", "line": em.line, "task": "$" + em.task,
                        "format": em.fmt, "pattern": src, "rendering": r,
                        "detail": "candidate can print text matching the scorer's "
                                  "own PASS pattern",
                    })
                    break
            else:
                continue
            break

    # the split-across-calls evasion: join every emission in file order.
    if len(ems) > 1 and not any(f["kind"] == "forged_pass" for f in findings):
        joined = "".join(em.fmt + ("\n" if em.newline else "") for em in ems)
        rends, bounded = renderings(joined)
        if bounded:
            notes.append(f"concatenation: bounded_search "
                         f"({len(conversions(joined))} conversions)")
        for src, rx in compiled:
            hit = next((r for r in rends if rx.search(r)), None)
            if hit is not None:
                findings.append({
                    "kind": "forged_pass", "line": ems[0].line, "task": "concatenated",
                    "format": joined, "pattern": src, "rendering": hit,
                    "detail": "the candidate's emissions CONCATENATE into text "
                              "matching the scorer's own PASS pattern",
                })
                break

    return {"forged": bool(findings), "findings": findings, "notes": notes,
            "emissions": len(ems)}


def forgery_reason(rtl_text: str, pass_patterns: Sequence[str]) -> Optional[str]:
    """One-line reason iff `rtl_text` must not be scored against a transcript
    these patterns are read from; None when the candidate is scoreable.

    This is the call site every scorer uses — it keeps the verdict wording in one
    place so the runner and the gate can never disagree."""
    if not pass_patterns:
        return None
    res = scan(rtl_text or "", pass_patterns)
    if not res["forged"]:
        return None
    f = res["findings"][0]
    where = f"line {f['line']}" if f["task"] != "concatenated" else "concatenated emissions"
    if f["kind"] == "forged_pass":
        return (f"verdict forgery: {f['task']} at {where} can print "
                f"{f['rendering']!r}, which the scorer reads as its PASS verdict")
    return (f"verdict forgery: {f['task']} at {where} writes a DUT-controlled "
            f"`%s`-class conversion onto the scored transcript "
            f"({f['format']!r}) — the verdict is no longer attributable")


# --------------------------------------------------------------------------- #
# (4) CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rtl", required=True, help="candidate RTL file to scan")
    ap.add_argument("--pattern", action="append", default=[],
                    help="a PASS regex the scorer will run over the transcript "
                         "(repeatable; at least one required)")
    ap.add_argument("--json", dest="json_out", help="write the findings here")
    a = ap.parse_args(argv)

    if not a.pattern:
        print("NOT CHECKED: no --pattern given; a forgery check without the "
              "scorer's own pass pattern would certify nothing", file=sys.stderr)
        return 2
    try:
        text = Path(a.rtl).read_text(errors="replace")
    except OSError as e:
        print(f"NOT CHECKED: cannot read {a.rtl}: {e}", file=sys.stderr)
        return 2
    try:
        res = scan(text, a.pattern)
    except re.error as e:
        print(f"NOT CHECKED: bad --pattern regex: {e}", file=sys.stderr)
        return 2

    res["rtl"] = str(a.rtl)
    res["patterns"] = list(a.pattern)
    if a.json_out:
        try:
            Path(a.json_out).write_text(json.dumps(res, indent=2) + "\n")
        except OSError as e:
            print(f"NOT CHECKED: cannot write {a.json_out}: {e}", file=sys.stderr)
            return 2
    for note in res["notes"]:
        print(f"[NOTE] {note}")
    if not res["forged"]:
        print(f"[PASS] {a.rtl}: {res['emissions']} transcript emission(s), none "
              f"can satisfy the scorer's pass pattern")
        return 0
    for f in res["findings"]:
        print(f"[FAIL] {f['kind']} at line {f['line']} ({f['task']}): {f['detail']}")
        print(f"       format={f['format']!r}")
        if "rendering" in f:
            print(f"       renders as {f['rendering']!r} vs pattern {f['pattern']!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
