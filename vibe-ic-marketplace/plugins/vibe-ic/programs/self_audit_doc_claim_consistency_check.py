#!/usr/bin/env python3
"""self_audit_doc_claim_consistency_check.py — anti-fabrication gate.

Sole rule: UNREPRODUCIBLE_BENCHMARK_PATH.

When a fenced code block in CHANGELOG.md / README.md / docs/**/*.md
quotes a benchmark path of the form `1st_benchmark_sn2025/<dir>/`,
that directory must exist on disk relative to the repo root. Catches
the v1.6.45 escape where CHANGELOG was rewritten to claim
`phase2+3_v10634/` was the real benchmark when only
`phase2+3_v10634-vendor/` existed.

VACUOUS-PASSes when the benchmark tree (`1st_benchmark_sn2025/`) is
absent — fresh checkouts and CI hosts without private benchmarks see
the gate as inapplicable.

(v1.6.45's rule A — GATE_COUNT_DRIFT for `==> all N gates PASS`
quotes — was retired in v1.6.48 because v1.6.47 killed the quote
convention itself, leaving the rule with nothing live to enforce.)

Usage:
    python3 self_audit_doc_claim_consistency_check.py <plugin_root>
                                                      [--json <out>]

Exit codes:
    0  PASS
    1  FAIL — doc claim disagrees with batch runner
    2  argument or I/O error

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple


# Benchmark path tokens like `1st_benchmark_sn2025/phase2+3_v10634-vendor`
# or `1st_benchmark_sn2025/phase2+3_v10634-vendor/`. The leading
# `1st_benchmark_sn2025/` is the only known root, so we anchor on it.
# Tokens containing wildcards / asterisks / `<...>` placeholders are
# excluded (they're not literal paths).
_BENCH_ROOT = "1st_benchmark_sn2025"
_BENCH_PATH_RE = re.compile(
    r"\b" + re.escape(_BENCH_ROOT)
    + r"/(?P<sub>[A-Za-z0-9_.+\-*?<>]+)/?"
)


@dataclass
class Finding:
    file: str
    line: int
    rule: str
    detail: str


def _audit_files(plugin_root: Path) -> List[Path]:
    """Scan plugin CHANGELOG (if present) plus repo-root README and
    every .md under repo-root docs/. Plugin.json / marketplace.json
    are excluded — only fenced markdown code blocks carry quoted
    benchmark paths, JSON description fields don't."""
    out: List[Path] = []
    cl = plugin_root / "CHANGELOG.md"
    if cl.is_file():
        out.append(cl)
    repo_root = plugin_root.parent.parent.parent
    for rel in ("README.md",):
        p = repo_root / rel
        if p.is_file():
            out.append(p)
    docs_dir = repo_root / "docs"
    if docs_dir.is_dir():
        out.extend(sorted(docs_dir.rglob("*.md")))
    return out


def _iter_fenced_lines(text: str):
    """Yield (line_no, line) pairs for every line inside a fenced
    code block (```...```). Lines outside fences are skipped — they
    are prose, where authors legitimately discuss phantom paths
    (e.g. "v1.6.45 quoted `phase2+3_v10634/` claiming…")."""
    in_fence = False
    for ln_no, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            yield ln_no, line


def _audit_benchmark_paths(plugin_root: Path,
                           audit_files: List[Path],
                           ) -> Tuple[bool, List[Finding]]:
    """Returns (gate_applicable, findings).

    `gate_applicable=False` => benchmark tree absent on this host;
    caller should treat the rule as VACUOUS.
    """
    repo_root = plugin_root.parent.parent.parent
    bench_root = repo_root / _BENCH_ROOT
    if not bench_root.is_dir():
        return False, []

    findings: List[Finding] = []
    for f in audit_files:
        # Only scan CHANGELOG-style files for benchmark paths;
        # plugin.json / marketplace.json carry compressed descriptions
        # not fenced examples.
        if f.suffix != ".md":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for ln_no, line in _iter_fenced_lines(text):
            for m in _BENCH_PATH_RE.finditer(line):
                sub = m.group("sub")
                # Skip placeholders / globs
                if any(ch in sub for ch in "<>*?") or \
                        sub.endswith("..."):
                    continue
                target = bench_root / sub
                if target.exists():
                    continue
                rel = (str(f.relative_to(plugin_root.parent))
                       if f.is_relative_to(plugin_root.parent)
                       else str(f))
                findings.append(Finding(
                    file=rel,
                    line=ln_no,
                    rule="UNREPRODUCIBLE_BENCHMARK_PATH",
                    detail=(
                        f"fenced code block references "
                        f"`{_BENCH_ROOT}/{sub}` but that path does "
                        f"not exist under {bench_root}. Either "
                        f"correct the path to the real benchmark "
                        f"directory or remove the example."
                    ),
                ))
    return True, findings


def audit(plugin_root: Path) -> Tuple[str, List[Finding]]:
    if not plugin_root.is_dir():
        return "VACUOUS_PASS", []

    files = _audit_files(plugin_root)
    bench_applicable, findings = _audit_benchmark_paths(plugin_root, files)
    if not bench_applicable:
        return "VACUOUS_PASS", []

    return ("FAIL" if findings else "PASS"), findings


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Anti-fabrication: enforce that any "
                    "`1st_benchmark_sn2025/<dir>/` path quoted in a "
                    "fenced markdown code block actually exists on "
                    "disk relative to the repo root.")
    ap.add_argument("plugin_root")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    root = Path(args.plugin_root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    verdict, findings = audit(root)
    report = {
        "gate": "self_audit_doc_claim_consistency_check",
        "verdict": verdict,
        "plugin_root": str(root),
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "VACUOUS_PASS":
        print("VACUOUS_PASS: 1st_benchmark_sn2025/ tree absent on this "
              "host (gate is dev-host-only)")
        return 0
    if verdict == "PASS":
        print("PASS: every fenced benchmark path resolves to a real "
              "directory")
        return 0
    print(f"FAIL: {len(findings)} doc-vs-reality drift(s):",
          file=sys.stderr)
    for f in findings[:20]:
        print(f"  [{f.rule}] {f.file}:{f.line}  {f.detail}",
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
