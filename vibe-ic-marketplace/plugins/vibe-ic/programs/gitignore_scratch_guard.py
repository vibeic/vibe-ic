#!/usr/bin/env python3
"""gitignore_scratch_guard.py — ORGANIC #720

Durable CI guard that the repo-root `.gitignore` carries the ROOT-ANCHORED
`/_*.js` rule, so session scratch Workflow/orchestration scripts created at the
repo root (`_review_backlog_*.js`, `_sweep_workflow.js`, …) can never be swept
into a commit and pushed to github. Also verifies the rule is correctly
root-anchored — it must NOT match a legitimately-tracked `_*.js` living in a
SUBDIR (the mcp-eda devices `_registry.js`).

This is the program-first persistence of the hygiene rule: a prose request a
future editor could drop becomes a CI-checkable invariant.

TWO POPULATIONS, AND WHY THEY ARE NOW SEPARATED BY A FLAG
=========================================================
The DEFAULT population is COMMIT-DETERMINED: four invariants that are answered
identically by any checkout of a given commit — the rule's presence, the two
`check-ignore` probes, and the tracked-file list. That is what makes this gate
safe to wire into `tools/ci/repo_hygiene_gates.sh`, which is itself audited by
`gate_host_independence_check`: every gate in that script is run TWICE at the
same commit (working checkout vs a fresh throwaway worktree) and must give the
same verdict line AND the same exit code.

`--include-worktree` adds the second population: untracked-and-unignored paths
whose name carries a scratch token. That one is a fact about a CHECKOUT, not
about a commit — `git status` untracked output is by definition not in the
commit — so wiring it into the host-independence corpus would turn a passing
probe red the moment any agent left a scratch file in the tree. It is wired
REPORT-ONLY into `tools/gatekeeper-land.sh` instead, where "what is sitting in
THIS tree right now" is the question actually being asked.

MEASURED 2026-08-03 over 250 checkouts of this repo on one host: the default
population is 0 red (`rule_present` true in 250/250, `subdir_registry_ignored`
false in 250/250, no tracked root `_*.js` anywhere). The worktree population is
61 red, every one of them the single path `vibe-ic-marketplace/
scratch_geom_signoff_tests/` in a checkout BEHIND origin/main — `.gitignore`
lines 139-143 already ignore it at the tip, verified with `check-ignore -v`.

Exit codes:
    0  the commit-determined invariants hold (and, with --include-worktree,
       no unignored scratch path is sitting in the tree)
    1  rule missing / mis-anchored / a tracked file would be affected
    2  NOTHING WAS MEASURED — not a git repo, or git would not answer. This is
       not a pass and must never be reported as one.

chip-AGNOSTIC: pure repo-hygiene path rule; no chip / vendor / SKU literal.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

_RULE = "/_*.js"
# a legitimately-tracked subdir _*.js that the ROOT anchor must NOT capture
_SUBDIR_TRACKED = ("vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/src/devices/"
                   "_registry.js")
_SCRATCH_PROBE = "_scratch_probe.js"
_SCRATCH_TOKENS = ("scratch", "_gds_closure", "scratchpad")

# EXIT CODES ARE WRITTEN AS LITERALS AT EVERY `return`, not as named
# constants. `gate_skip_routing_check` resolves a gate's skip terminators
# STATICALLY, and an exit expression it cannot fold — a module-level name — is
# reported as unanalysable, which takes the skip path out of the population
# that checks whether a skip reaches a consumer channel. Three gates in this
# repo are already unanalysable for exactly that reason; a gate landed in a
# campaign about unrouted skip paths should not be the fourth.


class CannotMeasure(Exception):
    """git would not answer. Distinct from "the rule is missing"."""


def _git(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root),
                          capture_output=True, text=True)


def _repo_root(start: Path) -> Optional[Path]:
    cp = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                        cwd=str(start), capture_output=True, text=True)
    return Path(cp.stdout.strip()) if cp.returncode == 0 else None


def _check_ignore(root: Path, relpath: str) -> bool:
    """Does the ignore RULE SET capture `relpath`?

    `--no-index` IS THE WHOLE ASSERTION. Without it, `git check-ignore` reports
    "not ignored" (rc 1) for any path that is TRACKED, whatever the rules say —
    `_registry.js` is tracked, so `subdir_registry_ignored` was a CONSTANT
    False and the root-anchoring half of this gate's own docstring could not
    fire. Proven with a mutant that plants BOTH `/_*.js` and the unanchored
    `_*.js`: `check-ignore --no-index` returns 0 (the subdir file IS captured)
    while this gate returned 0 PASS with `subdir_registry_ignored: false`.

    rc 128 (git unavailable / not a repo) is NOT "not ignored" — it is "no
    answer", and it raises rather than being folded into a finding.
    """
    cp = _git(root, "check-ignore", "--no-index", "--", relpath)
    if cp.returncode == 0:
        return True
    if cp.returncode == 1:
        return False
    raise CannotMeasure(
        f"`git check-ignore --no-index -- {relpath}` returned "
        f"{cp.returncode}: {(cp.stderr or '').strip()[:160]}")


def worktree_scratch(root: Path) -> List[str]:
    """UNTRACKED-and-unignored paths carrying a scratch token.

    A FACT ABOUT THIS CHECKOUT, not about the commit — hence the flag.

    #720 fixed the extension it happened to meet (`/_*.js`) and this guard
    probed that one rule with one synthetic filename, so it reported rc 0 while
    four scratch paths sat untracked-and-unignored in the working tree for 3 to
    9 days: `scratchpad/`, `scratchpad_pr487_msg.txt`, `_gds_closure/`, and
    `vibe-ic-marketplace/scratch_geom_signoff_tests/`. All four are ignored at
    origin/main today (`.gitignore` 139-143), which is why this population is
    reporting-only rather than blocking: its one measured instance is closed.

    Untracked-but-not-ignored is the state one `git add -A` turns into a
    commit, which is why this repo forbids `-A`. Probing a rule proves the
    rule; listing the tree proves the outcome, and only the second notices a
    category the rule does not cover.
    """
    cp = _git(root, "status", "--porcelain")
    if cp.returncode != 0:
        raise CannotMeasure(
            f"`git status --porcelain` returned {cp.returncode}: "
            f"{(cp.stderr or '').strip()[:160]}")
    untracked = [ln[3:] for ln in cp.stdout.splitlines()
                 if ln.startswith("?? ")]
    return sorted(f for f in untracked
                  if any(tok in f.lower() for tok in _SCRATCH_TOKENS))


def audit(root: Path, include_worktree: bool = False) -> dict:
    """Evidence dict. Raises CannotMeasure when git will not answer.

    THE PRECEDENCE BUG THIS REPLACES. The old guard wrote

        if root is None or not (root / ".git").exists() and not root.is_dir():

    which Python parses as ``A or (B and C)``. For any existing non-repo
    directory ``C`` is False, so the rc-2 branch was UNREACHABLE: every git
    call then failed and the program exited 1 — reporting "I could not look"
    as "the rule is missing", the repo's own vacuous-pass doctrine inverted.
    Measured against an empty non-repo directory: rc=1, not 2.
    """
    if not root.is_dir():
        raise CannotMeasure(f"{root} is not a directory")
    top = _repo_root(root)
    if top is None:
        raise CannotMeasure(f"{root} is not a git repository")
    root = top

    gi = root / ".gitignore"
    rule_present = gi.is_file() and _RULE in gi.read_text(
        encoding="utf-8", errors="replace").splitlines()
    root_scratch_ignored = _check_ignore(root, _SCRATCH_PROBE)
    subdir_registry_ignored = _check_ignore(root, _SUBDIR_TRACKED)

    ls = _git(root, "ls-files")
    if ls.returncode != 0:
        raise CannotMeasure(
            f"`git ls-files` returned {ls.returncode}: "
            f"{(ls.stderr or '').strip()[:160]}")
    tracked_root_scratch = [f for f in ls.stdout.splitlines()
                            if "/" not in f and f.startswith("_")
                            and f.endswith(".js")]

    violations: List[str] = []
    if not rule_present:
        violations.append(
            f"root .gitignore does not carry the literal line `{_RULE}`")
    if not root_scratch_ignored:
        violations.append(
            f"a root scratch script (`{_SCRATCH_PROBE}`) is NOT ignored")
    if subdir_registry_ignored:
        violations.append(
            f"the rule is MIS-ANCHORED: it also captures `{_SUBDIR_TRACKED}`, "
            "a legitimately-tracked subdir file")
    for f in tracked_root_scratch:
        violations.append(f"a root scratch script is already TRACKED: {f}")

    ev = {
        "program": "gitignore_scratch_guard",
        "invariants_checked": 4,
        "rule_present": rule_present,
        "root_scratch_ignored": root_scratch_ignored,
        "subdir_registry_ignored": subdir_registry_ignored,
        "tracked_root_scratch": tracked_root_scratch,
        "worktree_scan": "on" if include_worktree else "off",
        "violations": violations,
    }
    if include_worktree:
        found = worktree_scratch(root)
        ev["unignored_scratch_in_tree"] = found
        ev["worktree_violations"] = [
            f"untracked-and-unignored scratch path in the tree: {f}"
            for f in found]
    ev["ok"] = not violations
    return ev


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Guard the #720 root-anchored /_*.js gitignore rule.")
    ap.add_argument("--root", default=None,
                    help="repo root (default: git toplevel of CWD)")
    ap.add_argument("--json", default=None, help="write evidence JSON here")
    ap.add_argument("--include-worktree", action="store_true",
                    help="ALSO list untracked-and-unignored scratch paths "
                         "sitting in THIS checkout. Host-dependent by "
                         "construction, so it is not part of the default "
                         "population; see --worktree-blocking.")
    ap.add_argument("--worktree-blocking", action="store_true",
                    help="with --include-worktree: make those paths exit 1 "
                         "instead of being reported. Off by default — the one "
                         "measured instance is already ignored at the tip.")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else Path.cwd()
    try:
        ev = audit(root, include_worktree=args.include_worktree)
    except CannotMeasure as e:
        print(f"[SKIP] gitignore_scratch_guard: {e} — NOTHING was measured, "
              "which is not a pass.", file=sys.stderr)
        return 2   # CANNOT MEASURE

    text = json.dumps(ev, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(text + "\n")
    print(text)

    wt = ev.get("worktree_violations") or []
    blocking = list(ev["violations"]) + (
        wt if (args.include_worktree and args.worktree_blocking) else [])
    for v in ev["violations"]:
        print(f"  VIOLATION {v}", file=sys.stderr)
    for v in wt:
        tag = "VIOLATION" if args.worktree_blocking else "REPORT"
        print(f"  {tag} {v}", file=sys.stderr)

    # THE VERDICT LINE, and it carries its own denominator. Four
    # commit-determined invariants is a real population; a reader can tell this
    # from a run that examined nothing, and `gate_host_independence_check`
    # compares this exact line between two trees at the same commit.
    n = 4
    if blocking:
        print(f"[FAIL] gitignore_scratch_guard: {n} commit-determined "
              f"invariant(s) checked, {len(blocking)} violation(s)")
        return 1   # findings
    if wt:
        print(f"[PASS] gitignore_scratch_guard: {n} commit-determined "
              f"invariant(s) checked, 0 violation(s) "
              f"({len(wt)} worktree-local scratch path(s) REPORTED, not "
              f"blocking)")
        return 0   # pass
    print(f"[PASS] gitignore_scratch_guard: {n} commit-determined "
          f"invariant(s) checked, 0 violation(s)")
    return 0   # pass


if __name__ == "__main__":
    sys.exit(main())
