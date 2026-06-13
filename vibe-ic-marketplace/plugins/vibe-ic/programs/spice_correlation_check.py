#!/usr/bin/env python3
"""spice_correlation_check.py — deterministic gate for post-layout SPICE verification

Validates that post-layout SPICE simulation was performed and its results
correlate with STA timing. Two verification axes:

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


def run_audit(project: Path) -> AuditResult:
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
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

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
