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

3. IT ENUMERATED ONE LEVEL DEEP, so a PDK shipped only nested was invisible
   to the shipped-but-unregistered direction. This gate enumerates to depth
   and folds symlinks through `readlink -f`, because the image's REAL
   `sky130A` / `gf180mcuD` live under `ciel/.../` and comparing unresolved
   paths would report both as unregistered — two false findings on a correct
   image.

MEASURED ON MAIN TODAY: 6 entries, 5 carry a `container_path` and all 5
satisfy `name == basename`; 33 declared asset paths, 0 unresolvable. But the
third direction found a LIVE instance of the #389 condition:
`/foss/pdks/ihp-sg13cmos5l` ships in `vibeic-eda:0.2.30` with `libs.ref` +
`libs.tech`, is absent from the registry, and `--pdk ihp-sg13cmos5l` is
REFUSED — a tree present in the image that no operator can select. It is
recorded in a SHRINK-ONLY baseline rather than failing main, because failing
a pre-existing gap on day one makes a gate people route around; anything NEW
fails. (I did NOT measure whether it would complete a PnR run — "shipped and
unselectable" is what was measured, not "fully usable".)

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

_BASELINE_NAME = "pdk_shipped_unregistered_baseline.json"
_ASSET_SUFFIXES = ("_glob", "_deck")
_ASSET_KEYS_EXTRA = ("lefdef_layermap", "pnr_exclude_cell_file")


def _asset_keys(entry: Dict[str, Any]) -> List[str]:
    return [k for k, v in entry.items()
            if isinstance(v, str) and v
            and (k.endswith(_ASSET_SUFFIXES) or k in _ASSET_KEYS_EXTRA)]


_GHCR_REPO = "ghcr.io/vibeic/vibeic-eda"


def _image_tag() -> str:
    """The image the repo currently pins, or an env override."""
    ov = os.environ.get("VIBEIC_EDA_IMAGE")
    if ov:
        return ov
    for up in Path(__file__).resolve().parents:
        v = up / "tools" / "vibeic-eda" / "VERSION"
        if v.is_file():
            return f"{_GHCR_REPO}:{v.read_text().strip()}"
    return f"{_GHCR_REPO}:latest"


def _resolve_target(container: str):
    """('exec', name) | ('run', image) | None — how to reach the PDK tree.

    #408 finding 1 is that the asset half never actually ran. It required a
    LIVE container named `vibeic-eda`; this host runs `vpp_eda_030` and CI
    runs none at all, so the half of the gate that resolves declared assets
    reported SKIPPED everywhere and the check people relied on was the name
    half alone. An IMAGE is enough to answer the question — `docker run --rm`
    on the pinned tag reads the same /foss/pdks — so a missing container is no
    longer a reason not to look.
    """
    if container and subprocess.run(
            ["docker", "exec", container, "true"],
            capture_output=True, text=True).returncode == 0:
        return ("exec", container)
    img = _image_tag()
    if subprocess.run(["docker", "image", "inspect", img],
                      capture_output=True, text=True).returncode == 0:
        return ("run", img)
    return None


def _sh(target, script: str):
    """Run `script` in the container or the image; returns CompletedProcess."""
    if target is None:
        return subprocess.CompletedProcess([], 1, "", "no target")
    kind, ref = target
    cmd = (["docker", "exec", ref, "bash", "-lc", script] if kind == "exec"
           else ["docker", "run", "--rm", "--entrypoint", "bash", ref,
                 "-lc", script])
    return subprocess.run(cmd, capture_output=True, text=True)


def _container_alive(name: str) -> bool:
    """True when the PDK tree is reachable AT ALL — live container OR image."""
    return _resolve_target(name) is not None


def _resolves(container: str, path: str) -> bool:
    r = _sh(_resolve_target(container),
            f"ls -d {path} >/dev/null 2>&1 && echo OK || echo MISS")
    tail = (r.stdout or "").strip().splitlines()
    return bool(tail) and tail[-1] == "OK"


# Depth-limited enumeration of PDK-like trees. #408 finding 3: a one-level
# scan cannot see a PDK shipped only nested. This image has two — the real
# `ciel/.../sky130A` and `ciel/.../gf180mcuD` trees — but they are the TARGETS
# of the top-level symlinks, so reporting them would be two false findings on
# a correct image. Resolution: enumerate deep, then fold every path through
# `readlink -f` and compare RESOLVED paths, so a symlink and its target count
# once.
_ENUM_DEPTH = 6


def shipped_trees(container: str):
    """{resolved_path: basename} for every dir carrying libs.ref + libs.tech."""
    script = (
        f"find /foss/pdks -maxdepth {_ENUM_DEPTH} -type d -name libs.ref "
        f"2>/dev/null | while read d; do p=$(dirname \"$d\"); "
        f"[ -d \"$p/libs.tech\" ] && readlink -f \"$p\"; done | sort -u")
    r = _sh(_resolve_target(container), script)
    if r.returncode != 0:
        return {}
    out = {}
    for line in r.stdout.splitlines():
        s = line.strip()
        if s.startswith("/") and "libs.ref" not in s:
            out[s] = s.rsplit("/", 1)[-1]
    return out


def _resolved(container: str, path: str):
    r = _sh(_resolve_target(container), f"readlink -f {path} 2>/dev/null")
    for line in reversed(r.stdout.splitlines()):
        s = line.strip()
        if s.startswith("/"):
            return s
    return None

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

    # A THIRD name-half invariant: `tapcell_master` must be EXPLICIT.
    #
    # The resolver reads it with `reg.get("tapcell_master")`, so an OMITTED key
    # and an explicit `null` arrive identically as None — and None is a load-
    # bearing value: it means "this PDK ships no tapcell master", which routes
    # the PERC latch-up gate down the tapless-cell path. That path is correct
    # for a genuinely tapless PDK (ihp-sg13g2, ties inside every std cell) and
    # WRONG for a tapcell-methodology PDK, where it downgrades a skipped tapcell
    # step from a conclusive FAIL to a non-blocking INCOMPLETE — a real latch-up
    # exposure reported as an indeterminate (#586).
    #
    # Found live on `asap7`, whose branch built its PdkConfig without the field
    # while the image ships `MACRO TAPCELL_ASAP7_75t_R`. Requiring the key makes
    # "tapless" something an entry has to SAY, never something it can forget.
    #
    # `custom_auto_detect` declares no container_path — it is a sentinel, not a
    # PDK, and is exempt for the same reason the name check skips it.
    implicit_tapless = []
    for e in entries:
        name, cp = e.get("name"), e.get("container_path")
        if not name or not cp:
            continue
        if "tapcell_master" not in e:
            implicit_tapless.append({
                "name": name,
                "problem": "no `tapcell_master` key. The resolver cannot tell "
                           "that from an explicit null, which means the PDK "
                           "ships no tapcell master and sends the latch-up "
                           "gate down the tapless-cell path. State it: the "
                           "master's cell name, or null if genuinely tapless.",
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
    # #408 finding 3 — the other direction: a PDK the IMAGE ships that the
    # registry does not carry. `--pdk <it>` is then refused (correctly, by
    # #389's guard), so a usable tree sits there that no operator can select
    # and nothing says so.
    shipped_unregistered = []
    if have_image:
        registered_resolved = set()
        for e in entries:
            cp = e.get("container_path")
            if cp:
                rp = _resolved(container, str(cp))
                if rp:
                    registered_resolved.add(rp)
        for rp, base in sorted(shipped_trees(container).items()):
            if rp not in registered_resolved:
                shipped_unregistered.append({"path": rp, "basename": base})
    return {"readable": True, "entries": len(entries),
            "unselectable": unselectable,
            "implicit_tapless": implicit_tapless,
            "asset_check": "ran" if have_image else "SKIPPED",
            "container": container, "assets_checked": assets_checked,
            "unresolved": unresolved,
            "shipped_unregistered": shipped_unregistered}


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--registry", default=str(here / "pdk_registry.json"))
    ap.add_argument("--container",
                    default=os.environ.get("EDA_CONTAINER", "vibeic-eda"))
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true")
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

    # Shipped-but-unregistered is reported against a SHRINK-ONLY register:
    # `ihp-sg13cmos5l` predates this gate, and failing main on a pre-existing
    # gap makes a gate people route around. Anything NEW fails.
    known = set()
    bl = Path(a.baseline) if a.baseline else here / _BASELINE_NAME
    if bl.is_file():
        try:
            known = set(json.loads(bl.read_text()).get("known") or [])
        except (OSError, ValueError):
            known = set()
    su_new = [u for u in rep.get("shipped_unregistered", [])
              if u["basename"] not in known]
    # A recorded gap may only be declared PAID when the image was actually
    # enumerated. Without a reachable container the shipped set is EMPTY, and
    # subtracting it would report every recorded entry as resolved — "I could
    # not look" read as "it is fixed", the same error as the asset half, in
    # the shrink direction. Caught by the shared gate script failing on a
    # docker-less host.
    su_paid = (sorted(known - {u["basename"]
                               for u in rep.get("shipped_unregistered", [])})
               if rep["asset_check"] == "ran" else [])
    if a.write_baseline:
        now = sorted(u["basename"] for u in rep.get("shipped_unregistered", []))
        if known and len(now) > len(known):
            print(f"[FAIL] refusing to GROW the baseline "
                  f"({len(known)} -> {len(now)}): a PDK becoming unselectable "
                  f"is a regression, not a fact to record.")
            return 1
        bl.write_text(json.dumps(
            {"_comment": ("PDKs the image SHIPS that pdk_registry.json does "
                          "not carry, so `--pdk <name>` refuses them "
                          "(vibe-ic#408/#389). MAY ONLY SHRINK — each entry "
                          "is a usable tree no operator can select. Register "
                          "it, or remove it from the image."),
             "known": now}, indent=2) + "\n")
        print(f"wrote {bl} ({len(now)} entr(ies))")
        return 0

    for u in rep.get("shipped_unregistered", []):
        mark = "NEW " if u["basename"] not in known else "recorded"
        print(f"  shipped-but-unregistered [{mark}]: {u['path']} — "
              f"`--pdk {u['basename']}` is refused, so this tree is present "
              f"and unselectable")
    for b in su_paid:
        print(f"[FAIL] {b} is no longer shipped-but-unregistered — shrink the "
              f"baseline so it cannot become standing permission.")

    bad = (rep["unselectable"] + rep["unresolved"] + su_new
           + rep.get("implicit_tapless", []) + [{"paid": b} for b in su_paid])
    for u in rep.get("implicit_tapless", []):
        print(f"[FAIL] {u['name']}: {u['problem']}")
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
    print("[PASS] every registry entry is selectable by its own name and "
          "states its tapcell_master explicitly"
          + ("; every declared asset resolves." if rep["asset_check"] == "ran"
             else " (asset half not checked)."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
