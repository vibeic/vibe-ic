#!/usr/bin/env python3
"""A login shell in the container prints two lines before the tool does.

MEASURED, and re-measured on the current image (`vibeic-eda:0.2.63`):

    docker exec <c> bash -lc 'echo HELLO' 2>/dev/null
      [INFO] Final PATH variable: /headless/.local/bin:/foss/tools/bin:...
      [INFO] Final PYTHONPATH variable: /headless/.local/lib/python3.12/...
      HELLO

    docker exec <c> bash -lc 'echo HELLO' 2>&1 >/dev/null      ->  (empty)
    docker exec <c> bash -c  'echo HELLO'                      ->  HELLO

The banner is on **stdout**, not stderr, and only a LOGIN shell emits it. So any
caller that runs a command through `bash -lc` and then reads the captured stdout
as a value gets two junk lines prepended to its answer.

WHY THIS IS A GUARD AND NOT A REFACTOR
======================================
The hazard was already known — `lec_run` and `analog_real_corner_sweep` each
carry a comment about it. That is precisely the shape that rots: fixed in the
two programs that hit it, live in the other twenty-two, and invisible to the
next person who writes a parser.

So the population was measured rather than assumed. 24 programs pass `-lc`;
18 of them build the `docker exec` argv themselves, so there is no single seam
to fix. And every one of their stdout consumers is currently immune — they take
the LAST line, grep for a marker, or write to a file. **Zero live mis-parses.**

Rewriting 24 call sites to fix nothing would be churn, and `-lc` is not
load-bearing here (`bash -c` resolves yosys / openroad / klayout / magic /
netgen / iverilog on this image, all six). The thing actually worth preventing
is the NEXT parser, written blind, on the assumption that stdout starts with the
tool's own output.

This gate therefore fails only on the shapes the banner actually corrupts:

  * `int(cp.stdout)` / `float(cp.stdout)`      — a number that is now a banner
  * `cp.stdout.splitlines()[0]`                — the first line is the banner
  * `x = cp.stdout.strip()`  used whole        — the value carries both lines

It stays silent on `[-1]`, on a `for line in ...` scan, and on a redirect to a
file, because none of those are wrong.

chip-, PDK- and vendor-AGNOSTIC: it reads this repo's own Python for a shell
flag and a parse shape. Exit 0 clean, 1 on a finding, 2 if the population it
scans looks broken (an empty population would make a PASS vacuous).
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

PROGRAMS = Path(__file__).resolve().parent

#: The login-shell flag. `-lc` is the spelling every caller in this tree uses;
#: `-l -c` and `--login` are accepted so a reworded call site is not a bypass.
_LOGIN_SHELL_RE = re.compile(
    r"""(["']-lc["'])|(\bbash\s+-lc\b)|(["']--login["'])|(["']-l["']\s*,\s*["']-c["'])""")

#: stdout consumers the two prepended lines actually corrupt. Each carries the
#: reason it is here, so a future reader can judge the rule rather than obey it.
_FRAGILE = (
    (re.compile(r"(?<![\w.])(?:int|float)\(\s*[\w.]*\bstdout\b"),
     "numeric conversion of stdout — the banner is the first thing parsed"),
    (re.compile(r"\bstdout\b[\w.()]*\.splitlines\(\)\s*\[\s*0\s*\]"),
     "first line of stdout — that line is the banner"),
    (re.compile(r"^\s*\w+\s*=\s*[\w.]*\bstdout\b\.strip\(\)\s*(?:#.*)?$", re.M),
     "whole stdout captured as one value — it carries both banner lines"),
)


def _uses_login_shell(text: str) -> bool:
    return bool(_LOGIN_SHELL_RE.search(text))


def _fragile_sites(text: str) -> List[Tuple[int, str, str]]:
    """(lineno, why, source) for each banner-fragile stdout consumer."""
    lines = text.splitlines()
    out: List[Tuple[int, str, str]] = []
    for pat, why in _FRAGILE:
        for m in pat.finditer(text):
            ln = text[:m.start()].count("\n") + 1
            src = lines[ln - 1].strip() if ln <= len(lines) else ""
            out.append((ln, why, src[:120]))
    return sorted(set(out))


def _programs() -> List[Path]:
    return sorted(p for p in PROGRAMS.glob("*.py")
                  if p.name != Path(__file__).name)


def audit(programs: List[Path] | None = None) -> Dict[str, object]:
    progs = list(programs) if programs is not None else _programs()
    login: List[str] = []
    findings: Dict[str, List[Tuple[int, str, str]]] = {}
    for p in progs:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _uses_login_shell(text):
            continue
        login.append(p.name)
        sites = _fragile_sites(text)
        if sites:
            findings[p.name] = sites
    return {
        "program": "container_login_banner_parse_check",
        "population": len(progs),
        "login_shell_callers": sorted(login),
        "findings": {k: [{"line": ln, "why": w, "source": s}
                         for ln, w, s in v] for k, v in findings.items()},
        "verdict": "FAIL" if findings else "PASS",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, help="write the record here")
    args = ap.parse_args()

    rec = audit()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rec, indent=2) + "\n")

    name = rec["program"]
    if not rec["login_shell_callers"]:
        # Not a pass: either every caller stopped using a login shell (real, and
        # this gate should then be retired) or the detector stopped matching.
        # Saying "clean" without distinguishing those is the failure this gate
        # is about.
        print(f"[SKIP] {name}: no program in a population of "
              f"{rec['population']} passes a login shell to the container — "
              f"either the hazard is gone or this detector no longer matches "
              f"the call sites; both need a human, neither is a PASS.")
        return 2

    if rec["verdict"] == "PASS":
        print(f"[PASS] {name}: {len(rec['login_shell_callers'])} program(s) run "
              f"the container through a login shell, and none of them reads the "
              f"captured stdout in a shape the two prepended [INFO] lines "
              f"corrupt (no numeric conversion, no [0], no whole-value capture).")
        return 0

    print(f"[FAIL] {name}: a login shell prepends two [INFO] lines to stdout, "
          f"and these call sites parse stdout in a shape that breaks on them:")
    for fname, sites in sorted(rec["findings"].items()):
        for s in sites:
            print(f"  - {fname}:{s['line']}  {s['why']}")
            print(f"      {s['source']}")
    print("  Fix: read the LAST line, scan for the tool's own marker, or drop "
          "the login shell (`bash -c` resolves every tool on this image).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
