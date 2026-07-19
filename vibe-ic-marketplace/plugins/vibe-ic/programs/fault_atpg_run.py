#!/usr/bin/env python3
"""
fault_atpg_run.py — Open-source ATPG via Fault (cloudv-io/fault).

Runs Fault's `cut` + `atpg` subcommands on a synthesized netlist to produce
stuck-at test vectors and a coverage metric, then emits the artefacts
required by flow Step 11 (DFT insertion):

  <project>/dft/scan_netlist.v          (copy of cut netlist; Fault's cut DFF
                                         replacement is the moral equivalent
                                         of scan insertion for open flow)
  <project>/dft/atpg_coverage.rpt       (human-readable coverage ratio + count)
  <project>/dft/transition_atpg_plan.md (launch-off-capture / at-speed
                                         two-pattern mechanism plan +
                                         engine-capability record)
  <project>/reports/dft/coverage.json   (machine-readable with
                                         stuck_at_ge_target: bool and a
                                         `transition` fault-model block)

Eliminates the "no commercial ATPG" waiver (feedback_plugin_usage_discipline.md,
2026-04-22).

FOUNDRY-GRADE DEFAULT (2026-07 DFT-depth raise): the stuck-at target now
defaults to 95 % (foundry / ATE sign-off bar), configurable UP to 98 % via
`--min-coverage`. The old lenient 80 % pass is gone — a design below the
target FAILs (exit 1), never a lenient pass.

TWO FAULT MODELS:
  * stuck-at  — Fault's combinational stuck-at ATPG (real coverage number).
  * transition (at-speed / launch-off-capture) — a SECOND fault model with
    its own target (`--transition-target`, default 90 %). The launch-off-
    capture two-pattern mechanism + plan is always emitted; the coverage
    NUMBER is only reported if the underlying OSS engine can actually run
    transition ATPG. Fault (cloudv-io) is a single-pattern combinational
    stuck-at engine and does NOT support transition/delay ATPG, so the
    honest outcome is `transition.engine_limited = true` with a documented
    reason — never a fabricated transition-coverage number.

Usage:
    python3 fault_atpg_run.py <project_dir> \\
        --netlist synth/netlist.v \\
        --top aon_timer \\
        --clock clk_i \\
        [--pdk gf180] [--min-coverage 95] [--transition-target 90] \\
        [--tv-count 100] [--no-transition]

Requires the pinned vibeic-eda Docker image (Fault + GF180 cell model); see
_resolve_docker_image() for the pin + fallback order.
Fault ≈ 10-60 s for typical <5k-cell designs.

Exit 0 = stuck-at coverage >= target AND all artefacts produced.
Exit 1 = stuck-at coverage below target OR Fault failed.
Exit 2 = usage / IO / Docker error.

Note: a transition ENGINE limitation (Fault cannot do at-speed) is honestly
recorded but does NOT by itself fail this producer — the DFT sign-off gate
(dft_signoff_check.py) is where the "transition >= target OR documented
engine-limited" policy is enforced.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import os
import subprocess
import sys
from pathlib import Path
import _path_layout as _pl


def _resolve_docker_image() -> str:
    """Resolve the EDA docker image, preferring the forked vibeic-eda
    distribution (the iic-osic-tools fork this plugin actually ships and that
    carries Fault + iverilog + yosys) over the upstream image, which may not be
    pulled locally. Order: explicit env override → first locally-present
    PINNED vibeic-eda tag → legacy upstream name (last resort).

    The fork tags below are pinned, never ``:latest``: a floating tag can
    silently resolve to a stale local image whose tool behavior no longer
    matches what the plugin was verified against. Every ``vibeic-eda:X.Y.Z``
    literal here is a LIVE POINTER tracked by
    ``tools/vibeic-eda/sync_image_version.py`` (this file is registered in its
    INSTALL_DOC_CANDIDATES), so ``--set``/``--bump`` rewrites it mechanically
    and ``--check`` fails the suite on drift — do not hand-edit out of step.

    Historically this was hardcoded to ``hpretl/iic-osic-tools:latest``; on a
    machine that only has the fork pulled, ``docker run`` failed with
    image-not-found and the whole DFT step silently died. chip-AGNOSTIC."""
    env = os.environ.get("VIBEIC_EDA_IMAGE") or os.environ.get("IIC_EDA_IMAGE")
    if env:
        return env
    candidates = (
        "ghcr.io/vibeic/vibeic-eda:0.2.19",
        "vibeic-eda:0.2.19",
        "vibeic/vibeic-eda:0.2.19",
        "hpretl/iic-osic-tools:latest",
    )
    for img in candidates:
        try:
            r = subprocess.run(["docker", "image", "inspect", img],
                               capture_output=True, timeout=15)
            if r.returncode == 0:
                return img
        except Exception:
            pass
    # nothing found locally — return the fork's pinned canonical name; the
    # caller's `docker run` then pulls exactly the verified image (or surfaces
    # a clear pull error) rather than running a stale floating tag.
    return "ghcr.io/vibeic/vibeic-eda:0.2.19"


DOCKER_IMAGE = _resolve_docker_image()

# Foundry / ATE sign-off bar. Stuck-at coverage at 95 %+ is the widely-quoted
# minimum foundry acceptance floor; 98 %+ is the common aggressive target.
# Configurable via --min-coverage (may be set as high as 98/99).
FOUNDRY_STUCK_AT_DEFAULT = 95.0
# Transition (at-speed) coverage floors are typically a few points below the
# stuck-at floor because at-speed test escapes are harder; 90 % is a common
# foundry transition-fault target.
FOUNDRY_TRANSITION_DEFAULT = 90.0

# Keywords that, if present in `fault atpg --help`, would indicate the engine
# advertises a transition / at-speed / delay-fault (two-pattern) capability.
# Fault (cloudv-io) exposes none of these — its ATPG is single-pattern
# combinational stuck-at only. Probed at run time; NEVER assumed.
_TRANSITION_CAPABILITY_KEYWORDS = (
    "transition", "at-speed", "at speed", "atspeed",
    "launch-off-capture", "launch off capture", "launch-off-shift",
    "delay fault", "delay-fault", "delayfault", "two-pattern",
    "two pattern", "--slow", "--fast",
)

# Per-PDK defaults: verilog cell-model path (inside Docker) + DFF cell names.
# pdk=custom reads paths from --cell-model-path and --dff-cells flags.
PDK_CONFIG = {
    "gf180": {
        "cell_model": (
            "/foss/pdks/ciel/gf180mcu/versions/"
            "8f2d1529c86235d726979eb9ecb7e9628108590b"
            "/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0"
            "/verilog/gf180mcu_fd_sc_mcu7t5v0.v"
        ),
        "dff_cells": "gf180mcu_fd_sc_mcu7t5v0__dffq_1,gf180mcu_fd_sc_mcu7t5v0__dffrq_1",
    },
    # commercial 180nm PDK — used in the v046
    # aon_timer pilot and the spm commercial-PDK flow. This proprietary PDK ships a
    # Verilog simulation model but the run-dir PDK often
    # carries only the liberty; point --cell-model-path at the model copied
    # into the run dir's input/pdk/verilog/. The dff_cells list below is a
    # SEED only — the real set is auto-detected from the netlist by
    # detect_dff_cells() (unioned in), so a design that uses DFFHQD1 (not the
    # seeded DFFRQD1/DFFSQD1) is still cut correctly. Common commercial-PDK DFF
    # families: DFFHQD*/DFFSQD*/DFFRQD*/DFFSRQD*/SDFFHQD* (scan variants).
    "commercial_pdk": {
        # Inside the container this path is /pdk/verilog/... if the host
        # mounts shared_pdk at /pdk; fault_atpg_run mounts it that way below.
        # Overridable via --cell-model-path (project-relative → /work/...).
        "cell_model": "/pdk/verilog/commercial_pdk_verilog_210524/commercial_pdk_neg.v",
        "dff_cells": "DFFHQD1,DFFHQD2,DFFHQD4,DFFSQD1,DFFRQD1,DFFSRQD1",
    },
    # sky130A high-density stdcell library (default OpenLane PDK).
    # Added 2026-05-24 for v2 e2e benchmark spm_e2e — covers the broad
    # sky130_fd_sc_hd DFF family (dfxtp / dfrtp / dfstp / dfbbn / sdfxtp) plus the
    # ENABLE-flop family edfxtp/sedfxtp (yosys maps $_DFFE_* → edfxtp — the single
    # most common flop on real sky130 synth, e.g. 1024 in subservient; v1.4.21).
    "sky130": {
        "cell_model": (
            "/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/verilog/"
            "sky130_fd_sc_hd.v"
        ),
        "dff_cells": (
            "sky130_fd_sc_hd__dfxtp_1,sky130_fd_sc_hd__dfxtp_2,"
            "sky130_fd_sc_hd__dfxtp_4,"
            "sky130_fd_sc_hd__dfrtp_1,sky130_fd_sc_hd__dfrtp_2,"
            "sky130_fd_sc_hd__dfrtp_4,"
            "sky130_fd_sc_hd__dfstp_1,sky130_fd_sc_hd__dfstp_2,"
            "sky130_fd_sc_hd__dfstp_4,"
            "sky130_fd_sc_hd__sdfxtp_1,sky130_fd_sc_hd__sdfxtp_2,"
            "sky130_fd_sc_hd__sdfrtp_1,sky130_fd_sc_hd__sdfrtp_2,"
            "sky130_fd_sc_hd__edfxtp_1,sky130_fd_sc_hd__edfxbp_1,"
            "sky130_fd_sc_hd__sedfxtp_1,sky130_fd_sc_hd__sedfxbp_1"
        ),
    },
}

# Matches a flip-flop cell INSTANTIATION line: `CELLNAME instname (`. Anchored to
# line start + requires an instance name and an opening paren so a `wire dff_x;`
# declaration can never match. Two flop-cell naming conventions, both matched so
# the auto-detect is a true PDK-agnostic SUPERSET (never dependent on a seed):
#   1. commercial PREFIX — `DFF*` / `SDFF*` (e.g. DFFHQD1, SDFFRQD1);
#   2. OSS-PDK INFIX — `<lib>__[s][e]df…` where the flop family sits after the
#      `__` library separator, with optional scan (`s`) and/or enable (`e`)
#      variant letters: sky130 `__dfxtp`/`__dfrtp`/`__dfstp`/`__dfbbn`/`__sdfxtp`
#      AND the enable families `__edfxtp`/`__sedfxtp` (yosys maps `$_DFFE_*` →
#      `edfxtp`, the SINGLE most common flop on real sky130 synth — e.g. 1024 in
#      subservient); gf180 `__dffq`/`__sdffq`/`__edffq`.
#   3. GENERIC YOSYS PRIMITIVE — `\$_[…]DFF[…]_` escaped internal-cell FFs in a
#      PRE-TECHMAP netlist: `\$_DFF_P_`, `\$_DFFE_PP_`, `\$_SDFF_PP0_`,
#      `\$_DFFSR_PPP_` (the Fault-emitted cut/scan netlists are in THIS vocabulary
#      — a bogus non-cut full of `\$_DFF_P_` must be recognised as still-having-
#      flops so the cut-validity guard regenerates it). Latches (`\$_DLATCH_*`)
#      and `\$_SR_*` never carry `DFF`, so they never match.
# The three vocabularies together make the detect a TRUE superset. Non-flop cells
# never match: delay=`__dly`, latch=`__dl*`/`__lat*`/`\$_DLATCH`, buffer=`__buf`,
# mux=`__mux` — none reach `df`/`DFF`. This closes the empty-detect failure mode
# (WRONG `--dff` seed → `fault cut` cutting nothing → un-cut flops → a false
# NOT_APPLICABLE the coverage gate would silently pass — gate-gaming).
_DFF_INST_RE = re.compile(
    r'^\s*('
    r'S?DFF[A-Za-z0-9_]*'                        # commercial prefix DFF*/SDFF*
    r'|[A-Za-z][A-Za-z0-9_]*__s?e?df[a-z0-9_]*'   # OSS-PDK infix *__[s][e]df…
    r'|\\\$_[A-Z]*DFF[A-Z0-9_]*'                  # generic Yosys \$_…DFF…_ primitive
    r')\s+\\?[^\s()]+\s*\(', re.MULTILINE | re.IGNORECASE)


def detect_dff_cells(netlist_text: str) -> str:
    """Scan a gate-level netlist for instantiated flip-flop cells whose module
    name begins DFF / SDFF and return them sorted, comma-separated, de-duped —
    suitable for `fault cut --dff`. Chip- and PDK-AGNOSTIC. Returns "" when
    none are found (caller keeps the PDK-config seed).

    This closes the failure mode where a PDK config seeds the WRONG flop cell
    (e.g. seed DFFRQD1,DFFSQD1 but the netlist actually uses DFFHQD1): the
    detected set is UNIONED with the seed so cut always sees the real flop
    cell and does not leave 64 un-cut sequential elements (which would tank
    the measured stuck-at coverage or make ATPG meaningless)."""
    found = {m.group(1) for m in _DFF_INST_RE.finditer(netlist_text)}
    return ",".join(sorted(found))


def merge_dff_cells(seed: str | None, detected: str) -> str:
    """Union a PDK-config seed dff-cell list with the auto-detected set,
    preserving a stable sorted order. Pure — unit-tested. An empty/None seed
    yields just the detected set and vice-versa."""
    parts = set()
    for chunk in (seed or "", detected or ""):
        for tok in chunk.split(","):
            tok = tok.strip()
            if tok:
                parts.add(tok)
    return ",".join(sorted(parts))


def resolve_cell_model(cell_model_override: str | None,
                       pdk_cfg: dict | None) -> str | None:
    """Resolve the Verilog cell-model path as seen INSIDE the container.

    Priority: explicit --cell-model-path > PDK config. A container-absolute
    override (starts with '/', e.g. /pdk/... or /foss/...) is used as-is; a
    relative override is a project-relative path resolved under the /work mount
    (so the model can live inside the run dir → single mount, reproducible).
    Returns None when neither is available."""
    if cell_model_override:
        if cell_model_override.startswith("/"):
            return cell_model_override
        return "/work/" + cell_model_override.lstrip("./")
    if pdk_cfg is not None:
        return pdk_cfg.get("cell_model")
    return None


# Iverilog lives in iic-osic-tools but isn't in default PATH; set the env var
# Fault expects, and also prepend to PATH and LD_LIBRARY_PATH so sub-tools
# find the iverilog `vvp` simulator and its shared library (libvvp.so).
IVERILOG_ROOT = "/foss/tools/iverilog"
YOSYS_BIN = "/foss/tools/bin"
ENV_PREAMBLE = (
    f"export FAULT_IVERILOG={IVERILOG_ROOT}/bin/iverilog && "
    f"export FAULT_YOSYS={YOSYS_BIN}/yosys && "
    f"export PATH={IVERILOG_ROOT}/bin:{YOSYS_BIN}:$PATH && "
    f"export LD_LIBRARY_PATH={IVERILOG_ROOT}/lib:${{LD_LIBRARY_PATH:-}} && "
)


def _run_docker(
    project: Path,
    cmd: list[str],
    timeout: int = 600,
    pdk_dir: Path | None = None,
) -> tuple[int, str, str]:
    """Run a command inside iic-osic-tools.
    - project mounted at /work
    - pdk_dir (shared_pdk) mounted at /pdk (optional, for custom PDKs)
    """
    docker_cmd = [
        "docker", "run", "--rm",
        "--entrypoint", "bash",
        "-v", f"{project}:/work",
    ]
    if pdk_dir is not None and pdk_dir.exists():
        docker_cmd += ["-v", f"{pdk_dir}:/pdk"]
    docker_cmd += [
        DOCKER_IMAGE,
        "-c", ENV_PREAMBLE + " ".join(cmd),
    ]
    try:
        r = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "docker command timed out"
    except FileNotFoundError:
        return 127, "", "docker binary not found in PATH"


# ── Transition (at-speed) fault model ──────────────────────────────────
# A SECOND fault model alongside stuck-at. The mechanism (launch-off-capture
# two-pattern at-speed test) is always emitted as a plan; the coverage NUMBER
# is only reported if the OSS engine can actually run transition ATPG.

_TRANSITION_PLAN_TEMPLATE = """\
# Transition (at-speed) ATPG plan — launch-off-capture

