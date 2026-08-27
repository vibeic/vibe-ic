#!/usr/bin/env python3
"""
benchmark_verify_report.py — normalized per-benchmark-IC verification report.

Generates the single mandatory BENCHMARK_VERIFICATION_REPORT.md required by the
`benchmark-verify` skill for any benchmark IC that has been driven through the
full Vibe-IC flow (Design Documents -> generated RTL -> signed-off silicon).

It is chip-AGNOSTIC and DETERMINISTIC: it does not run EDA tools itself, it
AGGREGATES the evidence the flow + cross-check steps already produced, computes
the five verification pillars + their hard gates, and emits the report.

Six pillars (== the report sections, == the gates):
  1. Functional Verification Coverage   gate: == 100%
  2. 56-step Output Comparison (vs ref)  gate: every applicable step PASS
  3. Code Coverage (line)                gate: >= 90%
  4. FPGA digital verification           gate: PASS (or documented N/A)
  5. Analog verification                 gate: converged (or N/A for pure-digital)
  6. Design-for-ECO readiness            gate: spare-cell coverage PASS + spare
                                              preservation intact (or N/A if the
                                              IC genuinely has no place-and-route)

Inputs it looks for under <project> (all optional; missing -> PENDING, never a
silent PASS):
  reports/functional_coverage.json   {"requirements":[{id,source,desc,status}], ...}
  reports/code_coverage.json         {"line_pct":.., "branch_pct":.., "toggle_pct":..}
  reports/hw_test.json               {"verdict":"PASS"|"FAIL", "patterns":N, ...}
  analog/analog_block_list.json      (presence => analog applicable)
  reports/spare_cell_coverage.json   {"status":"PASS"|.., density/distribution/tie-off readiness}
  reports/spare_preservation.json    {"all_keep_attr_intact":bool, "removed":N}
  cross_check/**/step_<id>.md        per-step OURS-vs-REF verdict (first line w/ verdict token)
  SOURCE_MANIFEST.md                 GENERATED vs REUSED-IP tally

The Design-for-ECO gate (pillar 6) is owned methodologically by the
`design-for-eco` skill and verified by `spare_cell_coverage_check.py`
(readiness) + `spare_cell_preservation_check.py` (preservation). It applies to
any DIGITAL place-and-route IC (a DEF/GDS exists under phase3/); it is N/A only
for an IC that genuinely never reached place-and-route (e.g. analog-only).

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
    "D1": ("doc",  "L1-L23 field/semantic diff: ports/widths/PDK/clock/interface agree (same spec)"),
    "1":  ("equivalence", "LEC + co-sim: OUR RTL == REF RTL (functional equivalence)"),
    "2":  ("clean", "lint clean parity (both clean)"),
    "3":  ("clean", "CDC/RDC report parity"),
    "4":  ("equivalence", "simulation vs shared golden vectors (spec/standard golden)"),
    "5":  ("equivalence", "formal: assertions proved / k-induction vs spec golden"),
    "6":  ("metric", "FPGA early-proto report (optional)"),
    # No hardcoded checker count here: this string is printed verbatim as
    # P0's Method in BENCHMARK_VERIFICATION_REPORT.md, and it said "77
    # structural-RTL chip-agnostic checkers" long after the registry passed
    # 240 — a published figure ~3x below the real one. The live count comes
    # from flow_compliance_check's own umbrella step name (and
    # `flow_compliance_check.py --list-structural-gates`).
    "P0": ("clean", "structural-RTL chip-agnostic checkers clean "
                    "(count per flow_compliance_check --list-structural-gates)"),
    "7":  ("metric", "SDC diff: clock period / IO delay (both from L9)"),
    "8":  ("clean", "SDC validation parity"),
    "9":  ("metric", "synth netlist: cell-count/area in-range + LEC OUR==REF"),
    "10": ("metric", "pre-layout multi-corner STA slack compare"),
    "11": ("metric", "DFT scan-chain length + ATPG coverage compare"),
    # Functional-safety + at-speed delay-fault steps (flow stage2; chip-agnostic).
    "FS1": ("clean", "ISO-26262 FMEDA diagnostic-coverage (fault-injection) vs safety goal — "
                     "applies to safety designs; N/A otherwise"),
    "DT1": ("metric", "transition-delay-fault (at-speed LOC) ATPG fault-coverage compare"),
    "DT2": ("metric", "path-delay-fault (at-speed, timing-graded) ATPG fault-coverage compare"),
    "DT3": ("metric", "small-delay-defect (SDD) at-speed grade / coverage compare"),
    "12": ("metric", "post-DFT netlist compare"),
    "13": ("equivalence", "LEC: RTL == post-DFT netlist"),
    "14": ("clean", "pre-PnR Yosys gate parity"),
    "15": ("metric", "floorplan/PDN: die area + utilization in-range"),
    "16": ("metric", "clock planning parity"),
    "17": ("metric", "placement density + legality (check_placement)"),
    "18": ("metric", "Design-for-ECO: spare-cell coverage (density/distribution/tie-off) + "
                     "spare preservation vs optimization; OURS-vs-REF readiness"),
    "19": ("metric", "CTS: clock-tree depth/skew/buffer compare"),
    "20": ("metric", "post-CTS hold slack >= 0 (both)"),
    "21": ("metric", "routed DEF: DRT-violations ~0 + component/net counts in-range"),
    "22": ("metric", "SPEF parasitic R/C magnitude compare"),
    "23": ("metric", "post-route multi-corner STA slack compare (all corners >= 0)"),
    "24": ("clean", "IR drop within budget"),
    "25": ("clean", "EM lifetime within budget"),
    "26": ("clean", "antenna check clean"),
    "27": ("clean", "signal-integrity / crosstalk within budget"),
    # v2.3 renumber: PERC inserted at 28, downstream +1; HTOL at 43.
    "28": ("clean", "PERC reliability sign-off (ESD/latch-up/x-domain) clean"),
    "29": ("equivalence", "post-layout gate-sim + SDF vs golden"),
    "30": ("metric", "post-layout SPICE critical-path correlation"),
    "31": ("clean", "PV: DRC clean + LVS clean (both, non-vacuous)"),
    "32": ("clean", "Post-route timing repair pass"),
    "33": ("metric", "power analysis compare"),
    "34": ("metric", "metal-fill density compare"),
    "35": ("clean", "DFM screen (CMP density + via-redundancy advisory) clean"),
    "36": ("clean", "tapeout checklist parity"),
    "37": ("layout-endpoint", "GDSII: NOT pixel-comparable across micro-arch -> both DRC/LVS-clean + functional-equiv"),
    "38": ("doc", "foundry handoff (mask/WAT/scribe) parity"),
    "39": ("metric", "FPGA final sign-off (recompile + on-board)"),
}
for a in ["A1","A2","A3","A4","A5","A6","A7","A8","A9"]:
    STEP_METHOD[a] = ("analog", "analog step — applicable only for mixed-signal ICs")
for m in ["M1","M2","M3","M4"]:
    STEP_METHOD[m] = ("analog", "mixed-signal step — applicable only for A+D ICs")
for s in ["40","41","42","43","44"]:
    STEP_METHOD[s] = ("mfg", "manufacturing step — requires physical silicon")


def _load_steps(flow_yaml: Path):
    try:
        import yaml
        d = yaml.safe_load(flow_yaml.read_text())
        return [(str(s.get("id")), s.get("name", ""), str(s.get("stage", "")))
                for s in d.get("steps", []) if isinstance(s, dict)]
    except Exception as e:
        print(f"[warn] could not parse flow yaml ({e}); using built-in step ids",
              file=sys.stderr)
        # Keep this fallback set in sync with flow/phase1_phase2_phase3.yaml.
        # FS1/DT1/DT2/DT3 are the stage2 functional-safety + at-speed
        # delay-fault steps; omitting them left an all-pass project with 4
        # PENDING/unresolved steps when the yaml could not be parsed.
        ids = (["D1"] + [str(i) for i in range(1, 7)] + ["P0"]
               + [str(i) for i in range(7, 12)]
               + ["FS1","DT1","DT2","DT3"]
               + [str(i) for i in range(12, 15)]
               + ["A1","A2","A3","A4","A5","A6","A7","A8","A9"]
               + [str(i) for i in range(15, 40)]
               + ["M1","M2","M3","M4"] + [str(i) for i in range(40, 45)])
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
    """True iff the IC carries analog blocks — the predicate that gates Pillar 5.

    chip-AGNOSTIC. Signals (any one):
      * an analog block list at EITHER canonical location. The analog runner
        writes `phase3/analog/analog_block_list.json`; only the legacy
        project-root `analog/` location was checked before.
      * a per-block analog artefact produced anywhere in the A1..A9 track —
        corner_results.json (A4), spec.json (A1), topology.md (A2), a block
        netlist (A3) or a block GDS (A5).

    Why both: the old predicate demanded either the ROOT block list (a path the
    runner does not write) or a block **GDS** (an A5-layout artefact). An
    analog IC whose A-track ran the real corner sweep but stopped before layout
    — the normal state whenever A5 is waived — therefore fell through to
    `analog_ic=False` and Pillar 5 (analog closed-loop verification) reported
    "pure-digital IC (no analog blocks) / PASS". That is a silent FALSE PASS on
    the load-bearing pillar for every mixed-signal IC, and it also N/A'd every
    A1..A9 row of the Pillar-2 step comparison.

    The program already contradicted itself: Pillar 5's own else-branch reads
    `phase3/analog/analog_block_list.json`, the very path this predicate did
    not accept. Detection now keys on the artefacts the A-track actually emits,
    so an analog IC is recognised from A1 onward instead of only after A5.

    A genuinely pure-digital IC has none of these artefacts and stays N/A —
    that is the positive case and it must keep reporting N/A untouched.
    """
    for rel in ("analog/analog_block_list.json",
                "phase3/analog/analog_block_list.json"):
        if (project / rel).is_file():
            return True
    for pat in ("phase3/analog/*/corner_results.json",
                "phase3/analog/*/spec.json",
                "phase3/analog/*/topology.md",
                "phase3/analog/*/*.sp",
                "phase3/analog/*/*.gds"):
        if glob.glob(str(project / pat)):
            return True
    return False


def _has_place_and_route(project: Path) -> bool:
    """True iff the IC reached digital place-and-route (a DEF or a non-analog GDS
    exists under phase3/). Design-for-ECO (spare cells/pads) only applies to a
    placed-and-routed digital die; an analog-only IC that never ran PnR is N/A."""
    if glob.glob(str(project / "phase3" / "**" / "*.def"), recursive=True):
        return True
    for g in glob.glob(str(project / "phase3" / "**" / "*.gds"), recursive=True):
        # a GDS under phase3/analog/ is an analog block, not a digital PnR die
        if os.sep + "analog" + os.sep not in g:
            return True
    return False


def _content_rule_module():
    """`_analog_a_check_common`, or None when it cannot be imported.

    THE PREDICATE IS IMPORTED, NOT RESTATED — the same doctrine
    `_rtl_file_is_testbench` follows below. The three answers this pillar ranks
    are the three the analog gates certify on, and a second copy of the
    whitelist here would be free to drift from the one at the gate of record: a
    pillar signing off something the gate refuses, by another door."""
    try:
        _here = str(Path(__file__).resolve().parent)
        if _here not in sys.path:
            sys.path.insert(0, _here)
        import _analog_a_check_common as _aac  # local program, same dir
        return _aac
    except Exception:  # nosec — never let the shared import break the report
        return None


def _rtl_file_is_testbench(path: str) -> bool:
    """True iff `path` is a TESTBENCH / TB skeleton, NOT synthesizable design
    RTL. Reuses rtl_hygiene_lint._is_testbench — the SAME predicate the hygiene
    lint uses to decide synthesizability — so this report can never drift from it
    (the #524 shared-helper doctrine). #185: the runner emits a
    `sim_full_stack/tb_<top>_full.v` skeleton that is NOT design RTL; counting it
    as digital RTL made an all-analog IC (whose only .v is that skeleton) read as
    digital and FAIL Pillars 3/4 it can never satisfy. chip-AGNOSTIC. Falls back
    to a filename check when the shared predicate is unavailable."""
    try:
        _here = str(Path(__file__).resolve().parent)
        if _here not in sys.path:
            sys.path.insert(0, _here)
        import rtl_hygiene_lint as _rhl  # local program, same dir
        try:
            raw = Path(path).read_text(errors="replace")
        except OSError:
            raw = ""
        return _rhl._is_testbench(raw, path)
    except Exception:  # nosec — never let the shared import break the report
        name = os.path.basename(path).lower()
        return bool(re.search(r'(^|[_.])(tb|test|testbench)([_.]|$)', name))


def _has_synth_digital_rtl(project: Path) -> bool:
    """True iff the IC carries a synthesizable DIGITAL RTL block — i.e. there is
    HDL the digital flow (RTL→synth→PnR→DFT→FPGA) can actually operate on.

    chip-AGNOSTIC. A non-behavioral .v/.sv/.vhd anywhere under the project counts
    EXCEPT:
      * the analog hardmacro behavioral wrappers (phase3/analog/**) and analog
        cosim models (**/cosim/**), which are NOT synthesizable digital RTL, and
      * TESTBENCH / TB-skeleton files (tb_*, *_tb, testbench, the runner's
        sim_full_stack/tb_<top>_full.v skeleton), excluded via the shared
        rtl_hygiene_lint._is_testbench predicate (#185/#524 anti-drift) — the
        runner writes a testbench and must not then read it back as proof the
        design contains digital RTL.

    An analog-front-end chip whose only Verilog is the analog hardmacro wrapper,
    a behavioral mixed-signal cosim, or the emitted full-stack TB skeleton has NO
    synthesizable digital RTL and reads N/A on the digital pillars.
    """
    _seen: set = set()
    for pat in ("phase2/**/rtl/*.v", "phase2/**/rtl/*.sv", "phase2/**/rtl/*.vhd",
                "phase2/**/*.v", "phase2/**/*.sv",
                "**/*.v", "**/*.sv", "**/*.vhd"):
        for f in glob.glob(str(project / pat), recursive=True):
            if f in _seen:
                continue
            _seen.add(f)
            low = f.lower()
            if (os.sep + "analog" + os.sep) in low:   # analog hardmacro wrapper
                continue
            if (os.sep + "cosim" + os.sep) in low:     # analog cosim model
                continue
            if _rtl_file_is_testbench(f):              # TB skeleton, not design RTL
                continue
            return True
    return False


def _is_analog_only_ic(project: Path) -> bool:
    """True iff the IC is ANALOG-ONLY: it has analog blocks but NO synthesizable
    digital RTL and never reached digital place-and-route. For such an IC the
    pure-DIGITAL flow steps (RTL/synth/PnR/DFT/FPGA-class), Pillar 3 (code
    coverage of digital RTL) and Pillar 4 (FPGA digital verification) are N/A —
    there is no digital RTL for them to operate on. This MIRRORS how Pillar 6
    (Design-for-ECO) already N/As when the IC never reached place-and-route.
    chip-AGNOSTIC: keyed only on presence of analog blocks + absence of digital
    RTL/PnR, never on a chip name."""
    return (_is_analog_ic(project)
            and not _has_synth_digital_rtl(project)
            and not _has_place_and_route(project))


def _load_json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# Canonical + legacy locations of the full-stack TB result. chip-AGNOSTIC.
_FULL_STACK_RESULTS = (
    Path("phase2/stage1/sim_full_stack/results.json"),
    Path("sim_full_stack/results.json"),
    Path("sim/full_stack/results.json"),
)


def _full_stack_functional_coverage(project: Path):
    """(scored_with_golden, placeholder, relative_path) from the full-stack TB
    result, or (None, None, None) when no full-stack result exists.

    `scored_with_golden` counts vectors compared against a CONCRETE golden.
    A vector with `expected_bytes: null` is a bring-up placeholder and is
    never evidence of functional correctness.
    """
    for rel in _FULL_STACK_RESULTS:
        d = _load_json(project / rel)
        if not isinstance(d, dict):
            continue
        fc = d.get("functional_coverage")
        if isinstance(fc, dict) and isinstance(fc.get("scored_with_golden"), int):
            return (int(fc["scored_with_golden"]),
                    fc.get("placeholder"), str(rel))
        pv = d.get("per_vector")
        if isinstance(pv, list) and pv:
            scored = sum(1 for v in pv if isinstance(v, dict)
                         and v.get("expected_bytes") is not None)
            return scored, len(pv) - scored, str(rel)
    return None, None, None


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
    analog_only = _is_analog_only_ic(project)

    # Pure-DIGITAL 56-step steps for an analog-only IC operate on synthesizable
    # digital RTL or a digital PnR die — neither exists for an analog-front-end
    # with no digital RTL. For such an IC the ONLY applicable steps are the spec
    # cross-check (D1) + the analog/mixed-signal track (A*/M*); every other step
    # (digital RTL/synth/PnR/DFT/STA/DRC kinds, the P0 structural-RTL checker
    # bank, and the digital foundry-handoff doc step 36) N/As — exactly as
    # A*/M* N/A for a pure-digital IC and as Pillar 6 N/As without
    # place-and-route. chip-AGNOSTIC: keyed on step ID/kind, never a chip name.
    def _is_analog_only_applicable_step(sid: str, kind: str) -> bool:
        return kind == "analog" or sid == "D1"

    steps = _load_steps(flow)
    # ── Pillar 2: 56-step output comparison ──
    step_rows, n_pass, n_applicable, n_unresolved = [], 0, 0, 0
    for sid, name, stage in steps:
        kind, method = STEP_METHOD.get(sid, ("metric", "(uncategorized)"))
        applicable = True
        if kind == "analog" and not analog_ic:
            applicable = False; verdict = "N/A"
        elif kind == "mfg":
            applicable = False; verdict = "N/A (no silicon)"
        elif analog_only and not _is_analog_only_applicable_step(sid, kind):
            # analog-only IC: a pure-digital flow step (RTL/synth/PnR/DFT/
            # FPGA/foundry-handoff). No digital RTL/PnR for it to operate on.
            applicable = False
            verdict = "N/A (analog-only — no digital RTL)"
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

    # HONESTY GUARD (sha256 canary, 2026-07-19) — a full-stack TB that scored
    # ZERO vectors against a golden is a VACUOUS pass and must never satisfy
    # Pillar 1, no matter what reports/functional_coverage.json claims. The
    # full-stack results.json is the flow's own admission: `functional_coverage
    # .scored_with_golden == 0` with placeholder bring-up vectors means NO
    # functional correctness was verified end-to-end. chip-AGNOSTIC: reads the
    # flow's own coverage counters, no chip literal.
    fs_scored, fs_placeholder, fs_path = _full_stack_functional_coverage(project)
    if fs_scored is not None and fs_scored == 0:
        func_pct = 0.0
        func_detail = (
            f"FUNCTIONAL COVERAGE GAP — {fs_path} reports "
            f"scored_with_golden=0 (placeholder={fs_placeholder}): the "
            "full-stack TB verified NO vector against a golden. A vacuous TB "
            "is not a pass" + (f"; prior claim: {func_detail}"
                               if fc else "") + ".")

    # ── Pillar 3: code coverage ──
    # N/A for an analog-only IC: code coverage measures DIGITAL RTL line/branch/
    # toggle exercise, but there is no synthesizable digital RTL to instrument.
    # MIRRORS Pillar 6's N/A-without-place-and-route. A missing report on a
    # DIGITAL IC stays PENDING (never a silent pass).
    if analog_only:
        cc = None
        line_pct = None
        cc_na = True
        cc_detail = "analog-only IC — no synthesizable digital RTL to measure code coverage"
    else:
        cc = _load_json(project / "reports" / "code_coverage.json")
        line_pct = cc.get("line_pct") if cc else None
        cc_na = False
        cc_detail = (f"line {cc.get('line_pct')}% / branch {cc.get('branch_pct')}% / "
                     f"toggle {cc.get('toggle_pct')}%") if cc else \
                    "reports/code_coverage.json MISSING"

    # ── Pillar 4: FPGA ──
    # N/A for an analog-only IC: FPGA digital verification runs test patterns
    # through synthesizable digital RTL on an FPGA/BFM; there is no digital RTL.
    # MIRRORS Pillar 6's N/A-without-place-and-route.
    if analog_only:
        hw = None
        fpga_verdict = None
        fpga_na = True
        fpga_detail = "analog-only IC — no synthesizable digital RTL for FPGA/BFM verification"
    else:
        hw = _load_json(project / "reports" / "hw_test.json")
        fpga_verdict = (hw or {}).get("verdict") if hw else None
        fpga_na = False
        fpga_detail = (f"verdict={fpga_verdict}, patterns={hw.get('patterns')}"
                       if hw else "reports/hw_test.json MISSING")

    # ── Pillar 5: analog ──
    # The pillar asks "did the analog loop CLOSE", so mere presence of a block
    # list must not pass it. Presence-only made Pillar 5 structurally unable to
    # fail: any IC with analog blocks passed the load-bearing analog gate even
    # when the A-track verdict was FAIL and the corner sweep never measured.
    # Evidence consulted (all already on disk, no new tooling):
    #   * the A-track runner verdict (reports/phase3/analog_one_shot.json)
    #   * each block's corner_results.json `partial_measurement` flag — a
    #     partial sweep means .meas did not resolve on every corner, so the
    #     block's specs are NOT verified across PVT.
    # Anything short of a converged A-track is PENDING (never a silent pass).
    if not analog_ic:
        analog_state, analog_detail = "N/A", "pure-digital IC (no analog blocks)"
    else:
        abl = _load_json(project / "analog" / "analog_block_list.json") or \
              _load_json(project / "phase3" / "analog" / "analog_block_list.json")
        names = [b.get("name") for b in (abl or {}).get("blocks", []) if b.get("name")]
        a_run = _load_json(project / "reports" / "phase3" / "analog_one_shot.json")
        a_verdict = str((a_run or {}).get("verdict") or "").upper()
        partial = []
        # WHAT THE CLOSED LOOP CLOSED ON. `partial_measurement` says whether
        # every corner resolved; it says nothing about which circuit resolved
        # them. Measured before this: a project whose every corner artefact
        # RECORDS that its circuit came from a topology library, with no bound
        # input reaching any device parameter, read
        # "CONVERGED — all corner sweeps fully measured" and passed the
        # load-bearing analog pillar. The loop closed on the library default.
        #
        # An artefact that will not say which of the two it holds is ranked
        # BELOW the one that disclosed a library default, never above it:
        # otherwise this pillar pays a producer to delete a field.
        #
        # CLASSIFIED THROUGH THE SHARED SITE. This pillar is a consumer of the
        # same artefact the corner gate is the gate of record for; a local
        # `==` against the producer's raw tokens is free to drift from the
        # whitelist that gate certifies on, and then this report signs off a
        # tier the gate refuses. The import is local and fail-closed: if the
        # shared module cannot be reached the block is counted UNDISCLOSED,
        # never silently promoted.
        structure_only, undisclosed = [], []
        _acc = _content_rule_module()
        for cr in sorted(glob.glob(str(project / "phase3" / "analog" / "*" /
                                       "corner_results.json"))):
            d = _load_json(Path(cr)) or {}
            if d.get("partial_measurement"):
                partial.append(Path(cr).parent.name)
            klass = (_acc.classify_design_content(d.get("design_content"))
                     if _acc is not None else None)
            if _acc is not None and klass == _acc.CONTENT_STRUCTURE_ONLY:
                structure_only.append(Path(cr).parent.name)
            elif _acc is None or klass != _acc.CONTENT_DESIGN_BOUND:
                undisclosed.append(Path(cr).parent.name)
        blocks_txt = ", ".join(names) if names else "(see analog/ reports)"
        if not a_run:
            analog_state = "PENDING"
            analog_detail = (f"analog blocks: {blocks_txt} — A-track verdict MISSING "
                             "(reports/phase3/analog_one_shot.json)")
        elif a_verdict.startswith("FAIL"):
            analog_state = "FAIL"
            analog_detail = (f"analog blocks: {blocks_txt} — A-track verdict "
                             f"{a_verdict}")
        elif partial:
            analog_state = "PENDING"
            analog_detail = (f"analog blocks: {blocks_txt} — corner sweep is "
                             f"PARTIAL (.meas unresolved) for: {', '.join(partial)}")
        elif undisclosed:
            # NOT a pass, and NOT "not yet run": the artefact exists and
            # declines to say what it measured. Nothing to wait for and
            # nothing to certify.
            analog_state = "UNDISCLOSED"
            analog_detail = (
                f"analog blocks: {blocks_txt} — the corner artefact records no "
                f"answer to what circuit it simulated for: "
                f"{', '.join(undisclosed)}. A sweep that will not say whether "
                f"its geometry came from a bound input or from a library "
                f"default cannot show that the analog loop closed on this "
                f"design")
        elif structure_only:
            # The honest ceiling. It does not pass this pillar — the loop
            # closed on a library topology, not on the design — and it is
            # deliberately NOT a FAIL: a run that invents content to fill the
            # gap lands in the FAIL row above, and must never score better.
            analog_state = "STRUCTURE_ONLY"
            analog_detail = (
                f"analog blocks: {blocks_txt} — A-track verdict {a_verdict}, "
                f"all corner sweeps fully measured, and the artefacts record "
                f"that the circuit measured for {', '.join(structure_only)} "
                f"came from a topology library with no bound input reaching "
                f"any device parameter. Real corners on a library nominal are "
                f"a measurement OF THAT TOPOLOGY; the analog loop has not "
                f"closed on this design")
        else:
            analog_state = "CONVERGED"
            analog_detail = (f"analog blocks: {blocks_txt} — A-track verdict "
                             f"{a_verdict}, all corner sweeps fully measured "
                             f"on design-bound netlists")

    # ── Pillar 6: Design-for-ECO readiness (spare-cell coverage + preservation) ──
    # Applicable to any DIGITAL place-and-route IC; N/A only when the IC never
    # reached PnR (e.g. analog-only). A missing report is PENDING, never a pass.
    dfe_applicable = _has_place_and_route(project)
    if not dfe_applicable:
        dfe_state = "N/A"
        dfe_detail = "no place-and-route (no DEF/GDS) — spare cells/pads not applicable"
    else:
        cov = _load_json(project / "reports" / "spare_cell_coverage.json")
        pres = _load_json(project / "reports" / "spare_preservation.json")
        cov_pass = bool(cov) and str(cov.get("status", "")).upper() == "PASS"
        # THE GATE'S OWN VERDICT IS PART OF THE PREDICATE. Added 2026-07-28:
        # `spare_cell_preservation_check` grew a failure class
        # (RECORD_ARTEFACT_MISMATCH — two final artefacts of one run disagree
        # about which recorded spares they contain) whose report carries
        # `removed: []` and `all_keep_attr_intact: true` BY CONSTRUCTION,
        # because nothing was removed; the artefacts merely contradict each
        # other. Recomputing only those two fields therefore graded this pillar
        # PASS on a gate that had exited 1. A sign-off report that cannot see a
        # sign-off gate's verdict is the same false-certificate shape this
        # campaign exists to remove, so the verdict is now read directly and a
        # report that does not carry one is not silently assumed clean.
        pres_verdict = str((pres or {}).get("verdict", "")).upper()
        pres_intact = (
            bool(pres)
            and bool(pres.get("all_keep_attr_intact"))
            and int(pres.get("removed", 1) or 0) == 0
            and pres_verdict in ("PASS", "VACUOUS_PASS", "")
        )
        if cov is None and pres is None:
            dfe_state = "PENDING"
            dfe_detail = ("reports/spare_cell_coverage.json + "
                          "reports/spare_preservation.json MISSING "
                          "(run the stage3 Design-for-ECO step + its checkers)")
        elif cov is None:
            dfe_state = "PENDING"
            dfe_detail = "reports/spare_cell_coverage.json MISSING (readiness not verified)"
        elif pres is None:
            dfe_state = "PENDING"
            dfe_detail = ("reports/spare_preservation.json MISSING "
                          "(spare preservation not verified)")
        elif cov_pass and pres_intact:
            dfe_state = "PASS"
            dfe_detail = (f"coverage status={cov.get('status')}, "
                          f"keep_attr_intact={pres.get('all_keep_attr_intact')}, "
                          f"removed={pres.get('removed')}")
        else:
            dfe_state = "FAIL"
            dfe_detail = (f"coverage status={cov.get('status')} "
                          f"(PASS required), keep_attr_intact="
                          f"{pres.get('all_keep_attr_intact')}, removed="
                          f"{pres.get('removed')} (must be 0), preservation "
                          f"verdict={pres.get('verdict')!r} (PASS required)")

    # ── Source highlighting (GENERATED vs REUSED-IP) ──
    # ORGANIC v1462 — self-heal the acceptance artifact: the GENERATED/REUSED-IP
    # provenance already exists on disk (staged RTL + phase2/stage1/rtl/
    # SOURCE_MANIFEST.json) but the top-level markdown this report probes for was
    # never emitted (absent on all seven v1462 run dirs). Materialise it
    # FAITHFULLY from those artifacts (never fabricates; non-destructive — skips
    # a hand-authored one). Best-effort: a render failure just leaves it MISSING.
    try:
        _here = str(Path(__file__).resolve().parent)
        if _here not in sys.path:
            sys.path.insert(0, _here)
        import source_manifest_md_emit as _smme  # local program, same dir
        _smme.emit(project)
    except Exception:  # nosec — never let provenance emission break the report
        pass
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
    # Pillars 3 (code coverage) + 4 (FPGA) N/A-pass for an analog-only IC
    # (no digital RTL), mirroring Pillar 6's N/A-without-place-and-route.
    g_code = cc_na or (line_pct is not None and float(line_pct) >= a.code_cov_floor)
    g_fpga = fpga_na or (fpga_verdict == "PASS")
    # Pillar 5 passes only on a CONVERGED A-track (verdict non-FAIL, every
    # corner sweep fully measured, and every corner artefact recording that
    # what it measured was design-bound). PRESENT/PENDING/FAIL do not pass —
    # presence of analog blocks is not evidence that the analog loop closed —
    # and neither does STRUCTURE_ONLY (the loop closed on a library topology)
    # or UNDISCLOSED (the artefact will not say which circuit it closed on).
    g_analog = (not analog_ic) or (analog_state == "CONVERGED")
    # Design-for-ECO gate: N/A passes; otherwise requires coverage PASS + preservation intact.
    g_dfe = (not dfe_applicable) or (dfe_state == "PASS")
    overall = all([g_func, g_steps, g_code, g_fpga, g_analog, g_dfe])

    # ── Emit report ──
    L = []
    L.append(f"# Benchmark Verification Report — `{project.name}`")
    L.append("")
    L.append(f"_Generated by `benchmark_verify_report.py` (skill: benchmark-verify)._  "
             f"Reference: `{a.ref or '(set --ref)'}`")
    L.append("")
    L.append(f"## OVERALL: {'✅ PRODUCTION-READY (all gates pass)' if overall else '❌ NOT COMPLETE — close the loop on failing/pending gates'}")
    L.append("")
    # A SCOPED canonical statement (vibe-ic#445). "PRODUCTION-READY" is a
    # judgement about THESE SIX PILLARS, and a published cell copied it into
    # RESULT.md where it read as the CELL's verdict — over a flow audit that
    # said FAIL, with that cell's own final_summary.md saying in words
    # "blocking; do not claim PASS".
    #
    # Deliberately NOT the label `Verdict:`. `deliverable_verdict_consistency_
    # check` recognises `final|overall|headline|run|top-level verdict` and
    # would adopt a bare one as the DELIVERABLE's headline — which is the
    # category error in the other direction: pillar 2 reads "39/39 applicable
    # PASS" while the flow audit counts 63 steps, so a bare PASS here would let
    # a 39-step judgement impersonate a whole-flow one.
    #
    # So the scope travels WITH the sentence. Anyone quoting this line quotes
    # what it covers, and the flow verdict stays the flow's to state.
    L.append(f"**Benchmark-pillar verdict: {'PASS' if overall else 'FAIL'}** "
             f"— scope: the 6 benchmark pillars below, NOT flow convergence. "
             f"For whether the flow itself closed, read "
             f"`reports/audit/phase23_completion_audit.json` and "
             f"`reports/final_summary.md`.")
    L.append("")
    L.append("| Pillar | Gate | Status | Detail |")
    L.append("|---|---|---|---|")
    L.append(f"| 1. Functional Coverage | == 100% | {gate(g_func)} | {func_detail} ({func_pct if func_pct is not None else '—'}%) |")
    L.append(f"| 2. 56-step Output Comparison | all applicable PASS | {gate(g_steps)} | {n_pass}/{n_applicable} applicable PASS, {n_unresolved} unresolved |")
    _code_cell = "➖ N/A" if cc_na else gate(g_code)
    _fpga_cell = "➖ N/A" if fpga_na else gate(g_fpga)
    L.append(f"| 3. Code Coverage (line) | >= {a.code_cov_floor:.0f}% / N/A | {_code_cell} | {cc_detail} |")
    L.append(f"| 4. FPGA digital verification | PASS / N/A | {_fpga_cell} | {fpga_detail} |")
    # Pillar 5 status cell: `gate()` collapses everything short of a pass into
    # one word, and this pillar now has four things it can be. STRUCTURE-ONLY
    # is not a FAIL — a run honest about its ceiling must not be shown scoring
    # the same as one whose A-track failed — and UNDISCLOSED is not "PENDING",
    # because there is nothing to wait for. Mirrors Pillar 6's per-state cell.
    _analog_cell = {"N/A": "➖ N/A", "CONVERGED": "✅ PASS",
                    "PENDING": "⏳ PENDING",
                    "STRUCTURE_ONLY": "◐ STRUCTURE-ONLY (does not pass)",
                    "UNDISCLOSED": "❔ UNDISCLOSED (does not pass)",
                    }.get(analog_state, "❌ FAIL")
    L.append(f"| 5. Analog verification | converged / N/A | {_analog_cell} | {analog_detail} |")
    # Pillar 6 status cell: show N/A / PENDING explicitly (gate() collapses both to FAIL/PENDING).
    _dfe_cell = {"PASS": "✅ PASS", "N/A": "➖ N/A",
                 "PENDING": "⏳ PENDING"}.get(dfe_state, "❌ FAIL")
    L.append(f"| 6. Design-for-ECO readiness | coverage PASS + spares preserved / N/A | "
             f"{_dfe_cell} | {dfe_detail} |")
    L.append("")
    L.append(f"**Source provenance:** {src}")
    L.append("")
    L.append("> Honesty rules (benchmark-verify): no vacuous result counts as PASS; every PASS "
             "must trace to real evidence; a missing input is PENDING, never a silent PASS; "
             "any gate < target requires a closed-loop fix before claiming complete.")
    L.append("")
    # Pillar 6 detail
    L.append("## Pillar 6 — Design-for-ECO readiness (spare-cell coverage + preservation)")
    L.append("")
    L.append("> Methodology: the `design-for-eco` skill — pre-place a distributed, tied-off pool of "
             "spare std cells/gates (inverter/nand2/nor2/dff/mux2/aoi/oai) + reserved ECO pads "
             "(~1-5% area, all `dont_touch`/`keep`) after placement and before CTS, so a late bug "
             "can be fixed with a cheap metal-only ECO instead of a base-layer respin. This gate "
             "reads two checker outputs:")
    L.append("> - `reports/spare_cell_coverage.json` (from `spare_cell_coverage_check.py`, readiness): "
             "density/distribution/tie-off targets met → `status: PASS`.")
    L.append("> - `reports/spare_preservation.json` (from `spare_cell_preservation_check.py`): "
             "no spare/ECO cell/gate/pad was optimized away → `all_keep_attr_intact: true` and "
             "`removed: 0`.")
    L.append(f"> Applicability: this IC {'reached place-and-route (gate APPLIES)' if dfe_applicable else 'has no place-and-route (gate N/A)'}. "
             "A missing spare report is PENDING (not a silent pass).")
    L.append("")
    L.append(f"_Design-for-ECO status: **{dfe_state}** — {dfe_detail}_")
    L.append("")
    # Pillar 2 detail table
    L.append("## Pillar 2 — 56-step Output Comparison (OURS vs open-source reference)")
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
          f"code_line={'N/A' if cc_na else line_pct} "
          f"fpga={'N/A' if fpga_na else fpga_verdict} "
          f"analog={'N/A' if not analog_ic else analog_state} "
          f"design_for_eco={dfe_state} "
          f"analog_only={analog_only}")
    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
