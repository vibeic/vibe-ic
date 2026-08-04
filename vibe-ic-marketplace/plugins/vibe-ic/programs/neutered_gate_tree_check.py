#!/usr/bin/env python3
"""neutered_gate_tree_check.py — is a gate in this checkout unable to fail?

THE STATE THIS EXISTS FOR (measured 2026-08-04)
===============================================
`gate_cli_mutation_probe` answers "would anything notice if this gate could not
fail" by making it unable to fail and running its tests.  Until this change it
did that to the SHIPPED file, restoring in a ``finally`` — and a ``finally``
does not run on ``SIGKILL``.  Twice in one parallel-agent session a killed run
left a gate carrying an injected early return, plus a ``.probe-orig`` sidecar,
in a checkout other agents kept using.

An injected early return makes the gate exit 0.  The flow reads exit codes, so
the corrupted gate reads as PASS — for every step it guards, in every run, in
silence.  Both instances were found by hand.

The probe no longer touches the shipped tree, so no NEW instance can be created
this way.  That is not the same as a checkout being clean: a tree damaged by an
older build, a restored backup, or a hand-edit is still out there and still
lies.  This is the detector that makes the state visible instead of leaving it
to whoever happens to look.

WHY IT RE-DERIVES RATHER THAN RE-TYPES
======================================
The strings this scans for come from the probe's own ``_ENTRIES`` table, read
at import.  A detector that re-typed them would keep passing after the probe's
injection changed — a second list that looks authoritative and has quietly
stopped describing anything, which is the exact drift `_gate_dispatch.sh` and
`p0_gate_invocability_drift_check` were each written to remove.  It also means
this file never contains the sentinel literal, so it needs no self-exemption,
and an exemption is a hole.

THE MATCH IS ON A WHOLE LINE, not a substring.  The probe's own source carries
the injected text inside a string literal; a substring rule would report the
probe as neutered on every run, and a gate that cries wolf about itself gets
switched off.  The injected form is always a statement on its own line, so
``line.strip() in injected`` separates the two with no exemption list.

Exit codes: 0 clean, 1 a gate in this tree cannot fail, 2 nothing was examined.
chip-AGNOSTIC: it reads Python source, and knows nothing about any design.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import gate_cli_mutation_probe as _probe

GATE = "neutered_gate_tree_check"

_PLUGIN = Path(__file__).resolve().parent.parent


def injected_statements() -> Set[str]:
    """The exact lines the probe injects, taken from the probe."""
    return {inj.strip() for _pat, inj, _label in _probe._ENTRIES if inj.strip()}


def backup_suffix() -> str:
    return _probe._BACKUP_SUFFIX


def scan(root: Path) -> Tuple[List[Dict], int]:
    """`(findings, files_examined)` over every Python module under `root`."""
    injected = injected_statements()
    findings: List[Dict] = []
    examined = 0
    if not injected:
        # The probe's table could be read and is EMPTY. That is a broken
        # measurement, not a clean tree, and it must not exit 0.
        findings.append({
            "kind": "NO_SENTINEL_DERIVED",
            "path": "gate_cli_mutation_probe._ENTRIES",
            "detail": ("the probe declares no injection, so this check has "
                       "nothing to look for and cannot clear the tree")})
        return findings, 0
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        examined += 1
        try:
            text = p.read_text(errors="replace")
        except OSError as exc:
            findings.append({"kind": "UNREADABLE", "path": str(p),
                             "detail": str(exc)[:160]})
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if line.strip() in injected:
                findings.append({
                    "kind": "NEUTERED_GATE", "path": str(p), "line": n,
                    "detail": ("this line makes the program's entry point "
                               "return success before it does anything, so "
                               "the gate exits 0 and the flow reads PASS. It "
                               "is what an interrupted `gate_cli_mutation_"
                               "probe` run leaves behind. Remove the line — "
                               "and re-run every verdict taken since, because "
                               "each was measured against a gate that could "
                               "not fail.")})
    for p in sorted(root.rglob("*" + backup_suffix())):
        findings.append({
            "kind": "STALE_PROBE_BACKUP", "path": str(p),
            "detail": ("a mutation probe was interrupted while it held this "
                       "sidecar. The file it names may still be neutered; "
                       "restore it from the sidecar (or from git) and delete "
                       "the sidecar.")})
    return findings, examined


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root", nargs="?", default=None,
                    help="plugin root to scan (default: the shipped one)")
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args(argv)

    root = Path(a.root).resolve() if a.root else _PLUGIN
    scan_root = root / "programs" if (root / "programs").is_dir() else root
    findings, examined = scan(scan_root)

    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(json.dumps(
            {"program": GATE, "root": str(scan_root),
             "files_examined": examined,
             "verdict": "FAIL" if findings else "PASS",
             "findings": findings}, indent=2) + "\n")

    for f in findings:
        where = f["path"] + (":%d" % f["line"] if "line" in f else "")
        print("  [%s] %s" % (f["kind"], where), file=sys.stderr)
        print("      " + f["detail"], file=sys.stderr)

    # A zero denominator REFUSES. Pointed at the wrong directory this would
    # otherwise print the same green sentence as a real scan, which is the
    # vacuous pass `gate_zero_denominator_refuses_check` exists to forbid.
    if examined == 0:
        print("[NOT CHECKED] %s: no Python module under %s — nothing was "
              "examined, and this is not a pass." % (GATE, scan_root),
              file=sys.stderr)
        return 2
    if findings:
        print("[FAIL] %s: %d finding(s) over %d module(s) — this checkout "
              "carries a gate that cannot fail." % (GATE, len(findings),
                                                    examined))
        return 1
    print("[PASS] %s: %d module(s) examined; none carries an injected "
          "always-succeed entry point and no interrupted-probe sidecar is "
          "present." % (GATE, examined))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
