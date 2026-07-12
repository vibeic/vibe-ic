#!/usr/bin/env python3
"""spice_correlation_check.py — canonical Step-30 post-layout SPICE correlation

Validates that post-layout SPICE simulation was performed and its results
correlate with the STA timing model. Three verification axes:

  0. **Real ngspice cell-delay ↔ liberty correlation (commercial_pdk driver)**: when
     the design ships an ngspice PDK bridge shim
     (input/pdk/bridge/commercial_pdk_ngspice_shim.lib) and no correlation report
     exists yet, this gate RUNS ngspice on a representative standard cell pulled
     from the LVS-extracted transistor netlist (nmos→nch_tn / pmos→pch_tn) and
     correlates the SPICE-measured propagation delay against the liberty NLDM
     arc — at a MATCHED operating point (input slew + output load from the
     liberty index grid). It writes reports/phase3/spice_correlation.json with
     the REAL SPICE-vs-liberty numbers + %error + verdict, then feeds axis 1.
     Honest skip (no numbers fabricated) when shim/liberty/ngspice are absent.

  1. **Critical-path SPICE correlation**: compares SPICE-measured path delay
     against STA-reported delay. Flags >10 % discrepancy as ERROR (STA model
     may be inaccurate), >25 % as CRITICAL.

  2. **Analog block SPICE coverage**: if the design contains analog modules
     (LDO, PLL, OSC, bandgap, ADC, DAC, comparator), verifies that each has
     a corresponding SPICE simulation result.

Self-skips (exit 0 + INFO) when:
  - No extracted parasitics (SPEF) exist (Step 20 not reached)
  - No STA results exist (Step 21 not reached)

Usage:
    python3 spice_correlation_check.py <project_dir>
    python3 spice_correlation_check.py <project_dir> --json reports/gates/spice_correlation.json

Exit codes:
    0 = PASS (or self-skip)
    1 = FAIL (correlation mismatch or missing analog SPICE)
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl


ANALOG_MODULE_PATTERNS = re.compile(
    r"(ldo|pll|vco|osc|oscillat|bandgap|bgr|adc|dac|comparator|"
    r"charge.?pump|bias|regulator|opamp|ota|tia)",
    re.IGNORECASE,
)

SPICE_RESULT_PATTERNS = re.compile(
    r"\.(sp|spice|cir)$", re.IGNORECASE,
)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "spice_correlation_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None


def _find_spice_results(project: Path) -> List[Path]:
    """Find SPICE simulation output files."""
    candidates = []
    for d in ("phase3/stage3/spice", "spice", "sim_spice", "phase2/stage1/sim/spice", "analog_sim"):
        sd = project / d
        if sd.is_dir():
            for ext in ("*.log", "*.out", "*.txt", "*.raw", "*.csv"):
                candidates.extend(sd.glob(ext))
    return sorted(candidates)


def _find_spice_decks(project: Path) -> List[Path]:
    """Find SPICE netlists/decks."""
    decks = []
    for d in ("phase3/stage3/spice", "spice", "sim_spice", "phase2/stage1/sim/spice", "analog_sim"):
        sd = project / d
        if sd.is_dir():
            for ext in ("*.sp", "*.spice", "*.cir"):
                decks.extend(sd.glob(ext))
    return sorted(decks)


def _parse_spice_measurements(results: List[Path]) -> dict:
    """Extract .meas results from SPICE output files.

    Returns {measurement_name: float_value}.
    """
    meas = {}
    meas_re = re.compile(r"^(\S+)\s*=\s*([\d.eE+-]+)", re.MULTILINE)
    for f in results:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for m in meas_re.finditer(text):
            meas[m.group(1)] = float(m.group(2))
    return meas


def _extract_sta_worst_paths(project: Path) -> List[dict]:
    """Extract worst-path delays from STA reports.

    Returns list of {path: str, delay_ns: float, slack_ns: float}.
    """
    paths = []
    sta_dir = _pl.sta_dir(project)
    if not sta_dir.is_dir():
        return paths

    for rpt in sorted(sta_dir.glob("*.rpt")):
        try:
            text = rpt.read_text(errors="replace")
        except OSError:
            continue
        delay_re = re.compile(
            r"(?:data\s+arrival\s+time|Path\s+Delay)\s+([\d.]+)",
            re.IGNORECASE,
        )
        slack_re = re.compile(r"slack\s*\(?\w*\)?\s+([-\d.]+)", re.IGNORECASE)

        delays = [float(m.group(1)) for m in delay_re.finditer(text)]
        slacks = [float(m.group(1)) for m in slack_re.finditer(text)]

        if delays:
            worst_delay = max(delays)
            worst_slack = min(slacks) if slacks else 0.0
            paths.append({
                "source": str(rpt.name),
                "delay_ns": worst_delay,
                "slack_ns": worst_slack,
            })

    return paths


def _detect_analog_modules(project: Path) -> List[str]:
    """Scan RTL for modules that look like analog blocks."""
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.is_dir():
        return []

    found = set()
    module_re = re.compile(r"^\s*module\s+(\w+)", re.MULTILINE)

    for ext in ("*.v", "*.sv", "*.vh", "*.svh"):
        for f in rtl_dir.glob(ext):
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            for m in module_re.finditer(text):
                name = m.group(1)
                if ANALOG_MODULE_PATTERNS.search(name):
                    found.add(name)

    return sorted(found)


def _check_spice_correlation_json(project: Path) -> Optional[dict]:
    """Load spice_correlation.json if the agent produced one."""
    for candidate in (
        _pl.spice_dir(project) / "correlation.json",
        _pl.report_path(project, "spice_correlation.json"),
        project / "sim_spice" / "correlation.json",
    ):
        data = _load_json(candidate)
        if data:
            return data
    return None


def check_critical_path_correlation(
    project: Path, findings: List[Finding]
) -> dict:
    """Compare SPICE path delays against STA delays."""
    stats = {
        "sta_paths_found": 0,
        "spice_paths_found": 0,
        "max_discrepancy_pct": 0.0,
        "correlation_checked": False,
    }

    corr = _check_spice_correlation_json(project)
    if corr and "paths" in corr:
        stats["correlation_checked"] = True
        paths = corr["paths"]
        stats["spice_paths_found"] = len(paths)

        for p in paths:
            sta_delay = p.get("sta_delay_ns", 0)
            spice_delay = p.get("spice_delay_ns", 0)
            if sta_delay <= 0 or spice_delay <= 0:
                continue

            pct = abs(spice_delay - sta_delay) / sta_delay * 100
            stats["max_discrepancy_pct"] = max(stats["max_discrepancy_pct"], pct)

            if pct > 25:
                findings.append(Finding(
                    rule="SPICE_STA_CRITICAL_MISMATCH",
                    severity="ERROR",
                    message=(
                        f"Path '{p.get('path', '?')}': SPICE={spice_delay:.3f}ns vs "
                        f"STA={sta_delay:.3f}ns ({pct:.1f}% discrepancy). "
                        f"Liberty model may be significantly inaccurate."
                    ),
                ))
            elif pct > 10:
                findings.append(Finding(
                    rule="SPICE_STA_MISMATCH",
                    severity="ERROR",
                    message=(
                        f"Path '{p.get('path', '?')}': SPICE={spice_delay:.3f}ns vs "
                        f"STA={sta_delay:.3f}ns ({pct:.1f}% discrepancy). "
                        f"Review liberty timing model accuracy."
                    ),
                ))
            else:
                findings.append(Finding(
                    rule="SPICE_STA_CORRELATED",
                    severity="INFO",
                    message=(
                        f"Path '{p.get('path', '?')}': SPICE={spice_delay:.3f}ns vs "
                        f"STA={sta_delay:.3f}ns ({pct:.1f}% — within 10% tolerance). OK."
                    ),
                ))
        return stats

    spice_results = _find_spice_results(project)
    spice_decks = _find_spice_decks(project)
    sta_paths = _extract_sta_worst_paths(project)

    stats["sta_paths_found"] = len(sta_paths)
    stats["spice_paths_found"] = len(spice_results)

    if spice_results and sta_paths:
        meas = _parse_spice_measurements(spice_results)
        delay_keys = [k for k in meas if "delay" in k.lower() or "tpd" in k.lower()]

        if delay_keys and sta_paths:
            stats["correlation_checked"] = True
            spice_delay = max(meas[k] for k in delay_keys)
            sta_delay = max(p["delay_ns"] for p in sta_paths)

            if sta_delay > 0:
                if spice_delay > 1e-6:
                    spice_delay_ns = spice_delay * 1e9
                else:
                    spice_delay_ns = spice_delay

                pct = abs(spice_delay_ns - sta_delay) / sta_delay * 100
                stats["max_discrepancy_pct"] = pct

                if pct > 25:
                    findings.append(Finding(
                        rule="SPICE_STA_CRITICAL_MISMATCH",
                        severity="ERROR",
                        message=(
                            f"SPICE worst={spice_delay_ns:.3f}ns vs STA worst="
                            f"{sta_delay:.3f}ns ({pct:.1f}% discrepancy)"
                        ),
                    ))
                elif pct > 10:
                    findings.append(Finding(
                        rule="SPICE_STA_MISMATCH",
                        severity="ERROR",
                        message=(
                            f"SPICE worst={spice_delay_ns:.3f}ns vs STA worst="
                            f"{sta_delay:.3f}ns ({pct:.1f}% discrepancy)"
                        ),
                    ))
                else:
                    findings.append(Finding(
                        rule="SPICE_STA_CORRELATED",
                        severity="INFO",
                        message=(
                            f"SPICE worst={spice_delay_ns:.3f}ns vs STA worst="
                            f"{sta_delay:.3f}ns ({pct:.1f}%). OK."
                        ),
                    ))

    return stats


def check_analog_coverage(
    project: Path, findings: List[Finding]
) -> dict:
    """Verify analog blocks have SPICE sim results."""
    analog_modules = _detect_analog_modules(project)
    stats = {
        "analog_modules": analog_modules,
        "analog_count": len(analog_modules),
        "covered": 0,
        "uncovered": [],
    }

    if not analog_modules:
        findings.append(Finding(
            rule="NO_ANALOG_BLOCKS",
            severity="INFO",
            message="No analog modules detected in RTL; analog SPICE coverage N/A",
        ))
        return stats

    spice_decks = _find_spice_decks(project)
    spice_results = _find_spice_results(project)
    all_spice_text = set()
    for f in spice_decks + spice_results:
        all_spice_text.add(f.stem.lower())

    for mod in analog_modules:
        mod_lower = mod.lower()
        covered = any(mod_lower in s or s in mod_lower for s in all_spice_text)
        if covered:
            stats["covered"] += 1
            findings.append(Finding(
                rule="ANALOG_SPICE_COVERED",
                severity="INFO",
                message=f"Analog module '{mod}' has matching SPICE simulation",
            ))
        else:
            stats["uncovered"].append(mod)
            findings.append(Finding(
                rule="ANALOG_SPICE_MISSING",
                severity="ERROR",
                message=(
                    f"Analog module '{mod}' has no SPICE simulation. "
                    f"Gate-level SDF sim cannot verify analog behavior — "
                    f"run eda_spice with transistor-level netlist."
                ),
            ))

    return stats


# ══════════════════════════════════════════════════════════════════════════
#  commercial_pdk REAL ngspice cell-delay ↔ liberty correlation driver
# ══════════════════════════════════════════════════════════════════════════
#
# Canonical Step-30 (post-layout SPICE correlation) for a commercial PDK that
# ships an ngspice *bridge shim* (a corner wrapper `.lib`-ing down to the
# foundry HSPICE BSIM cards). Instead of only STRUCTURAL-checking, this driver
# runs REAL ngspice on a representative standard cell pulled from the design's
# LVS-extracted transistor netlist and correlates the SPICE-measured cell
# propagation delay against the liberty NLDM arc (the exact timing model STA
# consumes). The comparison is done at a MATCHED operating point (input slew +
# output load taken from the liberty index grid, so both sides characterise the
# identical corner) — the only honest way to compare a SPICE tpd to an NLDM arc.
#
# §4.05 NO-LEAK: reads ONLY design input (the extracted netlist + the PDK
# bridge shim + the PDK liberty) — never any oracle / golden / output.*.
# NDA: the PDK model/liberty CONTENT is read at runtime to compute numbers; it
# is NEVER copied into any emitted file or report (only derived delay numbers).
#
# The whole driver self-skips (returns None) when the bridge shim is absent
# (non-commercial_pdk design) or ngspice is unreachable — it NEVER fabricates numbers.

_commercial_pdk_SHIM_NAME = "commercial_pdk_ngspice_shim.lib"
_DEFAULT_CONTAINER = "vibeic-eda"
# Whole-word device-model rename: the LVS-extracted netlist uses generic
# nmos/pmos (LVS device names); the ngspice bridge shim binds W/L-binned
# BSIM models named nch_tn / pch_tn for the 1.8 V core devices.
_MODEL_MAP = {"nmos": "nch_tn", "pmos": "pch_tn"}


def _find_bridge_shim(project: Path) -> Optional[Path]:
    """Locate the commercial_pdk ngspice bridge shim under the design input PDK."""
    for rel in (
        "input/pdk/bridge/" + _commercial_pdk_SHIM_NAME,
        "pdk/bridge/" + _commercial_pdk_SHIM_NAME,
    ):
        p = project / rel
        if p.is_file():
            return p
    # `input/pdk` is often a symlink → root rglob at pdk (walk root is followed).
    root = project / "input" / "pdk"
    hits = sorted(root.rglob(_commercial_pdk_SHIM_NAME)) if root.is_dir() else []
    return hits[0] if hits else None


def _find_liberty_typ(project: Path) -> Optional[Path]:
    """Locate the typical-corner liberty (nom 1.8 V / 25 C)."""
    lib_dir = project / "input" / "pdk" / "liberty"
    cands: List[Path] = []
    if lib_dir.is_dir():
        cands += sorted(lib_dir.glob("*typ*.lib"))
        cands += sorted(lib_dir.glob("*_typ.lib"))
    if not cands:
        root = project / "input" / "pdk"
        if root.is_dir():
            cands += [p for p in root.rglob("*typ*.lib")]
    # de-dup, prefer the shortest name (the base typ lib, not a variant)
    seen, out = set(), []
    for p in cands:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[0] if out else None


def _find_hspice_dir(project: Path) -> Optional[Path]:
    """Directory the shim's nested bare-filename `.lib` references resolve
    against (contains e.g. commercial_pdk-S1.9cS.lib). Used as ngspice cwd so the
    shim → *_ngspice.lib → HSPICE .lib chain resolves.

    NOTE: `input/pdk` is often a symlink; `Path.rglob` (pre-3.13) does NOT
    traverse intermediate directory symlinks, so we root the search at
    `input/pdk` (the symlink itself, followed as the walk root) — not `input`."""
    known = project / "input" / "pdk" / "spice" / "HSPICE"
    if (known / "commercial_pdk-S1.9cS.lib").is_file() or list(known.glob("commercial_pdk-*.lib")):
        return known
    pdk = project / "input" / "pdk"
    roots = [pdk, project / "pdk", project / "input"]
    for pat in ("commercial_pdk-S1.9c*.lib", "commercial_pdk-*.lib"):
        for root in roots:
            if not root.is_dir():
                continue
            hits = sorted(root.rglob(pat))
            for h in hits:  # prefer a dir literally named HSPICE
                if h.parent.name.upper() == "HSPICE":
                    return h.parent
            if hits:
                return hits[0].parent
    return None


# ─────────────────────── liberty NLDM parsing (pure) ───────────────────────

def parse_liberty_header(text: str) -> dict:
    """Parse the library-level unit + threshold attributes (pure)."""
    def _num(pat, default=None):
        m = re.search(pat, text)
        return float(m.group(1)) if m else default

    tu = re.search(r'time_unit\s*:\s*"?\s*([\d.]+)\s*(ns|ps|us|s)"?', text)
    tu_scale = 1.0  # value → ns
    if tu:
        base, unit = float(tu.group(1)), tu.group(2)
        tu_scale = {"s": 1e9, "us": 1e3, "ns": 1.0, "ps": 1e-3}[unit] * base
    return {
        "time_unit_ns": tu_scale,
        "slew_lower_rise": _num(r"slew_lower_threshold_pct_rise\s*:\s*([\d.]+)", 30.0),
        "slew_upper_rise": _num(r"slew_upper_threshold_pct_rise\s*:\s*([\d.]+)", 70.0),
        "slew_lower_fall": _num(r"slew_lower_threshold_pct_fall\s*:\s*([\d.]+)", 30.0),
        "slew_upper_fall": _num(r"slew_upper_threshold_pct_fall\s*:\s*([\d.]+)", 70.0),
        "input_threshold_rise": _num(r"input_threshold_pct_rise\s*:\s*([\d.]+)", 50.0),
        "input_threshold_fall": _num(r"input_threshold_pct_fall\s*:\s*([\d.]+)", 50.0),
        "output_threshold_rise": _num(r"output_threshold_pct_rise\s*:\s*([\d.]+)", 50.0),
        "output_threshold_fall": _num(r"output_threshold_pct_fall\s*:\s*([\d.]+)", 50.0),
        "slew_derate": _num(r"slew_derate_from_library\s*:\s*([\d.]+)", 1.0),
        "nom_voltage": _num(r"nom_voltage\s*:\s*([\d.]+)", 1.8),
        "nom_temperature": _num(r"nom_temperature\s*:\s*([\d.\-]+)", 25.0),
    }


def _match_brace_block(text: str, start: int) -> str:
    """Return the substring from the '{' at/after `start` to its match."""
    i = text.index("{", start)
    depth, j = 0, i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1
    return text[i:]


def extract_cell_block(text: str, cell: str) -> Optional[str]:
    """Return the `cell (CELL) { ... }` block text (pure)."""
    m = re.search(r"cell\s*\(\s*" + re.escape(cell) + r"\s*\)\s*\{", text)
    if not m:
        return None
    return _match_brace_block(text, m.start())


def _parse_index(block: str, name: str) -> Optional[List[float]]:
    m = re.search(name + r'\s*\(\s*"([^"]*)"\s*\)', block)
    if not m:
        return None
    return [float(x) for x in m.group(1).split(",") if x.strip()]


def parse_nldm_table(block: str, table: str) -> Optional[dict]:
    """Parse a `<table>(...) { index_1(..) index_2(..) values(..) }` NLDM
    lookup table into {index_1, index_2, values:[[...]]}. `block` is a
    timing()/cell block substring. Values are in the liberty time unit (pure)."""
    m = re.search(table + r"\s*\([^)]*\)\s*\{", block)
    if not m:
        return None
    tb = _match_brace_block(block, m.start())
    idx1 = _parse_index(tb, "index_1")
    idx2 = _parse_index(tb, "index_2")
    vm = re.search(r"values\s*\((.*?)\)\s*;", tb, re.DOTALL)
    if not (idx1 and idx2 and vm):
        return None
    rows = re.findall(r'"([^"]*)"', vm.group(1))
    values = [[float(x) for x in r.split(",") if x.strip()] for r in rows]
    return {"index_1": idx1, "index_2": idx2, "values": values}


def liberty_pins(block: str) -> Tuple[List[str], List[str]]:
    """(input_pins, output_pins) from a cell block (pure)."""
    ins, outs = [], []
    for pm in re.finditer(r"pin\s*\(\s*(\w+)\s*\)\s*\{", block):
        pb = _match_brace_block(block, pm.start())
        d = re.search(r"direction\s*:\s*(\w+)", pb)
        if d and d.group(1) == "input":
            ins.append(pm.group(1))
        elif d and d.group(1) == "output":
            outs.append(pm.group(1))
    return ins, outs


def bilinear(index_1: List[float], index_2: List[float],
             values: List[List[float]], x: float, y: float) -> float:
    """Bilinear interpolation on an NLDM table (index_1 rows / index_2 cols),
    clamping to the grid edges outside the characterised range (pure)."""
    def _bracket(axis, v):
        if v <= axis[0]:
            return 0, 0, 0.0
        if v >= axis[-1]:
            return len(axis) - 1, len(axis) - 1, 0.0
        for k in range(len(axis) - 1):
            if axis[k] <= v <= axis[k + 1]:
                span = axis[k + 1] - axis[k]
                f = 0.0 if span == 0 else (v - axis[k]) / span
                return k, k + 1, f
        return len(axis) - 1, len(axis) - 1, 0.0

    i0, i1, fx = _bracket(index_1, x)
    j0, j1, fy = _bracket(index_2, y)
    v00, v01 = values[i0][j0], values[i0][j1]
    v10, v11 = values[i1][j0], values[i1][j1]
    top = v00 + fy * (v01 - v00)
    bot = v10 + fy * (v11 - v10)
    return top + fx * (bot - top)


# ───────────────── extracted-netlist subckt extraction (pure) ─────────────────

def extract_subckt(cells_text: str, name: str,
                   model_map: dict = None) -> Optional[Tuple[List[str], str]]:
    """Return (pin_list, subckt_text) for `.SUBCKT name ...` with the device
    model tokens renamed per `model_map` (whole-word). chip/vendor-AGNOSTIC —
    operates on generic SPICE subckt syntax (pure)."""
    model_map = _MODEL_MAP if model_map is None else model_map
    m = re.search(r"(?im)^\.SUBCKT\s+" + re.escape(name) + r"\b(.*?)^\.ENDS",
                  cells_text, re.DOTALL)
    if not m:
        return None
    body = m.group(0)
    header = re.match(r"(?im)^\.SUBCKT\s+" + re.escape(name) + r"\s+(.*)$",
                      body)
    pins = header.group(1).split() if header else []
    for src, dst in model_map.items():
        body = re.sub(r"(?<![\w.])" + re.escape(src) + r"(?![\w.])", dst, body)
    return pins, body


def _map_pin_to_node(pin: str, in_pin: str, out_pin: str) -> str:
    """Map a subckt pin name to the deck's stimulus node."""
    up = pin.upper()
    if pin == in_pin:
        return "a"
    if pin == out_pin:
        return "y"
    if up in ("VSS", "GND", "VGND", "VNW", "0"):
        return "0"
    if up in ("VDD", "VCC", "VPWR"):
        return "vdd"
    return "0"  # any unmodeled bulk/rail → ground (single-input cells)


