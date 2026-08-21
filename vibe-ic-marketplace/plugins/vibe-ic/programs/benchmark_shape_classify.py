#!/usr/bin/env python3
"""benchmark_shape_classify.py — classify a benchmark's run-shape
(A/B/C/D/E) from its on-disk layout.

Extracted from open-benchmark-methodology § 2 decision matrix. The
existing `benchmark_dispatch.py` *dispatches* on a shape already
recorded in BENCHMARK_REGISTRY.json; this program *derives* the
shape for a NEW benchmark that isn't in the registry yet, by
checking the § 2 predicates against the files on disk:

  1. Full IC (multiple HDL modules + a PDK/constraints target)?  → A
  2. Substantial standalone single-module + its own testbench?    → B
  3. Atomic micro-problem (≤30-line prompt, ≥100 of them)?        → C
  4. Agentic SoC + cocotb harness?                                → D
  5. Oracle gated / removed / non-functional metric?              → E

Each predicate is checkable from the layout:
  * module count   — count `module <name>` declarations across *.v/*.sv
  * PDK target     — presence of sky130/gf180/OpenLane config / .sdc/.tcl
  * prompt size    — max line count of prompt/spec files
  * dataset cardinality — count of sibling problem dirs / prompt files
  * cocotb harness — a *.py with `import cocotb` / `@cocotb.test`
  * gated oracle   — a marker file or --oracle-gated flag

Usage
=====
  python3 benchmark_shape_classify.py <benchmark_dir> [--problem-count N] \
      [--oracle-gated] [--json out.json]

  --problem-count   override the dataset cardinality (else auto-counted)
  --oracle-gated    force the E predicate (golden removed / access-gated)

Honest failure
==============
  * <benchmark_dir> not a directory → rc 2 (usage error).
  * A directory with NO HDL, NO prompt, NO harness → classified E
    ("no scorable content found") rather than a vacuous A/B/C — an
    empty/garbage dir does not earn a runnable shape.

Exit codes
==========
  0 — classified into A/B/C/D (a runnable shape)
  1 — classified E (blocked / out-of-scope / no scorable content)
  2 — usage error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_MODULE_RE = re.compile(r"^\s*module\s+[A-Za-z_]\w*", re.MULTILINE)
_PDK_TOKENS = ("sky130", "gf180", "openlane", "config.json", "config.tcl")
_PDK_SUFFIX = (".sdc", ".tcl", ".lef", ".def")
_COCOTB_RE = re.compile(r"import\s+cocotb|@cocotb\.test|from\s+cocotb")
_PROMPT_GLOBS = ("*prompt*.txt", "*prompt*.md", "*_prompt*", "*spec*.md",
                 "design_description.txt", "PROMPT.txt", "specification.md")


def _count_modules(d: Path) -> int:
    total = 0
    for ext in ("*.v", "*.sv"):
        for f in d.rglob(ext):
            try:
                total += len(_MODULE_RE.findall(f.read_text(encoding="utf-8",
                                                            errors="replace")))
            except OSError:
                continue
    return total


def _has_pdk_target(d: Path) -> bool:
    for f in d.rglob("*"):
        if not f.is_file():
            continue
        low = f.name.lower()
        if any(t in low for t in _PDK_TOKENS) or low.endswith(_PDK_SUFFIX):
            return True
    return False


def _has_cocotb(d: Path) -> bool:
    for f in d.rglob("*.py"):
        try:
            if _COCOTB_RE.search(f.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def _prompt_files(d: Path) -> list[Path]:
    found: set[Path] = set()
    for g in _PROMPT_GLOBS:
        found.update(d.rglob(g))
    return [p for p in found if p.is_file()]


def _max_prompt_lines(prompts: list[Path]) -> int:
    mx = 0
    for p in prompts:
        try:
            n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
        mx = max(mx, n)
    return mx


def classify(d: Path, problem_count: int | None, oracle_gated: bool) -> dict:
    n_modules = _count_modules(d)
    has_pdk = _has_pdk_target(d)
    has_cocotb = _has_cocotb(d)
    prompts = _prompt_files(d)
    n_prompts = problem_count if problem_count is not None else len(prompts)
    max_lines = _max_prompt_lines(prompts)
    has_hdl = n_modules > 0

    facts = {
        "module_count": n_modules,
        "has_pdk_target": has_pdk,
        "has_cocotb_harness": has_cocotb,
        "prompt_file_count": len(prompts),
        "problem_count": n_prompts,
        "max_prompt_lines": max_lines,
        "oracle_gated": oracle_gated,
    }

    # § 2 decision tree, in order.
    if oracle_gated:
        return {"shape": "E", "reason": "oracle_gated_or_removed", "facts": facts}
    if not has_hdl and not has_cocotb and not prompts:
        return {"shape": "E", "reason": "no_scorable_content", "facts": facts}
    # 4 — agentic SoC + cocotb harness.
    if has_cocotb:
        return {"shape": "D", "reason": "cocotb_harness_present", "facts": facts}
    # 1 — full IC: multiple modules AND a PDK/constraints target.
    if n_modules >= 2 and has_pdk:
        return {"shape": "A", "reason": "multi_module_with_pdk_target", "facts": facts}
    # 3 — atomic micro-problems: many small prompts.
    if n_prompts >= 100 and 0 < max_lines <= 30:
        return {"shape": "C", "reason": "atomic_microproblems_ge100_le30lines",
                "facts": facts}
    # 2 — substantial standalone single-module (+ its own TB, implied by HDL).
    if has_hdl or prompts:
        return {"shape": "B", "reason": "substantial_standalone_single_module",
                "facts": facts}
    return {"shape": "E", "reason": "no_scorable_content", "facts": facts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("benchmark_dir", help="benchmark directory to classify")
    ap.add_argument("--problem-count", type=int,
                    help="override dataset cardinality (else auto-counted)")
    ap.add_argument("--oracle-gated", action="store_true",
                    help="force the E predicate (golden removed / access-gated)")
    ap.add_argument("--json", help="write JSON report to this path")
    a = ap.parse_args(argv)

    d = Path(a.benchmark_dir)
    if not d.is_dir():
        print(f"usage error: not a directory: {d}", file=sys.stderr)
        return 2

    result = classify(d, a.problem_count, a.oracle_gated)
    result["program"] = "benchmark_shape_classify"
    result["benchmark_dir"] = str(d)
    if a.json:
        Path(a.json).write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Shape {result['shape']}  ({result['reason']})")
    print(f"  facts: {json.dumps(result['facts'])}")
    return 1 if result["shape"] == "E" else 0


if __name__ == "__main__":
    raise SystemExit(main())
