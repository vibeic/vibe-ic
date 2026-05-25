#!/usr/bin/env python3
"""tools/mcp_eda_sync_check.py — Wave 82 sync gate for mcp-eda dual tree.

mcp-eda-server lives in two places in this repo:

  - <repo_root>/mcp-eda-server/                                 (canonical)
  - vibe-ic-marketplace/plugins/vibe-ic/mcp-eda-server/         (mirror)

The mirror is shipped to plugin consumers; the root tree is the dev
copy. They MUST stay byte-for-byte equivalent for the source files
(`src/`, `test/`, `INSTALL_GUIDE.md`, `package.json`,
`devices_registry.json`, plus any top-level `*.py`/`*.md`).

Build artefacts that are routinely different across the two trees are
EXEMPTED from the diff:

  - node_modules/      (npm install artifact, never committed)
  - __pycache__/       (Python bytecode cache)
  - .pytest_cache/     (pytest cache)
  - package-lock.json  (npm lockfile, divergent across env)
  - serv_req_info.txt  (server-side runtime data)

When drift is found, the script prints the offending paths and exits
1; CI / pre-commit can run it with no args to gate on sync.

Exit codes
==========
0  PASS  — both trees agree on tracked files
1  FAIL  — drift detected
2  USAGE — bad invocation
"""
from __future__ import annotations

import argparse
import filecmp
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_TREE = REPO_ROOT / "mcp-eda-server"
PLUGIN_TREE = (
    REPO_ROOT
    / "vibe-ic-marketplace"
    / "plugins"
    / "vibe-ic"
    / "mcp-eda-server"
)

# Paths (relative to either tree) that may diverge without flagging
# drift. Any directory or filename in this set is ignored anywhere it
# appears in the tree walk.
EXEMPT_NAMES = {
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "package-lock.json",
    "serv_req_info.txt",
    ".DS_Store",
}


def _walk_tree(tree: Path) -> set[Path]:
    """Return every (file) path relative to `tree`, skipping exempt
    names anywhere in the path."""
    out: set[Path] = set()
    if not tree.is_dir():
        return out
    for p in tree.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(tree)
        if any(part in EXEMPT_NAMES for part in rel.parts):
            continue
        out.add(rel)
    return out


def diff_trees(root: Path, plugin: Path) -> dict:
    """Walk both trees; emit the lists of (only-root, only-plugin,
    differing) files."""
    root_files = _walk_tree(root)
    plug_files = _walk_tree(plugin)

    only_root = sorted(str(p) for p in (root_files - plug_files))
    only_plug = sorted(str(p) for p in (plug_files - root_files))
    common = root_files & plug_files
    differing: list[str] = []
    for rel in sorted(str(p) for p in common):
        a = root / rel
        b = plugin / rel
        try:
            if not filecmp.cmp(a, b, shallow=False):
                differing.append(rel)
        except OSError:
            differing.append(rel)
    return {
        "only_root": only_root,
        "only_plugin": only_plug,
        "differing": differing,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Verify mcp-eda-server root tree and plugin mirror agree."
    )
    p.add_argument("--root", type=Path, default=ROOT_TREE,
                   help="Path to <repo_root>/mcp-eda-server (canonical)")
    p.add_argument("--plugin", type=Path, default=PLUGIN_TREE,
                   help="Path to plugin mirror under vibe-ic-marketplace")
    p.add_argument("--strict", action="store_true",
                   help="Strict mode (default).  Always exits 1 on any drift.")
    args = p.parse_args(argv)
    _ = args.strict  # always strict

    if not args.root.is_dir():
        print(f"FAIL — root tree not found: {args.root}")
        return 1
    if not args.plugin.is_dir():
        print(f"FAIL — plugin mirror not found: {args.plugin}")
        return 1

    report = diff_trees(args.root, args.plugin)
    drift = (
        len(report["only_root"])
        + len(report["only_plugin"])
        + len(report["differing"])
    )
    if drift == 0:
        print(
            "PASS — mcp-eda-server root tree and plugin mirror agree "
            "(after exempting node_modules / __pycache__ / "
            ".pytest_cache / package-lock.json)"
        )
        return 0

    print(f"FAIL — mcp-eda dual-tree drift: {drift} difference(s)")
    if report["only_root"]:
        print(f"  · {len(report['only_root'])} file(s) only in root:")
        for f in report["only_root"][:20]:
            print(f"      {f}")
        if len(report["only_root"]) > 20:
            print(f"      … +{len(report['only_root']) - 20} more")
    if report["only_plugin"]:
        print(f"  · {len(report['only_plugin'])} file(s) only in plugin:")
        for f in report["only_plugin"][:20]:
            print(f"      {f}")
        if len(report["only_plugin"]) > 20:
            print(f"      … +{len(report['only_plugin']) - 20} more")
    if report["differing"]:
        print(f"  · {len(report['differing'])} file(s) differ:")
        for f in report["differing"][:20]:
            print(f"      {f}")
        if len(report["differing"]) > 20:
            print(f"      … +{len(report['differing']) - 20} more")
    print()
    print(
        "Fix: re-run tools/sync_opensource.sh (or rsync the canonical "
        "tree into the plugin mirror) and commit the result."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
