#!/usr/bin/env python3
"""harness_verdict_forgery_gate.py — refuse to score a submission that prints the
scorer's own verdict string.

WHY (vibe-ic#1745, measured on an upstream harness we run through):
    The scoring harness decides PASS by matching a regex against the SIMULATION's
    stdout, and the device under test SHARES that stdout with the testbench. So
    the thing being measured can emit the text the instrument reads. Reproduced
    with two submissions carrying IDENTICAL WRONG LOGIC: the second added one
    line that printed the harness's own pass sentence, and the pair scored 50%
    on a problem answered wrongly twice — while the simulator reported a nonzero
    mismatch count for BOTH.

    The honest-wrong control FAILs, so the check is not vacuous. It is FORGEABLE,
    which is worse: it discriminates correctly right up until someone forges it.

WHAT THIS GATE DOES:
    Scan the SUBMITTED RTL, before it is compiled or run, for output statements
    that can put the harness's verdict vocabulary onto the verdict channel. A
    design that prints the scorer's verdict string answered a question about the
    scorer, not a question about the circuit, so its simulation output is not
    evidence about the circuit and must not be scored as if it were.

    The verdict vocabulary is DERIVED from the caller's own `pass_regex` /
    `fail_regex` — the exact strings that scorer greps for — so there is no
    second list of magic words to keep in sync with the registry, and the gate
    is benchmark-agnostic by construction.

POLARITY (deliberate, and asymmetric):
    * a PASS-token emission is BLOCKING: it is the only direction that can
      INFLATE a verdict.
    * a FAIL-token emission is ADVISORY only: printing the failure sentence can
      only cost the submitter its own verdict, so blocking on it would add
      false-reject risk while removing no forgery.

WHAT IT DOES NOT CLAIM:
    Text assembled at run time — a verdict string built character-by-character
    into a register, or produced by an included file this scan never sees — is
    NOT DETECTED by a static scan and is not claimed to be. This gate closes the
    forgery that was measured; it is not a proof of unforgeability. The durable
    fix upstream is a verdict channel the DUT cannot write to.

chip-AGNOSTIC: every decision keys on the caller's regex and on generic Verilog /
SystemVerilog output-task grammar. No design name, benchmark name, or problem id
appears anywhere in this file.

CLI
    python3 harness_verdict_forgery_gate.py --rtl FILE --pass-regex RE [--fail-regex RE]
      rc 0  clean          — nothing on the verdict channel, safe to score
      rc 1  FORGERY        — a pass-token emission was found; do NOT score
      rc 2  NOT CHECKED    — the file could not be read (never reported as clean)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

# Verdict kinds. NOT_CHECKED is distinct from CLEAN on purpose: a scan that
# could not run is not a scan that found nothing (vibe-ic#1266 defect class).
CLEAN = "CLEAN"
FORGERY = "FORGERY"
NOT_CHECKED = "NOT_CHECKED"

# Every construct that can put text on the simulation's stdout/stderr — the same
# stream the scorer's regex is matched against. $f* variants are included: a file
# descriptor of 1/2 (or the STDOUT/STDERR mcd constants) writes to that stream.
_OUTPUT_TASKS = (
    "display", "displayb", "displayo", "displayh",
    "write", "writeb", "writeo", "writeh",
    "strobe", "strobeb", "strobeo", "strobeh",
    "monitor", "monitorb", "monitoro", "monitorh",
    "fdisplay", "fdisplayb", "fdisplayo", "fdisplayh",
    "fwrite", "fwriteb", "fwriteo", "fwriteh",
    "fstrobe", "fstrobeb", "fstrobeo", "fstrobeh",
    "fmonitor", "fmonitorb", "fmonitoro", "fmonitorh",
    "info", "warning", "error", "fatal",
)
_TASK_RE = re.compile(r"\$(" + "|".join(sorted(_OUTPUT_TASKS, key=len, reverse=True))
                      + r")\b\s*\(")

# Comments carry no output, so they are masked before the scan (offset-preserving
# so reported line numbers stay true to the submitted file).
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)

# A Verilog format specifier: %b %0d %8h %s %m %t %% …
_FMT_RE = re.compile(r"%[-+ 0#]*\d*(?:\.\d+)?[bBoOdDhHxXcCsSvVmMtTeEfFgGuUlLpP%]")

_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"')

_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "'": "'"}


def _mask_comments(text: str) -> str:
    """Blank out comments, preserving every byte offset (and every newline)."""
    def blank(m: "re.Match") -> str:
        return "".join(c if c == "\n" else " " for c in m.group(0))
    return _COMMENT_RE.sub(blank, text)


def _unescape(lit: str) -> str:
    """Turn a Verilog string literal (with quotes) into the text it prints."""
    body, out, i = lit[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            out.append(_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _call_args(masked: str, open_paren: int) -> str:
    """Text of the argument list whose '(' is at `open_paren`, paren-balanced."""
    depth, i, n = 0, open_paren, len(masked)
    while i < n:
        if masked[i] == "(":
            depth += 1
        elif masked[i] == ")":
            depth -= 1
            if depth == 0:
                return masked[open_paren + 1:i]
        i += 1
    return masked[open_paren + 1:]      # unbalanced source: scan what there is


def verdict_anchors(pattern: str, min_len: int = 2) -> List[str]:
    """The LITERAL fragments a regex requires, in order.

    `Mismatches:\\s*0\\s+in\\s+\\d+\\s+samples` -> ['Mismatches:', 'in', 'samples'].

    These are what a forger has to print, and — unlike the regex itself — they
    survive the format specifiers a `$display("… %0d …")` splices in. Fragments
    shorter than `min_len` are dropped: a one-character anchor matches nearly any
    text and would turn the ordered-anchor rule into a false-positive generator.
    """
    frags, buf, i, n = [], [], 0, len(pattern)
    quantifier = "*+?{"
    while i < n:
        c = pattern[i]
        if c == "\\" and i + 1 < n:
            nxt = pattern[i + 1]
            if nxt.isalnum():           # a class such as \s \d \w — not a literal
                buf, i = _flush(frags, buf, min_len), i + 2
                continue
            buf.append(nxt)             # an escaped literal such as \. or \+
            i += 2
            continue
        if c in "[](){}|^$.*+?":
            buf = _flush(frags, buf, min_len)
            i += 1
            continue
        # a literal char, unless the NEXT char makes it optional/repeatable
        if i + 1 < n and pattern[i + 1] in quantifier:
            buf = _flush(frags, buf, min_len)
            i += 1
            continue
        buf.append(c)
        i += 1
    _flush(frags, buf, min_len)
    return [f.strip() for f in frags if f.strip()]


def _flush(frags: List[str], buf: List[str], min_len: int) -> List[str]:
    frag = "".join(buf)
    if len(frag.strip()) >= min_len:
        frags.append(frag)
    return []


def _anchors_in_order(text: str, anchors: Sequence[str]) -> bool:
    """True iff every anchor occurs in `text`, in the anchors' own order."""
    if not anchors:
        return False
    pos = 0
    for a in anchors:
        j = text.find(a, pos)
        if j < 0:
            return False
        pos = j + len(a)
    return True


