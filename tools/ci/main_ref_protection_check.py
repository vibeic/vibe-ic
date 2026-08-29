#!/usr/bin/env python3
"""Assert that `main` carries the server-side rule that makes the lane MANDATORY.

WHY A CHECKER AND NOT JUST A RULESET
====================================
A ruleset is repository CONFIGURATION.  It lives outside the tree, nothing in
the tree references it, and deleting it is one API call that leaves no commit,
no diff and no reviewer.  The failure this repo just paid for is precisely that
shape: an enforcement surface everyone believed in, that measurement showed was
not there.

    MEASURED 2026-08-29, `vibeic/vibe-ic`:
      GET branches/main/protection -> 404 Branch not protected
      GET rulesets                 -> []
      GET actions/permissions      -> {"enabled": false}
    and 49 version-stamped landings between 40d0e14c0 and 6ae22986d5 went in
    over a hygiene gate that had been red on main for two days.

So the rule needs a reader.  This is it.

BLOCKING, and it says which question it answered
================================================
    exit 0  `main` is covered by an ACTIVE rule that requires the lane's status
            context, forbids non-fast-forward, and grants NO bypass actor.
    exit 1  a FINDING: `main` is reachable without the lane.  Names what is
            missing.
    exit 2  COULD NOT CHECK — no snapshot and no network, or a malformed
            document.  Never reported as covered.  `rc 2` is not `rc 0` here
            and must not be folded into one.

OFFLINE BY DEFAULT, ON PURPOSE
==============================
The repo-hygiene sweep runs on hosts with no credentials, and a gate that needs
the network is a gate that will be given a tolerance the first time it is
inconvenient.  So this reads a SNAPSHOT (`gh api repos/<slug>/rulesets` piped to
a file) and only reaches the network when `--live` is passed.  A missing
snapshot is rc 2 and says so; it is never rc 0.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

#: One spelling of the context, shared with `landing_status_publish.py`.  If
#: these two ever disagree the rule requires a status nobody publishes and every
#: landing is refused — loud, and the safe direction.
CONTEXT = "vibe-ic/landing-lane"

#: Ref patterns that a reader would accept as "this covers main".
MAIN_PATTERNS = frozenset({
    "refs/heads/main", "~DEFAULT_BRANCH", "~ALL", "refs/heads/**",
    "refs/heads/*",
})

REQUIRED_RULE_TYPES = ("required_status_checks", "non_fast_forward")


class CouldNotCheck(RuntimeError):
    """Nothing was concluded about the ref."""


def _fetch_live(slug: str) -> list[dict[str, Any]]:
    out = []
    for path in (f"repos/{slug}/rulesets", ):
        proc = subprocess.run(["gh", "api", path], capture_output=True,
                              text=True)
        if proc.returncode != 0:
            raise CouldNotCheck(
                f"`gh api {path}` exited {proc.returncode}: "
                f"{proc.stderr.strip()[:200]}")
        try:
            listing = json.loads(proc.stdout)
        except ValueError as exc:
            raise CouldNotCheck(f"unreadable listing from {path}: {exc}") from None
        if not isinstance(listing, list):
            raise CouldNotCheck(f"{path} did not return a list")
        for row in listing:
            rid = row.get("id")
            if rid is None:
                continue
            # The listing carries no `rules`; the per-ruleset document does.
            det = subprocess.run(["gh", "api", f"repos/{slug}/rulesets/{rid}"],
                                 capture_output=True, text=True)
            if det.returncode != 0:
                raise CouldNotCheck(
                    f"could not read ruleset {rid}: {det.stderr.strip()[:160]}")
            try:
                out.append(json.loads(det.stdout))
            except ValueError as exc:
                raise CouldNotCheck(f"ruleset {rid} unreadable: {exc}") from None
    return out


def load(snapshot: Path | None, slug: str, live: bool) -> list[dict[str, Any]]:
    if live:
        return _fetch_live(slug)
    if snapshot is None:
        raise CouldNotCheck(
            "no --snapshot and --live was not passed, so the rule state of "
            "`main` was NOT read. This is not a pass. Produce one with: "
            f"gh api repos/{slug}/rulesets --paginate > <file>  (and the "
            "per-ruleset documents), or pass --live.")
    if not snapshot.is_file():
        raise CouldNotCheck(f"snapshot not found: {snapshot}")
    try:
        doc = json.loads(snapshot.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CouldNotCheck(f"unreadable snapshot: {exc}") from None
    if isinstance(doc, dict):
        doc = [doc]
    if not isinstance(doc, list):
        raise CouldNotCheck("snapshot is neither a ruleset nor a list of them")
    return doc


def covers_main(ruleset: dict[str, Any]) -> bool:
    cond = (ruleset.get("conditions") or {}).get("ref_name") or {}
    include = [str(p) for p in (cond.get("include") or [])]
    exclude = [str(p) for p in (cond.get("exclude") or [])]
    if any(p in ("refs/heads/main", "~DEFAULT_BRANCH") for p in exclude):
        return False
    return any(p in MAIN_PATTERNS for p in include)


def findings(rulesets: list[dict[str, Any]]) -> list[str]:
    """Every reason `main` is still reachable without the lane. Empty == covered."""
    candidates = [r for r in rulesets
                  if str(r.get("target") or "branch") == "branch"
                  and covers_main(r)]
    if not candidates:
        return ["NO RULESET TARGETS `main` — a direct `git push --no-verify "
                "origin HEAD:refs/heads/main` is refused by nothing on the "
                "server, and the landing lane is therefore advisory."]
    out: list[str] = []
    satisfied = False
    for rs in candidates:
        name = str(rs.get("name") or rs.get("id"))
        local: list[str] = []
        if str(rs.get("enforcement")) != "active":
            local.append(f"ruleset {name!r} is enforcement="
                         f"{rs.get('enforcement')!r}, not 'active'")
        bypass = rs.get("bypass_actors") or []
        if bypass:
            local.append(
                f"ruleset {name!r} grants {len(bypass)} bypass actor(s), so the "
                f"people most able to skip the lane are exactly the ones "
                f"exempted from it")
        rules = {str(r.get("type")): r for r in (rs.get("rules") or [])}
        for want in REQUIRED_RULE_TYPES:
            if want not in rules:
                local.append(f"ruleset {name!r} carries no `{want}` rule")
        rsc = rules.get("required_status_checks")
        if rsc is not None:
            contexts = [str(c.get("context"))
                        for c in ((rsc.get("parameters") or {})
                                  .get("required_status_checks") or [])]
            if CONTEXT not in contexts:
                local.append(
                    f"ruleset {name!r} requires {contexts or 'no context'} and "
                    f"not {CONTEXT!r} — the lane's own verdict is not what "
                    f"gates the push")
        if not local:
            satisfied = True
        out.extend(local)
    return [] if satisfied else out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", default="",
                    help="a file holding the ruleset document(s) to judge")
    ap.add_argument("--repo-slug", default="vibeic/vibe-ic")
    ap.add_argument("--live", action="store_true",
                    help="read the rules from GitHub instead of a snapshot")
    a = ap.parse_args(argv)
    try:
        rulesets = load(Path(a.snapshot) if a.snapshot else None,
                        a.repo_slug, a.live)
    except CouldNotCheck as exc:
        print(f"[UNDETERMINED] main_ref_protection: {exc}", file=sys.stderr)
        return 2
    found = findings(rulesets)
    if found:
        print(f"[FAIL] main_ref_protection: {len(found)} finding(s) — `main` "
              f"is reachable without the landing lane")
        for f in found:
            print(f"    - {f}")
        return 1
    print("[PASS] main_ref_protection: `main` is covered by an active rule "
          f"requiring {CONTEXT}, forbidding non-fast-forward, with no bypass "
          "actor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
