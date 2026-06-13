#!/usr/bin/env python3
"""agent_checkin_scope_guard.py — role-based check-in (commit) path-scope gate.

Vibe-IC has FIVE agent roles with DIFFERENT check-in authority over the repo.
This program turns that authority into a DETERMINISTIC, executable boundary
(program-first, not prose-in-a-prompt): given a role and the set of paths a
commit would touch, it PASSes iff every path is inside that role's allow-list,
and FAILs (listing each offending path + the protected zone it lands in)
otherwise.

Roles + check-in authority (the canonical 5-agent governance matrix):

  | role             | may check in to                              |
  |------------------|----------------------------------------------|
  | core-agent       | EVERYTHING (the only role that edits the     |
  |                  | plugin + MCP; consumes backlog, fixes, pushes)|
  | benchmark-agent  | benchmark-data/  +  community/backlogs/      |
  | field-agent      | community/backlogs/  (files backlog only)    |
  | pm-agent         | NOTHING (Phase-1 design-time; no repo commit) |
  | ic-expert-agent  | NOTHING (Phase-1 design-time; no repo commit) |

Doctrine: the plugin and the MCP server are owned by the CORE agent alone.
Field and Benchmark agents that discover a problem do NOT fix the plugin/MCP
themselves — they file an ORGANIC backlog item (community/backlogs/ + a GitHub
issue) and the Core agent resolves it into the plugin/MCP. The Benchmark agent
additionally owns benchmark-data/ (it checks in run results / samples / reports);
the Field agent owns nothing but the backlog mirror.

This is an ALLOW-LIST model (default-deny for every restricted role) — a path
that matches no allowed prefix is a violation. `core-agent` has an open
allow-list (None) and may touch anything.

Usage:
    # explicit path list
    agent_checkin_scope_guard.py --role benchmark-agent --paths a/b.py c/d.md
    # the staged diff (what `git commit` would record)
    agent_checkin_scope_guard.py --role benchmark-agent --staged
    # a diff range
    agent_checkin_scope_guard.py --role field-agent --base HEAD
    # paths from a file (one per line; e.g. `git diff --cached --name-only > f`)
    agent_checkin_scope_guard.py --role core-agent --paths-file changed.txt
    # introspection
    agent_checkin_scope_guard.py --list-roles

Exit codes:
    0  PASS — every path is within the role's check-in scope (or role=core-agent)
    1  FAIL — one or more paths are outside the role's scope (each listed)
    2  argument / I/O error (unknown role, bad git invocation, etc.)

chip-AGNOSTIC: contains no chip / vendor / SKU literals; it reasons over repo
paths + role names only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Protected zones (repo-root-relative path prefixes). Order matters for
# message classification: the MCP server lives UNDER the plugin tree, so the
# more-specific mcp-eda prefix is checked before the generic plugin prefix.
# --------------------------------------------------------------------------
ZONE_MCP = "vibe-ic-marketplace/plugins/vibe-ic/mcp-eda/"
ZONE_PLUGIN = "vibe-ic-marketplace/plugins/vibe-ic/"
ZONE_BENCHMARK_DATA = "benchmark-data/"
ZONE_BACKLOG = "vibe-ic-marketplace/community/backlogs/"

# Ordered (most-specific-first) so classify() reports the tightest zone.
_ZONE_ORDER: Tuple[Tuple[str, str], ...] = (
    ("MCP (mcp-eda)", ZONE_MCP),
    ("plugin", ZONE_PLUGIN),
    ("backlog", ZONE_BACKLOG),
    ("benchmark-data", ZONE_BENCHMARK_DATA),
)

# --------------------------------------------------------------------------
# The canonical allow-lists. `None` = unrestricted (allow ALL paths).
# `[]` = allow NOTHING (default-deny for every path). Otherwise a path is
# allowed iff it starts with one of the listed prefixes.
# --------------------------------------------------------------------------
ROLE_ALLOW: Dict[str, Optional[List[str]]] = {
    "core-agent": None,  # owner of plugin + MCP + everything else
    "benchmark-agent": [ZONE_BENCHMARK_DATA, ZONE_BACKLOG],
    "field-agent": [ZONE_BACKLOG],
    "pm-agent": [],
    "ic-expert-agent": [],
}

# One-line description per role (for --list-roles + error context).
ROLE_DESC: Dict[str, str] = {
    "core-agent": "owns plugin + MCP; consumes backlog, fixes, pushes — may check in anywhere",
    "benchmark-agent": "runs Benchmark Evaluation / Benchmark IC — checks in benchmark-data/ + backlog only",
    "field-agent": "general field usage — files backlog only; NO benchmark-data / plugin / MCP",
    "pm-agent": "Phase-1 NL dialogue — design-time, no repo check-in",
    "ic-expert-agent": "Phase-1 technical review — design-time, no repo check-in",
}

# Repo-root markers used to strip an absolute path down to repo-relative.
_REPO_MARKERS = ("vibe-ic-marketplace/", "benchmark-data/", "IP/", "tools/")


def normalize_path(raw: str) -> str:
    """Normalize a path to repo-root-relative, forward-slash form.

    Handles: absolute paths (strip everything up to a known repo marker),
    a leading ``./``, and back-slashes. Returns the path unchanged when no
    repo marker is found (already relative, or a root-level file).
    """
    p = (raw or "").strip().replace("\\", "/")
    if not p:
        return ""
    while p.startswith("./"):
        p = p[2:]
    # Absolute or nested checkout path → cut at the first known repo marker.
    for marker in _REPO_MARKERS:
        idx = p.find(marker)
        if idx > 0:  # marker present but not already at position 0
            p = p[idx:]
            break
    return p.lstrip("/")


def classify_zone(path: str) -> str:
    """Return the protected-zone label a path lands in (most specific first)."""
    for label, prefix in _ZONE_ORDER:
        if path.startswith(prefix):
            return label
    return "repo (other)"


def path_allowed(role: str, path: str) -> bool:
    """True iff ``role`` may check in ``path`` (repo-relative, normalized)."""
    allow = ROLE_ALLOW[role]
    if allow is None:  # core-agent: unrestricted
        return True
    return any(path.startswith(prefix) for prefix in allow)


def evaluate(role: str, paths: List[str]) -> List[Dict[str, str]]:
    """Return the list of violations (empty == PASS).

    Each violation: {"path": <repo-relative>, "zone": <label>}.
    """
    violations: List[Dict[str, str]] = []
    seen = set()
    for raw in paths:
        norm = normalize_path(raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        if not path_allowed(role, norm):
            violations.append({"path": norm, "zone": classify_zone(norm)})
    return violations


def _git_paths(args: argparse.Namespace) -> List[str]:
    """Resolve the changed-path list from --staged / --base / --paths(-file)."""
    if args.paths:
        return list(args.paths)
    if args.paths_file:
        with open(args.paths_file, encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip()]
    cmd: List[str]
    if args.staged:
        cmd = ["git", "diff", "--cached", "--name-only"]
    else:  # --base
        cmd = ["git", "diff", "--name-only", args.base]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git invocation failed ({' '.join(cmd)}): "
            f"{proc.stderr.strip() or 'non-zero exit'}")
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Role-based check-in path-scope gate (the 5-agent governance matrix).")
    ap.add_argument("--role", help="agent role: " + " / ".join(sorted(ROLE_ALLOW)))
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--paths", nargs="+", help="explicit path list to check")
    src.add_argument("--paths-file", help="file with one path per line")
    src.add_argument("--staged", action="store_true",
                     help="check `git diff --cached --name-only`")
    src.add_argument("--base", help="check `git diff --name-only <base>` (e.g. HEAD)")
    ap.add_argument("--json", help="write JSON verdict to this path")
    ap.add_argument("--list-roles", action="store_true",
                    help="print the role/allow-list matrix and exit 0")
    args = ap.parse_args(argv)

    if args.list_roles:
        print("Agent check-in scope matrix:")
        for role in ("core-agent", "benchmark-agent", "field-agent",
                     "pm-agent", "ic-expert-agent"):
            allow = ROLE_ALLOW[role]
            scope = "EVERYTHING" if allow is None else (
                ", ".join(allow) if allow else "NOTHING")
            print(f"  {role:<16} → {scope}")
            print(f"  {'':<16}   {ROLE_DESC[role]}")
        return 0

    if not args.role:
        print("ERROR: --role is required (or use --list-roles).", file=sys.stderr)
        return 2
    if args.role not in ROLE_ALLOW:
        print(f"ERROR: unknown role {args.role!r}. Known roles: "
              f"{', '.join(sorted(ROLE_ALLOW))}.", file=sys.stderr)
        return 2
    if not (args.paths or args.paths_file or args.staged or args.base):
        print("ERROR: provide one of --paths / --paths-file / --staged / --base.",
              file=sys.stderr)
        return 2

    try:
        paths = _git_paths(args)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    violations = evaluate(args.role, paths)
    verdict = "PASS" if not violations else "FAIL"
    result = {
        "role": args.role,
        "verdict": verdict,
        "checked": len([normalize_path(p) for p in paths if normalize_path(p)]),
        "violations": violations,
    }
    if args.json:
        try:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2)
        except OSError as exc:
            print(f"ERROR: cannot write --json {args.json}: {exc}", file=sys.stderr)
            return 2

    if violations:
        print(f"FAIL: role '{args.role}' ({ROLE_DESC[args.role]}) may NOT check in "
              f"{len(violations)} path(s) outside its scope:")
        for v in violations:
            print(f"  - {v['path']}   [{v['zone']}]")
        allow = ROLE_ALLOW[args.role]
        scope = "EVERYTHING" if allow is None else (
            ", ".join(allow) if allow else "NOTHING (design-time role)")
        print(f"  allowed scope for '{args.role}': {scope}")
        print("  → file the change via an ORGANIC backlog item so the core-agent "
              "lands it (see skill community-backlog-submit); do NOT commit it here.")
        return 1

    print(f"PASS: role '{args.role}' — all {result['checked']} path(s) within "
          f"check-in scope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
