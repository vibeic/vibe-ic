#!/usr/bin/env python3
"""assign_version.py — the ONE command that assigns the next plugin version.

    tools/release/assign_version.py --next patch|minor [--repo DIR] [--dry-run]
                                    [--json OUT]

WHY THIS EXISTS (vibe-ic#2350)
==============================
MEASURED 2026-09-17 on e9135ccd0: `plugin.json`, both `marketplace.json` and the
README prose said 1.21.6, last moved by 592fcf53c (2026-09-13), 417 commits and
136 first-parent landings earlier. `claude plugin update` compares nothing but
that string, so for four days every installed user was told "already at the
latest version" while the marketplace clone moved hundreds of commits ahead.

The writer existed (`programs/gatekeeper_assign_version.py --write`) and so did
every check (`marketplace_version_sync_check`, `plugin_version_prose_sync_check`,
`version_bump_monotonic_check`). What did not exist was one command a lander
runs that does the assignment AND proves it: the writer only knows `patch`, and
the checks all run somewhere a `gh pr merge` landing never passes. This is that
command. It adds no second writer — it calls the existing one.

WHAT IT MAY CHANGE, AND HOW THAT IS PROVEN
==========================================
A DECLARED version position is a place the repo states the version it ships:

  * `plugin.json` `version`;
  * the `plugins[].version` of every `marketplace.json` entry whose source is
    that plugin (repo-root and nested);
  * the README claim forms `plugin_version_prose_sync_check` recognises.

Anything else that happens to spell the old version is a QUOTATION — a
docstring citing "MEASURED on plugin 1.21.6", a fixture, a corpus cell name —
and must not move. The landing chain once ran a tree-wide `sed s/$CUR/$V/g`,
and a docstring citing v1.18.84 was rewritten by twelve consecutive landings
(#2137). So the write is followed by checks that do NOT trust the writer:

  1. every file outside the declared set is byte-identical to before;
  2. every declared file equals an expectation derived HERE, independently:
     the JSON documents equal the old documents with only the declared fields
     set, and differ from the old text only on `"version"` lines; the prose
     files equal the old text with only the recognised claims rewritten;
  3. the repo's own checks agree: the manifests are in sync at the new version,
     the prose audit is PASS, and the new version is strictly greater.

Any failure RESTORES every file it wrote and exits 1, naming what was missed or
what moved that should not have. A position the writer skipped is a failure of
check 2; a quotation the writer touched is a failure of check 1 or 2.

`--dry-run` performs the same write and the same checks, prints the change, and
restores the tree — so a dry run is a measurement, not a prediction.

The mcp-eda server carries its OWN version (`mcp-eda/package.json`,
`SERVER_VERSION`), a separate line from the plugin's; it is not a declared
position of the plugin version and this command does not touch it.

EXIT CODES
    0  assigned (or, with --dry-run, assigned-verified-and-restored)
    1  refused after writing: a declared position was missed or an undeclared
       byte changed; the tree is restored
    2  bad input: no parseable current version, or the declared positions
       already disagree before the bump (fix that drift first — a bump from a
       drifted state would hide which value was right)

chip-AGNOSTIC: semver arithmetic over the repo's own version files.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_THIS = Path(__file__).resolve()
_SELF_ROOT = _THIS.parents[2]
_PROGRAMS = _SELF_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
sys.path.insert(0, str(_PROGRAMS))

import gatekeeper_assign_version as _gav        # noqa: E402  the one writer
import plugin_manifest_discovery as _pmd        # noqa: E402
import plugin_version_prose_sync_check as _prose  # noqa: E402
import version_bump_monotonic_check as _vbm     # noqa: E402

RC_OK, RC_REFUSED, RC_BAD_INPUT = 0, 1, 2
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache"}



def derive_cadence(cur: Optional[str], prev: Optional[str]) -> Tuple[str, str]:
    """Return (cadence, version_bump_label).

    cadence ∈ {"FULL", "TARGETED", "NONE"}; FULL for an x.y.0 milestone,
    TARGETED for an x.y.Z patch (Z>0). NONE when there is no parseable bump
    (no version change in the diff)."""
    cur_t = _vbm.parse_semver(cur) if cur else None
    prev_t = _vbm.parse_semver(prev) if prev else None
    if cur_t is None:
        return "NONE", f"unparseable/none (current={cur!r})"
    label = f"{prev}->{cur}" if prev else f"-> {cur}"
    # An x.y.0 patch component is a MINOR/major milestone -> FULL suite.
    if cur_t[2] == 0:
        return "FULL", label
    return "TARGETED", label


def next_version(cur: str, part: str) -> Optional[str]:
    t = _vbm.parse_semver(cur)
    if t is None:
        return None
    if part == "patch":
        return _gav.next_version(cur)          # patch 0..99, then x.(y+1).0
    if part == "minor":
        return f"{t[0]}.{t[1] + 1}.0"
    raise ValueError(f"unknown --next {part!r}")


# -- the tree, measured --------------------------------------------------------
def _files(repo: Path) -> List[Path]:
    """Every file a write could reach: tracked and untracked-not-ignored when the
    repo is a git checkout, otherwise a walk."""
    if (repo / ".git").exists():
        r = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "-co", "--exclude-standard"],
            capture_output=True)
        if r.returncode == 0:
            return [repo / p for p in r.stdout.decode(errors="surrogateescape")
                    .split("\0") if p and (repo / p).is_file()]
    out = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        out.extend(Path(root) / n for n in names)
    return out


def _digest(p: Path) -> Optional[str]:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _snapshot(files: List[Path], declared: List[Path], old: str
              ) -> Tuple[Dict[Path, Optional[str]], Dict[Path, bytes]]:
    """(digest of every file, bytes of every file a bump could plausibly touch).

    Bytes are kept for the declared files AND for every file that spells the old
    version, because those are exactly the files a wrong writer rewrites — the
    #2137 lander's `sed` reached nothing else. Restoring them is what makes a
    refusal leave the tree as it found it."""
    needle = old.encode()
    digests: Dict[Path, Optional[str]] = {}
    keep: Dict[Path, bytes] = {}
    wanted = {p.resolve() for p in declared}
    for p in files:
        try:
            data = p.read_bytes()
        except OSError:
            digests[p] = None
            continue
        digests[p] = hashlib.sha256(data).hexdigest()
        if p.resolve() in wanted or needle in data:
            keep[p] = data
    for p in declared:
        if p not in keep:
            keep[p] = p.read_bytes()
    return digests, keep


def declared_files(plugin_root: Path) -> Tuple[Path, List[Path], List[Path]]:
    """(plugin.json, manifests, existing prose sites) — the only files a bump may
    change. Resolved by the same discovery the writer and the checks use."""
    pj, manifests = _pmd.find_plugin_and_manifests(plugin_root)
    root = _gav._prose_root(manifests)
    prose = ([root / rel for rel in _prose._PROSE_SITES if (root / rel).is_file()]
             if root is not None else [])
    return pj, manifests, prose


# -- the independent expectation -----------------------------------------------
def _expected_prose(text: str, new: str) -> str:
    for _name, rx, compare in _prose._CLAIMS:
        want = _prose._wanted(new, compare)
        text = rx.sub(lambda m, w=want: m.group(0)[:m.start(1) - m.start()] + w
                      + m.group(0)[m.end(1) - m.start():], text)
    return text


def _expected_manifest(doc: dict, mkt: Path, pj: Path, new: str) -> dict:
    base = mkt.parent.parent
    for entry in doc.get("plugins", []) or []:
        if isinstance(entry, dict) and isinstance(entry.get("source"), str):
            if ((base / entry["source"]).resolve() / ".claude-plugin"
                    / "plugin.json") == pj.resolve():
                entry["version"] = new
    return doc


_VERSION_LINE = re.compile(r'"version"\s*:')


def _json_findings(path: Path, before: str, after: str, expected: dict) -> List[str]:
    out = []
    try:
        got = json.loads(after)
    except ValueError as exc:
        return [f"{path}: no longer parses as JSON ({exc})"]
    if got != expected:
        out.append(f"{path}: the document is not the old one with only the "
                   f"declared version field(s) moved")
    a, b = before.splitlines(), after.splitlines()
    if len(a) != len(b):
        out.append(f"{path}: line count changed {len(a)} -> {len(b)}; only the "
                   f"version value may move")
    else:
        for n, (x, y) in enumerate(zip(a, b), 1):
            if x != y and not (_VERSION_LINE.search(x) and _VERSION_LINE.search(y)):
                out.append(f"{path}:{n}: a non-version line changed: {x!r} -> {y!r}")
    return out


def verify(repo: Path, plugin_root: Path, old: str, new: str,
           snap_hash: Dict[Path, Optional[str]], snap_text: Dict[Path, str]
           ) -> List[str]:
    """Every reason the tree after the write is not exactly the declared bump."""
    pj, manifests, prose = declared_files(plugin_root)
    declared = {p.resolve() for p in [pj, *manifests, *prose]}
    findings: List[str] = []

    # 1. nothing outside the declared set moved
    for p in _files(repo):
        if p.resolve() in declared:
            continue
        if _digest(p) != snap_hash.get(p):
            findings.append(f"{p.relative_to(repo)}: changed, and it is not a "
                            f"declared version position")
    for p in snap_hash:
        if not p.exists():
            findings.append(f"{p.relative_to(repo)}: deleted by the bump")

    # 2. each declared file is exactly the independently derived expectation
    before_pj = json.loads(snap_text[pj])
    before_pj["version"] = new
    findings += _json_findings(pj, snap_text[pj], pj.read_text(), before_pj)
    for mkt in manifests:
        exp = _expected_manifest(json.loads(snap_text[mkt]), mkt, pj, new)
        findings += _json_findings(mkt, snap_text[mkt], mkt.read_text(), exp)
    for site in prose:
        want = _expected_prose(snap_text[site], new)
        got = site.read_text(errors="replace")
        if got != want:
            diff = [l for l in difflib.unified_diff(
                want.splitlines(), got.splitlines(), "expected", "written",
                lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
            findings.append(f"{site.relative_to(repo)}: prose is not exactly the "
                            f"declared claims moved: {diff[:4]}")

    # 3. the repo's own checks agree
    ok, drift = _pmd.verify_synced(plugin_root, expected=new)
    if not ok:
        findings += [f"{p}: states {v!r}, the assigned version is {w!r}"
                     for p, v, w in drift]
    root = _gav._prose_root(manifests)
    if root is not None:
        verdict, prose_findings, _ = _prose.audit(root)
        if verdict != "PASS":
            findings += [f"prose audit {verdict}: {f['detail']}"
                         for f in prose_findings]
    if _vbm.parse_semver(new) <= _vbm.parse_semver(old):
        findings.append(f"{new} is not strictly greater than {old}")
    return findings


# -- the command ---------------------------------------------------------------
def assign(repo: Path, part: str, dry_run: bool = False) -> Tuple[dict, int]:
    repo = repo.resolve()
    plugin_root = _gav._plugin_root(repo)
    old = _gav._read_current(plugin_root)
    if not old or _vbm.parse_semver(old) is None:
        return {"error": f"no parseable version in {_gav._plugin_json(plugin_root)}"}, \
            RC_BAD_INPUT
    new = next_version(old, part)

    # PREFLIGHT: the declared positions must agree BEFORE the bump.
    ok, drift = _pmd.verify_synced(plugin_root, expected=old)
    pj, manifests, prose = declared_files(plugin_root)
    root = _gav._prose_root(manifests)
    pre = [f"{p}: states {v!r}, plugin.json says {w!r}" for p, v, w in drift]
    if root is not None:
        verdict, pf, _ = _prose.audit(root)
        if verdict != "PASS":
            pre += [f"prose audit {verdict}: {f['detail']}" for f in pf]
    if pre:
        return {"error": "the declared version positions already disagree; "
                         "refusing to bump from a drifted state",
                "from": old, "findings": pre}, RC_BAD_INPUT

    declared = [pj, *manifests, *prose]
    snap_hash, snap_bytes = _snapshot(_files(repo), declared, old)
    snap_text = {p: snap_bytes[p].decode(errors="replace") for p in declared}

    def restore():
        for p, b in snap_bytes.items():
            try:
                if p.read_bytes() == b:
                    continue
            except OSError:
                pass
            p.write_bytes(b)

    try:
        _gav._write_version(plugin_root, new)
        write_error = ""
    except (RuntimeError, OSError) as exc:
        write_error = f"the writer refused: {exc}"
    findings = ([write_error] if write_error else []) + \
        verify(repo, plugin_root, old, new, snap_hash, snap_text)

    changed = []
    for p in declared:
        now = p.read_text(errors="replace")
        if now != snap_text[p]:
            changed.append({
                "file": str(p.relative_to(repo)),
                "diff": [l for l in difflib.unified_diff(
                    snap_text[p].splitlines(), now.splitlines(), lineterm="", n=0)
                    if l[:1] in "+-" and l[:3] not in ("+++", "---")]})
    cadence, label = derive_cadence(new, old)
    report = {"from": old, "assigned": new, "next": part, "cadence": cadence,
              "bump": label, "dry_run": dry_run, "changed": changed,
              "declared_positions": [str(p.relative_to(repo)) for p in declared],
              "findings": findings}
    if findings or dry_run:
        restore()
        report["restored"] = True
    return report, (RC_REFUSED if findings else RC_OK)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--next", required=True, choices=("patch", "minor"))
    ap.add_argument("--repo", type=Path, default=_SELF_ROOT)
    ap.add_argument("--dry-run", action="store_true",
                    help="write, verify, print the change, then restore")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)
    report, rc = assign(args.repo, args.next, args.dry_run)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    if "error" in report:
        print(f"assign_version: REFUSED — {report['error']}", file=sys.stderr)
        for f in report.get("findings", []):
            print(f"  - {f}", file=sys.stderr)
        return rc
    verb = ("would assign" if args.dry_run else "assigned") if rc == 0 else "REFUSED"
    print(f"assign_version: {verb} {report['from']} -> {report['assigned']} "
          f"(--next {args.next}; cadence {report['cadence']})")
    for c in report["changed"]:
        print(f"  {c['file']}")
        for line in c["diff"]:
            print(f"    {line}")
    for f in report["findings"]:
        print(f"  - {f}", file=sys.stderr)
    if report.get("restored"):
        print("  (tree restored)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
