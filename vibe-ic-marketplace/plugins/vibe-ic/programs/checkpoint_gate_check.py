#!/usr/bin/env python3
"""checkpoint_gate_check.py — deterministic phase-transition checkpoint gate.

╔══════════════════════════════════════════════════════════════════════════╗
║ ROTTED — DO NOT WIRE. SUPERSEDED BY THE PER-STEP GATE SET. (vibe-ic#693)  ║
╚══════════════════════════════════════════════════════════════════════════╝

This program runs without crashing, but it addresses a DIRECTORY LAYOUT THE
FLOW ABANDONED. It is recorded in
`programs/checker_execution_wiring_baseline.json :: unwired_by_decision`,
where `checker_execution_wiring_audit` re-derives the claim on every CI run.

MEASURED over the 46 run trees on a working checkout: **46/46 FAIL at checkpoint 1, 46/46
at checkpoint 2, 46/46 at checkpoint 3.** 100%, and every red is path rot, not
a defect. On one real DRC-clean Phase-3 run — a run whose DRC evidence is 9050
measured shapes in the layout it consumed:

  CP1  8 MISSING of 9. `phase1_spec/01_prompt.md` … `05_appnote.md` do not
       exist; the run uses `phase1/generated_docs/`. Only `l_layer_docs` PASSes.
  CP2  5 MISSING + 1 FAIL of 12, including TWO ACTIVE MIS-READS:
         [PASS] file:rtl → phase2/stage1/formal/formal_spm.sv
                the RTL glob resolved to the FORMAL file — a false MATCH, not
                merely a false miss;
         [FAIL] cell_count: 0 cell(s) (need > 0)
                on a run that placed real cells.
  CP3  6 MISSING of 8 (Quartus artefacts an ASIC run never produces).

There is also no insertion point: `grep -c checkpoint` over
`flow/phase1_phase2_phase3.yaml` is **0** — the flow has no checkpoint concept,
only per-step gates.

WHAT ALREADY COVERS ITS SUBSTANCE
  CP1 L-doc presence        → `phase1_doc_presence_check` (the one sub-check
                              here that passes)
  CP2 synth / DEF / GDS/DRC → flow steps 14 / 16 / 31 / 37
                              (`gds_substance_check`, `drc_report_check`,
                              `provenance_check`)
  CP3 FPGA sign-off         → step 37 + the FPGA cap-gap waiver machinery

Wiring it in ANY form — blocking or reporting — is an outage that trains
readers to ignore it. The repair is to rewrite the checklist against the
current layout, or delete the program. Not to wire it.

Codifies the manual battery of presence + threshold checks that the
`checkpoint-gate` skill (skills/checkpoint-gate/SKILL.md) used to ask the
agent to run by hand. Running them by hand is non-deterministic: a fresh
agent may forget a file, eyeball a score, or apply the wrong threshold.
This program runs the SAME checklist + the SAME fixed thresholds every
time and emits a single JSON verdict.

Chip-AGNOSTIC: the required files are addressed by GLOB (`*.sv`,
`*_formal.sv`, `*.def`, `*.gds`, ...) and the project root is supplied on
the CLI. No benchmark/chip-specific path or SKU is hard-coded.

Three checkpoints (mirrors SKILL.md exactly):

  Checkpoint 1 — Phase 1 → Phase 2 (Spec → Design)
    required files: phase1_spec/01_prompt.md .. 05_appnote.md + generated_docs/
    thresholds:
        ds_quality_check.py  total_score >= 70
        an_validator.py      total_score >= 56
        spec_validator.py    summary.errors == 0   (0 ERROR-level mismatches)
    plus: phase1_doc_presence_check.py must PASS (all 10 L-layer docs)

  Checkpoint 2 — Phase 2 → Phase 3 (Design → Verify)
    required files: rtl/<m>.sv, rtl/<m>_formal.sv, synth/synth.log,
        synth/synth_<m>.v, pnr/<m>.def, gds/<m>.gds,
        signoff/drc_report.rpt, schematic/<m>_schematic.md
    thresholds:
        synth_doctor.py  status != FAIL
        cell_count       > 0
        SVA assertions   >= 8   (in *_formal.sv)
        DRC violations   <= 5   (in drc_report.rpt, only if present)

  Checkpoint 3 — Phase 3 → Production (FPGA sign-off)
    required files: fpga/*.qpf .qsf .sdc *_top.sv compile.log *.sof
        fit.summary sta.summary
    thresholds:
        *.sof file present AND non-zero size

GRACEFUL DEGRADATION (no false alerts):
  * A required file that is absent is reported `status=MISSING` (not a
    crash and not silently passed).
  * An optional scorer tool (ds_quality_check.py / an_validator.py /
    spec_validator.py / synth_doctor.py — these live in the repo-root
    tools/ dir, OUTSIDE the plugin) that cannot be located, or whose
    invocation errors, is reported `status=MISSING-SCORER` with a clear
    note. We never fabricate a score and never crash. When the scorer
    is unavailable the threshold check is reported MISSING, never FAIL.
  * SVA counting and DRC counting use a structural / length-floor guard
    so an empty or unreadable file degrades to MISSING, never a spurious
    FAIL.

Overall verdict:
  PASS  — every required-file present AND every applicable threshold met
          AND no MISSING items.
  FAIL  — at least one required file MISSING or a threshold violated.
  (MISSING-SCORER alone does NOT flip a PASS to FAIL — it is reported as
   an `incomplete` warning so a human/agent knows the scorer must be run
   on a machine that has the repo-root tools/ dir.)

Usage:
    python3 checkpoint_gate_check.py <project_dir> --checkpoint {1|2|3}
    python3 checkpoint_gate_check.py <project_dir> --checkpoint 1 --json
    python3 checkpoint_gate_check.py <project_dir> --checkpoint 2 --json-out r.json

Exit codes:
    0  PASS
    1  FAIL (required file MISSING or threshold violated)
    2  usage / I/O error (e.g. project dir not found)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Fixed thresholds — copied VERBATIM from skills/checkpoint-gate/SKILL.md.
# Do not invent new numbers here; these are the documented gate values.
# ---------------------------------------------------------------------------
DS_SCORE_MIN = 70        # ds_quality_check.py total_score >= 70
AN_SCORE_MIN = 56        # an_validator.py total_score >= 56
SPEC_MAX_ERRORS = 0      # spec_validator.py 0 ERROR-level mismatches
SVA_MIN = 8              # >= 8 assert property in *_formal.sv
DRC_MAX = 5              # <= 5 DRC violations in drc_report.rpt
CELL_MIN = 1             # cell_count > 0  (i.e. >= 1)

# Length floor (bytes) under which a file is treated as empty/unreadable
# for heuristic counting — prevents false FAIL on a stub/empty artifact.
_MIN_CONTENT_BYTES = 4


@dataclass
class Check:
    name: str
    status: str            # PASS | FAIL | MISSING | MISSING-SCORER | SKIP
    detail: str = ""
    value: object = None
    threshold: object = None


@dataclass
class Report:
    checkpoint: int
    verdict: str = "FAIL"          # PASS | FAIL
    checks: List[Check] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _first_glob(project: Path, pattern: str) -> Optional[Path]:
    """Return the first file matching a recursive-ish glob, else None.

    `pattern` is relative to project root and may contain `*`. We search
    both the exact relative pattern and a recursive `**/` fallback so the
    layout (phase2_design/ vs phase2/stage1/ etc.) does not have to match
    a single hard-coded tree.
    """
    matches = sorted(project.glob(pattern))
    if matches:
        return matches[0]
    # recursive fallback on just the basename pattern
    base = pattern.split("/")[-1]
    rec = sorted(project.glob(f"**/{base}"))
    return rec[0] if rec else None


def _file_present_check(project: Path, name: str, pattern: str) -> Check:
    hit = _first_glob(project, pattern)
    if hit is None:
        return Check(name=name, status="MISSING",
                     detail=f"no file matching '{pattern}' under {project}")
    return Check(name=name, status="PASS",
                 detail=str(hit.relative_to(project)))


def _find_repo_tool(toolname: str) -> Optional[Path]:
    """Best-effort locate a repo-root tools/<toolname>.

    The scorers (ds_quality_check / an_validator / spec_validator /
    synth_doctor) ship in the monorepo's top-level tools/ dir, which is
    OUTSIDE the plugin bundle. Walk up from this file looking for a
    sibling `tools/<toolname>`. Returns None if not found — caller then
    reports MISSING-SCORER and does NOT crash.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "tools" / toolname
        if cand.is_file():
            return cand
    return None


