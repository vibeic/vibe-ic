#!/usr/bin/env python3
"""verilator_coverage_measure.py — v0.53 plugin gate

Force machine-measured Verilator coverage instead of agent-estimated numbers.

The v0.52 fresh-agent <half-duplex-tester> PASS was accompanied by a self-reported
"≥ 95 % estimated line coverage". When actually measured with
`verilator --coverage --coverage-line --coverage-toggle`, line coverage
was 78.3 %, toggle 75.5 %, branch 82.3 %. This gate rejects reports that
lack tool-generated coverage artefacts.

Three modes:
  measure    — run Verilator + compile + simulate a C++ driver + parse
               coverage.dat
  measure-tb — INSTRUMENT AND RUN THE PROJECT'S OWN VERILOG TESTBENCH.
               `verilator --binary --timing --coverage --coverage-line
               --coverage-toggle` builds a standalone simulation from the
               same TB the flow simulated, executes it, and the real
               line/toggle/branch points are read out of the coverage.dat
               that run produced. No C++ driver needed, so this is the mode
               a flow can actually wire.
  check      — only verify that a prior run produced coverage.dat +
               a coverage JSON with tool-generated content

ONE PRODUCER PER PATH
=====================
`reports/phase2/coverage/coverage_actual.json` used to be written by TWO
producers: `design_one_shot_runner`, which writes a FUNCTIONAL-verification
verdict payload there (verdict / evidence / verification_track /
scenarios_covered, NO `totals` container), and this program's `measure`,
which writes the line/toggle/branch measurement. A path with two producers
cannot be read: on every real run the functional payload landed there first
and `check` correctly reported that line/toggle/branch was never measured.

The two are now SEPARATE artefacts:

  reports/phase2/coverage/coverage_actual.json     functional verdict
                                                   (design_one_shot_runner)
  reports/phase2/coverage/coverage_verilator.json  the measurement
                                                   (this program)

`COVERAGE_MEASUREMENT_REL` below is the single name for the measurement
path; the Step-4 gate, `coverage_closure` and `fpga_verification_audit`
all read it. Nothing about the checker's standard changed — it still
refuses anything that is not a real tool-generated measurement.

ONE NAMESPACE PER DOCUMENT (#2180)
==================================
This report is composed on the host, stored on the host and read on the host,
so every path in it is a HOST path. Most of them are that by construction:
`coverage_dat`, `testbench` and `rtl_sources` are composed here from inputs
this program was handed.

`per_file`'s keys — and therefore `scope_files`, which is derived from them —
are the ONLY values that come from somewhere else: they are the source files
VERILATOR named, in the namespace Verilator ran in. When the flow dispatches
the instrumented build into the pinned image, that namespace is the
CONTAINER's, and writing it verbatim produced one document carrying two
namespaces with nothing in it saying which field was which:

    rtl_sources  ["<project>/phase2/stage1/rtl/<top>.v"]              host
    scope_files  ["/foss/designs/<project>/phase2/stage1/rtl/<top>.v"] container

Same bytes, two spellings, three keys apart. `_cov_project_root` below reads
both keys to locate the project, and `project_outputs_in_tree_check` blocks on
the container half — correctly, because on the machine the report is read on
that file does not exist.

So tool-reported paths are normalised at INGEST, in `parse_coverage_dat`,
before anything persists them, using the container's own mount table through
`_designs_root.host_spelling` — the module that already owns the forward
translation, so there is no second answer to a question the repo has answered
once. `path_namespace` in the payload states what happened, including the two
cases that are NOT a translation: a path with no host spelling at all (an
image-internal source, a PDK cell) is left in the tool's namespace and NAMED,
and a run that declared no container is recorded as not examined rather than
as a document full of host paths.

SCOPE — the DESIGN, not the testbench
=====================================
A testbench is driven top to bottom by construction, so folding its points
into the totals only dilutes them upward. `measure-tb` totals the points of
the RTL SOURCES ONLY (`--scope-file`, defaulted to the DUT sources handed to
Verilator) and records the per-file breakdown for everything, testbench
included, so the exclusion is visible rather than assumed.

Usage:
    # Measure from scratch (assumes RTL under ./rtl and main driver under
    # sim/cov_build/main.cpp — see your project's conventions)
    python3 verilator_coverage_measure.py measure \\
        --rtl-dir rtl \\
        --top example_top \\
        --main sim/cov_build/main.cpp \\
        --out reports/coverage/coverage_actual.json

    # Measure by instrumenting the project's OWN Verilog testbench
    python3 verilator_coverage_measure.py measure-tb \\
        --project . \\
        --out reports/phase2/coverage/coverage_verilator.json

    # Check-only mode (no rebuild, verify stored artefact)
    python3 verilator_coverage_measure.py check \\
        --coverage-json reports/phase2/coverage/coverage_verilator.json \\
        --min-line 70 --min-toggle 60 --min-branch 70

Exit code (`measure`):
    0 — all thresholds met
    1 — threshold(s) below target

Exit code (`check`) — COVERAGE-CREDIT SPLIT of the two meanings that used to
share exit 2. `flow_compliance_check._check_program_exit_zero` maps rc=2 onto
VACUOUS_PASS ("the input this gate audits does not apply to this project"),
and VACUOUS_PASS was counted into `pass_count`. So every rc=2 this program
returned bought the enclosing step PASS credit — including for an artefact
that EXISTS at the declared coverage path but carries no coverage in it.
An artefact under the coverage path with no `totals.*` is a MISLABELLED
artefact, not an inapplicable input.
(State AS MEASURED THEN. `flow_compliance_check` has since dropped
VACUOUS_PASS from the executed-PASS numerator — the tier leaves X and stays
in Y — so an rc=2 no longer buys PASS credit. The split below is unaffected:
a mislabelled artefact must be rc=1 whatever the tier above it counts, and
this program's own rc=2 was the mechanism by which step 4 was measured
VACUOUS_PASS on the host that found the numerator defect.)

    0 — a real measurement is present and every threshold is met
    1 — a DEFECT: below threshold, OR the artefact at the declared path is
        corrupt / mislabelled / forged, OR no measurement exists on a host
        where the Verilator toolchain that would have taken it IS installed
    3 — a DISCLOSED capability gap (printed with the `PASS_WITH_WAIVERS`
        stdout sentinel `_check_program_exit_zero` requires): no coverage
        measurement AND no Verilator on PATH to have taken one. The step
        resolves to WAIVED-DEFERRED — reviewable, review_required, and
        REMOVED from the executed-PASS numerator — instead of silently
        counting as a pass.

    rc=2 is no longer emitted by `check`. Other programs that legitimately
    use the input-missing convention (foundry_handoff_package_check,
    mixed_signal_merge_check) are untouched: the semantics change is local
    to this program, not to `_check_program_exit_zero`.

Generality: works for any Verilator-compatible RTL. Threshold defaults are
conservative; tighten per project maturity.
"""
from __future__ import annotations
import argparse
import ast
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ----- measurement --------------------------------------------------


