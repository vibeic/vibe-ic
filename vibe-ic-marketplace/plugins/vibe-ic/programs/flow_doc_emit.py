#!/usr/bin/env python3
"""flow_doc_emit.py — auto-generate the RUNNER-MARKER view of the Vibe-IC flow.

The flow docs (CANONICAL_FLOW / ALL_STEPS) kept going stale because the step lists were
hand-maintained while the runners moved. This generator makes the *ground-truth* part —
the actual `[N/15]` markers and `def step_*` functions the runners contain — a DERIVED
artefact, the same way `tools/gen_programs_index.py` makes `INDEX.md` derived.

Source of truth = the runner files. This script parses them and emits
`docs/architecture/FLOW_STEPS_GENERATED.md`. The narrative docs (CANONICAL_FLOW_v2.2.0,
ALL_STEPS_v2.3.2) and the curated 33-step / LVS-chain / sign-off tables stay hand-authored
(they are not derivable from markers) and link to this generated file for the live step lists.

Usage:
    python3 flow_doc_emit.py            # write FLOW_STEPS_GENERATED.md
    python3 flow_doc_emit.py --check    # exit 1 if the committed file is stale (CI freshness)
    python3 flow_doc_emit.py --stdout   # print to stdout, write nothing
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

PROGRAMS = Path(__file__).resolve().parent
# programs/ = <repo>/vibe-ic-marketplace/plugins/vibe-ic/programs → repo root = parents[3].
REPO = PROGRAMS.parents[3]
OUT = REPO / "docs" / "architecture" / "FLOW_STEPS_GENERATED.md"

P1 = PROGRAMS / "phase1_doc_one_shot_runner.py"
P2 = PROGRAMS / "phase2_one_shot_runner.py"
P3 = PROGRAMS / "phase3_one_shot_runner.py"
PA = PROGRAMS / "analog_one_shot_runner.py"


def _read(p: Path) -> str:
    return p.read_text(errors="replace") if p.is_file() else ""


def phase1_markers(src: str) -> List[Tuple[str, str]]:
    """[(marker, description)] from the runner's step markers, first occurrence, in order.

    Two equivalent marker forms are recognised (ORGANIC-20260522 routed the
    L1-L13 generators through the `_run_layer` watchdog wrapper, which prints
    the same `[N/15] LAYER ...` line at runtime but in source appears as a
    `_run_layer("[N/15]", "LAYER", ...)` call rather than a bare print):
      * `print(f"[N/15] desc ...")`            — e.g. [1/15] ingest, [15/15] coverage
      * `_run_layer("[N/15]", "LAYER", ...)`   — the L1-L13 + L8_TIMING emit steps
    Only matches code (not comments), so a `# ... [14b/15] ...` comment is ignored.
    """
    out: List[Tuple[str, str]] = []
    seen = set()
    pat = re.compile(
        r'print\(\s*f?"(\s*\[[0-9]+[a-z0-9]*/15\])\s*([^"]*?)"'
        r'|_run_layer\(\s*"(\[[0-9]+[a-z0-9]*/15\])"\s*,\s*"([^"]*)"',
        re.IGNORECASE)
    for m in pat.finditer(src):
        if m.group(1) is not None:
            marker = m.group(1).strip()
            desc = m.group(2).strip()
        else:
            marker = m.group(3).strip()
            desc = m.group(4).strip()
        # strip trailing " ..." progress dots
        desc = re.sub(r"\s*\.\.\.\s*$", "", desc).strip()
        if marker in seen:
            continue
        seen.add(marker)
        out.append((marker, desc))
    return out


def step_functions(src: str) -> List[str]:
    """Ordered, de-duplicated `def step_*` names (source order = definition order)."""
    out: List[str] = []
    seen = set()
    for m in re.finditer(r"^def (step_[a-z0-9_]+)\s*\(", src, re.MULTILINE):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def analog_steps(src: str) -> List[Tuple[str, str, str]]:
    """[(Ax, name, output)] from the header block `  A1 spec_extract  -> analog/...`."""
    out: List[Tuple[str, str, str]] = []
    seen = set()
    pat = re.compile(r"^\s*(A[1-9])\s+(\w+)\s+→\s+(.*)$", re.MULTILINE)
    for m in pat.finditer(src):
        ax = m.group(1)
        if ax in seen:
            continue
        seen.add(ax)
        out.append((ax, m.group(2), m.group(3).strip()))
    return out


def _table(headers: List[str], rows: List[List[str]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return f"{line}\n{sep}\n{body}"


def render() -> str:
    p1 = phase1_markers(_read(P1))
    p2 = step_functions(_read(P2))
    p3 = step_functions(_read(P3))
    pa = analog_steps(_read(PA))

    # CONTINUOUS GLOBAL NUMBERING across the sequential flow (Phase 1 → 2 → 3) — no per-phase
    # restart (Phase 3 does NOT start at 1). Analog A1-A8 / Mixed M1-M4 run PARALLEL to Phase 2,
    # so they keep their native A*/M* ids rather than joining the linear count.
    g = 0  # running global step index

    def _numbered(rows):
        nonlocal g
        out = []
        for r in rows:
            g += 1
            out.append([str(g)] + r)
        return out

    p1_end = len(p1)
    p2_end = p1_end + len(p2)
    p3_end = p2_end + len(p3)

    parts: List[str] = []
    parts.append("# Vibe-IC Flow — runner-marker view (AUTO-GENERATED)\n")
    parts.append(
        "> **AUTO-GENERATED by `programs/flow_doc_emit.py` — do not hand-edit.** Ground-truth step\n"
        "> list parsed directly from the runners. **One CONTINUOUS global step number** across the\n"
        "> sequential flow Phase 1 → 2 → 3 (Phase 3 does NOT restart at 1). Analog A1-A8 / Mixed\n"
        "> M1-M4 run PARALLEL to Phase 2 and keep their native A*/M* ids. The narrative docs\n"
        "> (`CANONICAL_FLOW_v2.2.0.md`, `ALL_STEPS_v2.3.2.md`) link here. Regenerate:\n"
        "> `python3 flow_doc_emit.py`.\n"
    )

    parts.append(f"\n## Phase 1 — `phase1_doc_one_shot_runner.py` (global steps 1-{p1_end})\n")
    parts.append(_table(["#", "Marker", "Step"],
                         _numbered([[mk, ds or "—"] for mk, ds in p1])))

    parts.append(f"\n## Phase 2 — `phase2_one_shot_runner.py` (global steps {p1_end + 1}-{p2_end})\n")
    parts.append(_table(["#", "Step function"], _numbered([[f"`{s}`"] for s in p2])))

    parts.append(f"\n## Phase 3 — `phase3_one_shot_runner.py` (global steps {p2_end + 1}-{p3_end})\n")
    parts.append(_table(["#", "Step function"], _numbered([[f"`{s}`"] for s in p3])))

    parts.append(f"\n## Analog — `analog_one_shot_runner.py` ({len(pa)} steps, PARALLEL to Phase 2)\n")
    parts.append(_table(["Step", "Name", "Output"],
                        [[ax, f"`{nm}`", out] for ax, nm, out in pa]))

    parts.append(
        f"\n## Totals\n\nSequential global steps: {p3_end} "
        f"(Phase 1: 1-{p1_end} · Phase 2: {p1_end + 1}-{p2_end} · Phase 3: {p2_end + 1}-{p3_end}) "
        f"· Analog (parallel): {len(pa)}\n"
    )
    return "\n".join(parts) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed FLOW_STEPS_GENERATED.md is stale")
    ap.add_argument("--stdout", action="store_true", help="print, write nothing")
    args = ap.parse_args(argv)

    content = render()
    if args.stdout:
        sys.stdout.write(content)
        return 0
    if args.check:
        existing = OUT.read_text(errors="replace") if OUT.is_file() else ""
        if existing != content:
            print(f"STALE: {OUT} differs from generator output — run "
                  f"`python3 flow_doc_emit.py`.", file=sys.stderr)
            return 1
        print(f"FRESH: {OUT.name} matches the runner markers.")
        return 0
    OUT.write_text(content)
    print(f"wrote {OUT} "
          f"(P1={content.count('/15]')} markers shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
