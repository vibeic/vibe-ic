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

MULTI-MANIFEST (v1.3.49). A repo can carry MORE THAN ONE marketplace.json
that references the SAME plugin. This tree does: the MAINTAINED manifest at
``vibe-ic-marketplace/.claude-plugin/marketplace.json`` (source
``./plugins/vibe-ic``) AND a REPO-ROOT manifest at
``.claude-plugin/marketplace.json`` (source
``./vibe-ic-marketplace/plugins/vibe-ic``). Both resolve to the SAME
plugin.json, so BOTH must carry the same version — but the naive "nearest
marketplace.json" walk only checked the maintained one, letting the repo-root
manifest silently drift (it sat at 1.3.42 for six releases while the maintained
manifest advanced to 1.3.48). This gate now checks EVERY marketplace.json in
the current checkout that resolves to the plugin's own plugin.json, so any
future bump that leaves an OUTER manifest behind FAILs the gate.

This gate is **chip-AGNOSTIC** — applies to ANY plugin marketplace. Only the
version-field equality is enforced; the manifests may legitimately differ in
``owner`` / ``homepage`` / ``source`` / ``description`` (the repo-root and
maintained manifests do), and those are NOT asserted.

Algorithm:
    1. Locate the NEAREST marketplace.json (default: walk up from cwd or accept
       --marketplace-dir). Call it the PRIMARY manifest.
    2. Compute the set of plugin.json abs-paths the primary references.
    3. Walk further up collecting OUTER marketplace.json files, keeping ONLY
       those whose plugins[].source resolves to a plugin.json ALSO referenced
       by the primary (same checkout). This binds "an outer manifest for THIS
       plugin" and skips an unrelated / sibling-checkout manifest (its source
       resolves to a different plugin.json abs-path).
    4. For every manifest (primary + relevant outer), for each plugins[] entry:
         a. Resolve the plugin's plugin.json via plugins[].source path.
         b. Compare plugins[].version vs plugin.json.version.
         c. record a mismatch finding on failure.
    5. PASS only when every plugin in every manifest is in sync.

Usage:
    python3 marketplace_version_sync_check.py [--marketplace-dir <path>] [--fix]

    --fix      Automatically bump each drifting marketplace.json
               plugins[].version to match plugin.json.version (writes the
               file(s) back).

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
from typing import Dict, List, Optional, Set, Tuple


def _find_marketplace_json(start: Path) -> Optional[Path]:
    """Walk up from start looking for the NEAREST .claude-plugin/marketplace.json."""
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


def _resolved_plugin_paths(mkt_json: Path, mkt: dict) -> Set[str]:
    """The set of plugin.json abs-paths this manifest resolves (via source)."""
    marketplace_dir = mkt_json.parent.parent  # strip .claude-plugin/
    paths: Set[str] = set()
    for entry in mkt.get("plugins", []) or []:
        if not isinstance(entry, dict):
            continue
        resolved = _load_plugin_json(marketplace_dir, entry.get("source", ""))
        if resolved is not None:
            paths.add(str(resolved[0].resolve()))
    return paths


def _find_outer_marketplaces(primary_mkt_json: Path,
                             canonical_paths: Set[str]) -> List[Path]:
    """Walk up from the primary manifest's marketplace dir collecting OUTER
    marketplace.json files that reference at least one plugin.json ALSO in
    `canonical_paths` (i.e. the SAME plugin, in the SAME checkout).

    Binding on the resolved plugin.json abs-path is what keeps this bounded to
    the current checkout: a sibling / stale parallel checkout's marketplace.json
    resolves its source to a DIFFERENT plugin.json abs-path, so it is skipped
    (never edited, never causes a spurious FAIL)."""
    outer: List[Path] = []
    seen: Set[str] = {str(primary_mkt_json.resolve())}
    cur = primary_mkt_json.parent.parent  # the marketplace dir of the primary
    for _ in range(8):
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
        cand = cur / ".claude-plugin" / "marketplace.json"
        if not cand.is_file():
            continue
        rc = str(cand.resolve())
        if rc in seen:
            continue
        try:
            m = json.loads(cand.read_text())
        except Exception:
            continue
        if _resolved_plugin_paths(cand, m) & canonical_paths:
            outer.append(cand)
            seen.add(rc)
    return outer


