#!/usr/bin/env python3
"""edge_history_reset_phantom_check.py — a history register reset to a constant
fabricates an edge the moment reset releases.

An edge detector keeps the previous value of a signal and compares:

    always @(posedge clk)
      if (!rst_n) prev <= 1'b0;     // <-- the defect
      else        prev <= sig;
    wire rise = sig & ~prev;

If `sig` is already high when reset releases, `prev` holds the constant 0 and
`rise` fires on a transition that never happened. Downstream that phantom arms
counters, starts intervals and produces verdicts about a measurement window that
does not exist -- and it is invisible in any test whose stimulus happens to
start low.

The fix the message names is `prev <= sig` in the reset arm: the history of a
signal at reset is that signal, not zero.

ADVISORY ONLY, AND THE MEASUREMENT SAYS WHY. Swept over this corpus the
signature fires on 7 of 57 genuinely-failing blind drafts and on 9 of 302
officially-PASSING deliveries. I tried to narrow it and my own data refused the
narrowing: `edge_detector_0001` (passes) and `clock_jitter_detection_module`
(fails) are structurally IDENTICAL -- history register reset to a constant,
source is an input port, edge term present. What separates them is whether the
source can be HIGH at the moment reset releases, and that lives in the stimulus,
not in the RTL this program is handed.

So every finding is severity WARN and this check never blocks an emit. It tells
an author where to look; deciding is theirs. A blocker here would refuse correct
synchronisers and edge detectors, which is worse than the defect it catches.

WHY THIS PROGRAM EXISTS AT ALL. The rule was distilled once from a blind CVDP
failure, written up with this exact specification, and never shipped. The same
design failed again in the next clean-room round by the identical mechanism,
byte for byte. Prose in a record is not enforcement; this file is.

Exit: 0 always for findings (advisory); 2 = CANNOT CHECK (no RTL). Use --strict
to exit 1 on a finding when a caller genuinely wants a hard stop.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files

_LINE_COMMENT = re.compile(r"//.*?$", re.M)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)

# `prev <= sig;` — a plain register-the-signal assignment, nothing else.
_HISTORY_ASSIGN = re.compile(
    r"(?<![\w$])([A-Za-z_]\w*)\s*<=\s*([A-Za-z_]\w*)\s*;")

# Any edge term over the pair, in the spellings RTL actually uses.
def _edge_terms(sig: str, prev: str) -> List[re.Pattern]:
    s, p = re.escape(sig), re.escape(prev)
    return [re.compile(pat) for pat in (
        rf"{s}\s*&&?\s*[!~]\s*{p}\b",       # sig && !prev   /  sig & ~prev
        rf"[!~]\s*{p}\s*&&?\s*{s}\b",       # !prev && sig
        rf"{s}\s*\^\s*{p}\b",               # sig ^ prev
        rf"{p}\s*\^\s*{s}\b",
        rf"[!~]\s*{s}\s*&&?\s*{p}\b",       # falling edge: !sig && prev
        rf"{p}\s*&&?\s*[!~]\s*{s}\b",
    )]


def strip_comments(text: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub(" ", text))


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: Optional[int] = None
    symbol: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _reset_blocks(text: str) -> List[str]:
    """The bodies of reset arms — `if (!rst) ... ` / `if (rst) ...`.

    Deliberately textual and generous: a reset arm this misses simply produces
    no finding, which is the safe direction for a check that must not cry wolf.
    """
    out = []
    for m in re.finditer(r"\bif\s*\(\s*([!~]?\s*[A-Za-z_]\w*)\s*\)", text):
        cond = m.group(1).replace(" ", "")
        bare = cond.lstrip("!~").lower()
        if not re.search(r"rst|reset|clr|clear", bare):
            continue
        body = text[m.end():m.end() + 900]
        cut = re.search(r"\belse\b", body)
        out.append(body[:cut.start()] if cut else body)
    return out


def check_text(code: str):
    """(findings, status) — the interface cvdp_gate's structural gates consume."""
    text = strip_comments(code or "")
    findings: List[Finding] = []
    if not text.strip():
        return findings, "SKIP"

    resets = _reset_blocks(text)
    if not resets:
        return findings, "PASS"

    seen = set()
    for m in _HISTORY_ASSIGN.finditer(text):
        prev, sig = m.group(1), m.group(2)
        if prev == sig or prev in seen:
            continue
        # It is only a HISTORY register if an edge term over the pair exists.
        if not any(p.search(text) for p in _edge_terms(sig, prev)):
            continue
        # ...and only a DEFECT if a reset arm drives it to a constant.
        const = re.compile(
            rf"(?<![\w$]){re.escape(prev)}\s*<=\s*("
            rf"\d*'\s*[bhdoBHDO]?[0-9a-fA-FxXzZ_]+|\d+)\s*;")
        for rb in resets:
            hit = const.search(rb)
            if not hit:
                continue
            seen.add(prev)
            findings.append(Finding(
                rule="EDGE_HISTORY_RESET_TO_CONSTANT",
                severity="WARN",
                symbol=prev,
                line=text.count("\n", 0, m.start()) + 1,
                message=(
                    f"'{prev}' holds the previous value of '{sig}' (an edge term "
                    f"over the pair exists) but its reset arm assigns the constant "
                    f"{hit.group(1)}. If '{sig}' is high when reset releases, the "
                    f"edge fires on a transition that never happened, and any "
                    f"counter or interval it arms measures a window that does not "
                    f"exist. Reset it as '{prev} <= {sig};' — the history of a "
                    f"signal at reset is that signal — and discard the first "
                    f"measured interval after reset before any threshold verdict."),
            ))
            break
    return findings, ("FAIL" if findings else "PASS")


def audit(path: str) -> AuditResult:
    root = Path(path).resolve()
    res = AuditResult(program="edge_history_reset_phantom_check", passed=True)
    if not root.exists():
        res.passed = False
        res.summary = {"files_scanned": 0, "status": "CANNOT_CHECK"}
        res.findings.append(Finding("PATH_MISSING", "ERROR", f"not found: {path}"))
        return res
    files = [root] if root.is_file() else list(rtl_source_files(root))
    if not files:
        res.summary = {"files_scanned": 0, "status": "CANNOT_CHECK"}
        return res
    base = root if root.is_dir() else root.parent
    for f in files:
        fs, _ = check_text(f.read_text(errors="replace"))
        for x in fs:
            x.file = str(f.relative_to(base)) if str(f).startswith(str(base)) else str(f)
        res.findings.extend(fs)
    res.passed = not res.findings
    res.summary = {"files_scanned": len(files),
                   "violations": len(res.findings), "status": "CHECKED"}
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on a finding (default: advisory, exit 0)")
    a = ap.parse_args()
    r = audit(a.path)
    if a.json:
        print(json.dumps(asdict(r), indent=2))
    else:
        for f in r.findings:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            print(f"[{f.severity}] {f.rule} ({loc}): {f.message}")
        print(f"\n{'PASS' if r.passed else 'FAIL'} — {r.summary}")
    if r.summary.get("status") == "CANNOT_CHECK":
        return 2
    # Advisory by default: see the module docstring for the measurement that
    # forbids blocking. `_structural_finding_gate` blocks only on ERROR
    # findings, and every finding here is WARN, so wiring this into the gate
    # surfaces it without ever refusing an emit.
    return 1 if (a.strict and not r.passed) else 0


if __name__ == "__main__":
    sys.exit(main())
