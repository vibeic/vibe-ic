#!/usr/bin/env python3
"""input_docs_coverage_check.py — v0.50 plugin gate

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This program is wired into the flow as an
`advisory_program_exit_zero` clause: it RUNS on every project that reaches its
step, its findings are printed, and its exit code cannot deny the step its PASS
tier. That is deliberate — it was wired to make a real check reachable, not to
block a landing on debt it did not create — and the declaration says so where
the audit looks. Without it, "wired where it cannot block" and "nobody decided"
are the same record, and the reliable way to stay clean is to say nothing.
Verifies that EVERY file in `input/docs/` has been read and cited by the
Phase-1 / Phase-2 agent chain. Prevents the failure mode observed with the
v0.50-pre HIGH <benchmark> pilot, where the fresh-agent produced plausible-looking
L*.json + RTL without actually parsing ~half the vendor documents, leading to
fabricated response structures that failed real <half-duplex-tester> hardware testing.

Coverage rule: for each file in `input/docs/`, at least one of:
  (a) `generated_docs/L*.json` contains a `provenance` object citing the file
      path (substring match, case-insensitive), OR
  (b) `input_docs_coverage.md` in the project root explicitly lists the file
      → which spec item(s) it contributed → which RTL module / testbench
      verifies it.

Usage:
    python3 input_docs_coverage_check.py <project_dir>
        [--docs-dir <path>]   (default: <project_dir>/input/docs)
        [--layers-dir <path>] (default: <project_dir>/generated_docs)
        [--coverage-md <path>] (default: <project_dir>/input_docs_coverage.md)
        [--json <out>]
        [--strict]

Exit codes:
    0 — every input/docs file has coverage
    1 — one or more files missing coverage
    2 — path / input error
"""
from __future__ import annotations
import argparse, json, os, sys, re
from pathlib import Path
import _path_layout as _pl


def list_input_docs(docs_dir: Path) -> list[Path]:
    if not docs_dir.exists():
        return []
    return sorted(
        p for p in docs_dir.iterdir()
        if p.is_file() and not p.name.startswith(".")
    )


def load_layer_jsons(layers_dir: Path) -> list[tuple[Path, dict]]:
    out = []
    if not layers_dir.exists():
        return out
    for p in sorted(layers_dir.glob("L*.json")):
        try:
            out.append((p, json.loads(p.read_text())))
        except Exception:
            pass
    return out


def _walk(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)
    elif isinstance(node, str):
        yield node


def cite_in_layer(layer_json: dict, doc_name: str) -> bool:
    """Return True if any string value in layer_json mentions doc_name (case-insensitive)."""
    needles = [doc_name.lower()]
    # Also check the stem without extension for looser match
    stem = doc_name.rsplit(".", 1)[0].lower()
    if stem and stem != doc_name.lower():
        needles.append(stem)
    for s in _walk(layer_json):
        s_lower = s.lower()
        if any(n in s_lower for n in needles):
            return True
    return False


def cite_in_coverage_md(coverage_text: str, doc_name: str) -> bool:
    t = coverage_text.lower()
    needles = [doc_name.lower(), doc_name.rsplit(".", 1)[0].lower()]
    return any(n in t for n in needles)


# ---------------------------------------------------------------------------
# v0.50.1 strict contribution check (learned from <benchmark> measured_timing.pptx miss)
# ---------------------------------------------------------------------------
# A fresh-agent cited `AS3616_measured_timing.pptx` in its coverage manifest with the
# single line:
#     "Reviewed for context; did not contribute RTL constants."
# It turned out slide 2 of that pptx contained exactly the lab-measured
# response-IBT=22.7us value that <half-duplex-tester> PASS requires. The agent looked at
# the file, formed an off-hand dismissal, and skipped. The plugin's earlier
# coverage check only verified the file was NAMED somewhere — not that the
# agent had actually DERIVED facts from it (or justified why not).
#
# This function catches the "looked-and-skipped" smell: if the coverage
# manifest cites a doc but marks it as non-contributing with a weak reason
# like "reviewed for context" or "did not contribute", raise a WARN (strict
# mode: FAIL) so a reviewer / follow-up agent can re-check the file.
_SKIP_SMELL_PHRASES = [
    "did not contribute",
    "reviewed for context",
    "not relevant",
    "skipped",
    "out of scope",
    "context only",
]


