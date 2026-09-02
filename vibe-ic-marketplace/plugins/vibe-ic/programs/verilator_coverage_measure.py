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
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
    vcmd += [str(tb)] + [str(f) for f in rtl_files]
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

    def pct(pair: List[int]) -> float:
        return round(100.0 * pair[0] / pair[1], 2) if pair[1] > 0 else 0.0

    return {
        "totals": {c: {"covered": agg[c][0], "total": agg[c][1],
                       "pct": pct(agg[c])} for c in agg},
        "scope_files": sorted(matched),
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
COVERAGE_LINE_RE = re.compile(r"^C\s+'([^']*)'\s+(\d+)\s*$")

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


def parse_coverage_dat(path: str) -> Dict[str, Any]:
    """Parse Verilator coverage.dat into per-category counts + per-file
    breakdown. Auto-detects 4.x vs 5.x record format on the first
    classifiable record so a single coverage.dat from either version
    works without a flag."""
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

    def pct(pair: List[int]) -> float:
        return round(100.0 * pair[0] / pair[1], 2) if pair[1] > 0 else 0.0

    return {
        "totals": {
            "line": {"covered": cats["line"][0], "total": cats["line"][1], "pct": pct(cats["line"])},
            "toggle": {"covered": cats["toggle"][0], "total": cats["toggle"][1], "pct": pct(cats["toggle"])},
            "branch": {"covered": cats["branch"][0], "total": cats["branch"][1], "pct": pct(cats["branch"])},
        },
        "per_file": {
            src: {k: {"covered": v[0], "total": v[1], "pct": pct(v)} for k, v in pf.items()}
            for src, pf in per_file.items()
        },
        "format_detected": classifier or "unknown",
    }


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


def cmd_measure(args: argparse.Namespace) -> int:
    dat = verilate_and_run(args.rtl_dir, args.top, args.main, args.build_dir)
    cov = parse_coverage_dat(dat)
    out = {
        "tool": "verilator",
        "coverage_dat": dat,
        **cov,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
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
)


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
    tb: Optional[str] = None
    for rel, pat in _TB_DISCOVERY_ORDER:
        hits = sorted((project / rel).glob(pat)) if (project / rel).is_dir() \
            else []
        if hits:
            tb = str(hits[0])
            break
    return rtl, tb


def cmd_measure_tb(args: argparse.Namespace) -> int:
    """Instrument + run the project's own testbench and write the measurement."""
    rtl = list(args.rtl or [])
    tb = args.tb
    if args.project:
        d_rtl, d_tb = discover_measure_inputs(Path(args.project))
        rtl = rtl or d_rtl
        tb = tb or d_tb
    if not rtl:
        print("[measure-tb] no RTL sources found to instrument",
              file=sys.stderr)
        return 1
    if not tb:
        print("[measure-tb] no testbench found to instrument — coverage "
              "cannot be measured without a stimulus that actually ran",
              file=sys.stderr)
        return 1

    default_build = (Path(args.project) / "phase2" / "stage1" / "sim"
                     / "cov_build") if args.project \
        else (Path(args.out).parent / "cov_build")
    build_dir = args.build_dir or str(default_build)
    run_dir = args.run_dir or build_dir
    dat = verilate_tb_and_run(rtl, tb, build_dir, run_dir,
                              build_jobs=args.build_jobs)
    cov = parse_coverage_dat(dat)
    scope = args.scope_file or rtl
    scoped = scope_totals(cov, scope)
    if scoped is None:
        print(f"[measure-tb] the instrumented run recorded no coverage points "
              f"for any of {[Path(x).name for x in scope]} — refusing to "
              f"report the unscoped total in their place", file=sys.stderr)
        return 1
    out = {
        "tool": "verilator",
        "measurement_mode": "measure-tb",
        "coverage_dat": dat,
        "testbench": tb,
        "rtl_sources": [str(x) for x in rtl],
        "totals": scoped["totals"],
        "scope_files": scoped["scope_files"],
        "per_file": cov["per_file"],
        "format_detected": cov["format_detected"],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    t = scoped["totals"]
    print(f"[measure-tb] line={t['line']['pct']}% "
          f"toggle={t['toggle']['pct']}% branch={t['branch']['pct']}% "
          f"(scope {scoped['scope_files']}, from {dat}) -> {args.out}")
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
#: `<name> = ...` (blocking, never `==`/`<=`/`>=`/`!=`) or `<name> <= ...`.
_COV_DRIVE_RE_TMPL = r"\b{name}\s*(?:<=(?!=)|(?<![<>=!])=(?!=))"
#: A module instantiation's named port connections: `.port(signal)`.
_COV_PORT_BIND_RE = re.compile(r"\.\s*(\w+)\s*\(\s*([\w\[\]:\s]*?)\s*\)")
#: `reg [31:0] name = 0;` / `reg name;` — the declaration, which is not a drive.
_COV_REG_DECL_RE = re.compile(
    r"(?m)^\s*reg\b[^;\n]*?\b(\w+)\s*(?:=[^;\n]*)?\s*[;,]")


def _cov_strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def functional_stimulus_audit(tb_path: Path) -> Dict[str, Any]:
    """Does this testbench ever move a DUT input other than clock and reset?

    Returns a record with `decidable`, `driven` (the functional inputs it does
    drive), `inert` (bound + drivable + never assigned) and
    `self_declared_connectivity_only`.  When the testbench cannot be read or
    carries no recognisable instantiation the audit is NOT decidable and the
    caller must fall through to its normal behaviour — an audit that cannot see
    must never be the reason a run is judged.
    """
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
    declared_reg = set(_COV_REG_DECL_RE.findall(body))
    drivable = sorted(bound & declared_reg)
    if not drivable:
        out["reason"] = ("no bound signal is declared `reg`, so the drivable "
                         "set cannot be determined")
        return out
    # Remove the declarations themselves: initialising at declaration is not
    # stimulus, it is the starting value.
    stripped = _COV_REG_DECL_RE.sub(" ", body)
    for name in drivable:
        drives = re.search(_COV_DRIVE_RE_TMPL.format(name=re.escape(name)),
                           stripped)
        if _COV_CLK_RST_RE.search(name):
            out["clock_reset"].append(name)
        elif drives:
            out["driven"].append(name)
        else:
            out["inert"].append(name)
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
    _tb = data.get("testbench")
    if _tb:
        _audit = functional_stimulus_audit(Path(str(_tb)))
        if _audit["decidable"] and not _audit["driven"]:
            _proj = _cov_project_root(data)
            _unused = _cov_unused_stronger_stimulus(_proj) if _proj else None
            print("[check] NO FUNCTIONAL STIMULUS IN THE COVERAGE BUILD — "
                  "this run measured no coverage of the design.",
                  file=sys.stderr)
            print(f"[check] the instrumented testbench was {_tb}, and of the "
                  f"signal(s) it binds to the design and declares drivable it "
                  f"assigns only {_audit['clock_reset'] or ['(none)']} — the "
                  f"clock and reset.  It never drives "
                  f"{_audit['inert'] or ['(none)']}, so the design's inputs "
                  f"were never moved.", file=sys.stderr)
            if _audit["self_declared_connectivity_only"]:
                print("[check] the testbench says so itself: its header "
                      "declares it connectivity-only.", file=sys.stderr)
            if _unused:
                print(f"[check] this run HAS a functional testbench that was "
                      f"not instrumented: {_unused}. Point the coverage build "
                      f"at a stimulus that exercises the design.",
                      file=sys.stderr)
            else:
                print("[check] no functional testbench was found in this run "
                      "to instrument instead.", file=sys.stderr)
            print(f"[check] the recorded percentages "
                  f"(line {data['totals']['line']['pct']}%, "
                  f"toggle {data['totals']['toggle']['pct']}%, "
                  f"branch {data['totals']['branch']['pct']}%) describe that "
                  f"testbench, NOT the RTL, and are NOT graded here.",
                  file=sys.stderr)
            return 1

    totals = data["totals"]
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
