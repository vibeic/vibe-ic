#!/usr/bin/env python3
"""dead_program_reference_check.py — shipped doctrine may not name a program
that does not exist.

THE CLASS, measured three times on main before this existed
===========================================================
A deletion PR removes a program. Prose elsewhere in the bundle still names
it as the owner of a contract, in backticks, in the present tense. The
deletion is green — nothing imports the file, so every import-graph and
reachability check is satisfied — and the lie ships. dead_plugin_path_check
already states the harm exactly, for a different token: "an agent following
the text verbatim runs a nonexistent checker".

Three live instances found on main on 2026-07-27, all fixed in the same
commit as this file:

  * l9_rtl_pin_consistency_check said the open-drain QSF contract "is owned
    by" a generator PR #462 had deleted three commits earlier. That PR's own
    body claimed "the one docstring that named the dead shims is updated
    here" — the file had TWO occurrences and the diff changed one.
  * phase1_gate_contract_check named a skill-compliance meta-checker as its
    counterpart. `git log --diff-filter=A` over the whole history returns
    nothing for that path: the program has NEVER existed.
  * benchmark-enhancement-capture/SKILL.md's routing table sent every
    mixed-signal M1-M4 recovery to a checker that does not exist, while the
    machine-readable table it mirrors (benchmark/CAPTURE_ROUTING.json, the
    one enhancement_emit.py actually reads) names the real one. The prose
    and the artefact it claims to mirror disagreed.

(The three dead names are deliberately written above WITHOUT backticks. A
backtick around a module name is this repo's notation for "this is code you
can run"; that is what this gate reads, and a checker whose own docstring
tripped it would be worthless.)

WHAT IT MEASURES
================
Every backtick-quoted `<name>.py` in the shipped bundle (programs/, skills/,
agents/, commands/, _shared/) must resolve to a file that exists somewhere in
the repository. Resolution is by BASENAME anywhere under the root, so a
reference to a tool that lives outside programs/ (tools/phase1_engine/render.py,
benchmark/gates_atomic.py) resolves and is not a finding.

DELIBERATE SCOPE LIMIT, and why it is not a loophole
====================================================
Only names in the repo's own program-naming classes are judged:

    _check.py  _audit.py  _gen.py  _guard.py  _lint.py  _runner.py

Bundle prose legitimately names files owned by OTHER projects — RTLLM's
auto_run.py, CVDP's build_db.py, efabless's mpw_precheck.py, a design's
tb.py — and those are not this repo's to keep alive. Judging them would
need an allowlist, and an allowlist is one more place for a stale entry to
hide. The suffix classes are exactly the shapes this repo uses for things an
agent is told to RUN, which is where the harm is. Measured over the bundle
at the time of writing: 1295 files, 12 unresolved names, 3 in the covered
classes — and all 3 were real defects.

`tests/` is excluded: test bodies construct fixture programs with invented
names at runtime (checker_execution_wiring_audit's own test builds a
sample checker), and those names correctly do not exist on disk. The PASS
line discloses the file count so the exclusion is visible.

Exit codes
----------
    0  PASS — every covered reference resolves (count disclosed)
    1  FAIL — at least one covered reference names a nonexistent file
    2  root not found / unreadable

chip-AGNOSTIC: pure text over the repo's own file names; no chip, vendor or
SKU literal.

Usage
-----
    python3 dead_program_reference_check.py [<repo-root>] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# A backticked module reference: `some_name.py`.
_REF_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*\.py)`")

# The naming classes this repo uses for programs an agent is told to run.
COVERED_SUFFIXES = ("_check.py", "_audit.py", "_gen.py", "_guard.py",
                    "_lint.py", "_runner.py")

_BUNDLE_SUBDIRS = ("programs", "skills", "agents", "commands", "_shared")
_SCAN_SUFFIXES = {".py", ".md", ".yaml", ".yml"}
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", "tests"}


def _existing_py_basenames(root: Path) -> set:
    """Every *.py basename that exists anywhere under `root`."""
    found = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in {".git", "__pycache__", ".pytest_cache",
                                    "node_modules"}]
        for fn in filenames:
            if fn.endswith(".py"):
                found.add(fn)
    return found


def _bundle_roots(root: Path) -> List[Path]:
    """Shipped-bundle roots under `root` (plugin dirs, or `root` itself)."""
    roots: List[Path] = []
    plugins = root / "vibe-ic-marketplace" / "plugins"
    if plugins.is_dir():
        roots.extend(p for p in sorted(plugins.iterdir()) if p.is_dir())
    if any((root / sub).is_dir() for sub in _BUNDLE_SUBDIRS):
        roots.append(root)
    return roots


def audit(root: Path) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    """Return (findings, counts). A finding is one unresolved reference."""
    existing = _existing_py_basenames(root)
    findings: List[Dict[str, str]] = []
    files_scanned = 0
    refs_seen = 0
    refs_covered = 0
    for bundle in _bundle_roots(root):
        for sub in _BUNDLE_SUBDIRS:
            base = bundle / sub
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
                    continue
                if any(part in _SKIP_DIRS for part in path.parts):
                    continue
                try:
                    text = path.read_text(errors="replace")
                except OSError:
                    continue
                files_scanned += 1
                for lineno, line in enumerate(text.splitlines(), 1):
                    for match in _REF_RE.finditer(line):
                        name = match.group(1)
                        refs_seen += 1
                        if not name.endswith(COVERED_SUFFIXES):
                            continue
                        refs_covered += 1
                        if name in existing:
                            continue
                        findings.append({
                            "file": str(path.relative_to(root)),
                            "line": lineno,
                            "name": name,
                            "text": line.strip()[:160],
                        })
    counts = {"files_scanned": files_scanned,
              "references_seen": refs_seen,
              "references_covered": refs_covered,
              "unresolved": len(findings)}
    return findings, counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", nargs="?", default=".",
                    help="repository root to audit (default: current dir)")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[ERROR] root not found: {root}", file=sys.stderr)
        return 2

    findings, counts = audit(root)
    if args.json:
        print(json.dumps({"program": "dead_program_reference_check",
                          "passed": not findings,
                          "counts": counts,
                          "findings": findings}, indent=2))
    else:
        scope = "/".join(s.replace(".py", "") for s in COVERED_SUFFIXES)
        if findings:
            print(f"[FAIL] {len(findings)} backticked program reference(s) "
                  f"name a file that does not exist in this repo:")
            for f in findings:
                print(f"  {f['file']}:{f['line']}: {f['name']}")
                print(f"      {f['text']}")
        print(f"scanned {counts['files_scanned']} bundle file(s); "
              f"{counts['references_seen']} backticked module reference(s), "
              f"{counts['references_covered']} in the covered classes "
              f"({scope}); {counts['unresolved']} unresolved")
        if not findings:
            print("[PASS] every covered program reference resolves")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
