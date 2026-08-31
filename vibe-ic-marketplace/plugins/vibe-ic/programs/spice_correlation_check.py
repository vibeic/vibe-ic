#!/usr/bin/env python3
"""spice_correlation_check.py — canonical Step-30 post-layout SPICE correlation

Validates that post-layout SPICE simulation was performed and its results
correlate with the STA timing model. Three verification axes:

  0. **Real ngspice cell-delay ↔ liberty correlation (commercial-PDK driver)**: when
     the design ships an ngspice PDK bridge shim
     (input/pdk/bridge/*_ngspice_shim.lib) and no correlation report
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

Self-skips when:
  - No extracted parasitics (SPEF) exist (Step 20 not reached)
  - No STA results exist (Step 21 not reached)

Usage:
    python3 spice_correlation_check.py <project_dir>
    python3 spice_correlation_check.py <project_dir> --json reports/gates/spice_correlation.json

Exit codes:
    0 = PASS: SPEF + STA both exist and the SPICE evidence correlates with
        the timing model
    1 = FAIL (correlation mismatch or missing analog SPICE)
    2 = VACUOUS: nothing was examined — the design has not reached Step 20
        (no SPEF) or Step 21 (no STA), so there is no post-layout timing to
        correlate against. #521: both used to be rc 0, on 197 of the 200
        tracked project roots. Note that the DIFFERENT case — SPEF and STA
        both present but no SPICE run at all — is deliberately NOT vacuous:
        it sets `skipped: False` and FAILs NO_SPICE_VERIFICATION, and that is
        unchanged here. Also rc 2 for an IO / parse error.
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
import _vacuous_exit as _vx
import _commercial_pdk as _cpdk  # config-driven commercial-PDK id (NDA: no SKU in source)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _progress_run as _pr  # noqa: E402


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


# A real STA numeric token: optional sign, integer, optional fraction, optional
# exponent. Deliberately does NOT admit a bare run of '-' (a report separator
# line), so it can never be handed to float(). chip/PDK-AGNOSTIC.
_STA_NUM = r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"


def _safe_float(tok: str):
    """float(tok) that returns None instead of raising on a non-numeric token
    (e.g. a '----' separator the STA report interleaves between blocks). Keeps
    the timing-report scrapers crash-proof against unforeseen line shapes."""
    try:
        return float(tok)
    except (TypeError, ValueError):
        return None


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
        # Arrival/path delay in EITHER column order, anchored to the SAME line
        # ([ \t], never \s): "Path Delay   <v>" / "data arrival time   <v>"
        # (value AFTER) and OpenROAD's "<v>   data arrival time" (value BEFORE,
        # the cumulative-time column). The pre-fix `...\s+([\d.]+)` spanned the
        # newline and read the FOLLOWING line's number as the arrival time.
        delay_after_re = re.compile(
            r"(?:data\s+arrival\s+time|Path\s+Delay)[ \t]+(" + _STA_NUM + r")",
            re.IGNORECASE,
        )
        delay_before_re = re.compile(
            r"(" + _STA_NUM + r")[ \t]+data\s+arrival\s+time", re.IGNORECASE)
        # OpenROAD `report_checks` prints the slack value on the SAME line as
        # the word "slack", in EITHER order — "<slack>   slack (MET)" (value
        # FIRST, current OpenROAD) or "slack (MET)   <slack>" (value LAST, some
        # OpenSTA prints) — and follows the block with a run of '-' separator
        # dashes. Anchor every capture to the SAME line ([ \t], never \s which
        # spans the newline into the dashes) and accept ONLY a real numeric
        # token, so a separator line can never be swallowed into float(). The
        # pre-fix `[-\d.]+` did exactly that (its \s+ ate the newline, its class
        # then matched the dashes) and raised ValueError, aborting the whole
        # Post-Layout SPICE Verification / Step 30 gate. chip/PDK-AGNOSTIC.
        slack_before_re = re.compile(
            r"(" + _STA_NUM + r")[ \t]+slack\b", re.IGNORECASE)
        slack_after_re = re.compile(
            r"slack[ \t]*\(?\w*\)?[ \t]*[:=]?[ \t]+(" + _STA_NUM + r")",
            re.IGNORECASE)
        worst_re = re.compile(
            r"(?:worst[ \t]+slack|wns)[ \t]*(?:max|min)?[ \t]+("
            + _STA_NUM + r")", re.IGNORECASE)

        delays = []
        for _rx in (delay_after_re, delay_before_re):
            for m in _rx.finditer(text):
                v = _safe_float(m.group(1))
                if v is not None:
                    delays.append(v)
        slacks = []
        for _rx in (slack_before_re, slack_after_re, worst_re):
            for m in _rx.finditer(text):
                v = _safe_float(m.group(1))
                if v is not None:
                    slacks.append(v)

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
    if corr and isinstance(corr.get("correlation"), dict) \
            and corr["correlation"].get("liberty_spef_cone_delay_ns"):
        c = corr["correlation"]
        stats["correlation_checked"] = True
        stats["spice_paths_found"] = 1
        stats["max_discrepancy_pct"] = abs(float(c.get("pct_error", 0.0)))
        verdict = c.get("verdict")
        severity = "ERROR" if verdict in (
            "MISMATCH", "CRITICAL_MISMATCH") else "INFO"
        findings.append(Finding(
            rule="SPICE_STA_" + str(verdict or "UNKNOWN"),
            severity=severity,
            message=(
                f"Critical path transistor simulation: "
                f"SPICE={c.get('spice_path_delay_ns')}ns vs "
                f"Liberty+SPEF={c.get('liberty_spef_cone_delay_ns')}ns "
                f"({c.get('pct_error')}%; derived tolerance "
                f"{c.get('tolerance_pct')}%) -> {verdict}"),
        ))
        return stats
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
#  Commercial-PDK REAL ngspice cell-delay ↔ liberty correlation driver
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
# (design without the bridge shim) or ngspice is unreachable — it NEVER fabricates numbers.

_DEFAULT_CONTAINER = "vibeic-eda"
# Whole-word device-model rename: the LVS-extracted netlist uses generic
# nmos/pmos (LVS device names); the ngspice bridge shim binds W/L-binned
# BSIM models named nch_tn / pch_tn for the 1.8 V core devices.
_MODEL_MAP = {"nmos": "nch_tn", "pmos": "pch_tn"}


def _find_bridge_shim(project: Path) -> Optional[Path]:
    """Locate the commercial-PDK ngspice bridge shim under the design input PDK.
    The shim filename comes from the private config; when unconfigured (public
    install) this returns None and the whole SPICE driver self-skips."""
    shim_name = _cpdk.ngspice_shim_name()
    if not shim_name:
        return None
    for rel in (
        "input/pdk/bridge/" + shim_name,
        "pdk/bridge/" + shim_name,
    ):
        p = project / rel
        if p.is_file():
            return p
    # `input/pdk` is often a symlink → root rglob at pdk (walk root is followed).
    root = project / "input" / "pdk"
    hits = sorted(root.rglob(shim_name)) if root.is_dir() else []
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
    against (contains the foundry HSPICE `.lib` files). Used as ngspice cwd so the
    shim → *_ngspice.lib → HSPICE .lib chain resolves.

    NOTE: `input/pdk` is often a symlink; `Path.rglob` (pre-3.13) does NOT
    traverse intermediate directory symlinks, so we root the search at
    `input/pdk` (the symlink itself, followed as the walk root) — not `input`."""
    # HSPICE `.lib` glob patterns come from the private config; unconfigured
    # (public install) -> no patterns -> nothing found -> the driver self-skips.
    lib_globs = _cpdk.hspice_lib_globs()
    if not lib_globs:
        return None
    known = project / "input" / "pdk" / "spice" / "HSPICE"
    if any(list(known.glob(g)) for g in lib_globs):
        return known
    pdk = project / "input" / "pdk"
    roots = [pdk, project / "pdk", project / "input"]
    for pat in lib_globs:
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
    cap = re.search(
        r"capacitive_load_unit\s*\(\s*([\d.]+)\s*,\s*(ff|pf|nf)\s*\)",
        text, re.IGNORECASE)
    cap_scale_pf = 1.0
    if cap:
        cap_scale_pf = float(cap.group(1)) * {
            "ff": 1e-3, "pf": 1.0, "nf": 1e3,
        }[cap.group(2).lower()]
    return {
        "time_unit_ns": tu_scale,
        "cap_unit_pf": cap_scale_pf,
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


def _local_grid_values(table: dict, x: float, y: float) -> List[float]:
    """Four NLDM samples bracketing ``(x, y)`` (duplicates at edges)."""
    def _indices(axis, value):
        if value <= axis[0]:
            return 0, 0
        if value >= axis[-1]:
            last = len(axis) - 1
            return last, last
        for i in range(len(axis) - 1):
            if axis[i] <= value <= axis[i + 1]:
                return i, i + 1
        last = len(axis) - 1
        return last, last
    i0, i1 = _indices(table["index_1"], x)
    j0, j1 = _indices(table["index_2"], y)
    values = table["values"]
    return [values[i0][j0], values[i0][j1],
            values[i1][j0], values[i1][j1]]


def _timing_blocks(cell_block: str) -> List[str]:
    out = []
    for m in re.finditer(r"\btiming\s*\([^)]*\)\s*\{", cell_block or ""):
        out.append(_match_brace_block(cell_block, m.start()))
    return out


def derive_liberty_path_tolerance(liberty_text: str, stages: List[dict],
                                  expected_ns: float) -> Optional[dict]:
    """Derive path tolerance from the exact NLDM grid cells STA sampled.

    Each stage contributes half the range of its four surrounding
    characterization samples.  Summing those interpolation resolutions gives
    a conservative path-level uncertainty without a tuned percentage, PDK
    constant, or design-specific exception.
    """
    if expected_ns <= 0 or not stages:
        return None
    hdr = parse_liberty_header(liberty_text)
    contributions = []
    total_uncertainty_ns = 0.0
    for stage in stages:
        cell_block = extract_cell_block(liberty_text, stage["cell"])
        if not cell_block:
            return None
        related = stage["toggle_pin"]
        timing = None
        for block in _timing_blocks(cell_block):
            rel = re.search(r'related_pin\s*:\s*"?([^";]+)', block)
            if rel and related in rel.group(1).split():
                timing = block
                break
        if timing is None:
            return None
        table_name = "cell_fall" if stage.get("transition") == "fall" \
            else "cell_rise"
        table = parse_nldm_table(timing, table_name)
        if not table:
            return None
        slew = stage.get("input_slew_ns")
        if slew is None:
            slew = table["index_1"][len(table["index_1"]) // 2]
        load_pf = stage.get("sta_load_pf")
        if load_pf is None:
            load_pf = stage.get("wire_cap_pf", 0.0)
        load_axis = load_pf / max(hdr["cap_unit_pf"], 1e-30)
        samples = _local_grid_values(table, float(slew), float(load_axis))
        uncertainty_ns = 0.5 * (max(samples) - min(samples)) \
            * hdr["time_unit_ns"]
        total_uncertainty_ns += uncertainty_ns
        contributions.append({
            "stage": stage["inst"],
            "cell": stage["cell"],
            "table": table_name,
            "input_slew_ns": round(float(slew), 9),
            "load_pf": round(float(load_pf), 9),
            "local_grid_half_range_ns": round(uncertainty_ns, 9),
        })
    return {
        "method": "sum_of_local_nldm_grid_half_ranges",
        "uncertainty_ns": round(total_uncertainty_ns, 9),
        "tolerance_pct": total_uncertainty_ns / expected_ns * 100.0,
        "contributions": contributions,
    }


def path_correlation_verdict(pct_error: float, tolerance_pct: float) -> str:
    """Classify with the derived tolerance; twice it is critical severity."""
    err = abs(pct_error)
    critical = 2.0 * tolerance_pct
    if err > critical and not math.isclose(err, critical, rel_tol=1e-12,
                                           abs_tol=1e-12):
        return "CRITICAL_MISMATCH"
    if err > tolerance_pct and not math.isclose(
            err, tolerance_pct, rel_tol=1e-12, abs_tol=1e-12):
        return "MISMATCH"
    return "CORRELATED"


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
        f"* {cell} SPICE↔liberty cell-delay correlation (commercial PDK {corner}, "
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
        cp = _pr.run(["docker", "exec", container, "bash", "-lc", cmd],
                            capture_output=True, text=True)
    except Exception as e:  # pragma: no cover - env dependent
        return False, f"docker/ngspice invocation failed: {e}"
    return cp.returncode == 0, cp.stdout


def _container_stdout(container: str, command: str,
                      timeout: int = 120) -> Optional[str]:
    try:
        cp = _pr.run(["docker", "exec", container, "bash", "-lc", command],
                     capture_output=True, text=True)
    except Exception:
        return None
    return cp.stdout if cp.returncode == 0 else None


def _read_container_text(container: str, path: str) -> Optional[str]:
    return _container_stdout(container, f"cat {shlex.quote(path)}", timeout=180)


def select_model_section(entries: List[Tuple[str, str]],
                         liberty_path: str) -> Optional[Tuple[str, str]]:
    """Choose the model section matching the active Liberty process token.

    The choice is semantic and data-driven: tokens such as ``tt`` in the
    Liberty filename prefer the corresponding central/typical model section.
    No PDK, foundry, library, or design name is encoded here.
    """
    if not entries:
        return None
    central = {"tt", "typ", "typical", "nom", "nominal"}
    process = central | {"ff", "ss", "fs", "sf", "fast", "slow"}
    lib_tokens = set(re.split(r"[^a-z]+", Path(liberty_path).stem.lower())) \
        & process
    wants_central = bool(lib_tokens & central)
    scored = []
    for path, section in entries:
        section_tokens = set(re.findall(r"[a-z]+", section.lower()))
        score = 0
        if lib_tokens & section_tokens:
            score += 20
        if wants_central and section_tokens & central:
            score += 10
        score -= len(path) / 10000.0
        scored.append((score, path, section))
    _score, path, section = max(scored)
    return path, section


def discover_installed_pdk_sources(container: str, liberty_path: str,
                                   required_cells: set) -> Optional[dict]:
    """Discover standard-cell SPICE + device model section beside Liberty."""
    marker = "/libs.ref/"
    if marker not in liberty_path:
        return None
    pdk_root = liberty_path.split(marker, 1)[0]
    cell_root = str(Path(liberty_path).parent.parent)
    find_cells = (
        f"find {shlex.quote(cell_root)} -type f "
        r"\( -name '*.spice' -o -name '*.sp' -o -name '*.cir' \) "
        "-path '*/spice/*' -print")
    cell_files = [line.strip() for line in
                  (_container_stdout(container, find_cells) or "").splitlines()
                  if line.strip().startswith("/")]
    best = None
    for path in sorted(cell_files):
        text = _read_container_text(container, path)
        if not text:
            continue
        names = set(re.findall(r"(?im)^\s*\.subckt\s+(\S+)", text))
        score = len(names & required_cells)
        if score and (best is None or score > best[0]):
            best = (score, path, text, names)
    if best is None:
        return None

    model_root = pdk_root + "/libs.tech/ngspice"
    scan = (
        f"find {shlex.quote(model_root)} -type f "
        r"\( -name '*.spice' -o -name '*.sp' -o -name '*.lib' \) "
        r"-exec grep -Him 24 -E '^[[:space:]]*[.]lib[[:space:]]+"
        r"[A-Za-z0-9_]+' {} + 2>/dev/null")
    raw = _container_stdout(container, scan, timeout=180) or ""
    entries: List[Tuple[str, str]] = []
    for line in raw.splitlines():
        m = re.match(r"^([^:]+):\s*\.lib\s+([A-Za-z0-9_]+)\s*$", line,
                     re.IGNORECASE)
        if m:
            entries.append((m.group(1), m.group(2)))
    model = select_model_section(entries, liberty_path)
    if model is None:
        return None
    prelude_scan = (
        f"for f in {shlex.quote(model_root)}/*.spice "
        f"{shlex.quote(model_root)}/*.sp; do "
        "test -f \"$f\" || continue; "
        "grep -qiE '^[[:space:]]*[.]param[[:space:]]+' \"$f\" || continue; "
        "grep -qiE '^[[:space:]]*[.]lib[[:space:]]+' \"$f\" && continue; "
        "printf '%s\\n' \"$f\"; done")
    preludes = sorted(line.strip() for line in
                      (_container_stdout(container, prelude_scan) or "").splitlines()
                      if line.strip().startswith("/"))
    return {
        "cell_spice": best[1],
        "cell_text": best[2],
        "subckt_names": best[3],
        "model_file": model[0],
        "model_section": model[1],
        "model_preludes": preludes,
    }


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
        "program": "spice_correlation_check.commercial_cell_driver",
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


# ══════════════════════════════════════════════════════════════════════════
#  Commercial-PDK REAL ngspice FULL-PATH correlation driver (Step-30, additive)
# ══════════════════════════════════════════════════════════════════════════
#
# Extends the single-cell driver to the FULL STA critical PATH: it parses the
# post-route STA report's critical-path cell sequence, STITCHES the design's
# LVS-extracted transistor subckts of those cells into one ngspice deck wired
# to match the real path connectivity (stage-i output net → stage-(i+1)
# toggling input pin, resolved from the gate-level netlist), loads every net
# with its REAL parasitic capacitance (SPEF *D_NET total + the downstream cell
# gate cap supplied physically by the stitched next stage), drives the path
# input at the plugin's nominal characterisation slew, runs REAL ngspice, and
# MEASURES the end-to-end propagation delay — then correlates it against the
# STA-reported path delay (same >10 % ERROR / >25 % CRITICAL thresholds).
#
# The stitch is physically faithful in a way a per-stage liberty sum is not:
# SPICE propagates each stage's OUTPUT slew into the next stage, so mid-path
# slews (which STA computes internally but never reports) fall out for free.
#
# §4.05 NO-LEAK: reads only design input (extracted netlist + SPEF + gate
# netlist + STA report) + the PDK bridge shim/liberty. Never any oracle /
# golden / output.*. NDA: PDK model/liberty content is read only to compute
# numbers; it is never copied into any emitted file.
#
# Honesty backstops (NEVER fabricate a number):
#   * no shim / no ngspice / no extracted subckts / no stitchable combinational
#     stage on the path  → return None (honest skip).
#   * the stitched deck's endpoint node fails to swing ≥ 50 % VDD (wrong
#     sensitisation for an unsupported gate family) → return None, no delay.

# Sequential / non-combinational cell-name families (endpoint or launch flop;
# never stitched as a combinational stage).
_SEQ_CELL_RE = re.compile(r"^(?:S?DF|DFF|DLA|DLH|DLL|LAT|SDFF|LSR)", re.IGNORECASE)
# Inverting combinational families (odd inversion → flips the arc polarity).
_INVERTING_RE = re.compile(r"^(?:INV|NAND|NOR|XNOR|AOI|OAI|IMUX|MXI|IND)",
                           re.IGNORECASE)


def _cell_family(cell: str) -> str:
    """Library-prefix-independent cell family token (pure)."""
    token = (cell or "").split("__")[-1]
    token = re.sub(r"(?:_[0-9]+|_[xX][0-9]+)$", "", token)
    family = re.compile(
        r"^(?:inv|buf|nand|nor|and|or|xor|xnor|aoi|oai|mux|mxi|imux|"
        r"s?dff|dfr|df|dla|dlh|dll|lat|lsr)", re.IGNORECASE)
    for part in re.split(r"_+", token):
        if family.match(part):
            return part
    return token


def normalize_mos_bulk(body: str, vss: str = "VSS", vdd: str = "VDD") -> str:
    """Rebind every MOSFET bulk (4th node) to the cell rails: nmos→VSS, pmos→
    VDD (pure). The LVS-extracted netlist ties each device bulk to its LOCAL
    source/internal node (an LVS artefact); left as-is the series pull-down /
    pull-up stacks of MULTI-transistor cells never fully switch in SPICE
    (a single inverter happens to already have bulk on the rails, which is why
    the cell driver worked without this). Keyed on the post-rename model token
    (nch_tn = nmos-derived, pch_tn = pmos-derived) or the raw nmos/pmos."""
    out = []
    line_re = re.compile(r"(\s*M\S+\s+\S+\s+\S+\s+\S+\s+)(\S+)(\s+)(\S+)(.*)")
    for ln in body.splitlines():
        m = line_re.match(ln)
        if m:
            pre, _bulk, sp, model, rest = m.groups()
            ml = model.lower()
            if ml in ("nch_tn", "nmos"):
                ln = pre + vss + sp + model + rest
            elif ml in ("pch_tn", "pmos"):
                ln = pre + vdd + sp + model + rest
        out.append(ln)
    return "\n".join(out)


def _subckt_rails(pins: List[str]) -> Tuple[str, str]:
    """(vss_pin, vdd_pin) names from a subckt pin list (pure)."""
    vss = vdd = None
    for p in pins:
        u = p.upper()
        if vss is None and u in ("VSS", "GND", "VGND", "VNW"):
            vss = p
        if vdd is None and u in ("VDD", "VCC", "VPWR"):
            vdd = p
    return vss or "VSS", vdd or "VDD"


def _subckt_device_lines(body: str) -> str:
    """Just the MOSFET instance lines of a normalised subckt body (pure)."""
    return "\n".join(l for l in body.splitlines()
                     if l.strip()[:1].upper() == "M")


def cell_inverts(cell: str) -> bool:
    """True if the cell inverts its combinational arc polarity (pure)."""
    return bool(_INVERTING_RE.match(_cell_family(cell)))


def is_sequential_cell(cell: str) -> bool:
    """True for flops/latches — never stitched as a combinational stage (pure)."""
    return bool(_SEQ_CELL_RE.match(_cell_family(cell)))


def tie_value_for_cell(cell: str) -> str:
    """Non-controlling tie node for a gate's NON-toggling inputs so the toggling
    input propagates (pure). AND/NAND → tie high (vdd); OR/NOR → tie low (0);
    XOR/XNOR → tie low (passes/inverts the other input). Complex families
    (AOI/OAI/MUX) default high; a wrong guess is caught by the swing backstop,
    never fabricated."""
    u = _cell_family(cell).upper()
    if u.startswith(("XOR", "XNOR", "NOR", "OR")):
        return "0"
    return "vdd"


# ─────────────────────────── STA path parsing (pure) ───────────────────────────

_STA_ROW_RE = re.compile(
    r"^\s*([\d.]+)\s+([\d.]+)\s+([v^])\s+(\S+)\s+\(([\w\[\]]+)\)\s*$",
    re.MULTILINE)
_STA_ROW_DETAIL_RE = re.compile(
    r"^\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+"
    r"([v^])\s+(\S+)\s+\(([\w\[\]]+)\)\s*$")


def parse_sta_path(text: str) -> Optional[dict]:
    """Parse an OpenSTA/OpenROAD report_checks max-delay path into a structured
    path (pure). Returns {startpoint, endpoint, start_time_ns, end_time_ns,
    path_delay_ns, endpoint_transition, rows:[{incr,time,tr,pin,inst,cell}]}.
    rows are the DATA rows that carry a `(CELL)`/`(in)`/`(out)` tag, in order."""
    starts = list(re.finditer(r"^Startpoint:\s+(\S+)", text, re.MULTILINE))
    if len(starts) > 1:
        text = text[:starts[1].start()]
        starts = starts[:1]
    sp = starts[0] if starts else None
    ep = re.search(r"^Endpoint:\s+(\S+)", text, re.MULTILINE)
    rows: List[dict] = []
    for line in (text or "").splitlines():
        detailed = _STA_ROW_DETAIL_RE.match(line)
        simple = _STA_ROW_RE.match(line) if detailed is None else None
        if detailed:
            cap, slew, incr, time_, tr, pin, cell = detailed.groups()
        elif simple:
            incr, time_, tr, pin, cell = simple.groups()
            cap = slew = None
        else:
            continue
        inst = pin.split("/")[0] if "/" in pin else pin
        rows.append({
            "incr": float(incr), "time": float(time_), "tr": tr,
            "pin": pin, "inst": inst, "cell": cell,
            "cap_pf": float(cap) if cap is not None else None,
            "slew_ns": float(slew) if slew is not None else None,
        })
    if not rows:
        return None
    start_tok = sp.group(1) if sp else rows[0]["inst"]
    end_tok = ep.group(1) if ep else rows[-1]["inst"]
    # data launch = first row that is a port `(in)` or the startpoint instance
    start_time = None
    for r in rows:
        if r["cell"].lower() == "in" or r["inst"] == start_tok:
            start_time = r["time"]
            break
    if start_time is None:
        start_time = rows[0]["time"]
    end_time = rows[-1]["time"]
    return {
        "startpoint": start_tok,
        "endpoint": end_tok,
        "start_time_ns": start_time,
        "end_time_ns": end_time,
        "path_delay_ns": round(end_time - start_time, 6),
        "endpoint_transition": "fall" if rows[-1]["tr"] == "v" else "rise",
        "rows": rows,
    }


def sta_path_stitch_score(text: str, subckt_names: set) -> int:
    """How many stitchable COMBINATIONAL stages a report's critical path yields
    (pure) — used to pick, among candidate STA reports, the one that exposes the
    richest combinational path (a bare flop→port path scores 0)."""
    p = parse_sta_path(text)
    if not p:
        return 0
    n = 0
    for r in p["rows"]:
        c = r["cell"]
        if c in subckt_names and not is_sequential_cell(c) \
                and c.lower() not in ("in", "out"):
            n += 1
    return n


# ─────────────────────── gate-netlist + SPEF parsing (pure) ──────────────────

_INST_RE = re.compile(
    r"(\w+)\s+(\S+)\s*\(\s*((?:\.\w+\s*\([^)]*\)\s*,?\s*)+)\)\s*;", re.DOTALL)
_CONN_RE = re.compile(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)")


def parse_verilog_instances(vtext: str) -> dict:
    """Map {instance_name: {pin: net}} from a structural gate-level netlist
    (pure). Only named-connection instances are captured; the top module port
    header (positional) is ignored."""
    inst_map: dict = {}
    for m in _INST_RE.finditer(vtext):
        cell, inst, blob = m.group(1), m.group(2), m.group(3)
        inst = inst.strip().lstrip("\\")
        conns = {p: n.strip().lstrip("\\")
                 for p, n in _CONN_RE.findall(blob)}
        if conns:
            inst_map[inst] = {"cell": cell, "conns": conns}
    return inst_map


def parse_spef_caps(spef_text: str) -> dict:
    """Map {net_name: total_cap_pf} from a SPEF (*NAME_MAP + *D_NET) (pure).
    Assumes *C_UNIT PF (the commercial-PDK extraction unit); callers needing another
    unit should scale. Returns {} when the SPEF has no D_NET records."""
    id2name = {}
    for m in re.finditer(r"^\*(\d+)\s+([A-Za-z_]\S*)\s*$", spef_text, re.MULTILINE):
        id2name[m.group(1)] = m.group(2)
    caps = {}
    for m in re.finditer(r"^\*D_NET\s+\*(\d+)\s+([\d.eE+\-]+)", spef_text,
                         re.MULTILINE):
        name = id2name.get(m.group(1))
        if name:
            try:
                caps[name] = float(m.group(2))
            except ValueError:
                pass
    return caps


def liberty_pin_cap(block: str, pin: str) -> Optional[float]:
    """Input-pin `capacitance` (in the liberty cap unit, typ pF) from a cell
    block (pure)."""
    m = re.search(r"pin\s*\(\s*" + re.escape(pin) + r"\s*\)\s*\{", block)
    if not m:
        return None
    pb = _match_brace_block(block, m.start())
    cm = re.search(r"\bcapacitance\s*:\s*([\d.]+)", pb)
    return float(cm.group(1)) if cm else None


def _find_pin_for_net(conns: dict, net: str) -> Optional[str]:
    """Which pin of an instance connects to `net` (pure)."""
    for pin, n in conns.items():
        if n == net:
            return pin
    return None


def resolve_path_stages(sta_path: dict, inst_map: dict, spef_caps: dict,
                        subckt_names: set, liberty_text: str,
                        max_stages: int = 12) -> Optional[dict]:
    """Resolve the STA path into an ordered list of stitchable combinational
    stages with the FAITHFUL toggling input pin, output net, and net parasitic
    load (pure). Returns {stages:[...], endpoint_load_pf, covered, total_comb}
    or None when nothing combinational is stitchable.

    Each stage: {inst, cell, toggle_pin, out_pin, out_net, wire_cap_pf}.
    The toggling pin of stage 0 is the first cell's pin on the startpoint net;
    of stage i>0 the pin on stage-(i-1)'s output net (real fanin chaining)."""
    comb_rows = [r for r in sta_path["rows"]
                 if r["cell"] in subckt_names
                 and not is_sequential_cell(r["cell"])
                 and r["cell"].lower() not in ("in", "out")]
    total_comb = len(comb_rows)
    if total_comb == 0:
        return None
    comb_rows = comb_rows[:max_stages]

    # startpoint net feeding the first stage's toggling input
    sp_tok = sta_path["startpoint"]
    if sp_tok in inst_map:  # DFF/cell launch → its first output net
        outs = [n for p, n in inst_map[sp_tok]["conns"].items()
                if p.upper() in ("Q", "QN", "Y", "Z")]
        prev_net = outs[0] if outs else None
    else:
        prev_net = sp_tok  # primary input port net (e.g. x[31])

    stages = []
    for r in comb_rows:
        inst = r["inst"]
        entry = inst_map.get(inst)
        if not entry:
            return None
        conns = entry["conns"]
        out_pin = r["pin"].split("/")[-1] if "/" in r["pin"] else "Y"
        out_net = conns.get(out_pin)
        if out_net is None:  # fall back to the sole output-looking pin
            outs = [p for p in conns if p.upper() in ("Y", "Z", "Q")]
            out_pin = outs[0] if outs else out_pin
            out_net = conns.get(out_pin)
        toggle_pin = _find_pin_for_net(conns, prev_net) if prev_net else None
        if toggle_pin is None:  # can't chain faithfully → representative pin
            ins = [p for p in conns
                   if p.upper() not in ("Y", "Z", "Q", "QN", "VDD", "VSS",
                                        "VPWR", "VGND", "VNW", "VPB", "VNB")]
            toggle_pin = ins[0] if ins else None
        if toggle_pin is None or out_net is None:
            return None
        row_index = sta_path["rows"].index(r)
        prior_slew = next(
            (pr.get("slew_ns") for pr in reversed(sta_path["rows"][:row_index])
             if pr.get("slew_ns") is not None), None)
        stages.append({
            "inst": inst, "cell": r["cell"], "toggle_pin": toggle_pin,
            "out_pin": out_pin, "out_net": out_net,
            "wire_cap_pf": spef_caps.get(out_net, 0.0),
            "sta_delay_ns": r["incr"],
            "input_slew_ns": prior_slew,
            "output_slew_ns": r.get("slew_ns"),
            "sta_load_pf": r.get("cap_pf"),
            "transition": "fall" if r["tr"] == "v" else "rise",
        })
        prev_net = out_net

    # endpoint receiver cap: the pin the last stage's out net drives (DFF D /
    # output-port external). Added lumped on the final node (its downstream
    # gate is NOT stitched). Pulled from the liberty pin cap when the endpoint
    # is a real cell instance.
    endpoint_load_pf = stages[-1]["wire_cap_pf"]
    ep_tok = sta_path["endpoint"]
    ep_entry = inst_map.get(ep_tok)
    if ep_entry:
        ep_pin = _find_pin_for_net(ep_entry["conns"], stages[-1]["out_net"])
        cblock = extract_cell_block(liberty_text, ep_entry["cell"]) \
            if ep_pin else None
        pc = liberty_pin_cap(cblock, ep_pin) if cblock else None
        if pc:
            endpoint_load_pf += pc
    return {
        "stages": stages,
        "endpoint_load_pf": endpoint_load_pf,
        "covered": len(stages),
        "total_comb": total_comb,
    }


# ───────────────────────── path deck build + meas (pure) ─────────────────────

def build_path_deck(shim_abs: str, corner: str, stages: List[dict],
                    subckts: dict, vdd: float, tr_ns: float, temp_c: float,
                    vth: float, endpoint_load_pf: float) -> str:
    """Assemble a self-contained ngspice deck stitching the resolved path
    stages (pure). Node convention: input `a`; stage i output `n{i}`, last
    output `pout`. Non-toggling inputs of each gate are tied to the family
    non-controlling rail; each output net carries its SPEF wire cap; the final
    node also carries the endpoint receiver cap. Measures both output arcs
    (rise/fall) end-to-end at the delay threshold; the input edge is chosen per
    the cumulative inversion parity so the requested output edge is reached."""
    n = len(stages)
    def out_node(i):
        return "pout" if i == n - 1 else f"n{i}"
    def in_node(i):
        return "a" if i == 0 else out_node(i - 1)

    body_lines, subckt_defs, cap_lines = [], [], []
    emitted = set()
    invert_parity = False
    for i, st in enumerate(stages):
        cell = st["cell"]
        pins, raw = subckts[cell]
        vss_p, vdd_p = _subckt_rails(pins)
        norm = normalize_mos_bulk(raw, vss_p, vdd_p)
        tie = tie_value_for_cell(cell)
        node_of = {}
        for p in pins:
            u = p.upper()
            if p == st["toggle_pin"]:
                node_of[p] = in_node(i)
            elif p == st["out_pin"]:
                node_of[p] = out_node(i)
            elif u in ("VSS", "GND", "VGND", "VNW"):
                node_of[p] = "0"
            elif u in ("VDD", "VCC", "VPWR"):
                node_of[p] = "vdd"
            else:
                node_of[p] = tie  # non-toggling input → non-controlling
        body_lines.append(
            f"x{i}_{st['inst'].strip('_') or i} "
            + " ".join(node_of[p] for p in pins) + f" {cell}")
        if cell not in emitted:
            subckt_defs.append(
                f".SUBCKT {cell} {' '.join(pins)}\n"
                f"{_subckt_device_lines(norm)}\n.ENDS")
            emitted.add(cell)
        wc = st["wire_cap_pf"]
        node = out_node(i)
        extra = wc + (endpoint_load_pf - wc if i == n - 1 else 0.0)
        if extra > 0:
            cap_lines.append(f"c{node} {node} 0 {extra*1e3:g}f")
        if cell_inverts(cell):
            invert_parity = not invert_parity

    td = 2.0
    pw = max(8.0, 24.0 * tr_ns)
    per = 2.0 * (td + tr_ns + pw)
    stop = per * 1.2
    step = max(0.001, tr_ns / 100.0)
    # output-fall arc: for even parity a falling INPUT yields a falling output;
    # for odd parity a rising input does. Same logic mirrored for output-rise.
    in_edge_for_fall = "RISE" if invert_parity else "FALL"
    in_edge_for_rise = "FALL" if invert_parity else "RISE"
    deck = [
        f"* spm critical-PATH stitch ({n} stages, commercial PDK {corner}, {temp_c:g}C)",
        f".lib '{shim_abs}' {corner}",
        f".temp {temp_c:g}",
        f"vdd vdd 0 {vdd:g}",
        f"vin a 0 pulse(0 {vdd:g} {td:g}n {tr_ns:g}n {tr_ns:g}n {pw:g}n {per:g}n)",
    ]
    deck += body_lines + cap_lines + subckt_defs
    deck += [
        f".tran {step:g}n {stop:g}n",
        f".meas tran tpd_fall TRIG v(a) VAL='{vth:g}' {in_edge_for_fall}=1 "
        f"TARG v(pout) VAL='{vth:g}' FALL=1",
        f".meas tran tpd_rise TRIG v(a) VAL='{vth:g}' {in_edge_for_rise}=1 "
        f"TARG v(pout) VAL='{vth:g}' RISE=1",
        f".meas tran vpout_max MAX v(pout)",
        f".meas tran vpout_min MIN v(pout)",
        ".end\n",
    ]
    return "\n".join(deck)


def _installed_pin_node(pin: str, stage: dict, input_node: str,
                        output_node: str) -> str:
    up = pin.upper()
    if pin == stage["toggle_pin"]:
        return input_node
    if pin == stage["out_pin"]:
        return output_node
    if up in ("VSS", "GND", "VGND", "VPW", "VNB", "VPB"):
        return "0"
    if up in ("VDD", "VCC", "VPWR", "VNW"):
        return "vdd"
    family = _cell_family(stage["cell"]).upper()
    toggle = stage["toggle_pin"].upper()
    if family.startswith(("MUX", "MXI", "IMUX")):
        is_select = bool(re.match(r"^(?:S|SEL|SELECT)[0-9]*$", up))
        if is_select:
            return "vdd" if re.search(r"(?:1|B)$", toggle) else "0"
        if re.match(r"^(?:S|SEL|SELECT)[0-9]*$", toggle):
            return "vdd" if re.search(r"(?:1|B)$", up) else "0"
    return tie_value_for_cell(stage["cell"])


def build_installed_path_deck(model_file: str, model_section: str,
                              model_preludes: List[str],
                              cell_spice: str, stages: List[dict],
                              subckts: dict, vdd: float, tr_ns: float,
                              temp_c: float, vth: float,
                              endpoint_load_pf: float) -> str:
    """Build a path deck referencing installed PDK sources, never copying them."""
    n = len(stages)
    def out_node(i):
        return "pout" if i == n - 1 else f"n{i}"
    def in_node(i):
        return "a" if i == 0 else out_node(i - 1)

    body, caps = [], []
    parity = False
    for i, stage in enumerate(stages):
        pins, _raw = subckts[stage["cell"]]
        nodes = [_installed_pin_node(p, stage, in_node(i), out_node(i))
                 for p in pins]
        body.append(f"xpath{i} {' '.join(nodes)} {stage['cell']}")
        wire = float(stage.get("wire_cap_pf") or 0.0)
        extra = wire + (endpoint_load_pf - wire if i == n - 1 else 0.0)
        if extra > 0:
            caps.append(f"cpath{i} {out_node(i)} 0 {extra * 1e3:g}f")
        if cell_inverts(stage["cell"]):
            parity = not parity

    td = 2.0
    pw = max(8.0, 24.0 * tr_ns)
    period = 2.0 * (td + tr_ns + pw)
    stop = period * 1.2
    step = max(0.001, tr_ns / 100.0)
    fall_trigger = "RISE" if parity else "FALL"
    rise_trigger = "FALL" if parity else "RISE"
    lines = [
        "* STA critical-path transistor-level correlation",
        *(f".include '{path}'" for path in model_preludes),
        f".lib '{model_file}' {model_section}",
        f".include '{cell_spice}'",
        f".temp {temp_c:g}",
        f"vdd vdd 0 {vdd:g}",
        f"vin a 0 pulse(0 {vdd:g} {td:g}n {tr_ns:g}n {tr_ns:g}n "
        f"{pw:g}n {period:g}n)",
        *body,
        *caps,
        f".tran {step:g}n {stop:g}n",
        f".meas tran tpd_fall TRIG v(a) VAL='{vth:g}' {fall_trigger}=1 "
        f"TARG v(pout) VAL='{vth:g}' FALL=1",
        f".meas tran tpd_rise TRIG v(a) VAL='{vth:g}' {rise_trigger}=1 "
        f"TARG v(pout) VAL='{vth:g}' RISE=1",
        ".meas tran vpout_max MAX v(pout)",
        ".meas tran vpout_min MIN v(pout)",
        ".end",
    ]
    return "\n".join(lines) + "\n"


_PATH_MEAS_RE = re.compile(
    r"^\s*(tpd_fall|tpd_rise|vpout_max|vpout_min)\s*=\s*"
    r"([\-+]?[0-9.]+(?:[eE][\-+]?\d+)?)", re.MULTILINE | re.IGNORECASE)


def parse_path_meas(stdout: str) -> dict:
    """Extract tpd_fall/tpd_rise (s) + vpout_max/min (V) from a transcript."""
    out = {}
    for m in _PATH_MEAS_RE.finditer(stdout or ""):
        try:
            out[m.group(1).lower()] = float(m.group(2))
        except ValueError:
            pass
    return out


def _pick_sta_report(project: Path, subckt_names: set) -> Optional[Path]:
    """Pick the STA report whose critical path exposes the most stitchable
    combinational stages (SPEF-based post-route report preferred; a bare
    flop→port estimate path scores 0)."""
    cands: List[Path] = []
    sta_dir = _pl.sta_dir(project)
    if sta_dir.is_dir():
        cands += sorted(sta_dir.glob("*.rpt"))
    pnr_rpt = project / "phase3" / "stage3" / "pnr" / "sta.rpt"
    if pnr_rpt.is_file():
        cands.append(pnr_rpt)
    best, best_score = None, 0
    for c in cands:
        try:
            score = sta_path_stitch_score(c.read_text(errors="replace"),
                                          subckt_names)
        except OSError:
            continue
        if score > best_score:
            best, best_score = c, score
    return best


def _find_gate_netlist(project: Path) -> Optional[Path]:
    """Locate the routed gate-level Verilog netlist."""
    pnr = project / "phase3" / "stage3" / "pnr"
    if pnr.is_dir():
        vs = sorted(pnr.glob("*_pnr.v")) or sorted(pnr.glob("*.v"))
        return vs[0] if vs else None
    return None


def run_commercial_pdk_path_correlation(
    project: Path,
    container: str = _DEFAULT_CONTAINER,
    corner: str = "ttt_lv",
    slew_ns: float = 0.4,
    max_stages: int = 12,
) -> Optional[dict]:
    """Run REAL ngspice on the STITCHED STA critical path and correlate the
    end-to-end SPICE path delay against the STA-reported path delay. Writes
    reports/phase3/spice_path_correlation.json. Returns the report dict, or
    None on an honest skip (missing shim/liberty/netlist/SPEF/ngspice, no
    stitchable stage, or a non-swinging deck).

    §4.05: only design-input + PDK read. NDA: PDK content never emitted."""
    shim = _find_bridge_shim(project)
    if not shim:
        return None
    liberty = _find_liberty_typ(project)
    cells_spice = _pl.extracted_dir(project) / "cells.spice"
    spef = next(iter(sorted(_pl.extracted_dir(project).glob("*.spef"))), None)
    netlist = _find_gate_netlist(project)
    hspice_dir = _find_hspice_dir(project)
    if not (liberty and cells_spice.is_file() and spef and netlist
            and hspice_dir):
        return None
    if _resolve_ngspice(container) is None:
        return None

    cells_text = cells_spice.read_text(errors="replace")
    subckt_names = set(re.findall(r"(?im)^\.SUBCKT\s+(\S+)", cells_text))
    sta_rpt = _pick_sta_report(project, subckt_names)
    if not sta_rpt:
        return None
    sta_path = parse_sta_path(sta_rpt.read_text(errors="replace"))
    if not sta_path or sta_path["path_delay_ns"] <= 0:
        return None

    inst_map = parse_verilog_instances(netlist.read_text(errors="replace"))
    spef_caps = parse_spef_caps(spef.read_text(errors="replace"))
    lib_text = liberty.read_text(errors="replace")
    resolved = resolve_path_stages(sta_path, inst_map, spef_caps,
                                   subckt_names, lib_text, max_stages)
    if not resolved:
        return None

    # extract + cache each stage's subckt (renamed nmos→nch_tn / pmos→pch_tn)
    subckts: dict = {}
    for st in resolved["stages"]:
        if st["cell"] not in subckts:
            sub = extract_subckt(cells_text, st["cell"])
            if not sub:
                return None
            subckts[st["cell"]] = sub

    hdr = parse_liberty_header(lib_text)
    vdd = hdr["nom_voltage"] or 1.8
    vth = vdd * (hdr["output_threshold_fall"] / 100.0)
    temp_c = hdr["nom_temperature"]
    tr_ns = pulse_tr_for_slew(slew_ns, hdr["slew_lower_fall"],
                              hdr["slew_upper_fall"], hdr["slew_derate"])

    deck = build_path_deck(str(shim.resolve()), corner, resolved["stages"],
                           subckts, vdd, tr_ns, temp_c, vth,
                           resolved["endpoint_load_pf"])
    out_dir = _pl.spice_dir(project)
    out_dir.mkdir(parents=True, exist_ok=True)
    deck_path = out_dir / "corr_path_critical.spice"
    deck_path.write_text(deck)
    ok, txt = _run_ngspice_in(container, str(hspice_dir.resolve()),
                              str(deck_path.resolve()))
    (out_dir / "corr_path_critical.log").write_text(txt)
    meas = parse_path_meas(txt)

    # honesty backstop: the endpoint node must actually swing ≥ 50 % VDD, else
    # the sensitisation was wrong for this gate family — skip, never fabricate.
    swing = meas.get("vpout_max", 0.0) - meas.get("vpout_min", 0.0)
    if swing < 0.5 * vdd:
        return None

    sta_delay_ns = sta_path["path_delay_ns"]
    direction = sta_path["endpoint_transition"]  # STA-reported endpoint edge
    primary_key = "tpd_fall" if direction == "fall" else "tpd_rise"
    spice_s = meas.get(primary_key)
    if spice_s is None or spice_s <= 0:
        return None
    pct = correlation_pct(spice_s, sta_delay_ns)
    verdict = ("CRITICAL_MISMATCH" if abs(pct) > 25 else
               "MISMATCH" if abs(pct) > 10 else "CORRELATED")

    arcs = []
    for key, arc in (("tpd_fall", "fall"), ("tpd_rise", "rise")):
        v = meas.get(key)
        if v is not None and v > 0:
            arcs.append({"arc": arc, "spice_delay_ns": round(v * 1e9, 6),
                         "is_sta_direction": arc == direction})

    report = {
        "program": "spice_correlation_check.commercial_path_driver",
        "version": "1.2.0",
        "provenance": "real_ngspice",
        "simulator": "ngspice (vibeic-eda container)",
        "reference": f"sta_report ({sta_rpt.name})",
        "pdk_bridge": f"{shim.name} :: {corner}",
        "corner": f"{corner} / {vdd:g}V / {temp_c:g}C",
        "netlist_source": "phase3/stage3/extracted/cells.spice "
                          "(LVS-extracted; nmos→nch_tn / pmos→pch_tn; "
                          "bulk normalised to rails)",
        "path": {
            "startpoint": sta_path["startpoint"],
            "endpoint": sta_path["endpoint"],
            "sta_endpoint_transition": direction,
            "stages": [
                {"stage": i, "inst": s["inst"], "cell": s["cell"],
                 "toggle_pin": s["toggle_pin"], "out_pin": s["out_pin"],
                 "out_net": s["out_net"],
                 "net_wire_cap_ff": round(s["wire_cap_pf"] * 1e3, 4)}
                for i, s in enumerate(resolved["stages"])
            ],
            "endpoint_load_ff": round(resolved["endpoint_load_pf"] * 1e3, 4),
        },
        "operating_point": {
            "input_slew_ns": slew_ns,
            "input_pulse_tr_ns": round(tr_ns, 6),
            "delay_threshold_v": round(vth, 4),
            "note": ("path input driven at the plugin nominal characterisation "
                     "slew; mid-path slews propagate physically through the "
                     "stitched stages (not assumed)."),
        },
        "correlation": {
            "spice_path_delay_ns": round(spice_s * 1e9, 6),
            "sta_path_delay_ns": round(sta_delay_ns, 6),
            "pct_error": round(pct, 3),
            "stages_correlated": resolved["covered"],
            "stages_total_combinational": resolved["total_comb"],
            "tolerance_pct": 10.0,
            "verdict": verdict,
        },
        "arcs": arcs,
        "logs": ["corr_path_critical.log"],
        "design_identity": {"design": project.name},
        "nda_note": "PDK model/liberty content read at runtime only; not emitted.",
    }
    # Sibling of the single-cell spice_correlation.json under reports/phase3/
    # (kept next to it explicitly, so both Step-30 correlation artifacts live
    # in the phase-3 report folder rather than the audit fallback bucket).
    out_path = _path_correlation_json_path(project)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def _path_correlation_json_path(project: Path) -> Path:
    """Canonical location of the full-path correlation report (reports/phase3/,
    beside the single-cell spice_correlation.json)."""
    return _pl.reports_dir(project) / "phase3" / "spice_path_correlation.json"


def _check_path_correlation_json(project: Path) -> Optional[dict]:
    """Load spice_path_correlation.json if already produced."""
    return _load_json(_path_correlation_json_path(project))


def run_installed_pdk_path_correlation(
    project: Path,
    liberty_path: str,
    container: str = _DEFAULT_CONTAINER,
    max_stages: int = 12,
) -> dict:
    """Run the BLOCKING Step 30 check from the active installed PDK.

    The active Liberty path is supplied by the Phase-3 PDK configuration.  Its
    sibling cell SPICE and device-model section are discovered at runtime.
    Only a genuinely absent ngspice executable returns ``NO_TOOL``; every
    missing input, parse failure, non-swinging deck, or simulator failure is an
    ``ERROR`` and cannot be promoted to a capability-gap skip.
    """
    project = Path(project)
    if _resolve_ngspice(container) is None:
        return {"status": "NO_TOOL", "reason": "ngspice executable absent"}
    liberty_text = _read_container_text(container, liberty_path)
    if not liberty_text:
        return {"status": "ERROR", "reason": "active Liberty unreadable"}
    netlist = _find_gate_netlist(project)
    spef = next(iter(sorted(_pl.extracted_dir(project).glob("*.spef"))), None)
    if not netlist or not spef:
        return {"status": "ERROR", "reason": "routed netlist or SPEF absent"}

    netlist_text = netlist.read_text(errors="replace")
    inst_map = parse_verilog_instances(netlist_text)
    required_cells = {entry["cell"] for entry in inst_map.values()}
    sources = discover_installed_pdk_sources(
        container, liberty_path, required_cells)
    if not sources:
        return {"status": "ERROR",
                "reason": "installed cell SPICE or model section unresolved"}

    sta_report = _pick_sta_report(project, sources["subckt_names"])
    if not sta_report:
        return {"status": "ERROR", "reason": "critical STA path unresolved"}
    sta_path = parse_sta_path(sta_report.read_text(errors="replace"))
    if not sta_path:
        return {"status": "ERROR", "reason": "critical STA path unparseable"}
    resolved = resolve_path_stages(
        sta_path, inst_map, parse_spef_caps(spef.read_text(errors="replace")),
        sources["subckt_names"], liberty_text, max_stages)
    if not resolved:
        return {"status": "ERROR", "reason": "critical path not stitchable"}

    expected_ns = sum(float(stage.get("sta_delay_ns") or 0.0)
                      for stage in resolved["stages"])
    tolerance = derive_liberty_path_tolerance(
        liberty_text, resolved["stages"], expected_ns)
    if not tolerance:
        return {"status": "ERROR",
                "reason": "Liberty grid tolerance could not be derived"}

    subckts = {}
    for stage in resolved["stages"]:
        cell = stage["cell"]
        if cell not in subckts:
            subckt = extract_subckt(sources["cell_text"], cell, model_map={})
            if not subckt:
                return {"status": "ERROR",
                        "reason": f"cell SPICE subckt absent: {cell}"}
            subckts[cell] = subckt

    hdr = parse_liberty_header(liberty_text)
    vdd = hdr["nom_voltage"] or 1.0
    temp_c = hdr["nom_temperature"]
    vth = vdd * hdr["output_threshold_fall"] / 100.0
    input_slew_ns = resolved["stages"][0].get("input_slew_ns")
    if input_slew_ns is None:
        input_slew_ns = tolerance["contributions"][0]["input_slew_ns"]
    tr_ns = pulse_tr_for_slew(
        float(input_slew_ns), hdr["slew_lower_fall"],
        hdr["slew_upper_fall"], hdr["slew_derate"])
    deck = build_installed_path_deck(
        sources["model_file"], sources["model_section"],
        sources["model_preludes"],
        sources["cell_spice"], resolved["stages"], subckts, vdd, tr_ns,
        temp_c, vth, resolved["endpoint_load_pf"])
    out_dir = _pl.spice_dir(project)
    out_dir.mkdir(parents=True, exist_ok=True)
    deck_path = out_dir / "correlation.spice"
    log_path = out_dir / "correlation.log"
    deck_path.write_text(deck)
    ok, transcript = _run_ngspice_in(
        container, str(Path(sources["model_file"]).parent), str(deck_path))
    log_path.write_text(transcript or "")
    if not ok:
        return {"status": "ERROR", "reason": "ngspice execution failed",
                "deck": str(deck_path), "log": str(log_path)}
    measured = parse_path_meas(transcript)
    swing = measured.get("vpout_max", 0.0) - measured.get("vpout_min", 0.0)
    if swing < 0.5 * vdd:
        return {"status": "ERROR", "reason": "critical path did not swing",
                "deck": str(deck_path), "log": str(log_path)}
    direction = sta_path["endpoint_transition"]
    key = "tpd_fall" if direction == "fall" else "tpd_rise"
    spice_s = measured.get(key)
    if spice_s is None or spice_s <= 0 or expected_ns <= 0:
        return {"status": "ERROR", "reason": "path delay measurement absent",
                "deck": str(deck_path), "log": str(log_path)}
    spice_ns = spice_s * 1e9
    pct_error = (spice_ns - expected_ns) / expected_ns * 100.0
    tolerance_pct = float(tolerance["tolerance_pct"])
    verdict = path_correlation_verdict(pct_error, tolerance_pct)
    report = {
        "program": "spice_correlation_check.installed_pdk_path_driver",
        "version": "2.0.0",
        "provenance": "real_ngspice_transistor_path",
        "reference": {
            "sta_report": sta_report.name,
            "startpoint": sta_path["startpoint"],
            "endpoint": sta_path["endpoint"],
            "endpoint_transition": direction,
            "sta_total_path_delay_ns": sta_path["path_delay_ns"],
            "liberty_spef_cone_delay_ns": round(expected_ns, 9),
        },
        "correlation": {
            "spice_path_delay_ns": round(spice_ns, 9),
            "liberty_spef_cone_delay_ns": round(expected_ns, 9),
            "pct_error": round(pct_error, 6),
            "tolerance_pct": round(tolerance_pct, 6),
            "critical_tolerance_pct": round(2.0 * tolerance_pct, 6),
            "tolerance_derivation": tolerance,
            "stages_correlated": resolved["covered"],
            "stages_total_combinational": resolved["total_comb"],
            "verdict": verdict,
        },
        "artifacts": {"deck": str(deck_path), "log": str(log_path)},
        "model_provenance": "active installed PDK selected from Liberty path",
        "nda_note": "Model and Liberty content were read at runtime, not emitted.",
    }
    report_path = _pl.reports_dir(project) / "phase3" / "spice_correlation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return {"status": "RAN", "report": report,
            "report_path": str(report_path), "deck": str(deck_path),
            "log": str(log_path)}


# ══════════════════════════════════════════════════════════════════════════
#  TOP-N critical-path correlation (additive over the single-path driver)
#
#  The single-path driver above stitches ONLY the #1 STA critical path. This
#  extends the same PROVEN per-path stitch to the top-N max-delay paths so the
#  correlation covers the timing-critical CONE, not one path. Each path is:
#    (1) taken from OpenSTA `report_checks -path_delay max -group_count N
#        -endpoint_count 1` (worst path per distinct endpoint), not the #1 only;
#    (2) stitched stage-by-stage (extracted subckts, nmos→nch_tn / pmos→pch_tn,
#        bulk-normalised, real SPEF net cap, endpoint receiver cap);
#    (3) driven at the nominal characterisation slew through REAL ngspice;
#    (4) correlated vs its own STA path delay (same >10 % ERROR / >25 % CRITICAL
#        thresholds).
#  Honesty is per-path: a path that cannot be sensitised (mixed AND/OR/XOR whose
#  static non-controlling tie is wrong for a stage → the endpoint fails to swing)
#  or has no stitchable combinational stage becomes an explicit per-path SKIP
#  with a reason — NEVER a fabricated number. The aggregate discloses N found,
#  N correlated, N skipped (+ why), worst |%err| and mean |%err|.
#  §4.05 NO-LEAK: reads only design input (extracted netlist + SPEF + gate
#  netlist + SDC) + the PDK bridge shim/liberty. OpenSTA reads the same design
#  inputs. Never any oracle / golden / output.*.
# ══════════════════════════════════════════════════════════════════════════

def split_sta_path_blocks(text: str) -> List[str]:
    """Split a multi-path `report_checks` transcript into per-path text blocks,
    one per `Startpoint:` header (pure). Each block is safe to feed to
    parse_sta_path (whose row regex ignores the required-time section)."""
    idxs = [mm.start() for mm in re.finditer(r"(?m)^Startpoint:", text or "")]
    if not idxs:
        return []
    idxs.append(len(text))
    return [text[idxs[i]:idxs[i + 1]] for i in range(len(idxs) - 1)]


def parse_sta_paths_multi(text: str, max_paths: int = 5,
                          dedup: bool = True) -> List[dict]:
    """Parse the top-N max-delay paths from a multi-path `report_checks`
    transcript (pure). OpenSTA emits paths worst-first; we dedup by
    (startpoint, endpoint) keeping the worst-first occurrence and return up to
    max_paths parsed path dicts (each in parse_sta_path's shape)."""
    out: List[dict] = []
    seen = set()
    for block in split_sta_path_blocks(text):
        p = parse_sta_path(block)
        if not p or p["path_delay_ns"] <= 0:
            continue
        key = (p["startpoint"], p["endpoint"])
        if dedup and key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) >= max_paths:
            break
    return out


