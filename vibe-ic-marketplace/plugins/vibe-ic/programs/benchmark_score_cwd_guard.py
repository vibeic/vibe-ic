#!/usr/bin/env python3
"""benchmark_score_cwd_guard.py — assert the host scorer is invoked
FROM the design directory before it runs.

Extracted from open-benchmark-methodology § 3 (the cwd=design_dir
rule). A benchmark testbench loads its golden vectors with a
relative path, e.g. `$readmemh("reference.txt", mem)`. iverilog/vvp
resolve that path relative to the *current working directory*, not
the .v file location. RTLLM's own `auto_run.py` does
`os.chdir(design); make vcs`. Forgetting this caused 3 false fails
in the 2026-05-28 RTLLM run.

This is a mechanical guard: given the design dir and the cwd the
scorer is about to run from, FAIL if cwd != design dir, OR if the
TB references a relative file that does not exist under the cwd.

Usage
=====
  # Pure cwd assertion (cwd defaults to os.getcwd()):
  python3 benchmark_score_cwd_guard.py --design <design_dir> [--cwd <dir>] \
      [--json out.json]

  # Also verify every relative $readmemh/$readmemb/$fopen path in the TB
  # resolves under the cwd:
  python3 benchmark_score_cwd_guard.py --design <design_dir> --cwd <dir> \
      --tb <testbench.v> [--json out.json]

Honest failure
==============
  * --design pointing at a non-directory → FAIL (rc 1).
  * cwd != design dir (after realpath) → FAIL (rc 1): the scorer would
    run from the wrong directory and relative golden-vector paths break.
  * --tb missing / unreadable → FAIL (rc 1).
  * A relative readmemh/fopen target in the TB that does not exist under
    cwd → FAIL (rc 1) with the offending path(s) listed.

A run with no relative file references and cwd==design is a real PASS
(the guard is satisfied). A run with cwd==design is the minimum bar.

Exit codes
==========
  0 — PASS (cwd==design, and every relative TB datafile resolves)
  1 — FAIL
  2 — usage error
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# $readmemh("vec.txt", ...) / $readmemb(...) / $fopen("golden.txt", ...)
_DATAFILE_RE = re.compile(
    r'\$(?:readmemh|readmemb|fopen)\s*\(\s*"([^"]+)"',
    re.IGNORECASE,
)


def _relative_datafiles(tb_text: str) -> list[str]:
    out: list[str] = []
    for m in _DATAFILE_RE.finditer(tb_text):
        path = m.group(1)
        # Absolute paths and pure macros (`...`) are not cwd-relative.
        if os.path.isabs(path) or path.startswith("`") or path.startswith("$"):
            continue
        out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--design", required=True, help="the benchmark design directory")
    ap.add_argument("--cwd", help="the directory the scorer will run from "
                                  "(default: current working directory)")
    ap.add_argument("--tb", help="testbench .v to scan for relative datafile refs")
    ap.add_argument("--json", help="write JSON report to this path")
    a = ap.parse_args(argv)

    report: dict = {"program": "benchmark_score_cwd_guard"}
    design = Path(a.design)
    if not design.is_dir():
        report.update(verdict="FAIL", reason="design_not_a_directory",
                      design=str(design))
        _emit(a, report)
        print(f"FAIL: design dir is not a directory: {design}", file=sys.stderr)
        return 1

    cwd = Path(a.cwd) if a.cwd else Path(os.getcwd())
    design_real = design.resolve()
    cwd_real = cwd.resolve()
    report["design"] = str(design_real)
    report["cwd"] = str(cwd_real)

    if cwd_real != design_real:
        report.update(verdict="FAIL", reason="cwd_not_design_dir")
        _emit(a, report)
        print(f"FAIL: scorer cwd {cwd_real} != design dir {design_real} — "
              f"relative $readmemh golden-vector paths will not resolve",
              file=sys.stderr)
        return 1

    if a.tb is not None:
        tb = Path(a.tb)
        if not tb.is_file():
            report.update(verdict="FAIL", reason="tb_missing", tb=str(tb))
            _emit(a, report)
            print(f"FAIL: testbench not found: {tb}", file=sys.stderr)
            return 1
        tb_text = tb.read_text(encoding="utf-8", errors="replace")
        rels = _relative_datafiles(tb_text)
        report["relative_datafiles"] = rels
        missing = [r for r in rels if not (cwd_real / r).exists()]
        report["missing_datafiles"] = missing
        if missing:
            report.update(verdict="FAIL", reason="relative_datafile_unresolved")
            _emit(a, report)
            print("FAIL: relative TB datafile(s) do not resolve under cwd: "
                  + ", ".join(missing), file=sys.stderr)
            return 1

    report["verdict"] = "PASS"
    _emit(a, report)
    print(f"PASS: cwd == design dir ({design_real}); scorer-relative paths OK")
    return 0


def _emit(a, report: dict) -> None:
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
