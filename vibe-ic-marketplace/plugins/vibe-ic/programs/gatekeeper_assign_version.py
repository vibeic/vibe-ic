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
  --write           apply the assigned version to plugin.json, the
                    marketplace.json `vibe-ic` entry (keeps them in sync — the
                    marketplace_version_sync_check invariant), AND the shipped
                    READMEs that state the version in prose (the
                    plugin_version_prose_sync_check invariant — #621). Without
                    --write the program only PRINTS the assigned version (a
                    dry-run). Every restatement of the version has ONE writer,
                    and it is this program; anything it does not write drifts.
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
import plugin_manifest_discovery as _pmd     # noqa: E402  (#152 shared discovery)
import plugin_version_prose_sync_check as _prose  # noqa: E402  (prose follows #621)

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


def _read_current(plugin_root: Path) -> Optional[str]:
    pj = _plugin_json(plugin_root)
    if not pj.is_file():
        return None
    try:
        return json.loads(pj.read_text()).get("version")
    except Exception:
        return None


def _prose_root(manifests: List[Path]) -> Optional[Path]:
    """The repo root whose PROSE states this plugin's version, or None.

    The prose sites are named relative to the REPO root (`README.md`,
    `vibe-ic-marketplace/README.md`, ...), so the root is the OUTERMOST ancestor
    carrying a marketplace.json that references this plugin — `manifests` is
    ordered nearest-ancestor-first, so that is the last entry. A plugin checked
    out with no marketplace ancestor states its version in no repo prose, and
    None says so rather than guessing a root and writing nothing under it.
    """
    if not manifests:
        return None
    return manifests[-1].parent.parent


def _write_version(plugin_root: Path, version: str) -> List[str]:
    """Write `version` into plugin.json AND EVERY marketplace.json that references
    this plugin (both the NESTED and the REPO-ROOT manifest — #152), AND every
    place the shipped READMEs state it in prose (#621). Delegates to the SHARED
    manifest-discovery helper (no hand-rolled single-manifest path that can miss
    one), then POST-WRITE SELF-CHECKS that all of them are in sync and RAISES on
    any residual drift so a partial write can never ship. Returns the list of
    files written.

    WHY PROSE IS WRITTEN HERE AND NOT CORRECTED BY HAND
    ---------------------------------------------------
    `plugin_version_prose_sync_check` shipped with a working `--fix` and NOTHING
    EVER CALLED IT: the repo referenced the checker from the hygiene gate (audit
    only), its own test, and INDEX.md — so every merge advanced the JSON and left
    the three READMEs a reader meets first behind. Measured on the tree that
    prompted this: the READMEs said 1.10.2 against a shipped 1.10.29, i.e. the
    gate had been reporting a true failure for 28 consecutive releases and the
    release path had no step that could ever clear it.

    Re-typing the number by hand is what produced that drift, so this makes the
    ONE WRITER of the version write the prose too — the same reason #152 moved
    manifest writing in here and #800 made emitters READ the version instead of
    restating it as a literal.
    """
    wrote = _pmd.write_version_all(plugin_root, version)
    ok, drift = _pmd.verify_synced(plugin_root, expected=version)
    if not ok:
        raise RuntimeError(
            "gatekeeper_assign_version post-write self-check FAILED — manifest "
            f"drift after writing {version!r}: "
            + "; ".join(f"{p} has {found!r} (want {want!r})"
                        for p, found, want in drift))

    _pj, manifests = _pmd.find_plugin_and_manifests(plugin_root)
    root = _prose_root(manifests)
    if root is None:
        return wrote
    touched = _prose.fix(root, version)
    wrote.extend(str(root / rel) for rel in sorted(touched))
    # Same discipline as the manifest self-check above, through the INDEPENDENT
    # path the hygiene gate uses: re-derive the shipped version from the manifest
    # and re-read every claim. A claim form `fix` does not recognise, or a file it
    # could not write, fails the merge here instead of shipping a README that
    # advertises a version the repo does not ship.
    verdict, findings, _stats = _prose.audit(root)
    if verdict != "PASS":
        raise RuntimeError(
            "gatekeeper_assign_version post-write self-check FAILED — prose "
            f"drift after writing {version!r} ({verdict}): "
            + "; ".join(f["detail"] for f in findings))
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
        try:
            wrote = _write_version(plugin_root, nxt)
        except RuntimeError as e:
            # #152 — the post-write self-check found residual manifest drift.
            # Abort with a clear rc-2 error, not an unhandled traceback.
            return ({"error": str(e), "assigned": nxt}, 2)
        except OSError as e:
            # A version file or a prose site could not be written (read-only
            # checkout, permissions). Same contract as the drift case: the merge
            # stops on a stated error instead of a traceback, and the caller is
            # told which restatement of the version is now out of step.
            return ({"error": f"gatekeeper_assign_version could not write the "
                              f"version {nxt!r} — prose/manifest may be "
                              f"partially written: {e}", "assigned": nxt}, 2)
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
