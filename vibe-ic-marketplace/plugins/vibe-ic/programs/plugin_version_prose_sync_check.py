#!/usr/bin/env python3
"""plugin_version_prose_sync_check — a version STATED IN PROSE must be the shipped one.

WHY (vibe-ic#621)
=================
`marketplace_version_sync_check` guards every place the version is stated in
JSON — and it was written because an OUTER manifest "sat at 1.3.42 for six
releases while the maintained manifest advanced to 1.3.48". The same drift then
happened one file type over, unguarded and much further:

    README.md                          badge  plugin-v1.5.12   |  Status: v1.4
    vibe-ic-marketplace/README.md      | Plugin version | 1.4.72 |
                                       ← the single plugin (v1.4.61)
    plugins/vibe-ic/README.md          plugin (**v1.4.61**)

against a shipped `plugin.json` of **1.9.36** — five minor versions, four
different stale numbers, in the three documents a reader meets first.

Correcting the numbers alone resets the counter and changes nothing: they drifted
because nothing compared them. This is the comparison.

WHAT IS AND IS NOT A CLAIM ABOUT THE PLUGIN VERSION
===================================================
NARROW BY CONSTRUCTION. These documents legitimately name other versions — the
MCP-EDA badge is `v1.0.0`, the EDA image is `0.2.x`, and prose cites historical
releases on purpose. So this does not scan for "a version-shaped string"; it
matches only the FORMS that assert THIS plugin's current version, each one taken
from a real drift above, and ignores everything else in the file.

A site that states no such claim is not a finding — the claims are optional. A
document that states one and gets it wrong is.

Exit: 0 every prose claim equals plugin.json / 1 at least one disagrees /
      2 could not establish the shipped version (no plugin.json, or several
      disagreeing) — never a pass over an unknown truth.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TOOL = "plugin_version_prose_sync_check"
RC_OK, RC_FINDINGS, RC_CANNOT_CHECK = 0, 1, 2

#: The shipped documents a reader meets first. Only files that EXIST are read;
#: the list is the scope, and it is published in the output so a PASS says how
#: much it looked at.
_PROSE_SITES = (
    "README.md",
    "vibe-ic-marketplace/README.md",
    "vibe-ic-marketplace/plugins/vibe-ic/README.md",
)

#: (name, pattern, compare) — `compare` is how much of the version the claim
#: asserts, so `Status: v1.9` is checked on major.minor and not failed for
#: omitting a patch it never claimed.
_CLAIMS: Tuple[Tuple[str, "re.Pattern", str], ...] = (
    ("shields badge", re.compile(r"badge/plugin-v(\d+\.\d+\.\d+)-"), "full"),
    ("badge link text", re.compile(r"\[!\[Plugin v(\d+\.\d+\.\d+)\]"), "full"),
    ("version table row",
     re.compile(r"\|\s*Plugin version\s*\|\s*\*\*(\d+\.\d+\.\d+)\*\*"), "full"),
    ("title", re.compile(r"plugin\s*\(\*\*v(\d+\.\d+\.\d+)\*\*\)"), "full"),
    ("tree diagram",
     re.compile(r"the single plugin\s*\(v(\d+\.\d+\.\d+)\)"), "full"),
    ("status line", re.compile(r"\*\*Status:\s*v(\d+\.\d+)\b"), "minor"),
)


def shipped_version(repo_root: Path) -> Tuple[Optional[str], str]:
    """(version, note) — the version of the plugin THIS REPO DECLARES IT SHIPS.

    Resolved through the repo-root `marketplace.json`'s own `plugins[].source`,
    which is the repo's statement of which plugin it ships. NOT by globbing
    `**/.claude-plugin/plugin.json`: measured on this tree, that finds 79 of
    them — the partner-plugin skeleton (a legitimately different plugin at
    0.1.0) and 39 stale agent worktrees under `.claude/worktrees` carrying
    versions from 1.6.84 to 1.7.99 — so the question "which is the shipped
    one?" cannot be answered by counting, and a majority vote among stale
    checkouts is not an authority.

    Two entries that DISAGREE is still not a version; it is a question, and
    `marketplace_version_sync_check` is the gate that answers it.
    """
    mkt = repo_root / ".claude-plugin" / "marketplace.json"
    if not mkt.is_file():
        return None, f"no {mkt.relative_to(repo_root)} — the repo declares no plugin"
    try:
        entries = json.loads(mkt.read_text(errors="replace")).get("plugins")
    except (OSError, ValueError) as exc:
        return None, f"cannot read {mkt.relative_to(repo_root)}: {exc}"
    if not isinstance(entries, list) or not entries:
        return None, f"{mkt.relative_to(repo_root)} declares no plugins[]"

    found: Dict[str, List[str]] = {}
    for e in entries:
        src = (e or {}).get("source") if isinstance(e, dict) else None
        if not isinstance(src, str):
            continue
        pj = (repo_root / src / ".claude-plugin" / "plugin.json").resolve()
        try:
            v = json.loads(pj.read_text(errors="replace")).get("version")
        except (OSError, ValueError):
            continue
        if isinstance(v, str) and v:
            try:
                rel = str(pj.relative_to(repo_root))
            except ValueError:
                rel = str(pj)
            found.setdefault(v, []).append(rel)
    if not found:
        return None, ("no plugin.json reachable from the repo-root manifest "
                      "carries a version")
    if len(found) > 1:
        return None, ("the manifest's plugins disagree about the version: "
                      + "; ".join(f"{v} ({', '.join(p)})"
                                  for v, p in sorted(found.items())))
    v = next(iter(found))
    return v, f"{v} (from {', '.join(sorted(found[v]))})"


def _wanted(version: str, compare: str) -> str:
    return ".".join(version.split(".")[:2]) if compare == "minor" else version


def audit(repo_root: Path,
          sites=_PROSE_SITES) -> Tuple[str, List[Dict], Dict]:
    version, note = shipped_version(repo_root)
    stats = {"shipped_version": version, "version_source": note,
             "sites_scanned": 0, "claims_compared": 0, "sites": list(sites)}
    if version is None:
        return "CANNOT_CHECK", [{"detail": note}], stats

    findings: List[Dict] = []
    for rel in sites:
        p = repo_root / rel
        if not p.is_file():
            continue
        stats["sites_scanned"] += 1
        text = p.read_text(errors="replace")
        for name, rx, compare in _CLAIMS:
            for m in rx.finditer(text):
                stats["claims_compared"] += 1
                want = _wanted(version, compare)
                if m.group(1) != want:
                    line = text[:m.start()].count("\n") + 1
                    findings.append({
                        "file": rel, "line": line, "claim": name,
                        "states": m.group(1), "shipped": want,
                        "detail": (f"{rel}:{line} states the plugin version as "
                                   f"{m.group(1)} in the {name}; the shipped "
                                   f"version is {want}"),
                    })
    return ("FINDINGS" if findings else "PASS"), findings, stats


def fix(repo_root: Path, version: str, sites=_PROSE_SITES) -> Dict[str, int]:
    """Rewrite every disagreeing claim to `version`. -> {site: n_rewritten}.

    Rewrites the CAPTURED GROUP only, so the surrounding text — a badge URL, a
    table cell, a tree-diagram line — is untouched and a claim this does not
    recognise is left exactly as it is rather than guessed at.
    """
    touched: Dict[str, int] = {}
    for rel in sites:
        p = repo_root / rel
        if not p.is_file():
            continue
        text = orig = p.read_text(errors="replace")
        n = 0
        for _name, rx, compare in _CLAIMS:
            want = _wanted(version, compare)

            def _sub(m, want=want):
                nonlocal n
                if m.group(1) == want:
                    return m.group(0)
                n += 1
                return m.group(0)[:m.start(1) - m.start()] + want + \
                    m.group(0)[m.end(1) - m.start():]

            text = rx.sub(_sub, text)
        if text != orig:
            p.write_text(text)
            touched[rel] = n
    return touched


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("repo_root", nargs="?", default=".")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--fix", action="store_true",
                    help="rewrite each disagreeing claim to the shipped "
                         "version. The version bump is the one writer; this "
                         "makes the prose follow it instead of being corrected "
                         "by hand every few releases, which is how it drifted "
                         "five minor versions.")
    a = ap.parse_args(argv)

    root = Path(a.repo_root).resolve()
    if not root.is_dir():
        print(f"[SKIP] {TOOL}: {a.repo_root!r} is not a directory — nothing "
              f"was compared, which is not a clean result", file=sys.stderr)
        return RC_CANNOT_CHECK

    if a.fix:
        version, note = shipped_version(root)
        if version is None:
            print(f"[SKIP] {TOOL}: {note} — refusing to rewrite prose against "
                  f"a version that could not be established", file=sys.stderr)
            return RC_CANNOT_CHECK
        touched = fix(root, version)
        for rel, n in sorted(touched.items()):
            print(f"  wrote: {rel} ({n} claim(s) -> {version})")
        if not touched:
            print(f"{TOOL}: nothing to rewrite — every claim already states "
                  f"{version}")

    verdict, findings, stats = audit(root)
    if a.json_out:
        out = Path(a.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {"tool": TOOL, "verdict": verdict, "findings": findings, **stats},
            indent=2) + "\n")

    if verdict == "CANNOT_CHECK":
        print(f"[SKIP] {TOOL}: {stats['version_source']} — the shipped version "
              f"is unknown, so no prose claim could be checked against it",
              file=sys.stderr)
        return RC_CANNOT_CHECK
    if verdict == "FINDINGS":
        for f in findings:
            print(f"[FAIL] {f['detail']}", file=sys.stderr)
        print(f"{TOOL}: FINDINGS — {len(findings)} of "
              f"{stats['claims_compared']} prose version claim(s) across "
              f"{stats['sites_scanned']} document(s) disagree with the shipped "
              f"{stats['shipped_version']}", file=sys.stderr)
        return RC_FINDINGS
    if stats["claims_compared"] == 0:
        # Every site read and not one stated a version. That is a real result
        # about documents that make no claim — but a PASS over zero comparisons
        # must say so rather than read as agreement.
        print(f"VACUOUS_PASS: {TOOL}: {stats['sites_scanned']} document(s) read "
              f"and none states a plugin version, so nothing was compared "
              f"against the shipped {stats['shipped_version']}")
        return RC_OK
    print(f"{TOOL}: PASS — {stats['claims_compared']} prose version claim(s) "
          f"across {stats['sites_scanned']} document(s) all state the shipped "
          f"{stats['shipped_version']}")
    return RC_OK


if __name__ == "__main__":
    raise SystemExit(main())
