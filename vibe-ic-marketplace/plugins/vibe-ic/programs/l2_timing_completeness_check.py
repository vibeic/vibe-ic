#!/usr/bin/env python3
"""
l2_timing_completeness_check.py — gate (LL-32) catching frs-gen
regressions that produce abstract-only L2_FRS.json with no concrete
timing keys when the input docs clearly measure timings.

Why this gate exists
====================
v0.119.30 <benchmark> vendor benchmark caught the regression:
  - input/docs/量測時序.pptx (extracted text) lists `tITO`, `tWFT`,
    `H1_MAX`, `BR_MIN` etc. with concrete µs values.
  - input/docs/MDV-A1101-FRS.txt §5.2 documents wake_pulse mechanism.
  - Fresh agent emitted L2_FRS.json with only `functional_requirements`
    + `non_functional_requirements` — no `timing_parameters` block,
    no numeric `*_us` / `*_ms` / `*_ns` keys.
  - frs_timing_range_check (LL-20) PASSed because there were no
    timing keys to verify — silent-skip path.
  - Downstream: spec-to-rtl had no L2 timing source, RTL went off
    rails.

This gate triggers when input/docs CONTAIN measured timings AND L2
contains NO timing keys — closing the "no keys = silent pass" hole in
LL-20.

Rule
----
1. Scan input/docs/ for evidence that timings are actually measured:
   • Regex `\\bt[A-Z][A-Za-z0-9]*_(us|ms|ns)\\b\\s*[:=]?\\s*[\\d.]+`
     (e.g. `tITO_ms = 5`, `tWFT: 20us`)
   • OR a table row pattern like `MIN .* Max .* (us|ms|ns)`
   • OR a `H[01]_MAX[\\d+]` / `BR_MIN[\\d+]` (vendor table — also implies
     timing presence)
2. If no evidence in input/docs/, silent-skip (PASS).
3. If evidence present, load L2_FRS.json (or L2_TIMING_WAVEFORM.json
   fallback) and walk the JSON tree for any numeric leaf with key
   ending in `_us` / `_ms` / `_ns` / `_ps` / `_cyc` / `_ticks`. Also
   accept top-level keys `timing_parameters`, `bit_timing_external`,
   `bit_timing_internal`, `timeouts` if non-empty.
4. If L2 has zero timing keys, FAIL with the doc evidence cited.

Honors waivers.json key `l2_timing_externalized_to_other_doc`
(≥20 chars) — for projects where timings live solely in L8 / L11.

Usage
-----
python3 l2_timing_completeness_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl

DOC_TIMING_PAT = re.compile(
    r"\bt[A-Z][A-Za-z0-9]*_(us|ms|ns)\b\s*[:=]?\s*[\d.]+",
)
TABLE_HDR_PAT = re.compile(
    r"\bMIN\b.*\bMAX\b.*\b(us|ms|ns)\b",
    re.IGNORECASE,
)
VENDOR_TABLE_PAT = re.compile(
    r"\b(H[01]_(MIN|MAX)|BR_(MIN|MAX)|IBT_(MIN|MAX))\s*\[\s*\d+\s*\]",
    re.IGNORECASE,
)

L2_TIMING_KEY_PAT = re.compile(
    r"_(us|ms|ns|ps|cyc|ticks)$",
    re.IGNORECASE,
)
L2_CONTAINER_KEYS = {
    "timing_parameters",
    "bit_timing_external",
    "bit_timing_internal",
    "timeouts",
    "response_timing",
    "protocol_specific_timing",
}


def find_input_docs(project: Path) -> list[Path]:
    base = project / "input" / "docs"
    if not base.is_dir():
        return []
    out: list[Path] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in {
            ".txt", ".md", ".csv", ".tsv", ".log", ".json",
            ".yaml", ".yml", "",
        }:
            out.append(p)
    return out


def find_l2(project: Path) -> Path | None:
    for stem in ("L2_FRS.json", "L2_TIMING_WAVEFORM.json"):
        for base in (_pl.generated_docs_dir(project), project / "docs",
                     project):
            p = base / stem
            if p.is_file():
                return p
    return None


def doc_has_timing_evidence(text: str) -> str | None:
    if DOC_TIMING_PAT.search(text):
        m = DOC_TIMING_PAT.search(text)
        return f"timing literal `{m.group(0)}`"
    if TABLE_HDR_PAT.search(text):
        return "MIN/MAX timing table header"
    if VENDOR_TABLE_PAT.search(text):
        return "vendor reference timing-tick table"
    return None


def collect_timing_keys(node, prefix="") -> int:
    if isinstance(node, dict):
        n = 0
        for k, v in node.items():
            kl = k.lower()
            if kl in L2_CONTAINER_KEYS and v:
                # Container present and non-empty: count once if it has
                # at least one numeric leaf or sub-dict with content.
                if isinstance(v, dict) and v:
                    n += 1
                elif isinstance(v, list) and v:
                    n += 1
            if L2_TIMING_KEY_PAT.search(k):
                if isinstance(v, (int, float)):
                    n += 1
                elif isinstance(v, list) and v and \
                     all(isinstance(x, (int, float)) for x in v):
                    n += 1
                elif isinstance(v, dict) and (
                    "min" in v or "max" in v or "value" in v
                ):
                    n += 1
            if isinstance(v, (dict, list)):
                n += collect_timing_keys(v, f"{prefix}.{k}")
        return n
    if isinstance(node, list):
        return sum(collect_timing_keys(x, prefix) for x in node)
    return 0


def waived(project: Path) -> bool:
    p = project / "waivers.json"
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
        v = d.get("l2_timing_externalized_to_other_doc", "")
        return isinstance(v, str) and len(v.strip()) >= 20
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: l2_timing_completeness_check.py <project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    docs = find_input_docs(project)
    evidence: list[tuple[str, str]] = []
    for d in docs:
        try:
            text = d.read_text(errors="replace")
        except Exception:
            continue
        ev = doc_has_timing_evidence(text)
        if ev:
            evidence.append((d.name, ev))

    if not evidence:
        print("PASS — no timing evidence in input/docs/ (gate skipped)")
        return 0

    l2 = find_l2(project)
    if not l2:
        if waived(project):
            print("PASS_WITH_WAIVER — L2 absent but waiver set")
            return 0
        print(f"FAIL — input/docs/ measure timings ({len(evidence)} "
              f"evidence hit(s)) but L2_FRS.json / "
              f"L2_TIMING_WAVEFORM.json is missing.")
        for fn, ev in evidence[:5]:
            print(f"  • {fn}: {ev}")
        return 1

    try:
        data = json.loads(l2.read_text())
    except Exception as e:
        print(f"FAIL — cannot parse {l2.name}: {e}")
        return 1

    n_keys = collect_timing_keys(data)
    if n_keys > 0:
        print(f"PASS — L2 has {n_keys} timing key(s) / non-empty timing "
              "container(s)")
        return 0

    if waived(project):
        print("PASS_WITH_WAIVER — L2 has no timing keys but waiver set")
        return 0

    print(f"FAIL — input/docs/ measure timings but L2 ({l2.name}) has "
          "ZERO timing keys (no `*_us` / `*_ms` / `*_ns` / `*_cyc` "
          "leaves, no non-empty `timing_parameters` / `timeouts` / "
          "`bit_timing_*` containers).")
    print()
    print("Doc evidence:")
    for fn, ev in evidence[:5]:
        print(f"  • {fn}: {ev}")
    print()
    print("Fix: re-run frs-gen / timing-waveform-gen and emit a")
    print("     `timing_parameters` block in L2_FRS.json with the")
    print("     concrete µs / ms / ns values from input/docs/. See")
    print("     SKILL.md `MANDATORY rule (v0.119.10)`.")
    print()
    print('Or document the intentional case in waivers.json:')
    print('    {"l2_timing_externalized_to_other_doc": "<reason>"}')
    return 1


if __name__ == "__main__":
    sys.exit(main())