def _run_json_tool(tool: Path, extra_args: List[str]) -> Optional[dict]:
    """Run a scorer with --json and parse stdout JSON. None on any failure."""
    try:
        proc = subprocess.run(
            [sys.executable, str(tool), *extra_args, "--json"],
            capture_output=True, text=True, timeout=120,
        )
    except Exception:
        return None
    out = proc.stdout.strip()
    if not out:
        return None
    # Some tools print a banner before JSON; grab the first {...} block.
    start = out.find("{")
    if start < 0:
        return None
    try:
        return json.loads(out[start:])
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    if len(data) < _MIN_CONTENT_BYTES:
        return None
    return data.decode("utf-8", errors="replace")


# Matches `assert property`, `assert(`, `assert (` — the SKILL.md grep.
_SVA_RE = re.compile(r"\bassert\s*(?:property\b|\()", re.IGNORECASE)
# DRC "violation" tokens — kept as a deny-list of the literal word so a
# clean report (0 violations) does not false-flag.
_DRC_RE = re.compile(r"violation", re.IGNORECASE)


def _count_sva(project: Path) -> Check:
    """Count SVA assertions across all *_formal.sv files. >= 8 required."""
    formal_files = sorted(project.glob("**/*_formal.sv"))
    if not formal_files:
        return Check(name="sva_count", status="MISSING", threshold=SVA_MIN,
                     detail="no *_formal.sv file found")
    total = 0
    counted_any = False
    for f in formal_files:
        txt = _read_text(f)
        if txt is None:
            continue
        counted_any = True
        total += len(_SVA_RE.findall(txt))
    if not counted_any:
        return Check(name="sva_count", status="MISSING", threshold=SVA_MIN,
                     detail="*_formal.sv present but empty/unreadable")
    status = "PASS" if total >= SVA_MIN else "FAIL"
    return Check(name="sva_count", status=status, value=total, threshold=SVA_MIN,
                 detail=f"{total} assertion(s) (need >= {SVA_MIN})")