def build_topN_sta_tcl(liberty: str, netlist: str, top: str,
                       sdc: Optional[str], spef: Optional[str],
                       n: int) -> str:
    """Assemble an OpenSTA script that reports the top-N max-delay paths, one
    per distinct endpoint (pure). `-endpoint_count 1` yields the worst path per
    endpoint so the N paths span distinct capture points, not N slices of one
    endpoint. (OpenSTA 3.1 accepts the -group_count/-endpoint_count spelling
    with a deprecation warning; the parser dedups defensively regardless.)"""
    lines = [
        f"read_liberty {liberty}",
        f"read_verilog {netlist}",
        f"link_design {top}",
    ]
    if sdc:
        lines.append(f"read_sdc {sdc}")
    if spef:
        lines.append(f"read_spef {spef}")
    lines.append(f"report_checks -path_delay max -group_count {int(n)} "
                 f"-endpoint_count 1 -format full")
    lines.append("exit")
    return "\n".join(lines) + "\n"


def aggregate_path_correlations(per_path: List[dict]) -> dict:
    """Pure aggregate over per-path correlation results. Correlated = a path
    that produced a real SPICE number; skipped = an honest per-path SKIP with a
    reason. Returns counts, skip-reason histogram, worst/mean |%err|, and the
    worst per-path verdict (CORRELATED < MISMATCH < CRITICAL_MISMATCH), or
    NO_PATH_CORRELATED when nothing could be sensitised."""
    corr = [p for p in per_path
            if p.get("pct_error") is not None
            and p.get("verdict") in ("CORRELATED", "MISMATCH",
                                     "CRITICAL_MISMATCH")]
    skipped = [p for p in per_path if p.get("verdict") == "SKIP"]
    skip_reasons: dict = {}
    for p in skipped:
        r = p.get("skip_reason", "unknown")
        skip_reasons[r] = skip_reasons.get(r, 0) + 1
    if corr:
        abserrs = [abs(p["pct_error"]) for p in corr]
        worst = max(abserrs)
        mean_abs = sum(abserrs) / len(abserrs)
        if any(p["verdict"] == "CRITICAL_MISMATCH" for p in corr):
            verdict = "CRITICAL_MISMATCH"
        elif any(p["verdict"] == "MISMATCH" for p in corr):
            verdict = "MISMATCH"
        else:
            verdict = "CORRELATED"
    else:
        worst = mean_abs = None
        verdict = "NO_PATH_CORRELATED"
    return {
        "n_paths": len(per_path),
        "n_correlated": len(corr),
        "n_skipped": len(skipped),
        "skip_reasons": skip_reasons,
        "worst_abs_pct_error": round(worst, 3) if worst is not None else None,
        "mean_abs_pct_error": round(mean_abs, 3) if mean_abs is not None
        else None,
        "tolerance_pct": 10.0,
        "verdict": verdict,
    }


