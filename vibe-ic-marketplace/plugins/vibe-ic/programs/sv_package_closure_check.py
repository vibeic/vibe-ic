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


# ORGANIC #589 — conditional-compilation awareness. The canonical
# assertion-macro header (`ifdef VERILATOR / `elsif SYNTHESIS / `else →
# include a sim-only macros file) made the textual scan report 5
# missing-definition FAILs on a fully-consistent closure: every flagged
# target lived in a branch the synthesis define-set never takes.
_COND_RE = re.compile(
    r"^\s*`(ifdef|ifndef|elsif|else|endif)\b\s*(\w+)?", re.M)


def _annotate_conditionals(text: str, defines: "Set[str] | None"
                           ) -> List[Tuple[str, bool, str]]:
    """Split `text` into (segment, reachable, guard) pieces by walking
    `ifdef/`ifndef/`elsif/`else/`endif with a branch stack.

    With ``defines`` given, ``reachable`` reflects actual branch
    evaluation under that define-set. With ``defines=None`` (no
    --define), every branch is treated reachable (legacy behaviour) but
    ``guard`` still names the innermost condition so the caller can
    downgrade conditional-branch findings to WARN. Unbalanced directives
    degrade gracefully (stack never underflows). Chip-AGNOSTIC."""
    segments: List[Tuple[str, bool, str]] = []
    # stack entries: [taken_now, any_branch_taken, guard_label]
    stack: List[List] = []

    def _reachable_now() -> bool:
        if defines is None:
            return True
        return all(fr[0] for fr in stack)

    def _guard_now() -> str:
        return stack[-1][2] if stack else ""

    pos = 0
    for m in _COND_RE.finditer(text):
        segments.append((text[pos:m.start()], _reachable_now(),
                         _guard_now()))
        pos = m.end()
        kw, sym = m.group(1), (m.group(2) or "")
        if kw == "ifdef":
            taken = defines is None or sym in defines
            stack.append([taken, taken, f"`ifdef {sym}"])
        elif kw == "ifndef":
            taken = defines is None or sym not in defines
            stack.append([taken, taken, f"`ifndef {sym}"])
        elif kw == "elsif":
            if stack:
                fr = stack[-1]
                taken = ((defines is None or sym in defines)
                         and not fr[1])
                fr[0] = taken
                fr[1] = fr[1] or taken
                fr[2] = f"`elsif {sym}"
        elif kw == "else":
            if stack:
                fr = stack[-1]
                fr[0] = (defines is None) or (not fr[1])
                fr[1] = True
                fr[2] = fr[2] + " → `else"
        elif kw == "endif":
            if stack:
                stack.pop()
    segments.append((text[pos:], _reachable_now(), _guard_now()))
    return segments


def _strip_string_literals(text: str) -> str:
    # remove "..." so a scoped-looking token inside a string is not a ref
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


def collect(files_text: Dict[str, str],
            defines: "Set[str] | None" = None
            ) -> Tuple[Set[str], Set[str], Set[str], Set[str], Set[str],
                       Dict[str, str]]:
    """Return (defined_pkgs, imported_pkgs, scoped_pkgs, include_targets,
    defined_basenames, guard_of) across the file-text map.

    #589: references are harvested per conditional-compilation segment.
    With ``defines`` given, UNREACHABLE segments are skipped entirely;
    without it every segment is scanned but ``guard_of`` records the
    innermost guarding condition for each include / package reference
    that sits inside any conditional branch (so the caller can downgrade
    those to WARN instead of asserting a hole the build never compiles)."""
    defined: Set[str] = set()
    imported: Set[str] = set()
    scoped: Set[str] = set()
    includes: Set[str] = set()
    guard_of: Dict[str, str] = {}
    basenames: Set[str] = set(Path(p).name for p in files_text)
    for path, raw in files_text.items():
        nocomment = _strip_comments(raw)
        for seg, reachable, guard in _annotate_conditionals(nocomment,
                                                            defines):
            if not reachable:
                continue
            # `include targets are legitimately quoted paths — scan them
            # BEFORE string-literal stripping (which would blank the path).
            for m in _INCLUDE_RE.finditer(seg):
                includes.add(m.group(1))
                if guard:
                    guard_of.setdefault(m.group(1), guard)
            # package defs / imports / scoped refs: string-stripped view
            # so a scoped-looking token inside a string literal is not a ref.
            text = _strip_string_literals(seg)
            defined |= set(_PKG_DEF_RE.findall(text))
            for pkg in _IMPORT_RE.findall(text):
                imported.add(pkg)
                if guard:
                    guard_of.setdefault(pkg, guard)
            # scoped refs: scan a copy with import lines removed so an
            # `import pkg::*` is not also counted as a scoped `pkg::*` ref.
            no_imports = _IMPORT_RE.sub("", text)
            for pkg in _SCOPED_RE.findall(no_imports):
                scoped.add(pkg)
                if guard:
                    guard_of.setdefault(pkg, guard)
    # std / built-in scopes are always available — never "missing".
    scoped -= {"std"}
    return defined, imported, scoped, includes, basenames, guard_of


