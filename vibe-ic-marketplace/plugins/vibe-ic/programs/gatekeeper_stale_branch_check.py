#!/usr/bin/env python3
"""gatekeeper_stale_branch_check.py — the STALE-BRANCH / phantom-revert guard.

WHY THIS EXISTS
---------------
A PR branch cut from an OLDER base than the CURRENT `origin/main` tip carries a
trap. A naive `origin/main..HEAD` diff of such a branch shows a PHANTOM REVERT
of every commit that landed on main SINCE the fork point — so a blind
`git checkout HEAD -- <files>` land (or any "just take the PR's file versions"
merge) SILENTLY REVERTS those already-landed fixes. Two real PRs (#246, #247)
were each cut from a pre-previous-fix base; only a manual merge-base check
caught it, and both were landed correctly by CHERRY-PICKING the PR's OWN delta
(`git diff <merge-base>..HEAD`), which applies only what the PR changed and
preserves the intervening work.

This guard fossilizes that check so no future gatekeeper has to remember it. It
runs at review time (base=origin/main, head=PR-branch) and makes the risk
un-missable:

  FRESH  — merge-base(base, head) == base tip. The branch is current; an
           ordinary squash-merge cannot phantom-revert anything. rc 0.

  STALE  — merge-base != base tip. Commits landed on base since the fork. It
           then measures the ACTUAL phantom-revert surface:
             * intervening files = files changed on base since the fork
               (`git diff --name-only <merge-base>..<base-tip>`),
             * PR files          = files the PR changes
               (`git diff --name-only <merge-base>..<head>`),
             * OVERLAP           = PR files ∩ intervening files.
           OVERLAP is exactly the set a blind checkout would revert.
             - OVERLAP non-empty  -> rc 1 (BLOCK): a blind checkout WOULD
               revert landed work on these files; the land MUST be a cherry-pick
               of the PR's delta, then a grep of the intervening fixes' symbols
               to prove no false revert.
             - OVERLAP empty      -> rc 0 (ADVISORY): stale but no shared file,
               so a blind checkout could not phantom-revert; a cherry-pick of
               the true delta is still the recommended, drift-free land.

This never judges whether the PR's CHANGE is good (that is Step-2.7 + the other
gates). It only guards the LANDING METHOD against a silent revert.

MODES / CLI
-----------
    gatekeeper_stale_branch_check.py --repo <dir> --base <ref> --head <ref>
                                     [--json <out>]

EXIT CODES
----------
  0  FRESH, or STALE with no file overlap (advisory only)
  1  STALE with file overlap — phantom-revert risk; land via cherry-pick
  2  ERROR — bad usage / unresolvable ref / git failure (fail LOUD)

chip-AGNOSTIC / DETERMINISTIC: reasons over commit graph + changed-path sets
only; no IC / vendor / SKU literal.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

GATE_NAME = "gatekeeper_stale_branch_check"


def _git(repo: Path, *args: str) -> Tuple[int, str, str]:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _rev(repo: Path, ref: str) -> str:
    rc, out, err = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if rc != 0:
        raise RuntimeError(f"cannot resolve ref {ref!r}: {err.strip()[:200]}")
    return out.strip()


def _merge_base(repo: Path, a: str, b: str) -> str:
    rc, out, err = _git(repo, "merge-base", a, b)
    if rc != 0:
        raise RuntimeError(
            f"no merge-base for {a!r} and {b!r}: {err.strip()[:200]}")
    return out.strip()


def _changed_files(repo: Path, rng: str) -> List[str]:
    rc, out, err = _git(repo, "diff", "--name-only", rng)
    if rc != 0:
        raise RuntimeError(f"git diff --name-only {rng} failed: "
                           f"{err.strip()[:200]}")
    return [ln for ln in out.splitlines() if ln.strip()]


@dataclass
class StaleResult:
    verdict: str                       # "FRESH" | "STALE_ADVISORY" | "STALE_OVERLAP"
    rc: int
    base_tip: str
    merge_base: str
    intervening_commits: int
    overlap_files: List[str] = field(default_factory=list)
    summary: str = ""


def analyze(repo: Path, base: str, head: str) -> StaleResult:
    """Compute the stale-branch verdict for landing `head` onto `base`."""
    base_tip = _rev(repo, base)
    mb = _merge_base(repo, base, head)
    if mb == base_tip:
        return StaleResult("FRESH", 0, base_tip, mb, 0,
                           summary=(f"FRESH: merge-base == {base} tip "
                                    f"({base_tip[:9]}); ordinary squash-merge "
                                    "cannot phantom-revert."))
    # Stale: measure the phantom-revert surface.
    rc, out, _ = _git(repo, "rev-list", "--count", f"{mb}..{base_tip}")
    n_inter = int(out.strip() or "0") if rc == 0 else -1
    inter_files = set(_changed_files(repo, f"{mb}..{base_tip}"))
    pr_files = set(_changed_files(repo, f"{mb}..{head}"))
    overlap = sorted(inter_files & pr_files)
    if overlap:
        return StaleResult(
            "STALE_OVERLAP", 1, base_tip, mb, n_inter, overlap,
            summary=(
                f"STALE + OVERLAP: branch forked at {mb[:9]}, {n_inter} "
                f"commit(s) landed on {base} since, and the PR ALSO touches "
                f"{len(overlap)} of the files they changed "
                f"({', '.join(overlap[:6])}"
                f"{' …' if len(overlap) > 6 else ''}). A blind "
                "`git checkout HEAD -- <files>` land WOULD phantom-revert that "
                "landed work. LAND VIA CHERRY-PICK of the PR's own delta "
                f"(`git diff {mb[:9]}..{head}`), then grep the intervening "
                "fixes' symbols to prove no false revert."))
    return StaleResult(
        "STALE_ADVISORY", 0, base_tip, mb, n_inter, [],
        summary=(
            f"STALE (advisory): branch forked at {mb[:9]}, {n_inter} commit(s) "
            f"landed on {base} since, but the PR shares NO file with them — a "
            "blind checkout could not phantom-revert. Cherry-pick of the true "
            "delta is still the recommended, drift-free land."))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Stale-branch / phantom-revert guard: FAILs when a PR "
                    "branch forked from an older base AND touches a file that "
                    "landed on base since, so a blind checkout would revert it.")
    ap.add_argument("--repo", default=None, help="repo root (default: cwd)")
    ap.add_argument("--base", required=True,
                    help="base ref (normally origin/main)")
    ap.add_argument("--head", required=True, help="head ref (the PR branch)")
    ap.add_argument("--json", help="write a JSON report to this path")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else Path.cwd()
    try:
        res = analyze(repo, args.base, args.head)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {"gate": GATE_NAME, **asdict(res)}, indent=2) + "\n")

    stream = sys.stderr if res.rc != 0 else sys.stdout
    print(f"{'FAIL' if res.rc == 1 else 'PASS'}: {res.summary}", file=stream)
    return res.rc


if __name__ == "__main__":
    raise SystemExit(main())