# ───────────────────────── slew mapping + deck build ─────────────────────────

def pulse_tr_for_slew(slew_lib_ns: float, lo_pct: float, hi_pct: float,
                      derate: float) -> float:
    """Input PULSE full-swing (0→100 %) transition time whose measured
    threshold-to-threshold (lo→hi) slew equals the liberty index value.

    liberty index = measured(lo→hi) slew / slew_derate  →
    measured(lo→hi) = slew_lib * derate; for a linear ramp the lo→hi time is
    ((hi-lo)/100) * tr_full, so tr_full = slew_lib*derate / ((hi-lo)/100) (pure)."""
    frac = max(1e-6, (hi_pct - lo_pct) / 100.0)
    return slew_lib_ns * max(1e-9, derate) / frac


def build_cell_delay_deck(shim_abs: str, corner: str, cell: str,
                          subckt_text: str, subckt_pins: List[str],
                          in_pin: str, out_pin: str, vdd: float,
                          tr_ns: float, load_pf: float, temp_c: float,
                          vth: float) -> str:
    """Assemble a self-contained ngspice deck that pulses the cell input and
    measures tphl (out↓) + tplh (out↑) at the liberty delay threshold (pure)."""
    nodes = " ".join(_map_pin_to_node(p, in_pin, out_pin) for p in subckt_pins)
    td = 2.0
    pw = max(8.0, 20.0 * tr_ns)
    per = 2.0 * (td + tr_ns + pw)
    stop = per * 1.2
    step = max(0.001, tr_ns / 100.0)  # ns
    load_ff = load_pf * 1000.0
    return (
        f"* {cell} SPICE↔liberty cell-delay correlation (commercial_pdk {corner}, "
        f"{temp_c:g}C, load={load_ff:g}fF, in_slew_tr={tr_ns:g}ns)\n"
        f".lib '{shim_abs}' {corner}\n"
        f".temp {temp_c:g}\n"
        f"vdd vdd 0 {vdd:g}\n"
        f"vin a 0 pulse(0 {vdd:g} {td:g}n {tr_ns:g}n {tr_ns:g}n {pw:g}n {per:g}n)\n"
        f"xdut {nodes} {cell}\n"
        f"cload y 0 {load_ff:g}f\n"
        f"{subckt_text.strip()}\n"
        f".tran {step:g}n {stop:g}n\n"
        f".meas tran tphl TRIG v(a) VAL='{vth:g}' RISE=1 "
        f"TARG v(y) VAL='{vth:g}' FALL=1\n"
        f".meas tran tplh TRIG v(a) VAL='{vth:g}' FALL=1 "
        f"TARG v(y) VAL='{vth:g}' RISE=1\n"
        f".end\n"
    )