Design clock : {clock}
Cut netlist  : {cut_rel}
Cell model   : {cell_model}
Target       : stuck-at-independent transition-fault coverage >= {target:.2f}%

## Fault model
Transition (a.k.a. delay / at-speed) faults model a node that is
functionally correct but too SLOW: a slow-to-rise (STR) or slow-to-fall
(STF) fault at each gate terminal. Detecting them requires a TWO-PATTERN
test (an initialization vector V1 then a launch vector V2) applied so the
transition is launched and captured at the rated (at-speed) clock period.

## Launch-off-capture (LOC) mechanism
1. Scan-in the initialization pattern V1 through the scan chain
   (scan_enable = 1) — the same scan chain inserted for stuck-at.
2. De-assert scan_enable (functional mode).
3. Pulse the functional clock at the rated period to LAUNCH the transition
   (V1 -> V2 combinational evolution) and CAPTURE the response one at-speed
   cycle later.
4. Scan-out the captured response and compare against the fault-free
   expected value.
(An alternative, launch-off-shift/LOS, launches from the last scan-shift
edge; LOC is preferred because it needs no at-speed scan-enable.)

## Engine capability
Engine probed : Fault (cloudv-io/fault) `fault atpg`
Supported     : {supported}
{capability_line}

## Honesty note
{honesty_note}
"""


def _fault_supports_transition(project: Path,
                               pdk_dir: Path | None = None
                               ) -> tuple[bool, str]:
    """Probe whether the Fault ATPG engine advertises a transition / at-speed
    capability by grepping `fault atpg --help`. Returns (supported, reason).

    Fault is a single-pattern combinational stuck-at engine and exposes no
    transition flag, so this returns (False, <reason>) in practice. The probe
    is honest — it never assumes support; it reads the tool's own help text.
    """
    ec, out, err = _run_docker(
        project, ["fault", "atpg", "--help"], timeout=120, pdk_dir=pdk_dir)
    help_text = (out + "\n" + err).lower()
    if ec not in (0, 1, 2) or not help_text.strip():
        # Could not run the probe (no docker / image). Report honestly as
        # "unknown -> treated as unsupported" rather than faking capability.
        return False, (
            "could not probe `fault atpg --help` (engine/docker unavailable, "
            f"exit={ec}); transition capability UNKNOWN — treated as "
            "unsupported (no fabricated transition number)")
    for kw in _TRANSITION_CAPABILITY_KEYWORDS:
        if kw in help_text:
            return True, (
                f"`fault atpg --help` advertises a '{kw}' flag — transition "
                "ATPG appears supported")
    return False, (
        "`fault atpg --help` exposes only single-pattern combinational "
        "stuck-at ATPG (no transition / at-speed / launch-off-capture / "
        "delay-fault / two-pattern flag) — the Fault engine cannot generate "
        "at-speed patterns")


def build_transition_report(supported: bool,
                            reason: str,
                            transition_target: float,
                            plan_rel: str,
                            measured_pct: float | None = None) -> dict:
    """Pure assembler for the transition fault-model block. NEVER fabricates
    a coverage number: if the engine is unsupported, coverage_pct stays None
    and engine_limited=True with a documented reason.

    chip-AGNOSTIC."""
    if supported and measured_pct is not None:
        ge = measured_pct >= transition_target
        return {
            "fault_model": "transition",
            "supported": True,
            "engine_limited": False,
            "coverage_pct": round(measured_pct, 4),
            "target_pct": transition_target,
            "ge_target": ge,
            "reason": reason,
            "plan_file": plan_rel,
        }
    # Unsupported (or supported-but-no-number): honest engine-limited record.
    return {
        "fault_model": "transition",
        "supported": bool(supported),
        "engine_limited": True,
        "coverage_pct": None,
        "target_pct": transition_target,
        "ge_target": None,
        "reason": reason,
        "plan_file": plan_rel,
    }


def run_transition_atpg(project: Path,
                        cut_rel: str,
                        cell_model: str,
                        clock: str,
                        transition_target: float,
                        pdk_dir: Path | None = None,
                        probe_fn=None) -> dict:
    """Emit the launch-off-capture at-speed mechanism plan and (if the engine
    supports it) a real transition-coverage number. Fault does not, so this
    writes the plan + an honest engine_limited record.

    `probe_fn(project, pdk_dir) -> (supported, reason)` is injectable for
    testing; defaults to the real `fault atpg --help` probe.
    """
    probe = probe_fn or _fault_supports_transition
    supported, reason = probe(project, pdk_dir)

    plan_rel = "phase2/stage2/dft/transition_atpg_plan.md"
    if supported:
        capability_line = f"Capability     : {reason}"
        honesty_note = (
            "Engine reports transition capability. Coverage NUMBER below is a "
            "real measurement from the at-speed ATPG run.")
    else:
        capability_line = f"Limitation     : {reason}"
        honesty_note = (
            "The at-speed pattern set is NOT generated because the open-source "
            "Fault engine cannot do transition ATPG. Per DFT-honesty doctrine "
            "we emit the mechanism/plan and record the engine limitation "
            "rather than fabricate a transition-coverage number. A commercial "
            "at-speed ATPG tool (or an OSS engine that gains delay-fault "
            "support) is required to close this coverage.")

    plan_text = _TRANSITION_PLAN_TEMPLATE.format(
        clock=clock,
        cut_rel=cut_rel,
        cell_model=cell_model,
        target=transition_target,
        supported=str(supported),
        capability_line=capability_line,
        honesty_note=honesty_note,
    )
    try:
        (project / plan_rel).parent.mkdir(parents=True, exist_ok=True)
        (project / plan_rel).write_text(plan_text)
    except OSError:
        pass

    # Fault has no transition mode, so we never obtain a measured number here.
    measured = None
    return build_transition_report(
        supported, reason, transition_target, plan_rel, measured)


def run_fault(
    project: Path,
    netlist_rel: str,
    clock: str,
    pdk: str,
    min_coverage: float,
    tv_count: int,
    pdk_dir: Path | None = None,
    reset: str | None = None,
    reset_active_low: bool = False,
    transition_target: float = FOUNDRY_TRANSITION_DEFAULT,
    run_transition: bool = True,
    transition_probe_fn=None,
    cell_model_override: str | None = None,
    dff_cells_override: str | None = None,
) -> tuple[int, dict]:
    """Run Fault cut+atpg in the Docker container. Returns (exit, report_dict).

    cell_model_override : explicit Verilog cell-model path (container-absolute
        or project-relative → /work/...). Wins over the PDK config; lets the
        commercial-PDK model live inside the run dir for reproducibility.
    dff_cells_override  : explicit `fault cut --dff` list. When None, the flop
        cells are auto-detected from the netlist and unioned with the PDK-config
        seed (detect_dff_cells + merge_dff_cells)."""
    pdk_cfg = PDK_CONFIG.get(pdk)
    if pdk_cfg is None and not cell_model_override:
        return 2, {"error": f"unsupported pdk: {pdk}. "
                            f"Supported: {list(PDK_CONFIG.keys())} "
                            f"(or pass --cell-model-path for a custom library)"}
    cell_model = resolve_cell_model(cell_model_override, pdk_cfg)
    if not cell_model:
        return 2, {"error": "no Verilog cell model resolved: pass "
                            "--cell-model-path or use a PDK with a configured "
                            "cell_model"}
    # Flop-cell resolution: explicit override wins; else auto-detect from the
    # netlist and union with the PDK-config seed so cut never misses the real
    # flop cell (fixes seed/netlist mismatch, e.g. DFFHQD1 vs seed DFFRQD1).
    if dff_cells_override:
        dff_cells = dff_cells_override
    else:
        try:
            netlist_text = (project / netlist_rel).read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            netlist_text = ""
        detected = detect_dff_cells(netlist_text)
        seed = pdk_cfg.get("dff_cells") if pdk_cfg else None
        dff_cells = merge_dff_cells(seed, detected) or (seed or "DFF")

    # Prepare output paths (relative to project / /work)
    dft_dir = _pl.dft_dir(project)
    reports_dft = (_pl.reports_phase2_dir(project) / "dft")
    dft_dir.mkdir(parents=True, exist_ok=True)
    reports_dft.mkdir(parents=True, exist_ok=True)

    cut_out = "phase2/stage2/dft/cut_netlist.v"
    tv_out = "phase2/stage2/dft/tv.json"
    cov_out = "phase2/stage2/dft/coverage.yml"
    rpt_out = "phase2/stage2/dft/atpg_coverage.rpt"

    netlist_abs = f"/work/{netlist_rel}"
    cut_abs = f"/work/{cut_out}"

    # Step A: fault cut (DFF-flattening). Note: fault cut does NOT take --top.
    cut_cmd = [
        "fault", "cut",
        "--output", cut_abs,
        "--dff", dff_cells,
        "--clock", clock,
    ]
    if reset:
        cut_cmd += ["--reset", reset]
        if reset_active_low:
            cut_cmd += ["--reset-active-low"]
    cut_cmd.append(netlist_abs)

    ec, out, err = _run_docker(project, cut_cmd, timeout=120, pdk_dir=pdk_dir)
    cut_log = (out + "\n" + err)[-1000:]
    if ec != 0 or not (project / cut_out).exists():
        return 1, {
            "stage": "cut",
            "exit": ec,
            "log_tail": cut_log,
        }

    # Step B: fault atpg
    atpg_cmd = [
        "fault", "atpg",
        "--cell-model", cell_model,
        "--clock", clock,
        "-o", f"/work/{tv_out}",
        "--output-coverage-metadata", f"/work/{cov_out}",
        "-m", str(min_coverage),
        "-v", str(tv_count),
        cut_abs,
    ]
    ec, out, err = _run_docker(project, atpg_cmd, timeout=1800, pdk_dir=pdk_dir)
    atpg_log = (out + "\n" + err)[-2000:]

    # Parse coverage. Fault 0.9 emits `ratio: <fractional>` in the YAML
    # metadata + "Found X fault sites" / "Final coverage: Y%" in stdout.
    coverage_ratio = 0.0
    faults_total = 0
    cov_file = project / cov_out
    if cov_file.exists():
        text = cov_file.read_text()
        m_ratio = re.search(
            r"^ratio\s*:\s*([0-9.eE+\-]+)", text, re.MULTILINE,
        )
        if m_ratio:
            val = float(m_ratio.group(1))
            coverage_ratio = val * 100.0 if val <= 1.0 else val

    # Fallbacks from stdout log
    if coverage_ratio == 0.0:
        m = re.search(r"Final coverage:\s*([0-9.]+)\s*%", atpg_log)
        if m:
            coverage_ratio = float(m.group(1))
    m_total = re.search(r"Found\s+(\d+)\s+fault\s+sites", atpg_log)
    if m_total:
        faults_total = int(m_total.group(1))

    # Derive covered count rather than counting YAML "-" lines (which also
    # match testVectors etc. and over-counts).
    faults_covered = int(round(faults_total * coverage_ratio / 100.0))

    # Also grep the atpg stdout for a coverage number — Fault prints it at end
    if coverage_ratio == 0.0:
        m = re.search(r"[Cc]overage[^0-9]*([0-9.]+)\s*%", atpg_log)
        if m:
            coverage_ratio = float(m.group(1))

    # ── Transition (at-speed) fault model — SECOND model, own target ──
    transition = None
    if run_transition:
        transition = run_transition_atpg(
            project,
            cut_rel=cut_out,
            cell_model=cell_model,
            clock=clock,
            transition_target=transition_target,
            pdk_dir=pdk_dir,
            probe_fn=transition_probe_fn,
        )

    # Human-readable transition summary line for the rpt.
    if transition is None:
        trans_line = "Transition     : SKIPPED (--no-transition)\n"
    elif transition.get("engine_limited"):
        trans_line = (
            f"Transition %   : ENGINE-LIMITED (target >= "
            f"{transition_target:.2f}%; see transition_atpg_plan.md)\n")
    else:
        tc = transition.get("coverage_pct")
        trans_line = (
            f"Transition %   : {tc:.2f} "
            f"(target {transition_target:.2f}%, "
            f"{'PASS' if transition.get('ge_target') else 'FAIL'})\n")

    # Write human-readable report
    (project / rpt_out).write_text(
        "Fault ATPG Coverage Report\n"
        "==========================\n"
        f"Clock         : {clock}\n"
        f"Netlist       : {netlist_rel}\n"
        f"PDK           : {pdk}\n"
        f"Stuck-at %    : {coverage_ratio:.2f}\n"
        f"Covered / Total: {faults_covered} / {faults_total}\n"
        f"Target (min)  : {min_coverage:.2f}\n"
        f"Result        : {'PASS' if coverage_ratio >= min_coverage else 'FAIL'}\n"
        f"{trans_line}"
        "\n"
        f"(coverage metadata: {cov_out})\n"
        f"(test vectors    : {tv_out})\n"
    )

    # Also drop a copy as scan_netlist.v (Fault's cut output is the scan-ready
    # netlist in the open flow)
    scan_netlist = _pl.dft_dir(project) / "scan_netlist.v"
    if not scan_netlist.exists() and (project / cut_out).exists():
        scan_netlist.write_bytes((project / cut_out).read_bytes())

    report = {
        "tool": "fault",
        "clock": clock,
        "pdk": pdk,
        "netlist": netlist_rel,
        "coverage_pct": coverage_ratio,
        "faults_covered": faults_covered,
        "faults_total": faults_total,
        "cell_model": cell_model,
        "dff_cells": dff_cells,
        "target_pct": min_coverage,
        "stuck_at_ge_target": coverage_ratio >= min_coverage,
        "atpg_exit": ec,
        "log_tail": atpg_log[-500:],
    }
    if transition is not None:
        report["transition"] = transition
        # Flat mirror fields so a simple consumer/gate can read them without
        # descending into the nested block.
        report["transition_coverage_pct"] = transition.get("coverage_pct")
        report["transition_target_pct"] = transition.get("target_pct")
        report["transition_ge_target"] = transition.get("ge_target")
        report["transition_supported"] = transition.get("supported")
        report["transition_engine_limited"] = transition.get("engine_limited")

    return (0 if report["stuck_at_ge_target"] else 1), report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("project_dir")
    p.add_argument("--netlist", default="phase2/stage2/synth/netlist.v",
                   help="Path (relative to project_dir) to synth netlist (default: synth/netlist.v)")
    p.add_argument("--clock", required=True, help="Clock signal name (e.g. clk_i)")
    p.add_argument("--reset", help="Reset signal name (optional)")
    p.add_argument("--reset-active-low", action="store_true", help="Reset is active low")
    p.add_argument("--pdk", default="commercial_pdk",
                   help=f"PDK name. Supported: {', '.join(PDK_CONFIG.keys())}")
    p.add_argument("--pdk-dir", help="Path to PDK dir (mounted at /pdk for custom PDKs)")
    p.add_argument("--cell-model-path", default=None,
                   help="Explicit Verilog cell-model path for the std-cell "
                        "library. Container-absolute (/pdk/..., /foss/...) is "
                        "used as-is; a relative path is project-relative "
                        "(resolved under the /work mount) so a commercial PDK "
                        "model copied into the run dir is fully reproducible. "
                        "Wins over the PDK config's cell_model.")
    p.add_argument("--dff-cells", default=None,
                   help="Explicit comma-separated flip-flop cell names for "
                        "`fault cut --dff`. When omitted, the flop cells are "
                        "auto-detected from the netlist (DFF/SDFF families) and "
                        "unioned with the PDK-config seed.")
    p.add_argument("--min-coverage", type=float, default=FOUNDRY_STUCK_AT_DEFAULT,
                   help="Minimum stuck-at coverage %% required — FOUNDRY-GRADE "
                        f"default {FOUNDRY_STUCK_AT_DEFAULT:.0f}%% "
                        "(set 98 for the aggressive target). Below the target "
                        "the run FAILs (exit 1).")
    p.add_argument("--transition-target", type=float,
                   default=FOUNDRY_TRANSITION_DEFAULT,
                   help="Minimum transition (at-speed) coverage %% target "
                        f"(default {FOUNDRY_TRANSITION_DEFAULT:.0f}%%). Reported "
                        "only if the OSS engine supports transition ATPG; "
                        "otherwise honestly recorded as engine-limited.")
    p.add_argument("--no-transition", action="store_true",
                   help="Skip the transition (at-speed) fault-model pass "
                        "entirely (stuck-at only).")
    p.add_argument("--tv-count", type=int, default=100,
                   help="Initial test-vector batch size (default 100)")
    p.add_argument("--json", help="Write report JSON to this path "
                                  "(default: reports/dft/coverage.json under project)")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"fault_atpg_run: not a directory: {project}", file=sys.stderr)
        return 2

    netlist = project / args.netlist
    if not netlist.exists():
        print(f"fault_atpg_run: netlist not found: {netlist}", file=sys.stderr)
        return 2

    # For the commercial PDK the default PDK dir is ../../shared_pdk relative to project,
    # matching benchmark/phase2+3_v046 convention
    pdk_dir = None
    if args.pdk_dir:
        pdk_dir = Path(args.pdk_dir).resolve()
    elif args.pdk == "commercial_pdk":
        candidate = project.parent / "shared_pdk"
        if candidate.exists():
            pdk_dir = candidate

    exit_code, report = run_fault(
        project,
        netlist_rel=args.netlist,
        clock=args.clock,
        pdk=args.pdk,
        min_coverage=args.min_coverage,
        tv_count=args.tv_count,
        pdk_dir=pdk_dir,
        reset=args.reset,
        reset_active_low=args.reset_active_low,
        transition_target=args.transition_target,
        run_transition=not args.no_transition,
        cell_model_override=args.cell_model_path,
        dff_cells_override=args.dff_cells,
    )

    json_path = Path(args.json) if args.json else (_pl.report_path(project, "dft/coverage.json"))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2))

    cov = report.get("coverage_pct", 0.0)
    target = report.get("target_pct", 0.0)
    print(f"fault_atpg_run: stuck-at coverage={cov:.2f}%  target={target:.2f}%  "
          f"stuck_at_ge_target={report.get('stuck_at_ge_target', False)}")
    tr = report.get("transition")
    if tr is not None:
        if tr.get("engine_limited"):
            print(f"fault_atpg_run: transition=ENGINE-LIMITED "
                  f"(target={tr.get('target_pct')}%) — {tr.get('reason')}")
        else:
            print(f"fault_atpg_run: transition coverage={tr.get('coverage_pct')}%  "
                  f"target={tr.get('target_pct')}%  "
                  f"transition_ge_target={tr.get('ge_target')}")
    if exit_code != 0:
        print(f"  (see: {json_path})", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