def _count_drc(project: Path) -> Check:
    """Count DRC violations in drc_report.rpt. <= 5 allowed. SKIP if absent."""
    rpt = _first_glob(project, "**/drc_report.rpt")
    if rpt is None:
        # SKILL.md: DRC check only runs "if drc_report.rpt exists".
        return Check(name="drc_violations", status="SKIP", threshold=DRC_MAX,
                     detail="no drc_report.rpt — DRC check not applicable yet")
    txt = _read_text(rpt)
    if txt is None:
        return Check(name="drc_violations", status="MISSING", threshold=DRC_MAX,
                     detail="drc_report.rpt empty/unreadable")
    count = len(_DRC_RE.findall(txt))
    status = "PASS" if count <= DRC_MAX else "FAIL"
    return Check(name="drc_violations", status=status, value=count,
                 threshold=DRC_MAX,
                 detail=f"{count} 'violation' token(s) (max {DRC_MAX})")


# ---------------------------------------------------------------------------
# Checkpoint 1 — Phase 1 → Phase 2
# ---------------------------------------------------------------------------
CP1_FILES = [
    ("prompt",      "phase1_spec/01_prompt.md"),
    ("dialog",      "phase1_spec/02_dialog.md"),
    ("spec",        "phase1_spec/03_spec_confirmed.md"),
    ("datasheet",   "phase1_spec/04_datasheet.md"),
    ("appnote",     "phase1_spec/05_appnote.md"),
]


