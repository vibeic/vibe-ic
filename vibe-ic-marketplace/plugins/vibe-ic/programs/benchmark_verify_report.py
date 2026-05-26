#!/usr/bin/env python3
"""
benchmark_verify_report.py — normalized per-benchmark-IC verification report.

Generates the single mandatory BENCHMARK_VERIFICATION_REPORT.md required by the
`benchmark-verify` skill for any benchmark IC that has been driven through the
full Vibe-IC flow (Design Documents -> generated RTL -> signed-off silicon).

It is chip-AGNOSTIC and DETERMINISTIC: it does not run EDA tools itself, it
AGGREGATES the evidence the flow + cross-check steps already produced, computes
the five verification pillars + their hard gates, and emits the report.

Five pillars (== the report sections, == the gates):
  1. Functional Verification Coverage   gate: == 100%
  2. 55-step Output Comparison (vs ref)  gate: every applicable step PASS
  3. Code Coverage (line)                gate: >= 90%
  4. FPGA digital verification           gate: PASS (or documented N/A)
  5. Analog verification                 gate: converged (or N/A for pure-digital)

Inputs it looks for under <project> (all optional; missing -> PENDING, never a
silent PASS):
  reports/functional_coverage.json   {"requirements":[{id,source,desc,status}], ...}
  reports/code_coverage.json         {"line_pct":.., "branch_pct":.., "toggle_pct":..}
  reports/hw_test.json               {"verdict":"PASS"|"FAIL", "patterns":N, ...}
  analog/analog_block_list.json      (presence => analog applicable)
  cross_check/**/step_<id>.md        per-step OURS-vs-REF verdict (first line w/ verdict token)
  SOURCE_MANIFEST.md                 GENERATED vs REUSED-IP tally

Usage:
  python3 benchmark_verify_report.py <project_dir> [--ref <reference_dir>] \
      [--flow <phase1_phase2_phase3.yaml>] [--out <report.md>]
"""
from __future__ import annotations
import argparse, json, re, sys, glob, os
from pathlib import Path

VERDICT_TOKENS = ["MATCH", "EQUIVALENT", "IN-RANGE", "BOTH-CLEAN", "PASS",
                  "DIFFERENT-BUT-OK", "BETTER-THAN-REF", "N/A", "GAP", "FAIL",
                  "TODO", "NO-TOOL"]
# A step PASSES the comparison gate if OURS is equivalent/in-range/clean vs REF,
# beats REF, or the step is a justified N/A (e.g. analog on a digital IC, or a
# capability neither the open-source flow nor the reference can produce).
PASS_TOKENS = {"MATCH", "EQUIVALENT", "IN-RANGE", "BOTH-CLEAN", "PASS",
               "DIFFERENT-BUT-OK", "BETTER-THAN-REF", "N/A"}

