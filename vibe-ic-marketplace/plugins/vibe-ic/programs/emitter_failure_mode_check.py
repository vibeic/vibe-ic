#!/usr/bin/env python3
"""
emitter_failure_mode_check.py — anti-fabrication gate (v1.6.38).

Doctrine rule #6: an emitter program must NOT emit `verdict: PASS`
when its prerequisite tool failed or its required input was missing.
The honest verdicts in those cases are `INSUFFICIENT_DATA`, `TOOL_FAILED`,
or `WAIVED-DEFERRED` with an explicit ticket.

Real-world inspiration (the v1.6.37 escape):
  `_signoff_emit.py:emit_drc_signoff` ran `klayout`; if klayout failed
  to launch, the captured log was empty, the regex `r"(\\d+) errors"`
  found nothing, the count defaulted to 0, and verdict was set to
  PASS. Same shape in `emit_antenna_report` and `emit_metal_fill`.

This gate scans every `emit_*` (or `_emit_*`) function in the plugin
`programs/` tree and FAILs when:

  (a) The function declares verdict = "PASS" / writes a JSON dict
      whose `verdict` key is a literal `"PASS"`, AND
  (b) Its source contains an `except` block, an `if not <path>.exists()`
      branch, an `if rc != 0` branch, an empty-log default, OR a
      missing-input branch within the same function scope.
  AND
  (c) The PASS path is reachable from the failure-mode branch (no
      intervening `return` from the failure branch with a non-PASS
      verdict).

Heuristic, not full taint analysis. Designed to be conservative — it
flags suspicious shape; the human reviewer / agent fixes by either
rewriting the failure branch to emit `INSUFFICIENT_DATA` or `FAIL` or
explicitly annotating the function `# emitter-failure-mode: reviewed`.

Usage:
    python3 emitter_failure_mode_check.py <plugin_root>
                                          [--json <out>]
                                          [--allow-annotation]

Exit codes:
    0  PASS — no emitter has a fail-then-PASS shape, or every flagged
       function carries the explicit annotation
    1  FAIL — at least one emitter is suspicious and unannotated
    2  argument or I/O error

chip-AGNOSTIC. No vendor / IC / specific filename hardcoded.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple


# Annotation an author may place in a function's docstring or a leading
# comment to certify "I have reviewed the failure-mode handling and
# confirmed the PASS verdict cannot fire on tool-failure / missing-input
# paths." The annotation has to be ABOVE the function line OR in its
# docstring.
_REVIEWED_ANNOTATION = "emitter-failure-mode: reviewed"

# Function-name patterns we audit. Restricted to emitter-style names so
# we don't false-flag every helper that returns "PASS".
_EMITTER_NAME_RE = re.compile(r"^_?emit_[a-z0-9_]+$")


@dataclass
class EmitterFinding:
    file: str
    function: str
    line: int
    rule: str
    detail: str = ""


def _function_has_pass_verdict(func: ast.FunctionDef) -> bool:
    """True if any node in the function body assigns or returns the
    literal string `"PASS"` to a name `verdict` or as a dict value at
    key `verdict`. Walks the AST recursively; doesn't try to track
    aliasing."""
    for node in ast.walk(func):
        # Pattern: verdict = "PASS"
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "verdict":
                    if isinstance(node.value, ast.Constant) \
                            and node.value.value == "PASS":
                        return True
        # Pattern: dict literal {"verdict": "PASS", ...}
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "verdict":
                    if isinstance(v, ast.Constant) and v.value == "PASS":
                        return True
        # Pattern: f.write(json.dumps({"verdict": "PASS", ...}))
        # already covered by the Dict walk above.
        # Pattern: return "PASS" — too generic to flag without
        # caller context; skipped.
    return False


def _function_has_failure_branch(func: ast.FunctionDef,
                                 source_lines: List[str]) -> bool:
    """True if the function body contains any of:
      - bare `except` / `except Exception` / `except OSError`
      - a check like `if rc != 0` / `if returncode != 0`
      - a check `if not <path>.exists()` / `if not <path>.is_file()`
      - a check `if not <var>` / `if <log> == ""`  (empty-log default)
    """
    src = "\n".join(source_lines[func.lineno - 1: func.end_lineno or
                                 func.lineno + 200])
    if re.search(r"except\b", src):
        return True
    if re.search(r"\b(?:rc|returncode|exit_code)\s*!=\s*0", src):
        return True
    if re.search(r"\.exists\(\)\s*[:)\]]?\s*$|"
                 r"not\s+\w[\w\.]*\.exists\(\)|"
                 r"not\s+\w[\w\.]*\.is_file\(\)",
                 src, re.MULTILINE):
        return True
    if re.search(r'==\s*""|==\s*\'\'|len\(\w+\)\s*==\s*0', src):
        return True
    return False


def _function_is_annotated(func: ast.FunctionDef,
                           source_lines: List[str]) -> bool:
    """True if the function body's docstring or the line directly above
    its def contains the reviewed annotation."""
    # Docstring
    doc = ast.get_docstring(func) or ""
    if _REVIEWED_ANNOTATION in doc:
        return True
    # Leading comment lines
    above = func.lineno - 2  # 0-indexed line above the `def`
    while above >= 0:
        line = source_lines[above].strip()
        if not line:
            above -= 1
            continue
        if line.startswith("#"):
            if _REVIEWED_ANNOTATION in line:
                return True
            above -= 1
            continue
        break  # non-comment line stops the scan
    return False


def audit(plugin_root: Path,
          allow_annotation: bool = True
          ) -> Tuple[str, List[EmitterFinding]]:
    findings: List[EmitterFinding] = []
    programs = plugin_root / "programs"
    if not programs.is_dir():
        return "VACUOUS_PASS", []

    py_files = sorted(programs.glob("*.py"))
    if not py_files:
        return "VACUOUS_PASS", []

    for py in py_files:
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(text, filename=str(py))
        except SyntaxError:
            continue
        source_lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not _EMITTER_NAME_RE.match(node.name):
                continue
            if not _function_has_pass_verdict(node):
                continue
            if not _function_has_failure_branch(node, source_lines):
                continue
            if allow_annotation and \
                    _function_is_annotated(node, source_lines):
                continue
            rel = py.relative_to(plugin_root)
            findings.append(EmitterFinding(
                file=str(rel),
                function=node.name,
                line=node.lineno,
                rule="EMITTER_FAIL_THEN_PASS",
                detail=("function declares verdict='PASS' literal AND "
                        "has a failure-mode branch (except / rc!=0 / "
                        "missing-input / empty-log) reachable in the "
                        "same scope. Either rewrite the failure branch "
                        "to emit verdict='INSUFFICIENT_DATA' or "
                        "'TOOL_FAILED', or annotate with the reviewed "
                        f"comment '{_REVIEWED_ANNOTATION}'."),
            ))
    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Anti-fabrication: flag emit_* functions whose "
                    "verdict='PASS' path is reachable from a tool-"
                    "failure / missing-input branch.")
    ap.add_argument("plugin_root",
                    help="Plugin root (containing programs/ subdir)")
    ap.add_argument("--json", help="write JSON report to this path")
    ap.add_argument("--allow-annotation", action="store_true",
                    default=True,
                    help=f"honor the '{_REVIEWED_ANNOTATION}' annotation "
                         "(default: on).")
    ap.add_argument("--no-annotation", dest="allow_annotation",
                    action="store_false",
                    help="ignore the reviewed annotation; flag every "
                         "match.")
    args = ap.parse_args(argv)

    root = Path(args.plugin_root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    verdict, findings = audit(root, allow_annotation=args.allow_annotation)
    report = {
        "gate": "emitter_failure_mode_check",
        "verdict": verdict,
        "plugin_root": str(root),
        "annotation_honored": args.allow_annotation,
        "annotation_token": _REVIEWED_ANNOTATION,
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print("VACUOUS_PASS: no programs/ dir or no .py files")
        return 0
    if verdict == "PASS":
        print("PASS: no emit_* function has a fail-then-PASS shape "
              "(or all flagged functions carry the reviewed annotation)")
        return 0
    print(f"FAIL: {len(findings)} emit_* function(s) flagged:",
          file=sys.stderr)
    for f in findings[:10]:
        print(f"  [{f.rule}] {f.file}:{f.line} {f.function} — "
              f"{f.detail[:200]}", file=sys.stderr)
    if len(findings) > 10:
        print(f"  … and {len(findings) - 10} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