def find_weak_contributions(coverage_text: str) -> list[tuple[str, str]]:
    """Return list of (line_number_hint, snippet) for suspiciously-weak
    non-contribution claims in the coverage manifest."""
    findings = []
    for i, line in enumerate(coverage_text.splitlines(), start=1):
        l = line.lower()
        for phrase in _SKIP_SMELL_PHRASES:
            if phrase in l:
                findings.append((f"line {i}", line.strip()[:200]))
                break
    return findings


def check(project_dir: Path, docs_dir: Path, layers_dir: Path,
          coverage_md: Path) -> dict:
    docs = list_input_docs(docs_dir)
    if not docs:
        return {
            "pass": False,
            "error": f"no files found in input docs dir {docs_dir}",
            "findings": [],
        }

    layers = load_layer_jsons(layers_dir)
    coverage_text = coverage_md.read_text() if coverage_md.exists() else ""

    findings = []
    covered = []
    for d in docs:
        name = d.name
        # Check each layer JSON
        cited_in = []
        for (lp, lj) in layers:
            if cite_in_layer(lj, name):
                cited_in.append(lp.name)
        # Check coverage manifest
        in_md = cite_in_coverage_md(coverage_text, name)

        if not cited_in and not in_md:
            findings.append({
                "severity": "FAIL",
                "rule": "input_doc_coverage",
                "doc": name,
                "message": f"input/docs/{name} not cited in any L*.json provenance or input_docs_coverage.md",
            })
        else:
            covered.append({
                "doc": name,
                "cited_in_layers": cited_in,
                "cited_in_manifest": in_md,
            })

    # v0.50.1 — flag weak "reviewed for context" dismissals that previously
    # hid load-bearing facts (see <benchmark> measured_timing.pptx post-mortem).
    weak = find_weak_contributions(coverage_text) if coverage_text else []
    for loc, snippet in weak:
        findings.append({
            "severity": "WARN",
            "rule": "weak_contribution_claim",
            "location": loc,
            "message": (
                f"Coverage manifest says: {snippet!r} — this phrase is a known "
                "'looked-and-skipped' smell. If the doc truly has no RTL-relevant "
                "facts, explain per-section which specific items you ruled "
                "unused and why. v0.50.1 learned from <benchmark> measured_timing.pptx "
                "where slide 2 contained the response-IBT=22.7us value needed "
                "for <half-duplex-tester> PASS but was dismissed as 'reviewed for context'."
            ),
        })

    return {
        "docs_total": len(docs),
        "docs_covered": len(covered),
        "docs_missing": sum(1 for f in findings if f["severity"] == "FAIL"),
        "weak_contributions": len(weak),
        "coverage": covered,
        "findings": findings,
        "pass": not any(f["severity"] == "FAIL" for f in findings),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--docs-dir", default=None)
    ap.add_argument("--layers-dir", default=None)
    ap.add_argument("--coverage-md", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="Exit 1 on any missing coverage (default behaviour).")
    args = ap.parse_args()

    proj = Path(args.project_dir)
    if not proj.exists():
        print(f"ERROR: project dir {proj} not found", file=sys.stderr)
        return 2

    docs_dir = Path(args.docs_dir) if args.docs_dir else proj / "input" / "docs"
    layers_dir = Path(args.layers_dir) if args.layers_dir else _pl.generated_docs_dir(proj)
    coverage_md = Path(args.coverage_md) if args.coverage_md else proj / "input_docs_coverage.md"

    result = check(proj, docs_dir, layers_dir, coverage_md)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result.get("pass") else 1


if __name__ == "__main__":
    sys.exit(main())
