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

The header was made honest first; the PROSE was not, and the prose is what a
reader believes. Four places on the page assert liveness in words:

    <meta name="description">   "…即時狀態：504 格，每一格都是對當前原始碼重新計算的謂詞。"
    <meta property="og:...">    the same sentence again
    <p class="sub">             "每一格都是對當前原始碼重新計算的謂詞,
                                 不是把判定存起來再讀回來。"
    <div class="eyebrow">       "Flow Gate · live state"

The third is the load-bearing one: it names the exact thing that is not true —
the distributions ARE stored and read back, and this program is what stores them.
A page can carry an honest two-part timestamp and still be believed wrong,
because nobody reads a timestamp to decide what a sentence means.

So the same pass that recomputes the figures also rewrites those four claims to
say which half is live. `--check` reports a stale claim as DRIFT, exactly like a
stale version number: both are the page asserting something about a tree it no
longer matches.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from typing import List, Tuple
from pathlib import Path

# `_progress_run` lives in the plugin's `programs/`, which is not a sibling of
# this file. Walk UP until the directory that actually holds it is found, so
# this works from `tools/`, from `tools/<sub>/`, and from inside the flattened
# plugin cache where the marketplace path does not exist.
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402


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


#: A page has spelled its dimension table two ways, and BOTH are it.
#:
#:  * the LEGACY shape, `<td class="dnum">n</td>` -- one such cell per row;
#:  * the CURRENT shape, a label cell reading `D1`..`D9`, after the 2026-08-26
#:    rewrite renamed the class to `num`.
#:
#: MEASURED 2026-08-28: keying on the legacy CLASS alone counted 0 dimensions
#: on the rewritten page and a plain run rewrote a real `cells 612` down to
#: `cells 0`. Replacing it with the label alone counted 0 on the legacy shape --
#: the same defect, one spelling over, and this repo's own liveness test caught
#: it. So both are read, and the larger is taken: a page tabulates ONE set of
#: dimensions, and whichever marker survives its markup is evidence of the same
#: table. A spelling this program has never seen still lands on the refusal
#: below rather than on a silent zero.
_DIM_LABEL_RE = re.compile(r">\s*D([1-9])\s*<")
_DIM_LEGACY_RE = re.compile(r'<td class="dnum">\d+</td>')


def dimension_rows(page: str) -> int:
    """How many dimensions the page tabulates, over either spelling.

    The label count is DISTINCT: a bilingual page writes each label twice (the
    `data-en` copy and the rendered text), and counting occurrences would
    multiply the cell figure by whatever the markup happened to repeat. The
    legacy count is per-cell, which is what that shape meant.
    """
    return max(len(set(_DIM_LABEL_RE.findall(page))),
               len(_DIM_LEGACY_RE.findall(page)))


def _version_at(plugin_root: "Path", commit: str):
    """The plugin version recorded AT `commit`, or None if it cannot be read.

    None is returned for every failure -- not a working-tree fallback. A
    fallback here would silently answer a question about one commit with a fact
    about another, which is the defect this helper exists to prevent.
    """
    rel = "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"
    try:
        out = _pr.run(["git", "show", f"{commit}:{rel}"],
                      cwd=str(plugin_root), capture_output=True, text=True)
    except Exception:
        # Any failure to ASK is the same answer: this program does not know the
        # version at that commit, and must not substitute one it does know.
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)["version"]
    except (ValueError, KeyError):
        return None


def run_suite(cmd: str, cwd: Path) -> str:
    r = _pr.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()
    for line in reversed(tail):
        if re.search(r"\d+ (passed|failed)", line):
            return re.sub(r"\s*\[.*?\]\s*", " ", line).strip()
    return "suite produced no summary line"


# The words a reader believes, and what each must say instead.
# Keyed on the FALSE half so a page already corrected is left alone and the
# substitution stays idempotent.
_LIVENESS_CLAIMS = (
    ("每一格都是對當前原始碼<b>重新計算</b>的謂詞，不是把判定存起來再讀回來。",
     "表頭的數字（步驟數、格數、plugin 版本）每次產生都對當前原始碼重新計算；"
     "下方八個維度的 E/W/n 分佈<b>不是</b>——它們是一次人工評估的結果，"
     "由這支程式原封搬運，日期標在表頭。"),
    ("即時狀態：504 格，每一格都是對當前原始碼重新計算的謂詞。",
     "表頭數字為現算；八個維度的分佈為指定日期的人工評估，非現算。"),
    ("每一格都是對當前原始碼重新計算的謂詞。",
     "表頭數字為現算；八個維度的分佈為指定日期的人工評估，非現算。"),
    ("Flow Gate · live state",
     "Flow Gate · header live, distributions inherited"),
)


