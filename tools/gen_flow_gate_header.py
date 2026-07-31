#!/usr/bin/env python3
"""Recompute the flow-gate page header from source, and refuse to restamp what
it cannot compute.

WHY THIS EXISTS
===============
`flow-gate.html` calls itself "live state" and carries a header of five figures:

    plugin v1.8.87 · flow steps 63 · cells 504 · suite 912 passed · updated <ts>

Measured 2026-07-31: the plugin was at v1.9.2, the flow yaml held 71 id+name
entries, and the whole programs suite reported 25384 passed. Three of the five
numbers disagreed with the tree, and nothing recomputed them -- the page was
hand-maintained, so "live state" was a claim about the page's intent rather than
about its contents.

WHAT IT COMPUTES, and how
-------------------------
* flow steps -- the flow yaml's id+name entries MINUS the stage containers.
  `71 - 8 stage_* = 63`, which is where the page's own number comes from.
* cells      -- steps x the dimension rows actually present in the page.
* plugin     -- .claude-plugin/plugin.json.
* suite      -- ONLY when `--suite-cmd` is given, and the command is recorded in
  the page beside the number. A test count with no stated selection is not a
  fact about anything; the old `912 passed` could not be reproduced because
  nothing said what it counted.
* updated    -- the run time.

WHAT IT REFUSES
---------------
The eight per-dimension E/W/n distributions are NOT recomputed. They are bespoke
predicates over the flow ("is this gate reached by one of three channels", "can
this step actually fail") and this program does not have them. Guessing at them
would produce a generator that measures something ADJACENT to what the page
claims -- the exact defect this repo spent the day removing.

So they are carried forward untouched, and the header stops implying they were
recomputed: `updated` becomes two dated facts, one for the figures this program
derives and one for the distributions it inherited. A reader can then see which
half is live.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def flow_steps(flow_yaml: Path) -> tuple[int, int, int]:
    """(steps, total_entries, stage_containers)."""
    import yaml
    doc = yaml.safe_load(flow_yaml.read_text(encoding="utf-8"))
    entries: list = []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "name" in o:
                entries.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    stages = [e for e in entries if str(e["id"]).startswith("stage")]
    return len(entries) - len(stages), len(entries), len(stages)


def dimension_rows(page: str) -> int:
    return len(re.findall(r'<td class="dnum">\d+</td>', page))


def run_suite(cmd: str, cwd: Path) -> str:
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                       timeout=14400)
    tail = (r.stdout or "").strip().splitlines()
    for line in reversed(tail):
        if re.search(r"\d+ (passed|failed)", line):
            return re.sub(r"\s*\[.*?\]\s*", " ", line).strip()
    return "suite produced no summary line"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--page", type=Path,
                    default=Path("/home/reyerchu/vibeic.ai/flow-gate.html"))
    ap.add_argument("--plugin-root", type=Path,
                    default=Path("/home/reyerchu/vibe-ic/vibe-ic-marketplace/"
                                 "plugins/vibe-ic"))
    ap.add_argument("--suite-cmd", default=None,
                    help="test selection to run; its NAME is published with the "
                         "number. Omit to carry the previous figure forward "
                         "unchanged rather than restamp it.")
    ap.add_argument("--now", default=None, help="timestamp override, for tests")
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit 1; write nothing")
    args = ap.parse_args(argv)

    page = args.page.read_text(encoding="utf-8")
    steps, total, stages = flow_steps(
        args.plugin_root / "flow" / "phase1_phase2_phase3.yaml")
    dims = dimension_rows(page)
    version = json.loads(
        (args.plugin_root / ".claude-plugin" / "plugin.json")
        .read_text(encoding="utf-8"))["version"]
    now = args.now or datetime.now().strftime("%Y-%m-%d %H:%M")

    cur = {
        "plugin": re.search(r"plugin <b>v([\d.]+)</b>", page),
        "steps": re.search(r"flow steps <b>(\d+)</b>", page),
        "cells": re.search(r"cells <b>(\d+)</b>", page),
    }
    drift = []
    if cur["plugin"] and cur["plugin"].group(1) != version:
        drift.append(f"plugin v{cur['plugin'].group(1)} -> v{version}")
    if cur["steps"] and cur["steps"].group(1) != str(steps):
        drift.append(f"flow steps {cur['steps'].group(1)} -> {steps}")
    if cur["cells"] and cur["cells"].group(1) != str(steps * dims):
        drift.append(f"cells {cur['cells'].group(1)} -> {steps * dims}")

    if args.check:
        for d in drift:
            print(f"  DRIFT  {d}")
        print(f"  derived: {steps} steps ({total} yaml entries - {stages} stages)"
              f" x {dims} dimensions = {steps * dims} cells, plugin v{version}")
        return 1 if drift else 0

    out = page
    out = re.sub(r"plugin <b>v[\d.]+</b>", f"plugin <b>v{version}</b>", out)
    out = re.sub(r"flow steps <b>\d+</b>", f"flow steps <b>{steps}</b>", out)
    out = re.sub(r"cells <b>\d+</b>", f"cells <b>{steps * dims}</b>", out)

    if args.suite_cmd:
        summary = run_suite(args.suite_cmd, args.plugin_root / "programs")
        out = re.sub(r"suite <b>[^<]*</b>",
                     f"suite <b>{summary}</b> <i>({args.suite_cmd})</i>", out)

    # Say exactly which figures this timestamp covers. A single "updated" on a
    # header where half the numbers were recomputed and half were inherited is
    # the page-level version of a gate reporting on something it did not
    # measure.
    carried = ["the per-dimension distributions below"]
    if not args.suite_cmd:
        carried.append("the suite figure")
    out = re.sub(
        r"updated <b>[^<]*</b>",
        f"updated <b>{now}</b> "
        f"<i>(plugin / steps / cells derived from source; "
        f"{' and '.join(carried)} carried forward, not recomputed)</i>",
        out)

    if out == page:
        print("  no change")
        return 0
    args.page.write_text(out, encoding="utf-8")
    for d in drift:
        print(f"  fixed  {d}")
    print(f"  wrote {args.page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
