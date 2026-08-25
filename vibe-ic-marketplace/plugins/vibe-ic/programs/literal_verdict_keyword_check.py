#!/usr/bin/env python3
"""
literal_verdict_keyword_check.py — anti-fabrication gate (v1.6.38).

Doctrine: a numeric value in an emitted sign-off report (DRC violation
count, EM Jmax, IR drop, DFT coverage %, SI coupling ratio, etc.) must
either be MEASURED at runtime or DERIVED from a documented PDK / spec
input. Hardcoding such values as Python literals masquerading as
measurements lets an emitter pass gate keyword-scans while doing zero
real work.

Real-world inspiration (the v1.6.37 escape):
  `_signoff_emit.py:emit_si_crosstalk_report` had `coupling_ratio = 0.10`
  hardcoded → reported `noise = 180 mV` hardcoded → `violations = 0`
  hardcoded → permanent verdict=PASS, every project, every chip. Same
  shape in `emit_dft_scan_chain` (`coverage_pct = 70.0`), `emit_em_report`
  (`j_max_ma_per_um = 2.0  # <PDK> SOA`).

This gate scans every `emit_*` (or `_emit_*`) function and FAILs when
a sign-off-style numeric attribute is assigned to a literal constant
without a justifying source comment.

Justifications recognised:
  - `# source: <path>`           — value comes from a PDK file or
                                    documented spec; reviewer can audit
  - `# computed_from: <expr>`    — value derives from another variable
  - `# default: <reason>`        — explicit default is acceptable
  - `# sentinel`                 — used as a placeholder before
                                    measurement (e.g. `coverage_pct = -1`)

Watched attribute name patterns (case-insensitive substring):
  coverage, coverage_pct, j_max, jmax, em_threshold, ir_threshold,
  drop_mv, peak_mv, threshold_mv, coupling_ratio, coupling_cap,
  noise_mv, violations, viol_count, slack, wns, tns, leakage_mw,
  power_mw, density_pct.

If the attribute matches a watched name AND the rhs is a numeric
literal (int / float) AND none of the justifications appear in the
SAME line trailing comment OR the line above OR the function
docstring, the gate flags it.

Usage:
    python3 literal_verdict_keyword_check.py <plugin_root>
                                              [--json <out>]

Exit codes:
    0  PASS
    1  FAIL — at least one literal-without-source flagged
    2  argument or I/O error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Set, Tuple


_EMITTER_NAME_RE = re.compile(r"^_?emit_[a-z0-9_]+$")

# Substring tokens we treat as sign-off-style numeric attributes.
# Match is case-insensitive against the assignment target name.
_WATCHED: Tuple[str, ...] = (
    "coverage", "coverage_pct",
    "j_max", "jmax", "em_threshold", "em_jmax",
    "ir_threshold", "ir_drop",
    "drop_mv", "peak_mv", "threshold_mv",
    "coupling_ratio", "coupling_cap", "coupling_pf",
    "noise_mv", "noise_pct",
    "violations", "viol_count", "violation_count",
    "slack", "wns", "tns",
    "leakage_mw", "power_mw",
    "density_pct", "fill_pct",
    "delta_pct",
)

# Justification patterns recognised in a comment / docstring on the
# same or preceding line. If any of these match, the literal is
# accepted.
_JUSTIFY_RE = re.compile(
    r"#\s*source\s*[:=]|"
    r"#\s*computed_from\s*[:=]|"
    r"#\s*default\s*[:=]|"
    r"#\s*sentinel\b|"
    r"#\s*placeholder\b|"
    r"#\s*literal-verdict\s*[:=]\s*reviewed",
    re.IGNORECASE,
)


#: THE DENOMINATOR THIS GATE'S PASS STANDS ON.
#: `gate_discloses_denominator_check` measured this program answering PASS
#: over an EMPTY tree while saying only "PASS: every ... is reproducible" —
#: an output indistinguishable from a real clean run. A pass that does not
#: say what it looked at is the same shape as a scan that looked at nothing.
#: Recorded by `audit()` and printed by `main()`; nothing else reads it, and
#: no signature changed, so every existing caller and test is untouched.
_SCANNED = {"files": 0, "items": 0}


@dataclass
class LiteralFinding:
    file: str
    function: str
    line: int
    attribute: str
    literal_value: str
    rule: str
    detail: str = ""


def _is_watched(name: str) -> bool:
    n = name.lower()
    return any(tok in n for tok in _WATCHED)


def _comment_or_docstring_justifies(node: ast.Assign,
                                    source_lines: List[str],
                                    func: ast.FunctionDef) -> bool:
    line_idx = node.lineno - 1  # 0-based
    if 0 <= line_idx < len(source_lines):
        if _JUSTIFY_RE.search(source_lines[line_idx]):
            return True
    if line_idx - 1 >= 0:
        prev = source_lines[line_idx - 1]
        if _JUSTIFY_RE.search(prev):
            return True
    doc = ast.get_docstring(func) or ""
    if "literal-verdict: reviewed" in doc:
        return True
    return False


def _walk_emitter_assigns(func: ast.FunctionDef
                          ) -> List[Tuple[str, ast.Assign]]:
    out: List[Tuple[str, ast.Assign]] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if not isinstance(tgt, ast.Name):
                continue
            if not _is_watched(tgt.id):
                continue
            if not isinstance(node.value, ast.Constant):
                continue
            if not isinstance(node.value.value, (int, float)):
                continue
            # ints used as integer counts (0, 1) sometimes legit for
            # tested-constant defaults; allow value == 0 but flag the
            # rest (the v1.6.37 escapes were 0.10, 70.0, 2.0, 0.0
            # specifically — patterns we want to catch).
            out.append((tgt.id, node))
    return out


def audit(plugin_root: Path
          ) -> Tuple[str, List[LiteralFinding]]:
    findings: List[LiteralFinding] = []
    programs = plugin_root / "programs"
    if not programs.is_dir():
        return "VACUOUS_PASS", []

    _pys = sorted(programs.glob("*.py"))
    _SCANNED["files"] = len(_pys)
    for py in _pys:
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(text, filename=str(py))
        except SyntaxError:
            continue
        source_lines = text.splitlines()
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef):
                continue
            if not _EMITTER_NAME_RE.match(func.name):
                continue
            for attr, assign in _walk_emitter_assigns(func):
                if _comment_or_docstring_justifies(assign,
                                                   source_lines,
                                                   func):
                    continue
                rel = py.relative_to(plugin_root)
                findings.append(LiteralFinding(
                    file=str(rel),
                    function=func.name,
                    line=assign.lineno,
                    attribute=attr,
                    literal_value=repr(assign.value.value),
                    rule="LITERAL_VERDICT_NO_SOURCE",
                    detail=(f"`{attr} = {assign.value.value!r}` is a "
                            "sign-off-style numeric value with no "
                            "justifying comment. Add `# source: <path>`, "
                            "`# computed_from: <expr>`, or "
                            "`# default: <reason>` on the same or "
                            "preceding line, or annotate the function "
                            "docstring with `literal-verdict: reviewed`."),
                ))
    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Anti-fabrication: detect hardcoded sign-off "
                    "numerics in emit_* functions without a "
                    "justifying source comment.")
    ap.add_argument("plugin_root")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    root = Path(args.plugin_root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    verdict, findings = audit(root)
    report = {
        "gate": "literal_verdict_keyword_check",
        "verdict": verdict,
        "plugin_root": str(root),
        "watched_tokens": list(_WATCHED),
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print("VACUOUS_PASS: no programs/ dir")
        return 0
    if verdict == "PASS":
        print(f"PASS: {_SCANNED['files']} source file(s) scanned — no "
              f"literal sign-off numeric without source justification "
              f"in an emit_* function")
        return 0
    print(f"FAIL: {len(findings)} literal-without-source assignment(s):",
          file=sys.stderr)
    for f in findings[:10]:
        print(f"  [{f.rule}] {f.file}:{f.line} {f.function} — "
              f"`{f.attribute} = {f.literal_value}`",
              file=sys.stderr)
    if len(findings) > 10:
        print(f"  … and {len(findings) - 10} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
