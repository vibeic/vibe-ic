#!/usr/bin/env python3
"""Caravel user_project_wrapper HARDEN + full-chip MERGE + live XOR driver.

TAPEOUT-SIGNOFF P0#3 (LIVE half). This is the executable half of the Caravel
integration flow: it turns the plan-only `NOT_RUN` stub of
`caravel_integration_runner.step_b1_openlane_wrapper_pnr` into an ACTUAL
OpenLane hardening of `user_project_wrapper` at Caravel's FIXED
2.92 x 3.52 mm outline + fixed pad-ring / core-ring (the `config.json` the
caravel project ships), then MERGES the hardened wrapper GDS into the golden
full-chip `caravel.gds` (top cell = caravel), then FEEDS the assembled GDS +
golden reference + a blackbox-macro allow-list into `xor_layout_check.py` for a
real, computed layer-by-layer XOR verdict.

Why a driver (not inline in the runner)
=======================================
The three live operations (OpenLane harden, KLayout full-chip merge, KLayout
XOR) each need a real EDA image + PDK + golden geometry that a unit test cannot
carry. So each is written as a pure PLAN/PREFLIGHT function plus a live RUN that
takes an INJECTABLE runner callable. That lets the orchestration + the XOR-feed
wiring be unit-tested with mocks (a synthetic hardened wrapper + golden -> the
XOR gate actually runs) while the live path stays a single real `docker run`.

§4.05 honesty invariants (enforced + unit-tested)
=================================================
  * A missing OpenLane image / missing PDK / missing project config -> the
    harden is BLOCKED with EXACTLY the list of missing prerequisites. It is
    NEVER reported as a hardened GDS that does not exist.
  * The full-chip MERGE and the XOR are ONLY attempted when the upstream step
    produced a real artifact on disk. A NOT_RUN / FAILED / BLOCKED harden
    short-circuits the chain to BLOCKED -- a XOR is never run against a
    fabricated / absent assembled GDS, so a clean XOR can never be manufactured
    from a harden that did not happen.
  * The XOR verdict itself is delegated to `xor_layout_check.evaluate`, whose
    own §4.05 rules apply (absent report / GDS -> INCOMPLETE, waiver only
    swallows residual inside an EXPLICIT allow-listed macro).

Chip-AGNOSTIC: the design name, top cell, wrapper cell, outline, image, PDK and
allow-list are ALL caller-supplied. No design-specific literal is baked in.

CLI
===
  # (1) plan the harden (no live run) -- prints the docker command + any missing prereqs
  python3 caravel_wrapper_harden_driver.py harden \
      --project-dir caravel_user_project --design user_project_wrapper

  # (2) live harden (needs image + PDK + project config)
  python3 caravel_wrapper_harden_driver.py harden --run \
      --project-dir caravel_user_project --design user_project_wrapper \
      --image efabless/openlane:2023.07.19-1 --pdk-root $PDK_ROOT

  # (3) full-chip merge: hardened wrapper GDS -> golden caravel base -> assembled
  python3 caravel_wrapper_harden_driver.py merge --run \
      --base golden_caravel.gds --wrapper user_project_wrapper.gds \
      --out caravel_assembled.gds --top caravel --wrapper-cell user_project_wrapper

  # (4) live XOR: assembled vs golden, with an explicit blackbox-macro allow-list
  python3 caravel_wrapper_harden_driver.py xor --run \
      --assembled caravel_assembled.gds --golden golden_caravel.gds --top caravel \
      --allow-macro user_proj_example --report-out xor_report.json

Exit codes:  0 = PASS / PASS_WITH_WAIVER,  1 = FAIL,  2 = BLOCKED / NOT_RUN.

Unit tests: `programs/tests/test_caravel_wrapper_harden_driver.py`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# xor_layout_check lives beside this file; import both flat + packaged.
try:
    import xor_layout_check as xlc
except ImportError:  # pragma: no cover
    from . import xor_layout_check as xlc  # type: ignore

EMITTED_BY = "vibe-ic plugin caravel_wrapper_harden_driver v1"
OPENLANE_IMAGE_DEFAULT = "efabless/openlane:2023.07.19-1"

# A runner is any callable (list[str]|str) -> (rc, stdout, stderr). Injected in
# tests so the wiring can be exercised with no live EDA image.
Runner = Callable[..., Tuple[int, str, str]]


@dataclass
class DriverResult:
    step: str              # "harden" / "merge" / "xor"
    verdict: str           # PASS / PASS_WITH_WAIVER / FAIL / BLOCKED / NOT_RUN
    details: Dict[str, Any] = field(default_factory=dict)
    blocked_reason: str = ""
    command_hint: str = ""
    artifact: Optional[str] = None   # produced GDS / report path

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Shared subprocess runner (TimeoutExpired-safe: .stdout may be bytes)
# ---------------------------------------------------------------------------
def default_runner(cmd, timeout: int = 3600) -> Tuple[int, str, str]:
    """Run an argv (or shell string) and return (rc, stdout, stderr)."""
    shell = isinstance(cmd, str)
    try:
        cp = subprocess.run(cmd, shell=shell, capture_output=True,
                            timeout=timeout)
        out = cp.stdout.decode("utf-8", "replace") if cp.stdout else ""
        err = cp.stderr.decode("utf-8", "replace") if cp.stderr else ""
        return cp.returncode, out, err
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired as e:  # pragma: no cover - env dependent
        def _dec(x):
            if x is None:
                return ""
            return x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x)
        return 124, _dec(e.stdout), f"timeout after {timeout}s"


def docker_image_available(image: str,
                           runner: Optional[Runner] = None) -> bool:
    """True iff `docker images` lists `image`. Injectable for tests."""
    runner = runner or default_runner
    rc, out, _ = runner(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        timeout=60)
    if rc != 0:
        return False
    want = image if ":" in image else image + ":"
    for line in out.splitlines():
        line = line.strip()
        if line == image or line == want or line.startswith(image + ":"):
            return True
        if ":" not in image and line.startswith(image + ":"):
            return True
    return False


# ---------------------------------------------------------------------------
# (1) HARDEN — OpenLane run of the wrapper at the fixed outline
# ---------------------------------------------------------------------------
def _resolve_pdk_root(pdk_root: Optional[str]) -> Optional[str]:
    return pdk_root or os.environ.get("PDK_ROOT") or None


def wrapper_config_path(project_dir: Path, design: str) -> Path:
    """OpenLane-1 config location: openlane/<design>/config.json."""
    return project_dir / "openlane" / design / "config.json"


def preflight_harden(project_dir: Path, design: str, image: str,
                     pdk_root: Optional[str],
                     runner: Optional[Runner] = None) -> List[str]:
    """Return the list of MISSING prerequisites for a live harden (empty = ok).

    Each entry is a precise, actionable string so a BLOCKED verdict tells a
    submitter EXACTLY what to supply."""
    missing: List[str] = []
    if not docker_image_available(image, runner=runner):
        missing.append(f"OpenLane docker image not available: {image} "
                       "(docker pull it, or pass --image)")
    resolved = _resolve_pdk_root(pdk_root)
    if not resolved:
        missing.append("sky130A PDK not found: set PDK_ROOT (or pass "
                       "--pdk-root) to a built sky130A PDK directory")
    elif not Path(resolved).is_dir():
        missing.append(f"PDK_ROOT is not a directory: {resolved}")
    elif not (Path(resolved) / "sky130A").is_dir():
        missing.append(f"PDK_ROOT has no sky130A sub-PDK: {resolved}/sky130A")
    cfg = wrapper_config_path(project_dir, design)
    if not project_dir.is_dir():
        missing.append(f"caravel project dir absent: {project_dir}")
    elif not cfg.is_file():
        missing.append(f"wrapper OpenLane config absent: {cfg}")
    return missing


def build_harden_command(project_dir: Path, design: str, image: str,
                         pdk_root: Optional[str],
                         tag: str = "harden") -> List[str]:
    """The `docker run ... flow.tcl` argv that hardens the wrapper at its fixed
    outline. Uses OpenLane-1 `flow.tcl -design <path>`; the design's own
    config.json carries the FIXED DIE_AREA / pad-ring / core-ring so the outline
    is never hand-set here (chip-AGNOSTIC)."""
    resolved = _resolve_pdk_root(pdk_root) or "$PDK_ROOT"
    proj = str(project_dir.resolve()) if project_dir.exists() else str(project_dir)
    return [
        "docker", "run", "--rm",
        "-v", f"{proj}:/work",
        "-v", f"{resolved}:/pdk",
        "-e", "PDK_ROOT=/pdk",
        "-e", "PDK=sky130A",
        image,
        "flow.tcl",
        "-design", f"/work/openlane/{design}",
        "-tag", tag,
        "-overwrite",
    ]


def harden_command_hint(project_dir: Path, design: str, image: str,
                        pdk_root: Optional[str]) -> str:
    """Human-facing command hint (both the canonical caravel `make` target and
    the underlying explicit `flow.tcl` docker invocation)."""
    argv = build_harden_command(project_dir, design, image, pdk_root)
    return (f"cd {project_dir} && make {design}   "
            f"# canonical caravel harden; underlying: "
            + " ".join(argv))


def find_hardened_gds(project_dir: Path, design: str,
                      tag: Optional[str] = None) -> Optional[Path]:
    """Locate the hardened GDS the OpenLane run produced, newest first.

    OpenLane-1 layout: openlane/<design>/runs/<tag>/results/final/gds/<design>.gds
    (older runs used results/magic/<design>.gds). Chip-AGNOSTIC glob.

    §4.05 honesty: when `tag` is given, the search is SCOPED to that run's tag
    directory ONLY. This is critical -- an untagged (all-runs) search lets a
    STALE GDS from an earlier, unrelated run mask the CURRENT invocation that
    produced nothing (e.g. an OpenLane PDK-version-guard abort), which would
    fabricate a PASS off a GDS this run never made. Passing None keeps the
    legacy all-runs behaviour for callers that genuinely want the newest."""
    runs = project_dir / "openlane" / design / "runs"
    if not runs.is_dir():
        return None
    base = f"{tag}" if tag else "*"
    cands: List[Path] = []
    for pat in (f"{base}/results/final/gds/{design}.gds",
                f"{base}/results/magic/{design}.gds",
                f"{base}/results/**/{design}.gds"):
        cands.extend(runs.glob(pat))
    cands = [c for c in cands if c.is_file()]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def find_hardened_gl_netlists(project_dir: Path, design: str,
                              tag: Optional[str] = None) -> List[Path]:
    """Locate the gate-level Verilog netlist(s) the OpenLane run produced.

    OpenLane-1 layout: openlane/<design>/runs/<tag>/results/final/verilog/gl/
    holds the hardened gl netlists -- the primary `<design>.v` (the one the
    Efabless mpw_precheck reads as `verilog/gl/<design>.v` for its Consistency
    and LVS checks) plus siblings such as `<design>.nl.v`. Chip-AGNOSTIC glob.

    §4.05 honesty (identical to `find_hardened_gds`): when `tag` is given the
    search is SCOPED to that run's tag directory ONLY, so a STALE gl netlist from
    an earlier unrelated run can never mask a CURRENT invocation that produced
    nothing -- which would let a fabricated netlist be staged into the project and
    manufacture a Consistency/LVS pass off a harden that did not happen. Passing
    None keeps the newest-run behaviour for callers that genuinely want it.

    Returns the produced gl netlists ordered with `<design>.v` FIRST (so the
    primary user netlist leads), then the remaining siblings, all from the single
    newest gl directory. Empty list when the harden produced no gl netlist."""
    runs = project_dir / "openlane" / design / "runs"
    if not runs.is_dir():
        return []
    base = f"{tag}" if tag else "*"
    all_gl = [p for p in runs.glob(f"{base}/results/final/verilog/gl/*.v")
              if p.is_file()]
    if not all_gl:
        return []
    # Scope to the SINGLE newest gl directory (one run's netlists), so we never
    # mix netlists from two different runs.
    newest = max(all_gl, key=lambda p: p.stat().st_mtime)
    gl_dir = newest.parent
    files = sorted(p for p in gl_dir.glob("*.v") if p.is_file())
    primary = gl_dir / f"{design}.v"
    ordered: List[Path] = []
    if primary in files:
        ordered.append(primary)
    ordered.extend(p for p in files if p != primary)
    return ordered


def run_stage_gl(project_dir: Path, design: str,
                 tag: Optional[str] = None,
                 gl_netlists: Optional[List[Path]] = None,
                 dest_dir: Optional[Path] = None) -> DriverResult:
    """STAGE the harden's produced gl netlist(s) into the project's `verilog/gl/`.

    This is the missing wire between the OpenLane harden and the Efabless
    mpw_precheck: the precheck's Consistency + LVS checks read the user netlist at
    `<project>/verilog/gl/<design>.v` (see mpw_precheck
    checks/utils/utils.py: `user_netlist = project_path / "verilog/gl/<design>.v"`),
    but the OpenLane harden writes it under
    `openlane/<design>/runs/<tag>/results/final/verilog/gl/<design>.v`. Without
    this copy the Consistency check FAILs with "user_project_wrapper.v file was
    not found in verilog/gl" and LVS has no user netlist to compare.

    §4.05 honesty invariants (unit-tested):
      * Stages ONLY gl netlists that ACTUALLY exist on disk from the harden. If
        the harden produced NONE, returns BLOCKED and writes NOTHING -- never an
        empty / fabricated netlist -- so the precheck Consistency/LVS still FAIL
        honestly.
      * When `tag` is given the source search is tag-scoped (via
        `find_hardened_gl_netlists`), so a stale prior-run netlist can never be
        staged in place of a current run that produced nothing."""
    project_dir = Path(project_dir)
    dest_dir = Path(dest_dir) if dest_dir else (project_dir / "verilog" / "gl")
    if gl_netlists is None:
        gl_netlists = find_hardened_gl_netlists(project_dir, design, tag=tag)
    else:
        gl_netlists = [Path(p) for p in gl_netlists if Path(p).is_file()]
    if not gl_netlists:
        return DriverResult(
            "stage_gl", "BLOCKED",
            details={"design": design, "dest_dir": str(dest_dir),
                     "staged": [],
                     "note": ("harden produced no gl netlist under "
                              "runs/*/results/final/verilog/gl -- nothing staged "
                              "(§4.05: never fabricate a netlist; the precheck "
                              "Consistency/LVS still FAIL honestly)")},
            blocked_reason="no produced gl netlist to stage into verilog/gl")
    dest_dir.mkdir(parents=True, exist_ok=True)
    staged: List[str] = []
    for src in gl_netlists:
        dst = dest_dir / src.name
        shutil.copy2(str(src), str(dst))
        staged.append(str(dst))
    return DriverResult(
        "stage_gl", "PASS",
        details={"design": design, "dest_dir": str(dest_dir),
                 "staged": staged,
                 "source_gl_dir": str(gl_netlists[0].parent)},
        artifact=str(dest_dir / f"{design}.v"))


def run_harden(project_dir: Path, design: str,
               image: str = OPENLANE_IMAGE_DEFAULT,
               pdk_root: Optional[str] = None,
               run: bool = False,
               tag: str = "harden",
               runner: Optional[Runner] = None,
               timeout: int = 7200,
               stage_gl: bool = False) -> DriverResult:
    """Harden the wrapper. run=False -> NOT_RUN plan (command hint + missing
    prereqs). run=True -> live: BLOCKED if prereqs missing (never a fake GDS),
    else run OpenLane and PASS iff a hardened GDS lands on disk, else FAIL.

    `stage_gl=True` wires the harden's success path into the precheck input: on a
    clean PASS the produced gl netlist(s) are staged into `verilog/gl/` (via
    `run_stage_gl`, tag-scoped) so mpw_precheck's Consistency + LVS checks can
    read `verilog/gl/<design>.v`. The stage result is recorded under
    details["gl_staged"] and NEVER upgrades or fabricates the harden verdict -- a
    non-PASS harden stages nothing (§4.05)."""
    project_dir = Path(project_dir)
    runner = runner or default_runner
    hint = harden_command_hint(project_dir, design, image, pdk_root)
    missing = preflight_harden(project_dir, design, image, pdk_root,
                               runner=runner)
    if not run:
        return DriverResult(
            "harden", "NOT_RUN",
            details={"design": design, "image": image,
                     "missing_prerequisites": missing,
                     "outline_source": str(wrapper_config_path(project_dir, design))},
            command_hint=hint,
            blocked_reason="" if not missing else
                           "live run would be BLOCKED: " + "; ".join(missing))
    if missing:
        return DriverResult(
            "harden", "BLOCKED",
            details={"design": design, "image": image,
                     "missing_prerequisites": missing},
            blocked_reason="; ".join(missing),
            command_hint=hint)
    argv = build_harden_command(project_dir, design, image, pdk_root, tag=tag)
    rc, out, err = runner(argv, timeout=timeout)
    # §4.05: scope the GDS search to THIS run's tag so a stale prior-run GDS can
    # never mask a current invocation that produced nothing.
    gds = find_hardened_gds(project_dir, design, tag=tag)
    if gds is not None and rc == 0:
        details: Dict[str, Any] = {"design": design, "rc": rc,
                                   "stdout_tail": out[-2000:],
                                   "stderr_tail": err[-2000:]}
        if stage_gl:
            # Wire the success path into the precheck input: stage the produced
            # gl netlist(s) into verilog/gl/ (tag-scoped -> only THIS run's
            # netlists). This never changes the harden verdict.
            details["gl_staged"] = run_stage_gl(
                project_dir, design, tag=tag).as_dict()
        return DriverResult(
            "harden", "PASS", details=details,
            command_hint=hint, artifact=str(gds))
    if gds is not None and rc != 0:
        # OpenLane produced a GDS for THIS run but the flow itself exited
        # non-zero -- e.g. the end-of-flow KLayout XOR signoff tripped
        # `quit_on_xor_error` (a known blackbox-macro streamout floor), or a
        # late signoff/STA failure. The place+route may well have converged, but
        # the flow did NOT sign off, so this is NOT a clean PASS. Record the
        # produced GDS in details (not as `artifact`, so the merge/XOR chain does
        # not treat an un-signed-off layout as a deliverable), and FAIL honestly.
        return DriverResult(
            "harden", "FAIL",
            details={"design": design, "rc": rc,
                     "produced_gds_but_flow_failed": str(gds),
                     "stdout_tail": out[-4000:], "stderr_tail": err[-4000:],
                     "note": ("OpenLane produced a hardened GDS for this run but "
                              "the flow exited non-zero (did NOT sign off) -- "
                              "e.g. the end-of-flow KLayout XOR signoff hit "
                              "quit_on_xor_error on a blackbox macro. Not a "
                              "clean PASS; inspect the run's signoff logs.")},
            command_hint=hint)
    return DriverResult(
        "harden", "FAIL",
        details={"design": design, "rc": rc,
                 "stdout_tail": out[-4000:], "stderr_tail": err[-4000:],
                 "note": ("OpenLane produced no hardened GDS for this run "
                          "-- inspect the run log (e.g. a DRT-0302 multi-bterm "
                          "power-net routing wall, a PDK-version-guard abort, or "
                          "a synth/floorplan error)")},
        command_hint=hint)


# ---------------------------------------------------------------------------
# (2) MERGE — hardened wrapper into the golden full-chip caravel base
# ---------------------------------------------------------------------------
# KLayout pya merge: read the golden/base full-chip GDS (which instantiates the
# wrapper cell -- possibly as an empty abstract), replace that wrapper cell's
# contents with the hardened wrapper geometry (copy_tree across layouts), and
# write the assembled full-chip GDS with the top cell unchanged. Chip-AGNOSTIC:
# top cell + wrapper cell + paths are all parameters.
_MERGE_SCRIPT_TEMPLATE = '''\
# Auto-generated by {emitted_by} -- KLayout full-chip GDS merge.
# Replaces the (abstract) wrapper cell inside the golden full-chip base with the
# hardened wrapper geometry, keeping the base top cell. Run under
# `klayout -zz -b -r <script>`.
import os, sys, json
import pya

BASE = os.environ.get("MERGE_BASE", {base!r})       # golden full-chip base GDS
WRAP = os.environ.get("MERGE_WRAPPER", {wrapper!r})  # hardened wrapper GDS
OUT = os.environ.get("MERGE_OUT", {out!r})           # assembled full-chip GDS
TOP = os.environ.get("MERGE_TOP", {top!r})           # expected top cell (caravel)
WCELL = os.environ.get("MERGE_WRAPPER_CELL", {wcell!r})
STATUS = os.environ.get("MERGE_STATUS", {status!r})


def _status(obj):
    if STATUS:
        with open(STATUS, "w") as fh:
            json.dump(obj, fh, indent=2)


base = pya.Layout()
base.read(BASE)
wl = pya.Layout()
wl.read(WRAP)

src = wl.cell(WCELL)
if src is None:
    tops = wl.top_cells()
    src = tops[0] if tops else None
if src is None:
    _status({{"error": "wrapper cell not found in " + WRAP, "wrapper_cell": WCELL}})
    print("MERGE_ERROR wrapper-cell-not-found")
    sys.exit(3)

# Scale the wrapper into the base DBU if they differ.
if abs((wl.dbu or 0.001) - (base.dbu or 0.001)) > 1e-9:
    wl.dbu = wl.dbu  # keep; copy_tree scales by dbu automatically in KLayout

dst = base.cell(WCELL)
if dst is None:
    dst = base.create_cell(WCELL)
else:
    dst.clear()          # drop the abstract placeholder geometry+insts
dst.copy_tree(src)       # import hardened geometry (whole sub-hierarchy)

base_top = base.cell(TOP)
top_names = [c.name for c in base.top_cells()]
base.write(OUT)
_status({{"tool": "klayout-merge", "base": BASE, "wrapper": WRAP, "out": OUT,
          "top_expected": TOP, "top_present": (base_top is not None),
          "top_cells": top_names, "wrapper_cell": WCELL,
          "wrapper_shapes_merged": True}})
print("MERGE_WRITTEN " + OUT)
print("MERGE_TOP_PRESENT " + ("1" if base_top is not None else "0"))
'''


def build_merge_script(base_gds: str, wrapper_gds: str, out_gds: str,
                       top_cell: str, wrapper_cell: str,
                       status_out: str = "") -> str:
    """Return the pya KLayout full-chip merge script (chip-AGNOSTIC)."""
    return _MERGE_SCRIPT_TEMPLATE.format(
        emitted_by=EMITTED_BY, base=str(base_gds), wrapper=str(wrapper_gds),
        out=str(out_gds), top=str(top_cell), wcell=str(wrapper_cell),
        status=str(status_out))


def klayout_command_hint(script_path: str) -> str:
    return (f"export QT_QPA_PLATFORM=offscreen && "
            f"klayout -zz -b -r {script_path}")


def run_merge(base_gds: Path, wrapper_gds: Path, out_gds: Path,
              top_cell: str, wrapper_cell: str,
              run: bool = False,
              script_path: Optional[Path] = None,
              status_out: Optional[Path] = None,
              klayout_runner: Optional[Runner] = None,
              timeout: int = 1800) -> DriverResult:
    """Merge the hardened wrapper into the golden base. run=False -> NOT_RUN
    plan. Missing base/wrapper -> BLOCKED (never a fabricated assembled GDS)."""
    base_gds, wrapper_gds, out_gds = \
        Path(base_gds), Path(wrapper_gds), Path(out_gds)
    script_path = script_path or (out_gds.parent / "_merge_fullchip.py")
    status_out = status_out or (out_gds.parent / "_merge_status.json")
    hint = klayout_command_hint(str(script_path))
    missing = []
    if not Path(base_gds).is_file():
        missing.append(f"golden full-chip base GDS absent: {base_gds}")
    if not Path(wrapper_gds).is_file():
        missing.append(f"hardened wrapper GDS absent: {wrapper_gds}")
    if not run:
        return DriverResult(
            "merge", "NOT_RUN",
            details={"top": top_cell, "wrapper_cell": wrapper_cell,
                     "missing_prerequisites": missing},
            command_hint=hint,
            blocked_reason="" if not missing else "; ".join(missing))
    if missing:
        return DriverResult(
            "merge", "BLOCKED",
            details={"top": top_cell, "wrapper_cell": wrapper_cell,
                     "missing_prerequisites": missing},
            blocked_reason="; ".join(missing), command_hint=hint)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        build_merge_script(str(base_gds), str(wrapper_gds), str(out_gds),
                           top_cell, wrapper_cell, str(status_out)),
        encoding="utf-8")
    runner = klayout_runner or default_runner
    rc, out, err = runner(hint, timeout=timeout)
    if Path(out_gds).is_file():
        status: Dict[str, Any] = {}
        if Path(status_out).is_file():
            try:
                status = json.loads(Path(status_out).read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                status = {}
        return DriverResult(
            "merge", "PASS",
            details={"top": top_cell, "wrapper_cell": wrapper_cell,
                     "rc": rc, "status": status,
                     "stdout_tail": out[-1000:]},
            command_hint=hint, artifact=str(out_gds))
    return DriverResult(
        "merge", "FAIL",
        details={"top": top_cell, "wrapper_cell": wrapper_cell, "rc": rc,
                 "stdout_tail": out[-2000:], "stderr_tail": err[-2000:],
                 "note": "merge produced no assembled GDS"},
        command_hint=hint)


# ---------------------------------------------------------------------------
# (3) XOR — feed assembled + golden + allow-list into xor_layout_check
# ---------------------------------------------------------------------------
def run_xor(assembled_gds: Path, golden_gds: Path, top: str,
            allow_macros: Optional[List[str]] = None,
            report_out: Optional[Path] = None,
            script_out: Optional[Path] = None,
            run: bool = False,
            klayout_runner: Optional[Runner] = None,
            timeout: int = 1800) -> DriverResult:
    """Compute the live XOR of the assembled GDS vs the golden reference.

    Emits the KLayout XOR script (via xor_layout_check), runs it live when
    run=True, then delegates the verdict to xor_layout_check.evaluate (which
    owns the §4.05 allow-list rules). A missing assembled/golden GDS is BLOCKED,
    never a fabricated clean XOR."""
    allow_macros = list(allow_macros or [])
    report_out = Path(report_out) if report_out else \
        (Path(assembled_gds).parent / "xor_report.json")
    script_out = Path(script_out) if script_out else \
        (report_out.parent / "_xor_fullchip.py")
    missing = []
    if not Path(assembled_gds).is_file():
        missing.append(f"assembled GDS absent: {assembled_gds}")
    if not Path(golden_gds).is_file():
        missing.append(f"golden reference GDS absent: {golden_gds}")

    script_text = xlc.emit_xor_script(top, str(assembled_gds),
                                      str(golden_gds), str(report_out),
                                      allow_macros=allow_macros)
    hint = xlc.klayout_command_hint(str(script_out))

    if not run:
        return DriverResult(
            "xor", "NOT_RUN",
            details={"top": top, "allow_macros": allow_macros,
                     "missing_prerequisites": missing,
                     "report_out": str(report_out)},
            command_hint=hint,
            blocked_reason="" if not missing else "; ".join(missing))
    if missing:
        return DriverResult(
            "xor", "BLOCKED",
            details={"top": top, "allow_macros": allow_macros,
                     "missing_prerequisites": missing},
            blocked_reason="; ".join(missing), command_hint=hint)

    script_out.parent.mkdir(parents=True, exist_ok=True)
    script_out.write_text(script_text, encoding="utf-8")
    runner = klayout_runner or default_runner
    rc, out, err = runner(hint, timeout=timeout)

    result = xlc.evaluate(report_out, allow_macros, top=top,
                          layout_under_test=assembled_gds,
                          golden_reference=golden_gds)
    verdict = result.get("verdict", "INCOMPLETE")
    # Map the XOR gate's INCOMPLETE (absent/unparseable report) to BLOCKED so
    # the driver's verdict vocabulary is uniform -- still never a fake PASS.
    driver_verdict = "BLOCKED" if verdict == "INCOMPLETE" else verdict
    return DriverResult(
        "xor", driver_verdict,
        details={"xor": result, "rc": rc, "stdout_tail": out[-1000:]},
        blocked_reason=result.get("incomplete_reason", "") if
            verdict == "INCOMPLETE" else "",
        command_hint=hint, artifact=str(report_out))


# ---------------------------------------------------------------------------
# Orchestration — harden -> merge -> xor, with §4.05 short-circuit
# ---------------------------------------------------------------------------
def harden_merge_xor(project_dir: Path, design: str, golden_gds: Path,
                     assembled_out: Path, top_cell: str, wrapper_cell: str,
                     allow_macros: Optional[List[str]] = None,
                     image: str = OPENLANE_IMAGE_DEFAULT,
                     pdk_root: Optional[str] = None,
                     run: bool = False,
                     harden_runner: Optional[Runner] = None,
                     klayout_runner: Optional[Runner] = None,
                     hardened_gds: Optional[Path] = None) -> Dict[str, Any]:
    """Full live chain. The MERGE + XOR are attempted ONLY when the upstream
    step produced a real artifact -- a NOT_RUN/FAILED/BLOCKED harden or merge
    short-circuits the whole chain to BLOCKED, so a clean XOR can never be
    manufactured from a harden that did not happen (§4.05).

    `hardened_gds` may be passed to short-circuit the harden step (e.g. a
    previously-hardened wrapper, or a synthetic one in tests)."""
    allow_macros = list(allow_macros or [])
    steps: List[DriverResult] = []

    # --- harden ---
    if hardened_gds is not None and Path(hardened_gds).is_file():
        h = DriverResult("harden", "PASS",
                         details={"design": design,
                                  "note": "pre-supplied hardened wrapper GDS"},
                         artifact=str(hardened_gds))
    else:
        h = run_harden(project_dir, design, image=image, pdk_root=pdk_root,
                       run=run, runner=harden_runner)
    steps.append(h)
    if h.verdict != "PASS" or not h.artifact:
        return _chain_report(steps, "BLOCKED",
                             "harden did not produce a wrapper GDS "
                             f"(verdict={h.verdict}); "
                             "merge + XOR NOT attempted (no fabricated pass)")

    # --- merge ---
    m = run_merge(golden_gds, Path(h.artifact), assembled_out, top_cell,
                  wrapper_cell, run=run, klayout_runner=klayout_runner)
    steps.append(m)
    if m.verdict != "PASS" or not m.artifact:
        return _chain_report(steps, "BLOCKED",
                             f"merge did not produce an assembled GDS "
                             f"(verdict={m.verdict}); XOR NOT attempted")

    # --- xor ---
    x = run_xor(Path(m.artifact), golden_gds, top_cell,
                allow_macros=allow_macros, run=run,
                klayout_runner=klayout_runner)
    steps.append(x)
    return _chain_report(steps, x.verdict, x.blocked_reason)


def _chain_report(steps: List[DriverResult], overall: str,
                  note: str = "") -> Dict[str, Any]:
    return {
        "overall_verdict": overall,
        "note": note,
        "steps": [s.as_dict() for s in steps],
        "emitted_by": EMITTED_BY,
    }


def verdict_exit_code(verdict: str) -> int:
    if verdict in ("PASS", "PASS_WITH_WAIVER"):
        return 0
    if verdict == "FAIL":
        return 1
    return 2  # BLOCKED / NOT_RUN / INCOMPLETE -> never a success


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Caravel wrapper HARDEN + full-chip MERGE + live XOR "
                    "driver (chip-AGNOSTIC).")
    sub = p.add_subparsers(dest="cmd", required=True)

    ph = sub.add_parser("harden", help="OpenLane harden of the wrapper")
    ph.add_argument("--project-dir", type=Path, required=True)
    ph.add_argument("--design", default="user_project_wrapper")
    ph.add_argument("--image", default=OPENLANE_IMAGE_DEFAULT)
    ph.add_argument("--pdk-root", default=None)
    ph.add_argument("--run", action="store_true")
    ph.add_argument("--stage-gl", action="store_true", dest="stage_gl",
                    help="On a clean PASS, stage the produced gl netlist(s) into "
                         "verilog/gl/ so mpw_precheck Consistency/LVS can read "
                         "verilog/gl/<design>.v (§4.05: only a produced netlist).")

    ps = sub.add_parser("stage-gl", help="Stage the harden's produced gl "
                        "netlist(s) into verilog/gl/ for mpw_precheck")
    ps.add_argument("--project-dir", type=Path, required=True)
    ps.add_argument("--design", default="user_project_wrapper")
    ps.add_argument("--tag", default=None,
                    help="Scope the source search to this OpenLane run tag "
                         "(§4.05: prevents a stale prior-run netlist masking a "
                         "current run that produced none). Default: newest run.")

    pm = sub.add_parser("merge", help="Merge hardened wrapper into golden base")
    pm.add_argument("--base", type=Path, required=True)
    pm.add_argument("--wrapper", type=Path, required=True)
    pm.add_argument("--out", type=Path, required=True)
    pm.add_argument("--top", default="caravel")
    pm.add_argument("--wrapper-cell", default="user_project_wrapper")
    pm.add_argument("--run", action="store_true")

    px = sub.add_parser("xor", help="Live XOR assembled vs golden")
    px.add_argument("--assembled", type=Path, required=True)
    px.add_argument("--golden", type=Path, required=True)
    px.add_argument("--top", default="caravel")
    px.add_argument("--allow-macro", action="append", default=[],
                    dest="allow_macros")
    px.add_argument("--report-out", type=Path, default=None)
    px.add_argument("--run", action="store_true")

    pf = sub.add_parser("all", help="harden -> merge -> xor (live chain)")
    pf.add_argument("--project-dir", type=Path, required=True)
    pf.add_argument("--design", default="user_project_wrapper")
    pf.add_argument("--golden", type=Path, required=True)
    pf.add_argument("--assembled-out", type=Path, required=True)
    pf.add_argument("--top", default="caravel")
    pf.add_argument("--wrapper-cell", default="user_project_wrapper")
    pf.add_argument("--allow-macro", action="append", default=[],
                    dest="allow_macros")
    pf.add_argument("--image", default=OPENLANE_IMAGE_DEFAULT)
    pf.add_argument("--pdk-root", default=None)
    pf.add_argument("--run", action="store_true")

    p.add_argument("--out-json", type=Path, default=None)
    args = p.parse_args(argv)

    if args.cmd == "harden":
        r = run_harden(args.project_dir, args.design, image=args.image,
                       pdk_root=args.pdk_root, run=args.run,
                       stage_gl=getattr(args, "stage_gl", False))
        payload = r.as_dict()
        verdict = r.verdict
    elif args.cmd == "stage-gl":
        r = run_stage_gl(args.project_dir, args.design, tag=args.tag)
        payload = r.as_dict()
        verdict = r.verdict
    elif args.cmd == "merge":
        r = run_merge(args.base, args.wrapper, args.out, args.top,
                      args.wrapper_cell, run=args.run)
        payload = r.as_dict()
        verdict = r.verdict
    elif args.cmd == "xor":
        r = run_xor(args.assembled, args.golden, args.top,
                    allow_macros=args.allow_macros,
                    report_out=args.report_out, run=args.run)
        payload = r.as_dict()
        verdict = r.verdict
    else:  # all
        payload = harden_merge_xor(
            args.project_dir, args.design, args.golden, args.assembled_out,
            args.top, args.wrapper_cell, allow_macros=args.allow_macros,
            image=args.image, pdk_root=args.pdk_root, run=args.run)
        verdict = payload["overall_verdict"]

    out = json.dumps(payload, indent=2)
    if getattr(args, "out_json", None):
        args.out_json.write_text(out + "\n", encoding="utf-8")
    else:
        print(out)
    return verdict_exit_code(verdict)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
