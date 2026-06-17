#!/usr/bin/env python3
"""gatekeeper_assign_version.py — v1.1.7 (owner directive 2026-06-17).

THE GATEKEEPER ASSIGNS ALL VERSIONS. An authoring agent (field / core /
benchmark) opens a PR that carries the chip-AGNOSTIC fix + regression tests but
NO version bump — because two PRs in flight that each bumped their own version
would COLLIDE (both pick `x.y.(z+1)`), and only the SERIALIZED gatekeeper, which
lands PRs one at a time onto an advancing `main`, can assign a strictly-monotonic
version per merge. This program is that assignment step: at merge time the
gatekeeper reads the CURRENT `main` version and computes + (optionally) writes the
NEXT version into the PR's tree, so the squash-merged commit carries exactly one
gatekeeper-assigned version bump.

VERSION SCHEME (BINDING): patch段 0..99 (兩位數，不進三位數);
  x.y.99 之後 = x.(y+1).0  (minor +1, patch 歸 0). 例：1.0.99 → 1.1.0 → 1.1.1.
The `x.y.0` rollover is a MINOR MILESTONE → the gatekeeper runs the FULL suite
before landing it (the cadence decision now belongs to the gatekeeper, since the
gatekeeper owns the version — the author cannot know it).

INTERFACES
----------
    gatekeeper_assign_version.py [--repo DIR] [--from-version X.Y.Z]
                                 [--write] [--json OUT]

  --repo DIR        repo / plugin-root to resolve plugin.json + marketplace.json
                    (default: walk up from this file to the plugin root).
  --from-version    the BASE version to increment from (default: read the repo's
                    CURRENT plugin.json version — i.e. main's version at merge).
  --write           apply the assigned version to BOTH plugin.json AND the
                    marketplace.json `vibe-ic` entry (keeps them in sync — the
                    marketplace_version_sync_check invariant). Without --write
                    the program only PRINTS the assigned version (a dry-run).
  --json OUT        write {from, assigned, milestone, cadence, wrote[]} JSON.

EXIT CODES
----------
    0  assigned (and written, if --write)
    2  bad input — unparseable current version / files not found

chip-AGNOSTIC: pure semver arithmetic over the plugin's own version files; no
chip / vendor / SKU literal.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_THIS = Path(__file__).resolve()
_PROGRAMS_DIR = _THIS.parent
sys.path.insert(0, str(_PROGRAMS_DIR))
import version_bump_monotonic_check as _vbm  # noqa: E402  (reuse parse_semver)

_PATCH_MAX = 99  # patch段 0..99; x.y.99 -> x.(y+1).0


def next_version(cur: str) -> Optional[str]:
    """The strictly-monotonic NEXT version after `cur` under the BINDING scheme:
    patch+1 while patch < 99; at x.y.99 roll over to x.(y+1).0. Returns None when
    `cur` is not a parseable `X.Y.Z`."""
    t = _vbm.parse_semver(cur)
    if t is None:
        return None
    major, minor, patch = t
    if patch < _PATCH_MAX:
        return f"{major}.{minor}.{patch + 1}"
    return f"{major}.{minor + 1}.0"


def is_milestone(version: str) -> bool:
    """An x.y.0 version is a MINOR MILESTONE (patch component == 0) → FULL suite."""
    t = _vbm.parse_semver(version)
    return t is not None and t[2] == 0


def _plugin_root(repo: Optional[Path]) -> Path:
    if repo is not None:
        # accept either the repo root (has vibe-ic-marketplace/) or the plugin
        # root (has .claude-plugin/plugin.json) directly.
        cand = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        if (cand / ".claude-plugin" / "plugin.json").is_file():
            return cand
        if (repo / ".claude-plugin" / "plugin.json").is_file():
            return repo
        return cand
    # default: walk up from programs/ to the plugin root (…/plugins/vibe-ic/).
    return _PROGRAMS_DIR.parent


def _plugin_json(plugin_root: Path) -> Path:
    return plugin_root / ".claude-plugin" / "plugin.json"


def _marketplace_json(plugin_root: Path) -> Optional[Path]:
    # the marketplace.json that carries the `vibe-ic` entry lives at the
    # marketplace root: <plugin_root>/../../.claude-plugin/marketplace.json.
    mj = plugin_root.parent.parent / ".claude-plugin" / "marketplace.json"
    return mj if mj.is_file() else None


def _read_current(plugin_root: Path) -> Optional[str]:
    pj = _plugin_json(plugin_root)
    if not pj.is_file():
        return None
    try:
        return json.loads(pj.read_text()).get("version")
    except Exception:
        return None


def _write_version(plugin_root: Path, version: str) -> List[str]:
    """Write `version` into plugin.json AND the marketplace.json vibe-ic entry.
    String-replace the plugin.json `version` field (preserve formatting); rewrite
    the marketplace.json with json.dumps. Returns the list of files written."""
    wrote: List[str] = []
    pj = _plugin_json(plugin_root)
    cur = json.loads(pj.read_text()).get("version")
    txt = pj.read_text()
    new = txt.replace(f'"version": "{cur}"', f'"version": "{version}"', 1)
    if new == txt:  # formatting differs — fall back to a JSON round-trip
        d = json.loads(txt)
        d["version"] = version
        new = json.dumps(d, indent=2) + "\n"
    pj.write_text(new)
    wrote.append(str(pj))
    mj = _marketplace_json(plugin_root)
    if mj is not None:
        d = json.loads(mj.read_text())
        for entry in d.get("plugins", []) or []:
            if isinstance(entry, dict) and entry.get("name") == "vibe-ic":
                entry["version"] = version
        mj.write_text(json.dumps(d, indent=2) + "\n")
        wrote.append(str(mj))
    return wrote


def assign(repo: Optional[Path], from_version: Optional[str],
           write: bool) -> Tuple[dict, int]:
    plugin_root = _plugin_root(repo)
    cur = from_version or _read_current(plugin_root)
    if not cur:
        return ({"error": f"no current version (plugin.json under {plugin_root})"},
                2)
    nxt = next_version(cur)
    if nxt is None:
        return ({"error": f"unparseable current version {cur!r}"}, 2)
    wrote: List[str] = []
    if write:
        if not _plugin_json(plugin_root).is_file():
            return ({"error": f"plugin.json not found under {plugin_root}"}, 2)
        wrote = _write_version(plugin_root, nxt)
    report = {
        "from": cur,
        "assigned": nxt,
        "milestone": is_milestone(nxt),
        "cadence": "FULL" if is_milestone(nxt) else "TARGETED",
        "wrote": wrote,
    }
    return report, 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Gatekeeper version assignment: compute (and optionally "
                    "write) the next strictly-monotonic version.")
    ap.add_argument("--repo", default=None, type=Path,
                    help="repo / plugin-root (default: walk up from this file)")
    ap.add_argument("--from-version", default=None,
                    help="base version to increment (default: read plugin.json)")
    ap.add_argument("--write", action="store_true",
                    help="apply the assigned version to plugin.json + "
                         "marketplace.json (else dry-run / print only)")
    ap.add_argument("--json", default=None, help="write the report JSON here")
    args = ap.parse_args(argv)
    report, rc = assign(args.repo, args.from_version, args.write)
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    if rc == 0:
        verb = "wrote" if args.write else "would assign"
        print(f"gatekeeper_assign_version: {verb} {report['from']} -> "
              f"{report['assigned']} "
              f"({'MILESTONE/FULL' if report['milestone'] else 'patch/TARGETED'})")
        for f in report.get("wrote", []):
            print(f"  + {f}")
    else:
        print(f"ERROR: {report.get('error')}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
