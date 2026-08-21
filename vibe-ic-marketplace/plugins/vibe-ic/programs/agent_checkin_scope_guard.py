#!/usr/bin/env python3
"""agent_checkin_scope_guard.py — role-based check-in (commit) path-scope gate.

Vibe-IC has FIVE agent roles with DIFFERENT check-in authority over the repo.
This program turns that authority into a DETERMINISTIC, executable boundary
(program-first, not prose-in-a-prompt): given a role and the set of paths a
commit would touch, it PASSes iff every path is inside that role's allow-list,
and FAILs (listing each offending path + the protected zone it lands in)
otherwise.

Roles + check-in authority (the governance matrix):

  | role             | may check in to                              |
  |------------------|----------------------------------------------|
  | repo-gatekeeper  | EVERYTHING — the SINGLE maintainer role that |
  |                  | authors fixes into plugin + MCP AND gates /  |
  |                  | assigns versions / lands them on main        |
  | core-agent       | alias of repo-gatekeeper (author half)       |
  | gatekeeper       | alias of repo-gatekeeper (land half)         |
  | benchmark-agent  | benchmark-data/ (results) + plugin/MCP (fixes |
  |                  | via version-less PR) — NO-MIX in one commit  |
  | field-agent      | community/backlogs/  (files backlog only)    |
  | ic-expert-agent  | NOTHING (Phase-1 design-time; no repo commit) |

Doctrine: the plugin and the MCP server are LANDED on main only by the single
REPO-GATEKEEPER role (2026-06-18 — author + gate + version + land unified;
`core-agent`/`gatekeeper` are aliases). The BENCHMARK agent (2026-06-21 owner
directive "USE PR to issue bugs") may AUTHOR chip-AGNOSTIC plugin/MCP fixes as a
VERSION-LESS PR (the repo-gatekeeper reviews + assigns the version + lands it) —
it NO LONGER files a backlog. Its measure-only HONESTY is preserved not by a
plugin ban but by the NO-MIX invariant: a single commit may carry benchmark
RESULTS (benchmark-data/) OR plugin/MCP EDITS, never BOTH, so a hand-patch can
never ride along in the run whose published number it changes. The Field agent
still files the backlog mirror only; ic-expert is design-time (no check-in).

This is an ALLOW-LIST model (default-deny for every restricted role) — a path
that matches no allowed prefix is a violation. `repo-gatekeeper` (and its
`core-agent`/`gatekeeper` aliases) has an open allow-list (None) and may touch
anything.

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
from _atomic_artefact import writing as atomic_writing  # vibe-ic#1082 (helper from PR #1094)

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
    # repo-gatekeeper (2026-06-18, owner directive): the SINGLE role that both
    # AUTHORS fixes into the plugin/MCP and GATES + assigns versions + LANDS them
    # on main — the unification of the former `core-agent` (author) and
    # `gatekeeper` (land). Unrestricted check-in scope.
    "repo-gatekeeper": None,
    # `core-agent` and `gatekeeper` are retained as ALIASES of repo-gatekeeper
    # (same unrestricted scope) so existing `--role core-agent` invocations and
    # the gatekeeper flow keep working — they denote the SAME single role.
    "core-agent": None,        # alias of repo-gatekeeper (author half)
    "gatekeeper": None,        # alias of repo-gatekeeper (land half)
    # benchmark-agent (2026-06-21, owner directive "USE PR to issue bugs"): MEASURES
    # the plugin AND may AUTHOR chip-AGNOSTIC plugin/MCP fixes via a VERSION-LESS PR
    # (no longer files backlog). The measure-only honesty is preserved NOT by a
    # plugin ban but by the NO-MIX invariant below: results and plugin edits must
    # land in SEPARATE commits, so a hand-patch can never be bundled into the run
    # whose number it inflates.
    "benchmark-agent": [ZONE_BENCHMARK_DATA, ZONE_PLUGIN, ZONE_MCP],
    "field-agent": [ZONE_BACKLOG],
    "ic-expert-agent": [],
}

# NO-MIX anti-gaming invariant — roles that MEASURE the plugin AND may author
# plugin/MCP fixes via PR may NOT carry BOTH benchmark RESULTS (benchmark-data/)
# AND plugin/MCP EDITS in a SINGLE commit. Bundling a plugin patch with the run
# that "passed because of it" is the benchmark-gaming vector; the published number
# must reflect the runner, never a hand-patch committed alongside it. So a result
# commit is pure benchmark-data, and a fix commit is pure plugin/MCP (a version-less
# PR branch). repo-gatekeeper (the lander) is exempt.
NO_MIX_ROLES = ("benchmark-agent",)

# One-line description per role (for --list-roles + error context).
ROLE_DESC: Dict[str, str] = {
    "repo-gatekeeper": "the SINGLE maintainer role — authors fixes into plugin + MCP AND gates/assigns-version/lands on main (former core-agent + gatekeeper unified); may check in anywhere",
    "core-agent": "alias of repo-gatekeeper (author half) — may check in anywhere",
    "gatekeeper": "alias of repo-gatekeeper (land half) — may check in anywhere",
    "benchmark-agent": "runs Benchmark Evaluation / Benchmark IC — checks in benchmark-data/ (results) and may author plugin/MCP fixes via a version-less PR; NO-MIX: never both in one commit",
    "field-agent": "general field usage — files backlog only; NO benchmark-data / plugin / MCP",
    "ic-expert-agent": "Phase-1 NL dialogue (plain-language register) + technical review — design-time, no repo check-in",
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
    # Canonicalize redundant separators a manually-supplied --paths/--paths-file
    # might carry (Step-2.7 defense-in-depth: git --name-only is already clean, so
    # these only enter via the operator route, but a `//` or mid-path `/./` would
    # otherwise defeat the startswith-zone check below and weaken NO-MIX).
    while "//" in p:
        p = p.replace("//", "/")
    while "/./" in p:
        p = p.replace("/./", "/")
    # Already repo-root-relative (the path STARTS at a known zone marker) → do
    # NOT re-truncate, even when a LATER marker nests inside it. Step-2.7
    # anti-gaming: the old "first marker in list order with idx>0" cut discarded
    # the LEADING zone of a result path like
    # `benchmark-data/run/work/vibe-ic-marketplace/.../SCORE.md` (it became
    # `vibe-ic-marketplace/...`), so `has_result` went False and the NO-MIX gate
    # silently failed to fire on a genuinely mixed result+plugin PR. It also
    # mis-rooted a legit `benchmark-data/.../IP/...` result and a plugin
    # `vibe-ic-marketplace/plugins/vibe-ic/tools/...` file.
    if any(p.startswith(m) for m in _REPO_MARKERS):
        return p.lstrip("/")
    # Absolute / nested-checkout path → cut at the LEFTMOST known repo marker
    # (smallest index), so a nested later marker cannot strip a leading zone.
    cut = min((i for i in (p.find(m) for m in _REPO_MARKERS) if i > 0),
              default=-1)
    if cut > 0:
        p = p[cut:]
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
    norms: List[str] = []
    for raw in paths:
        norm = normalize_path(raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        norms.append(norm)
        if not path_allowed(role, norm):
            violations.append({"path": norm, "zone": classify_zone(norm)})
    # NO-MIX anti-gaming invariant: a single commit may carry benchmark RESULTS
    # OR plugin/MCP EDITS, never BOTH (ZONE_PLUGIN already covers ZONE_MCP since
    # the MCP tree lives under the plugin tree).
    if role in NO_MIX_ROLES:
        has_result = any(n.startswith(ZONE_BENCHMARK_DATA) for n in norms)
        has_plugin = any(n.startswith(ZONE_PLUGIN) for n in norms)
        if has_result and has_plugin:
            violations.append({
                "path": "<this commit MIXES benchmark-data/ results with plugin/MCP edits>",
                "zone": "NO-MIX (anti-gaming: split into a pure result commit + a pure plugin-fix PR)",
            })
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
                     "ic-expert-agent"):
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
            with atomic_writing(args.json, encoding="utf-8") as fh:
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
        if any(v["zone"].startswith("NO-MIX") for v in violations):
            print("  → SPLIT this commit: land the benchmark RESULTS as a pure "
                  "benchmark-data/ commit, and the plugin/MCP fix as a SEPARATE "
                  "version-less PR commit (no benchmark-data/ paths). Never bundle "
                  "a plugin patch with the run whose number it changes.")
        else:
            print("  → open a VERSION-LESS PR for a plugin/MCP fix (the repo-gatekeeper "
                  "lands it); do NOT file a backlog and do NOT bundle it with results.")
        return 1

    print(f"PASS: role '{args.role}' — all {result['checked']} path(s) within "
          f"check-in scope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
