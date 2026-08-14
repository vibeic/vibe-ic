#!/usr/bin/env python3
"""analog_digital_interface_check.py — deterministic gate for digital-analog interface validation

Validates that every analog block has a properly defined digital-analog
interface with signal direction, type, and voltage domain.

Checks:
  1. Every block in analog_block_list.json has interface pins (in interface.json
     or spec.json "interface" / "pins" key)
  2. Each signal has direction (input/output/inout), type (digital/analog/power),
     and voltage_domain
  3. Level-shifter requirement flagged when digital (1.8V/1.2V) meets analog (3.3V)

Self-skips when:
  - No analog_block_list.json or empty block list
  - The IC is classified non-analog and every declared block is a
    low_confidence phantom keyword hit (ORGANIC #676)

Usage:
    python3 analog_digital_interface_check.py <project_dir>
    python3 analog_digital_interface_check.py <project_dir> --json reports/gates/interface.json

Exit codes:
    0 = PASS: at least one declared analog block's interface was read and it
        is complete
    1 = FAIL (missing or incomplete interface)
    2 = VACUOUS: nothing was examined — no analog block is declared, or the
        declared ones are the phantom keyword hits of a pure-digital IC, so
        there is no analog/digital boundary here to validate. #521: both used
        to be rc 0. Also rc 2 for an IO / parse error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import _path_layout as _pl
import _vacuous_exit as _vx
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_digital_interface_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


DIGITAL_DOMAINS = {"1.2V", "1.2", "1.8V", "1.8", "1.0V", "1.0", "0.9V", "0.9"}
ANALOG_DOMAINS = {"3.3V", "3.3", "2.5V", "2.5", "5.0V", "5.0", "5V"}
REQUIRED_FIELDS = {"direction", "type", "voltage_domain"}


def _load_block_list(project: Path) -> List[str]:
    bl = _pl.analog_dir(project) / "analog_block_list.json"
    if not bl.exists():
        return []
    try:
        data = json.loads(bl.read_text(errors="replace"))
        if isinstance(data, dict) and "blocks" in data:
            return [b["name"] if isinstance(b, dict) else str(b)
                    for b in data["blocks"]]
        if isinstance(data, list):
            return [b["name"] if isinstance(b, dict) else str(b)
                    for b in data]
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return []


def _load_interface(project: Path, block: str) -> Optional[List[Dict[str, Any]]]:
    analog_dir = _pl.analog_dir(project) / block
    iface_file = analog_dir / "interface.json"
    if iface_file.exists():
        try:
            data = json.loads(iface_file.read_text(errors="replace"))
            if isinstance(data, dict) and "pins" in data:
                return data["pins"]
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass

    spec_file = analog_dir / "spec.json"
    if spec_file.exists():
        try:
            data = json.loads(spec_file.read_text(errors="replace"))
            if isinstance(data, dict):
                if "interface" in data:
                    iface = data["interface"]
                    if isinstance(iface, list):
                        return iface
                    if isinstance(iface, dict) and "pins" in iface:
                        return iface["pins"]
                if "pins" in data:
                    return data["pins"]
        except (json.JSONDecodeError, OSError):
            pass

    return None


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    blocks = _load_block_list(project)

    if not blocks:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG",
            severity="INFO",
            message="No analog_block_list.json or empty; skipping interface check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_blocks"}
        return result

    # ORGANIC #676 — class-N/A skip (defence-in-depth; see
    # analog_flow_compliance_check). A pure-digital SoC whose only "blocks" are
    # low_confidence phantom keyword hits skips the analog-digital interface
    # check instead of hard-FAILing. §4.05 no-leak: real analog IC / confident
    # block still gated.
    try:
        import _analog_a_check_common as _aac
        if _aac.analog_class_is_na(project):
            result.findings.append(Finding(
                rule="SKIP_DIGITAL_CLASS_NA",
                severity="INFO",
                message=("IC classified non-analog and all declared blocks are "
                         "low_confidence phantom keyword hits — analog-digital "
                         "interface N/A (ORGANIC #676)"),
            ))
            result.summary = {"skipped": True,
                              "reason": "digital_class_na_low_confidence"}
            return result
    except Exception:
        pass

    complete = 0
    errors = 0
    level_shifter_warnings = 0

    for block in blocks:
        pins = _load_interface(project, block)

        if pins is None:
            errors += 1
            result.passed = False
            result.findings.append(Finding(
                rule="INTERFACE_MISSING",
                severity="ERROR",
                message=(
                    f"Block '{block}': no interface definition found. "
                    f"Create analog/{block}/interface.json or add 'interface' "
                    f"key to spec.json."
                ),
            ))
            continue

        if not pins:
            errors += 1
            result.passed = False
            result.findings.append(Finding(
                rule="INTERFACE_EMPTY",
                severity="ERROR",
                message=f"Block '{block}': interface defined but has no pins",
            ))
            continue

        block_ok = True
        for pin in pins:
            if not isinstance(pin, dict):
                continue
            name = pin.get("name", "(unnamed)")
            missing = REQUIRED_FIELDS - set(pin.keys())
            if missing:
                block_ok = False
                result.findings.append(Finding(
                    rule="INTERFACE_INCOMPLETE_PIN",
                    severity="ERROR",
                    message=(
                        f"Block '{block}' pin '{name}': missing fields "
                        f"{', '.join(sorted(missing))}"
                    ),
                ))

            domain = str(pin.get("voltage_domain", ""))
            if domain in DIGITAL_DOMAINS:
                pass
            elif domain in ANALOG_DOMAINS:
                pass
            elif domain and domain not in DIGITAL_DOMAINS | ANALOG_DOMAINS:
                result.findings.append(Finding(
                    rule="INTERFACE_UNKNOWN_DOMAIN",
                    severity="WARNING",
                    message=f"Block '{block}' pin '{name}': unknown voltage domain '{domain}'",
                ))

        all_domains: Set[str] = set()
        for pin in pins:
            if isinstance(pin, dict) and "voltage_domain" in pin:
                all_domains.add(str(pin["voltage_domain"]))
        has_digital = bool(all_domains & DIGITAL_DOMAINS)
        has_analog = bool(all_domains & ANALOG_DOMAINS)
        if has_digital and has_analog:
            level_shifter_warnings += 1
            result.findings.append(Finding(
                rule="INTERFACE_LEVEL_SHIFTER",
                severity="WARNING",
                message=(
                    f"Block '{block}': mixes digital ({all_domains & DIGITAL_DOMAINS}) "
                    f"and analog ({all_domains & ANALOG_DOMAINS}) domains — "
                    f"level shifter required at boundary"
                ),
            ))

        if not block_ok:
            errors += 1
            result.passed = False
        else:
            complete += 1
            result.findings.append(Finding(
                rule="INTERFACE_COMPLETE",
                severity="INFO",
                message=f"Block '{block}' interface fully defined ({len(pins)} pins)",
            ))

    result.summary = {
        "skipped": False,
        "total_blocks": len(blocks),
        "complete": complete,
        "errors": errors,
        "level_shifter_warnings": level_shifter_warnings,
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
    # v1.6.144 (#57) — FPGA-prototype-stage stub waiver.
    import _fpga_stub_waiver as _stub
    _stub.add_fpga_stub_argparse(ap)
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

    waiver_status: str = "PASS"
    if not result.passed and _stub.fpga_stub_waiver_active(args):
        result.passed = True
        waiver_status = "PASS_WITH_WAIVERS"
        result.summary["fpga_stub_waiver_applied"] = True
        result.summary["waiver_reason"] = _stub.fpga_stub_reason()
        for f in result.findings:
            if f.severity == "ERROR":
                f.severity = "WARNING"

    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    if not args.json:
        print(_vx.verdict_line("analog_digital_interface_check", result.passed,
                               skipped, reason, pass_token=waiver_status))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
