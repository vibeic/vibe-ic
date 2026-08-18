#!/usr/bin/env python3
"""tb_vcs_only_construct_detect.py — detect VCS/Xcelium-only
SystemVerilog testbench constructs that iverilog cannot run.

Extracted from open-benchmark-methodology § 4 Category D
(tool-substitution gap). When a benchmark mandates Synopsys VCS or
Cadence Xcelium and we substitute iverilog, a failing TB may be
failing purely because it uses a commercial-only construct iverilog
rejects — that is a Category-D tool-gap, not an agent-fixable RTL
bug. This program scans the TB for the known iverilog-rejecting
constructs and reports the offending line(s) as evidence, so the
triage can auto-classify Category-D instead of burning close-loop
compute on it.

FORK-FIXABLE, NOT a terminal FLOOR (v1.3.43 doctrine update): because
we FORK the EDA tools (`vibeic/{iverilog,verilator,yosys,OpenROAD,…}`,
shipped as `vibeic-eda`), a Category-D hit is an ENGINEERING BACKLOG
ITEM against the fork — route it to `tools/vibeic-eda/FIX_STATUS.md`,
NOT a permanent ceiling. Detecting the construct does NOT by itself
prove the case is unwinnable: run the § 4.1 floor-proof (build+run the
GOLDEN under a tool that supports the feature — Verilator `--timing`,
forked iverilog). If the golden PASSES → confirmed genuine tool-gap →
fork the capability (many are already closed, e.g. `break;`/`continue;`
in the forked iverilog 14-devel). If the golden ALSO fails there → it
was NEVER a pure tool-gap; re-triage as a dataset/RTL floor. NEVER
patch a tool to "pass benchmark X" — fix the CAPABILITY, not the case.

Detected constructs (the ones observed to reject under iverilog 12
in the 2026-05-28 RTLLM sweep, e.g. ring_counter / asyn_fifo):
  * array-aggregate / assignment-pattern init   `'{ ... }`
  * `break;` / `continue;` inside SV loops (iverilog -g2012 gap)
  * `std::randomize` / `.randomize()` constrained-random
  * `$urandom_range(` system task
  * `unique`/`priority` case (some iverilog versions reject)
  * `wait_order` / `fork ... join_none` advanced fork
  * SV `string` queue ops `.push_back(` / `.pop_front(`

Usage
=====
  python3 tb_vcs_only_construct_detect.py <testbench.v|.sv> [--json out.json]

Honest failure / semantics
==========================
  * FAIL (rc 1) means "VCS-only construct(s) FOUND" → the TB is a
    Category-D tool-gap; the report lists the construct + line and
    marks `disposition = FORK-FIXABLE` with a `fork_route` to
    FIX_STATUS.md. (FAIL here is the *detector firing*, i.e. evidence
    the case fails under our current substitution — the next step is
    the § 4.1 floor-proof + fork the capability, NOT shelve a floor.)
  * PASS (rc 0) means "no known VCS-only construct found" → the TB
    is NOT a Category-D tool-gap; a failing run must be triaged
    elsewhere (real RTL bug / spec-ambiguity / etc.).
  * Missing / unreadable TB → rc 2 (usage error): cannot scan a file
    that isn't there; never a vacuous PASS.

Exit codes
==========
  0 — PASS (no VCS-only construct detected)
  1 — FAIL (VCS-only construct detected — Category-D floor evidence)
  2 — usage error (missing/unreadable input)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# (construct id, human label, compiled regex). Patterns are line-oriented
# and avoid common false positives (e.g. `'{` requires the apostrophe-brace
# assignment-pattern form, not a plain `{`).
PATTERNS = [
    ("assignment_pattern",
     "array-aggregate / assignment-pattern init ('{...})",
     re.compile(r"'\s*\{")),
    ("break_stmt",
     "break; statement",
     re.compile(r"\bbreak\s*;")),
    ("continue_stmt",
     "continue; statement",
     re.compile(r"\bcontinue\s*;")),
    ("std_randomize",
     "std::randomize / .randomize() constrained-random",
     re.compile(r"(std\s*::\s*randomize|\.\s*randomize\s*\()")),
    ("urandom_range",
     "$urandom_range() system task",
     re.compile(r"\$urandom_range\s*\(")),
    ("unique_priority_case",
     "unique/priority case",
     re.compile(r"\b(unique|priority)\s+case\b")),
    ("advanced_fork",
     "fork...join_none / wait_order advanced fork",
     re.compile(r"\b(join_none|join_any|wait_order)\b")),
    ("queue_ops",
     "SV queue ops (.push_back/.pop_front)",
     re.compile(r"\.\s*(push_back|pop_front|push_front|pop_back)\s*\(")),
]

# Strip line comments and block comments before matching (a construct
# mentioned in a comment is not actually compiled).
_LINE_COMMENT = re.compile(r"//.*$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT.sub("", text)
    return "\n".join(_LINE_COMMENT.sub("", ln) for ln in text.splitlines())


def scan_text(text: str) -> list[dict]:
    """Return a list of {construct, label, line, snippet} hits."""
    clean = _strip_comments(text)
    hits: list[dict] = []
    for i, line in enumerate(clean.splitlines(), start=1):
        for cid, label, rx in PATTERNS:
            if rx.search(line):
                hits.append({"construct": cid, "label": label,
                             "line": i, "snippet": line.strip()[:120]})
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tb", help="path to the testbench .v / .sv")
    ap.add_argument("--json", help="write JSON report to this path")
    a = ap.parse_args(argv)

    p = Path(a.tb)
    if not p.is_file():
        print(f"usage error: testbench not found: {p}", file=sys.stderr)
        return 2
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:  # pragma: no cover - unreadable file
        print(f"usage error: cannot read {p}: {e}", file=sys.stderr)
        return 2

    hits = scan_text(text)
    report = {"program": "tb_vcs_only_construct_detect",
              "tb": str(p), "hits": hits}
    if hits:
        report["verdict"] = "FAIL"
        report["category"] = "D"
        report["reason"] = "vcs_only_construct_detected"
        # v1.3.43: Category-D is FORK-FIXABLE (route to the vibeic-eda fork
        # backlog), NOT a terminal floor. Detection is evidence for the § 4.1
        # floor-proof, not a verdict of unwinnable.
        report["disposition"] = "FORK-FIXABLE"
        report["fork_route"] = "tools/vibeic-eda/FIX_STATUS.md"
        report["floor_proof_required"] = (
            "run the GOLDEN under a tool that supports the feature "
            "(Verilator --timing / forked iverilog); PASS => genuine tool-gap "
            "=> fork the capability; golden ALSO fails => re-triage dataset/RTL")
        _emit(a, report)
        for h in hits:
            print(f"CATEGORY-D (FORK-FIXABLE, route to FIX_STATUS.md): "
                  f"{h['label']} at line {h['line']}: {h['snippet']}",
                  file=sys.stderr)
        return 1
    report["verdict"] = "PASS"
    _emit(a, report)
    print(f"PASS: no VCS/Xcelium-only construct found in {p.name}")
    return 0


def _emit(a, report: dict) -> None:
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
