#!/usr/bin/env python3
"""gate_discloses_denominator_check.py — a PASS must say how much it looked at.

THE CLASS (vibe-ic#447), measured four times before this existed
=================================================================
A gate answers PASS after examining NOTHING, and its output is
indistinguishable from a real clean run:

    nda_tracked_tree_scan        PASSed on 21 of 20143 blobs (cwd prefix shift)
    l4_systemrdl_export          audit-corpus found 0 of 201 documents -> PASS
                                 (skip-set matched the ABSOLUTE path)
    cross_layer_reference_check  46 cells in a checkout vs 23 in a worktree,
                                 making a COUNT-based baseline host-dependent
    source_chip_agnostic_check   a scan of 1239 files and a scan of 0 printed
                                 the same sentence, byte for byte

Four different walking bugs — cwd, absolute-vs-relative, tracked-vs-on-disk —
and one thing in common: NONE OF THEM COULD BE SEEN FROM THE OUTPUT. Each
survived until something unrelated exposed it.

WHAT THIS CHECKS, AND WHAT IT DELIBERATELY DOES NOT
====================================================
It runs every gate in ``tools/ci/repo_hygiene_gates.sh`` against a scratch
EMPTY repository and requires that a PASS there DISCLOSE that it examined
nothing.

It does NOT require a gate to FAIL on an empty tree. PASS-on-empty is often
CORRECT — ``tracked_symlink_portability_check`` on a tree with no symlinks is
genuinely clean — and a check that demanded otherwise would fire on legitimate
state, which is how the orphan-capability detector (#439) earned deletion
rather than a landing.

    THE DISCRIMINATOR IS DISCLOSURE, NOT VERDICT.

A gate may say PASS over zero items as long as a reader can SEE that it was
zero: a count, or an explicit "no corpus" / "nothing to check" / SKIP.

MEASURED WHILE BUILDING IT, and the reason the discriminator is what it is: a
first version looked only at the LAST line for a digit and flagged 5 of 25.
Four were false — ``tracked_symlink_portability_check`` prints
``dangling ...: 0`` on the line ABOVE its verdict, and
``artefact_defect_close_check`` says ``[SKIPPED] no issue corpus``, which IS
the disclosure. Scanning the WHOLE output for a count or an explicit
nothing-statement gives **0 of 25**. The class is currently closed; this exists
to keep the fifth instance from landing.

The gate list is PARSED from the CI script rather than duplicated here, so a
gate added to CI is covered without anyone remembering to add it twice.

chip-AGNOSTIC: it reasons about process exit codes and output text only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent

# A gate discloses its scope with a NUMBER, or by saying plainly that there was
# nothing to examine. Both are honest; only silence is not.
_DISCLOSURE_RE = re.compile(
    r"\d"
    r"|\bno\s+(?:issue\s+)?corpus\b"
    r"|\bnone\b|\bnothing\b|\bnot\s+present\b|\bnot\s+a\s+directory\b"
    r"|\bSKIP\b|\bSKIPPED\b|\bVACUOUS\b|\bNOTHING_SCANNED\b",
    re.IGNORECASE)

_RUN_RE = re.compile(
    # Accepts BOTH `run` and its `run_*` variants. A wrapper added for one
    # gate (`run_tolerating_uncheckable`) silently escaped this parser, so any
    # gate wired through it would not be covered — a coverage hole in the very
    # check that exists to close coverage holes.
    r'^\s*run(?:_\w+)?\s+"([^"]+)"\s+"?(\$ROOT|\$PLUGIN)"?\s+(.+)$', re.M)


def parse_gates(script: Path) -> List[Tuple[str, str, str]]:
    """(label, cwd-token, command) for every `run` line in the CI script."""
    try:
        text = script.read_text(errors="replace")
    except OSError:
        return []
    return [(m.group(1), m.group(2), m.group(3).strip())
            for m in _RUN_RE.finditer(text)]


def _scratch_repo(base: Path) -> Path:
    """An empty but VALID git repository — several gates ask git for a
    tracked-file list, and a non-repo would make them fail for the wrong
    reason."""
    d = base / "empty"
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(d), "config", k, v], check=True)
    (d / "seed.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(d), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(d), "commit", "-qm", "base"], check=True)
    return d


def _expand(cmd: str, repo_root: Path, scratch: Path) -> List[str]:
    c = cmd.replace('"$PG/', str(_HERE) + "/")
    c = c.replace('"$ROOT/', str(repo_root) + "/")
    c = c.replace('"', "")
    c = c.replace("$PLUGIN", str(_PLUGIN))
    c = c.replace("$ROOT", str(scratch))
    return c.split()


def audit(repo_root: Path, timeout: int = 120) -> Tuple[str, List[Dict]]:
    script = repo_root / "tools" / "ci" / "repo_hygiene_gates.sh"
    gates = parse_gates(script)
    if not gates:
        # Never a silent PASS — this program's own denominator.
        return "NOTHING_SCANNED", []

    findings: List[Dict] = []
    with tempfile.TemporaryDirectory() as td:
        scratch = _scratch_repo(Path(td))
        for label, _wd, cmd in gates:
            argv = _expand(cmd, repo_root, scratch)
            try:
                r = subprocess.run(argv, cwd=str(scratch), capture_output=True,
                                   text=True, timeout=timeout)
            except (OSError, subprocess.SubprocessError) as exc:
                findings.append({
                    "gate": label, "kind": "GATE_UNRUNNABLE",
                    "detail": f"could not be driven against a scratch tree: {exc}",
                })
                continue
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode == 0 and not _DISCLOSURE_RE.search(out):
                findings.append({
                    "gate": label, "kind": "PASS_WITHOUT_DENOMINATOR",
                    "detail": ("answered PASS over an EMPTY tree without "
                               "disclosing that it examined nothing — this "
                               "output is indistinguishable from a real clean "
                               "run"),
                    "output_tail": out.strip().splitlines()[-1][:200]
                    if out.strip() else "(no output at all)",
                })
    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo_root", nargs="?", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args(argv)

    root = Path(a.repo_root).resolve() if a.repo_root else _PLUGIN.parents[2]
    verdict, findings = audit(root)
    gates = parse_gates(root / "tools" / "ci" / "repo_hygiene_gates.sh")

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"verdict": verdict, "gates_probed": len(gates),
             "findings": findings}, indent=2) + "\n")

    if verdict == "NOTHING_SCANNED":
        print(f"NOTHING_SCANNED: no `run` lines parsed from "
              f"{root}/tools/ci/repo_hygiene_gates.sh — this check would "
              f"otherwise report a clean result over an empty gate list, "
              f"which is the very defect it exists to catch.", file=sys.stderr)
        return 2

    for f in findings:
        print(f"  [{f['kind']}] {f['gate']}", file=sys.stderr)
        print(f"      {f['detail']}", file=sys.stderr)
        if f.get("output_tail"):
            print(f"      last line: {f['output_tail']}", file=sys.stderr)

    if findings:
        print(f"[FAIL] {len(findings)} gate(s) of {len(gates)} answer PASS "
              f"over an empty tree without disclosing it.", file=sys.stderr)
        return 1
    print(f"[PASS] all {len(gates)} CI gate(s) disclose what they examined "
          f"(probed against an empty tree).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
