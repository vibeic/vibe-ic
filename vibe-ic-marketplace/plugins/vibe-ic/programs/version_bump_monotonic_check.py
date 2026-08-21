#!/usr/bin/env python3
"""version_bump_monotonic_check.py — strict version-bump gate for the
core-agent loop (extracted from vibe-ic:core-agent-loop §Step 3).

The skill's Step 3 says the core-agent must "bump the patch version in
BOTH locations" before pushing. Two distinct invariants are implied:

  (A) plugin.json.version == marketplace.json plugins[].version  (equality)
      — already enforced by ``marketplace_version_sync_check.py``.

  (B) the NEW version is STRICTLY GREATER than the PREVIOUS commit's
      version (monotonic bump).  No existing program checked this. If the
      agent commits without bumping (or accidentally lowers the version),
      ``/plugin update`` sees no version change and silently no-ops,
      leaving end-users on a stale cache.

This program implements invariant (B): it reads the current working-tree
``plugin.json.version`` and compares it (semver) against the version
recorded in ``plugin.json`` at a baseline git ref (default: HEAD, i.e.
the previous commit). PASS iff current > baseline. It ALSO re-asserts
(A) so the loop has one self-contained gate.

Semver compare is numeric per-component (so 0.2.10 > 0.2.9, not the
lexical opposite).

Usage
-----
    # compare working-tree plugin.json vs the version at HEAD
    python3 version_bump_monotonic_check.py --plugin-json <path/plugin.json> \
            [--marketplace-json <path/marketplace.json>] [--base HEAD] \
            [--json <out>]

    # explicit two-value compare (no git; for testing / CI)
    python3 version_bump_monotonic_check.py --current 0.2.13 --previous 0.2.12

THREE CASES, NOT TWO (fixed 2026-07-22)
---------------------------------------
This program originally reduced current-vs-previous to ONE boolean,
``bump_ok = current > previous``, so "no version change" and "version went
BACKWARDS" both landed in ``not bump_ok`` and returned the SAME exit code 1.
It could not tell them apart.

That conflation made the gate structurally unpassable in PR CI. The
documented workflow (see skills/gatekeeper-loop, agents/repo-gatekeeper) is
that contributing agents open **VERSION-LESS** PRs and the gatekeeper alone
assigns the monotonic version at merge — two in-flight PRs that each
self-bumped would collide. So ``current == previous`` is the sanctioned
HAPPY PATH on every authoring PR, and a gate that fails on it fails by
construction on every PR. ``gatekeeper_review.py`` already modelled this
correctly with its ``--version-by-gatekeeper`` deferral; that flag was simply
never plumbed into this standalone program, which .github/workflows/
gatekeeper-ci.yml invokes DIRECTLY. This program now takes the same flag.

    case                          default    --version-by-gatekeeper
    no version change (cur==prev)   FAIL(1)      PASS(0)   <- documented path
    monotonic bump    (cur> prev)   PASS(0)      PASS(0)
    backwards         (cur< prev)   FAIL(1)      FAIL(1)   <- the real defect
    malformed                       ERR(2)       ERR(2)

The default stays STRICT so the two contexts that genuinely require a bump —
the direct-push core-agent loop, and the gatekeeper's post-assignment re-run
after gatekeeper_assign_version.py writes the version — keep full enforcement.

Exit codes
----------
    0   PASS — current strictly greater than previous, OR unchanged under
            --version-by-gatekeeper (and, if a marketplace.json was given,
            equality holds).
    1   FAIL — current < previous (REGRESSION, always), current == previous
            without --version-by-gatekeeper (no bump), OR
            plugin.json != marketplace.json.
    2   argument / I/O / git error (e.g. baseline ref has no plugin.json,
            malformed version) — an HONEST error, never a silent PASS.

Missing files / unparseable versions -> rc 2. There is no vacuous PASS
path: a bump cannot be "verified" without two real, comparable versions.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple


_SEMVER_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)")


def parse_semver(v: str) -> Optional[Tuple[int, int, int]]:
    """Parse 'X.Y.Z' (optional leading v) into a numeric tuple, or None."""
    if not isinstance(v, str):
        return None
    m = _SEMVER_RE.match(v)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _read_json_version(path: Path) -> Optional[str]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return d.get("version")


def _read_marketplace_version(path: Path) -> Optional[str]:
    """Return plugins[0].version (or first plugin with a version)."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    plugins = d.get("plugins")
    if not isinstance(plugins, list):
        return None
    for entry in plugins:
        if isinstance(entry, dict) and entry.get("version") is not None:
            return entry.get("version")
    return None


