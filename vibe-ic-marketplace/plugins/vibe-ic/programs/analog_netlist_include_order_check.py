#!/usr/bin/env python3
"""analog_netlist_include_order_check.py — deterministic SPICE model-include
ordering gate.

Rule (from skill `analog-netlist-gen`):
    For GF180, the device-model design file `design.ngspice` MUST be
    `.include`d BEFORE the parameter library `.lib ... sm141064.ngspice`.
    The design.ngspice file defines the subcircuit device models that the
    sm141064.ngspice corner library binds parameters onto; ngspice resolves
    `.include`/`.lib` directives in textual order, so a `.lib` appearing
    before its `.include` leaves the corner parameters bound to undefined
    models — a real, silent simulation-setup defect.

This is a pure line-order structural check over the netlist's
`.include` / `.lib` statements. It is INDEPENDENT of the body-connection /
device-classification rules already enforced by analog_netlist_pdk_check.py.

Scope:
  * Only GF180 netlists carry the design.ngspice → sm141064.ngspice
    two-file ordering contract, so the ordering rule is applied only when
    BOTH markers are present. SKY130 uses a single `.lib sky130.lib.spice`
    and has no two-file ordering constraint, so such files PASS the
    ordering rule (reported INFO).

Self-skips (exit 0 + INFO) when:
  * no .sp files under the project's analog dir.

Honest-FAIL guarantees:
  * absent / non-directory project  -> exit 2
  * a GF180 netlist with .lib before .include design.ngspice -> exit 1
  * garbage / empty .sp with no include directives at all -> that file is
    reported NO_INCLUDE (does NOT vacuously pass the ordering rule; it is a
    distinct INFO finding and the gate stays PASS only because ordering is
    inapplicable — the model-include PRESENCE rule is owned by
    analog_netlist_pdk_check.py, not here).

Usage:
    python3 analog_netlist_include_order_check.py <project_dir>
    python3 analog_netlist_include_order_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS (or self-skip)
    1 = FAIL (ordering violation)
    2 = IO / parse error

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
except Exception:  # pragma: no cover - import shim
    _HAVE_PL = False

GATE = "analog_netlist_include_order_check"

# Directive matcher: capture (include|lib) keyword + the path token.
INCLUDE_RE = re.compile(r"^\s*\.(include|lib)\b\s+(\S+)", re.IGNORECASE)

DESIGN_MARKER = "design.ngspice"
LIB_MARKER = "sm141064.ngspice"


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = GATE
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# See analog_netlist_connectivity_check for the measured rationale: the flow
# YAML anchors A3 netlists at `phase2/analog/*/*.sp` while the analog runner
# writes them under `phase3/analog/<block>/`. Returning only the FIRST existing
# root hid the phase2 decks from this gate on every project that had reached A5
# — a vacuous PASS. Scan every analog root; never fall back to the whole
# project (a digital PEX netlist is not an analog deck).
_ANALOG_ROOT_RELS = ("phase1/analog", "phase2/analog", "phase3/analog",
                     "analog")


def _analog_roots(project: Path) -> List[Path]:
    """Every analog root that exists, de-duplicated, in scan order."""
    roots: List[Path] = []
    seen = set()

    def _add(cand: Optional[Path]) -> None:
        if cand is None or not cand.is_dir():
            return
        try:
            key = cand.resolve()
        except OSError:
            key = cand
        if key in seen:
            return
        seen.add(key)
        roots.append(cand)

    if _HAVE_PL:
        try:
            d = _pl.analog_dir(project)
            _add(Path(d) if d else None)
        except Exception:
            pass
    for rel in _ANALOG_ROOT_RELS:
        _add(project / rel)
    return roots


def _sp_files(project: Path) -> List[Path]:
    """Every `.sp` deck under every analog root, de-duplicated."""
    out: List[Path] = []
    seen = set()
    for root in _analog_roots(project):
        for sp in sorted(root.rglob("*.sp")):
            try:
                key = sp.resolve()
            except OSError:
                key = sp
            if key in seen:
                continue
            seen.add(key)
            out.append(sp)
    return sorted(out)


def _check_file(text: str, rel: str, findings: List[Finding]) -> bool:
    """Return True if this file PASSes the ordering rule."""
    if DESIGN_MARKER not in text or LIB_MARKER not in text:
        # Not a GF180 two-file deck; ordering rule inapplicable.
        if ".include" in text.lower() or ".lib" in text.lower():
            findings.append(Finding(
                rule="ORDER_INAPPLICABLE",
                severity="INFO",
                message=(f"{rel}: not a GF180 design.ngspice+sm141064 deck; "
                         f"two-file ordering rule inapplicable"),
                file=rel,
            ))
        else:
            findings.append(Finding(
                rule="NO_INCLUDE",
                severity="INFO",
                message=(f"{rel}: no .include/.lib directives "
                         f"(presence is owned by analog_netlist_pdk_check)"),
                file=rel,
            ))
        return True

    design_line: Optional[int] = None
    lib_line: Optional[int] = None
    for idx, raw in enumerate(text.splitlines(), start=1):
        m = INCLUDE_RE.match(raw)
        if not m:
            continue
        kw, path_tok = m.group(1).lower(), m.group(2)
        if kw == "include" and DESIGN_MARKER in path_tok and design_line is None:
            design_line = idx
        if kw == "lib" and LIB_MARKER in path_tok and lib_line is None:
            lib_line = idx

    if design_line is None:
        # marker present in text but never on an .include line (e.g. comment)
        findings.append(Finding(
            rule="DESIGN_INCLUDE_NOT_FOUND",
            severity="ERROR",
            message=(f"{rel}: '{DESIGN_MARKER}' appears but never on a valid "
                     f".include line; cannot establish ordering"),
            file=rel,
        ))
        return False
    if lib_line is None:
        findings.append(Finding(
            rule="LIB_NOT_FOUND",
            severity="ERROR",
            message=(f"{rel}: '{LIB_MARKER}' appears but never on a valid "
                     f".lib line; cannot establish ordering"),
            file=rel,
        ))
        return False

    if lib_line < design_line:
        findings.append(Finding(
            rule="LIB_BEFORE_DESIGN_INCLUDE",
            severity="ERROR",
            message=(f"{rel}: .lib {LIB_MARKER} (line {lib_line}) appears "
                     f"BEFORE .include {DESIGN_MARKER} (line {design_line}); "
                     f"design.ngspice MUST come first"),
            file=rel,
            line=lib_line,
        ))
        return False

    findings.append(Finding(
        rule="INCLUDE_ORDER_OK",
        severity="INFO",
        message=(f"{rel}: .include {DESIGN_MARKER} (line {design_line}) "
                 f"precedes .lib {LIB_MARKER} (line {lib_line})"),
        file=rel,
    ))
    return True


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    if not _analog_roots(project):
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR", severity="INFO",
            message="No analog directory; skipping include-order check"))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    sp_files = _sp_files(project)
    if not sp_files:
        result.findings.append(Finding(
            rule="SKIP_NO_SP_FILES", severity="INFO",
            message="No .sp files; skipping include-order check"))
        result.summary = {"skipped": True, "reason": "no_sp_files"}
        return result

    checked = 0
    passed = 0
    gf180_decks = 0
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
        if DESIGN_MARKER in text and LIB_MARKER in text:
            gf180_decks += 1
        if _check_file(text, rel, result.findings):
            passed += 1

    result.passed = (checked == passed)
    result.summary = {
        "skipped": False,
        "files_checked": checked,
        "files_pass": passed,
        "files_fail": checked - passed,
        "gf180_two_file_decks": gf180_decks,
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
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    else:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {GATE}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
