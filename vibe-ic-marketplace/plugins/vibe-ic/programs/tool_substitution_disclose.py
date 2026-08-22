#!/usr/bin/env python3
"""tool_substitution_disclose.py — emit the mandatory RESULT.md
tool-substitution disclosure block from a fixed lookup table.

Extracted from open-benchmark-methodology § 3. Open benchmarks
frequently mandate commercial EDA tools we don't have. Every
RESULT.md MUST state the substitution explicitly. This program turns
the fixed `mandated → substitute (+ caveat)` lookup into a
deterministic markdown table so the disclosure can't drift or be
forgotten.

The lookup is the canonical § 3 table:

  Synopsys VCS sim         → iverilog 12        (VCS-only TB constructs reject)
  Synopsys Design Compiler → yosys + OpenROAD   (NOT apples-to-apples PPA)
  Cadence Xcelium          → iverilog           (same commercial gap as VCS)
  nvidia/cvdp-sim:v1.0.0   → hpretl/iic-osic-tools (cocotb version delta)

Usage
=====
  # Emit the full canonical disclosure table:
  python3 tool_substitution_disclose.py --all [--json out.json]

  # Emit only the rows that apply to a given run (by mandated-tool tokens):
  python3 tool_substitution_disclose.py --mandated "Synopsys VCS,Xcelium" \
      [--json out.json]

  # Verify a produced RESULT.md actually carries the disclosure for the
  # tools it used (FAILs if a mandated tool is used but not disclosed):
  python3 tool_substitution_disclose.py --verify RESULT.md \
      --mandated "Synopsys VCS"

Honest failure
==============
  * --mandated with a token that matches NO known mandated tool → FAIL
    (rc 1): you can't disclose a substitution we have no entry for; emit
    nothing and force the caller to add the entry rather than fabricate.
  * --verify on a missing/empty RESULT.md → FAIL (rc 1): cannot confirm a
    disclosure that isn't there.
  * --verify when a mandated tool's substitute string is absent from the
    RESULT.md → FAIL (rc 1) with the missing rows listed.

Exit codes
==========
  0 — PASS (emitted ≥1 row, or --verify found all required disclosures)
  1 — FAIL (no matching row / missing disclosure / empty input)
  2 — usage error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Canonical § 3 substitution lookup. Each row is keyed by the commercial
# tool the benchmark mandates; `match` lists tokens (lowercased substrings)
# that identify that mandate in free text.
SUBSTITUTIONS = [
    {
        "mandated": "Synopsys VCS sim",
        "substitute": "iverilog 12",
        "caveat": "Some VCS-only TB constructs (array-aggregate init, `break;`) "
                  "reject under iverilog → pure tool-gap floor",
        "match": ["synopsys vcs", "vcs sim", " vcs"],
    },
    {
        "mandated": "Synopsys Design Compiler PPA",
        "substitute": "yosys + OpenROAD (sky130/gf180)",
        "caveat": "NOT reported as PPA in benchmark RESULT (not apples-to-apples). "
                  "If you DO report, label clearly",
        "match": ["design compiler", "synopsys dc", "dc ppa"],
    },
    {
        "mandated": "Cadence Xcelium",
        "substitute": "iverilog",
        "caveat": "Same iverilog-vs-commercial gap as VCS",
        "match": ["xcelium", "cadence"],
    },
    {
        "mandated": "nvidia/cvdp-sim:v1.0.0 Docker image",
        "substitute": "hpretl/iic-osic-tools (iverilog 13 + cocotb 2.0.1)",
        "caveat": "Note the substitution + cocotb version delta",
        "match": ["cvdp-sim", "nvidia/cvdp", "cvdp sim"],
    },
    {
        # ORGANIC #717 — completing the VCS→iverilog substitution at the
        # CONSTRUCT level: a deterministic semantics-preserving source rewrite
        # of the closed safe subset (break;→labelled-block disable,
        # continue;→inner-block disable, drop unique/priority qualifier),
        # written to a `*_iv.v` SIDECAR (original TB untouched) by
        # tb_vcs_only_construct_remediate.py.
        "mandated": "VCS-only TB construct (break;/continue;/unique-priority)",
        "substitute": "semantics-preserving iverilog rewrite (*_iv.v sidecar)",
        "caveat": "Closed safe subset ONLY; gated on golden-still-passes — a "
                  "TB-weakening rewrite is rejected. std::randomize / "
                  "$urandom_range / join_none / queue ops stay FLOOR-D.",
        "match": ["vcs-only tb construct", "tb construct rewrite",
                  "semantics-preserving iverilog rewrite"],
    },
    # v1.3.96 — ADVANCED-NODE / COMMERCIAL-ONLY gaps (docs/ADVANCED_NODE_EXTENSION.md).
    # NO OSS engine at any node → substitute is "none". These are NEVER numbered
    # OSS steps and never counted in the PASS; disclosed here so a report that
    # touches the area names the gap honestly. (Where an OSS FLOOR exists it was
    # added as a real step: VCD-vectored dynamic-IR, FMEDA-DC, power-domain CDC.)
    {
        "mandated": "PrimeTime-POCV / statistical STA (POCV/SSTA)",
        "substitute": "none (commercial-only) — flat-OCV + AOCV is the OSS floor",
        "caveat": "Needs LVF / POCV coefficient data absent from OSS PDKs; ≤7nm "
                  "within-die variation data is foundry-NDA",
        "match": ["pocv", "ssta", "statistical sta", "primetime-pocv", "lvf"],
    },
    {
        "mandated": "RedHawk-SC / Voltus transient dynamic-IR (di/dt)",
        "substitute": "none (commercial-only) — VCD-vectored PSM is the OSS floor",
        "caveat": "OSS PSM is resistive/vectored only; no L·di/dt time-domain "
                  "inductive-droop solve",
        "match": ["redhawk", "voltus", "transient ir", "di/dt", "dynamic ir transient"],
    },
    {
        "mandated": "2.5D/3D advanced packaging / chiplet assembly (CoWoS/EMIB/TSV)",
        "substitute": "none (commercial-only) — D2D protocol layer only in OSS",
        "caveat": "Multi-die assembly rules / interposer / hybrid-bond PDK absent "
                  "in OSS; UCIe/CXL/HBM3 PROTOCOL RTL is synthesized",
        "match": ["cowos", "emib", "chiplet", "2.5d", "3d ic", "tsv", "hybrid bond",
                  "3dblox"],
    },
    {
        "mandated": "MBIST / LBIST + memory ATPG",
        "substitute": "none (commercial-only)",
        "caveat": "Memory BIST insertion + memory fault models are commercial; "
                  "OSS Fault does logic stuck-at ATPG only",
        "match": ["mbist", "lbist", "memory bist", "tessent"],
    },
    # v1.3.99 — two former "none" areas now have a REAL disclosed OSS tier
    # (they moved from ADVANCED_NODE_EXTENSION gaps to flow steps 22/DT2):
    {
        "mandated": "Calibre xRC / StarRC-XT / QRC field-solved coupling extraction",
        "substitute": "OpenRCX v2 -lef_rc grounded RC + analytical lateral "
                      "coupling augment (_spef_coupling, step 22) + REAL 3D BEM "
                      "field solve via FasterCap on a PDK-inverted fitted "
                      "dielectric stack (pdk_dielectric_fit + fastercap_extract, "
                      "step 22 field_solve — lateral + inter-layer crossover)",
        "caveat": "NOT foundry-calibrated: the dielectric stack is FITTED from "
                  "the PDK's own area+fringe cap, not the foundry rules.C/.nxtgrd "
                  "multi-dielectric profile; single fitted eps_r per solve; "
                  "aggressor-victim crosstalk (SI) sign-off remains commercial",
        "match": ["xrc", "starrc", "nxtgrd", "rules.c", "qrc", "fastercap",
                  "field solver extraction", "coupling extraction"],
    },
    {
        "mandated": "Commercial at-speed (path-delay / small-delay-defect) ATPG",
        "substitute": "path_delay_fault_atpg_run (step DT2: OpenSTA K-longest "
                      "on routed netlist+SPEF -> per-path LOC miter SAT, "
                      "robust/non-robust graded) + sdd_atpg_run (step DT3: "
                      "slack-weighted small-delay-defect grade)",
        "caveat": "Top-K longest paths only (exhaustive PDF is exponential; K "
                  "disclosed); PI-launched paths are not LOC-testable and are "
                  "excluded, never counted; SDD is STA-slack-graded, not a "
                  "per-defect-size SPICE credit",
        "match": ["at-speed atpg", "at speed atpg", "path delay atpg",
                  "path-delay atpg", "small delay defect", "sdd atpg",
                  "tetramax"],
    },
    {
        "mandated": "Side-channel leakage sim (DPA/CPA/EM)",
        "substitute": "none (commercial-only)",
        "caveat": "Leakage-model simulation needs a specialized engine (PROLEAD/…)",
        "match": ["side-channel", "side channel", "dpa", "cpa leakage", "proleaD"],
    },
]


def _rows_for(mandated_csv: str | None) -> tuple[list[dict], list[str]]:
    """Return (matched rows, unmatched tokens). If mandated_csv is None,
    return ALL canonical rows (the --all behaviour)."""
    if mandated_csv is None:
        return list(SUBSTITUTIONS), []
    tokens = [t.strip() for t in mandated_csv.split(",") if t.strip()]
    matched: list[dict] = []
    unmatched: list[str] = []
    seen_idx: set[int] = set()
    for tok in tokens:
        low = tok.lower()
        hit = False
        for i, row in enumerate(SUBSTITUTIONS):
            if any(m in low or low in m for m in row["match"]) or low in row["mandated"].lower():
                hit = True
                if i not in seen_idx:
                    seen_idx.add(i)
                    matched.append(row)
        if not hit:
            unmatched.append(tok)
    return matched, unmatched


def render_table(rows: list[dict]) -> str:
    lines = [
        "## Tool substitution (open-benchmark-methodology § 3)",
        "",
        "| Benchmark mandates | We substitute | Caveat |",
        "|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['mandated']} | {r['substitute']} | {r['caveat']} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--all", action="store_true",
                    help="emit the full canonical disclosure table")
    ap.add_argument("--mandated",
                    help="CSV of commercial tools the benchmark mandated")
    ap.add_argument("--verify", help="RESULT.md to verify disclosure in")
    ap.add_argument("--json", help="write JSON report to this path")
    a = ap.parse_args(argv)

    if not a.all and a.mandated is None and a.verify is None:
        ap.error("need --all, --mandated, or --verify")

    report: dict = {"program": "tool_substitution_disclose"}

    # Determine the required rows.
    rows, unmatched = _rows_for(None if a.all else a.mandated)

    if not a.all and a.mandated is not None and unmatched and not rows:
        report["verdict"] = "FAIL"
        report["reason"] = "no_known_substitution_for_mandated"
        report["unmatched"] = unmatched
        _emit(a, report, None)
        print(f"FAIL: no canonical substitution row for: {', '.join(unmatched)}",
              file=sys.stderr)
        return 1

    if a.verify is not None:
        p = Path(a.verify)
        if not p.exists() or not p.read_text(encoding="utf-8", errors="replace").strip():
            report["verdict"] = "FAIL"
            report["reason"] = "result_md_missing_or_empty"
            report["path"] = str(p)
            _emit(a, report, None)
            print(f"FAIL: RESULT.md missing or empty: {p}", file=sys.stderr)
            return 1
        text = p.read_text(encoding="utf-8", errors="replace")
        missing = [r for r in rows
                   if r["substitute"].split("(")[0].strip().lower() not in text.lower()]
        report["required_rows"] = [r["mandated"] for r in rows]
        report["missing_disclosures"] = [r["mandated"] for r in missing]
        report["unmatched_tokens"] = unmatched
        if missing:
            report["verdict"] = "FAIL"
            report["reason"] = "substitution_not_disclosed"
            _emit(a, report, None)
            print("FAIL: RESULT.md missing substitution disclosure for: "
                  + ", ".join(r["mandated"] for r in missing), file=sys.stderr)
            return 1
        report["verdict"] = "PASS"
        _emit(a, report, None)
        print(f"PASS: all {len(rows)} mandated-tool substitution(s) disclosed")
        return 0

    # Emit mode.
    table = render_table(rows)
    report["verdict"] = "PASS"
    report["emitted_rows"] = [r["mandated"] for r in rows]
    report["unmatched_tokens"] = unmatched
    report["table"] = table
    _emit(a, report, table)
    print(table)
    if unmatched:
        print(f"(note: {len(unmatched)} mandated token(s) had no canonical row: "
              f"{', '.join(unmatched)})", file=sys.stderr)
    return 0


def _emit(a, report: dict, table: str | None) -> None:
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