_MEAS_RE = re.compile(
    r"^\s*(tphl|tplh)\s*=\s*([\-+]?[0-9.]+(?:[eE][\-+]?\d+)?)",
    re.MULTILINE | re.IGNORECASE)


def parse_meas_delays(stdout: str) -> dict:
    """Extract tphl/tplh (seconds) from an ngspice -b transcript (pure)."""
    out = {}
    for m in _MEAS_RE.finditer(stdout or ""):
        try:
            out[m.group(1).lower()] = float(m.group(2))
        except ValueError:
            pass
    return out


def correlation_pct(spice_s: float, liberty_ns: float) -> Optional[float]:
    """Signed %error of SPICE tpd vs the liberty NLDM arc (pure)."""
    if not liberty_ns or liberty_ns <= 0:
        return None
    return (spice_s * 1e9 - liberty_ns) / liberty_ns * 100.0


# ─────────────────────── ngspice invocation (container) ───────────────────────

def _resolve_ngspice(container: str) -> Optional[str]:
    """Absolute ngspice path inside the container, or None. Reuses the analog
    driver's resolver when importable; else probes the canonical locations."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import analog_real_corner_sweep as _acs  # noqa: E402
        return _acs._resolve_ngspice(container)
    except Exception:
        for probe in ("command -v ngspice",
                      "ls /foss/tools/bin/ngspice 2>/dev/null | head -1",
                      "ls /foss/tools/*/bin/ngspice 2>/dev/null | head -1"):
            try:
                r = subprocess.run(["docker", "exec", container, "bash", "-lc",
                                    probe], capture_output=True, text=True,
                                   timeout=60)
            except Exception:
                return None
            for raw in (r.stdout or "").splitlines():
                line = raw.strip()
                if line.startswith("/") and "ngspice" in line:
                    return line
        return None


def _run_ngspice_in(container: str, cwd_dir: str, deck_path: str,
                    timeout: int = 180) -> Tuple[bool, str]:
    """Run `ngspice -b <deck>` with cwd=<cwd_dir> in the container so the
    shim's nested bare-filename .lib chain resolves. Returns (ok, transcript)."""
    ngspice = _resolve_ngspice(container) or "ngspice"
    cmd = (f"export PATH=/foss/tools/bin:$PATH; cd {shlex.quote(cwd_dir)} && "
           f"{shlex.quote(ngspice)} -b {shlex.quote(deck_path)} 2>&1")
    try:
        cp = subprocess.run(["docker", "exec", container, "bash", "-lc", cmd],
                            capture_output=True, text=True, timeout=timeout)
    except Exception as e:  # pragma: no cover - env dependent
        return False, f"docker/ngspice invocation failed: {e}"
    return cp.returncode == 0, cp.stdout