def _top_module_name(vtext: str) -> Optional[str]:
    """Top module name from a structural gate netlist (pure)."""
    m = re.search(r"(?m)^\s*module\s+(\w+)", vtext or "")
    return m.group(1) if m else None


def _find_sdc(project: Path) -> Optional[Path]:
    """Locate the routed design's timing constraints (for OpenSTA)."""
    p = project / "phase3" / "stage3" / "pnr" / "constraint.sdc"
    if p.is_file():
        return p
    pnr = project / "phase3" / "stage3" / "pnr"
    if pnr.is_dir():
        c = sorted(pnr.glob("*.sdc"))
        if c:
            return c[0]
    hits = sorted(project.rglob("constraint.sdc"))
    return hits[0] if hits else None


def _resolve_opensta(container: str) -> Optional[str]:
    """Absolute OpenSTA (`sta`) path inside the container, or None."""
    for probe in ("command -v sta",
                  "ls /foss/tools/bin/sta 2>/dev/null | head -1",
                  "ls /foss/tools/*/bin/sta 2>/dev/null | head -1"):
        try:
            r = subprocess.run(["docker", "exec", container, "bash", "-lc",
                                probe], capture_output=True, text=True,
                               timeout=60)
        except Exception:
            return None
        for raw in (r.stdout or "").splitlines():
            line = raw.strip()
            if line.startswith("/") and line.endswith("/sta"):
                return line
    return None


