#!/usr/bin/env python3
"""pdk_registry_selectable_check.py — a PDK the image ships must be
SELECTABLE, and every asset the registry declares must RESOLVE.

THIS GATE BLOCKS (rc=1) on either.

WHY (vibe-ic#408, the #389 family)
----------------------------------
#408 records a WITHDRAWN drift checker (never pushed) that returned
CONSISTENT for two states it advertised as findings. Both are real
invariants of `pdk_registry.json`, and nothing on main enforces either:

1. IT NEVER CHECKED A DECLARED ASSET. It stat'ed `container_path` and
   nothing else, so a registry whose `liberty_glob`, `tech_lef_glob` and
   `cell_lef_glob` all pointed at a non-existent directory reported clean.
   `--pdk <name>` then dies at asset resolution instead of at argument
   validation — the failure moves later and gets harder to read.

2. IT KEYED THE SHIPPED SIDE ON `basename(container_path)`, NOT ON `name`.
   `--pdk` matches the NAME. Renaming an entry to `<dir>-TYPO` while leaving
   the path alone left a complete, usable PDK in the image that no operator
   could select — the #389 incident condition verbatim — reported as clean.

Measured on main today: 6 entries, 5 carry a `container_path` and all 5
satisfy `name == basename`; 33 declared asset paths, 0 unresolvable. So this
gate is green now. It exists because nothing was keeping it that way, and
because #389 has already recurred three times.

TWO HALVES, JUDGED SEPARATELY
-----------------------------
The NAME half is pure registry data and always runs — it needs no image, so
a host without docker still gets it. The ASSET half needs the image; when no
container is reachable it reports SKIPPED for that half and says so. It is
never folded into a PASS: "I could not look" and "I looked and it is clean"
are different claims, and collapsing them is the defect #408 is about.

chip-AGNOSTIC: reads the registry's own data. `custom_auto_detect` carries no
`container_path` (it is the auto-detect sentinel, not a directory), so the
name rule applies only to entries that declare a path.

USAGE
-----
    pdk_registry_selectable_check.py [--registry F] [--container NAME]
                                     [--json OUT]

EXIT CODES
----------
    0 = PASS     1 = FAIL     2 = registry unreadable
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

_ASSET_SUFFIXES = ("_glob", "_deck")
_ASSET_KEYS_EXTRA = ("lefdef_layermap", "pnr_exclude_cell_file")


def _asset_keys(entry: Dict[str, Any]) -> List[str]:
    return [k for k, v in entry.items()
            if isinstance(v, str) and v
            and (k.endswith(_ASSET_SUFFIXES) or k in _ASSET_KEYS_EXTRA)]


def _container_alive(name: str) -> bool:
    if not name:
        return False
    r = subprocess.run(["docker", "exec", name, "true"],
                       capture_output=True, text=True)
    return r.returncode == 0


def _resolves(container: str, path: str) -> bool:
    r = subprocess.run(
        ["docker", "exec", container, "bash", "-lc",
         f"ls -d {path} >/dev/null 2>&1 && echo OK || echo MISS"],
        capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()
    return bool(tail) and tail[-1] == "OK"


def audit(registry: Path, container: str) -> dict:
    try:
        data = json.loads(registry.read_text(errors="replace"))
    except (OSError, ValueError) as exc:
        return {"readable": False, "reason": f"{type(exc).__name__}: {exc}"}
    entries = [e for e in (data.get("pdks") or []) if isinstance(e, dict)]

    unselectable = []
    for e in entries:
        name, cp = e.get("name"), e.get("container_path")
        if not name or not cp:
            continue          # the auto-detect sentinel declares no directory
        base = str(cp).rstrip("/").rsplit("/", 1)[-1]
        if name != base:
            unselectable.append({
                "name": name, "container_path": cp, "basename": base,
                "problem": "`--pdk` matches the NAME; the image ships the "
                           "directory. They differ, so this PDK is present "
                           "and unselectable.",
            })

    assets_checked = 0
    unresolved = []
    have_image = _container_alive(container)
    if have_image:
        for e in entries:
            cp = e.get("container_path")
            if not cp:
                continue
            for k in _asset_keys(e):
                pat = str(e[k])
                full = (pat if pat.startswith("/")
                        else f"{str(cp).rstrip('/')}/{pat.lstrip('/')}")
                assets_checked += 1
                if not _resolves(container, full):
                    unresolved.append({"name": e.get("name"), "key": k,
                                       "path": full})
    return {"readable": True, "entries": len(entries),
            "unselectable": unselectable,
            "asset_check": "ran" if have_image else "SKIPPED",
            "container": container, "assets_checked": assets_checked,
            "unresolved": unresolved}


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--registry", default=str(here / "pdk_registry.json"))
    ap.add_argument("--container",
                    default=os.environ.get("EDA_CONTAINER", "vibeic-eda"))
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)

    rep = audit(Path(a.registry), a.container)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(rep, indent=2) + "\n")

    if not rep.get("readable"):
        print(f"[SKIP] pdk_registry_selectable_check: registry unreadable — "
              f"{rep.get('reason', '')}")
        return 2

    print(f"pdk_registry_selectable_check: {rep['entries']} registry entr(ies)")
    if rep["asset_check"] == "ran":
        print(f"  asset resolution : {rep['assets_checked']} declared path(s) "
              f"checked in container {rep['container']!r}")
    else:
        print(f"  asset resolution : SKIPPED — container "
              f"{rep['container']!r} not reachable. This half was NOT "
              f"checked; it is not a clean result.")

    bad = rep["unselectable"] + rep["unresolved"]
    for u in rep["unselectable"]:
        print(f"[FAIL] unselectable PDK: name={u['name']!r} but the image "
              f"ships {u['basename']!r} ({u['container_path']}). "
              f"{u['problem']}")
    for u in rep["unresolved"]:
        print(f"[FAIL] {u['name']}.{u['key']} resolves to nothing: {u['path']}")
    if bad:
        print(f"   {len(bad)} finding(s). A PDK present-and-unselectable is "
              f"the #389 incident condition; an unresolvable declared asset "
              f"moves the failure from argument validation to a later, "
              f"harder-to-read death.")
        return 1
    print("[PASS] every registry entry is selectable by its own name"
          + ("; every declared asset resolves." if rep["asset_check"] == "ran"
             else " (asset half not checked)."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