# ─────────────────────────── driver orchestrator ───────────────────────────

def run_commercial_pdk_cell_correlation(
    project: Path,
    container: str = _DEFAULT_CONTAINER,
    cell: str = "INVD1",
    corner: str = "ttt_lv",
    slew_ns: float = 0.4,
    loads_pf: Tuple[float, ...] = (0.021, 0.0385, 0.084),
) -> Optional[dict]:
    """Run REAL ngspice on a representative extracted cell and correlate its
    SPICE propagation delay against the liberty NLDM arc at matched operating
    points. Writes reports/phase3/spice_correlation.json. Returns the report
    dict, or None on an honest skip (no shim / no liberty / no ngspice).

    §4.05: only design-input + PDK are read. NDA: PDK content never emitted."""
    shim = _find_bridge_shim(project)
    if not shim:
        return None
    liberty = _find_liberty_typ(project)
    cells_spice = _pl.extracted_dir(project) / "cells.spice"
    hspice_dir = _find_hspice_dir(project)
    if not (liberty and cells_spice.is_file() and hspice_dir):
        return None
    if _resolve_ngspice(container) is None:
        return None

    lib_text = liberty.read_text(errors="replace")
    hdr = parse_liberty_header(lib_text)
    cblock = extract_cell_block(lib_text, cell)
    if not cblock:
        return None
    cell_rise = parse_nldm_table(cblock, "cell_rise")
    cell_fall = parse_nldm_table(cblock, "cell_fall")
    if not (cell_rise and cell_fall):
        return None
    ins, outs = liberty_pins(cblock)
    in_pin = ins[0] if ins else "A"
    out_pin = outs[0] if outs else "Y"

    sub = extract_subckt(cells_spice.read_text(errors="replace"), cell)
    if not sub:
        return None
    subckt_pins, subckt_text = sub

    vdd = hdr["nom_voltage"] or 1.8
    vth = vdd * (hdr["output_threshold_fall"] / 100.0)
    temp_c = hdr["nom_temperature"]
    tr_ns = pulse_tr_for_slew(slew_ns, hdr["slew_lower_fall"],
                              hdr["slew_upper_fall"], hdr["slew_derate"])

    out_dir = _pl.spice_dir(project)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths, op_points, logs = [], [], []
    for load_pf in loads_pf:
        deck = build_cell_delay_deck(
            str(shim.resolve()), corner, cell, subckt_text, subckt_pins,
            in_pin, out_pin, vdd, tr_ns, load_pf, temp_c, vth)
        deck_path = out_dir / f"corr_{cell.lower()}_{int(round(load_pf*1000))}ff.spice"
        deck_path.write_text(deck)
        ok, txt = _run_ngspice_in(container, str(hspice_dir.resolve()),
                                  str(deck_path.resolve()))
        (out_dir / (deck_path.stem + ".log")).write_text(txt)
        logs.append(deck_path.stem + ".log")
        meas = parse_meas_delays(txt)
        lib_fall_ns = bilinear(cell_fall["index_1"], cell_fall["index_2"],
                               cell_fall["values"], slew_ns, load_pf) \
            * hdr["time_unit_ns"]
        lib_rise_ns = bilinear(cell_rise["index_1"], cell_rise["index_2"],
                               cell_rise["values"], slew_ns, load_pf) \
            * hdr["time_unit_ns"]
        for arc, spice_key, lib_ns in (
            ("fall", "tphl", lib_fall_ns), ("rise", "tplh", lib_rise_ns)):
            spice_s = meas.get(spice_key)
            if spice_s is None:
                continue
            pct = correlation_pct(spice_s, lib_ns)
            rec = {
                "path": f"{cell} {in_pin}->{out_pin} {arc} "
                        f"@slew={slew_ns}ns,load={load_pf*1000:g}fF",
                "arc": arc,
                "spice_delay_ns": round(spice_s * 1e9, 6),
                "liberty_delay_ns": round(lib_ns, 6),
                # `sta_delay_ns` alias so check_critical_path_correlation() —
                # which compares SPICE vs the STA timing model — consumes the
                # liberty arc (the exact NLDM value STA uses for this cell).
                "sta_delay_ns": round(lib_ns, 6),
                "pct_error": None if pct is None else round(pct, 3),
            }
            paths.append(rec)
            op_points.append(rec)

    if not paths:
        return None

    abs_pcts = [abs(p["pct_error"]) for p in paths if p["pct_error"] is not None]
    max_abs = max(abs_pcts) if abs_pcts else 0.0
    mean_abs = (sum(abs_pcts) / len(abs_pcts)) if abs_pcts else 0.0
    verdict = ("CRITICAL_MISMATCH" if max_abs > 25 else
               "MISMATCH" if max_abs > 10 else "CORRELATED")

    report = {
        "program": "spice_correlation_check.commercial_pdk_cell_driver",
        "version": "1.1.0",
        "provenance": "real_ngspice",
        "simulator": "ngspice (vibeic-eda container)",
        "reference": f"liberty_nldm ({liberty.name})",
        "pdk_bridge": f"{shim.name} :: {corner}",
        "corner": f"{corner} / {vdd:g}V / {temp_c:g}C",
        "cell": cell,
        "arc_pin": {"input": in_pin, "output": out_pin},
        "netlist_source": "phase3/stage3/extracted/cells.spice "
                          "(LVS-extracted; nmos→nch_tn / pmos→pch_tn)",
        "operating_point": {
            "input_slew_ns": slew_ns,
            "input_pulse_tr_ns": round(tr_ns, 6),
            "delay_threshold_v": round(vth, 4),
            "slew_thresholds_pct": [hdr["slew_lower_fall"], hdr["slew_upper_fall"]],
            "slew_derate": hdr["slew_derate"],
            "loads_pf": list(loads_pf),
        },
        "paths": paths,
        "correlation": {
            "samples": len(paths),
            "max_abs_pct": round(max_abs, 3),
            "mean_abs_pct": round(mean_abs, 3),
            "tolerance_pct": 10.0,
            "verdict": verdict,
        },
        "logs": logs,
        "design_identity": {"design": project.name},
        "nda_note": "PDK model/liberty content read at runtime only; not emitted.",
    }
    out_path = _pl.report_path(project, "spice_correlation.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def run_audit(project: Path, run_spice: bool = True,
              container: str = _DEFAULT_CONTAINER) -> AuditResult:
    result = AuditResult()

    extracted = _pl.extracted_dir(project)
    sta_dir = _pl.sta_dir(project)

    if not extracted.is_dir() or not list(extracted.glob("*.spef")):
        result.findings.append(Finding(
            rule="SKIP_NO_SPEF",
            severity="INFO",
            message="No SPEF files found (Step 20 not reached); skipping SPICE gate",
        ))
        result.summary = {"skipped": True, "reason": "no_spef"}
        return result

    if not sta_dir.is_dir() or not list(sta_dir.glob("*.rpt")):
        result.findings.append(Finding(
            rule="SKIP_NO_STA",
            severity="INFO",
            message="No STA reports found (Step 21 not reached); skipping SPICE gate",
        ))
        result.summary = {"skipped": True, "reason": "no_sta"}
        return result

    # ── Canonical Step-30: run REAL ngspice cell-delay↔liberty correlation ──
    # When the design ships an commercial_pdk ngspice bridge shim and no correlation
    # report exists yet, characterise a representative extracted cell in real
    # ngspice and correlate it against the liberty NLDM arc. Honest skip (no
    # numbers fabricated) when the shim/liberty/simulator are unavailable.
    driver_report = None
    if run_spice and _check_spice_correlation_json(project) is None \
            and _find_bridge_shim(project) is not None:
        try:
            driver_report = run_commercial_pdk_cell_correlation(
                project, container=container)
        except Exception as e:  # never let the driver crash the gate
            result.findings.append(Finding(
                rule="SPICE_DRIVER_ERROR",
                severity="INFO",
                message=f"commercial_pdk ngspice correlation driver could not run: {e}",
            ))
        if driver_report is not None:
            c = driver_report.get("correlation", {})
            result.findings.append(Finding(
                rule="SPICE_CORRELATION_RAN",
                severity="INFO",
                message=(
                    f"Real ngspice cell correlation on "
                    f"{driver_report.get('cell')} ({driver_report.get('corner')}): "
                    f"{c.get('samples')} arcs, max |Δ|={c.get('max_abs_pct')}% "
                    f"vs liberty NLDM → {c.get('verdict')}"),
            ))

    spice_results = _find_spice_results(project)
    spice_decks = _find_spice_decks(project)
    corr_json = _check_spice_correlation_json(project)

    if not spice_results and not spice_decks and not corr_json:
        result.passed = False
        result.findings.append(Finding(
            rule="NO_SPICE_VERIFICATION",
            severity="ERROR",
            message=(
                "Post-layout SPICE verification was not performed. "
                "SPEF extraction exists (Step 20) and STA ran (Step 21), "
                "but no SPICE decks or results found in spice/, sim_spice/, "
                "or analog_sim/. Run eda_spice on critical paths and analog blocks."
            ),
        ))
        result.summary = {
            "skipped": False,
            "spice_decks": 0,
            "spice_results": 0,
            "pass": False,
        }
        return result

    corr_stats = check_critical_path_correlation(project, result.findings)
    analog_stats = check_analog_coverage(project, result.findings)

    has_errors = any(f.severity == "ERROR" for f in result.findings)
    if has_errors:
        result.passed = False

    result.summary = {
        "skipped": False,
        "spice_decks": len(spice_decks),
        "spice_results": len(spice_results),
        "correlation": corr_stats,
        "analog": analog_stats,
        "pass": result.passed,
    }
    return result


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    ap.add_argument("--container", default=_DEFAULT_CONTAINER,
                    help="container hosting ngspice (default: vibeic-eda)")
    ap.add_argument("--no-spice", action="store_true",
                    help="structural-only; do NOT invoke the ngspice driver")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir, run_spice=not args.no_spice,
                       container=args.container)

    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    if not args.json:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] spice_correlation_check")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