def _emitted_texts(masked: str) -> List[tuple]:
    """[(offset, [literal, …], joined)] — one entry per output-task call.

    `joined` is the call's literals concatenated in source order, so a verdict
    string split across several literals in one call is still seen whole.
    """
    out = []
    for m in _TASK_RE.finditer(masked):
        args = _call_args(masked, m.end() - 1)
        lits = [_unescape(s) for s in _STRING_RE.findall(args)]
        if lits:
            out.append((m.start(), lits, "".join(lits)))
    return out


def scan_rtl(rtl_text: str, pass_regex: str,
             fail_regex: Optional[str] = None) -> List[dict]:
    """Findings for one submission. `blocking` marks the inflating direction."""
    masked = _mask_comments(rtl_text or "")
    calls = _emitted_texts(masked)
    findings: List[dict] = []
    channels = [("pass", pass_regex, True)]
    if fail_regex:
        channels.append(("fail", fail_regex, False))
    for channel, pattern, blocking in channels:
        try:
            rx = re.compile(pattern)
        except re.error:
            continue
        anchors = verdict_anchors(pattern)
        for offset, lits, joined in calls:
            line = masked.count("\n", 0, offset) + 1
            for candidate in list(dict.fromkeys(lits + [joined])):
                kind = None
                if rx.search(candidate):
                    kind = "verdict_string_literal"
                elif _FMT_RE.search(candidate) and _anchors_in_order(
                        _FMT_RE.sub("\x00", candidate), anchors):
                    kind = "verdict_string_format"
                elif _anchors_in_order(candidate, anchors):
                    kind = "verdict_anchors_in_order"
                if kind:
                    findings.append({"channel": channel, "kind": kind,
                                     "line": line, "blocking": blocking,
                                     "text": candidate[:200]})
                    break
    return findings


def gate(rtl_text: str, pass_regex: str,
         fail_regex: Optional[str] = None) -> dict:
    """{verdict, blocking, findings, reason} for an in-memory submission."""
    findings = scan_rtl(rtl_text, pass_regex, fail_regex)
    blocking = [f for f in findings if f["blocking"]]
    if blocking:
        first = blocking[0]
        reason = ("harness_verdict_forgery — the submission prints the scorer's "
                  f"own PASS verdict text at line {first['line']} "
                  f"({first['kind']}): {first['text']!r}. Its simulation output "
                  "is not evidence about the circuit; the run is NOT scored.")
    else:
        reason = ""
    return {"verdict": FORGERY if blocking else CLEAN,
            "blocking": blocking, "findings": findings, "reason": reason}


def gate_file(path, pass_regex: str, fail_regex: Optional[str] = None) -> dict:
    """Same as `gate`, reading the submission from disk.

    An unreadable file is NOT_CHECKED, never CLEAN: a scan that could not look
    has not looked.
    """
    try:
        text = Path(path).read_text(errors="ignore")
    except OSError as exc:
        return {"verdict": NOT_CHECKED, "blocking": [], "findings": [],
                "reason": f"NOT CHECKED — cannot read {path}: {exc}"}
    res = gate(text, pass_regex, fail_regex)
    res["path"] = str(path)
    return res


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rtl", required=True, help="submitted RTL file to scan")
    ap.add_argument("--pass-regex", required=True,
                    help="the regex the scorer matches for PASS")
    ap.add_argument("--fail-regex", default=None,
                    help="the regex the scorer matches for FAIL (advisory)")
    ap.add_argument("--json", action="store_true", help="emit the result as JSON")
    a = ap.parse_args(list(argv) if argv is not None else None)
    res = gate_file(a.rtl, a.pass_regex, a.fail_regex)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"{res['verdict']}  {a.rtl}")
        for f in res["findings"]:
            mark = "BLOCKING" if f["blocking"] else "advisory"
            print(f"  [{mark}] line {f['line']}  {f['channel']}-token "
                  f"{f['kind']}: {f['text']!r}")
        if res["reason"]:
            print("  " + res["reason"])
    return {CLEAN: 0, FORGERY: 1, NOT_CHECKED: 2}[res["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