# A mismatch finding: (manifest_path, plugin_name, mkt_ver, pj_ver, pj_path)
Finding = Tuple[Path, str, str, str, Path]


def _check_manifest(mkt_json: Path, mkt: dict,
                    findings: List[Finding], matched: List[str]) -> None:
    """Append version-drift findings (and matched descriptions) for one manifest."""
    marketplace_dir = mkt_json.parent.parent  # strip .claude-plugin/
    plugin_entries = mkt.get("plugins", [])
    if not isinstance(plugin_entries, list):
        return
    label = _rel(mkt_json)
    for entry in plugin_entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "<unknown>")
        mkt_ver = entry.get("version")
        if mkt_ver is None:
            matched.append(f"[{label}] {name} (no version pinned)")
            continue
        resolved = _load_plugin_json(marketplace_dir, entry.get("source", ""))
        if resolved is None:
            findings.append((mkt_json, name, str(mkt_ver),
                             "<plugin.json not found>", marketplace_dir))
            continue
        pj_path, pj = resolved
        pj_ver = pj.get("version")
        if pj_ver != mkt_ver:
            findings.append((mkt_json, name, str(mkt_ver), str(pj_ver), pj_path))
        else:
            matched.append(f"[{label}] {name}={pj_ver}")


def _rel(p: Path) -> str:
    """Path relative to cwd when possible (nicer output), else absolute."""
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except Exception:
        return str(p)