def _run_opensta_in(container: str, cwd_dir: str, tcl_path: str,
                    timeout: int = 240) -> Tuple[bool, str]:
    """Run `sta -no_init -exit <tcl>` in the container. Returns (ok, stdout)."""
    sta = _resolve_opensta(container) or "sta"
    cmd = (f"export PATH=/foss/tools/bin:$PATH; cd {shlex.quote(cwd_dir)} && "
           f"{shlex.quote(sta)} -no_init -exit {shlex.quote(tcl_path)} 2>&1")
    try:
        cp = _pr.run(["docker", "exec", container, "bash", "-lc", cmd],
                            capture_output=True, text=True)
    except Exception as e:  # pragma: no cover - env dependent
        return False, f"docker/opensta invocation failed: {e}"
    return cp.returncode == 0, cp.stdout


def _stitch_sim_correlate_path(
    sta_path: dict, inst_map: dict, spef_caps: dict, subckt_names: set,
    cells_text: str, lib_text: str, hdr: dict, shim: Path, container: str,
    corner: str, slew_ns: float, max_stages: int, hspice_dir: Path,
    out_dir: Path, tag: str,
) -> dict:
    """Stitch ONE STA path, run REAL ngspice, correlate the end-to-end SPICE
    path delay vs its STA delay. Returns a per-path result dict. On any honesty
    backstop → a SKIP dict with a reason (NEVER a fabricated number). This is
    the SAME per-path recipe the single-path driver proved (0.391 vs 0.43 ns,
    -9.0 % CORRELATED on spm) — factored so the top-N loop reuses it verbatim."""
    base = {
        "startpoint": sta_path["startpoint"],
        "endpoint": sta_path["endpoint"],
        "sta_path_delay_ns": round(sta_path["path_delay_ns"], 6),
        "sta_endpoint_transition": sta_path["endpoint_transition"],
    }
    if sta_path["path_delay_ns"] <= 0:
        return {**base, "verdict": "SKIP",
                "skip_reason": "non_positive_sta_delay"}
    resolved = resolve_path_stages(sta_path, inst_map, spef_caps,
                                   subckt_names, lib_text, max_stages)
    if not resolved:
        return {**base, "verdict": "SKIP",
                "skip_reason": "no_stitchable_combinational_stage"}
    subckts: dict = {}
    for st in resolved["stages"]:
        if st["cell"] not in subckts:
            sub = extract_subckt(cells_text, st["cell"])
            if not sub:
                return {**base, "verdict": "SKIP",
                        "skip_reason": f"subckt_extract_failed:{st['cell']}",
                        "stages_total_combinational": resolved["total_comb"]}
            subckts[st["cell"]] = sub

    vdd = hdr["nom_voltage"] or 1.8
    vth = vdd * (hdr["output_threshold_fall"] / 100.0)
    temp_c = hdr["nom_temperature"]
    tr_ns = pulse_tr_for_slew(slew_ns, hdr["slew_lower_fall"],
                              hdr["slew_upper_fall"], hdr["slew_derate"])
    stage_view = [
        {"stage": i, "inst": s["inst"], "cell": s["cell"],
         "toggle_pin": s["toggle_pin"], "out_pin": s["out_pin"],
         "out_net": s["out_net"],
         "net_wire_cap_ff": round(s["wire_cap_pf"] * 1e3, 4)}
        for i, s in enumerate(resolved["stages"])
    ]
    deck = build_path_deck(str(shim.resolve()), corner, resolved["stages"],
                           subckts, vdd, tr_ns, temp_c, vth,
                           resolved["endpoint_load_pf"])
    deck_path = out_dir / f"corr_path_{tag}.spice"
    deck_path.write_text(deck)
    ok, txt = _run_ngspice_in(container, str(hspice_dir.resolve()),
                              str(deck_path.resolve()))
    (out_dir / f"corr_path_{tag}.log").write_text(txt)
    meas = parse_path_meas(txt)

    common = {
        "stages_correlated": resolved["covered"],
        "stages_total_combinational": resolved["total_comb"],
        "endpoint_load_ff": round(resolved["endpoint_load_pf"] * 1e3, 4),
        "stages": stage_view,
        "log": f"corr_path_{tag}.log",
    }
    # honesty backstop: the endpoint node must actually swing ≥ 50 % VDD, else
    # the static sensitisation was wrong for this gate family (mixed AND/OR/XOR)
    # → explicit SKIP, never a fabricated number.
    swing = meas.get("vpout_max", 0.0) - meas.get("vpout_min", 0.0)
    if swing < 0.5 * vdd:
        return {**base, **common, "verdict": "SKIP",
                "skip_reason": "endpoint_did_not_swing",
                "endpoint_swing_v": round(swing, 4)}
    direction = sta_path["endpoint_transition"]
    primary_key = "tpd_fall" if direction == "fall" else "tpd_rise"
    spice_s = meas.get(primary_key)
    if spice_s is None or spice_s <= 0:
        return {**base, **common, "verdict": "SKIP",
                "skip_reason": "no_measured_endpoint_edge"}
    pct = correlation_pct(spice_s, sta_path["path_delay_ns"])
    verdict = ("CRITICAL_MISMATCH" if abs(pct) > 25 else
               "MISMATCH" if abs(pct) > 10 else "CORRELATED")
    arcs = []
    for key, arc in (("tpd_fall", "fall"), ("tpd_rise", "rise")):
        v = meas.get(key)
        if v is not None and v > 0:
            arcs.append({"arc": arc, "spice_delay_ns": round(v * 1e9, 6),
                         "is_sta_direction": arc == direction})
    return {**base, **common, "verdict": verdict,
            "spice_path_delay_ns": round(spice_s * 1e9, 6),
            "pct_error": round(pct, 3),
            "arcs": arcs}


