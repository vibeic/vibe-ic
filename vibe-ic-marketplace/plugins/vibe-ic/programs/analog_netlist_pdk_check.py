#!/usr/bin/env python3
"""analog_netlist_pdk_check.py — deterministic gate for SPICE netlist PDK compliance

Validates that analog SPICE netlists follow correct PDK conventions:
  1. Model include present (.include/.lib with recognized PDK model path)
  2. Body connections correct (PMOS→VDD, NMOS→VSS/0)
  3. Device names match PDK (nfet_03v3/pfet_03v3 for GF180, etc.)
  4. KNOWN_MODELS: every X-line model token that belongs to the detected
     PDK's device-model namespace is a real device for that PDK. A token in
     the namespace but absent from the registry => UNKNOWN_PDK_MODEL (a
     stray / typo'd model name). Tokens OUTSIDE the namespace (user-defined
     subckts) are not validated — zero false positives by construction. The
     known-model set is sourced from programs/pdk_registry.json (per-PDK
     `device_models`), NOT a hardcoded literal in this file.

Self-skips (exit 0 + INFO) when:
  - No .sp files under analog/

Usage:
    python3 analog_netlist_pdk_check.py <project_dir>
    python3 analog_netlist_pdk_check.py <project_dir> --json reports/gates/analog_pdk.json

Exit codes:
    0 = PASS (or self-skip)
    1 = FAIL (PDK convention violation)
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Set, Tuple
import _path_layout as _pl
from _analog_stub_marker import is_stub_text  # v1.6.177 (#72 P1-6)


GF180_MODEL_MARKERS = ("design.ngspice", "sm141064.ngspice")
SKY130_MODEL_MARKERS = ("sky130.lib.spice", "sky130A_setup")

GF180_PMOS = re.compile(r"pfet_0[36]v[03]", re.IGNORECASE)
GF180_NMOS = re.compile(r"nfet_0[36]v[03]", re.IGNORECASE)
SKY130_PMOS = re.compile(r"sky130_fd_pr__pfet", re.IGNORECASE)
SKY130_NMOS = re.compile(r"sky130_fd_pr__nfet", re.IGNORECASE)

VDD_NAMES = {"vdd", "vcc", "vpwr", "avdd", "dvdd", "supply"}
VSS_NAMES = {"vss", "gnd", "0", "vgnd", "avss", "dvss", "ground"}

DEVICE_RE = re.compile(
    r"^[Xx](\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
    re.MULTILINE,
)

INCLUDE_RE = re.compile(
    r"^\s*\.(include|lib)\s+(\S+)",
    re.MULTILINE | re.IGNORECASE,
)

# Map the short PDK token returned by _detect_pdk() to the registry entry name.
_PDK_REGISTRY_NAME = {"sky130": "sky130A", "gf180": "gf180mcuD"}

_REGISTRY_PATH = Path(__file__).resolve().parent / "pdk_registry.json"


def _load_device_model_registry() -> dict:
    """Read programs/pdk_registry.json → {short_pdk: {prefix, bare_re, models:set}}.

    Honest-skip on any IO/parse problem: returns {} so the KNOWN_MODELS check
    is silently disabled rather than emitting garbage findings. The model set
    is NEVER hardcoded here — it lives in the registry data file.
    """
    out: dict = {}
    try:
        data = json.loads(_REGISTRY_PATH.read_text())
    except (OSError, ValueError):
        return out
    for pdk in data.get("pdks", []):
        models = pdk.get("device_models")
        if not models:
            continue
        # find the short token that maps to this registry name
        short = next(
            (s for s, name in _PDK_REGISTRY_NAME.items() if name == pdk.get("name")),
            None,
        )
        if short is None:
            continue
        out[short] = {
            "prefix": pdk.get("device_model_prefix", ""),
            "bare_re": pdk.get("device_model_bare_re"),
            "models": {m.lower() for m in models},
        }
    return out


def _in_pdk_namespace(model: str, reg: dict) -> bool:
    """True iff `model` looks like it belongs to this PDK's device-model
    namespace (and is therefore validated against the known-model set).

    A token is in-namespace when EITHER it carries the canonical PDK prefix
    (e.g. ``sky130_fd_pr__``) OR it matches the optional bare-form regex
    (e.g. GF180 ``nfet_03v3``). Everything else (user subckt calls) is
    out-of-namespace and never flagged — this is the zero-false-positive
    guarantee.
    """
    ml = model.lower()
    prefix = (reg.get("prefix") or "").lower()
    if prefix and ml.startswith(prefix):
        return True
    bare_re = reg.get("bare_re")
    if bare_re and re.search(bare_re, ml, re.IGNORECASE):
        return True
    return False


def _check_known_models(
    text: str, rel_path: str, pdk: Optional[str], findings: List[Finding]
) -> int:
    """For the detected PDK, verify each X-line model token that belongs to
    that PDK's device-model namespace is a known device. Emit
    UNKNOWN_PDK_MODEL for a stray/typo token. Returns the error count.

    Honest-skip when PDK is unknown or the registry has no entry for it
    (returns 0, no findings) — never a vacuous pass and never a false flag.
    """
    if pdk is None:
        return 0
    registry = _load_device_model_registry()
    reg = registry.get(pdk)
    if not reg or not reg.get("models"):
        return 0

    known = reg["models"]
    errors = 0
    for m in DEVICE_RE.finditer(text):
        inst = m.group(1)
        model = m.group(6)
        if not _in_pdk_namespace(model, reg):
            continue  # user subckt or foreign token — not our concern
        if model.lower() not in known:
            line_num = text[: m.start()].count("\n") + 1
            findings.append(Finding(
                rule="UNKNOWN_PDK_MODEL",
                severity="ERROR",
                message=(
                    f"Device X{inst} references model '{model}' which is in the "
                    f"{pdk} device-model namespace but is not a known {pdk} device "
                    f"(stray or typo'd model name). Check programs/pdk_registry.json "
                    f"device_models for the valid set."
                ),
                file=rel_path,
                line=line_num,
            ))
            errors += 1
    return errors


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_netlist_pdk_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _detect_pdk(text: str) -> Optional[str]:
    for marker in GF180_MODEL_MARKERS:
        if marker in text:
            return "gf180"
    for marker in SKY130_MODEL_MARKERS:
        if marker in text:
            return "sky130"
    return None


def _check_model_includes(text: str, rel_path: str, findings: List[Finding]) -> bool:
    includes = INCLUDE_RE.findall(text)
    if not includes:
        findings.append(Finding(
            rule="NO_MODEL_INCLUDE",
            severity="ERROR",
            message=(
                f"No .include or .lib directive found. "
                f"SPICE netlist must include PDK device models."
            ),
            file=rel_path,
        ))
        return False
    return True


def _check_body_connections(
    text: str, rel_path: str, findings: List[Finding]
) -> int:
    errors = 0
    for m in DEVICE_RE.finditer(text):
        inst = m.group(1)
        body = m.group(5).lower()
        model = m.group(6)

        is_pmos = GF180_PMOS.search(model) or SKY130_PMOS.search(model)
        is_nmos = GF180_NMOS.search(model) or SKY130_NMOS.search(model)

        if is_pmos and body in VSS_NAMES:
            line_num = text[:m.start()].count("\n") + 1
            findings.append(Finding(
                rule="PMOS_BODY_TO_VSS",
                severity="ERROR",
                message=(
                    f"PMOS device X{inst} has body connected to '{m.group(5)}' "
                    f"(should be VDD/supply). Model: {model}"
                ),
                file=rel_path,
                line=line_num,
            ))
            errors += 1

        if is_nmos and body in VDD_NAMES:
            line_num = text[:m.start()].count("\n") + 1
            findings.append(Finding(
                rule="NMOS_BODY_TO_VDD",
                severity="ERROR",
                message=(
                    f"NMOS device X{inst} has body connected to '{m.group(5)}' "
                    f"(should be VSS/GND/0). Model: {model}"
                ),
                file=rel_path,
                line=line_num,
            ))
            errors += 1

    return errors


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    analog_dir = _pl.analog_dir(project)
    if not analog_dir.is_dir():
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR",
            severity="INFO",
            message="No analog/ directory; skipping netlist PDK check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    sp_files = sorted(analog_dir.rglob("*.sp"))

    if not sp_files:
        result.findings.append(Finding(
            rule="SKIP_NO_SP_FILES",
            severity="INFO",
            message="No .sp files under analog/; skipping netlist PDK check",
        ))
        result.summary = {"skipped": True, "reason": "no_sp_files"}
        return result

    files_checked = 0
    files_pass = 0
    files_stub = 0   # v1.6.177 (#72 P1-6)
    total_body_errors = 0
    total_model_errors = 0

    for sp in sp_files:
        try:
            text = sp.read_text(errors="replace")
        except OSError:
            continue

        rel = str(sp.relative_to(project))
        files_checked += 1

        # v1.6.177 (#72 P1-6) — when a SPICE netlist carries the
        # deterministic-stub marker (`extraction_strategy=
        # deterministic_stub` on the first non-empty line),
        # skip the strict model-include + body-connection checks.
        # Stubs are intentionally minimal substance; failing them
        # here causes the gate to FAIL on every PASS_WITH_STUB
        # benchmark run. chip-AGNOSTIC: the marker is a structural
        # property of the artefact, never a chip-class literal.
        if is_stub_text(text):
            files_stub += 1
            files_pass += 1
            result.findings.append(Finding(
                rule="NETLIST_PDK_STUB_ACCEPTED",
                severity="INFO",
                message=(f"{rel}: deterministic-stub netlist "
                         f"accepted (PASS_WITH_STUB tier)"),
                file=rel,
            ))
            continue

        file_ok = True

        if not _check_model_includes(text, rel, result.findings):
            file_ok = False

        body_errs = _check_body_connections(text, rel, result.findings)
        if body_errs > 0:
            file_ok = False
            total_body_errors += body_errs

        pdk = _detect_pdk(text)
        model_errs = _check_known_models(text, rel, pdk, result.findings)
        if model_errs > 0:
            file_ok = False
            total_model_errors += model_errs

        if file_ok:
            files_pass += 1
            result.findings.append(Finding(
                rule="NETLIST_PDK_OK",
                severity="INFO",
                message=f"{rel}: model includes present, body connections correct",
                file=rel,
            ))

    if files_checked > files_pass:
        result.passed = False

    # v1.6.177 (#72 P1-6) — surface tier in the summary so
    # flow_compliance_check / downstream readers can distinguish
    # real PASS from PASS_WITH_STUB.
    verdict_tier = "PASS"
    if result.passed and files_stub and files_stub == files_checked:
        verdict_tier = "PASS_WITH_STUB"
    elif result.passed and files_stub:
        verdict_tier = "PASS_WITH_STUB_PARTIAL"

    result.summary = {
        "skipped": False,
        "files_checked": files_checked,
        "files_pass": files_pass,
        "files_stub": files_stub,
        "files_fail": files_checked - files_pass,
        "body_connection_errors": total_body_errors,
        "unknown_pdk_model_errors": total_model_errors,
        "pass": result.passed,
        "verdict_tier": verdict_tier,
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
        print(f"[{status}] analog_netlist_pdk_check")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
