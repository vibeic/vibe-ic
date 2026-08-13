#!/usr/bin/env python3
"""
vendored_attribution_present_check.py — vibe-ic#1043.

THE OBLIGATION, AND WHY IT NEEDS A MACHINE
==========================================
Apache-2.0 §4(b) and §4(d) attach to distributing the WORK. They do not attach
to publishing a run that used it. So withdrawing a run does not withdraw the
duty: if the vendored file stays in the tree, the record that names its origin
and licence has to stay with it.

#1043 was filed because a withdrawal branch appeared to delete attribution
records while the code they attribute stayed. MEASURED on a38902d1 and on
`withdraw/nonpassing-published-runs@a8e254ad`, that specific condition does NOT
reproduce — the withdrawal deletes 2 manifests and 0 Apache-2.0 files survive
under either, and all 330 it ships are covered. #1027, whose 33 restores the
issue measured against, is CLOSED.

What DOES reproduce is the reason nobody noticed either way: **nothing checks.**
MEASURED on a38902d1, this gate's first run:

    tracked SOURCE_MANIFEST.md                      : 9
    shipped files DECLARING Apache-2.0              : 493
      covered by a manifest at or above them        : 491
      NOT covered by any manifest                   : 2

    benchmark-data/ic/spm/v1.9.96_gf180mcuD/phase2/stage2/dft/cell_model_combined.v
        "Copyright 2022 GlobalFoundries PDK Authors"
    benchmark-data/ic/spm/v1.10.18_sky130A/phase2/stage2/dft/cell_model_combined.v
        "Copyright 2020 The SkyWater PDK Authors"

Two third-party PDK cell models shipped with no record naming where they came
from. Small, real, and on main — which is the point: the duty was being met by
habit, and habit leaves no verdict behind.

THE POPULATION IS THE FILE'S OWN DECLARATION
============================================
Not a directory list, not a vendor name list. A file is in scope because IT
SAYS it is Apache-2.0 — an SPDX tag or the standard header. That is the same
predicate the licence itself turns on, it needs no registry to stay current,
and a newly vendored file is in scope the moment it lands rather than when
someone remembers to add its directory somewhere.

ATTRIBUTION IS INHERITED DOWNWARD, which is how these records are actually
organised: a `SOURCE_MANIFEST.md` covers the subtree it sits in. The gate looks
for the NEAREST one at or above each file. It deliberately does not check the
manifest's CONTENTS against the file — that would be a second, much larger
claim (that every covered file is individually named), and asserting it here
while it is untrue of every existing manifest would make the gate red on
arrival and get it switched off.

chip-AGNOSTIC: the vendors above appear in MEASUREMENTS quoted in this
docstring, never in the predicate. Nothing here reasons about any IC, vendor,
SKU or process.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

#: An SPDX tag or the standard Apache-2.0 header sentence. Both spellings are
#: required: SPDX alone misses every vendored PDK file, which carries the long
#: header and no tag.
_APACHE = re.compile(
    r"SPDX-License-Identifier:\s*Apache-2\.0"
    r"|Licensed under the Apache License",
    re.I)

#: Text-ish sources only. A binary artefact carrying the bytes of a licence
#: header is not what §4 is about, and reading every GDS to find out is not
#: worth the minutes.
_SRC_SUFFIXES = (".v", ".sv", ".vh", ".svh", ".py", ".c", ".h", ".cc", ".cpp",
                 ".sh", ".tcl", ".vhd", ".vhdl")

_MANIFEST = "SOURCE_MANIFEST.md"
#: Only the head is read. A licence declaration lives at the top of a file by
#: universal convention, and scanning whole netlists would make this gate cost
#: minutes for nothing.
_HEAD_BYTES = 4000


def tracked_files(root: Path, sub: str) -> List[str]:
    """What git TRACKS, because distribution is what the obligation turns on.

    An untracked file on one machine is not something this repo ships.
    """
    p = subprocess.run(["git", "ls-files", sub], cwd=str(root),
                       capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        return []
    return [t for t in p.stdout.split() if t]


def declares_apache(path: Path) -> bool:
    try:
        return bool(_APACHE.search(path.read_text(errors="replace")[:_HEAD_BYTES]))
    except OSError:
        return False


def _covering(rel: str, manifest_dirs: List[str]) -> Optional[str]:
    best = None
    for d in manifest_dirs:
        if rel == d or rel.startswith(d + "/"):
            if best is None or len(d) > len(best):
                best = d
    return best


def audit(root: Path, sub: str) -> Dict[str, Any]:
    tracked = tracked_files(root, sub)
    manifests = [t for t in tracked if t.endswith(_MANIFEST)]
    manifest_dirs = sorted({str(Path(m).parent) for m in manifests})

    declared: List[str] = []
    uncovered: List[str] = []
    for t in tracked:
        if not t.endswith(_SRC_SUFFIXES):
            continue
        if not declares_apache(root / t):
            continue
        declared.append(t)
        if _covering(t, manifest_dirs) is None:
            uncovered.append(t)

    return {
        "program": "vendored_attribution_present_check",
        "root": str(root),
        "scope": sub,
        "tracked": len(tracked),
        "manifests": len(manifests),
        "apache_declared": len(declared),
        "covered": len(declared) - len(uncovered),
        "uncovered": sorted(uncovered),
        "pass": not uncovered,
    }


def _report(res: Dict[str, Any]) -> None:
    if res["tracked"] == 0:
        print(f"[CANNOT DETERMINE] vendored_attribution: nothing tracked under "
              f"{res['scope']} in {res['root']} — 0 file(s) examined, and this "
              f"is NOT a pass.")
        return
    if res["apache_declared"] == 0:
        # An honest empty population, stated. Distinguishable from a clean one.
        print(f"[SKIP] vendored_attribution: {res['tracked']} tracked file(s) "
              f"under {res['scope']}, NONE declaring Apache-2.0 — nothing to "
              f"attribute, and this is not a pass over any vendored file.")
        return
    for u in res["uncovered"]:
        print(f"[FAIL] NO_ATTRIBUTION: {u} declares Apache-2.0 and no "
              f"{_MANIFEST} at or above it names its origin")
    verdict = "PASS" if res["pass"] else "FAIL"
    print(f"[{verdict}] vendored_attribution: {res['apache_declared']} shipped "
          f"file(s) declare Apache-2.0; {res['covered']} covered by one of "
          f"{res['manifests']} {_MANIFEST}; {len(res['uncovered'])} uncovered "
          f"({res['tracked']} tracked file(s) examined)")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Every shipped file that DECLARES Apache-2.0 must have a "
                    "SOURCE_MANIFEST.md at or above it (vibe-ic#1043).")
    ap.add_argument("root", nargs="?", default=".",
                    help="repository root")
    ap.add_argument("--scope", default="benchmark-data",
                    help="path under the root to audit (default benchmark-data)")
    ap.add_argument("--json")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve()
    if not root.is_dir():
        print(f"[ERROR] not a directory: {root}", file=sys.stderr)
        return 2

    res = audit(root, a.scope)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(res, indent=2) + "\n")
    _report(res)

    if res["tracked"] == 0 or res["apache_declared"] == 0:
        # "I could not look" and "there was nothing to look at" are rc 2, never
        # 0 — the `_vacuous_exit` convention this repo applies to every gate.
        return 2
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