def run(cmd: List[str], cwd: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def verilate_and_run(rtl_dir: str, top: str, main_cpp: str, build_dir: str) -> str:
    """Verilate + make + execute to produce coverage.dat. Returns path to .dat."""
    rtl_files = sorted(
        [str(p) for p in Path(rtl_dir).glob("*.v")]
        + [str(p) for p in Path(rtl_dir).glob("*.sv")]
    )
    if not rtl_files:
        raise SystemExit(f"No .v/.sv under {rtl_dir}")

    Path(build_dir).mkdir(parents=True, exist_ok=True)

    # verilate
    # `-I<rtl_dir>` is required so RTL with `include "params.vh"` etc.
    # can find its headers. Without it, projects that split params/
    # types out of the main .v fail to elaborate (regression caught by
    # B3 v0.55.1 verilator-bugs analysis on phase2+3_v050_smoke).
    vcmd = [
        "verilator",
        "--cc",
        "--exe",
        "--build",
        "--coverage",
        "--coverage-line",
        "--coverage-toggle",
        "--coverage-user",
        f"-I{rtl_dir}",
        "--top-module",
        top,
        "-Mdir",
        build_dir,
        main_cpp,
    ] + rtl_files
    r = run(vcmd, check=False)
    if r.returncode != 0:
        raise SystemExit(f"verilator failed:\nSTDERR:\n{r.stderr}\nSTDOUT:\n{r.stdout}")

    # Execute
    exe = Path(build_dir) / f"V{top}"
    if not exe.exists():
        raise SystemExit(f"compiled executable not found: {exe}")
    r = run([str(exe)], cwd=build_dir, check=False)
    if r.returncode != 0:
        # run may intentionally exit non-zero; coverage.dat can still be valid
        sys.stderr.write(
            f"[warn] simulator exit={r.returncode}; continuing if coverage.dat present\n"
        )

    dat = Path(build_dir) / "coverage.dat"
    if not dat.exists():
        # Try Verilator's default location
        dat = Path(build_dir) / "logs" / "coverage.dat"
    if not dat.exists():
        raise SystemExit(f"coverage.dat not produced under {build_dir}")
    return str(dat)


#: Canonical relative path of the MEASUREMENT artefact this program produces,
#: under the project's reports root. Kept as one name so the Step-4 gate,
#: `coverage_closure` and `fpga_verification_audit` cannot drift apart, and so
#: it can never again collide with the functional-verdict payload
#: `design_one_shot_runner` writes to `coverage/coverage_actual.json`.
COVERAGE_MEASUREMENT_REL = "coverage/coverage_verilator.json"

#: Verilator flags that turn instrumentation ON. Named once: an argv that
#: lacks them produces a coverage.dat with no line/toggle/branch points, which
#: is exactly the "measured nothing" state this program exists to refuse.
COVERAGE_INSTRUMENTATION_FLAGS = (
    "--coverage", "--coverage-line", "--coverage-toggle",
)


def _tb_top_module(tb_path: Path) -> str:
    """Top module name of a Verilog testbench: the first `module <name>`.

    Falls back to the file stem, which is the convention every TB the flow
    generates already follows (`tb_<top>_oracle.v` holds `tb_<top>_oracle`).
    """
    try:
        text = tb_path.read_text(errors="replace")
    except OSError:
        return tb_path.stem
    m = re.search(r"^\s*module\s+([A-Za-z_][A-Za-z0-9_$]*)", text, re.M)
    return m.group(1) if m else tb_path.stem


def verilate_tb_and_run(rtl_files: List[str], tb_path: str, build_dir: str,
                        run_dir: str,
                        exec_fn=None, build_jobs: int = 0) -> str:
    """Instrument + build + RUN the project's own Verilog testbench.

    `verilator --binary --timing` builds a standalone simulation executable
    straight from the TB's `initial`/`always` blocks — no C++ driver — so the
    SAME testbench the flow simulated is what gets instrumented. The three
    `COVERAGE_INSTRUMENTATION_FLAGS` are what make the run emit coverage
    points at all.

    `exec_fn(argv, cwd) -> (rc, stdout, stderr)` lets a caller dispatch the
    two commands somewhere else (e.g. into the pinned tool container) while
    the discovery, parsing and thresholding stay here. Default: run locally.

    Returns the path of the coverage.dat the RUN produced. Raises SystemExit
    when Verilator, the build or the simulation did not produce one — an
    absent measurement is reported as absent, never substituted.
    """
    if exec_fn is None:
        def exec_fn(argv, cwd):  # noqa: ANN001 — local default
            r = run(argv, cwd=cwd, check=False)
            return r.returncode, r.stdout, r.stderr

    if not rtl_files:
        raise SystemExit("no RTL sources to instrument")
    tb = Path(tb_path)
    if tb.suffix == ".py":
        return verilate_professional_tb_and_run(
            rtl_files, tb, Path(build_dir), Path(run_dir),
            exec_fn=exec_fn, build_jobs=build_jobs)
    if not tb.is_file():
        raise SystemExit(f"testbench not found: {tb_path}")
    top = _tb_top_module(tb)
    Path(build_dir).mkdir(parents=True, exist_ok=True)
    Path(run_dir).mkdir(parents=True, exist_ok=True)

    # INCLUDE PATH — the TB's directory AND every directory the RTL comes
    # from. Passing a file to the compiler does not make its own directory
    # searchable for that file's `` `include ``s.
    #
    # MEASURED (opentitan_aes, v1.15.80): the coverage build died with
    #   %Error: .../rtl/lc_ctrl_pkg.sv:6:10: Cannot find include file:
    #           'prim_assert.sv'
    #   ... Looked in: .../sim_full_stack/  .../sim/cov_build/  (and bare names)
    # while `prim_assert.sv` was staged RIGHT THERE in .../phase2/stage1/rtl/
    # next to the file including it. Only `-I{tb.parent}` was passed, so the
    # one directory guaranteed to hold the sources' own headers was the one
    # directory never searched. coverage_verilator.json was therefore not
    # produced, and the two checks that read it went rc=2 EXECUTION_ERROR —
    # a resource failure reported as if the design had no coverage.
    #
    # Order-stable and de-duplicated: the TB dir keeps its historical first
    # position, and a project whose TB and RTL share a directory still gets a
    # single `-I`. chip-AGNOSTIC: directory arithmetic only.
    _inc_dirs = []
    for _d in [tb.parent] + [Path(f).parent for f in rtl_files]:
        if _d not in _inc_dirs:
            _inc_dirs.append(_d)
    vcmd = ["verilator", "--binary", "--timing",
            *COVERAGE_INSTRUMENTATION_FLAGS,
            "-Wno-fatal", "-Wno-lint",
            *[f"-I{d}" for d in _inc_dirs],
            "--top-module", top,
            "-Mdir", str(build_dir)]
    if build_jobs > 0:
        vcmd += ["--build-jobs", str(build_jobs)]
    # Parse package declarations before the testbench that imports them.
    vcmd += [str(f) for f in rtl_files] + [str(tb)]
    rc, out, err = exec_fn(vcmd, run_dir)
    if rc != 0:
        raise SystemExit(
            f"verilator coverage build failed (rc={rc}):\nSTDERR:\n{err}\n"
            f"STDOUT:\n{out}")

    exe = Path(build_dir) / f"V{top}"
    rc, out, err = exec_fn([str(exe)], run_dir)
    if rc != 0:
        # A TB may $finish non-zero; coverage.dat can still be valid, so this
        # is a warning, not a substitution.
        sys.stderr.write(
            f"[warn] simulation exit={rc}; continuing if coverage.dat present\n")

    for cand in (Path(run_dir) / "coverage.dat",
                 Path(build_dir) / "coverage.dat",
                 Path(build_dir) / "logs" / "coverage.dat"):
        if cand.is_file():
            return str(cand)
    raise SystemExit(
        f"no coverage.dat produced by the instrumented run under {run_dir} "
        f"— the simulation did not emit coverage points")


def _professional_bundle(tb: Path) -> Dict[str, Any]:
    """Resolve the existing professional generator contract; never infer a top.

    These refusals are BLOCKING for this measurement. An unfilled hook is not
    coverage stimulus, and a disconnected Python file is not a simulator bundle.
    """
    try:
        plan = json.loads((tb.parent / "verification_plan.json").read_text())
    except (OSError, ValueError) as exc:
        raise SystemExit(f"PROFESSIONAL_COVERAGE_PLAN_INVALID: {tb}: {exc}")
    tiers = {"expert_reference": "expert_filled",
             "serial_stream": "streaming_bounded_latency",
             "parallel_arith": "closed_form"}
    top = plan.get("top") if isinstance(plan, dict) else None
    if (not isinstance(top, str) or not re.fullmatch(r"[A-Za-z_]\w*", top)
            or tb.name != f"tb_{top}.py"
            or plan.get("reference_model_tier") != tiers.get(plan.get("dut_kind"))
            or plan.get("dut_kind") not in tiers):
        raise SystemExit(f"PROFESSIONAL_COVERAGE_PLAN_INCOMPLETE: {tb}")
    if not tb.is_file():
        raise SystemExit(f"PROFESSIONAL_COVERAGE_TB_ABSENT: {tb}")
    if plan["dut_kind"] == "expert_reference":
        import professional_tb_gen as _ptg  # noqa: PLC0415
        source = _ptg._load_expert_reference_tb(tb.parent)
        if source is None or source != tb.read_text(errors="replace"):
            raise SystemExit(f"PROFESSIONAL_COVERAGE_HOOK_UNFILLED_OR_STALE: {tb}")
    return plan


def verilate_professional_tb_and_run(
        rtl_files: List[str], tb: Path, build: Path, run_dir: Path, *,
        exec_fn, build_jobs: int = 0) -> str:
    """Instrument the SAME cocotb module generated and simulated at Step 4.

    The build/run directory is distinct from the Icarus bundle: its JUnit and
    coverage.dat are this execution's evidence. Missing, failed, skipped or
    zero-test JUnit refuses coverage, even when a .dat was written on shutdown.
    No functional-coverage bins or instruction counts are inferred here.
    """
    plan = _professional_bundle(tb)
    audit = functional_stimulus_audit(tb)
    if not audit["decidable"] or not audit["driven"]:
        raise SystemExit(f"PROFESSIONAL_COVERAGE_NO_FUNCTIONAL_STIMULUS: {tb}: "
                         f"{audit['reason'] or audit['inert']}")
    build.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    # Every attempt owns fresh files. Retain earlier JUnit, raw coverage,
    # logs, execution records and builds, including a failed rerun.
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    attempt = Path(tempfile.mkdtemp(prefix=f'attempt_{stamp}_', dir=run_dir))
    build = build / attempt.name / 'build'
    build.mkdir(parents=True, exist_ok=True)
    run_dir = attempt
    # All sources are the caller's RTL closure, not a second Makefile selector.
    # Paths in the generated file are relative to the consumer cwd so the same
    # file works under host and container bind-mount spellings.
    import os  # noqa: PLC0415
    rel = lambda p: os.path.relpath(str(p), str(run_dir))
    sources = " \\\n\t".join(rel(p) for p in rtl_files)
    flags = " ".join(COVERAGE_INSTRUMENTATION_FLAGS)
    includes = " ".join(dict.fromkeys(rel(Path(p).parent) for p in rtl_files))
    makefile = run_dir / "coverage_cocotb.mk"
    makefile.write_text(
        "SIM = verilator\nTOPLEVEL_LANG = verilog\n"
        f"VERILOG_SOURCES = $(abspath {sources})\n"
        f"TOPLEVEL = {plan['top']}\nMODULE = {tb.stem}\n"
        f"VERILOG_INCLUDE_DIRS = $(abspath {includes})\n"
        f"COMPILE_ARGS += --timing {flags} -Wno-fatal -Wno-lint\n"
        f"SIM_BUILD = {rel(build / 'obj_dir')}\n"
        f"CUSTOM_COMPILE_DEPS += {makefile.name}\n"
        "COCOTB_RESULTS_FILE = coverage_results.xml\n"
        f"export PYTHONPATH := $(abspath {rel(tb.parent)}):$(PYTHONPATH)\n"
        "include $(shell cocotb-config --makefiles)/Makefile.sim\n")
    # Only the new attempt's files can satisfy this measurement.
    junit = run_dir / "coverage_results.xml"
    dat = run_dir / "coverage.dat"
    command = ["make", "-f", str(makefile), f"-j{max(1, build_jobs)}"]
    rc, out, err = exec_fn(command, str(run_dir))
    (run_dir / "coverage_cocotb.log").write_text((out or "") + "\n" + (err or ""))
    import _sim_results_bridge as _srb  # noqa: PLC0415
    summary = _srb.parse_junit(junit)
    execution = {
        "testbench": str(tb), "top": plan["top"],
        "reference_model_tier": plan["reference_model_tier"],
        "instrumented_junit": str(junit), "test_denominator": summary,
        "functional_stimulus": audit, "coverage_dat": str(dat),
        "instrumentation_flags": list(COVERAGE_INSTRUMENTATION_FLAGS),
        "exit_code": rc, "measurement_status": "NOT_MEASURED",
    }
    execution_path = run_dir / "coverage_cocotb_execution.json"
    execution_path.write_text(json.dumps(execution, indent=2) + "\n")
    if (rc != 0 or not summary or summary["tests"] <= 0
            or summary["passed"] <= 0 or summary["failures"]
            or summary["errors"] or summary["skipped"]):
        raise SystemExit(f"PROFESSIONAL_COVERAGE_SIMULATION_REFUSED: {tb}: "
                         f"rc={rc}, instrumented_junit={summary}")
    if not dat.is_file():
        raise SystemExit(f"PROFESSIONAL_COVERAGE_DAT_ABSENT: {tb}")
    activity = _professional_input_activity(dat, plan["top"], audit["driven"])
    if not activity:
        raise SystemExit(f"PROFESSIONAL_COVERAGE_INPUT_ACTIVITY_UNOBSERVED: {tb}")
    import hashlib  # noqa: PLC0415
    execution.update({
        "measurement_status": "MEASURED",
        "observed_functional_input_toggles": activity,
        "testbench_sha256": hashlib.sha256(tb.read_bytes()).hexdigest(),
    })
    execution_path.write_text(json.dumps(execution, indent=2) + "\n")
    return str(dat)


def _professional_input_activity(dat: Path, top: str,
                                 inputs: Sequence[str]) -> Dict[str, int]:
    """Actual top-input transitions from this tool-generated v5 coverage data.

    AST assignment is only a dispatch contract. Here the tool must also have
    observed a declared functional input move; initialization to zero or an
    unreachable assignment cannot satisfy that observation. No denominator is
    changed: the original data continues to feed all existing coverage metrics.
    """
    hits = {}
    for raw in dat.read_text(errors="replace").splitlines():
        match = COVERAGE_LINE_RE.match(raw)
        if not match or int(match[2]) <= 0:
            continue
        fields = dict(pair.split("\x02", 1) for pair in match[1].split("\x01")
                      if "\x02" in pair)
        if (fields.get("page") != f"v_toggle/{top}"
                or fields.get("h") not in {top, "TOP", f"TOP.{top}"}):
            continue
        name = re.split(r"\[|:", fields.get("o", ""), 1)[0]
        if name in inputs:
            hits[name] = hits.get(name, 0) + int(match[2])
    return hits


def _check_professional_execution(tb: Path, dat: Path) -> Optional[str]:
    """Consume the instrumented bundle's own JUnit and top-input observations."""
    import hashlib  # noqa: PLC0415
    import _sim_results_bridge as _srb  # noqa: PLC0415
    try:
        plan = _professional_bundle(tb)
        record = json.loads((dat.parent / "coverage_cocotb_execution.json").read_text())
        summary = _srb.parse_junit(dat.parent / "coverage_results.xml")
        if (record.get("testbench") != str(tb)
                or record.get("testbench_sha256") != hashlib.sha256(tb.read_bytes()).hexdigest()
                or not summary or summary["tests"] <= 0 or summary["passed"] <= 0
                or summary["failures"] or summary["errors"] or summary["skipped"]
                or summary != record.get("test_denominator")):
            return "instrumented Python source/JUnit is missing, changed, failed, skipped or zero-test"
        audit = functional_stimulus_audit(tb)
        activity = _professional_input_activity(dat, plan["top"], audit["driven"])
        if not activity or activity != record.get("observed_functional_input_toggles"):
            return "tool data recorded no matching top-level functional-input movement"
    except (SystemExit, OSError, ValueError, TypeError) as exc:
        return str(exc)
    return None


def scope_totals(cov: Dict[str, Any],
                 scope_basenames: List[str]) -> Optional[Dict[str, Any]]:
    """Re-total `cov` over ONLY the named source files.

    A testbench is executed top to bottom by construction, so leaving it in
    the totals reports the testbench's own coverage as if it were the
    design's. Returns None when NONE of the named sources appear in the
    coverage data — that means the instrumented run covered a different
    closure than the one claimed, and the caller must refuse rather than
    report the unscoped number instead.
    """
    wanted = {Path(n).name for n in scope_basenames}
    agg = {"line": [0, 0], "toggle": [0, 0], "branch": [0, 0]}
    matched: List[str] = []
    for src, pf in (cov.get("per_file") or {}).items():
        if Path(src).name not in wanted:
            continue
        matched.append(src)
        for cat in agg:
            entry = pf.get(cat)
            if isinstance(entry, dict):
                agg[cat][0] += int(entry.get("covered", 0))
                agg[cat][1] += int(entry.get("total", 0))
    if not matched:
        return None

    line_points = list(agg['line'])
    line_map = {src: lines for src, lines in (cov.get('line_union') or {}).items()
                if Path(src).name in wanted and lines}
    if line_map:
        agg['line'] = [sum(h > 0 for lines in line_map.values() for h in lines.values()),
                       sum(len(lines) for lines in line_map.values())]

    def pct(pair: List[int]) -> float:
        return round(100.0 * pair[0] / pair[1], 2) if pair[1] > 0 else 0.0

    return {
        "totals": {c: {"covered": agg[c][0], "total": agg[c][1],
                       "pct": pct(agg[c])} for c in agg},
        "scope_files": sorted(matched),
        "line_metric": "executable_line_union" if line_map else "category_points",
        "line_point_totals": {"covered": line_points[0], "total": line_points[1],
                              "pct": pct(line_points)},
    }


# ----- parsing ------------------------------------------------------

# Coverage record format. Both Verilator 4.x and 5.x emit one record per
# line, prefixed `C` (the type) then a single-quoted blob of fields and
# a hit count: `C '<blob>' <hits>`. The blob's structure changed between
# versions:
#
#   v4.x:   `\x02<category>\x01<file>\x01<line>\x01...\x01`
#           — leading `\x02` byte then category as the first segment.
#
#   v5.x:   `<key1>\x02<value1>\x01<key2>\x02<value2>\x01...\x01`
#           — every segment is a `key\x02value` pair. Category is
#             encoded in the `page` field (`v_line/<mod>`,
#             `v_toggle/<mod>`, `v_branch/<mod>`).
#
# We support both. The 5.x branch was added after the B3 coverage gap
# analysis (2026-04-24) found Verilator 5.020's coverage.dat parsed as
# zero points by the prior 4.x-only regex.
# Coverage point metadata can contain apostrophes in Verilog literals (for
# example `32'h1`) inside the quoted payload. The record's closing quote is
# the last one, immediately before the hit count.
COVERAGE_LINE_RE = re.compile(r"^C\s+'(.*)'\s+(\d+)\s*$")

_V5_PAGE_TO_CAT = {"v_line": "line", "v_toggle": "toggle", "v_branch": "branch"}


def _classify_v5(blob: str) -> Optional[str]:
    """Verilator 5.x parser: pull the `page` field and map to a category.
    Returns None when the record isn't a recognised category (e.g.
    Verilator's own metadata records)."""
    fields: Dict[str, str] = {}
    for pair in blob.split("\x01"):
        if "\x02" in pair:
            k, v = pair.split("\x02", 1)
            fields[k] = v
    page = fields.get("page", "")
    head = page.split("/", 1)[0] if "/" in page else page
    return _V5_PAGE_TO_CAT.get(head)


def _classify_v4(blob: str) -> Optional[str]:
    """Verilator 4.x parser: leading byte is `\\x02` then category name
    as the first \\x01-separated segment."""
    parts = blob.split("\x01")
    if not parts:
        return None
    head = parts[0].lstrip("\x02").strip()
    if head in ("line", "toggle", "branch"):
        return head
    return None


def _file_v5(blob: str) -> Optional[str]:
    """Pull the `f` (filename) field from a v5.x record."""
    for pair in blob.split("\x01"):
        if pair.startswith("f\x02"):
            return pair[2:]
    return None


def _file_v4(blob: str) -> Optional[str]:
    """v4.x: file is the second \\x01-separated segment."""
    parts = blob.split("\x01")
    return parts[1] if len(parts) > 1 else None


#: The namespace every path in this program's report is written in. Stated as
#: a value so the payload can carry it and a reader never has to infer it.
REPORT_PATH_NAMESPACE = "host"


def host_path_namespace(
        paths: Sequence[str],
        mounts: Optional[Sequence[Tuple[Path, str]]],
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Map tool-reported paths to the HOST spelling, plus what was done.

    #2180. Verilator answers in the namespace it ran in. When the flow
    dispatches it into the pinned image, every source it names is a CONTAINER
    path, and writing that verbatim into a report composed on the host makes
    one document carry two namespaces with nothing in it saying which field is
    which. MEASURED on this repo's own corpus: `scope_files` held
    `/foss/designs/<project>/…` while `rtl_sources`, three keys away, held the
    host path to the SAME bytes.

    The rule is not "rewrite anything that looks like a container path". It is
    the container's own mount table, read through the ONE module that owns
    host<->container translation (`_designs_root.host_spelling`), so this
    program does not maintain a second answer to a question already answered.

    Returns ``(mapping, disclosure)``. A path with no host spelling is NOT in
    the mapping and IS in ``disclosure['untranslated']``: keeping it in the
    tool's namespace is the honest outcome for a file that has none here (an
    image-internal source, a PDK cell), and naming it is what stops that from
    reading like a host path.
    """
    mapping: Dict[str, str] = {}
    counts = {"already_host": 0, "translated_from_container": 0}
    untranslated: List[str] = []
    collisions: List[List[str]] = []
    if mounts is not None:
        import _designs_root as _dr                    # noqa: PLC0415
        taken: Dict[str, str] = {}
        basis_of: Dict[str, str] = {}
        for src in paths:
            tr = _dr.host_spelling(src, mounts=mounts)
            if tr.path is None:
                untranslated.append(src)
                continue
            if tr.path in taken and taken[tr.path] != src:
                # Two tool-reported paths that would become ONE host path. A
                # silent merge would delete a measured file's row, so both are
                # left in the tool's namespace and the collision is named.
                # The withdrawn one's basis is decremented with it: a
                # disclosure whose counts and `untranslated` do not add up to
                # the paths examined is the same defect this program is
                # fixing, one level down.
                first = taken.pop(tr.path)
                collisions.append(sorted([first, src]))
                mapping.pop(first, None)
                counts[basis_of[first]] -= 1
                untranslated.extend([first, src])
                continue
            taken[tr.path] = src
            mapping[src] = tr.path
            basis_of[src] = tr.basis
            counts[tr.basis] = counts.get(tr.basis, 0) + 1
    disclosure: Dict[str, Any] = {
        "reported_in": REPORT_PATH_NAMESPACE,
        "examined": mounts is not None,
        "mounts_consulted": len(list(mounts or ())),
        **counts,
        "untranslated": sorted(set(untranslated)),
    }
    if mounts is None:
        # NOT "examined and they were all host paths". No caller declared that
        # the tool ran elsewhere, so nothing was compared against anything and
        # the counts above stay at zero rather than being filled with a
        # default. `None` and `[]` are kept apart on purpose: this branch is
        # "the tool ran here", the one below is "it ran over there and I could
        # not read the mount table", and answering the second with the first
        # is how an untranslatable path comes to render as a host path.
        disclosure["note"] = (
            "no container was declared, so the tool-reported paths were "
            "neither examined nor rewritten; the tool ran on this filesystem "
            "and its paths are this machine's")
    elif not mounts:
        disclosure["note"] = (
            "a container was declared and its mount table could not be read, "
            "so no path could be translated; every one below is left in the "
            "TOOL's namespace and named rather than presented as a host path")
    if collisions:
        disclosure["collisions"] = collisions
    return mapping, disclosure


def parse_coverage_dat(
        path: str,
        *,
        mounts: Optional[Sequence[Tuple[Path, str]]] = None,
) -> Dict[str, Any]:
    """Parse Verilator coverage.dat into per-category counts + per-file
    breakdown. Auto-detects 4.x vs 5.x record format on the first
    classifiable record so a single coverage.dat from either version
    works without a flag.

    `mounts` is the container's ``(host source, container destination)`` bind
    mounts when the instrumented run was dispatched into a container. Given
    them, the per-file keys — the only values in this payload that come from
    the TOOL rather than being composed here — are normalised to the host
    spelling before anything persists them (#2180). Omit them and nothing is
    rewritten, which is correct for a run whose Verilator executed here.
    """
    cats = {"line": [0, 0], "toggle": [0, 0], "branch": [0, 0], "other": [0, 0]}
    per_file: Dict[str, Dict[str, List[int]]] = {}
    classifier = None  # set on first successful classification

    with open(path, "r", errors="replace") as f:
        for raw in f:
            m = COVERAGE_LINE_RE.match(raw)
            if not m:
                continue
            blob, hits = m.group(1), int(m.group(2))
            if classifier is None:
                # First classifiable record selects the format.
                head = _classify_v5(blob) or _classify_v4(blob)
                if head is not None:
                    classifier = "v5" if _classify_v5(blob) is not None else "v4"
            if classifier == "v5":
                head = _classify_v5(blob)
                src = _file_v5(blob)
            elif classifier == "v4":
                head = _classify_v4(blob)
                src = _file_v4(blob)
            else:
                head, src = None, None
            if head is None:
                head = "other"
            if head not in cats:
                head = "other"
            cats[head][1] += 1
            if hits > 0:
                cats[head][0] += 1
            if src:
                per_file.setdefault(
                    src, {"line": [0, 0], "toggle": [0, 0], "branch": [0, 0]})
                pf = per_file[src]
                if head in pf:
                    pf[head][1] += 1
                    if hits > 0:
                        pf[head][0] += 1

    host_of, disclosure = host_path_namespace(list(per_file), mounts)
    line_map = union_line_map([path], require_hierarchy=False) or {}
    line_host_of, _ = host_path_namespace(list(line_map), mounts)

    def pct(pair: List[int]) -> float:
        return round(100.0 * pair[0] / pair[1], 2) if pair[1] > 0 else 0.0

    return {
        "totals": {
            "line": {"covered": cats["line"][0], "total": cats["line"][1], "pct": pct(cats["line"])},
            "toggle": {"covered": cats["toggle"][0], "total": cats["toggle"][1], "pct": pct(cats["toggle"])},
            "branch": {"covered": cats["branch"][0], "total": cats["branch"][1], "pct": pct(cats["branch"])},
        },
        "per_file": {
            host_of.get(src, src):
                {k: {"covered": v[0], "total": v[1], "pct": pct(v)}
                 for k, v in pf.items()}
            for src, pf in per_file.items()
        },
        "format_detected": classifier or "unknown",
        "path_namespace": disclosure,
        "line_union": {line_host_of.get(src, src): lines for src, lines in line_map.items()},
    }


#: The one record field that is a property of the TESTBENCH rather than of the
#: design: Verilator writes the instrumented point's INSTANCE PATH here, so the
#: same design point recorded by two different testbenches is two different
#: records. MEASURED (subservient x gf180mcuD, lane icsub2 r18) — the two lines
#: below are byte-identical apart from it:
#:   ...\x01f\x02<rtl>/subservient.v\x01l\x02100\x01t\x02toggle...\x01o\x02c_reg[0]:0->1\x01h\x02blinky_hex.u_dut  17
#:   ...\x01f\x02<rtl>/subservient.v\x01l\x02100\x01t\x02toggle...\x01o\x02c_reg[0]:0->1\x01h\x02rv32i_40.u_dut     46
#: which is why `verilator_coverage --write` over ten testbenches returns a
#: denominator ten times too large: it concatenates where it looks like it
#: merges (measured: line total 1350 against a design with 135 line points).
_COV_HIER_FIELD_RE = re.compile(r"\x01h\x02[^\x01]*")


def coverage_point_key(blob: str) -> Optional[str]:
    """The identity of a coverage POINT, independent of which testbench saw it.

    `None` when this record carries no hierarchy field — then the caller cannot
    know whether two records from two runs are the same point, and MUST NOT
    union them. Returning None rather than the raw blob is the whole safety
    property: a silent fallback would double every denominator.
    """
    if "\x01h\x02" not in blob:
        return None
    return _COV_HIER_FIELD_RE.sub("", blob)


def union_coverage_dats(
        paths: Sequence[str],
        *,
        mounts: Optional[Sequence[Tuple[Path, str]]] = None,
) -> Dict[str, Any]:
    """One measurement over SEVERAL instrumented runs of the same design.

    THE COVERAGE OF A SUITE IS THE UNION OF ITS CASES. A design verified by ten
    testbenches, each exercising one scenario, has ten partial measurements and
    exactly one true one; publishing any single member's number describes that
    member, not the design. MEASURED on subservient: the ten authored L10
    oracles individually span line 63.70%-97.78% and their union is 98.52%,
    while the run published 68.89% — the alphabetically first one — and failed
    a 70% floor with it.

    A point is COVERED when ANY run hit it, and counted ONCE.

    Refuses rather than guesses: when a record carries no hierarchy field the
    union is not derivable, and this returns `unionisable: False` with the file
    that could not be keyed, so the caller falls back to a single measurement
    and SAYS it did. Same payload shape as `parse_coverage_dat`, so every
    existing reader works unchanged.
    """
    hits: Dict[str, int] = {}
    fmt: Optional[str] = None
    for path in paths:
        with open(path, "r", errors="replace") as fh:
            for raw in fh:
                m = COVERAGE_LINE_RE.match(raw)
                if not m:
                    continue
                blob, n = m.group(1), int(m.group(2))
                if fmt is None:
                    if _classify_v5(blob) is not None:
                        fmt = "v5"
                    elif _classify_v4(blob) is not None:
                        fmt = "v4"
                key = coverage_point_key(blob)
                if key is None:
                    return {"unionisable": False, "blocked_by": str(path),
                            "reason": ("a coverage record in this file carries "
                                       "no hierarchy field, so two runs' "
                                       "records cannot be matched to the same "
                                       "point and a union would multiply the "
                                       "denominator by the number of runs")}
                hits[key] = hits.get(key, 0) + n

    cats = {"line": [0, 0], "toggle": [0, 0], "branch": [0, 0], "other": [0, 0]}
    per_file: Dict[str, Dict[str, List[int]]] = {}
    for key, n in hits.items():
        head = (_classify_v5(key) if fmt == "v5" else _classify_v4(key)) or "other"
        if head not in cats:
            head = "other"
        src = _file_v5(key) if fmt == "v5" else _file_v4(key)
        cats[head][1] += 1
        if n > 0:
            cats[head][0] += 1
        if src:
            pf = per_file.setdefault(
                src, {"line": [0, 0], "toggle": [0, 0], "branch": [0, 0]})
            if head in pf:
                pf[head][1] += 1
                if n > 0:
                    pf[head][0] += 1

    host_of, disclosure = host_path_namespace(list(per_file), mounts)
    line_map = union_line_map(paths) or {}
    line_host_of, _ = host_path_namespace(list(line_map), mounts)

    def pct(pair: List[int]) -> float:
        return round(100.0 * pair[0] / pair[1], 2) if pair[1] > 0 else 0.0

    return {
        "unionisable": True,
        "line_union": {line_host_of.get(src, src): lines for src, lines in line_map.items()},
        "runs_unioned": len(list(paths)),
        "distinct_points": len(hits),
        "totals": {c: {"covered": cats[c][0], "total": cats[c][1],
                       "pct": pct(cats[c])}
                   for c in ("line", "toggle", "branch")},
        "per_file": {
            host_of.get(src, src):
                {k: {"covered": v[0], "total": v[1], "pct": pct(v)}
                 for k, v in pf.items()}
            for src, pf in per_file.items()},
        "format_detected": fmt or "unknown",
        "path_namespace": disclosure,
    }


# ----- the tool's own line union (lcov) ---------------------------------

#: THE TOOL ALREADY MERGES LINES ACROSS INSTANCE PATHS; ONLY `--write` DOES
#: NOT. MEASURED in the released image (verilator_coverage 5.053, two TBs that
#: instantiate the same module as `tbA.u_dut` and `tbB.dut_i`):
#: `--write merged.dat` keeps 58 `C` records, twice the 29 of one run, while
#: `--write-info merged.info` writes ONE `DA:<line>,<hits>` per source line of
#: the shared module, keyed by file and line only. So the line-level suite
#: union has a second, independent producer: the tool. Toggle and branch
#: points stay per instance in lcov (`BRDA` rows repeat), so those keep the
#: `h`-stripping union above. The lcov `DA` row is per SOURCE LINE and carries
#: every point type on that line (a port's toggle points sit on the module
#: header line), so the two are compared as the same question: which lines of
#: which file carry a point, and which of them any run hit.
LCOV_INFO_NAME = "coverage_union.info"


def parse_lcov_info(text: str) -> Dict[str, Dict[int, int]]:
    """`{file: {line: hits}}` from `verilator_coverage --write-info` output.

    Only `SF:` / `DA:` / `end_of_record` are read. A `DA` row outside an `SF`
    record is malformed input and raises ValueError, so an unreadable file can
    never be read as an empty (and therefore agreeing) union."""
    out: Dict[str, Dict[int, int]] = {}
    current: Optional[str] = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            current = line[3:]
            out.setdefault(current, {})
        elif line.startswith("DA:"):
            if current is None:
                raise ValueError(f"lcov DA row outside an SF record: {line!r}")
            fields = line[3:].split(",")
            if len(fields) < 2:
                raise ValueError(f"malformed lcov DA row: {line!r}")
            n, hits = int(fields[0]), int(fields[1])
            out[current][n] = max(out[current].get(n, 0), hits)
        elif line == "end_of_record":
            current = None
    return out


def union_line_map(paths: Sequence[str], *, require_hierarchy: bool = True
                   ) -> Optional[Dict[str, Dict[int, int]]]:
    """`{file: {line: hits}}` over every point of the `h`-stripped union.

    The same question lcov answers, asked of this program's own union: every
    point type, keyed by file and line, hit when any run hit any point on it.
    None when a record cannot be keyed (same refusal as `union_coverage_dats`)."""
    hits: Dict[str, Dict[int, int]] = {}
    for path in paths:
        with open(path, "r", errors="replace") as fh:
            for raw in fh:
                m = COVERAGE_LINE_RE.match(raw)
                if not m:
                    continue
                blob, n = m.group(1), int(m.group(2))
                if require_hierarchy and coverage_point_key(blob) is None:
                    return None
                fields = dict(seg.split("\x02", 1) for seg in blob.split("\x01")
                              if "\x02" in seg)
                src, lineno = fields.get("f"), fields.get("l")
                if not src or not (lineno or "").isdigit():
                    continue
                per = hits.setdefault(src, {})
                for one in {int(lineno)} | _span_lines(fields.get("S", "")):
                    per[one] = per.get(one, 0) + n
    return hits


def _span_lines(spec: str) -> set:
    """The lines a point's `S` field names (`5`, `2-4`, `2-4,7`).

    MEASURED: an `else` point recorded at `l=4` carries `S=5`, and lcov writes
    a `DA:5` row for it. Reading only `l` loses that line."""
    lines: set = set()
    for part in (spec or "").split(","):
        lo, _, hi = part.strip().partition("-")
        if lo.isdigit() and (not hi or hi.isdigit()):
            lines.update(range(int(lo), int(hi or lo) + 1))
    return lines


def cross_check_line_union(ours: Optional[Dict[str, Dict[int, int]]],
                           tool: Optional[Dict[str, Dict[int, int]]],
                           scope: Sequence[str]) -> Dict[str, Any]:
    """Compare the two line unions over the DUT files named in `scope`.

    `agree` is True only when both sides name the same scoped files, the same
    lines in each, and the same subset of them hit. A side that is absent is
    NOT_MEASURED, never agreement."""
    import instrument_calibration as _calibration
    try:
        _calibration.assert_calibrated(
            "verilator_coverage_measure::cross_check_line_union")
    except _calibration.Uncalibrated as exc:
        return {"status": "NOT_MEASURED", "reason_class": exc.reason_class,
                "reason": str(exc)}
    if ours is None or tool is None:
        return {"status": "NOT_MEASURED",
                "reason": ("the h-stripped union could not be keyed"
                           if ours is None else
                           "verilator_coverage --write-info produced no "
                           "readable lcov union")}
    wanted = {Path(n).name for n in scope}

    def scoped(side: Dict[str, Dict[int, int]]) -> Dict[str, Dict[int, int]]:
        return {Path(f).name: lines for f, lines in side.items()
                if Path(f).name in wanted}

    a, b = scoped(ours), scoped(tool)
    mismatches: List[Dict[str, Any]] = []
    for name in sorted(set(a) | set(b)):
        la, lb = a.get(name, {}), b.get(name, {})
        if set(la) != set(lb):
            mismatches.append({"file": name, "kind": "line_set",
                               "only_h_stripped_union": sorted(set(la) - set(lb)),
                               "only_lcov": sorted(set(lb) - set(la))})
        hit_a = {n for n, h in la.items() if h > 0}
        hit_b = {n for n, h in lb.items() if h > 0}
        if hit_a != hit_b:
            mismatches.append({"file": name, "kind": "hit_set",
                               "only_h_stripped_union": sorted(hit_a - hit_b),
                               "only_lcov": sorted(hit_b - hit_a)})
    total = sum(len(lines) for lines in b.values())
    covered = sum(1 for lines in b.values() for h in lines.values() if h > 0)
    if not b:
        return {"status": "NOT_MEASURED",
                "reason": "the lcov union names none of the scoped DUT files",
                "lcov_files": sorted(tool)}
    return {"status": "MEASURED", "agree": not mismatches,
            "lcov_line_totals": {
                "covered": covered, "total": total,
                "pct": round(100.0 * covered / total, 2) if total else 0.0},
            "mismatches": mismatches}


def lcov_line_union(dats: Sequence[str], out_dir: str,
                    exec_fn=None) -> Tuple[Optional[Dict[str, Dict[int, int]]], str]:
    """Run `verilator_coverage --write-info` over `dats`; return (map, info path)."""
    if exec_fn is None:
        def exec_fn(argv, cwd):  # noqa: ANN001 — local default
            r = run(argv, cwd=cwd, check=False)
            return r.returncode, r.stdout, r.stderr
    info = str(Path(out_dir) / LCOV_INFO_NAME)
    try:
        Path(info).unlink()
    except OSError:
        pass
    try:
        rc, _out, _err = exec_fn(["verilator_coverage", "--write-info", info,
                                  *[str(d) for d in dats]], out_dir)
    except OSError:
        return None, info
    if rc != 0 or not Path(info).is_file():
        return None, info
    try:
        return parse_lcov_info(Path(info).read_text(errors="replace")), info
    except ValueError:
        return None, info


# ----- artefact provenance -----------------------------------------

TOOL_SIGNATURES = [
    "verilator",  # tool name often appears in coverage.dat's preamble
    "C '\x02",    # binary tag marker
    "points_count",
]

ESTIMATION_FLAGS = [
    re.compile(r"\bestimated?\b", re.I),
    re.compile(r"\bapprox(?:imate)?\b", re.I),
    re.compile(r"≥\s*\d+\s*%"),
    re.compile(r">=\s*\d+\s*%"),
    re.compile(r"\bmanual(ly)? counted\b", re.I),
]


def artefact_looks_tool_generated(json_payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Heuristic: artefact must have numeric per-category counts + reference
    a coverage.dat path that exists. Reject if narrative fields include
    'estimated', '≥ 95 %', etc.
    """
    totals = json_payload.get("totals", {})
    for cat in ("line", "toggle", "branch"):
        if cat not in totals:
            return False, f"missing totals.{cat}"
        for key in ("covered", "total", "pct"):
            if key not in totals[cat]:
                return False, f"missing totals.{cat}.{key}"
    # Narrative fields (optional but if present must not contain estimation
    # keywords)
    for field in ("note", "notes", "source", "tool"):
        v = json_payload.get(field, "")
        if isinstance(v, str):
            for pat in ESTIMATION_FLAGS:
                if pat.search(v):
                    return False, f"estimation keyword in {field!r}: {v!r}"
    # If a .dat path is recorded, verify it exists
    dat = json_payload.get("coverage_dat")
    if dat and not Path(dat).exists():
        return False, f"coverage.dat path recorded but missing: {dat}"
    return True, "ok"


# ----- artefact classification --------------------------------------
#
# The declared coverage path is shared: `design_one_shot_runner` writes a
# FUNCTIONAL-verification verdict payload (verdict / evidence /
# verification_track / scenarios_covered) to
# reports/phase2/coverage/coverage_actual.json, the same path the flow YAML
# declares as the coverage artefact this gate audits. Such a payload carries
# no `totals` container at all — no line/toggle/branch was ever measured —
# so the coverage gate must NAME that collision rather than treat the path
# as an inapplicable input.

#: Keys that assert a coverage NUMBER. A payload carrying one of these while
#: carrying no `totals` container is a coverage CLAIM with no measurement
#: behind it — a forgery, never a capability gap.
_BARE_COVERAGE_CLAIM_KEYS = (
    "line_pct", "toggle_pct", "branch_pct",
    "line_coverage", "toggle_coverage", "branch_coverage",
    "coverage_pct", "coverage_percent", "line_coverage_pct",
)

#: Artefact kinds that are always a DEFECT, whatever the host toolchain is.
_DEFECT_KINDS = ("corrupt", "malformed", "forged")
#: Artefact kinds meaning "no coverage measurement exists at this path".
_NO_MEASUREMENT_KINDS = ("absent", "foreign")


def classify_coverage_artefact(path: Path) -> Tuple[str, str, Dict[str, Any]]:
    """Classify what actually sits at the declared coverage path.

    Returns ``(kind, detail, payload)``:

      ``measured``  a well-formed tool-generated coverage artefact — apply
                    thresholds to it.
      ``absent``    nothing at the path.
      ``foreign``   valid JSON with NO ``totals`` container: another producer
                    owns this path and no coverage was measured here.
      ``corrupt``   the file exists but is not parseable JSON.
      ``malformed`` claims to be coverage (``totals`` present) but the
                    container is incomplete / its coverage.dat backlink is
                    dead.
      ``forged``    a coverage number asserted with no measurement behind it
                    — well-formed counters carrying estimation language, or a
                    bare percentage claim with no ``totals``. This is the
                    exact "≥ 95 % estimated" shape the gate exists to reject.
    """
    if not path.exists():
        return "absent", f"no artefact at {path}", {}
    try:
        data = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001 — any unparseable file is corrupt
        return "corrupt", f"{path}: parse error: {exc}", {}
    if not isinstance(data, dict):
        return ("corrupt",
                f"{path}: top level is {type(data).__name__}, not an object",
                {})

    totals = data.get("totals")
    if not isinstance(totals, dict) or not totals:
        claims = [k for k in _BARE_COVERAGE_CLAIM_KEYS if k in data]
        if claims:
            return ("forged",
                    f"{path}: asserts coverage via {claims} with no `totals` "
                    f"container behind it — a coverage claim is not a "
                    f"coverage measurement", data)
        owner = (data.get("verification_track") or data.get("verdict")
                 or "another producer")
        return ("foreign",
                f"{path}: carries no `totals` container — the file at the "
                f"declared coverage path is a {owner!r} payload written by "
                f"another producer, so line/toggle/branch was never measured "
                f"here", data)

    ok, reason = artefact_looks_tool_generated(data)
    if ok:
        return "measured", "ok", data
    if reason.startswith("estimation keyword"):
        return "forged", f"{path}: {reason}", data
    return "malformed", f"{path}: {reason}", data


# ----- CLI ----------------------------------------------------------


def _mounts_for(container: str) -> Optional[List[Tuple[Path, str]]]:
    """The named container's bind mounts, or None when none was named.

    None and `[]` are different answers and are kept apart: None means the
    caller did not say the tool ran elsewhere, `[]` means it did and the mount
    table could not be read. The second is disclosed by
    `host_path_namespace` as `mounts_consulted: 0` with every path left in the
    tool's namespace, rather than silently treated as a local run.
    """
    if not container:
        return None
    try:
        import _designs_root as _dr                    # noqa: PLC0415
        return list(_dr.container_mounts(container))
    except Exception:                                  # noqa: BLE001
        return []


def cmd_measure(args: argparse.Namespace) -> int:
    dat = verilate_and_run(args.rtl_dir, args.top, args.main, args.build_dir)
    cov = parse_coverage_dat(dat, mounts=_mounts_for(getattr(args, "container", "")))
    scoped = scope_totals(cov, list(cov.get('per_file') or {}))
    out = {
        "tool": "verilator",
        "coverage_dat": dat,
        **cov,
        **(scoped or {}),
        "per_file_metric": "category_points",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    if not scoped or scoped['line_metric'] != 'executable_line_union':
        print('[measure] executable-line coverage NOT_MEASURED', file=sys.stderr)
        return 1
    totals = out["totals"]
    line_pct = totals["line"]["pct"]
    toggle_pct = totals["toggle"]["pct"]
    branch_pct = totals["branch"]["pct"]
    print(
        f"[measure] line={line_pct}% toggle={toggle_pct}% branch={branch_pct}% "
        f"→ {args.out}"
    )
    if any(p < t for p, t in [(line_pct, args.min_line), (toggle_pct, args.min_toggle), (branch_pct, args.min_branch)]):
        print("[measure] below one or more thresholds", file=sys.stderr)
        return 1
    return 0


#: Where the flow's own testbenches live, most-authoritative first. The
#: oracle TB is the one the flow actually simulates for a functional verdict,
#: so instrumenting it measures the run that was believed, not a second
#: stimulus written to make a number look better.
_TB_DISCOVERY_ORDER = (
    ("phase2/stage1/sim_full_stack", "tb_*_oracle.v"),
    ("phase2/stage1/sim_full_stack", "tb_*_full.v"),
    ("phase2/stage1/sim/tb", "*.v"),
    # THE PER-MODULE UNIT TESTBENCH, and it is LAST on purpose: the order
    # above is most-authoritative-first, and the unit TB is not what the flow
    # simulates for its functional verdict. It is here because the selection
    # below prefers whichever candidate DRIVES A FUNCTIONAL INPUT, and on a
    # design whose generated end-to-end harnesses are inert this is the only
    # stimulus the flow itself demands the existence of.
    #
    # MEASURED on `subservient` x gf180mcuD. `verilator_coverage_measure
    # check` reported, in its own words:
    #   "NO FUNCTIONAL STIMULUS IN THE COVERAGE BUILD -- this run measured no
    #    coverage of the design ... of the signal(s) it binds to the design and
    #    declares drivable it assigns only ['i_clk','i_rst'] -- the clock and
    #    reset. It never drives ['i_sram_data'] ... the recorded percentages
    #    (line 45.19%, toggle 34.76%, branch 43.75%) describe that testbench,
    #    NOT the RTL"
    # Every candidate the three entries above found was inert: the
    # `sim_full_stack` harness declares itself connectivity-only, and the
    # `sim/tb/*.v` unit cases are the generator's SUBSTANCE FLOOR shape, each
    # carrying `VIBEIC_TB_ORACLE: NONE`. Meanwhile
    # `rtl_unit_test_coverage_check` -- a gate in this same flow -- was
    # DEMANDING a `sim_unit/tb_<module>.v` for that very module and routing
    # the job to the `rtl-unit-testbench-gen` skill. So the flow asked for the
    # one testbench that can move the design and then looked everywhere except
    # where it had asked for it. The two lists are now the same list.
    #
    # `rtl_unit_test_coverage_check`'s own `--sim-dir` default is
    # `<project>/sim_unit`; the phase-2 spelling is carried too so a project
    # that files it under the stage tree is not silently skipped.
    ("sim_unit", "tb_*.v"),
    ("phase2/stage1/sim_unit", "tb_*.v"),
)


def _professional_measure_testbenches(project: Path) -> List[str]:
    """Every generator-owned professional bundle, including refused bundles.

    If no functional Verilog/Python candidate exists, missing/incomplete plans
    reach the adapter's named refusal instead of a connectivity harness. An
    incomplete generated hook does not displace an existing functional Verilog
    suite. No previous JUnit is used for discovery; the instrumented simulation
    must establish its own result.
    """
    candidates = []
    for bundle in sorted((project / "phase2/stage1/sim_professional").glob("*")):
        if not bundle.is_dir() or bundle.name.startswith("."):
            continue
        candidates.append(str(bundle / f"tb_{bundle.name}.py"))
    return candidates


def discover_measure_inputs(project: Path) -> Tuple[List[str], Optional[str]]:
    """(RTL sources, testbench) for `project`, or ([], None) when absent.

    RTL selection reuses `design_one_shot_runner._select_asic_rtl_sources`
    when it can be imported — the SAME selector the simulation itself used —
    so the instrumented closure is the simulated closure. The fallback is a
    plain non-testbench glob of the RTL directory.
    """
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl: List[str] = []
    if rtl_dir.is_dir():
        try:
            import design_one_shot_runner as _dosr  # noqa: PLC0415
            rtl = [str(f) for f in _dosr._select_asic_rtl_sources(rtl_dir)]
        except Exception:  # noqa: BLE001 — selector is an optimisation
            rtl = [str(f) for f in
                   sorted(rtl_dir.glob("*.sv")) + sorted(rtl_dir.glob("*.v"))
                   if not (f.name.startswith("tb_") or f.stem.endswith("_tb"))]
    candidates: List[str] = []
    for rel, pat in _TB_DISCOVERY_ORDER:
        if (project / rel).is_dir():
            candidates.extend(
                str(path) for path in sorted((project / rel).glob(pat)))
    candidates.extend(_professional_measure_testbenches(project))

    # Keep the declared path order as the fallback, but do not prefer an inert
    # connectivity harness over a later testbench that demonstrably drives a
    # functional input.  The audit is the single producer of that vocabulary;
    # discovery does not maintain a second definition of "stimulus".
    tb: Optional[str] = candidates[0] if candidates else None
    for candidate in candidates:
        audit = functional_stimulus_audit(Path(candidate))
        if audit["decidable"] and audit["driven"]:
            tb = candidate
            break
    if tb:
        rtl.extend(_cov_sources_for_tb(project, Path(tb), rtl))
    return rtl, tb


def discover_measure_testbenches(project: Path) -> Tuple[List[str], List[str]]:
    """(RTL sources, EVERY testbench that drives the design) — the suite, not
    a member of it.

    `discover_measure_inputs` returns the FIRST driving candidate and is kept
    exactly as it was, because callers that measure one testbench are still
    right to ask for one. This is the selector for the question "what does this
    design's verification cover", whose answer is a set.

    WHY IT MATTERS, MEASURED (subservient x gf180mcuD, lane icsub2, r17 vs r18
    on the same RTL and the same denominators). `_TB_DISCOVERY_ORDER` places
    `phase2/stage1/sim/tb/*.v` ahead of `sim_unit/tb_*.v`. While those files
    were the generator's substance-floor scaffolds they were inert, the audit
    said so, and selection fell through to the unit testbench: line 80.74%. The
    moment a real per-case oracle suite was authored into that directory, the
    alphabetically first member drove the design, selection stopped there, and
    the run published `blinky_hex`'s line 68.89% as the design's coverage —
    below a 70% floor the suite clears at 98.52%. Nothing about the design had
    changed; the verification had got BETTER.

    Order is the discovery order, de-duplicated. Falls back to the single
    first candidate when NONE is decidably driven, which is what the one-TB
    selector does, so a project with no functional stimulus is unaffected."""
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl, _first = discover_measure_inputs(project)
    candidates: List[str] = []
    for rel, pat in _TB_DISCOVERY_ORDER:
        if (project / rel).is_dir():
            for path in sorted((project / rel).glob(pat)):
                if str(path) not in candidates:
                    candidates.append(str(path))
    professional = _professional_measure_testbenches(project)
    candidates.extend(c for c in professional if c not in candidates)
    driving = [c for c in candidates
               if (lambda a: a["decidable"] and a["driven"])(
                   functional_stimulus_audit(Path(c)))]
    chosen = driving or professional or ([candidates[0]] if candidates else [])
    for tb in chosen:
        for extra in _cov_sources_for_tb(project, Path(tb), rtl):
            if extra not in rtl:
                rtl.append(extra)
    del rtl_dir
    return rtl, chosen


def _cov_sources_for_tb(project: Path, tb: Path,
                        rtl: List[str]) -> List[str]:
    """Resolve testbench-only helper modules from the design input.

    This delegates source lookup to ``testbench_gen``'s existing scoped
    resolver.  It does not invent another search root, and it does not infer
    that a shared instance signal is stimulus; only
    :func:`functional_stimulus_audit` produces that verdict.
    """
    if tb.suffix == ".py":
        return []
    try:
        import testbench_gen as _tbg  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — discovery must retain its old fallback
        return []

    defined = set()
    for source in rtl:
        try:
            source_body = _cov_strip_comments(
                Path(source).read_text(errors="replace"))
        except OSError:
            continue
        defined.update(re.findall(r"\bmodule\s+(\w+)\b", source_body))

    try:
        body = _cov_strip_comments(tb.read_text(errors="replace"))
    except OSError:
        return []
    extra: List[str] = []
    for match in re.finditer(r"(?m)^\s*(\w+)\s+\w+\s*\(", body):
        module = match.group(1)
        if module in defined or module in {
                "module", "if", "for", "while", "case", "initial",
                "always", "assign", "task", "function", "begin", "end"}:
            continue
        source = _tbg._resolve_from_design_input(project, module)
        if source is None or str(source) in rtl or str(source) in extra:
            continue
        extra.append(str(source))
        defined.update(re.findall(
            r"\bmodule\s+(\w+)\b",
            _cov_strip_comments(source.read_text(errors="replace"))))
    return extra


def measure_suite(rtl: Sequence[str], tbs: Sequence[str], build_dir: str, *,
                  run_dir: Optional[str] = None, exec_fn=None,
                  build_jobs: int = 0,
                  mounts: Optional[Sequence[Tuple[Path, str]]] = None,
                  scope: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Build and run EVERY testbench in `tbs`, then UNION their points.

    THE ONE IMPLEMENTATION. This exists because there were two: the CLI's
    `measure-tb` and a hand-rolled copy inside `design_one_shot_runner`'s
    `step_verilator_coverage`, which is the one the flow actually runs. They
    had the same shape and the same payload keys, so a fix to the first was
    invisible in every real run — MEASURED on subservient r21, where the landed
    suite-union code produced `measurement_scope: None` and `testbenches: 0`
    because nothing in the flow's path had ever called it. A second
    implementation of a measurement is a second answer waiting to disagree.

    `exec_fn` is threaded through to `verilate_tb_and_run` so the caller
    decides WHERE the build runs; everything else — one build directory per
    testbench, the per-testbench totals, the union, and the named refusal when
    the records cannot be keyed — is decided once, here.

    Returns the pieces a payload is composed from; composing it stays with the
    caller, because the two callers write to different places for different
    readers."""
    dats: List[str] = []
    per_tb: Dict[str, Any] = {}
    for i, one_tb in enumerate(tbs):
        # ONE BUILD DIRECTORY PER TESTBENCH. Sharing one lets a later Verilator
        # build overwrite an earlier coverage.dat, and the union would then be
        # over fewer runs than it names — silently.
        sub = (build_dir if len(tbs) == 1
               else str(Path(build_dir) / f"tb{i:02d}_{Path(one_tb).stem}"))
        sub_run = ((run_dir or build_dir) if len(tbs) == 1 else sub)
        try:
            dat_i = verilate_tb_and_run(list(rtl), str(one_tb), sub, sub_run,
                                        exec_fn=exec_fn, build_jobs=build_jobs)
        except SystemExit as exc:
            if Path(one_tb).suffix == ".py":
                # A declared professional suite that did not execute cannot
                # disappear from an otherwise green suite union.
                raise
            # DISCLOSED, never silently dropped: a member that would not build
            # is a member whose contribution is missing from the union, and the
            # reader has to be told which one.
            per_tb[str(one_tb)] = {"measured": False, "reason": str(exc)[:400]}
            continue
        dats.append(dat_i)
        one_cov = parse_coverage_dat(dat_i, mounts=mounts)
        one_scoped = scope_totals(one_cov, list(scope or rtl))
        per_tb[str(one_tb)] = {"measured": True, "coverage_dat": dat_i,
                               "totals": one_scoped["totals"] if one_scoped
                               else None}
    union_refused = ""
    cov: Optional[Dict[str, Any]] = None
    if len(dats) > 1:
        cov = union_coverage_dats(dats, mounts=mounts)
        if not cov.get("unionisable"):
            # FAIL SAFE AND SAY SO: reporting a concatenated denominator would
            # be worse than reporting one member's honest number.
            union_refused = (f"the {len(dats)} runs could not be unioned "
                             f"({cov.get('reason')}); reporting the FIRST "
                             f"measured testbench alone")
            cov = parse_coverage_dat(dats[0], mounts=mounts)
            dats = dats[:1]
    elif dats:
        cov = parse_coverage_dat(dats[0], mounts=mounts)
    # THE TOOL'S LINE UNION, BESIDE OURS. Recorded, and a disagreement is a
    # named finding that `check` refuses; neither side replaces the other.
    line_check: Dict[str, Any] = {"status": "NOT_MEASURED",
                                  "reason": "no coverage.dat to union"}
    if dats:
        tool_map, info = lcov_line_union(dats, build_dir, exec_fn=exec_fn)
        line_check = cross_check_line_union(union_line_map(dats), tool_map,
                                            list(scope or rtl))
        line_check["lcov_info"] = info
    return {"dats": dats, "cov": cov, "per_testbench": per_tb,
            "union_refused": union_refused,
            "line_union_cross_check": line_check,
            "measured": [str(t) for t in tbs
                         if per_tb.get(str(t), {}).get("measured")],
            "scope_used": list(scope or rtl)}


def suite_payload_fields(result: Dict[str, Any]) -> Dict[str, Any]:
    """The payload keys BOTH producers must carry, composed once.

    `testbench` keeps naming ONE testbench because every existing reader audits
    it for functional stimulus; `testbenches` is the honest population and
    `measurement_scope` says which of the two the totals belong to."""
    measured = result.get("measured") or []
    dats = result.get("dats") or []
    scoped = scope_totals(result.get('cov') or {}, list(result.get('scope_used') or []))
    return {
        "testbenches": measured,
        "measurement_scope": ("union-of-suite" if len(dats) > 1
                              else "single-testbench"),
        "per_testbench": result.get("per_testbench") or {},
        "union_refused": result.get("union_refused") or "",
        "line_metric": scoped['line_metric'] if scoped else 'NOT_MEASURED',
        "line_point_totals": scoped['line_point_totals'] if scoped else None,
        "per_file_metric": "category_points",
        "line_union_cross_check": result.get("line_union_cross_check") or {
            "status": "NOT_MEASURED", "reason": "not recorded by the producer"},
    }


def prepare_professional_coverage_report(path: Path) -> None:
    """Retain the prior report and make the current attempt unmeasured.

    A refused attempt must never lend the previous PASS to the consumer.
    The previous report remains an independent byte-for-byte history copy.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = None
    if path.is_file():
        history = path.parent / (path.stem + '.history')
        history.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        folder = Path(tempfile.mkdtemp(prefix=f'attempt_{stamp}_', dir=history))
        previous = folder / path.name
        shutil.copy2(path, previous)
    path.write_text(json.dumps({
        "tool": "verilator", "measurement_mode": "measure-tb",
        "measurement_status": "NOT_MEASURED",
        "reason": "current professional coverage attempt has no accepted measurement",
        "previous_report": str(previous) if previous else None,
    }, indent=2) + "\n")


def fail_professional_coverage_report(path: Path, reason: str) -> None:
    """Record the current refusal without consuming or changing history."""
    record = json.loads(Path(path).read_text())
    record.update(measurement_status="NOT_MEASURED", reason=reason)
    Path(path).write_text(json.dumps(record, indent=2) + "\n")


def cmd_measure_tb(args: argparse.Namespace) -> int:
    """Instrument + run the project's own testbench and write the measurement."""
    rtl = list(args.rtl or [])
    # THE SUITE, NOT A MEMBER OF IT. An explicit `--tb` still measures exactly
    # that one testbench — a caller who names one is right to get one. Only
    # DISCOVERY was ever the problem: it returned the first driving candidate
    # and the totals were published as the design's.
    tbs: List[str] = [args.tb] if args.tb else []
    if args.project and not tbs:
        d_rtl, d_tbs = discover_measure_testbenches(Path(args.project))
        rtl = rtl or d_rtl
        tbs = d_tbs
    elif args.project and not rtl:
        rtl = discover_measure_inputs(Path(args.project))[0]
    if not rtl:
        print("[measure-tb] no RTL sources found to instrument",
              file=sys.stderr)
        return 1
    if not tbs:
        print("[measure-tb] no testbench found to instrument — coverage "
              "cannot be measured without a stimulus that actually ran",
              file=sys.stderr)
        return 1

    default_build = (Path(args.project) / "phase2" / "stage1" / "sim"
                     / "cov_build") if args.project \
        else (Path(args.out).parent / "cov_build")
    build_dir = args.build_dir or str(default_build)
    run_dir = args.run_dir or build_dir
    mounts = _mounts_for(getattr(args, "container", ""))
    scope = args.scope_file or rtl
    professional = any(Path(tb).suffix == ".py" for tb in tbs)
    if professional:
        prepare_professional_coverage_report(Path(args.out))

    # ONE implementation, shared with the flow's own producer.
    try:
        res = measure_suite(rtl, tbs, build_dir, run_dir=run_dir,
                            build_jobs=args.build_jobs, mounts=mounts, scope=scope)
    except SystemExit as exc:
        if professional:
            fail_professional_coverage_report(Path(args.out), str(exc))
        raise
    dats, per_tb = res["dats"], res["per_testbench"]
    for one_tb, rec in per_tb.items():
        if not rec.get("measured"):
            print(f"[measure-tb] {Path(one_tb).name}: NOT MEASURED — "
                  f"{str(rec.get('reason'))[:200]}", file=sys.stderr)
    if not dats:
        print("[measure-tb] no testbench produced coverage points — refusing "
              "to report a measurement nothing measured", file=sys.stderr)
        return 1
    union_note = res["union_refused"]
    if union_note:
        print(f"[measure-tb] {union_note}", file=sys.stderr)
    cov = res["cov"]
    dat = dats[0]
    scoped = scope_totals(cov, scope)
    if scoped is None:
        print(f"[measure-tb] the instrumented run recorded no coverage points "
              f"for any of {[Path(x).name for x in scope]} — refusing to "
              f"report the unscoped total in their place", file=sys.stderr)
        return 1
    measured = res["measured"]
    out = {
        "tool": "verilator",
        "measurement_mode": "measure-tb",
        "coverage_dat": dat,
        "testbench": measured[0] if measured else tbs[0],
        **suite_payload_fields(res),
        "rtl_sources": [str(x) for x in rtl],
        "totals": scoped["totals"],
        "scope_files": scoped["scope_files"],
        "per_file": cov["per_file"],
        "format_detected": cov["format_detected"],
        "path_namespace": cov["path_namespace"],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    t = scoped["totals"]
    _how = (f"UNION of {len(dats)} testbench(es)" if len(dats) > 1
            else f"from {dat}")
    print(f"[measure-tb] line={t['line']['pct']}% "
          f"toggle={t['toggle']['pct']}% branch={t['branch']['pct']}% "
          f"(scope {scoped['scope_files']}, {_how}) -> {args.out}")
    if len(dats) > 1:
        for one_tb in measured:
            one = (per_tb.get(one_tb) or {}).get("totals") or {}
            if one:
                print(f"[measure-tb]   {Path(one_tb).name}: "
                      f"line={one['line']['pct']}% "
                      f"toggle={one['toggle']['pct']}% "
                      f"branch={one['branch']['pct']}%")
    below = [f"{c} {t[c]['pct']}% < {th}%"
             for c, th in (("line", args.min_line),
                           ("toggle", args.min_toggle),
                           ("branch", args.min_branch))
             if t[c]["pct"] < th]
    if below:
        print("[measure-tb] below threshold(s): " + "; ".join(below),
              file=sys.stderr)
        return 1
    return 0


#: Exit code + stdout sentinel `flow_compliance_check._check_program_exit_zero`
#: recognises as "PASSED WITH WAIVERS" -> step tier WAIVED-DEFERRED. Both are
#: required there, so a stray rc=3 from an unrelated program is never waived.
WAIVER_EXIT_CODE = 3
WAIVER_STDOUT_SENTINEL = "PASS_WITH_WAIVERS"

#: The named capability this gate needs. Printed so the deferral is
#: attributable, in the same shape the flow's other cap-gap waivers use.
COVERAGE_CAPABILITY = "cap:verilator_coverage_toolchain"

#: Which executable's presence decides "capability gap" vs "defect". Made
#: overridable so a test harness (or a container that ships Verilator under
#: another name) can PIN the decision rather than inherit whatever the host
#: happens to have. Note the only direction this can move a verdict is
#: FAIL -> WAIVED-DEFERRED, which is still not a PASS and is printed in full.
VERILATOR_BIN_ENV = "VIBE_IC_VERILATOR_BIN"
VERILATOR_BIN_DEFAULT = os.environ.get(VERILATOR_BIN_ENV, "verilator")


# ── did this coverage build contain any functional stimulus at all? ────────
#
# THE DEFECT, MEASURED — sha256 x sky130A, plugin 1.15.94, frozen tree c3584d0aa:
#
#   reports/phase2/coverage/coverage_verilator.json
#     "measurement_mode": "measure-tb"
#     "testbench": "phase2/stage1/sim_full_stack/tb_sha256_full.v"
#   -> [check] below threshold(s): line 16.48% < 70.0%;
#                                  toggle 2.34% < 60.0%; branch 13.46% < 70.0%
#
# That testbench is an 87-line generated skeleton whose OWN header says "It is
# CONNECTIVITY-ONLY (it closes no functional coverage on its own)".  It declares
# `cs`, `we`, `address`, `write_data`, wires them to the DUT, initialises them
# at declaration and NEVER assigns them again: the only signals it drives are
# the clock and the reset.  16.48% is the coverage of releasing reset and
# waiting — it is not a property of the RTL.  The same run held a cocotb
# testbench that had just driven 1020 NIST vectors through the whole design.
#
# "I did not measure the design" and "I measured the design at 16.48%" are two
# different facts, and reporting the second when the first is true sends the
# reader to the RTL for a defect that is in the coverage build.  This audit
# separates them.  It NEVER makes the verdict pass: a run with no functional
# stimulus still blocks, because unmeasured is not verified.
#
# THE CRITERION IS THE TESTBENCH'S OWN BEHAVIOUR, not its name.  A population
# defined by one spelling of a filename is blind to every other spelling, so
# nothing here matches `*_full.v` or any other path shape.  What is counted is
# a fact anyone can re-derive from the file: of the signals this testbench
# binds to the DUT's ports and declares as drivable (`reg`), how many does it
# ever assign outside their declaration, excluding the clock and the reset?
# Zero means the design's inputs were never moved.  The header self-description
# is reported as corroboration and decides nothing, precisely because a comment
# can be deleted while the testbench stays inert.
#: Clock/reset name grammar — these two are infrastructure, not stimulus.
_COV_CLK_RST_RE = re.compile(
    r"(?i)(?:^|_)(?:clk|clock|rst|reset|resetn|rstn|nrst|por|sclk|hclk|aclk)"
    r"(?:_|\d|n)*$")
#: Port-direction suffixes are spelling, not signal purpose.  Removing one
#: before applying the existing grammar makes ``clk_i`` and ``rst_ni`` retain
#: the same meaning as ``clk`` and ``rst_n``.  Deliberately do not treat every
#: ``clk_*``/``reset_*`` prefix as infrastructure: names such as
#: ``clk_enable_i`` and ``reset_value_i`` can be functional inputs.
_COV_DIR_SUFFIX_RE = re.compile(r"(?i)_(?:ni|no|io|i|o|n|p)$")


def _cov_is_clock_or_reset(name: str) -> bool:
    """Apply the canonical clock/reset grammar after one direction suffix."""
    if _COV_CLK_RST_RE.search(name):
        return True
    without_direction = _COV_DIR_SUFFIX_RE.sub("", name)
    return (without_direction != name
            and bool(_COV_CLK_RST_RE.search(without_direction)))


#: `<name> = ...` (blocking, never `==`/`<=`/`>=`/`!=`) or `<name> <= ...`.
_COV_DRIVE_RE_TMPL = r"\b{name}\s*(?:<=(?!=)|(?<![<>=!])=(?!=))"
#: A field or selected element assigned after declaration is a real drive of
#: its aggregate.  Requiring at least one selector avoids treating a typed
#: declaration initializer as runtime stimulus.
_COV_FIELD_DRIVE_RE_TMPL = (
    r"\b{name}(?:\.\w+|\[[^\]]*\])+\s*"
    r"(?:<=(?!=)|(?<![<>=!])=(?!=))")
#: A module instantiation's named port connections: `.port(signal)`.
_COV_PORT_BIND_RE = re.compile(r"\.\s*(\w+)\s*\(\s*([\w\[\]:\s]*?)\s*\)")
#: A whole `reg ...;` declaration STATEMENT — the declaration, which is not a
#: drive.  NOT line-anchored and NOT one-name-per-match, because it was both
#: and each cost the audit a signal:
#:
#:     reg clk = 1'b0; reg rst; reg a; wire q;
#:
#: is THREE declarations on one line, and `(?m)^\s*reg` sees only the first —
#: so `a`, the design's only functional input, was never in the drivable set at
#: all.  A comma list (`reg a, b;`) lost everything after the first name for
#: the same reason.  The names are pulled out of the matched statement by
#: `_cov_declared_regs`, so one expression serves both readers: the name scan
#: and the `sub()` that strips declarations before looking for drives.
_COV_REG_DECL_RE = re.compile(
    r"\breg\b(?:\s+(?:signed|unsigned))?(?:\s*\[[^\]\n]*\])?[^;\n]*;")
#: Strips the keyword, an optional sign qualifier and an optional packed range
#: off a matched declaration, leaving the comma list of declared names.
_COV_REG_DECL_HEAD_RE = re.compile(
    r"^\s*reg\b(?:\s+(?:signed|unsigned))?(?:\s*\[[^\]\n]*\])?")


def _cov_split_top_level(text: str) -> List[str]:
    """`text` split on commas that are not inside `{}`, `()` or `[]`.

    A declaration's initialiser may itself contain commas
    (`reg [3:0] x = {1'b0, 3'b000};`), and splitting through one would
    manufacture a name out of the middle of an expression.
    """
    items: List[str] = []
    depth = 0
    cur: List[str] = []
    for ch in text:
        if ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        if ch == "," and depth <= 0:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    items.append("".join(cur))
    return items


def _cov_declared_regs(body: str) -> set:
    """Every name declared `reg` in `body`, however the declarations are laid
    out — several statements on one line, and comma lists within a statement.
    """
    names = set()
    for stmt in _COV_REG_DECL_RE.findall(body):
        tail = _COV_REG_DECL_HEAD_RE.sub("", stmt).rstrip(";")
        for item in _cov_split_top_level(tail):
            m = re.match(r"\s*(\w+)", item)
            if m:
                names.add(m.group(1))
    return names


def _cov_strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def _professional_python_audit(tb: Path) -> Dict[str, Any]:
    """Python stimulus uses the design's L9 input contract, not pin guesses.

    A source assignment alone is not execution evidence. This audit admits a
    self-checking bundle for simulation; the adapter subsequently requires this
    instrumented run's nonzero, unskipped passing JUnit before crediting data.
    """
    out = {"testbench": str(tb), "decidable": False, "reason": "",
           "driven": [], "inert": [], "clock_reset": [],
           "self_declared_connectivity_only": False,
           "stimulus_language": "cocotb-python"}
    try:
        plan = _professional_bundle(tb)
        tree = ast.parse(tb.read_text())
        project = _cov_project_root({"rtl_sources": [str(tb)]})
        if project is None:
            raise ValueError("Python testbench is outside a canonical project bundle")
        import arith_oracle_tb_gen as _aog  # noqa: PLC0415
        import professional_tb_gen as _ptg  # noqa: PLC0415
        top, ports = _aog._load_top_ports(project)
        if top != plan["top"] or not ports:
            raise ValueError("professional top does not match the design's L9 ports")
        cr = _ptg._load_clock_reset(project, ports)
    except (SystemExit, OSError, SyntaxError, ValueError, TypeError) as exc:
        out["reason"] = str(exc)
        return out
    constants = {}
    roots = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        constants[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.args.args:
            roots.add(node.args.args[0].arg)

    def signal(handle):
        if isinstance(handle, ast.Attribute) and isinstance(handle.value, ast.Name):
            return handle.attr if handle.value.id in roots else None
        if (isinstance(handle, ast.Call) and isinstance(handle.func, ast.Name)
                and handle.func.id == "getattr" and len(handle.args) >= 2
                and isinstance(handle.args[0], ast.Name)
                and handle.args[0].id in roots):
            name = handle.args[1]
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                return name.value
            if isinstance(name, ast.Name) and isinstance(constants.get(name.id), str):
                return constants[name.id]
        return None

    inputs = {p["name"] for p in ports if p.get("dir") == "input"}
    infrastructure = {cr.get("clk"), cr.get("rst")}
    data_inputs = inputs - infrastructure
    values = {name: set() for name in data_inputs}
    dynamic = set()
    reads = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "value" and isinstance(node.ctx, ast.Load):
            name = signal(node.value)
            if name:
                reads.add(name)
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Attribute) or target.attr != "value":
                continue
            name = signal(target.value)
            if name in inputs & infrastructure:
                out["clock_reset"].append(name)
            if name not in data_inputs:
                continue
            try:
                value = ast.literal_eval(node.value)
                values[name].add(repr(value))
            except (ValueError, TypeError):
                dynamic.add(name)
    if not reads or not any(isinstance(n, ast.Assert) for n in ast.walk(tree)):
        out["reason"] = "no observed DUT read and self-check assertion in the Python source"
        return out
    out["clock_reset"] = sorted(set(out["clock_reset"]))
    out["driven"] = sorted(dynamic | {n for n, v in values.items() if len(v) > 1})
    out["inert"] = sorted(data_inputs - set(out["driven"]))
    out["decidable"] = bool(data_inputs)
    return out


def functional_stimulus_audit(tb_path: Path) -> Dict[str, Any]:
    """Does this testbench ever move a DUT input other than clock and reset?

    Returns a record with `decidable`, `driven` (the functional inputs it does
    drive), `inert` (bound + drivable + never assigned) and
    `self_declared_connectivity_only`.  When the testbench cannot be read or
    carries no recognisable instantiation the audit is NOT decidable and the
    caller must fall through to its normal behaviour — an audit that cannot see
    must never be the reason a run is judged.
    """
    if tb_path.suffix == ".py":
        return _professional_python_audit(tb_path)
    out: Dict[str, Any] = {
        "testbench": str(tb_path), "decidable": False, "reason": "",
        "driven": [], "inert": [], "clock_reset": [],
        "self_declared_connectivity_only": False,
    }
    try:
        raw = tb_path.read_text(errors="replace")
    except OSError as exc:
        out["reason"] = f"testbench unreadable: {exc}"
        return out
    out["self_declared_connectivity_only"] = bool(
        re.search(r"(?i)connectivity[\s-]*only", raw))
    body = _cov_strip_comments(raw)
    bound = {sig.strip() for _port, sig in _COV_PORT_BIND_RE.findall(body)
             if sig.strip() and sig.strip().isidentifier()}
    if not bound:
        out["reason"] = ("no named port connections found, so which signals "
                         "reach the design cannot be determined")
        return out
    declared_reg = _cov_declared_regs(body)
    # A packed/struct variable may be declared with a package type rather than
    # ``reg`` and driven field by field.  Count that observed assignment using
    # the same bound-signal population; do not guess that a signal shared by
    # two instances is driven, because a DUT output feeding a monitor has that
    # shape too.
    stripped = _COV_REG_DECL_RE.sub(" ", body)
    field_driven = {
        name for name in bound
        if re.search(_COV_FIELD_DRIVE_RE_TMPL.format(name=re.escape(name)),
                     stripped)
    }
    drivable = sorted((bound & declared_reg) | field_driven)
    if not drivable:
        out["reason"] = ("no bound signal is declared `reg` or has an "
                         "observed field assignment, so the drivable set "
                         "cannot be determined")
        return out
    # Remove the declarations themselves: initialising at declaration is not
    # stimulus, it is the starting value.
    for name in drivable:
        drives = (re.search(_COV_DRIVE_RE_TMPL.format(name=re.escape(name)),
                            stripped)
                  or re.search(_COV_FIELD_DRIVE_RE_TMPL.format(
                      name=re.escape(name)), stripped))
        if _cov_is_clock_or_reset(name):
            out["clock_reset"].append(name)
        elif drives:
            out["driven"].append(name)
        else:
            out["inert"].append(name)
    if not out["driven"] and not out["inert"]:
        # EMPTY POPULATION.  Every drivable bound signal is a clock or a
        # reset, so this testbench declares no functional design input at
        # all.  "Does it move a functional input?" then has nothing to be
        # asked about, and `driven == []` is NOT OBSERVED rather than NO.
        # Answering it anyway is the zero-denominator verdict this repo
        # refuses everywhere else, and it is not hypothetical: it is the
        # second half of the defect above — the mis-read emptied the set,
        # and this branch then read the empty set as proof of inertness and
        # printed "It never drives ['(none)']".
        out["reason"] = (
            "every bound drivable signal is a clock or reset "
            f"({out['clock_reset'] or ['(none)']}); the testbench declares "
            "no functional design input, so whether one is moved is not "
            "decidable from this source")
        return out
    out["decidable"] = True
    return out


def _cov_unused_stronger_stimulus(project: Path) -> Optional[str]:
    """Name a functional testbench this run HAS and this build did not use.

    Reported so the verdict points at the run's own evidence instead of leaving
    the reader to find it.  Returns None when there is nothing to name — the
    verdict then simply says no functional stimulus was present.
    """
    try:
        for res in sorted(
                project.glob("phase2/stage1/sim_professional/*/results.xml")):
            try:
                import _sim_results_bridge as _srb            # noqa: PLC0415
                summ = _srb.parse_junit(res)
            except Exception:                                  # noqa: BLE001
                summ = None
            if not summ or summ.get("tests", 0) <= 0:
                continue
            return (f"{res.parent.relative_to(project).as_posix()} "
                    f"(tests={summ['tests']} failures={summ['failures']} "
                    f"errors={summ['errors']})")
    except (OSError, ValueError):
        return None
    return None


def _cov_project_root(data: Dict[str, Any]) -> Optional[Path]:
    """The project this measurement belongs to, from its own recorded paths."""
    for key in ("rtl_sources", "scope_files"):
        for entry in (data.get(key) or []):
            parts = Path(str(entry)).parts
            if "phase2" in parts:
                return Path(*parts[:parts.index("phase2")])
    return None


def _report_no_measurement(args: argparse.Namespace, kind: str,
                           detail: str) -> int:
    """No coverage measurement exists at the declared path.

    Whether that is a DEFECT or a disclosed capability gap turns on one
    question the gate can answer for itself: was the toolchain that would
    have taken the measurement even installed?
      * absent  -> rc 3 + sentinel: EXPLAIN the gap (WAIVED-DEFERRED,
                   review_required, not counted as executed-PASS).
      * present -> rc 1: the capability existed and the measurement was
                   simply never taken. That is a defect, not an exemption.
    """
    tool = shutil.which(args.verilator_bin)
    if tool is None:
        print(f"[check] coverage NOT measured — {detail}")
        print(f"[check] {args.verilator_bin!r} is not on PATH, so no "
              f"line/toggle/branch coverage could have been produced on this "
              f"host. Disclosing a named capability gap "
              f"({COVERAGE_CAPABILITY}) — NOT certifying the step. "
              f"Remediation: install Verilator and run "
              f"`verilator_coverage_measure measure --out "
              f"{args.coverage_json}`.")
        print(f"{WAIVER_STDOUT_SENTINEL}: coverage deferred on "
              f"{COVERAGE_CAPABILITY} (review_required — a tapeout review "
              f"must close this before production)")
        return WAIVER_EXIT_CODE
    print(f"[check] FAIL — {detail}", file=sys.stderr)
    print(f"[check] {args.verilator_bin!r} IS installed ({tool}): the "
          f"capability to measure coverage was available and no measurement "
          f"was taken. This is a defect, not a capability gap.",
          file=sys.stderr)
    return 1


def cmd_check(args: argparse.Namespace) -> int:
    p = Path(args.coverage_json)
    kind, detail, data = classify_coverage_artefact(p)
    if kind in _DEFECT_KINDS:
        # A file that exists at the declared coverage path but is corrupt,
        # mislabelled-as-coverage, or forged is a DEFECT — never the
        # "input not applicable" exemption. Before the coverage-credit split all three
        # returned rc=2 and bought the step a PASS-counted VACUOUS_PASS.
        print(f"[check] artefact not tool-generated ({kind}): {detail}",
              file=sys.stderr)
        return 1
    if kind in _NO_MEASUREMENT_KINDS:
        return _report_no_measurement(args, kind, detail)
    # ── WHAT WAS THE PERCENTAGE MEASURED ON? ─────────────────────────────
    # A number produced by a testbench that never moved a design input is not
    # a coverage measurement of the design.  Reporting it against a functional
    # threshold reads as an RTL quality defect and sends the reader to the
    # wrong file.  This still BLOCKS — unmeasured is not verified — it just
    # stops blocking for the wrong reason.  Undecidable audits fall through.
    # A UNION IS DRIVEN IF ANY MEMBER DRIVES. `testbenches` is the honest
    # population when the measurement is a union; `testbench` names one member
    # and is what a pre-union payload carries, so both are consulted and the
    # question asked of the set is the one this block has always asked of the
    # single file: did ANY stimulus move a design input. Refusing a suite
    # because its first member happens to be inert would re-introduce, on the
    # judging side, exactly the one-member-stands-for-the-whole error the
    # measuring side just stopped making.
    _tbs = [str(x) for x in (data.get("testbenches") or []) if x]
    if not _tbs and data.get("testbench"):
        _tbs = [str(data["testbench"])]
    _tb = _tbs[0] if _tbs else None
    if _tb:
        _audits = [functional_stimulus_audit(Path(x)) for x in _tbs]
        for _one_tb in _tbs:
            if Path(_one_tb).suffix != ".py":
                continue
            _one_dat = ((data.get("per_testbench") or {}).get(_one_tb) or {}).get(
                "coverage_dat", data.get("coverage_dat"))
            _refusal = _check_professional_execution(Path(_one_tb), Path(_one_dat or ""))
            if _refusal:
                print(f"[check] PROFESSIONAL_COVERAGE_EVIDENCE_REFUSED: {_one_tb}: {_refusal}")
                return 1
        _audit = next((a for a in _audits if a["decidable"] and a["driven"]),
                      _audits[0])
        if _audit["decidable"] and not _audit["driven"]:
            _proj = _cov_project_root(data)
            _unused = _cov_unused_stronger_stimulus(_proj) if _proj else None
            # THE VERDICT GOES TO STDOUT.  This block first shipped writing
            # all five lines to stderr, and the sentence it exists to say
            # never reached the step record.  MEASURED, sha256 x sky130A on
            # v1.16.41: stdout 0 bytes, stderr 859 bytes;
            # `flow_compliance_check.output_snippet` keeps
            # `_head_and_tail(stdout)` but only `_grown_tail(stderr, 300)` —
            # a deliberate asymmetry its own docstring explains, because
            # stderr is the CRASH channel and a crash's evidence is its tail.
            # So the headline, being FIRST, was cut before the caller's
            # `out[:200]` ever ran, and the step record showed line 4:
            #
            #   output: [check] this run HAS a functional testbench that was
            #           not instrumented: ...
            #
            # Widening that 200 does NOT fix it: the sentence is not in the
            # 344-byte snippet at all.  Nor is the fix to change the stderr
            # window — that window is load-bearing for crash detection and is
            # pinned by `test_crash_is_flagged_as_a_crash_at_any_checkout_depth`.
            #
            # The defect is a CHANNEL one, and it is mine: a gate's verdict is
            # stdout, and stderr is where a crash lands.  Writing a structured
            # verdict into the crash channel got it treated as crash tail.
            # Moving it back is not betting on which line a consumer picks —
            # `_head_and_tail` keeping the head is that function's stated
            # contract, not an accident of position.
            print("[check] NO FUNCTIONAL STIMULUS IN THE COVERAGE BUILD — "
                  "this run measured no coverage of the design.")
            print(f"[check] the instrumented testbench was {_tb}, and of the "
                  f"signal(s) it binds to the design and declares drivable it "
                  f"assigns only {_audit['clock_reset'] or ['(none)']} — the "
                  f"clock and reset.  It never drives "
                  f"{_audit['inert'] or ['(none)']}, so the design's inputs "
                  f"were never moved.")
            if _audit["self_declared_connectivity_only"]:
                print("[check] the testbench says so itself: its header "
                      "declares it connectivity-only.")
            if _unused:
                print(f"[check] this run HAS a functional testbench that was "
                      f"not instrumented: {_unused}. Point the coverage build "
                      f"at a stimulus that exercises the design.")
            else:
                print("[check] no functional testbench was found in this "
                      "run to instrument instead.")
            print(f"[check] the recorded percentages "
                  f"(line {data['totals']['line']['pct']}%, "
                  f"toggle {data['totals']['toggle']['pct']}%, "
                  f"branch {data['totals']['branch']['pct']}%) describe that "
                  f"testbench, NOT the RTL, and are NOT graded here.")
            return 1

    # TWO PRODUCERS OF ONE LINE UNION MUST AGREE. The tool's lcov union and
    # the h-stripped union answer the same question; a measured disagreement
    # means one of the two published line numbers is wrong, and which one is
    # not decidable here. An unmeasured cross-check is disclosed, not failed.
    _xc = data.get("line_union_cross_check")
    if isinstance(_xc, dict) and _xc.get("status") == "MEASURED" \
            and _xc.get("agree") is False:
        print("[check] LINE_UNION_DISAGREES: verilator_coverage --write-info "
              "and the h-stripped suite union name different lines or hits: "
              + json.dumps(_xc.get("mismatches"))[:600])
        return 1

    totals = data["totals"]
    # Older reports can carry a v_line-only headline beside a measured native
    # LCOV union. The line floor consumes that same executable-line population.
    if isinstance(_xc, dict) and _xc.get('status') == 'MEASURED':
        line_pct = _xc['lcov_line_totals']['pct']
    elif data.get('line_metric') in ('category_points', 'NOT_MEASURED'):
        print('[check] executable-line coverage NOT_MEASURED; category points are not the line floor')
        return 1
    else:
        line_pct = totals["line"]["pct"]
    toggle_pct = totals["toggle"]["pct"]
    branch_pct = totals["branch"]["pct"]
    below = []
    if line_pct < args.min_line:
        below.append(f"line {line_pct}% < {args.min_line}%")
    if toggle_pct < args.min_toggle:
        below.append(f"toggle {toggle_pct}% < {args.min_toggle}%")
    if branch_pct < args.min_branch:
        below.append(f"branch {branch_pct}% < {args.min_branch}%")
    if below:
        print("[check] below threshold(s):", "; ".join(below), file=sys.stderr)
        return 1
    print(
        f"[check] PASS  line={line_pct}%  toggle={toggle_pct}%  branch={branch_pct}%"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="mode", required=True)

    m = sub.add_parser("measure", help="Verilate + run + parse + write JSON")
    m.add_argument("--rtl-dir", required=True)
    m.add_argument("--top", required=True)
    m.add_argument("--main", required=True, help="path to Verilator main.cpp driver")
    m.add_argument("--build-dir", default="phase2/stage1/sim/cov_build")
    m.add_argument("--out", required=True)
    m.add_argument("--min-line", type=float, default=70.0)
    m.add_argument("--min-toggle", type=float, default=60.0)
    m.add_argument("--min-branch", type=float, default=70.0)
    m.add_argument("--container", default="", help='name of the container the instrumented run was dispatched into. Given, its bind mounts translate the paths VERILATOR reports back to the host spelling this report is written in (#2180). Omit for a run whose Verilator executed here — nothing is then rewritten and nothing is claimed.')
    m.set_defaults(func=cmd_measure)

    mt = sub.add_parser(
        "measure-tb",
        help=("Instrument the project's own Verilog testbench with "
              "verilator --binary --timing --coverage and measure the run"))
    mt.add_argument("--project", help="project root; discovers RTL + testbench")
    mt.add_argument("--rtl", action="append",
                    help="RTL source (repeatable); overrides discovery")
    mt.add_argument("--tb", help="testbench file; overrides discovery")
    mt.add_argument("--scope-file", action="append",
                    help=("source whose points are totalled (repeatable). "
                          "Default: the RTL sources, so the testbench's own "
                          "coverage never inflates the design's."))
    mt.add_argument("--build-dir")
    mt.add_argument("--run-dir")
    mt.add_argument("--build-jobs", type=int, default=0)
    mt.add_argument("--out", required=True)
    mt.add_argument("--min-line", type=float, default=70.0)
    mt.add_argument("--min-toggle", type=float, default=60.0)
    mt.add_argument("--min-branch", type=float, default=70.0)
    mt.add_argument("--container", default="", help='name of the container the instrumented run was dispatched into. Given, its bind mounts translate the paths VERILATOR reports back to the host spelling this report is written in (#2180). Omit for a run whose Verilator executed here — nothing is then rewritten and nothing is claimed.')
    mt.set_defaults(func=cmd_measure_tb)

    c = sub.add_parser("check", help="Verify an existing coverage measurement")
    c.add_argument("--coverage-json", required=True)
    c.add_argument("--min-line", type=float, default=70.0)
    c.add_argument("--min-toggle", type=float, default=60.0)
    c.add_argument("--min-branch", type=float, default=70.0)
    c.add_argument(
        "--verilator-bin", default=VERILATOR_BIN_DEFAULT,
        help=("executable whose presence on PATH decides whether an absent "
              f"measurement is a disclosed capability gap (rc=3) or a defect "
              f"(rc=1). Overridable via ${VERILATOR_BIN_ENV} so a harness can "
              f"pin the capability decision instead of inheriting the host's. "
              f"Default: verilator"))
    c.set_defaults(func=cmd_check)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
