#!/usr/bin/env python3
"""
rig_topology_image_extracted_check.py — gate (LL-35).

When the project's `input/docs/` (or `input/`) ships an image whose
filename suggests it is the FPGA pin-planner / board diagram /
topology snapshot, the bringup-plan skill MUST run a vision pass and
emit `<project>/rig_topology.json` so downstream RTL+QSF can be
cross-checked against the planner.

Why this gate exists
====================
v0.119.32 <benchmark> vendor benchmark — the only physical evidence of
the FPGA pin map (PIN_V10 for ID_BUS, PIN_B8 for RESET_N, etc.) was
in `A3606_pin_planner.jpg`. The text-only extractor cannot read
images, so the fresh agent had no source of truth for the pin map
and emitted a placeholder QSF that physically can't match what the
host-tester is wired to. The connect_test FAILed on a wrong-pin
floor, not on a CRC mismatch.

Rule
----
Trigger: `<project>/input/docs/` or `<project>/input/` contains ≥1
image file whose filename matches one of (case-insensitive):
    *pin*.{jpg,jpeg,png,bmp}
    *planner*.{jpg,jpeg,png,bmp}
    *board*.{jpg,jpeg,png,bmp}
    *topology*.{jpg,jpeg,png,bmp}

When triggered, `rig_topology.json` MUST exist (in
`<project>/`, `<project>/generated_docs/`, or `<project>/bringup/`)
and validate against the canonical schema:

    {
      "fpga_board":  "<board model>",
      "host_tester": "<host tester>",
      "extracted_from": "<source image filename>",
      "wiring": [
        {"chip_signal": "...", "fpga_pin": "...",
         "direction": "Input|Output|Bidir"},
        ...
      ]
    }

Honors waiver `rig_topology_image_inaccessible` (≥40 chars) — for
hand-drawn whiteboard photos / OCR-resistant images.

Silent-skips when no candidate images exist.

Usage
-----
    python3 rig_topology_image_extracted_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
NAME_HINTS = (
    re.compile(r"pin", re.IGNORECASE),
    re.compile(r"planner", re.IGNORECASE),
    re.compile(r"board", re.IGNORECASE),
    re.compile(r"topology", re.IGNORECASE),
)
REQUIRED_TOP_KEYS = ("fpga_board", "host_tester", "extracted_from",
                     "wiring")
REQUIRED_WIRING_KEYS = ("chip_signal", "fpga_pin", "direction")


def _candidate_images(project: Path) -> list[Path]:
    out: list[Path] = []
    bases = [project / "input" / "docs", project / "input"]
    seen: set[Path] = set()
    for base in bases:
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in IMAGE_EXTS:
                continue
            if any(pat.search(p.name) for pat in NAME_HINTS):
                if p not in seen:
                    out.append(p)
                    seen.add(p)
    return out


def _load_rig_topology(project: Path) -> tuple[Path | None, dict | None]:
    for base in (project, _pl.generated_docs_dir(project),
                 project / "bringup", project / "docs"):
        p = base / "rig_topology.json"
        if p.is_file():
            try:
                return p, json.loads(p.read_text(errors="replace"))
            except Exception:
                return p, None
    return None, None


def _validate_schema(d: dict) -> list[str]:
    """Returns a list of schema problems (empty == valid)."""
    problems: list[str] = []
    if not isinstance(d, dict):
        return ["top-level must be a JSON object"]
    for k in REQUIRED_TOP_KEYS:
        if k not in d:
            problems.append(f"missing top-level key '{k}'")
    wiring = d.get("wiring")
    if wiring is not None:
        if not isinstance(wiring, list):
            problems.append("`wiring` must be a list")
        elif not wiring:
            problems.append("`wiring` is empty")
        else:
            for i, entry in enumerate(wiring):
                if not isinstance(entry, dict):
                    problems.append(
                        f"wiring[{i}] must be an object")
                    continue
                for k in REQUIRED_WIRING_KEYS:
                    if k not in entry:
                        problems.append(
                            f"wiring[{i}] missing '{k}'")
    return problems


def _waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
    except Exception:
        return False
    v = d.get("rig_topology_image_inaccessible", "")
    return isinstance(v, str) and len(v.strip()) >= 40


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: rig_topology_image_extracted_check.py "
              "<project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    images = _candidate_images(project)
    if not images:
        print("PASS — no rig-topology candidate image in "
              "input/docs (gate skipped)")
        return 0

    rt_path, rt = _load_rig_topology(project)
    if rt_path is None:
        if _waived(project):
            print(f"PASS_WITH_WAIVER — pin-planner image "
                  f"{images[0].name!r} present but rig_topology.json "
                  f"absent (waived)")
            return 0
        print(f"FAIL — pin-planner-style image found in input "
              f"({[i.name for i in images[:3]]}) but "
              f"rig_topology.json is missing.")
        print()
        print("Fix: run the bringup-plan skill's vision step. Open "
              "the image with your vision capability, read the "
              "pin-assignment table, and emit "
              "<project>/rig_topology.json with keys "
              "{fpga_board, host_tester, extracted_from, wiring[]}.")
        return 1

    if rt is None:
        if _waived(project):
            print(f"PASS_WITH_WAIVER — rig_topology.json at "
                  f"{rt_path} is invalid JSON (waived)")
            return 0
        print(f"FAIL — rig_topology.json at {rt_path} is invalid "
              f"JSON.")
        return 1

    problems = _validate_schema(rt)
    if problems:
        if _waived(project):
            print(f"PASS_WITH_WAIVER — rig_topology.json schema "
                  f"problems waived: {problems}")
            return 0
        print(f"FAIL — rig_topology.json at {rt_path} schema "
              f"problems:")
        for p in problems[:8]:
            print(f"    - {p}")
        return 1

    print(f"PASS — rig_topology.json at {rt_path.name} valid "
          f"(extracted from {rt.get('extracted_from')!r}, "
          f"{len(rt.get('wiring') or [])} wiring entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
