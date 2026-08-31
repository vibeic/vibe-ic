#!/usr/bin/env python3
"""Refuse benchmark-specific routing or solving entry points.

Open evaluations differ only at the thin I/O/scorer boundary. Benchmark ICs
use the same whole-chip runner as any other IC. A benchmark name, cid, problem
id, or benchmark-IC name must never select a different author/router/solver.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROGRAMS = Path(__file__).resolve().parents[1] / "programs"
sys.path.insert(0, str(PROGRAMS))
from _atomic_artefact import write_text as _atomic_write_text

PLUGIN = Path(__file__).resolve().parents[1]
BENCHMARK = PLUGIN / "benchmark"
REGISTRY = BENCHMARK / "BENCHMARK_REGISTRY.json"

FORBIDDEN_ENTRY_GLOBS = (
    "*_task_router.py",
    "*_task_loop.py",
    "*_phase1_entry.py",
    "*_prompt_export.py",
    "*_solve_pipeline.py",
    "*_tier_pipeline.py",
    "*_atomic_bridge.py",
)
FORBIDDEN_ENTRY_TEXT = (
    "local_export",
    "per-cid",
    "cvdp_task_router",
    "cvdp_task_loop",
    "cvdp_phase1_entry",
    "cvdp_prompt_export",
    "gates_atomic.py",
)
GENERAL_OPEN_BENCHES = (
    "verilogeval-v2",
    "verilogeval-human",
    "rtllm",
    "cvdp-open",
)
ENTRY_DOCS = (
    PLUGIN / "README.md",
    PLUGIN / "agents" / "benchmark-agent.md",
    PLUGIN / "commands" / "vibe-ic-benchmark.md",
    PLUGIN / "hooks" / "benchmark-keyword-skill-reminder.sh",
    PLUGIN / "skills" / "open-benchmark-methodology" / "SKILL.md",
    BENCHMARK / "README.md",
    BENCHMARK / "blind_instructions_shape_b.md",
    BENCHMARK / "blind_instructions_shape_c.md",
    BENCHMARK / "blind_instructions_shape_cvdp.md",
)
GENERAL_CORE_FILES = (
    PLUGIN / "programs" / "task_nature_route.py",
    PLUGIN / "programs" / "vibe_ic_one_shot_runner.py",
    PLUGIN / "programs" / "design_one_shot_runner.py",
)
_BENCHMARK_SELECTOR = re.compile(
    r"(?:cvdp|rtllm|verilogeval|benchmark[_-]?clean|\bprob\d+|\bcid\d+)",
    re.IGNORECASE)


def _selector_literals(test: ast.AST) -> List[str]:
    """Benchmark/problem literals used by a control-flow selector."""
    found: List[str] = []
    for node in ast.walk(test):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _BENCHMARK_SELECTOR.search(node.value):
                found.append(node.value)
    return found


def audit(plugin: Path = PLUGIN) -> Dict[str, object]:
    plugin = Path(plugin)
    benchmark = plugin / "benchmark"
    findings: List[dict] = []
    registry_path = benchmark / "BENCHMARK_REGISTRY.json"
    try:
        registry = json.loads(registry_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {"verdict": "FAIL", "findings": [{
            "rule": "REGISTRY_UNREADABLE", "path": str(registry_path),
            "detail": str(exc)}]}
    entries = registry.get("benchmarks") or {}

    # Scan the shipped plugin, not only benchmark/.  Historical benchmark-name
    # pipelines lived under programs/, which made a benchmark/-only audit green
    # while the alternate solver was still installable.
    for pattern in FORBIDDEN_ENTRY_GLOBS:
        for path in plugin.rglob(pattern):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            findings.append({
                "rule": "BENCHMARK_SPECIFIC_ENTRY_FILE",
                "path": str(path.relative_to(plugin)),
                "detail": f"matches forbidden executable entry shape {pattern}",
            })

    # A generic filename can still hide an IC/benchmark-specific branch. Audit
    # executable selectors in the common router and runners rather than grepping
    # comments or provenance notes.
    core_roots = [plugin / path.relative_to(PLUGIN)
                  for path in GENERAL_CORE_FILES]
    for path in core_roots:
        try:
            tree = ast.parse(path.read_text(errors="replace"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            findings.append({
                "rule": "GENERAL_CORE_UNREADABLE",
                "path": str(path.relative_to(plugin)),
                "detail": str(exc),
            })
            continue
        selectors = []
        for node in ast.walk(tree):
            test = None
            if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)):
                test = node.test
            elif isinstance(node, ast.Match):
                test = node.subject
                for case in node.cases:
                    selectors.extend(_selector_literals(case.pattern))
            if test is not None:
                selectors.extend(_selector_literals(test))
        if selectors:
            findings.append({
                "rule": "GENERAL_CORE_BENCHMARK_SELECTOR",
                "path": str(path.relative_to(plugin)),
                "detail": "control flow selects on " + repr(sorted(set(selectors))),
            })

    for name in GENERAL_OPEN_BENCHES:
        entry = entries.get(name)
        if not isinstance(entry, dict):
            findings.append({
                "rule": "GENERAL_BENCHMARK_MISSING",
                "path": str(registry_path.relative_to(plugin)),
                "detail": f"{name} is absent",
            })
            continue
        solve = entry.get("solve_entry")
        if not isinstance(solve, dict):
            findings.append({
                "rule": "GENERAL_ENTRY_UNDECLARED",
                "path": f"registry:{name}",
                "detail": "solve_entry is absent",
            })
            continue
        front = str(solve.get("front_door") or "")
        if ("programs/benchmark_dispatch.py" not in front
                or "--solve" not in front):
            findings.append({
                "rule": "GENERAL_ENTRY_NOT_FRONT_DOOR",
                "path": f"registry:{name}",
                "detail": front or "front_door is absent",
            })
        entry_text = json.dumps(
            {"flow": entry.get("flow"), "solve_entry": solve},
            ensure_ascii=False).lower()
        for token in FORBIDDEN_ENTRY_TEXT:
            if token.lower() in entry_text:
                findings.append({
                    "rule": "SHORTCUT_REFERENCED_BY_REGISTRY",
                    "path": f"registry:{name}",
                    "detail": f"contains {token!r}",
                })

    ic = entries.get("benchmark_clean")
    policy = ic.get("entry_policy") if isinstance(ic, dict) else None
    expected = {
        "front_door": "commands/vibe-ic-all.md",
        "runner": "programs/vibe_ic_one_shot_runner.py",
        "verify": "skills/benchmark-verify/SKILL.md",
        "benchmark_specific_solver": False,
    }
    if policy != expected:
        findings.append({
            "rule": "BENCHMARK_IC_NOT_GENERAL_ENTRY",
            "path": "registry:benchmark_clean",
            "detail": f"expected {expected!r}, got {policy!r}",
        })

    doc_roots = [plugin / path.relative_to(PLUGIN) for path in ENTRY_DOCS]
    doc_roots += sorted((plugin / "benchmark" / "examples").glob("*.md"))
    for path in doc_roots:
        try:
            text = path.read_text(errors="replace").lower()
        except OSError as exc:
            findings.append({
                "rule": "ENTRY_DOC_UNREADABLE", "path": str(path),
                "detail": str(exc)})
            continue
        if "--setup" in text:
            findings.append({
                "rule": "RETIRED_SETUP_RECOMMENDED",
                "path": str(path.relative_to(plugin)),
                "detail": "canonical entry documentation still names --setup",
            })
        if "--floor-only" in text or "--reattempt-floor" in text:
            findings.append({
                "rule": "PARTIAL_EVALUATION_RECOMMENDED",
                "path": str(path.relative_to(plugin)),
                "detail": "canonical entry documentation names a partial prior-failure run",
            })
        if "gates_atomic.py" in text:
            findings.append({
                "rule": "DIRECT_GATE_ENTRY_RECOMMENDED",
                "path": str(path.relative_to(plugin)),
                "detail": "canonical entry documentation names gates_atomic.py",
            })

    return {
        "verdict": "PASS" if not findings else "FAIL",
        "finding_count": len(findings),
        "findings": findings,
        "policy": {
            "open_evaluation": (
                "benchmark_dispatch --solve/--resume/--score"),
            "benchmark_ic": (
                "vibe-ic-all -> vibe_ic_one_shot_runner -> benchmark-verify"),
            "benchmark_specific_solver": False,
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plugin-root", type=Path, default=PLUGIN)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    report = audit(args.plugin_root)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(args.json, json.dumps(report, indent=2) + "\n")
    if report["verdict"] == "PASS":
        print("PASS: benchmark evaluation and benchmark IC use general entries")
        return 0
    print(f"FAIL: {report['finding_count']} benchmark shortcut finding(s)",
          file=sys.stderr)
    for finding in report["findings"]:
        print(f"  [{finding['rule']}] {finding['path']} — "
              f"{finding['detail']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