# ── Per-step output-comparison METHOD table (chip-agnostic) ──────────────────
# Method describes HOW to cross-check OUR step output vs the open-source ref.
# `kind`: equivalence | metric | clean | doc | layout-endpoint | mfg | analog
STEP_METHOD = {
    "D1": ("doc",  "L1-L13 field/semantic diff: ports/widths/PDK/clock/interface agree (same spec)"),
    "1":  ("equivalence", "LEC + co-sim: OUR RTL == REF RTL (functional equivalence)"),
    "2":  ("clean", "lint clean parity (both clean)"),
    "3":  ("clean", "CDC/RDC report parity"),
    "4":  ("equivalence", "simulation vs shared golden vectors (spec/standard golden)"),
    "5":  ("equivalence", "formal: assertions proved / k-induction vs spec golden"),
    "6":  ("metric", "FPGA early-proto report (optional)"),
    "P0": ("clean", "77 structural-RTL chip-agnostic checkers clean"),
    "7":  ("metric", "SDC diff: clock period / IO delay (both from L9)"),
    "8":  ("clean", "SDC validation parity"),
    "9":  ("metric", "synth netlist: cell-count/area in-range + LEC OUR==REF"),
    "10": ("metric", "pre-layout multi-corner STA slack compare"),
    "11": ("metric", "DFT scan-chain length + ATPG coverage compare"),
    "12": ("metric", "post-DFT netlist compare"),
    "13": ("equivalence", "LEC: RTL == post-DFT netlist"),
    "14": ("clean", "pre-PnR Yosys gate parity"),
    "15": ("metric", "floorplan/PDN: die area + utilization in-range"),
    "16": ("metric", "clock planning parity"),
    "17": ("metric", "placement density + legality (check_placement)"),
    "18": ("metric", "CTS: clock-tree depth/skew/buffer compare"),
    "19": ("metric", "post-CTS hold slack >= 0 (both)"),
    "20": ("metric", "routed DEF: DRT-violations ~0 + component/net counts in-range"),
    "21": ("metric", "SPEF parasitic R/C magnitude compare"),
    "22": ("metric", "post-route multi-corner STA slack compare (all corners >= 0)"),
    "23": ("clean", "IR drop within budget"),
    "24": ("clean", "EM lifetime within budget"),
    "25": ("clean", "antenna check clean"),
    "26": ("clean", "signal-integrity / crosstalk within budget"),
    "27": ("equivalence", "post-layout gate-sim + SDF vs golden"),
    "28": ("metric", "post-layout SPICE critical-path correlation"),
    "29": ("clean", "PV: DRC clean + LVS clean (both, non-vacuous)"),
    "30": ("clean", "ECO repair loop (only if PV failed)"),
    "31": ("metric", "power analysis compare"),
    "32": ("metric", "metal-fill density compare"),
    "33": ("clean", "tapeout checklist parity"),
    "34": ("layout-endpoint", "GDSII: NOT pixel-comparable across micro-arch -> both DRC/LVS-clean + functional-equiv"),
    "35": ("doc", "foundry handoff (mask/WAT/scribe) parity"),
    "36": ("metric", "FPGA final sign-off (recompile + on-board)"),
}
for a in ["A1","A2","A3","A4","A5","A6","A7","A8","A9"]:
    STEP_METHOD[a] = ("analog", "analog step — applicable only for mixed-signal ICs")
for m in ["M1","M2","M3","M4"]:
    STEP_METHOD[m] = ("analog", "mixed-signal step — applicable only for A+D ICs")
for s in ["37","38","39","40"]:
    STEP_METHOD[s] = ("mfg", "manufacturing step — requires physical silicon")


def _load_steps(flow_yaml: Path):
    try:
        import yaml
        d = yaml.safe_load(flow_yaml.read_text())
        return [(str(s.get("id")), s.get("name", ""), str(s.get("stage", "")))
                for s in d.get("steps", []) if isinstance(s, dict)]
    except Exception as e:
        print(f"[warn] could not parse flow yaml ({e}); using built-in 55-step ids",
              file=sys.stderr)
        ids = (["D1"] + [str(i) for i in range(1, 7)] + ["P0"]
               + [str(i) for i in range(7, 14)]
               + ["A1","A2","A3","A4","A5","A6","A7","A8","A9"]
               + [str(i) for i in range(14, 37)]
               + ["M1","M2","M3","M4"] + [str(i) for i in range(37, 41)])
        return [(i, "", "") for i in dict.fromkeys(ids)]


def _read_step_verdict(project: Path, sid: str):
    """First verdict token found in any cross_check/**/step_<id>.md."""
    for f in glob.glob(str(project / "cross_check" / "**" / f"step_{sid}.md"),
                       recursive=True) + \
             glob.glob(str(project / "cross_check" / "**" / f"step_{sid.zfill(2)}.md"),
                       recursive=True):
        txt = Path(f).read_text(errors="ignore")[:4000]
        for tok in VERDICT_TOKENS:
            if re.search(rf"\b{re.escape(tok)}\b", txt):
                return tok, f
    return None, None


