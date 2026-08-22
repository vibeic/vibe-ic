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
    2  IO / parse error, OR this gate compared nothing. THREE branches, and
       this list is one-to-one with them:
         (a) no .claude-plugin/marketplace.json found within 8 levels
             -> reason `no-marketplace-json`
         (b) the primary manifest parsed, but its `plugins` key is present
             and is NOT a list -> reason `manifest-has-no-plugins-array`
         (c) zero plugin entries were compared across EVERY manifest — the
             `plugins` key is absent, or the list is empty, or no entry is a
             usable object -> reason `no-plugin-entries-compared`

    #528 — the missing-input branches used to return 0 while the branches
    BESIDE them ("--marketplace-dir not a directory", "cannot parse
    <manifest>") already returned 2. Both conventions were live in one
    `main()`, twelve lines apart. "The input I audit does not exist" is this
    repo's canonical rc-2 case: `flow_compliance_check._check_program_exit_zero`
    maps rc 2 to the VACUOUS tier, and `gatekeeper_review.GateResult.green` is
    `rc in (0, -1)`, so rc 0 here credited a plain PASS to a run that never
    compared a version — in a MERGE gate.

    WHY (c) IS PHRASED AS A DENOMINATOR AND NOT AS AN INPUT SHAPE. The first
    round of this fix wrote (b) only, and its docstring said "a manifest with
    no plugins[] array" — which reads like (c) but is not what the code did:
    `.get("plugins", [])` hands back the default `[]`, which IS a list, so an
    ABSENT key sailed past (b) and printed `[PASS] ... 0 plugin entr(ies)`.
    Two further shapes did the same (`plugins: []`, and a list holding no
    usable object). A sentinel default in place of `[]` would have closed the
    first of those three and left the other two. (c) is tested against
    `matched` — the gate's OWN record of what it compared — so it needs no
    guess about which malformed spelling appears next.

    The landing usages all supply a directory where the manifest exists AND
    carries comparable entries (`tools/ci/pre_commit_check.sh` guards on
    `[ -d "$SYNC_DIR/.claude-plugin" ]` before invoking at all;
    `tools/ci/repo_hygiene_gates.sh` runs it from the plugin directory;
    `.github/workflows/gatekeeper-ci.yml` passes `$MARKETPLACE_DIR`), so none
    of the three branches fires there — verified by executing all five, see
    `test_marketplace_version_sync_check`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import _vacuous_exit as _vx


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
        # #528 — rc 2, matching the two branches above and below. Routed
        # through the shared site so the printed verdict and the exit code
        # come from the same pair and cannot drift apart again.
        _vx.announce_vacuous("marketplace_version_sync_check",
                             "no-marketplace-json")
        print(f"[SKIP] marketplace_version_sync_check: "
              f"no .claude-plugin/marketplace.json found within 8 levels of "
              f"{start}")
        return _vx.exit_code(passed=True, skipped=True)

    try:
        primary_mkt = json.loads(primary.read_text())
    except Exception as e:
        print(f"ERROR: cannot parse {primary}: {e}", file=sys.stderr)
        return 2

    if not isinstance(primary_mkt.get("plugins", []), list):
        # #528 — same class as the branch above: the manifest parsed, but the
        # array this gate compares versions from is not there, so nothing was
        # compared. Its immediate neighbour ("cannot parse") is already rc 2.
        _vx.announce_vacuous("marketplace_version_sync_check",
                             "manifest-has-no-plugins-array")
        print(f"[SKIP] marketplace_version_sync_check: "
              f"{primary} has no plugins[] array")
        return _vx.exit_code(passed=True, skipped=True)

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
    if not findings and not matched:
        # #528 follow-up — THE DENOMINATOR IS THE TEST, NOT THE INPUT SHAPE.
        #
        # `matched` is this gate's own record of what it actually compared.
        # Empty means zero version comparisons happened, and a PASS over zero
        # comparisons is the thing this whole issue closes — here in a MERGE
        # gate (`gatekeeper_review.GateResult.green` is `rc in (0, -1)`).
        #
        # The first fix guarded ONE input shape (`plugins` present but not a
        # list) and left three more, all of which printed
        # `[PASS] ... 0 plugin entr(ies)`. MEASURED against the pre-#528 file:
        #
        #     plugins key ENTIRELY ABSENT   OLD rc 0 -> NEW rc 2
        #     plugins: []  (empty list)     OLD rc 0 -> NEW rc 2
        #     plugins: ["a", "b"]  (no dict) OLD rc 0 -> NEW rc 2
        #
        # `.get("plugins", [])` makes "absent" and "empty" indistinguishable,
        # and a sentinel default would have fixed only the first of the three.
        # Routing from `matched` fixes all of them and needs no guess about
        # which malformed shape someone will write next — including the case
        # where entries exist but none is a usable object, which no
        # input-shape guard placed before the walk could have seen.
        _vx.announce_vacuous("marketplace_version_sync_check",
                             "no-plugin-entries-compared")
        print(f"[SKIP] marketplace_version_sync_check: "
              f"{n_manifests} manifest(s) carry no comparable plugins[] "
              f"entry, so no version was compared")
        return _vx.exit_code(passed=True, skipped=True)

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