def rewrite_liveness_claims(page: str) -> Tuple[str, List[str]]:
    """Make the page's words agree with what this program actually recomputes.

    Returns the page and the claims that were still asserting liveness. An empty
    list means the page already says which half is live -- so running twice
    changes nothing, and `--check` on a corrected page is silent.
    """
    stale: List[str] = []
    for false_claim, honest in _LIVENESS_CLAIMS:
        if false_claim in page:
            stale.append(false_claim[:44])
            page = page.replace(false_claim, honest)
    return page, stale


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Both defaults were absolute personal-home paths, which the
    # shipped-path portability gate rejects — correctly. A hard-coded home is
    # not a default, it is one machine's layout: on any other checkout the tool
    # silently writes to, or reads from, somewhere that does not exist.
    #
    # `--plugin-root` is DERIVED from this file's own location, so it is right
    # by construction wherever the repo is cloned. `--page` has no such anchor
    # (the site tree is a sibling of the repo, not inside it), so it comes from
    # an env var and is otherwise REQUIRED rather than guessed: a default that
    # points at a path this machine happens to have would fail on someone
    # else's checkout by writing the wrong file, which is worse than asking.
    _repo_root = Path(__file__).resolve().parents[1]
    _page_env = os.environ.get("VIBEIC_FLOW_GATE_PAGE")
    ap.add_argument("--page", type=Path,
                    default=Path(_page_env) if _page_env else None,
                    required=not _page_env,
                    help="output HTML page (or set VIBEIC_FLOW_GATE_PAGE)")
    ap.add_argument("--plugin-root", type=Path,
                    default=_repo_root / "vibe-ic-marketplace"
                                       / "plugins" / "vibe-ic")
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

    # A VERSION BESIDE A PINNED COMMIT IS THAT COMMIT'S VERSION, not today's.
    # MEASURED 2026-08-28: the page states `plugin v1.12.33 - source 10b9e12c3`
    # because its figures were measured on that commit. The working tree had
    # moved to v1.12.34, so this program reported drift and a plain run would
    # have written `plugin v1.12.34 - source 10b9e12c3` -- a version and a
    # commit that contradict each other, on the page whose own rule is that
    # published digits are derived. Restamping half of a pin breaks the pin.
    pinned = re.search(r"source <b>([0-9a-f]{7,40})</b>", page)
    if pinned:
        at = _version_at(args.plugin_root, pinned.group(1))
        if at is None:
            print(f"CANNOT CHECK: the page pins source {pinned.group(1)}, and "
                  f"the plugin version at that commit could not be read. "
                  f"Restamping the version beside a pin this program cannot "
                  f"resolve would publish a contradiction. NOT a pass, and "
                  f"nothing was written.", file=sys.stderr)
            return 2
        version = at
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

    _, stale_claims = rewrite_liveness_claims(page)
    for c in stale_claims:
        drift.append(f"the page still claims liveness in words: \u201c{c}\u2026\u201d")

    # A COUNT OF ZERO IS NOT A MEASUREMENT. If no dimension row was found, this
    # program did not measure the page -- it failed to READ it, and the two look
    # identical from the outside. MEASURED 2026-08-28, on the tree as it stood:
    # with the old cosmetic matcher against the rewritten page, `--check` printed
    # "0 cells" as a derived figure and a plain run REWROTE a real `cells 612`
    # down to `cells 0`. The page's whole subject is that it has 612 cells.
    #
    # So zero is refused at rc 2 CANNOT CHECK, in BOTH modes, before any drift
    # is reported or anything is written. Refusing is the only outcome that
    # cannot be mistaken for a verdict about the page.
    if dims == 0 and cur["cells"]:
        print(f"CANNOT CHECK: {args.page} states a cells figure "
              f"({cur['cells'].group(1)}) but no dimension row could be read "
              f"from it, so the derived count would be {steps} x 0 = 0. That is "
              f"this program failing to read the page, not a measurement of it. "
              f"NOT a pass, and nothing was written.", file=sys.stderr)
        return 2

    if args.check:
        for d in drift:
            print(f"  DRIFT  {d}")
        print(f"  derived: {steps} steps ({total} yaml entries - {stages} stages)"
              f" x {dims} dimensions = {steps * dims} cells, plugin v{version}")
        return 1 if drift else 0

    out, _ = rewrite_liveness_claims(page)
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
        # Consume any parenthetical a PREVIOUS run appended, not just the
        # timestamp. Without this the note accumulates: measured, three runs
        # leave three copies of it on one line. It went unnoticed because this
        # program runs rarely and the duplication sits at the end of a long
        # line — a substitution that is not idempotent is a substitution that
        # only looks right the first time.
        r"updated <b>[^<]*</b>(?:\s*<i>\([^<]*\)</i>)*",
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
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
