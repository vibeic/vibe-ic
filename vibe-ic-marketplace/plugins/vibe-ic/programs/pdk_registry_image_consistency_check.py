#!/usr/bin/env python3
"""Report BOTH directions of pdk_registry.json <-> EDA-image drift.

WHY THIS EXISTS
---------------
`ihp-sg13cmos5l` shipped complete inside the EDA image for several releases
with no `pdk_registry.json` entry. Nothing reported that, so `--pdk
ihp-sg13cmos5l` was accepted and a whole cell was driven to a sign-off verdict
against a DIFFERENT PDK's liberty/LEF (vibe-ic#389). vibe-ic#392 made the
runner refuse an explicitly NAMED `--pdk` it cannot resolve, which stops the
wrong-PDK RESULT — but refusing only tells an OPERATOR "no" at the moment they
ask. It never tells the MAINTAINER that a usable PDK is sitting in the image
unregistered, nor that a registered entry has gone stale because the image
moved. That is what this check is for, and it is why it reports BOTH
directions rather than only the one that caused the incident:

  shipped_but_unregistered — the image ships a usable PDK the registry does not
                             declare. Operators cannot select it at all.
  registered_but_absent    — the registry declares a PDK whose assets are not
                             in the image. `--pdk <name>` then dies at asset
                             resolution instead of at argument validation.

WHAT COUNTS AS A SHIPPED PDK
----------------------------
A directory under the PDK root that contains BOTH `libs.ref` and `libs.tech`.
This is STRUCTURAL and name-agnostic on purpose — no allow-list of PDK names,
so a PDK nobody has heard of is still detected. It is also what keeps the check
TIGHT: `/foss/pdks/ciel` is a PDK-manager cache holding per-foundry
subdirectories and has neither `libs.ref` nor `libs.tech`, so it is not a PDK
and is not reported. A looser test (every subdirectory) would fire on it and on
`versions.txt`, and a check that fires on things that are not defects gets
ignored.

Registry entries with NO `container_path` are documented placeholders that
describe auto-detection heuristics rather than a shipped asset tree
(`custom_auto_detect` is the shipped example). They are exempt STRUCTURALLY —
by the absence of the field that would make them checkable — not by name.

The image is resolved through `fault_atpg_run._resolve_docker_image`, the same
pinned-image logic the rest of the plugin uses, so this check MOVES WHEN THE
IMAGE MOVES instead of asserting against a tag frozen in this file.

EXIT CODES
----------
  0  CONSISTENT     — both directions empty.
  1  INCONSISTENT   — at least one finding (details on stdout / in --json).
  2  INDETERMINATE  — the image could not be inspected (no docker, image
                      absent, timeout). NOT a pass: nothing was verified.

chip-AGNOSTIC: no chip, design or vendor token appears in the logic.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROGRAMS_DIR = Path(__file__).resolve().parent
DEFAULT_REGISTRY = PROGRAMS_DIR / "pdk_registry.json"
DEFAULT_PDK_ROOT = "/foss/pdks"

# A directory is a PDK iff it carries BOTH of these. Structural, not nominal.
PDK_MARKER_DIRS = ("libs.ref", "libs.tech")


def _resolve_image(explicit: Optional[str]) -> str:
    """The image to inspect. Single-sourced from the plugin's existing pinned-
    image resolver so this check cannot drift from what the flow actually runs
    (a hand-copied tag here would silently check a different image than the one
    that produced the artefacts)."""
    if explicit:
        return explicit
    env = os.environ.get("VIBEIC_EDA_IMAGE") or os.environ.get("IIC_EDA_IMAGE")
    if env:
        return env
    try:
        sys.path.insert(0, str(PROGRAMS_DIR))
        from fault_atpg_run import _resolve_docker_image  # type: ignore
        return _resolve_docker_image()
    except Exception:
        # Never invent a tag: an unresolvable image must reach the caller as
        # INDETERMINATE, not as a guess that might accidentally exist.
        return ""


def _image_pdk_dirs(image: str, pdk_root: str,
                    timeout: int = 180) -> Tuple[Optional[List[str]], str]:
    """Names of directories under `pdk_root` that carry every PDK_MARKER_DIRS.

    Returns (names, error). `names is None` means the image could not be
    inspected — the caller must report INDETERMINATE, never CONSISTENT."""
    tests = " -a ".join(
        f'-d "$d/{m}"' for m in PDK_MARKER_DIRS)
    script = (
        f'for d in {shlex.quote(pdk_root)}/*/; do '
        f'  if [ {tests} ]; then basename "$d"; fi; '
        f'done'
    )
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "/bin/bash",
             image, "-c", script],
            capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return None, "docker executable not found"
    except subprocess.TimeoutExpired:
        return None, f"docker run timed out after {timeout}s"
    except Exception as e:                                   # pragma: no cover
        return None, f"docker run failed: {e}"
    if r.returncode != 0:
        return None, (f"docker run exited {r.returncode}: "
                      f"{(r.stderr or '').strip()[:400]}")
    return sorted(n for n in r.stdout.split() if n), ""


def _image_path_is_dir(image: str, path: str, timeout: int = 120) -> bool:
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "/bin/bash",
             image, "-c", f'test -d {shlex.quote(path)}'],
            capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def check(registry_path: Path, image: str,
          pdk_root: str = DEFAULT_PDK_ROOT) -> Dict[str, Any]:
    reg = json.loads(Path(registry_path).read_text())
    entries = [e for e in (reg.get("pdks") or []) if e.get("name")]

    declared: Dict[str, str] = {}
    placeholders: List[str] = []
    for e in entries:
        cp = e.get("container_path")
        if cp:
            declared[e["name"]] = cp
        else:
            placeholders.append(e["name"])

    shipped, err = _image_pdk_dirs(image, pdk_root)
    if shipped is None:
        return {"verdict": "INDETERMINATE", "image": image,
                "pdk_root": pdk_root, "error": err,
                "registry": str(registry_path)}

    declared_basenames = {Path(p).name for p in declared.values()}
    shipped_but_unregistered = sorted(
        n for n in shipped if n not in declared_basenames)

    registered_but_absent = sorted(
        name for name, cp in declared.items()
        if not _image_path_is_dir(image, cp))

    verdict = ("CONSISTENT"
               if not shipped_but_unregistered and not registered_but_absent
               else "INCONSISTENT")
    return {
        "verdict": verdict,
        "image": image,
        "pdk_root": pdk_root,
        "registry": str(registry_path),
        "shipped_pdks": shipped,
        "registered_pdks": sorted(declared),
        "placeholder_entries_exempt": sorted(placeholders),
        "shipped_but_unregistered": shipped_but_unregistered,
        "registered_but_absent": registered_but_absent,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Report both directions of pdk_registry.json <-> EDA "
                    "image drift.")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY),
                    help="pdk_registry.json to check "
                         "(default: the one beside this program)")
    ap.add_argument("--image", default=None,
                    help="EDA image to inspect (default: the plugin's "
                         "pinned image)")
    ap.add_argument("--pdk-root", default=DEFAULT_PDK_ROOT,
                    help=f"PDK root inside the image "
                         f"(default: {DEFAULT_PDK_ROOT})")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="also write the report as JSON here")
    args = ap.parse_args(argv)

    image = _resolve_image(args.image)
    if not image:
        print("[INDETERMINATE] pdk_registry_image_consistency_check: could "
              "not resolve an EDA image to inspect. Nothing was verified.")
        return 2

    rep = check(Path(args.registry), image, args.pdk_root)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(rep, indent=2) + "\n")

    if rep["verdict"] == "INDETERMINATE":
        print(f"[INDETERMINATE] pdk_registry_image_consistency_check: "
              f"{rep['error']}. Nothing was verified (image={rep['image']}).")
        return 2

    print(f"image    : {rep['image']}")
    print(f"pdk root : {rep['pdk_root']}")
    print(f"registry : {rep['registry']}")
    print(f"shipped PDKs    ({len(rep['shipped_pdks'])}): "
          f"{', '.join(rep['shipped_pdks']) or '-'}")
    print(f"registered PDKs ({len(rep['registered_pdks'])}): "
          f"{', '.join(rep['registered_pdks']) or '-'}")
    if rep["placeholder_entries_exempt"]:
        print(f"placeholder entries exempt (no container_path): "
              f"{', '.join(rep['placeholder_entries_exempt'])}")

    n_unreg = len(rep["shipped_but_unregistered"])
    n_abs = len(rep["registered_but_absent"])
    for n in rep["shipped_but_unregistered"]:
        print(f"[FINDING] shipped_but_unregistered: {n!r} is a usable PDK in "
              f"{rep['image']} but pdk_registry.json declares no entry for "
              f"it — operators cannot select it, and before the fail-closed "
              f"guard `--pdk {n}` silently resolved to another PDK.")
    for n in rep["registered_but_absent"]:
        print(f"[FINDING] registered_but_absent: pdk_registry.json declares "
              f"{n!r} but its container_path is not present in "
              f"{rep['image']} — `--pdk {n}` will fail at asset resolution.")

    print(f"[{rep['verdict']}] pdk_registry_image_consistency_check: "
          f"{n_unreg} shipped-but-unregistered, "
          f"{n_abs} registered-but-absent.")
    return 0 if rep["verdict"] == "CONSISTENT" else 1


if __name__ == "__main__":
    sys.exit(main())