def audit(files_text: Dict[str, str],
          defines: "Set[str] | None" = None) -> Dict:
    defined, imported, scoped, includes, basenames, guard_of = collect(
        files_text, defines)
    referenced = imported | scoped
    missing_pkgs = sorted(referenced - defined)
    missing_includes = sorted(
        inc for inc in includes
        if Path(inc).name not in basenames)
    findings: List[Dict] = []

    def _severity(token: str) -> str:
        # #589 — without a define-set we cannot know which branch the
        # build takes: a reference guarded by ANY conditional is
        # advisory (WARN, guard named), not a hard closure hole. With
        # --define given, unreachable branches were already excluded, so
        # whatever remains genuinely compiles → FAIL.
        if defines is None and token in guard_of:
            return "WARN"
        return "FAIL"

    for p in missing_pkgs:
        via = []
        if p in imported:
            via.append("import")
        if p in scoped:
            via.append("scoped-ref (pkg::sym)")
        sev = _severity(p)
        guard_note = (f" [inside conditional branch: {guard_of[p]} — "
                      f"advisory; pass --define to evaluate reachability]"
                      if sev == "WARN" else "")
        findings.append({
            "severity": sev, "rule": "package_definition_missing",
            "package": p,
            "message": f"package {p!r} is referenced ({', '.join(via)}) but "
                       f"no staged file declares `package {p};` — closure "
                       f"hole (scoped pkg:: references are easy to miss in an "
                       f"import-only diff){guard_note}",
        })
    for inc in missing_includes:
        sev = _severity(inc)
        guard_note = (f" [inside conditional branch: {guard_of[inc]} — "
                      f"advisory; pass --define to evaluate reachability]"
                      if sev == "WARN" else "")
        findings.append({
            "severity": sev, "rule": "include_target_missing",
            "include": inc,
            "message": f"`include \"{inc}\" has no matching staged file "
                       f"(basename {Path(inc).name!r} not present)"
                       f"{guard_note}",
        })
    ok = not any(f["severity"] == "FAIL" for f in findings)
    return {
        "verdict": "PASS" if ok else "FAIL",
        "defines": sorted(defines) if defines is not None else None,
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
    # ORGANIC #589 — conditional-compilation define-set: with one or
    # more --define, `ifdef branch reachability is evaluated and only
    # the taken branches are scanned (e.g. --define SYNTHESIS makes the
    # canonical assertion-macro header resolve like the real build).
    ap.add_argument("--define", action="append", default=None,
                    metavar="NAME",
                    help="treat NAME as defined when evaluating "
                         "`ifdef/`elsif branches (repeatable)")
    args = ap.parse_args(argv)

    files_text = _gather_files(args.targets)
    if not files_text:
        print(f"error: no .sv/.v/.svh under {args.targets}", file=sys.stderr)
        return 2

    defines = set(args.define) if args.define is not None else None
    report = audit(files_text, defines)
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
