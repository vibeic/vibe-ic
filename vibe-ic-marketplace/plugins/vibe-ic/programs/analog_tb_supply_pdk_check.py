#!/usr/bin/env python3
"""analog_tb_supply_pdk_check.py — deterministic testbench supply-vs-PDK
consistency gate.

Rule (from skill `analog-netlist-gen`):
    The testbench supply value MUST match the PDK / device flavor:
      * GF180  -> Vdd 3.3 V, devices nfet_03v3 / pfet_03v3 (03v3 = 3.3 V)
      * SKY130 -> Vdd 1.8 V, devices sky130_fd_pr__nfet_01v8 / pfet_01v8
    A 3.3 V supply on a 01v8 (1.8 V) device, or a 1.8 V supply on a 03v3
    device, is a real setup defect — it either over-stresses the device
    model or biases it out of its operating region, and the corner sweep
    silently produces garbage.

This is a table-lookup check:
  1. detect PDK from the model-include markers and/or device tokens
  2. detect the supply DC value from a `Vdd/Vsupply/Vvdd ... DC <v>` source
  3. detect device flavor (03v3 / 01v8 / 05v0) from the device model tokens
  4. FAIL on any mismatch in the expected (pdk, vdd_volts, flavor) triple.

Expected table:
    gf180  : vdd in {3.3, 5.0}, flavor in {03v3, 05v0}  (3v3 default)
    sky130 : vdd == 1.8,        flavor == 01v8

Tolerance on the supply value: +/- 5% (datasheet nominal jitter).

Honest-FAIL guarantees:
  * absent / non-directory project -> exit 2
  * a tb deck declaring `Vdd VDD 0 DC 3.3` with sky130_fd_pr__nfet_01v8
    devices -> exit 1 (SUPPLY_DEVICE_MISMATCH)
  * a deck with NO recognizable PDK -> reported UNKNOWN_PDK INFO, that file
    is skipped (cannot judge) and is surfaced in files_unknown_pdk; the gate
    does not vacuously PASS such a file.
  * a deck with a PDK but NO supply source -> NO_SUPPLY INFO, surfaced in
    files_no_supply, not a vacuous pass.

Usage:
    python3 analog_tb_supply_pdk_check.py <project_dir>
    python3 analog_tb_supply_pdk_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS: at least one .sp deck was read and no supply/device/PDK triple
        is inconsistent
    1 = FAIL (supply/device/PDK mismatch)
    2 = VACUOUS: nothing was examined — no analog/ directory, or no .sp file
        in it, so no supply and no device flavor was ever compared. #521:
        both used to be rc 0, on 196 of the 200 tracked project roots — the
        whole-gate counterpart of the per-file "not a vacuous pass" rules
        above. Also rc 2 for an IO / parse error.

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

try:
    import _path_layout as _pl
    _HAVE_PL = True
except Exception:  # pragma: no cover
    _HAVE_PL = False

import _vacuous_exit as _vx
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

GATE = "analog_tb_supply_pdk_check"

GF180_MARKERS = ("design.ngspice", "sm141064.ngspice")
SKY130_MARKERS = ("sky130.lib.spice", "sky130A_setup", "sky130_fd_pr__")

# device-flavor -> nominal supply volts
FLAVOR_VOLTS = {"01v8": 1.8, "03v3": 3.3, "05v0": 5.0}

# PDK -> set of legal flavors
PDK_FLAVORS = {
    "gf180": {"03v3", "05v0"},
    "sky130": {"01v8"},
}

FLAVOR_RE = re.compile(r"_(0[135]v[08])\b", re.IGNORECASE)

# A DC voltage source feeding a supply-named node: name starts with V and
# the source name contains 'dd'/'supply'/'vcc'/'pwr'. Capture the DC value.
SUPPLY_SRC_RE = re.compile(
    r"^\s*(V\w*(?:dd|supply|vcc|pwr|cc)\w*)\s+\S+\s+\S+\s+"
    r"(?:DC\s+)?([0-9]*\.?[0-9]+)",
    re.IGNORECASE | re.MULTILINE,
)

TOL = 0.05  # +/- 5%


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str = GATE
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _analog_dir(project: Path) -> Optional[Path]:
    if _HAVE_PL:
        try:
            d = _pl.analog_dir(project)
            if d and Path(d).is_dir():
                return Path(d)
        except Exception:
            pass
    for cand in (project / "phase3" / "analog",
                 project / "phase2" / "analog",
                 project / "analog"):
        if cand.is_dir():
            return cand
    if project.is_dir():
        return project
    return None


def _detect_pdk(text: str) -> Optional[str]:
    for m in GF180_MARKERS:
        if m in text:
            return "gf180"
    for m in SKY130_MARKERS:
        if m in text:
            return "sky130"
    return None


def _detect_flavors(text: str) -> set:
    return {m.group(1).lower() for m in FLAVOR_RE.finditer(text)}


def _detect_supply_volts(text: str) -> Optional[float]:
    m = SUPPLY_SRC_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(2))
    except ValueError:
        return None


def _within(actual: float, nominal: float) -> bool:
    return abs(actual - nominal) <= nominal * TOL


def _check_file(text: str, rel: str, findings: List[Finding]) -> Optional[bool]:
    """Return True (pass), False (fail), or None (skipped / not judgeable)."""
    pdk = _detect_pdk(text)
    if pdk is None:
        findings.append(Finding(
            rule="UNKNOWN_PDK", severity="INFO",
            message=f"{rel}: no recognizable PDK markers; cannot judge supply",
            file=rel))
        return None

    volts = _detect_supply_volts(text)
    if volts is None:
        findings.append(Finding(
            rule="NO_SUPPLY", severity="INFO",
            message=f"{rel}: PDK={pdk} but no Vdd/supply DC source found",
            file=rel))
        return None

    legal_flavors = PDK_FLAVORS[pdk]
    flavors = _detect_flavors(text) & set(FLAVOR_VOLTS)

    ok = True

    # 1) supply value must match one of the PDK's legal flavor voltages
    legal_volts = [FLAVOR_VOLTS[f] for f in legal_flavors]
    if not any(_within(volts, v) for v in legal_volts):
        ok = False
        findings.append(Finding(
            rule="SUPPLY_PDK_MISMATCH", severity="ERROR",
            message=(f"{rel}: PDK={pdk} supply {volts}V is not within "
                     f"{TOL*100:.0f}% of any legal "
                     f"{sorted(legal_volts)}V"),
            file=rel))

    # 2) device flavor must be legal for the PDK, and the supply must match
    #    the device flavor's nominal voltage.
    for f in sorted(flavors):
        if f not in legal_flavors:
            ok = False
            findings.append(Finding(
                rule="DEVICE_FLAVOR_PDK_MISMATCH", severity="ERROR",
                message=(f"{rel}: device flavor {f} is not legal for "
                         f"PDK={pdk} (legal: {sorted(legal_flavors)})"),
                file=rel))
            continue
        if not _within(volts, FLAVOR_VOLTS[f]):
            ok = False
            findings.append(Finding(
                rule="SUPPLY_DEVICE_MISMATCH", severity="ERROR",
                message=(f"{rel}: supply {volts}V does not match device "
                         f"flavor {f} nominal {FLAVOR_VOLTS[f]}V"),
                file=rel))

    if ok:
        findings.append(Finding(
            rule="TB_SUPPLY_OK", severity="INFO",
            message=(f"{rel}: PDK={pdk} supply {volts}V consistent with "
                     f"flavors {sorted(flavors) or 'n/a'}"),
            file=rel))
    return ok


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    analog_dir = _analog_dir(project)
    if analog_dir is None:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR", severity="INFO",
            message="No analog directory; skipping tb supply check"))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    sp_files = sorted(analog_dir.rglob("*.sp"))
    if not sp_files:
        result.findings.append(Finding(
            rule="SKIP_NO_SP_FILES", severity="INFO",
            message="No .sp files; skipping tb supply check"))
        result.summary = {"skipped": True, "reason": "no_sp_files"}
        return result

    checked = 0
    judged = 0
    files_pass = 0
    files_unknown_pdk = 0
    files_no_supply = 0
    for sp in sp_files:
        try:
            text = sp.read_text(errors="replace")
        except OSError:
            continue
        try:
            rel = str(sp.relative_to(project))
        except ValueError:
            rel = str(sp)
        checked += 1
        verdict = _check_file(text, rel, result.findings)
        if verdict is None:
            # distinguish the two skip reasons by scanning the last finding
            if result.findings and result.findings[-1].rule == "UNKNOWN_PDK":
                files_unknown_pdk += 1
            else:
                files_no_supply += 1
            continue
        judged += 1
        if verdict:
            files_pass += 1
        else:
            result.passed = False

    result.summary = {
        "skipped": False,
        "files_checked": checked,
        "files_judged": judged,
        "files_pass": files_pass,
        "files_fail": judged - files_pass,
        "files_unknown_pdk": files_unknown_pdk,
        "files_no_supply": files_no_supply,
        "pass": result.passed,
    }
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)
    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)
    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)
    else:
        print(_vx.verdict_line(GATE, result.passed, skipped, reason))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
