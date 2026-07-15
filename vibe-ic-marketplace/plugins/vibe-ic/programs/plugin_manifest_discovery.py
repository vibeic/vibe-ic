#!/usr/bin/env python3
"""plugin_manifest_discovery.py — ONE source of truth for locating EVERY
version-bearing manifest of a plugin (ORGANIC #152).

A repo can carry MORE THAN ONE ``marketplace.json`` that references the SAME
plugin. This tree carries two, at DIFFERENT ancestor depths of the plugin root
(``vibe-ic-marketplace/plugins/vibe-ic``):

  * the NESTED maintained manifest:  ``vibe-ic-marketplace/.claude-plugin/marketplace.json``
  * the REPO-ROOT manifest:          ``.claude-plugin/marketplace.json``

The two version tools historically each missed a DIFFERENT one:
  * ``gatekeeper_assign_version.py --write`` bumped plugin.json + the NESTED
    manifest but NOT the root (v1.4.28 field report);
  * ``marketplace_version_sync_check.py --fix`` bumped the ROOT but NOT the
    nested (v1.4.17 incident).
Either single-tool path could ship a sync-check red light or (worse) a silent
``/plugin update`` no-op.

Because BOTH manifests live at ANCESTOR directories of the plugin root, a SINGLE
UPWARD walk from the plugin root finds both — direction- and cwd-independent.
Binding on the RESOLVED plugin.json abs-path skips an unrelated / sibling-
checkout manifest (its ``plugins[].source`` resolves to a different plugin.json).

chip-AGNOSTIC: pure filesystem + JSON; no chip / vendor / SKU literal.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

_MAX_ASCEND = 16


def plugin_json_of(plugin_root: Path) -> Path:
    return plugin_root / ".claude-plugin" / "plugin.json"


def _entry_source(entry: dict) -> Optional[str]:
    src = entry.get("source")
    if isinstance(src, dict):
        src = src.get("path") or src.get("source")
    return src if isinstance(src, str) else None


def _manifest_plugin_json_paths(mkt_json: Path) -> List[Path]:
    """Abs plugin.json paths every ``plugins[].source`` in this manifest resolves
    to (only those that exist)."""
    try:
        mkt = json.loads(mkt_json.read_text())
    except Exception:
        return []
    mkt_dir = mkt_json.parent.parent  # strip .claude-plugin/
    out: List[Path] = []
    for entry in mkt.get("plugins", []) or []:
        if not isinstance(entry, dict):
            continue
        src = _entry_source(entry)
        if src is None:
            continue
        pj = (mkt_dir / src).resolve() / ".claude-plugin" / "plugin.json"
        if pj.is_file():
            out.append(pj)
    return out


def manifest_references_plugin(mkt_json: Path, plugin_json: Path) -> bool:
    pj = plugin_json.resolve()
    return any(p == pj for p in _manifest_plugin_json_paths(mkt_json))


def find_plugin_and_manifests(plugin_root: Path) -> Tuple[Path, List[Path]]:
    """``(plugin_json, [marketplace.json ...])`` — the plugin's own plugin.json
    plus EVERY ``.claude-plugin/marketplace.json`` at an ANCESTOR directory of the
    plugin root that references it. Nearest ancestor first; deterministic."""
    plugin_root = plugin_root.resolve()
    pj = plugin_json_of(plugin_root)
    manifests: List[Path] = []
    cur = plugin_root
    for _ in range(_MAX_ASCEND):
        cand = cur / ".claude-plugin" / "marketplace.json"
        if cand.is_file() and manifest_references_plugin(cand, pj):
            rc = cand.resolve()
            if rc not in manifests:
                manifests.append(rc)
        if cur.parent == cur:
            break
        cur = cur.parent
    return pj, manifests


def read_plugin_version(plugin_root: Path) -> Optional[str]:
    try:
        return json.loads(plugin_json_of(plugin_root).read_text()).get("version")
    except Exception:
        return None


def _write_plugin_json_version(pj: Path, version: str) -> None:
    """String-replace the plugin.json ``version`` field (preserves formatting);
    fall back to a JSON round-trip if the field is not found verbatim."""
    txt = pj.read_text()
    cur = json.loads(txt).get("version")
    new = txt.replace(f'"version": "{cur}"', f'"version": "{version}"', 1) \
        if cur else txt
    if new == txt:
        d = json.loads(txt)
        d["version"] = version
        new = json.dumps(d, indent=2) + "\n"
    pj.write_text(new)


def _write_manifest_version(mkt_json: Path, plugin_json: Path,
                            version: str) -> bool:
    """Set ``version`` on every ``plugins[]`` entry whose source resolves to
    plugin_json. Returns True iff the file was written (an entry changed).
    Preserves the file's existing unicode-escaping style (ensure_ascii inferred
    from the original) so the write is a MINIMAL diff — only the version line
    changes, never the descriptions."""
    try:
        txt = mkt_json.read_text()
        mkt = json.loads(txt)
    except Exception:
        return False
    mkt_dir = mkt_json.parent.parent
    pj = plugin_json.resolve()
    changed = False
    for entry in mkt.get("plugins", []) or []:
        if not isinstance(entry, dict):
            continue
        src = _entry_source(entry)
        if src is None:
            continue
        entry_pj = (mkt_dir / src).resolve() / ".claude-plugin" / "plugin.json"
        if entry_pj == pj and entry.get("version") != version:
            entry["version"] = version
            changed = True
    if changed:
        escaped = "\\u" in txt      # keep the original's escaping style
        mkt_json.write_text(
            json.dumps(mkt, indent=2, ensure_ascii=escaped) + "\n")
    return changed


def write_version_all(plugin_root: Path, version: str) -> List[str]:
    """Write ``version`` into plugin.json AND EVERY manifest referencing it.
    Returns the list of files ACTUALLY written (plugin.json always; each manifest
    whose entry changed). The invariant it guarantees: after this call every
    discovered manifest carries `version`."""
    pj, manifests = find_plugin_and_manifests(plugin_root)
    wrote: List[str] = []
    _write_plugin_json_version(pj, version)
    wrote.append(str(pj))
    for mkt in manifests:
        if _write_manifest_version(mkt, pj, version):
            wrote.append(str(mkt))
    return wrote


def _manifest_versions_for(mkt_json: Path, plugin_json: Path) -> List[Optional[str]]:
    try:
        mkt = json.loads(mkt_json.read_text())
    except Exception:
        return []
    mkt_dir = mkt_json.parent.parent
    pj = plugin_json.resolve()
    out: List[Optional[str]] = []
    for entry in mkt.get("plugins", []) or []:
        if not isinstance(entry, dict):
            continue
        src = _entry_source(entry)
        if src is None:
            continue
        entry_pj = (mkt_dir / src).resolve() / ".claude-plugin" / "plugin.json"
        if entry_pj == pj:
            out.append(entry.get("version"))
    return out


def verify_synced(plugin_root: Path, expected: Optional[str] = None
                  ) -> Tuple[bool, List[Tuple[str, Optional[str], str]]]:
    """``(ok, drift)`` — read plugin.json + EVERY discovered manifest; ``drift`` is
    a list of ``(path, found_version, expected_version)``. ``expected`` defaults to
    plugin.json's own version (the source of truth). A post-write self-check for
    the two version tools: any manifest left stale → ``ok=False``."""
    pj, manifests = find_plugin_and_manifests(plugin_root)
    pv = read_plugin_version(plugin_root)
    exp = expected if expected is not None else pv
    drift: List[Tuple[str, Optional[str], str]] = []
    if pv != exp:
        drift.append((str(pj), pv, exp or ""))
    for mkt in manifests:
        for v in _manifest_versions_for(mkt, pj):
            if v != exp:
                drift.append((str(mkt), v, exp or ""))
    return (len(drift) == 0, drift)
