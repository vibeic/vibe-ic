#!/usr/bin/env python3
"""single_testpath_guard.py — pytest.ini must declare ONE test tree.

Captured v0.2.24 (benchmark-enhancement-capture, Bucket A) from the v0.2.19
two-test-tree merge. pytest.ini once declared two python test roots
(`testpaths = programs/tests tests`): the unit tree + the integration/regression
GATE tree. Running `pytest programs/tests/` (a path-filtered subset) went GREEN
locally while CI runs bare `pytest` over BOTH — so gate-tree regressions shipped
RED. The user's directive "let two test folders be one" merged them to a single
tree. THIS guard makes that invariant permanent: it FAILs if `testpaths` ever
lists more than one entry again, which is precisely the footgun (a second tree a
subset run can silently skip).

Scope note: this checks ONLY pytest.ini's declared `testpaths`. Genuinely
separate suites with their OWN runners (mcp-eda's node/python tests,
per-skill compliance tests) are NOT in `testpaths` and are correctly ignored —
they are not the footgun, which was specifically TWO python trees a single
`pytest` invocation was meant to cover.

Usage:
    python3 single_testpath_guard.py [<plugin_root>] [--json <out>]
    # default plugin_root = the dir containing pytest.ini above this program

Exit: 0 = exactly one testpath, and it exists (PASS) / 1 = >1 testpath OR the
declared testpath is missing (FAIL) / 2 = pytest.ini not found (operational).
"""
from __future__ import annotations

import argparse
import configparser
import json
import sys
from pathlib import Path


def read_testpaths(ini: Path) -> list[str]:
    cp = configparser.ConfigParser()
    cp.read(ini)
    for sect in ("pytest", "tool:pytest"):
        if cp.has_section(sect) and cp.has_option(sect, "testpaths"):
            return [t for t in cp.get(sect, "testpaths").split() if t]
    return []


def evaluate(plugin_root: Path) -> dict:
    ini = plugin_root / "pytest.ini"
    testpaths = read_testpaths(ini)
    findings = []
    if len(testpaths) == 0:
        findings.append("pytest.ini declares NO testpaths — the full suite is "
                        "undefined; declare exactly one test tree.")
    elif len(testpaths) > 1:
        findings.append(
            f"pytest.ini declares {len(testpaths)} testpaths {testpaths} — the "
            f"two-tree footgun: a path-filtered `pytest <one>` run silently "
            f"skips the others. Merge to a single tree (v0.2.19 doctrine).")
    else:
        only = (plugin_root / testpaths[0])
        if not only.is_dir():
            findings.append(f"declared testpath '{testpaths[0]}' does not exist "
                            f"at {only}.")
    return {"testpaths": testpaths, "findings": findings}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("plugin_root", nargs="?", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    root = Path(a.plugin_root) if a.plugin_root else \
        Path(__file__).resolve().parent.parent
    if not (root / "pytest.ini").is_file():
        print(f"SKIP: no pytest.ini at {root / 'pytest.ini'}", file=sys.stderr)
        return 2

    res = evaluate(root)
    verdict = "PASS" if not res["findings"] else "FAIL"
    report = {"gate": "single_testpath_guard", "verdict": verdict, **res}
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(report, indent=2) + "\n")

    if res["findings"]:
        print("FAIL: " + " ".join(res["findings"]))
        return 1
    print(f"PASS: pytest.ini declares a single test tree {res['testpaths']} "
          f"(no two-tree footgun).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