def checkpoint1(project: Path) -> Report:
    rep = Report(checkpoint=1)
    for name, pat in CP1_FILES:
        rep.checks.append(_file_present_check(project, f"file:{name}", pat))

    # generated_docs presence (delegate to phase1_doc_presence_check.py).
    gen = _first_glob(project, "generated_docs")
    if gen is None:
        gen = project / "generated_docs"
    rep.checks.append(_l_layer_check(gen))

    # Scorer: datasheet quality >= 70
    ds = _first_glob(project, "phase1_spec/04_datasheet.md")
    rep.checks.append(_score_check(
        "ds_quality", "ds_quality_check.py", ds, DS_SCORE_MIN))

    # Scorer: application note >= 56
    an = _first_glob(project, "phase1_spec/05_appnote.md")
    rep.checks.append(_score_check(
        "an_quality", "an_validator.py", an, AN_SCORE_MIN))

    # Scorer: spec cross-consistency 0 ERROR
    rep.checks.append(_spec_validator_check(project, ds, an))

    _finalize(rep)
    return rep


def _l_layer_check(gen_dir: Path) -> Check:
    tool = Path(__file__).resolve().parent / "phase1_doc_presence_check.py"
    if not tool.is_file():
        return Check(name="l_layer_docs", status="MISSING-SCORER",
                     detail="phase1_doc_presence_check.py not alongside")
    if not gen_dir.exists():
        return Check(name="l_layer_docs", status="MISSING",
                     detail=f"generated_docs/ not found ({gen_dir})")
    try:
        proc = subprocess.run(
            [sys.executable, str(tool), str(gen_dir), "--json"],
            capture_output=True, text=True, timeout=120,
        )
        data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except Exception as e:
        return Check(name="l_layer_docs", status="MISSING-SCORER",
                     detail=f"could not run phase1_doc_presence_check.py: {e}")
    passed = bool(data.get("passed"))
    missing = data.get("stats", {}).get("missing_layers", "?")
    return Check(name="l_layer_docs",
                 status="PASS" if passed else "FAIL",
                 value=missing,
                 detail="all 10 L-layer docs present" if passed
                        else f"{missing} L-layer doc(s) missing")


def _score_check(name: str, toolname: str, target: Optional[Path],
                 minimum: int) -> Check:
    if target is None:
        return Check(name=name, status="MISSING", threshold=minimum,
                     detail=f"input file for {toolname} not found")
    tool = _find_repo_tool(toolname)
    if tool is None:
        return Check(name=name, status="MISSING-SCORER", threshold=minimum,
                     detail=f"{toolname} not found in repo-root tools/ "
                            "(scorer ships outside the plugin)")
    data = _run_json_tool(tool, [str(target)])
    if data is None or "total_score" not in data:
        return Check(name=name, status="MISSING-SCORER", threshold=minimum,
                     detail=f"{toolname} produced no parseable JSON score")
    score = data["total_score"]
    status = "PASS" if score >= minimum else "FAIL"
    return Check(name=name, status=status, value=score, threshold=minimum,
                 detail=f"score {score} (need >= {minimum})")


def _spec_validator_check(project: Path, ds: Optional[Path],
                          an: Optional[Path]) -> Check:
    name = "spec_consistency"
    if ds is None or an is None:
        return Check(name=name, status="MISSING", threshold=SPEC_MAX_ERRORS,
                     detail="datasheet and/or appnote missing — cannot cross-check")
    tool = _find_repo_tool("spec_validator.py")
    if tool is None:
        return Check(name=name, status="MISSING-SCORER", threshold=SPEC_MAX_ERRORS,
                     detail="spec_validator.py not found in repo-root tools/")
    spec = _first_glob(project, "phase1_spec/03_spec_confirmed.md")
    args = ["--ds", str(ds), "--an", str(an)]
    if spec is not None:
        args += ["--spec", str(spec)]
    data = _run_json_tool(tool, args)
    if data is None:
        return Check(name=name, status="MISSING-SCORER", threshold=SPEC_MAX_ERRORS,
                     detail="spec_validator.py produced no parseable JSON")
    errors = data.get("summary", {}).get("errors")
    if errors is None:
        errors = 0 if data.get("consistent") else None
    if errors is None:
        return Check(name=name, status="MISSING-SCORER", threshold=SPEC_MAX_ERRORS,
                     detail="spec_validator.py JSON lacked summary.errors")
    status = "PASS" if errors <= SPEC_MAX_ERRORS else "FAIL"
    return Check(name=name, status=status, value=errors, threshold=SPEC_MAX_ERRORS,
                 detail=f"{errors} ERROR-level mismatch(es) (max {SPEC_MAX_ERRORS})")


