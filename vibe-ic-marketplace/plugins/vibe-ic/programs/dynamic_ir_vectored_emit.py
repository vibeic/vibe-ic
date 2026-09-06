#!/usr/bin/env python3
"""dynamic_ir_vectored_emit.py — TRANSIENT (dynamic) IR-drop EMITTER (real PSM).

ADVANCED-NODE GAP #2 (from the flow gap-analysis): Step 24 does STATIC IR only
(OpenROAD PSM `analyze_power_grid`, vectorless default). The DYNAMIC (di/dt)
transient tier was previously marked "HONEST BLOCKED: OSS PSM is static-only" —
that stance is now RETIRED. The vibeic-eda OpenROAD fork ships a REAL transient
solver:

  `analyze_power_grid -net <net> -transient -period <ns> [-steps N] [-decap_cap C]`

which performs the static DC operating point + a backward-Euler RC time-stepping
solve under a vectorless per-clock triangular current model (quasi-static when
no on-die capacitance is supplied), and reports the WORST DYNAMIC voltage droop.
This EMITTER wires that solver into the flow — it GENERATES the real transient
number; it does NOT need a switching VCD (the di/dt profile is derived from the
clock period). The full per-instance VECTORED DVD (RedHawk-SC / Voltus with a
SAIF/VCD activity trace + package/board L·di/dt) is the accuracy tier tracked
separately (psm-vectored-refine); the BASE transient di/dt solve is real and
shipped.

WHAT THIS EMITTER DOES
  read routed DEF + tech/cell/macro LEF + Liberty (+ optional SDC for the clock
  period)
    -> openroad: set_wire_rc / set_layer_rc  →
       analyze_power_grid -net <power net> -transient -period <ns> -steps <N>
    -> parse "Worst dynamic IR drop  : <V> V" from the transient PSM report
       (NB: distinct from the static "Worstcase IR drop:" line, which the
       transient path ALSO prints — the dynamic regex REQUIRES the word
       "dynamic" so the two never collide)
    -> write reports/phase3/dynamic_ir.json  {max_dynamic_drop_mv, vdd_v,
       static_from_transient_mv, dynamic_static_ratio, analysis_mode:
       "transient_psm", disclosure:"real backward-Euler di/dt solve", …}
  The gate `dynamic_ir_drop_check.py` then reads max_dynamic_drop_mv vs a budget.

SDC-PERIOD MAPPING
  `-period` is REQUIRED by the solver (PSM-0107) and is expressed in the design's
  STA time unit (ns for a standard tech). We parse `create_clock … -period <num>`
  from the design SDC and pass that value; when no SDC clock is discoverable we
  fall back to a documented default period (the quasi-static droop MAGNITUDE and
  the ~2x dynamic/static ratio are period-insensitive; the period only sets the
  RC timestep) and record period_source.

DYNAMIC BUDGET
  A quasi-static transient number is ≈2x the static drop (the solver's own
  Dynamic/static ratio is ~2.0), so a design that passes STATIC at e.g. 5.3% of
  Vdd legitimately shows ~10.6% DYNAMIC. The dynamic tier therefore uses a
  LOOSER %-of-Vdd budget than the static tier — the emitter default is 15% and
  it is written into the payload so the gate re-derives the SAME budget.

HONEST SKIP (§4.05 — never a fabricated number):
  * missing DEF/LEF/Liberty         -> {status:"SKIPPED_MISSING_INPUTS"} (rc 0)
  * DEF has no SPECIALNETS power net -> {status:"SKIPPED_NO_PDN"} (rc 0)
  * transient produced no dynamic-IR line -> {status:"ERROR_NO_PSM_IR"} (rc 1)
The static IR path (Step 24 `_emit_ir_em_reports`) is untouched and remains
authoritative for the static tier.

CLI
  python3 dynamic_ir_vectored_emit.py --project <run_dir> [--out F] [--net N]
        [--period-ns P] [--steps N] [--decap-cap C] [--budget-pct P]
  python3 dynamic_ir_vectored_emit.py --def D --tech-lef T --cell-lef C \
        --liberty L [--macro-lef M ...] [--sdc S] --out F [--net N]
  main(argv) -> 0 emitted/skipped-honestly / 1 tool-error / 2 IO-or-arg error.

chip-AGNOSTIC: power nets discovered from DEF SPECIALNETS; clock period from SDC;
no design literals.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _docker_watchdog as _dw    # noqa: E402  the canonical supervised
# `docker exec` primitive: identity-stamped reap, container-side ceiling, and
# the IN-CONTAINER CPU probe this call site cannot do without (see `emit`).

#: How long the openroad transient solve may be COMPLETELY IDLE — no CPU, no
#: I/O, no log growth — before it is called wedged. NOT a bound on how long a
#: PSM solve over a large die may legitimately take.
_IR_STALL_GRACE_S = 1800
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_exec as _ce  # noqa: E402 — the ONE guarded docker-exec argv
import _eda_pin as _pin  # noqa: E402 — the ONE place the pin is stated
import _progress_run as _pr  # noqa: E402

_DEFAULT_CONTAINER = _pin.default_container_name()
_TOOLS = "/foss/tools"
# Dynamic tier default budget (%-of-Vdd). LOOSER than the static tier: a
# quasi-static transient droop is ≈2x the static drop, so a design passing static
# at ~5% legitimately shows ~10%+ dynamic. Written into the payload so the gate
# re-derives the same budget.
_DEFAULT_DYN_BUDGET_PCT = 15.0
# Fallback clock period (ns) when the SDC exposes no create_clock. The
# quasi-static droop magnitude + dynamic/static ratio are period-insensitive;
# the period only sets the RC timestep, so a default is honest (recorded).
_DEFAULT_PERIOD_NS = 10.0
_DEFAULT_STEPS = 100

# ── PURE HELPERS (unit-tested; no docker / no filesystem side effects) ──────────

# STATIC "########## IR report" line ("Worstcase IR drop: <V> V"). The transient
# path prints this too, so the DYNAMIC regex below must NOT reuse it.
_WORST_IR_RE = re.compile(r"Worstcase\s+IR\s+drop\s*:\s*([0-9.eE+\-]+)\s*V", re.I)
# DYNAMIC "########## Dynamic (transient) IR report" line. The word "dynamic" is
# REQUIRED so this never matches the static "Worstcase IR drop:" nor the
# transient report's own "Worst static IR drop:" line.
_WORST_DYN_IR_RE = re.compile(
    r"Worst\s+dynamic\s+IR\s+drop\s*:\s*([0-9.eE+\-]+)\s*V", re.I)
# The transient report's OWN static reference (same solve → directly comparable).
_WORST_STATIC_TR_RE = re.compile(
    r"Worst\s+static\s+IR\s+drop\s*:\s*([0-9.eE+\-]+)\s*V", re.I)
_DYN_RATIO_RE = re.compile(
    r"Dynamic/static\s+ratio\s*:\s*([0-9.eE+\-]+)", re.I)
_PKG_DROOP_RE = re.compile(
    r"Package\s+L\*di/dt\s+droop\s*:\s*([0-9.eE+\-]+)\s*V", re.I)
_TIMESTEP_RE = re.compile(r"Timestep\s*:\s*([0-9.eE+\-]+)\s*s", re.I)
_STEPS_RE = re.compile(r"^\s*Steps\s*:\s*(\d+)\s*$", re.I | re.M)
_CURRENT_MODEL_RE = re.compile(r"Current\s+model\s*:\s*(vectored|vectorless)", re.I)
_QUASI_STATIC_RE = re.compile(r"Capacitance\s+model\s*:\s*quasi-static", re.I)
_ONDIE_CAP_RE = re.compile(r"On-die\s+capacitance\s*:\s*([0-9.eE+\-]+)\s*F", re.I)
_AVG_IR_RE = re.compile(r"Average\s+IR\s+drop\s*:\s*([0-9.eE+\-]+)\s*V", re.I)
_SUPPLY_RE = re.compile(r"Supply\s+voltage\s*:\s*([0-9.eE+\-]+)\s*V", re.I)
_ANNOT_RE = re.compile(r"Annotated\s+(\d+)\s+pin\s+activit", re.I)
_TOTAL_P_RE = re.compile(r"Total\s+power\s*:\s*([0-9.eE+\-]+)\s*W", re.I)
# PSM-0107 = transient requires -period (guards a period-derivation bug).
_PSM_NO_PERIOD_RE = re.compile(r"PSM-0107|Transient analysis requires -period", re.I)

# SDC create_clock period (design time unit, ns for a standard tech).
_SDC_PERIOD_RE = re.compile(
    r"create_clock\b[^\n]*?-period\s+([0-9.eE+\-]+)", re.I)

# Sim sub-dirs a VCD may live under (optional — only used by the future vectored
# refinement; the base transient solve does not require one).
_VCD_GLOBS = (
    "phase2/stage1/sim*/**/*.vcd",
    "phase2/stage1/sim*/*.vcd",
    "phase3/**/sim*/**/*.vcd",
    "reports/**/*.vcd",
)


def find_vcd(project: Path) -> Optional[Path]:
    """First NON-EMPTY .vcd under the project's sim dirs, or None. Optional — the
    base transient solve does not need a VCD (di/dt is derived from the clock
    period); this feeds only the future per-instance VECTORED refinement."""
    for pat in _VCD_GLOBS:
        for cand in sorted(project.glob(pat)):
            try:
                if cand.is_file() and cand.stat().st_size > 0:
                    return cand
            except OSError:
                continue
    return None


def discover_vcd_scope(vcd_text: str) -> Optional[str]:
    """Derive the DUT scope path from a VCD's `$scope module <m>` nesting.

    Returns "<tb>/<dut>" (the two outermost MODULE scopes), the single outermost
    module, or None. Only `module` scopes count (task/function/fork skipped).
    Used only by the future vectored refinement path."""
    mods: List[str] = []
    depth_stack: List[Tuple[str, str]] = []  # (kind, name)
    for m in re.finditer(r"\$scope\s+(\w+)\s+(\S+)\s+\$end|\$upscope\s+\$end",
                          vcd_text):
        if m.group(1) is None:  # $upscope
            if depth_stack:
                depth_stack.pop()
            continue
        kind, name = m.group(1), m.group(2)
        depth_stack.append((kind, name))
        if kind == "module":
            path = [n for (k, n) in depth_stack if k == "module"]
            mods.append("/".join(path))
    if not mods:
        return None
    two_level = [p for p in mods if p.count("/") == 1]
    if two_level:
        return two_level[0]
    return mods[0]


def _to_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_worst_dynamic_ir_v(psm_log: str) -> Optional[float]:
    """Worst DYNAMIC (transient) IR drop in Volts, or None. Requires the word
    'dynamic' so it never picks up the static 'Worstcase IR drop:' line (both
    appear in a `-transient` run's stdout)."""
    m = _WORST_DYN_IR_RE.search(psm_log)
    v = _to_float(m.group(1)) if m else None
    return abs(v) if v is not None else None


def parse_worst_static_tr_v(psm_log: str) -> Optional[float]:
    """Worst STATIC IR drop from the TRANSIENT report (same solve → directly
    comparable to the dynamic number), or None."""
    m = _WORST_STATIC_TR_RE.search(psm_log)
    v = _to_float(m.group(1)) if m else None
    return abs(v) if v is not None else None


def parse_dynamic_static_ratio(psm_log: str) -> Optional[float]:
    m = _DYN_RATIO_RE.search(psm_log)
    return _to_float(m.group(1)) if m else None


def parse_package_droop_v(psm_log: str) -> Optional[float]:
    m = _PKG_DROOP_RE.search(psm_log)
    v = _to_float(m.group(1)) if m else None
    return abs(v) if v is not None else None


def parse_worst_ir_v(psm_log: str) -> Optional[float]:
    """Worst STATIC 'Worstcase IR drop' in Volts, or None (legacy static line)."""
    m = _WORST_IR_RE.search(psm_log)
    v = _to_float(m.group(1)) if m else None
    return abs(v) if v is not None else None


def parse_supply_v(psm_log: str) -> Optional[float]:
    m = _SUPPLY_RE.search(psm_log)
    return _to_float(m.group(1)) if m else None


def parse_timestep_s(psm_log: str) -> Optional[float]:
    m = _TIMESTEP_RE.search(psm_log)
    return _to_float(m.group(1)) if m else None


def parse_steps(psm_log: str) -> Optional[int]:
    m = _STEPS_RE.search(psm_log)
    return int(m.group(1)) if m else None


def parse_current_model(psm_log: str) -> Optional[str]:
    m = _CURRENT_MODEL_RE.search(psm_log)
    return m.group(1).lower() if m else None


def parse_cap_model(psm_log: str) -> Optional[str]:
    if _QUASI_STATIC_RE.search(psm_log):
        return "quasi-static"
    m = _ONDIE_CAP_RE.search(psm_log)
    if m:
        return f"on-die-cap {m.group(1)}F"
    return None


def parse_annotated_pins(psm_log: str) -> Optional[int]:
    m = _ANNOT_RE.search(psm_log)
    return int(m.group(1)) if m else None


def parse_total_power_w(psm_log: str) -> Optional[float]:
    m = _TOTAL_P_RE.search(psm_log)
    return _to_float(m.group(1)) if m else None


def parse_sdc_period_ns(sdc_text: str) -> Optional[float]:
    """Smallest `create_clock … -period <num>` value (ns) in an SDC, or None.
    The TIGHTEST clock is the worst-case for di/dt, so we take the minimum."""
    vals = [v for v in (_to_float(m) for m in _SDC_PERIOD_RE.findall(sdc_text))
            if v is not None and v > 0]
    return min(vals) if vals else None


def derive_period_ns(sdc: Optional[Path]) -> Tuple[float, str]:
    """(period_ns, source). Parse the SDC clock period; else the documented
    default. `source` ∈ {"sdc_create_clock", "default_fallback"}."""
    if sdc is not None:
        try:
            p = parse_sdc_period_ns(Path(sdc).read_text(errors="ignore"))
        except OSError:
            p = None
        if p is not None:
            return p, "sdc_create_clock"
    return _DEFAULT_PERIOD_NS, "default_fallback"


def read_static_ir_mv(ir_drop_json: Path) -> Optional[float]:
    """Worst STATIC IR in mV from a Step-24 ir_drop.json (worst_ir_uv), or None."""
    try:
        d = json.loads(ir_drop_json.read_text(errors="ignore"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    uv = d.get("worst_ir_uv")
    if isinstance(uv, (int, float)):
        return float(uv) / 1000.0
    return None


def discover_power_nets(def_file: Path) -> List[str]:
    """USE POWER nets from a DEF SPECIALNETS block (chip-AGNOSTIC structural parse)."""
    power: List[str] = []
    try:
        text = def_file.read_text(errors="ignore")
    except OSError:
        return power
    m = re.search(r"^SPECIALNETS\b.*?^END SPECIALNETS",
                  text, re.MULTILINE | re.DOTALL)
    if not m:
        return power
    for net_m in re.finditer(r"^\s*-\s+([A-Za-z_][\w$]*)(.*?)(?=^\s*-\s+|\Z)",
                             m.group(0), re.MULTILINE | re.DOTALL):
        name, body = net_m.group(1), net_m.group(2)
        if re.search(r"\bUSE\s+POWER\b", body) and name not in power:
            power.append(name)
    return power


def build_result(worst_dyn_mv: float, vdd_v: Optional[float],
                 static_tr_mv: Optional[float], ratio: Optional[float],
                 package_droop_mv: Optional[float], power_net: str,
                 period_ns: float, period_source: str, steps: Optional[int],
                 timestep_s: Optional[float], current_model: Optional[str],
                 cap_model: Optional[str],
                 static_mv: Optional[float] = None) -> Dict[str, object]:
    """Assemble the dynamic_ir.json payload (real transient numbers + honest
    disclosure). Keeps the gate-consumed keys max_dynamic_drop_mv / vdd_v.

    HONEST LABEL OF THE TRANSIENT TIER. When NO on-die capacitance is supplied
    the fork's transient solver runs in its `quasi-static` mode, where the
    dynamic droop is a DETERMINISTIC scaling of the static drop: the tool prints
    a constant `Dynamic/static ratio : 2.00` and the dynamic number is exactly
    2x the static one for EVERY design (measured: sky130A caravel 0.0728 =
    2x0.0364; gf180 spm 14.3 = 2x7.15 — the same 2.00 to three significant
    figures across two different designs, PDKs, supplies and periods). Such a
    number answers the STATIC question scaled by a constant; it carries no
    independent di/dt information and is a conservative UPPER BOUND, not a
    genuine transient result. Only a decap-aware solve (on-die capacitance
    supplied) is a genuine dynamic droop. The payload therefore DISCLOSES which
    of the two it is (`scaled_static_bound`) and never labels a quasi-static
    bound as "not a static echo". chip-AGNOSTIC: keyed on the tool's own
    capacitance-model string, no design/PDK/vendor literal."""
    _is_genuine = isinstance(cap_model, str) and cap_model.startswith("on-die-cap")
    scaled_static_bound = not _is_genuine
    _solver_desc = (
        "OpenROAD PSM `analyze_power_grid -transient` performs the static DC "
        "operating point + a backward-Euler RC time-stepping solve under a "
        "vectorless per-clock triangular current model. The per-instance "
        "VECTORED DVD with a SAIF/VCD activity trace + package/board L·di/dt "
        "(RedHawk-SC / Voltus vectored) is the accuracy refinement tracked "
        "separately.")
    if _is_genuine:
        disclosure = (
            "REAL decap-aware transient (di/dt) IR-drop: " + _solver_desc +
            " On-die capacitance was supplied, so this is a genuine dynamic "
            "droop, not a fixed scaling of the static drop.")
    elif isinstance(cap_model, str) and cap_model.startswith("quasi-static"):
        disclosure = (
            "QUASI-STATIC SCALED-STATIC BOUND (no on-die decap supplied): " +
            _solver_desc + " With no on-die capacitance the transient solve "
            "degenerates to a FIXED ratio of the static drop (the tool prints a "
            "constant Dynamic/static ratio), so this number is the static solve "
            "scaled by that ratio — a conservative UPPER BOUND, not an "
            "independent di/dt measurement. A reader must not take it as a "
            "genuine vectored/decap-aware transient result; supply on-die decap "
            "(-decap_cap) for a genuine transient solve.")
    else:
        disclosure = (
            "SCALED-STATIC BOUND (capacitance model undetermined): " +
            _solver_desc + " The solve's capacitance model could not be read, "
            "so genuineness cannot be asserted; this number is treated as a "
            "conservative static-derived bound, not a genuine di/dt result.")
    res: Dict[str, object] = {
        "signoff_dimension": "dynamic_transient_ir_drop",
        "analysis_mode": "transient_psm",
        "dynamic_ir_report_emitted": True,
        "tool": "openroad-psm (analyze_power_grid -transient)",
        # keys the dynamic_ir_drop_check.py gate consumes:
        "max_dynamic_drop_mv": round(worst_dyn_mv, 4),
        "power_net": power_net,
        "period_ns": period_ns,
        "period_source": period_source,
        "steps": steps,
        "timestep_s": timestep_s,
        "current_model": current_model,       # vectorless (base) / vectored (#8)
        "capacitance_model": cap_model,        # quasi-static / on-die-cap
        # True when the number is a scaling of the static solve (quasi-static /
        # undetermined), False for a genuine decap-aware transient solve.
        "scaled_static_bound": scaled_static_bound,
        "disclosure": disclosure,
    }
    if static_tr_mv is not None:
        res["static_from_transient_mv"] = round(static_tr_mv, 4)
    if ratio is not None:
        res["dynamic_static_ratio"] = round(ratio, 4)
    if package_droop_mv is not None:
        res["package_ldidt_droop_mv"] = round(package_droop_mv, 4)
    if vdd_v is not None:
        res["vdd_v"] = vdd_v
        res["vdd"] = vdd_v  # gate alias
        res["max_dynamic_drop_pct"] = round(worst_dyn_mv / (vdd_v * 1000.0) * 100.0, 3)
    # exceeds_static vs an external Step-24 static number when available, else vs
    # the transient report's own static reference.
    base_static = static_mv if static_mv is not None else static_tr_mv
    if base_static is not None:
        res["static_ir_mv"] = round(base_static, 4)
        res["exceeds_static"] = worst_dyn_mv > base_static
        res["dynamic_vs_static_ratio"] = round(worst_dyn_mv / base_static, 3) \
            if base_static > 0 else None
    return res


_OPCOND_RE = re.compile(r"^\s*operating_conditions\s*\(\s*([A-Za-z0-9_.\-]+)\s*\)")


def liberty_operating_condition(liberty) -> str:
    """NAME of an operating condition the liberty defines, or "".

    Same root cause as the static path (vibe-ic#362): PSM cannot determine
    the supply voltage and aborts PSM-0079 when the library declares an
    `operating_conditions(<name>) { ... }` block but no
    `default_operating_conditions`. Measured with OpenSTA's own API on a real
    gf180 standard-cell liberty: `default_operating_conditions` is NULL while
    the named block exists and carries `voltage = 5.0`; 30 of 30 gf180mcuD
    standard-cell liberties are in that state.

    DELIBERATE DUPLICATION, ~10 lines. This module is standalone by design
    (its own argparse entry point, imported by nothing in the runner), and
    importing `phase3_one_shot_runner` for one regex would pull a 25k-line
    module — and its import-time side effects — into a program that exists to
    be run on its own. The shared thing here is the LIBERTY GRAMMAR, which is
    IEEE 1497 and does not drift; a shared helper module for it would be the
    right move only once a third caller appears.

    Reads the file directly: this program already receives host-visible paths
    (it is invoked with `--liberty` by the caller), unlike the runner which
    must also handle container-only paths."""
    try:
        txt = Path(liberty).read_text(errors="replace")
    except (OSError, TypeError):
        return ""
    for line in txt.splitlines():
        m = _OPCOND_RE.match(line)
        if m:
            return m.group(1)
    return ""


def missing_required_inputs(def_file, tech_lef, cell_lef, liberty) -> List[str]:
    """CLI-flag names of the required transient-emit inputs that are absent
    (None). The LIBERTY is REQUIRED — `analyze_power_grid -transient` needs the
    cell timing/power models to solve, so the runner must wire pdk.liberty (the
    same Liberty the STA/PSM steps resolve); without it the emit honestly SKIPs
    "missing required input(s) --liberty" instead of generating the flagship
    dynamic-IR number. PURE (no filesystem / docker)."""
    return [n for n, v in (("--def", def_file), ("--tech-lef", tech_lef),
                           ("--cell-lef", cell_lef), ("--liberty", liberty))
            if v is None]


def skip_result(reason: str, status: str = "SKIPPED_MISSING_INPUTS"
                ) -> Dict[str, object]:
    """Honest SKIP payload — NO fabricated droop number (§4.05)."""
    return {
        "signoff_dimension": "dynamic_transient_ir_drop",
        "analysis_mode": "transient_psm",
        "status": status,
        "dynamic_ir_report_emitted": False,
        "reason": reason,
        "disclosure": (
            "§4.05: no transient dynamic-IR number is fabricated. The static IR "
            "sign-off (reports/phase3/ir_drop.json) stands; the dynamic-IR tier "
            "is a conditional SKIP."),
    }


# ── DOCKER / OPENROAD RUN (side-effecting; not unit-tested) ─────────────────────

def _build_transient_tcl(def_file: Path, tech_lef: Path, cell_lef: Path,
                         liberty: Path, macro_lefs: List[Path],
                         sdc: Optional[Path], power_net: str,
                         period_ns: float, steps: int,
                         decap_cap: Optional[str], via_res: Dict[str, float],
                         metal_prefix: str) -> str:
    """The exact OpenROAD PSM TRANSIENT TCL (host paths; container mounts them).

    Mirrors the static grid setup that already produces a real IR number on the
    routed PDN, then appends `-transient -period <ns> -steps <N>` (no VCD needed —
    the solver derives di/dt from the clock period)."""
    macro_tcl = "\n".join(f"read_lef {f}" for f in macro_lefs)
    sdc_tcl = f"catch {{read_sdc {sdc}}}\n" if sdc else ""
    via_tcl = "".join(f"catch {{set_layer_rc -via {c} -resistance {r}}}\n"
                      for c, r in sorted(via_res.items()))
    decap_arg = f" -decap_cap {decap_cap}" if decap_cap else ""
    _oc = liberty_operating_condition(liberty)
    return (
        f"read_lef {tech_lef}\n"
        f"read_lef {cell_lef}\n"
        f"{macro_tcl}\n"
        f"read_liberty {liberty}\n"
        # vibe-ic#362 — select the library's own operating condition when it
        # declares one but names no default; without it PSM aborts PSM-0079
        # and the transient run produces nothing. Emitted only when a block
        # exists and catch-guarded: a PDK with a default is unchanged.
        + (f"catch {{set_operating_conditions {_oc}}}\n" if _oc else "")
        + f"read_def {def_file}\n"
        f"{sdc_tcl}"
        f"if {{[catch {{set_wire_rc -signal -layer {metal_prefix}1}}]}} "
        f"{{ catch {{set_wire_rc -layer {metal_prefix}1}} }}\n"
        f"catch {{set_wire_rc -clock -layer {metal_prefix}5}}\n"
        f"{via_tcl}"
        f'puts "=== DYN_IR PSM {power_net} transient period={period_ns}ns ==="\n'
        f"if {{[catch {{analyze_power_grid -net {power_net} -transient "
        f"-period {period_ns} -steps {steps}{decap_arg}}} _psm_err]}} {{\n"
        f'  puts "PSM_TRANSIENT_NONFATAL {power_net}: $_psm_err"\n}}\n'
        f"exit\n"
    )


def _discover_via_res(tech_lef: Optional[Path]) -> Dict[str, float]:
    """Per-CUT-LAYER via resistance (ohm) from a tech LEF's fixed-VIA MASTER
    blocks, for OpenROAD PSM `set_layer_rc -via` (mirrors the runner's
    `_discover_via_resistances`; {} when no LEF / no via RESISTANCE)."""
    out: Dict[str, float] = {}
    if not tech_lef:
        return out
    try:
        text = Path(tech_lef).read_text(errors="ignore")
    except OSError:
        return out
    cur_via = cur_cut = cur_res = None
    for raw in text.splitlines():
        s = raw.strip()
        m = re.match(r"VIA\s+(\S+)", s)
        if m and not s.startswith("VIARULE"):
            cur_via, cur_cut, cur_res = m.group(1), None, None
            continue
        if cur_via is None:
            continue
        m = re.match(r"LAYER\s+(\S+)", s)
        if m:
            nm = m.group(1).rstrip(";")
            if re.match(r"(VIA\d+|CONT)$", nm.upper()):
                cur_cut = nm
            continue
        m = re.match(r"RESISTANCE\s+([0-9.eE+\-]+)", s)
        if m:
            try:
                cur_res = float(m.group(1))
            except ValueError:
                cur_res = None
            continue
        if s.startswith("END") and cur_via is not None:
            if cur_cut and cur_res is not None:
                prev = out.get(cur_cut)
                out[cur_cut] = cur_res if prev is None else min(prev, cur_res)
            cur_via = cur_cut = cur_res = None
    return out


def _supervisor_note(err: str) -> str:
    """The supervisor's own last line (`WATCHDOG_STALLED: ...`), for the payload
    reason. Quoted rather than re-worded so the reason names what the watchdog
    actually reported and cannot drift from it."""
    for line in reversed((err or "").splitlines()):
        if line.startswith("WATCHDOG_"):
            return line.strip()
    return "(no supervisor line)"


def _docker_exec_raw(container: str, cmd: str, timeout: int = 15
                     ) -> Tuple[int, str, str]:
    """Bounded, UNSUPERVISED `docker exec` — for the watchdog's OWN short
    control-plane probes (identity-stamp read, CPU `ps`, TERM/KILL signal),
    never for the openroad run itself. `_docker_watchdog.run_docker_supervised`
    is the only caller; this is its injected `docker_exec_raw`."""
    try:
        cp = subprocess.run(_ce.docker_exec_argv(container, "bash", "-lc", cmd),
                            capture_output=True, text=True, timeout=timeout)
        return cp.returncode, cp.stdout or "", cp.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"probe timed out after {timeout}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return 126, "", f"{type(exc).__name__}: {exc}"


def emit(def_file: Path, tech_lef: Path, cell_lef: Path, liberty: Path,
         macro_lefs: List[Path], sdc: Optional[Path], out_json: Path,
         power_net: Optional[str], container: str, metal_prefix: str,
         static_json: Optional[Path], budget_pct: float,
         period_ns: Optional[float], steps: int,
         decap_cap: Optional[str]) -> Tuple[int, Dict[str, object]]:
    """Run the TRANSIENT PSM and write dynamic_ir.json. Returns (rc, payload)."""
    out_json.parent.mkdir(parents=True, exist_ok=True)
    nets = [power_net] if power_net else discover_power_nets(def_file)
    if not nets:
        payload = skip_result(
            "DEF has no SPECIALNETS power grid (no power net to analyze)",
            status="SKIPPED_NO_PDN")
        out_json.write_text(json.dumps(payload, indent=2) + "\n")
        return 0, payload
    net = nets[0]
    if period_ns is None:
        period_ns, period_source = derive_period_ns(sdc)
    else:
        period_source = "cli"
    via_res = _discover_via_res(tech_lef)
    tcl = _build_transient_tcl(def_file, tech_lef, cell_lef, liberty, macro_lefs,
                               sdc, net, period_ns, steps, decap_cap, via_res,
                               metal_prefix)
    tcl_path = out_json.parent / "dynamic_ir_transient.tcl"
    tcl_path.write_text(tcl)
    cmd = (f"export PATH={_TOOLS}/openroad/bin:{_TOOLS}/bin:$PATH && "
           f"openroad -no_init -exit {tcl_path} 2>&1 | "
           f"tee {out_json.parent}/dynamic_ir.log")
    try:
        # PROGRESS, NOT RUNTIME. A transient PSM solve on a large die is exactly
        # the honest long work a 1800 s cap murders, and relabelling that kill
        # NOT_MEASURED — which this file briefly did — left the solve just as
        # dead.
        #
        # AND THE PROGRESS MUST BE READ INSIDE THE CONTAINER (v1.12.29). This
        # launch is a `docker exec`, so the host's /proc sees only the exec
        # CLIENT: openroad runs under containerd-shim and is never a ppid-chain
        # descendant of the client, so the client's CPU and I/O sit flat for the
        # whole solve. Supervising this argv with `run_host_supervised` leaves
        # exactly one live signal — growth of the tee'd log — and any run that
        # buffers, or whose log is not on a shared mount, is then
        # indistinguishable from a hang. `run_docker_supervised` reads the CPU
        # of the job's process TREE inside the container, and reaps by identity
        # stamp rather than by pattern.
        grace = float(_IR_STALL_GRACE_S)
        # `run_docker_supervised` does NOT derive its poll cadence from the
        # grace the way `run_host_supervised` does; it defaults to a flat 30 s.
        # Deriving it here keeps a declared grace actually observed. Sampling
        # more often can only make a hang be NOTICED sooner — it can never kill
        # a working job earlier — so this is an observation cadence, not a bound.
        rc, out, err = _dw.run_docker_supervised(
            container, cmd, tcl_path.name,
            docker_exec_raw=_docker_exec_raw,
            stall_grace_s=grace,
            poll_s=max(0.25, min(_dw.DEFAULT_POLL_S, grace / 4.0)),
            log_path=out_json.parent / "dynamic_ir.log")
        if rc in (_dw.RC_STALLED, _dw.RC_CEILING):
            payload = {
                "status": "ERROR_TOOL",
                "dynamic_ir_report_emitted": False,
                "reason": (f"the openroad transient run made no forward "
                           f"progress — no in-container CPU, no I/O, no log "
                           f"growth — for {_IR_STALL_GRACE_S}s and was "
                           f"stopped. openroad was WEDGED. That is a measured "
                           f"fact about the tool, not a finding about the "
                           f"design's IR drop. Supervisor said: "
                           f"{_supervisor_note(err)}")}
            out_json.write_text(json.dumps(payload, indent=2) + "\n")
            return 1, payload
        log = (out or "") + "\n" + (err or "")
    except (FileNotFoundError, OSError) as e:
        payload = {"status": "ERROR_TOOL", "dynamic_ir_report_emitted": False,
                   "reason": f"openroad run failed or stalled: {e}"}
        out_json.write_text(json.dumps(payload, indent=2) + "\n")
        return 1, payload

    worst_v = parse_worst_dynamic_ir_v(log)
    if worst_v is None:
        reason = ("PSM produced no 'Worst dynamic IR drop' line "
                  "(grid disconnected / no valid resistance map / solver error)")
        if _PSM_NO_PERIOD_RE.search(log):
            reason = ("transient solve rejected the clock period (PSM-0107) — "
                      "check SDC create_clock / --period-ns")
        payload = {"signoff_dimension": "dynamic_transient_ir_drop",
                   "analysis_mode": "transient_psm",
                   "status": "ERROR_NO_PSM_IR",
                   "dynamic_ir_report_emitted": False,
                   "reason": reason,
                   "period_ns": period_ns, "period_source": period_source,
                   "log_tail": log[-1500:]}
        out_json.write_text(json.dumps(payload, indent=2) + "\n")
        return 1, payload

    vdd = parse_supply_v(log)
    static_mv = read_static_ir_mv(static_json) if static_json else None
    payload = build_result(
        worst_dyn_mv=worst_v * 1000.0, vdd_v=vdd,
        # V -> mV, like every other magnitude on this call. parse_worst_static_tr_v
        # returns VOLTS; feeding it raw made static_from_transient_mv (and, whenever
        # no external Step-24 static number was available, static_ir_mv /
        # dynamic_vs_static_ratio / exceeds_static) wrong by 1000x.
        static_tr_mv=(lambda s: s * 1000.0 if s is not None else None)(
            parse_worst_static_tr_v(log)),
        ratio=parse_dynamic_static_ratio(log),
        package_droop_mv=(lambda p: p * 1000.0 if p is not None else None)(
            parse_package_droop_v(log)),
        power_net=net, period_ns=period_ns, period_source=period_source,
        steps=parse_steps(log), timestep_s=parse_timestep_s(log),
        current_model=parse_current_model(log), cap_model=parse_cap_model(log),
        static_mv=static_mv)
    # local budget verdict (the authoritative gate re-derives it from budget_pct)
    payload["budget_pct"] = budget_pct
    if vdd is not None:
        budget_mv = budget_pct / 100.0 * vdd * 1000.0
        payload["budget_mv"] = round(budget_mv, 4)
        payload["verdict"] = "PASS" if worst_v * 1000.0 < budget_mv else "FAIL"
    out_json.write_text(json.dumps(payload, indent=2) + "\n")
    return 0, payload


def _auto_discover(project: Path) -> Dict[str, object]:
    """Best-effort discovery of DEF/LEF/Liberty/SDC from a run dir layout."""
    pnr = project / "phase3" / "stage3" / "pnr"
    def_file = None
    for name in ("*.def",):
        for c in sorted(pnr.glob(name)):
            if c.stem not in ("floorplan", "placed", "post_cts", "post_hold",
                              "routed_preantenna"):
                def_file = c
                break
    if def_file is None:
        cands = sorted(pnr.glob("routed.def")) or sorted(pnr.glob("*.def"))
        def_file = cands[0] if cands else None
    pdk = project / "input" / "pdk"
    tech = next(iter(sorted(pdk.rglob("*tech*.lef"))), None)
    cell = next((f for f in sorted(pdk.rglob("*.lef"))
                 if "tech" not in f.name.lower()
                 and "macro" in f.name.lower()), None)
    if cell is None:
        cell = next((f for f in sorted(pdk.rglob("*.lef"))
                     if "tech" not in f.name.lower()), None)
    lib = next(iter(sorted(pdk.rglob("*typ*.lib"))), None) \
        or next(iter(sorted(pdk.rglob("*.lib"))), None)
    sdc = next(iter(sorted(project.rglob("*/pnr/*.sdc"))), None) \
        or next(iter(sorted(project.rglob("*constraint*/*.sdc"))), None) \
        or next(iter(sorted(project.rglob("*.sdc"))), None)
    return {"def": def_file, "tech_lef": tech, "cell_lef": cell,
            "liberty": lib, "sdc": sdc}


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Transient (dynamic) IR-drop emitter (OpenROAD PSM "
                    "-transient).")
    ap.add_argument("--project", type=Path, default=None,
                    help="run dir — auto-discovers DEF/LEF/Liberty/SDC")
    ap.add_argument("--def", dest="def_file", type=Path, default=None)
    ap.add_argument("--tech-lef", type=Path, default=None)
    ap.add_argument("--cell-lef", type=Path, default=None)
    ap.add_argument("--liberty", type=Path, default=None)
    ap.add_argument("--macro-lef", type=Path, action="append", default=[])
    ap.add_argument("--sdc", type=Path, default=None)
    ap.add_argument("--net", default=None, help="power net (default: DEF discover)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output dynamic_ir.json (default reports/phase3/)")
    ap.add_argument("--static-json", type=Path, default=None,
                    help="Step-24 ir_drop.json for the exceeds-static compare")
    ap.add_argument("--container", default=_DEFAULT_CONTAINER)
    ap.add_argument("--metal-prefix", default="MET")
    ap.add_argument("--budget-pct", type=float, default=_DEFAULT_DYN_BUDGET_PCT,
                    help="dynamic droop budget as %% of Vdd (default 15 — the "
                         "dynamic tier is looser than static; quasi-static ≈2x)")
    ap.add_argument("--period-ns", type=float, default=None,
                    help="clock period (ns) for -transient (default: SDC-derived)")
    ap.add_argument("--steps", type=int, default=_DEFAULT_STEPS,
                    help="transient time-steps per period (default 100)")
    ap.add_argument("--decap-cap", default=None,
                    help="optional on-die decap (e.g. 1pF); default quasi-static")
    ns = ap.parse_args(argv)

    if ns.project:
        disc = _auto_discover(ns.project)
        ns.def_file = ns.def_file or disc["def"]
        ns.tech_lef = ns.tech_lef or disc["tech_lef"]
        ns.cell_lef = ns.cell_lef or disc["cell_lef"]
        ns.liberty = ns.liberty or disc["liberty"]
        ns.sdc = ns.sdc or disc["sdc"]
        if ns.out is None:
            ns.out = ns.project / "reports" / "phase3" / "dynamic_ir.json"
        if ns.static_json is None:
            sj = ns.project / "reports" / "phase3" / "ir_drop.json"
            ns.static_json = sj if sj.is_file() else None

    if ns.out is None:
        print("error: --out or --project required", file=sys.stderr)
        return 2
    missing = missing_required_inputs(
        ns.def_file, ns.tech_lef, ns.cell_lef, ns.liberty)
    if missing:
        payload = skip_result(
            f"cannot run: missing required input(s) {', '.join(missing)}",
            status="SKIPPED_MISSING_INPUTS")
        ns.out.parent.mkdir(parents=True, exist_ok=True)
        ns.out.write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps(payload, indent=2))
        return 0

    rc, payload = emit(
        def_file=ns.def_file, tech_lef=ns.tech_lef, cell_lef=ns.cell_lef,
        liberty=ns.liberty, macro_lefs=list(ns.macro_lef), sdc=ns.sdc,
        out_json=ns.out, power_net=ns.net, container=ns.container,
        metal_prefix=ns.metal_prefix, static_json=ns.static_json,
        budget_pct=ns.budget_pct, period_ns=ns.period_ns, steps=ns.steps,
        decap_cap=ns.decap_cap)
    print(json.dumps(payload, indent=2))
    return rc


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    raise SystemExit(_pr.exit_undetermined_on_stall(main, sys.argv[1:]))
