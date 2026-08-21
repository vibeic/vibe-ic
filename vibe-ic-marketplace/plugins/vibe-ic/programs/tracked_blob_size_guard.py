#!/usr/bin/env python3
"""tracked_blob_size_guard.py — the size guard `.gitignore` already promised.

THIS GATE BLOCKS (rc=1) when a tracked blob exceeds the commit ceiling.

WHY IT EXISTS
-------------
On 2026-07-25 the repo-root `.gitignore` stopped ignoring published layout
artefacts:

    !benchmark-data/ic/**/*.gds
    !benchmark-data/ic/**/*.def

and the comment beside them states the policy that makes that safe:

    大 die 的大檔（>50MB）由 benchmark_evidence_structure_check 的 size-guard
    擋、改走 git-lfs / GitHub Release（sha256 存 MANIFEST）。

That guard was never written. `benchmark_evidence_structure_check.py` contains
no size rule of any kind. So the negation is live and the thing that was
supposed to bound it is a sentence.

WHAT THAT COSTS, MEASURED 2026-07-26 against this tree. Ten untracked `.gds`
under `benchmark-data/ic/` are between 74 MB and 105 MB and are ACCEPTED by
the negation above. Two of them — `sha256/phase3/stage3/pnr/chip_top.gds` and
`sha256/phase3/stage4/foundry_handoff/chip_top.gds`, both 105.18 MB — are over
GitHub's 100 MB per-file HARD limit. One `git add` of either and the push is
rejected outright, after the objects are already in local history, which is
the expensive kind of mistake to undo.

WHY A SIZE RULE RATHER THAN AN EXTENSION RULE. The measured spread of GDS in
this project is three orders of magnitude — 0.73 MB for `spm`, 105 MB for
`sha256`. An extension cannot express that, which is why the publisher's
`_RAW_EXTS` drop threw away 0.8 MB artefacts a reviewer wants in order to
avoid 105 MB ones nobody can commit. Size is the property that actually
matters, so size is what is checked.

NO BASELINE, DELIBERATELY. Measured before choosing the ceiling: the largest
tracked blob in this repo is 26.75 MB and exactly ONE tracked blob exceeds
20 MB. A 50 MB ceiling therefore starts with zero debt, so there is no
register to shrink and no pre-existing violation to grant standing permission
to. A gate that starts clean is a gate that stays readable.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# GitHub warns at 50 MB and REFUSES at 100 MB. The ceiling is the warning
# line, not the refusal line: a gate that only fires at the point where the
# push already fails has told you nothing you were not about to learn.
_CEILING = 50 * 1000 * 1000
_GITHUB_HARD = 100 * 1000 * 1000


def oversized(repo: Path, ref: str = "HEAD", ceiling: int = _CEILING):
    """(path, bytes) for every tracked blob above `ceiling`, largest first."""
    r = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "-l", "--full-tree", ref],
        capture_output=True, text=True)
    if r.returncode != 0:
        # An empty list reads as "nothing is oversized". Refuse instead —
        # the same rule the NDA scan learned in #416.
        raise RuntimeError(
            f"git could not list the tree at {ref}: {r.stderr.strip()[:200]}")
    out, seen = [], 0
    for line in r.stdout.splitlines():
        try:
            meta, path = line.split("\t", 1)
            parts = meta.split()
            if parts[1] != "blob":          # gitlinks/trees carry no size
                continue
            size = int(parts[3])
        except (ValueError, IndexError):
            continue
        seen += 1
        if size > ceiling:
            out.append((path, size))
    return sorted(out, key=lambda t: -t[1]), seen


def _toplevel(repo: Path) -> Path:
    r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() \
        else repo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--ceiling-mb", type=float, default=_CEILING / 1e6)
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)

    repo = _toplevel(Path(a.repo).resolve())
    ceiling = int(a.ceiling_mb * 1000 * 1000)
    try:
        big, seen = oversized(repo, a.ref, ceiling)
    except RuntimeError as exc:
        print(f"[ERROR] tracked_blob_size_guard: {exc}\n"
              "   Nothing was checked. This is NOT a clean result.")
        return 2

    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {"ref": a.ref, "ceiling_bytes": ceiling, "blobs": seen,
             "oversized": [{"path": p, "bytes": s} for p, s in big]},
            indent=2) + "\n")

    if big:
        print(f"[FAIL] {len(big)} tracked blob(s) exceed the "
              f"{ceiling / 1e6:.0f} MB commit ceiling. Route these to "
              f"git-lfs or a GitHub Release and keep the sha256 in the "
              f"MANIFEST, which is what makes the artefact verifiable "
              f"without being stored:")
        for p, s in big:
            over = "  >>> OVER GITHUB'S 100 MB HARD LIMIT" \
                if s > _GITHUB_HARD else ""
            print(f"   {s / 1e6:8.2f} MB  {p}{over}")
        return 1

    print(f"[PASS] tracked_blob_size_guard: {seen} tracked blob(s) at "
          f"{a.ref}, none above {ceiling / 1e6:.0f} MB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