# ---------------------------------------------------------------------------
# Checkpoint 2 — Phase 2 → Phase 3
# ---------------------------------------------------------------------------
CP2_FILES = [
    ("rtl",        "**/rtl/*.sv"),
    ("formal_sv",  "**/*_formal.sv"),
    ("synth_log",  "**/synth/synth.log"),
    ("netlist",    "**/synth/synth_*.v"),
    ("def",        "**/*.def"),
    ("gds",        "**/*.gds"),
    ("drc_report", "**/drc_report.rpt"),
    ("schematic",  "**/*_schematic.md"),
]


def checkpoint2(project: Path) -> Report:
    rep = Report(checkpoint=2)
    for name, pat in CP2_FILES:
        rep.checks.append(_file_present_check(project, f"file:{name}", pat))

    # synth_doctor: status != FAIL and cell_count > 0 (two checks)
    rep.checks.extend(_synth_doctor_checks(project))

    # SVA >= 8
    rep.checks.append(_count_sva(project))

    # DRC <= 5 (only if drc_report.rpt present; else SKIP)
    rep.checks.append(_count_drc(project))

    _finalize(rep)
    return rep


def _synth_doctor_checks(project: Path) -> List[Check]:
    log = _first_glob(project, "**/synth/synth.log")
    if log is None:
        return [
            Check(name="synth_status", status="MISSING",
                  detail="synth/synth.log not found"),
            Check(name="cell_count", status="MISSING", threshold=CELL_MIN,
                  detail="synth/synth.log not found"),
        ]
    tool = _find_repo_tool("synth_doctor.py")
    if tool is None:
        return [
            Check(name="synth_status", status="MISSING-SCORER",
                  detail="synth_doctor.py not found in repo-root tools/"),
            Check(name="cell_count", status="MISSING-SCORER", threshold=CELL_MIN,
                  detail="synth_doctor.py not found in repo-root tools/"),
        ]
    data = _run_json_tool(tool, [str(log)])
    if data is None:
        return [
            Check(name="synth_status", status="MISSING-SCORER",
                  detail="synth_doctor.py produced no parseable JSON"),
            Check(name="cell_count", status="MISSING-SCORER", threshold=CELL_MIN,
                  detail="synth_doctor.py produced no parseable JSON"),
        ]
    status = str(data.get("status", "UNKNOWN"))
    cells = data.get("cell_count", 0)
    status_check = Check(
        name="synth_status",
        status="PASS" if status != "FAIL" else "FAIL",
        value=status,
        detail=f"synth_doctor status={status} (must != FAIL)")
    try:
        cells_int = int(cells)
    except (TypeError, ValueError):
        cells_int = 0
    cell_check = Check(
        name="cell_count",
        status="PASS" if cells_int >= CELL_MIN else "FAIL",
        value=cells_int, threshold=CELL_MIN,
        detail=f"{cells_int} cell(s) (need > 0)")
    return [status_check, cell_check]


# ---------------------------------------------------------------------------
# Checkpoint 3 — Phase 3 → Production (FPGA sign-off)
# ---------------------------------------------------------------------------
CP3_FILES = [
    ("qpf",         "**/fpga/*.qpf"),
    ("qsf",         "**/fpga/*.qsf"),
    ("sdc",         "**/fpga/*.sdc"),
    ("fpga_top",    "**/fpga/*_top.sv"),
    ("compile_log", "**/fpga/compile.log"),
    ("fit_summary", "**/fpga/fit.summary"),
    ("sta_summary", "**/fpga/sta.summary"),
]


def checkpoint3(project: Path) -> Report:
    rep = Report(checkpoint=3)
    for name, pat in CP3_FILES:
        rep.checks.append(_file_present_check(project, f"file:{name}", pat))

    # SOF present AND non-zero size
    rep.checks.append(_sof_check(project))

    _finalize(rep)
    return rep


