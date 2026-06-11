#!/usr/bin/env python3
r"""
sv_package_closure_check.py — SystemVerilog package-dependency closure gate
(ORGANIC #549).

THE PROBLEM
-----------
A REUSED-IP / Shape-A staging step validated package closure by diffing
`import pkg::*;` statements against package definitions only. SystemVerilog
also lets code reference a package symbol WITHOUT importing it, via a scoped
reference `pkg::SYM`. A staged file set whose import-diff looked complete then
exploded at sv2v / elaborate time with N "package not found" errors because
the RTL used `top_pkg::`, `lc_ctrl_pkg::` etc. as scoped references with no
matching `import` and no staged definition.

WHAT THIS GATE DOES
-------------------
Scan a set of staged .sv/.v files and collect three classes of package
dependency:

  1. `import <pkg>::*;`  /  `import <pkg>::<sym>;`           (import closure)
  2. `<pkg>::<sym>`       scoped references (the missing class)
  3. `\`include "<file>"`  include directives                (file closure)

Then resolve each against what the staged set DEFINES:

  * a package is DEFINED when some staged file has `package <pkg>;`
  * an include target is DEFINED when a staged file's basename matches

Any referenced package with no staged definition, or any `\`include` whose
target is not present, is a MISSING dependency → FAIL. A set whose every
package/include dependency resolves → PASS.

This is a deterministic structural pre-gate for REUSED-IP staging (Bucket A):
it catches the scoped-reference closure hole BEFORE the expensive elaborate.

USAGE
-----
    python3 sv_package_closure_check.py <dir-or-file>... [--json <out>]

EXIT CODES
----------
    0 — closure complete (every package / include dependency defined)
    1 — at least one missing package / include
    2 — IO / argument error (no files found)

chip-AGNOSTIC: pure SystemVerilog grammar; no vendor / IC / package literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


# A SystemVerilog identifier.
_ID = r"[A-Za-z_]\w*"

# package <name>;  (definition)
_PKG_DEF_RE = re.compile(rf"\bpackage\s+({_ID})\s*;", re.MULTILINE)
# import <pkg>::*;  / import <pkg>::<sym>;  (possibly comma-listed)
_IMPORT_RE = re.compile(rf"\bimport\s+({_ID})\s*::\s*(?:\*|{_ID})")
# <pkg>::<sym>  scoped reference (the missing-closure class). The `::` is the
# discriminator; `import` lines are stripped before this scan so an import is
# not double-counted as a scoped ref.
_SCOPED_RE = re.compile(rf"\b({_ID})\s*::\s*{_ID}")
# `include "path/to/file.svh"
_INCLUDE_RE = re.compile(r'`include\s+"([^"]+)"')


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _strip_string_literals(text: str) -> str:
    # remove "..." so a scoped-looking token inside a string is not a ref
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


def collect(files_text: Dict[str, str]) -> Tuple[Set[str], Set[str],
                                                 Set[str], Set[str], Set[str]]:
    """Return (defined_pkgs, imported_pkgs, scoped_pkgs, include_targets,
    defined_basenames) across the file-text map."""
    defined: Set[str] = set()
    imported: Set[str] = set()
    scoped: Set[str] = set()
    includes: Set[str] = set()
    basenames: Set[str] = set(Path(p).name for p in files_text)
    for path, raw in files_text.items():
        nocomment = _strip_comments(raw)
        # `include targets are legitimately quoted paths — scan them BEFORE
        # string-literal stripping (which would blank the path).
        for m in _INCLUDE_RE.finditer(nocomment):
            includes.add(m.group(1))
        # package defs / imports / scoped refs: scan the string-stripped view
        # so a scoped-looking token inside a string literal is not a ref.
        text = _strip_string_literals(nocomment)
        defined |= set(_PKG_DEF_RE.findall(text))
        imported |= set(_IMPORT_RE.findall(text))
        # scoped refs: scan a copy with import lines removed so an
        # `import pkg::*` is not also counted as a scoped `pkg::*` ref.
        no_imports = _IMPORT_RE.sub("", text)
        scoped |= set(_SCOPED_RE.findall(no_imports))
    # std / built-in scopes are always available — never "missing".
    scoped -= {"std"}
    return defined, imported, scoped, includes, basenames


def audit(files_text: Dict[str, str]) -> Dict:
    defined, imported, scoped, includes, basenames = collect(files_text)
    referenced = imported | scoped
    missing_pkgs = sorted(referenced - defined)
    missing_includes = sorted(
        inc for inc in includes
        if Path(inc).name not in basenames)
    findings: List[Dict] = []
    for p in missing_pkgs:
        via = []
        if p in imported:
            via.append("import")
        if p in scoped:
            via.append("scoped-ref (pkg::sym)")
        findings.append({
            "severity": "FAIL", "rule": "package_definition_missing",
            "package": p,
            "message": f"package {p!r} is referenced ({', '.join(via)}) but "
                       f"no staged file declares `package {p};` — closure "
                       f"hole (scoped pkg:: references are easy to miss in an "
                       f"import-only diff)",
        })
    for inc in missing_includes:
        findings.append({
            "severity": "FAIL", "rule": "include_target_missing",
            "include": inc,
            "message": f"`include \"{inc}\" has no matching staged file "
                       f"(basename {Path(inc).name!r} not present)",
        })
    ok = not findings
    return {
        "verdict": "PASS" if ok else "FAIL",
        "defined_packages": sorted(defined),
        "imported_packages": sorted(imported),
        "scoped_ref_packages": sorted(scoped),
        "includes": sorted(includes),
        "missing_packages": missing_pkgs,
        "missing_includes": missing_includes,
        "findings": findings,
    }


def _gather_files(targets: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for t in targets:
        p = Path(t)
        if p.is_dir():
            for f in sorted(list(p.rglob("*.sv")) + list(p.rglob("*.v"))
                            + list(p.rglob("*.svh"))):
                try:
                    out[str(f)] = f.read_text(errors="replace")
                except OSError:
                    continue
        elif p.is_file():
            try:
                out[str(p)] = p.read_text(errors="replace")
            except OSError:
                continue
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="SystemVerilog package-closure gate (#549): catches "
                    "scoped pkg::sym references with no staged definition.")
    ap.add_argument("targets", nargs="+", help="file(s) / directory(ies)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    files_text = _gather_files(args.targets)
    if not files_text:
        print(f"error: no .sv/.v/.svh under {args.targets}", file=sys.stderr)
        return 2

    report = audit(files_text)
    report["files_scanned"] = len(files_text)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")

    print(f"=== sv_package_closure_check ({len(files_text)} file(s)) ===")
    print(f"  verdict: {report['verdict']}")
    for f in report["findings"]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
