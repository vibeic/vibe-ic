#!/usr/bin/env python3
"""Every abort our EDA fork downgrades to a warning must still be visible to the flow.

WHY THIS EXISTS (vibe-ic#552)
=============================
The forks carry a standing doctrine: where stock aborts, we warn and continue, so
a post-route ECO is not killed by a condition the flow can handle. `RSZ-0089`,
`DPL-0033`, `DRT-0305`, `DRT-627` are all instances.

Every one of those downgrades moves a condition OUT of the set the flow's gates
can see, **by construction** — the downgrade exists precisely to stop the tool
emitting an error, and the gates match on `[ERROR ...]`.

Measured instance: `vibeic/OpenROAD 8d040d56c` downgrades an inaccessible pin
from the fatal `DRT-0073` to a `DRT-627` warning. `phase3_one_shot_runner`'s
`_route_fail_markers` are six strings, every one an `[ERROR ...]`. So the flow
printed `routing complete: YES` for a design carrying a pin the router never
reached, and nothing anywhere looked at `DRT-627`.

THE ASYMMETRY IS THE DEFECT, NOT THE MISSING STRING
====================================================
Adding `DRT-627` to a list fixes one instance and leaves the shape: the next
downgrade lands in a fork, months later, in a different repo, and nothing
connects it to the consumer that needs to know. So this check asserts the
REGISTRY is complete rather than asserting any particular ID is present:

  * `DOWNGRADES` below names every warn-level ID our forks emit in place of an
    upstream abort, with the fork commit and the consumer that must see it.
  * Each entry's consumer is checked to actually reference the ID.
  * A downgrade with no consumer is a FAIL, not a note — that is the whole
    finding.

WHAT THIS CANNOT DO, STATED
===========================
It cannot discover a downgrade nobody registered. Reading the fork sources over
the network on every gate run would be slow and would fail closed on an offline
maintainer, which is worse. So the registry is authored, and the honest scope is
"the downgrades we know about are wired" — not "no unwired downgrade exists".
`--audit-fork <path>` compares against a checked-out fork when one is available,
which is how a new downgrade gets found; without it the check says so rather
than implying coverage it does not have.

Exit: 0 every registered downgrade is visible, 1 one is not, 2 nothing compared.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

RC_PASS, RC_FAIL, RC_NOT_CHECKED = 0, 1, 2


@dataclass(frozen=True)
class Downgrade:
    """One abort our fork turned into a warning, and who must notice."""
    ident: str          #: the warn-level message id, e.g. "DRT-627"
    replaces: str       #: the upstream abort it stands in for
    fork: str           #: repo + commit that introduced the downgrade
    why: str            #: why the downgrade is correct
    consumer: str       #: repo-relative file that must reference `ident`


#: THE REGISTRY. Adding a downgrade to a fork without adding it here is what
#: #552 was: the fix shipped, the flow never learned about it.
DOWNGRADES: tuple = (
    Downgrade(
        ident="DRT-627",
        replaces="DRT-0073 (No access point for <inst>/<term>)",
        fork="vibeic/OpenROAD 8d040d56c",
        why=("the fatal form is raised inside an OpenMP region in "
             "FlexPA::updateDirtyInsts, so it crosses the parallel boundary "
             "and std::terminate kills the tool mid-ECO with no diagnostic"),
        consumer="programs/phase3_one_shot_runner.py",
    ),
)


def _programs_root(start: Path) -> Path:
    return Path(__file__).resolve().parent if start is None else start


def check(plugin_root: Path) -> List[dict]:
    """One finding per registered downgrade whose consumer cannot see it."""
    findings: List[dict] = []
    for d in DOWNGRADES:
        target = plugin_root / d.consumer
        if not target.is_file():
            findings.append({**asdict(d), "problem": "consumer file missing",
                             "path": str(target)})
            continue
        text = target.read_text(errors="replace")
        # The ID must appear in a MATCHER, not merely in the file. My first
        # version stripped whole-line comments and searched for the bare id —
        # and a deliberate mutation (breaking the regex to DRT-999999) still
        # PASSED, because the id also occurs in an inline comment and in the
        # human-readable report text. Neither of those makes the flow see
        # anything. So the id must appear inside something that MATCHES: a
        # compiled pattern, a membership test, or a marker tuple.
        code = "\n".join(ln for ln in text.splitlines()
                         if not ln.lstrip().startswith("#"))
        matcher = re.compile(
            r"(?:re\.compile|re\.search|re\.findall|re\.match|in\s+log_txt|"
            r"_markers\s*=\s*\()[^\n]*" + re.escape(d.ident), re.I)
        if not matcher.search(code):
            findings.append({
                **asdict(d), "path": str(target),
                "problem": (f"{d.consumer} never matches {d.ident} in code, so "
                            f"the condition {d.replaces} used to raise is "
                            f"invisible to it"),
            })
    return findings


def audit_fork(fork_src: Path) -> List[str]:
    """Warn-level DRT/RSZ/DPL ids in a checked-out fork that are NOT registered.

    Best-effort and explicitly scoped: it reads `logger_->warn(<TOOL>, <id>` and
    reports ids no registry entry names. It cannot tell a downgrade from a
    warning that was always a warning — that judgement stays with the author —
    so its output is a prompt to check, never a verdict.
    """
    known = {d.ident.split("-")[-1].lstrip("0") or "0" for d in DOWNGRADES}
    seen: set = set()
    pat = re.compile(r"logger_->warn\(\s*(\w+)\s*,\s*(\d+)", re.S)
    for f in fork_src.rglob("*.cpp"):
        try:
            for tool, num in pat.findall(f.read_text(errors="replace")):
                if num.lstrip("0") not in known:
                    seen.add(f"{tool}-{num}  {f.relative_to(fork_src)}")
        except OSError:
            continue
    return sorted(seen)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plugin_root", nargs="?", default=None,
                    help="plugin root (default: this program's parent)")
    ap.add_argument("--audit-fork", default=None,
                    help="path to a checked-out fork src/ to scan for "
                         "unregistered warn ids")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    root = (Path(a.plugin_root).resolve() if a.plugin_root
            else Path(__file__).resolve().parents[1])
    if not DOWNGRADES:
        print("[NOT CHECKED] the downgrade registry is empty — nothing was "
              "compared, which is not a pass", file=sys.stderr)
        return RC_NOT_CHECKED

    findings = check(root)
    extra = audit_fork(Path(a.audit_fork)) if a.audit_fork else None

    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps({
            "program": "fork_downgrade_visibility_check",
            "registered": len(DOWNGRADES),
            "findings": findings,
            "unregistered_warn_ids": extra,
        }, indent=2) + "\n", encoding="utf-8")

    if extra:
        print(f"[NOTE] {len(extra)} warn id(s) in the fork are not in the "
              f"registry. Not all are downgrades — check each:", file=sys.stderr)
        for e in extra[:20]:
            print(f"    {e}", file=sys.stderr)

    if findings:
        print(f"[FAIL] {len(findings)} downgrade(s) our fork ships are invisible "
              f"to the consumer that must see them:", file=sys.stderr)
        for f in findings:
            print(f"    {f['ident']} (replaces {f['replaces']})\n"
                  f"      fork: {f['fork']}\n"
                  f"      {f['problem']}", file=sys.stderr)
        return RC_FAIL

    scope = ("" if a.audit_fork else
             " (registry only — pass --audit-fork to scan a fork for "
             "unregistered warn ids)")
    print(f"[PASS] all {len(DOWNGRADES)} registered fork downgrade(s) are "
          f"referenced by the consumer that must notice them{scope}")
    return RC_PASS


if __name__ == "__main__":
    sys.exit(main())