def _apply_fix(mkt_json: Path, mkt: dict, findings: List[Finding]) -> int:
    """Bump this manifest's drifting plugins[].version to plugin.json's. Returns
    the count of versions bumped in this manifest."""
    n = 0
    my = [f for f in findings if f[0] == mkt_json
          and f[3] != "<plugin.json not found>"]
    if not my:
        return 0
    for entry in mkt.get("plugins", []) or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        for _mj, fname, mver, pver, _pj in my:
            if fname == name:
                entry["version"] = pver
                print(f"  [FIX] [{_rel(mkt_json)}] {name}: "
                      f"marketplace.json {mver} → {pver}")
                n += 1
    if n:
        mkt_json.write_text(json.dumps(mkt, indent=2, ensure_ascii=False) + "\n")
    return n


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--marketplace-dir", type=Path, default=None,
                   help="Path containing .claude-plugin/marketplace.json. "
                        "Default: walk up from cwd.")
    p.add_argument("--fix", action="store_true",
                   help="Auto-bump each drifting marketplace.json "
                        "plugins[].version to match plugin.json.")
    args = p.parse_args()

    start = args.marketplace_dir if args.marketplace_dir else Path.cwd()
    if not start.is_dir():
        print(f"ERROR: --marketplace-dir not a directory: {start}",
              file=sys.stderr)
        return 2

    primary = _find_marketplace_json(start)
    if primary is None:
        print(f"[SKIP] marketplace_version_sync_check: "
              f"no .claude-plugin/marketplace.json found within 8 levels of "
              f"{start}")
        return 0

    try:
        primary_mkt = json.loads(primary.read_text())
    except Exception as e:
        print(f"ERROR: cannot parse {primary}: {e}", file=sys.stderr)
        return 2

    if not isinstance(primary_mkt.get("plugins", []), list):
        print(f"[SKIP] marketplace_version_sync_check: "
              f"{primary} has no plugins[] array")
        return 0

    # Build the manifest list: primary + any OUTER manifest that resolves to the
    # SAME plugin.json (the repo-root manifest is exactly this — its source
    # `./vibe-ic-marketplace/plugins/vibe-ic` resolves to the maintained plugin).
    canonical = _resolved_plugin_paths(primary, primary_mkt)
    manifests: List[Tuple[Path, dict]] = [(primary, primary_mkt)]
    seen_paths = {str(primary.resolve())}
    for outer_path in _find_outer_marketplaces(primary, canonical):
        try:
            manifests.append((outer_path, json.loads(outer_path.read_text())))
            seen_paths.add(str(outer_path.resolve()))
        except Exception:
            continue

    # ORGANIC #152 — union in the SHARED, direction-agnostic discovery. The
    # outer-walk above only walks UP from the PRIMARY, so a cwd at the repo root
    # (primary = the ROOT manifest) would MISS the NESTED manifest (it is DOWN,
    # inside vibe-ic-marketplace/) — the v1.4.17 `--fix` blind spot. Walking up
    # from each referenced plugin ROOT finds BOTH manifests regardless of cwd,
    # since both are ancestors of the plugin root. Deduped by resolved path.
    try:
        import plugin_manifest_discovery as _pmd
        for pj_path in canonical:
            plugin_root = Path(pj_path).resolve().parent.parent
            _pj, extra = _pmd.find_plugin_and_manifests(plugin_root)
            for mk in extra:
                rp = str(mk.resolve())
                if rp in seen_paths:
                    continue
                try:
                    manifests.append((mk, json.loads(mk.read_text())))
                    seen_paths.add(rp)
                except Exception:
                    continue
    except Exception:
        pass

    findings: List[Finding] = []
    matched: List[str] = []
    for mkt_json, mkt in manifests:
        _check_manifest(mkt_json, mkt, findings, matched)

    n_manifests = len(manifests)
    if not findings:
        print(f"[PASS] marketplace_version_sync_check: "
              f"{n_manifests} manifest(s), {len(matched)} plugin entr(ies) — "
              f"all marketplace + plugin.json versions in sync "
              f"({', '.join(matched)})")
        return 0

    if args.fix:
        total = 0
        for mkt_json, mkt in manifests:
            total += _apply_fix(mkt_json, mkt, findings)
        # ORGANIC #152 — POST-FIX SELF-CHECK: re-read every manifest and confirm
        # ZERO residual drift; a partial fix (a manifest the walk missed) must
        # not silently pass. Red light → abort with rc 2.
        residual: List[Finding] = []
        recheck_matched: List[str] = []
        for mkt_json, _old in manifests:
            try:
                fresh = json.loads(mkt_json.read_text())
            except Exception:
                continue
            _check_manifest(mkt_json, fresh, residual, recheck_matched)
        if residual:
            print(f"[FAIL] marketplace_version_sync_check: post-fix self-check "
                  f"still finds {len(residual)} drift(s) across "
                  f"{n_manifests} manifest(s) — fix incomplete.")
            for mkt_json, name, mver, pver, _pj in residual:
                print(f"  - [{_rel(mkt_json)}] {name}: {mver!r} != {pver!r}")
            return 2
        print(f"[PASS_AFTER_FIX] marketplace_version_sync_check: "
              f"wrote {total} version(s) across {n_manifests} manifest(s); "
              f"post-fix self-check clean")
        return 0

    print(f"[FAIL] marketplace_version_sync_check: "
          f"{len(findings)} plugin entr(ies) across {n_manifests} manifest(s) "
          f"have marketplace.json plugins[].version != plugin.json.version. "
          f"`/plugin update` reads marketplace.json as the version source "
          f"of truth — when these drift, end-user upgrade silently no-ops.")
    for mkt_json, name, mver, pver, pjpath in findings:
        print(f"  - [{_rel(mkt_json)}] {name}: marketplace.json says {mver!r} "
              f"but plugin.json ({pjpath}) says {pver!r}")
    print(f"\nFix: re-run with --fix, OR manually edit each listed "
          f"marketplace.json to set plugins[].version to match plugin.json.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