def _sof_check(project: Path) -> Check:
    sof = _first_glob(project, "**/fpga/*.sof")
    if sof is None:
        return Check(name="sof_file", status="MISSING",
                     detail="no *.sof file under fpga/")
    try:
        size = sof.stat().st_size
    except OSError as e:
        return Check(name="sof_file", status="MISSING",
                     detail=f"could not stat SOF: {e}")
    status = "PASS" if size > 0 else "FAIL"
    return Check(name="sof_file", status=status, value=size,
                 detail=f"{sof.name} size={size} byte(s) (must be non-zero)")


# ---------------------------------------------------------------------------
# Finalize + verdict
# ---------------------------------------------------------------------------
def _finalize(rep: Report) -> None:
    # Tally per-status and decide the verdict. PASS requires zero FAIL and
    # zero MISSING; MISSING-SCORER and SKIP are reported but do not block.
    n_pass = sum(1 for c in rep.checks if c.status == "PASS")
    n_fail = sum(1 for c in rep.checks if c.status == "FAIL")
    n_missing = sum(1 for c in rep.checks if c.status == "MISSING")
    n_scorer = sum(1 for c in rep.checks if c.status == "MISSING-SCORER")
    n_skip = sum(1 for c in rep.checks if c.status == "SKIP")
    rep.stats = {
        "pass": n_pass, "fail": n_fail, "missing": n_missing,
        "missing_scorer": n_scorer, "skip": n_skip,
        "total": len(rep.checks),
    }
    # PASS requires no FAIL and no MISSING. MISSING-SCORER and SKIP do not
    # block (they are reported but cannot be evaluated on this machine).
    rep.verdict = "PASS" if (n_fail == 0 and n_missing == 0) else "FAIL"
    rep.stats["incomplete"] = (n_scorer > 0)


def run(project: Path, checkpoint: int) -> Report:
    if checkpoint == 1:
        return checkpoint1(project)
    if checkpoint == 2:
        return checkpoint2(project)
    if checkpoint == 3:
        return checkpoint3(project)
    raise ValueError(f"unknown checkpoint {checkpoint} (expected 1, 2 or 3)")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir", help="Path to the design project root")
    ap.add_argument("--checkpoint", type=int, required=True, choices=(1, 2, 3),
                    help="Which phase-transition checkpoint to gate")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON report to stdout")
    ap.add_argument("--json-out", default=None,
                    help="Write JSON report to this path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.exists() or not project.is_dir():
        msg = f"ERROR: project_dir not found or not a directory: {project}"
        if args.json or args.json_out:
            payload = json.dumps(
                {"checkpoint": args.checkpoint, "verdict": "FAIL",
                 "error": msg, "checks": [], "stats": {}}, indent=2)
            if args.json_out:
                Path(args.json_out).write_text(payload + "\n")
            if args.json:
                print(payload)
        else:
            print(msg, file=sys.stderr)
        return 2

    rep = run(project, args.checkpoint)
    payload = json.dumps(
        {"checkpoint": rep.checkpoint, "verdict": rep.verdict,
         "checks": [asdict(c) for c in rep.checks], "stats": rep.stats},
        indent=2)

    if args.json_out:
        Path(args.json_out).write_text(payload + "\n")
    if args.json:
        print(payload)
    elif not args.json_out:
        print(f"Checkpoint {rep.checkpoint} gate — verdict: {rep.verdict}")
        for c in rep.checks:
            line = f"  [{c.status:<14}] {c.name}: {c.detail}"
            print(line)
        s = rep.stats
        print(f"\n  {s['pass']} PASS / {s['fail']} FAIL / {s['missing']} MISSING"
              f" / {s['missing_scorer']} MISSING-SCORER / {s['skip']} SKIP"
              f"  ({s['total']} checks)")
        if s.get("incomplete"):
            print("  NOTE: one or more external scorers were unavailable on this "
                  "machine (MISSING-SCORER). Re-run on a host with the repo-root "
                  "tools/ dir to fully certify those thresholds.")
        if rep.verdict == "PASS":
            print(f"\n  Result: PASS — checkpoint {rep.checkpoint} satisfied.")
        else:
            print(f"\n  Result: FAIL — fix MISSING/FAIL items before the phase "
                  "transition.")

    return 0 if rep.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
