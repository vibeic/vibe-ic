#!/usr/bin/env python3
"""marketplace_version_sync_check.py

Closes the version-drift bug where ``marketplace.json`` declares
``plugins[].version`` differently from each plugin's own
``plugin.json.version``. When the two disagree, ``/plugin update`` reads
marketplace.json as the source of truth, sees no version change, and
silently no-ops — leaving end-users stuck on stale cache versions.

Concrete failure mode (commit ed516664):
    plugin.json:       0.135.0
    marketplace.json plugins[].version:  0.120.0  (stale 15 minor versions)
    `/plugin update <plugin>` → "already at latest" message even though
    end-user still on 0.134.0 cache. Manual installed_plugins.json edit
    required to recover.

This gate is **chip-AGNOSTIC** — applies to ANY plugin marketplace.

Algorithm:
    1. Locate the marketplace.json (default: walk up from cwd or accept
       --marketplace-dir).
    2. For each entry in marketplace.json.plugins[]:
         a. Resolve the plugin's plugin.json via plugins[].source path.
         b. Compare marketplace.json plugins[].version vs plugin.json.version.
         c. FAIL if mismatch.
    3. PASS only when every plugin is in sync.

Usage:
    python3 marketplace_version_sync_check.py [--marketplace-dir <path>] [--fix]

    --fix      Automatically bump marketplace.json plugins[].version to
               match plugin.json.version (writes the file back).

Exit codes:
    0  PASS — every plugin's marketplace + plugin.json versions match.
    1  FAIL — at least one mismatch (run with --fix to auto-correct).
    2  IO / parse error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple


def _find_marketplace_json(start: Path) -> Optional[Path]:
    """Walk up from start looking for .claude-plugin/marketplace.json."""
    cur = start.resolve()
    for _ in range(8):
        cand = cur / ".claude-plugin" / "marketplace.json"
        if cand.is_file():
            return cand
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _load_plugin_json(marketplace_dir: Path,
                     source: str) -> Optional[Tuple[Path, dict]]:
    """Resolve plugins[].source (relative to marketplace dir) to plugin.json."""
    if isinstance(source, dict):
        # alternate marketplace schema where source is {"path": "./..."}
        source = source.get("path") or source.get("source")
    if not isinstance(source, str):
        return None
    plugin_dir = (marketplace_dir / source).resolve()
    plugin_json = plugin_dir / ".claude-plugin" / "plugin.json"
    if not plugin_json.is_file():
        return None
    try:
        return plugin_json, json.loads(plugin_json.read_text())
    except Exception:
        return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--marketplace-dir", type=Path, default=None,
                   help="Path containing .claude-plugin/marketplace.json. "
                        "Default: walk up from cwd.")
    p.add_argument("--fix", action="store_true",
                   help="Auto-bump marketplace.json plugins[].version to match plugin.json.")
    args = p.parse_args()

    start = args.marketplace_dir if args.marketplace_dir else Path.cwd()
    if not start.is_dir():
        print(f"ERROR: --marketplace-dir not a directory: {start}",
              file=sys.stderr)
        return 2

    mkt_json = _find_marketplace_json(start)
    if mkt_json is None:
        print(f"[SKIP] marketplace_version_sync_check: "
              f"no .claude-plugin/marketplace.json found within 8 levels of "
              f"{start}")
        return 0

    try:
        mkt = json.loads(mkt_json.read_text())
    except Exception as e:
        print(f"ERROR: cannot parse {mkt_json}: {e}", file=sys.stderr)
        return 2

    marketplace_dir = mkt_json.parent.parent  # strip .claude-plugin/
    plugin_entries = mkt.get("plugins", [])
    if not isinstance(plugin_entries, list):
        print(f"[SKIP] marketplace_version_sync_check: "
              f"{mkt_json} has no plugins[] array")
        return 0

    findings: List[Tuple[str, str, str, Path]] = []  # (name, mkt_ver, pj_ver, pj_path)
    matched: List[str] = []
    for entry in plugin_entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "<unknown>")
        mkt_ver = entry.get("version")
        if mkt_ver is None:
            # marketplace.json doesn't pin a version for this plugin — OK
            matched.append(f"{name} (no version pinned)")
            continue
        resolved = _load_plugin_json(marketplace_dir, entry.get("source", ""))
        if resolved is None:
            findings.append((name, str(mkt_ver),
                             "<plugin.json not found>",
                             marketplace_dir))
            continue
        pj_path, pj = resolved
        pj_ver = pj.get("version")
        if pj_ver != mkt_ver:
            findings.append((name, str(mkt_ver), str(pj_ver), pj_path))
        else:
            matched.append(f"{name}={pj_ver}")

    if not findings:
        print(f"[PASS] marketplace_version_sync_check: "
              f"{len(matched)} plugin(s) — all marketplace + plugin.json "
              f"versions in sync ({', '.join(matched)})")
        return 0

    if args.fix:
        # auto-bump marketplace.json plugins[].version to match plugin.json
        for entry in plugin_entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            for fname, mver, pver, pjpath in findings:
                if fname == name and pver != "<plugin.json not found>":
                    entry["version"] = pver
                    print(f"  [FIX] {name}: marketplace.json {mver} → {pver}")
        mkt_json.write_text(json.dumps(mkt, indent=2, ensure_ascii=False) + "\n")
        print(f"[PASS_AFTER_FIX] marketplace_version_sync_check: "
              f"wrote {mkt_json} with {len(findings)} version(s) bumped")
        return 0

    print(f"[FAIL] marketplace_version_sync_check: "
          f"{len(findings)} plugin(s) have marketplace.json "
          f"plugins[].version != plugin.json.version. "
          f"`/plugin update` reads marketplace.json as the version source "
          f"of truth — when these drift, end-user upgrade silently no-ops.")
    for name, mver, pver, pjpath in findings:
        print(f"  - {name}: marketplace.json says {mver!r} but plugin.json "
              f"({pjpath}) says {pver!r}")
    print(f"\nFix: re-run with --fix, OR manually edit "
          f"{mkt_json} to set each plugins[].version to match plugin.json.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