def _topN_path_correlation_json_path(project: Path) -> Path:
    """Canonical location of the top-N path-correlation report (reports/phase3/,
    beside spice_path_correlation.json)."""
    return _pl.reports_dir(project) / "phase3" / \
        "spice_topN_path_correlation.json"


def _check_topN_path_correlation_json(project: Path) -> Optional[dict]:
    """Load spice_topN_path_correlation.json if already produced."""
    return _load_json(_topN_path_correlation_json_path(project))


def run_commercial_pdk_topN_path_correlation(
    project: Path,
    container: str = _DEFAULT_CONTAINER,
    corner: str = "ttt_lv",
    slew_ns: float = 0.4,
    max_stages: int = 12,
    top_n: int = 5,
) -> Optional[dict]:
    """Run REAL ngspice on the TOP-N STA max-delay paths and correlate each
    stitched end-to-end SPICE path delay against its STA path delay. Writes
    reports/phase3/spice_topN_path_correlation.json with per-path
    (endpoint, STA delay, SPICE delay, %err, verdict) + an aggregate (worst |
    mean |%err|, N correlated, N skipped + why). Returns the report dict, or
    None on an honest skip (missing shim/liberty/netlist/SPEF/ngspice, or no
    path could even be read). Additive: leaves the single-cell + single-path
    reports untouched.

    §4.05: only design-input + PDK read. NDA: PDK content never emitted."""
    shim = _find_bridge_shim(project)
    if not shim:
        return None
    liberty = _find_liberty_typ(project)
    cells_spice = _pl.extracted_dir(project) / "cells.spice"
    spef = next(iter(sorted(_pl.extracted_dir(project).glob("*.spef"))), None)
    netlist = _find_gate_netlist(project)
    hspice_dir = _find_hspice_dir(project)
    if not (liberty and cells_spice.is_file() and spef and netlist
            and hspice_dir):
        return None
    if _resolve_ngspice(container) is None:
        return None

    cells_text = cells_spice.read_text(errors="replace")
    subckt_names = set(re.findall(r"(?im)^\.SUBCKT\s+(\S+)", cells_text))
    lib_text = liberty.read_text(errors="replace")
    hdr = parse_liberty_header(lib_text)
    netlist_text = netlist.read_text(errors="replace")
    inst_map = parse_verilog_instances(netlist_text)
    spef_caps = parse_spef_caps(spef.read_text(errors="replace"))

    out_dir = _pl.spice_dir(project)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── primary source: run OpenSTA for the top-N max-delay paths ──
    sta_paths: List[dict] = []
    sta_source = None
    top = _top_module_name(netlist_text) or project.name
    sdc = _find_sdc(project)
    if _resolve_opensta(container) is not None:
        tcl = build_topN_sta_tcl(
            str(liberty.resolve()), str(netlist.resolve()), top,
            str(sdc.resolve()) if sdc else None,
            str(spef.resolve()), top_n)
        tcl_path = out_dir / "topN_report_checks.tcl"
        tcl_path.write_text(tcl)
        ok, sta_stdout = _run_opensta_in(container, str(out_dir.resolve()),
                                         str(tcl_path.resolve()))
        (out_dir / "topN_report_checks.log").write_text(sta_stdout or "")
        sta_paths = parse_sta_paths_multi(sta_stdout or "", max_paths=top_n)
        if sta_paths:
            sta_source = (f"opensta report_checks -path_delay max "
                          f"-group_count {top_n} -endpoint_count 1")
    # ── fallback: single best pre-existing report (opensta absent) ──
    if not sta_paths:
        rpt = _pick_sta_report(project, subckt_names)
        if rpt:
            p = parse_sta_path(rpt.read_text(errors="replace"))
            if p and p["path_delay_ns"] > 0:
                sta_paths = [p]
                sta_source = (f"sta_report ({rpt.name}) "
                              f"[opensta unavailable; single path]")
    if not sta_paths:
        return None

    per_path: List[dict] = []
    for i, sp in enumerate(sta_paths):
        res = _stitch_sim_correlate_path(
            sp, inst_map, spef_caps, subckt_names, cells_text, lib_text, hdr,
            shim, container, corner, slew_ns, max_stages, hspice_dir, out_dir,
            tag=f"top{i}")
        res["rank"] = i
        per_path.append(res)

    agg = aggregate_path_correlations(per_path)
    vdd = hdr["nom_voltage"] or 1.8
    temp_c = hdr["nom_temperature"]
    vth = vdd * (hdr["output_threshold_fall"] / 100.0)
    tr_ns = pulse_tr_for_slew(slew_ns, hdr["slew_lower_fall"],
                              hdr["slew_upper_fall"], hdr["slew_derate"])
    report = {
        "program": "spice_correlation_check.commercial_topN_path_driver",
        "version": "1.0.0",
        "provenance": "real_ngspice",
        "simulator": "ngspice (vibeic-eda container)",
        "sta_source": sta_source,
        "requested_top_n": top_n,
        "pdk_bridge": f"{shim.name} :: {corner}",
        "corner": f"{corner} / {vdd:g}V / {temp_c:g}C",
        "netlist_source": "phase3/stage3/extracted/cells.spice "
                          "(LVS-extracted; nmos→nch_tn / pmos→pch_tn; "
                          "bulk normalised to rails)",
        "operating_point": {
            "input_slew_ns": slew_ns,
            "input_pulse_tr_ns": round(tr_ns, 6),
            "delay_threshold_v": round(vth, 4),
            "note": ("each path's input driven at the plugin nominal "
                     "characterisation slew; mid-path slews propagate "
                     "physically through the stitched stages (not assumed)."),
        },
        "paths": per_path,
        "aggregate": agg,
        "design_identity": {"design": project.name},
        "nda_note": "PDK model/liberty content read at runtime only; "
                    "not emitted.",
    }
    out_path = _topN_path_correlation_json_path(project)
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
    # When the design ships a commercial-PDK ngspice bridge shim and no correlation
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
                message=f"commercial-PDK ngspice correlation driver could not run: {e}",
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

    # ── Step-30 (additive): REAL ngspice FULL critical-PATH correlation ──
    # Stitch the STA critical-path cells' extracted transistor subckts into one
    # ngspice deck and correlate the end-to-end SPICE path delay against the
    # STA-reported path delay. Honest skip (no numbers) when inputs/simulator
    # are unavailable or the stitched deck fails to swing.
    path_report = None
    if run_spice and _check_path_correlation_json(project) is None \
            and _find_bridge_shim(project) is not None:
        try:
            path_report = run_commercial_pdk_path_correlation(
                project, container=container)
        except Exception as e:  # never let the driver crash the gate
            result.findings.append(Finding(
                rule="SPICE_PATH_DRIVER_ERROR",
                severity="INFO",
                message=f"commercial-PDK ngspice path-correlation driver could not run: {e}",
            ))
    else:
        path_report = _check_path_correlation_json(project)
    if path_report is not None:
        pc = path_report.get("correlation", {})
        sev = "ERROR" if pc.get("verdict") in (
            "MISMATCH", "CRITICAL_MISMATCH") else "INFO"
        result.findings.append(Finding(
            rule=("SPICE_PATH_" + ("MISMATCH" if sev == "ERROR"
                                   else "CORRELATED")),
            severity=sev,
            message=(
                f"Real ngspice path correlation "
                f"({pc.get('stages_correlated')}/"
                f"{pc.get('stages_total_combinational')} combinational stages): "
                f"SPICE={pc.get('spice_path_delay_ns')}ns vs "
                f"STA={pc.get('sta_path_delay_ns')}ns "
                f"({pc.get('pct_error')}%) → {pc.get('verdict')}"),
        ))

    # ── Step-30 (additive): REAL ngspice TOP-N critical-PATH correlation ──
    # Extend the proven per-path stitch from the #1 path to the top-N max-delay
    # paths (OpenSTA report_checks -group_count N -endpoint_count 1) so the
    # correlation spans the timing-critical CONE. Per-path honest SKIP (with a
    # reason) for any path that can't be sensitised; the aggregate discloses N
    # found / correlated / skipped. Honest skip of the whole gate when inputs /
    # simulator are unavailable.
    topN_report = None
    if run_spice and _check_topN_path_correlation_json(project) is None \
            and _find_bridge_shim(project) is not None:
        try:
            topN_report = run_commercial_pdk_topN_path_correlation(
                project, container=container)
        except Exception as e:  # never let the driver crash the gate
            result.findings.append(Finding(
                rule="SPICE_TOPN_PATH_DRIVER_ERROR",
                severity="INFO",
                message=f"commercial-PDK ngspice top-N path-correlation driver "
                        f"could not run: {e}",
            ))
    else:
        topN_report = _check_topN_path_correlation_json(project)
    if topN_report is not None:
        agg = topN_report.get("aggregate", {})
        sev = "ERROR" if agg.get("verdict") in (
            "MISMATCH", "CRITICAL_MISMATCH") else "INFO"
        result.findings.append(Finding(
            rule=("SPICE_TOPN_PATH_" + ("MISMATCH" if sev == "ERROR"
                                        else "CORRELATED")),
            severity=sev,
            message=(
                f"Real ngspice top-N path correlation "
                f"({agg.get('n_correlated')}/{agg.get('n_paths')} paths "
                f"correlated, {agg.get('n_skipped')} skipped): "
                f"worst |Δ|={agg.get('worst_abs_pct_error')}% "
                f"mean |Δ|={agg.get('mean_abs_pct_error')}% "
                f"vs STA → {agg.get('verdict')}"),
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

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    if not args.json:
        print(_vx.verdict_line("spice_correlation_check", result.passed,
                               skipped, reason))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                suffix = " (measured SPICE decks=0)" if f.rule == "NO_SPICE_VERIFICATION" else ""
                print(f"  [{f.severity}] {f.rule}: {f.message}{suffix}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    # A stall is not a verdict about the subject: it reaches the exit
    # code as rc 2 (UNDETERMINED), announced, never as a finding.
    sys.exit(_pr.exit_undetermined_on_stall(main))