def _git_show_version(repo_dir: Path, ref: str, rel_path: str) -> Optional[str]:
    """git show <ref>:<rel_path> -> parse .version. None on any failure."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_dir), "show", f"{ref}:{rel_path}"],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout).get("version")
    except Exception:
        return None


def _git_path_changed(repo_dir: Path, ref: str, rel_path: str) -> Optional[bool]:
    """Did THIS CHANGE touch `rel_path`?

    Diffs from the MERGE BASE of `ref` and HEAD — not from `ref` itself. `ref`
    is the base-BRANCH TIP, so diffing it directly against the working tree
    also reports every commit that landed on the base while this PR sat open,
    and a version-less PR would look like it had edited the version whenever
    `main` moved. The merge base isolates what this change actually authored.

    Returns None when git cannot answer, so an unknown NEVER becomes a silent
    'unchanged' (which would be a vacuous pass)."""
    def _run(args: List[str]):
        try:
            return subprocess.run(["git", "-C", str(repo_dir), *args],
                                  capture_output=True, text=True, check=False)
        except OSError:
            return None

    mb = _run(["merge-base", ref, "HEAD"])
    origin = mb.stdout.strip() if (mb is not None and mb.returncode == 0) else ref

    out = _run(["diff", "--name-only", origin, "--", rel_path])
    if out is None or out.returncode != 0:
        return None
    return bool(out.stdout.strip())


@dataclass
class Report:
    passed: bool
    current: Optional[str]
    previous: Optional[str]
    bump_ok: bool
    equality_checked: bool
    equality_ok: Optional[bool]
    reason: str
    # The THREE-WAY verdict on current-vs-previous. "unchanged" is what a
    # version-less authoring PR looks like; it is NOT the same fact as
    # "regressed", and the two must never share an exit code by accident.
    change: str = "unknown"          # "bumped" | "unchanged" | "regressed"
    deferred: bool = False           # unchanged + version_by_gatekeeper -> PASS


def _next_canonical(t: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """The single successor version per the BINDING scheme owned by
    gatekeeper_assign_version.next_version(): patch 0..99, then x.y.99 ->
    x.(y+1).0."""
    major, minor, patch = t
    if patch < 99:
        return (major, minor, patch + 1)
    return (major, minor + 1, 0)


def evaluate(current: Optional[str], previous: Optional[str],
             market: Optional[str], equality_checked: bool,
             version_by_gatekeeper: bool = False,
             version_file_touched: Optional[bool] = None) -> Tuple[Report, int]:
    """Three-way compare of current vs previous.

    ``version_by_gatekeeper=True`` marks the VERSION-LESS AUTHORING PR context
    (the documented normal path: contributing agents open PRs that do not touch
    plugin.json / marketplace.json, and the gatekeeper assigns the monotonic
    version at merge). In that context ``current == previous`` is the expected
    happy path and PASSES. It does NOT soften anything else: a version that
    goes BACKWARDS still FAILS with or without the flag, and the marketplace
    equality invariant is still enforced in every case.

    ``version_file_touched=False`` is the DIRECT evidence of a version-less PR
    (the diff does not modify plugin.json at all), as opposed to the ``cur ==
    prev`` proxy. The two agree when CI checks out the PR's *merge* commit
    (actions/checkout@v4's default on ``pull_request``), because the merge
    inherits the base's version. They DIVERGE when the head ref is checked out
    directly and ``main`` has since moved ahead — then an untouched version
    file reads as "regressed" purely because main advanced, which is not a
    defect of the PR. Trusting the diff makes the verdict independent of the
    checkout strategy. This cannot be gamed: a PR that never touches the
    version file cannot introduce a bad version.
    """
    cur_t = parse_semver(current) if current is not None else None
    prev_t = parse_semver(previous) if previous is not None else None

    if cur_t is None:
        return Report(False, current, previous, False, equality_checked,
                      None, f"current version unparseable: {current!r}"), 2
    if prev_t is None:
        return Report(False, current, previous, False, equality_checked,
                      None, f"previous version unparseable: {previous!r}"), 2

    # THREE distinct facts, never collapsed into one boolean.
    if cur_t > prev_t:
        change = "bumped"
    elif cur_t == prev_t:
        change = "unchanged"
    else:
        change = "regressed"
    bump_ok = change == "bumped"

    equality_ok: Optional[bool] = None
    if equality_checked:
        mkt_t = parse_semver(market) if market is not None else None
        if market is None or mkt_t is None:
            return Report(False, current, previous, bump_ok, True, False,
                          f"marketplace version unparseable: {market!r}",
                          change), 2
        equality_ok = (current == market) or (cur_t == mkt_t)

    # VERSION-LESS PR, established from the DIFF rather than inferred from a
    # value comparison. Nothing to enforce: this change does not touch the
    # version at all, so it can neither skip nor reverse one. Whatever the
    # comparison says here is an artifact of where `main` happens to sit.
    if version_by_gatekeeper and version_file_touched is False:
        if equality_checked and not equality_ok:
            return Report(False, current, previous, False, True, False,
                          f"plugin.json {current} != marketplace.json "
                          f"{market}", change), 1
        return Report(True, current, previous, False, equality_checked,
                      equality_ok,
                      f"OK: version-less authoring PR — the diff does not "
                      f"touch plugin.json (at {current}); the gatekeeper "
                      f"assigns the monotonic version at merge"
                      + (" (marketplace in sync)" if equality_checked else ""),
                      change, True), 0

    # A backwards version is the real defect this gate exists to catch. It
    # fails unconditionally — the gatekeeper flag does NOT excuse it.
    if change == "regressed":
        return Report(False, current, previous, False, equality_checked,
                      equality_ok,
                      f"version REGRESSED: current {current} < previous "
                      f"{previous}", change), 1

    if change == "unchanged":
        if not version_by_gatekeeper:
            # Direct-push / post-assignment context: a missing bump means
            # `/plugin update` no-ops and users stay on a stale cache.
            return Report(False, current, previous, False, equality_checked,
                          equality_ok,
                          f"version not bumped: current {current} == previous "
                          f"{previous}", change), 1
        # Version-less authoring PR — the DOCUMENTED normal case.
        if equality_checked and not equality_ok:
            return Report(False, current, previous, False, True, False,
                          f"plugin.json {current} != marketplace.json "
                          f"{market}", change), 1
        return Report(True, current, previous, False, equality_checked,
                      equality_ok,
                      f"OK: no version change at {current} — version-less "
                      f"authoring PR; the gatekeeper assigns the monotonic "
                      f"version at merge"
                      + (" (marketplace in sync)" if equality_checked else ""),
                      change, True), 0

    if equality_checked and not equality_ok:
        return Report(False, current, previous, True, True, False,
                      f"plugin.json {current} != marketplace.json "
                      f"{market}", change), 1

    # A forward jump larger than one step is REPORTED but not failed: this
    # program's baseline is the PR's merge-base, and `main` advances many times
    # a day, so a legitimate PR can legally sit several versions behind. The
    # one-step rule is owned + enforced by gatekeeper_assign_version.py at the
    # moment of assignment, where the baseline is CURRENT main. Failing on a
    # gap here would re-create exactly the always-red bug this gate had.
    gap = cur_t != _next_canonical(prev_t)
    return Report(True, current, previous, True, equality_checked, equality_ok,
                  f"OK: {previous} -> {current} (strict bump"
                  + (", non-adjacent — one-step rule is enforced at assignment"
                     if gap else "")
                  + (", marketplace in sync" if equality_checked else "")
                  + ")", change), 0


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Assert the version bump is strictly monotonic vs the "
                    "previous commit (chip-AGNOSTIC).")
    p.add_argument("--plugin-json", type=Path, default=None,
                   help="Path to working-tree plugin.json.")
    p.add_argument("--marketplace-json", type=Path, default=None,
                   help="Path to marketplace.json (optional; re-asserts equality).")
    p.add_argument("--base", default="HEAD",
                   help="Git ref to compare against (default: HEAD = previous commit).")
    p.add_argument("--current", default=None,
                   help="Explicit current version (skips git / plugin.json read).")
    p.add_argument("--previous", default=None,
                   help="Explicit previous version (skips git read).")
    p.add_argument("--json", default=None, help="Write JSON report to this path.")
    p.add_argument("--version-by-gatekeeper", action="store_true",
                   help="VERSION-LESS AUTHORING PR context: 'no version change' "
                        "is the documented normal path and PASSES (the "
                        "gatekeeper assigns the monotonic version at merge). A "
                        "BACKWARDS version still FAILS. Same semantics as the "
                        "flag of the same name on gatekeeper_review.py.")
    args = p.parse_args(argv)

    current: Optional[str] = None
    previous: Optional[str] = None
    market: Optional[str] = None
    equality_checked = False
    version_file_touched: Optional[bool] = None

    if args.current is not None and args.previous is not None:
        current = args.current
        previous = args.previous
    else:
        if args.plugin_json is None:
            print("ERROR: provide --plugin-json (and optionally --base) "
                  "or both --current and --previous.", file=sys.stderr)
            return 2
        pj = args.plugin_json
        if not pj.is_file():
            print(f"ERROR: plugin.json not found: {pj}", file=sys.stderr)
            return 2
        current = _read_json_version(pj)
        if current is None:
            print(f"ERROR: cannot read 'version' from {pj}", file=sys.stderr)
            return 2
        # Resolve repo dir + path relative to repo root for `git show`.
        repo_dir = pj.resolve().parent
        try:
            top = subprocess.run(
                ["git", "-C", str(repo_dir), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=False)
            if top.returncode != 0:
                print(f"ERROR: not a git repo: {repo_dir}", file=sys.stderr)
                return 2
            repo_root = Path(top.stdout.strip())
            rel = pj.resolve().relative_to(repo_root).as_posix()
        except (OSError, ValueError) as e:
            print(f"ERROR: cannot resolve git path for {pj}: {e}", file=sys.stderr)
            return 2
        version_file_touched = _git_path_changed(repo_root, args.base, rel)
        previous = _git_show_version(repo_root, args.base, rel)
        if previous is None:
            print(f"ERROR: cannot read plugin.json version at {args.base} "
                  f"({rel}). If this is the first commit, supply --previous.",
                  file=sys.stderr)
            return 2

    if args.marketplace_json is not None:
        mj = args.marketplace_json
        if not mj.is_file():
            print(f"ERROR: marketplace.json not found: {mj}", file=sys.stderr)
            return 2
        market = _read_marketplace_version(mj)
        equality_checked = True

    report, rc = evaluate(current, previous, market, equality_checked,
                          args.version_by_gatekeeper, version_file_touched)
    report_json = json.dumps(asdict(report), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json + "\n", encoding="utf-8")

    tag = {0: "PASS", 1: "FAIL", 2: "ERROR"}[rc]
    print(f"[{tag}] version_bump_monotonic_check: {report.reason}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