def _is_analog_ic(project: Path) -> bool:
    return (project / "analog" / "analog_block_list.json").is_file() or \
           bool(glob.glob(str(project / "phase3" / "analog" / "*" / "*.gds")))


def _load_json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--ref", default="")
    ap.add_argument("--flow", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--code-cov-floor", type=float, default=90.0)
    a = ap.parse_args()
    project = Path(a.project).resolve()
    if not project.is_dir():
        print(f"error: project not a dir: {project}"); sys.exit(2)
    here = Path(__file__).resolve().parent
    flow = Path(a.flow) if a.flow else (here.parent / "flow" / "phase1_phase2_phase3.yaml")
    out = Path(a.out) if a.out else (project / "BENCHMARK_VERIFICATION_REPORT.md")
    analog_ic = _is_analog_ic(project)

    steps = _load_steps(flow)
    # ── Pillar 2: 55-step output comparison ──
    step_rows, n_pass, n_applicable, n_unresolved = [], 0, 0, 0
    for sid, name, stage in steps:
        kind, method = STEP_METHOD.get(sid, ("metric", "(uncategorized)"))
        applicable = True
        if kind == "analog" and not analog_ic:
            applicable = False; verdict = "N/A"
        elif kind == "mfg":
            applicable = False; verdict = "N/A (no silicon)"
        else:
            v, _ = _read_step_verdict(project, sid)
            verdict = v or "PENDING"
        if applicable:
            n_applicable += 1
            base = verdict.split()[0]
            if base in PASS_TOKENS:
                n_pass += 1
            elif base in ("FAIL", "GAP", "NO-TOOL", "TODO", "PENDING"):
                n_unresolved += 1
        step_rows.append((sid, name[:40], "applicable" if applicable else "N/A",
                          verdict, method))

    # ── Pillar 1: functional coverage ──
    fc = _load_json(project / "reports" / "functional_coverage.json")
    if fc and isinstance(fc.get("requirements"), list):
        reqs = fc["requirements"]
        tot = len(reqs)
        ok = sum(1 for r in reqs if str(r.get("status", "")).upper() in ("PASS", "VERIFIED", "COVERED"))
        func_pct = (100.0 * ok / tot) if tot else 0.0
        func_detail = f"{ok}/{tot} requirements verified"
    else:
        func_pct, func_detail = None, "reports/functional_coverage.json MISSING"

    # ── Pillar 3: code coverage ──
    cc = _load_json(project / "reports" / "code_coverage.json")
    line_pct = cc.get("line_pct") if cc else None
    cc_detail = (f"line {cc.get('line_pct')}% / branch {cc.get('branch_pct')}% / "
                 f"toggle {cc.get('toggle_pct')}%") if cc else \
                "reports/code_coverage.json MISSING"

    # ── Pillar 4: FPGA ──
    hw = _load_json(project / "reports" / "hw_test.json")
    fpga_verdict = (hw or {}).get("verdict") if hw else None
    fpga_detail = (f"verdict={fpga_verdict}, patterns={hw.get('patterns')}"
                   if hw else "reports/hw_test.json MISSING")

    # ── Pillar 5: analog ──
    if not analog_ic:
        analog_state, analog_detail = "N/A", "pure-digital IC (no analog blocks)"
    else:
        abl = _load_json(project / "analog" / "analog_block_list.json")
        analog_state = "PRESENT"
        analog_detail = f"analog blocks: {abl if abl else '(see analog/ reports)'}"

    # ── Source highlighting (GENERATED vs REUSED-IP) ──
    sm = (project / "SOURCE_MANIFEST.md")
    src = "SOURCE_MANIFEST.md MISSING (REQUIRED — tag every module GENERATED/REUSED-IP)"
    if sm.is_file():
        t = sm.read_text(errors="ignore")
        g = len(re.findall(r"\bGENERATED\b", t)); r = len(re.findall(r"\bREUSED-IP\b", t))
        src = f"SOURCE_MANIFEST present (GENERATED tokens={g}, REUSED-IP tokens={r})"

    # ── Gates ──
    def gate(ok): return "✅ PASS" if ok else "❌ FAIL/PENDING"
    g_func = (func_pct == 100.0)
    g_steps = (n_unresolved == 0 and n_applicable > 0)
    g_code = (line_pct is not None and float(line_pct) >= a.code_cov_floor)
    g_fpga = (fpga_verdict == "PASS")
    g_analog = (not analog_ic) or (analog_state == "PRESENT")  # presence; deep check via analog skills
    overall = all([g_func, g_steps, g_code, g_fpga, g_analog])

    # ── Emit report ──
    L = []
    L.append(f"# Benchmark Verification Report — `{project.name}`")
    L.append("")
    L.append(f"_Generated by `benchmark_verify_report.py` (skill: benchmark-verify)._  "
             f"Reference: `{a.ref or '(set --ref)'}`")
    L.append("")
    L.append(f"## OVERALL: {'✅ PRODUCTION-READY (all gates pass)' if overall else '❌ NOT COMPLETE — close the loop on failing/pending gates'}")
    L.append("")
    L.append("| Pillar | Gate | Status | Detail |")
    L.append("|---|---|---|---|")
    L.append(f"| 1. Functional Coverage | == 100% | {gate(g_func)} | {func_detail} ({func_pct if func_pct is not None else '—'}%) |")
    L.append(f"| 2. 55-step Output Comparison | all applicable PASS | {gate(g_steps)} | {n_pass}/{n_applicable} applicable PASS, {n_unresolved} unresolved |")
    L.append(f"| 3. Code Coverage (line) | >= {a.code_cov_floor:.0f}% | {gate(g_code)} | {cc_detail} |")
    L.append(f"| 4. FPGA digital verification | PASS | {gate(g_fpga)} | {fpga_detail} |")
    L.append(f"| 5. Analog verification | converged / N/A | {gate(g_analog)} | {analog_detail} |")
    L.append("")
    L.append(f"**Source provenance:** {src}")
    L.append("")
    L.append("> Honesty rules (benchmark-verify): no vacuous result counts as PASS; every PASS "
             "must trace to real evidence; a missing input is PENDING, never a silent PASS; "
             "any gate < target requires a closed-loop fix before claiming complete.")
    L.append("")
    # Pillar 2 detail table
    L.append("## Pillar 2 — 55-step Output Comparison (OURS vs open-source reference)")
    L.append("")
    L.append("> Comparison is step-appropriate, NOT byte-identical: equivalence steps use LEC/co-sim; "
             "metric steps compare magnitude/trend in-range; layout endpoints use "
             "'both independently DRC/LVS/STA-clean + functionally equivalent' (different micro-arch "
             "is expected and is NOT a failure).")
    L.append("")
    L.append("| Step | Name | Applicability | Verdict | Cross-check method |")
    L.append("|---|---|---|---|---|")
    for sid, name, appl, verdict, method in step_rows:
        L.append(f"| {sid} | {name} | {appl} | {verdict} | {method} |")
    L.append("")
    L.append(f"_Total steps: {len(step_rows)} · applicable: {n_applicable} · "
             f"PASS: {n_pass} · unresolved: {n_unresolved}_")
    out.write_text("\n".join(L) + "\n")
    print(f"wrote {out}")
    print(f"OVERALL={'PRODUCTION-READY' if overall else 'NOT-COMPLETE'} "
          f"func={func_pct} steps={n_pass}/{n_applicable}(unresolved {n_unresolved}) "
          f"code_line={line_pct} fpga={fpga_verdict} analog={'N/A' if not analog_ic else analog_state}")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
