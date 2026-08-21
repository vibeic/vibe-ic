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

NO PASS WITHOUT A DENOMINATOR (#511)
------------------------------------
MEASURED, both cases, same build: on a structurally empty project (only
`input/docs/` and `reports/`, nothing in them) this gate printed

    [PASS] analog_netlist_include_order_check

as its ENTIRE output — one line, rc 0, and no report file written. On a real
corpus project carrying two SPICE decks it printed the SAME line, byte for
byte. Zero decks examined and two decks examined were indistinguishable to
anything reading either the exit code or the text, so a consumer could not
tell "the include order is correct" from "there was no netlist".

The gate now states what it examined, in `_gate_denominator`'s fixed shape,
on stdout AND in `summary.denominator`, and an examination of nothing is a
DISCLOSED SKIP (verdict `VACUOUS_PASS`, rc 2 = NOT CHECKED, plus a
`VACUOUS_PASS:` token on stderr) rather than a PASS. This is the idiom
`si_mcf_sta_check` and `l6_fsm_scaffold_actionable_check` already use; no
third one is invented here. The ordering rule ITSELF is untouched: a GF180
deck with `.lib` before `.include design.ngspice` is still rc 1, with the
same LIB_BEFORE_DESIGN_INCLUDE finding.

Honest-FAIL guarantees:
  * absent / non-directory project  -> exit 2
  * a GF180 netlist with .lib before .include design.ngspice -> exit 1
  * garbage / empty .sp with no include directives at all -> that file is
    reported NO_INCLUDE (does NOT vacuously pass the ordering rule; it is a
    distinct INFO finding and the gate stays PASS only because ordering is
    inapplicable — the model-include PRESENCE rule is owned by
    analog_netlist_pdk_check.py, not here). Such a file still COUNTS in the
    denominator: it was read and put through the rule.

Usage:
    python3 analog_netlist_include_order_check.py <project_dir>
    python3 analog_netlist_include_order_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS (decks examined, ordering honest)
    1 = FAIL (ordering violation)
    2 = VACUOUS_PASS (nothing to examine — disclosed, NOT a sign-off)
        or IO / parse error

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

import _gate_denominator as _gd
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

try:
    import _path_layout as _pl
    _HAVE_PL = True
except Exception:  # pragma: no cover - import shim
    _HAVE_PL = False

GATE = "analog_netlist_include_order_check"

#: What ONE unit is, in this gate's own terms. A bare integer would not say
#: whether the count is of decks, of directives or of blocks — the exact
#: ambiguity `_gate_denominator` exists to remove.
DENOMINATOR_UNIT = ("SPICE netlist deck(s) (*.sp) read and put through the "
                    "model-include ordering rule")

#: rc 2 is this repo's NOT-CHECKED tier: `flow_compliance_check` promotes it
#: to the VACUOUS_PASS verdict tier rather than a bare PASS.
RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2

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
    #: PASS / VACUOUS_PASS / FAIL. `passed` keeps its literal meaning for every
    #: existing consumer (a vacuous run has signed nothing off, so it is not a
    #: FAIL); `verdict` is where the three-way answer lives.
    verdict: str = "PASS"
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
    # fallback: any directory literally named 'analog' or project itself
    for cand in (project / "phase3" / "analog",
                 project / "phase2" / "analog",
                 project / "analog"):
        if cand.is_dir():
            return cand
    if project.is_dir():
        return project
    return None


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


def _vacuous(result: AuditResult, rule: str, reason: str,
             summary_reason: str, considered: int = 0,
             details: Optional[dict] = None) -> AuditResult:
    """Record a run that put ZERO decks through the ordering rule.

    Constructing the denominator with ``examined == 0`` and no reason raises,
    so this gate cannot regress into a silent zero by omission — only by
    writing a reason down, which is reviewable.
    """
    result.findings.append(Finding(rule=rule, severity="INFO", message=reason))
    result.verdict = "VACUOUS_PASS"
    # `passed` keeps its LITERAL meaning — the ordering rule was applied and
    # found nothing wrong — so a consumer reading only that field can no longer
    # be handed a vacuous run as a clean one. It is not a FAIL either: no ERROR
    # finding is emitted and rc is the skip tier. The three-way answer is in
    # `verdict`, the same split `si_mcf_sta_check` makes.
    result.passed = False
    result.summary = {"skipped": True, "reason": summary_reason,
                      "files_checked": 0, "files_pass": 0, "files_fail": 0,
                      "gf180_two_file_decks": 0, "pass": False}
    _gd.attach(result.summary, _gd.Denominator(
        unit=DENOMINATOR_UNIT, examined=0, considered=considered,
        not_applicable_reason=reason, details=details or {}))
    return result


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()
    analog_dir = _analog_dir(project)
    if analog_dir is None:
        return _vacuous(
            result, "SKIP_NO_ANALOG_DIR",
            ("no analog directory: none of phase3/analog/, phase2/analog/ or "
             "analog/ exists under the project and the project path itself is "
             "not a directory, so no SPICE deck could be reached. NOT a "
             "sign-off: the model-include ordering of this project has NOT "
             "been checked."),
            "no_analog_dir")

    sp_files = sorted(analog_dir.rglob("*.sp"))
    try:
        _adir = str(analog_dir.relative_to(project))
    except ValueError:
        _adir = str(analog_dir)
    if not sp_files:
        return _vacuous(
            result, "SKIP_NO_SP_FILES",
            (f"no SPICE deck (*.sp) anywhere under {_adir or '.'}, so no "
             f"file carries an .include/.lib pair to order. NOT a sign-off: "
             f"the model-include ordering of this project has NOT been "
             f"checked."),
            "no_sp_files", details={"analog_dir": _adir})

    checked = 0
    passed = 0
    gf180_decks = 0
    unreadable = 0
    for sp in sp_files:
        try:
            text = sp.read_text(errors="replace")
        except OSError:
            # Considered but never examined: it never reached the rule body.
            unreadable += 1
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

    if checked == 0:
        # Decks were FOUND and none could be read — `considered > 0` with
        # `examined == 0`, the exact shape #496 exists to make visible.
        return _vacuous(
            result, "SKIP_NO_READABLE_SP_FILES",
            (f"{len(sp_files)} SPICE deck(s) were found under "
             f"{_adir or '.'} and NONE could be read (OSError on every one), "
             f"so the ordering rule was applied to nothing. NOT a sign-off."),
            "no_readable_sp_files", considered=len(sp_files),
            details={"analog_dir": _adir, "unreadable": unreadable})

    result.passed = (checked == passed)
    result.verdict = "PASS" if result.passed else "FAIL"
    result.summary = {
        "skipped": False,
        "files_checked": checked,
        "files_pass": passed,
        "files_fail": checked - passed,
        "gf180_two_file_decks": gf180_decks,
        "pass": result.passed,
    }
    _gd.attach(result.summary, _gd.Denominator(
        unit=DENOMINATOR_UNIT, examined=checked, considered=len(sp_files),
        details={"analog_dir": _adir,
                 "gf180_two_file_decks": gf180_decks,
                 "unreadable": unreadable}))
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
        return RC_VACUOUS

    result = run_audit(args.project_dir)
    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)

    denom = result.summary.get(_gd.DENOMINATOR_KEY) or {}
    reason = str(denom.get("not_applicable_reason") or "")

    if not args.json:
        # The verdict line carries the denominator ON ITSELF. Pointing at a
        # report nobody opens is what let the one-line `[PASS] <gate>` stand
        # for both a clean two-deck run and a run over nothing (#511).
        print(f"[{result.verdict}] {GATE}: {_gd.line_of(result.summary)}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.verdict == "VACUOUS_PASS":
        # Second, rc-independent channel — emitted even under --json, where
        # stdout is deliberately empty, so a text consumer is never handed
        # silence. `flow_compliance_check._stdout_signals_vacuous` matches this
        # token at line start.
        print(f"VACUOUS_PASS: {reason}", file=sys.stderr)
        return RC_VACUOUS
    return RC_PASS if result.passed else RC_FAIL


if __name__ == "__main__":
    sys.exit(main())
