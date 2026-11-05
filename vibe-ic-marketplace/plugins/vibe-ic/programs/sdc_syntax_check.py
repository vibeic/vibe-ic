#!/usr/bin/env python3
"""
sdc_syntax_check.py — Deterministic compliance check for constraint-gen.

Verifies that SDC (Synopsys Design Constraints) files exist and contain valid
clock definitions, timing constraints, and no obvious syntax errors.

What it catches:
  1. NO_SDC_FILE — no .sdc files found in project directory
  2. NO_CREATE_CLOCK — SDC file has no create_clock command
  3. NO_TIMING_CONSTRAINT — no set_input_delay, set_output_delay, set_max_delay,
     set_false_path, or set_multicycle_path found
  4. BAD_CLOCK_PERIOD — clock period is outside reasonable range (0.1ns to 10000ns)
  5. SYNTAX_ERROR — unmatched brackets or missing -period value
  6. EMPTY_FILE — SDC file is empty or has no meaningful content

Usage:
    python3 sdc_syntax_check.py ./my_project
    python3 sdc_syntax_check.py ./my_project --json

Exit codes:
    0 = valid SDC file(s) found
    1 = no valid SDC found

Generality: works for ANY IC project with SDC constraint files.
No external tool dependencies — pure Python.
"""
from __future__ import annotations

# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Measured
# on the base tree: 454 of the 1385 top-level programs died that way. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------


import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Tuple
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)
import _gate_authorship as _ga  # R-0915-152 (who invoked this writer)
import _path_layout as _pl
import sdc_constraints as _sdc


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str       # ERROR, WARNING, INFO
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str
    passed: bool
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
CREATE_CLOCK_RE = re.compile(
    r'\bcreate_clock\b', re.MULTILINE
)
CLOCK_PERIOD_RE = re.compile(
    r'\bcreate_clock\b[^;\n]*-period\s+(\S+)', re.MULTILINE
)
TIMING_COMMANDS = [
    "set_input_delay",
    "set_output_delay",
    "set_max_delay",
    "set_false_path",
    "set_multicycle_path",
]
TIMING_RE = re.compile(
    r'\b(' + '|'.join(TIMING_COMMANDS) + r')\b', re.MULTILINE
)

# Reasonable clock period bounds (nanoseconds)
MIN_PERIOD_NS = 0.1
MAX_PERIOD_NS = 10000.0


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------
def discover_sdc_files(base: Path, *, include_phase3: bool = True) -> List[Path]:
    """Return the design SDC population for the Step-7/8 contract.

    The flow's staged inputs are defined by :func:`sdc_constraints.collect_sdc_files`;
    Step 7's declared Phase-2 outputs are the two direct roots appended here.
    LibreLane run directories are deliberately outside this contract: their
    tool-generated ``*.abc.sdc`` files are judged by the OpenSTA receipt, not by
    the design regex arm. A recursive project scan would turn an intermediate
    deck into a false design failure.
    """
    extra_dirs = [_pl.fpga_early_dir(base), _pl.constraints_dir(base)]
    if include_phase3:
        # Direct mode owns the Phase-3 design deck.  In dual mode OpenSTA's
        # current receipt is authoritative for that same deck, so the regex
        # arm audits only the staged design constraints to avoid double-counting.
        extra_dirs.extend([
            _pl.phase3_stage3_dir(base) / "constraints",
            _pl.cts_dir(base) / "constraints",
            _pl.pnr_dir(base),
        ])
    return _sdc.collect_sdc_files(base, extra_dirs=extra_dirs)


# ---------------------------------------------------------------------------
# Bracket checking
# ---------------------------------------------------------------------------
def check_brackets(text: str) -> List[Tuple[int, str]]:
    """Check for unmatched brackets in SDC text.

    Returns list of (line_number, description) for issues found.
    """
    issues: List[Tuple[int, str]] = []
    stack: List[Tuple[str, int]] = []  # (bracket_char, line_number)
    pairs = {')': '(', ']': '[', '}': '{'}

    for lineno, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        # Skip comments
        if stripped.startswith("#"):
            continue
        for ch in stripped:
            if ch in ('(', '[', '{'):
                stack.append((ch, lineno))
            elif ch in (')', ']', '}'):
                if not stack:
                    issues.append((lineno, f"Unmatched closing '{ch}'"))
                elif stack[-1][0] != pairs[ch]:
                    issues.append((lineno, f"Mismatched bracket: expected closing for '{stack[-1][0]}' but got '{ch}'"))
                    stack.pop()
                else:
                    stack.pop()

    for bracket, lineno in stack:
        issues.append((lineno, f"Unmatched opening '{bracket}'"))

    return issues


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------
#: Where the step-8 tool path writes OpenSTA's own verdict on the SDC.
OPENSTA_GATE = Path("phase3/librelane/prelayout/gates/step8_sdc_opensta.json")


def opensta_gate(base: Path) -> Tuple[str, List[Finding], bool]:
    """Step 8 on the tool path: OpenSTA's read_sdc/check_setup verdict.

    Selected by `phase3/librelane_switch.json` step "8". In `librelane` mode it
    replaces the regex parse below; in `dual` both must pass. The record must
    be bound to the SDC the flow hands the tool, else it is someone else's run.
    """
    import librelane_contract as _llc
    try:
        mode = _llc.selected_mode(base, "8")
    except (_llc.Refusal, ValueError, OSError) as exc:
        return "invalid", [Finding("SWITCH_INVALID", "ERROR", str(exc))], False
    if mode == "direct":
        return mode, [], True
    record = base / OPENSTA_GATE
    if not record.is_file():
        return mode, [Finding("OPENSTA_GATE_ABSENT", "ERROR",
                              f"{OPENSTA_GATE} not written: STAPrePNR did not run "
                              "for this project", str(OPENSTA_GATE))], False
    try:
        doc = json.loads(record.read_text())
    except (OSError, ValueError) as exc:
        return mode, [Finding("OPENSTA_GATE_UNREADABLE", "ERROR", str(exc),
                              str(OPENSTA_GATE))], False
    raw_deck = Path(str(doc.get("sdc") or ""))
    deck = raw_deck if raw_deck.is_absolute() else base / raw_deck
    try:
        resolved_base = base.resolve()
        resolved_deck = deck.resolve(strict=False)
        in_project = resolved_deck.is_relative_to(resolved_base)
    except OSError:
        in_project = False
        resolved_deck = deck
    if (not in_project or not resolved_deck.is_file()
            or doc.get("sdc_sha256") != _llc.digest(resolved_deck)):
        return mode, [Finding("OPENSTA_GATE_STALE", "ERROR",
                              f"record is not bound to the current project SDC bytes of {resolved_deck}",
                              str(OPENSTA_GATE))], False
    deck = resolved_deck
    status = doc.get("verdict")
    findings = [Finding("OPENSTA_" + str(status), "ERROR" if status != "PASS" else "INFO",
                        text, str(OPENSTA_GATE)) for text in doc.get("findings") or []]
    findings.append(Finding("OPENSTA_VERDICT", "INFO" if status == "PASS" else "ERROR",
                            f"OpenSTA read_sdc/check_setup verdict {status} on {deck}",
                            str(OPENSTA_GATE)))
    return mode, findings, status == "PASS"


def audit(project_dir: str) -> AuditResult:
    base = Path(project_dir)
    mode, tool_findings, tool_passed = (opensta_gate(base) if base.is_dir()
                                        else ("direct", [], True))
    if mode == "librelane":
        return AuditResult(program="sdc_syntax_check", passed=tool_passed,
                           findings=tool_findings,
                           summary={"mode": mode, "judge": str(OPENSTA_GATE)})
    result = _regex_audit(project_dir, include_phase3=(mode == "direct"))
    if mode != "direct":
        result.findings = tool_findings + result.findings
        result.passed = result.passed and tool_passed
        result.summary["mode"] = mode
    return result


def _regex_audit(project_dir: str, *, include_phase3: bool = True,
                 sdc_path: Optional[Path] = None,
                 sdc_sha256: Optional[str] = None) -> AuditResult:
    findings: List[Finding] = []
    base = Path(project_dir)
    explicit = sdc_path is not None or sdc_sha256 is not None

    if not base.exists() or not base.is_dir():
        findings.append(Finding(
            rule=("SDC_AUTHORITY_REFUSED" if explicit else "DIR_MISSING"),
            severity="ERROR",
            message=f"Project directory does not exist: {project_dir}",
        ))
        return AuditResult(
            program="sdc_syntax_check",
            passed=False,
            findings=findings,
            summary={"files_checked": 0, "valid_files": 0},
        )

    # D20's early, technology-independent caller supplies its one
    # invocation-bound original deck explicitly. Every existing CLI/default
    # caller retains declared-root discovery.
    if explicit and (sdc_path is None or not isinstance(sdc_sha256, str)
                     or not re.fullmatch(r"[0-9a-f]{64}", sdc_sha256)):
        findings.append(Finding(
            rule="SDC_AUTHORITY_REFUSED", severity="ERROR",
            message="explicit SDC authority requires one path and SHA-256",
        ))
        return AuditResult(
            program="sdc_syntax_check", passed=False, findings=findings,
            summary={"files_checked": 0, "valid_files": 0,
                     "sdc_files_checked": [],
                     "sdc_sha256_expected": sdc_sha256,
                     "sdc_sha256_observed": None},
        )
    if explicit:
        candidate = Path(sdc_path)
        try:
            project_root = base.resolve(strict=True)
            declared_root = project_root / "input/constraints"
            if ((project_root / "input").is_symlink()
                    or declared_root.is_symlink()):
                raise ValueError("input/constraints path traverses a symlink")
            if candidate.parent != declared_root:
                raise ValueError(
                    "explicit SDC parent is not literal input/constraints authority")
            input_root = declared_root.resolve(strict=True)
            if input_root != declared_root:
                raise ValueError("input/constraints traverses a symlink")
            if candidate.is_symlink():
                raise ValueError("explicit SDC is a symlink")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_file() or resolved.parent != input_root:
                raise ValueError(
                    "explicit SDC is not a direct input/constraints file")
        except (OSError, RuntimeError, ValueError) as exc:
            findings.append(Finding(
                rule="SDC_AUTHORITY_REFUSED", severity="ERROR",
                message=str(exc), file=str(candidate),
            ))
            return AuditResult(
                program="sdc_syntax_check", passed=False, findings=findings,
                summary={"files_checked": 0, "valid_files": 0,
                         "sdc_files_checked": [],
                         "sdc_sha256_expected": sdc_sha256,
                         "sdc_sha256_observed": None},
            )
        sdc_files = [resolved]
    else:
        sdc_files = discover_sdc_files(
            base, include_phase3=include_phase3)

    if explicit:
        try:
            observed = hashlib.sha256(sdc_files[0].read_bytes()).hexdigest()
        except OSError:
            observed = None
        if observed != sdc_sha256:
            findings.append(Finding(
                rule="SDC_AUTHORITY_REFUSED", severity="ERROR",
                message=("explicit SDC bytes do not match the "
                         "invocation-bound SHA-256"),
                file=str(sdc_files[0]),
            ))
            return AuditResult(
                program="sdc_syntax_check", passed=False, findings=findings,
                summary={"files_checked": 0, "valid_files": 0,
                         "sdc_files_checked": [str(p) for p in sdc_files],
                         "sdc_sha256_expected": sdc_sha256,
                         "sdc_sha256_observed": observed},
            )

    if not sdc_files:
        findings.append(Finding(
            rule="NO_SDC_FILE",
            severity="ERROR",
            message="No .sdc files found in project directory",
        ))
        return AuditResult(
            program="sdc_syntax_check",
            passed=False,
            findings=findings,
            summary={"files_checked": 0, "valid_files": 0},
        )

    valid_files = 0

    for sf in sdc_files:
        rel = str(sf.relative_to(base)) if sf.is_relative_to(base) else str(sf)
        file_errors = 0

        try:
            text = sf.read_text(errors="replace")
        except OSError as e:
            findings.append(Finding(
                rule="READ_ERROR",
                severity="ERROR",
                message=f"Cannot read file: {e}",
                file=rel,
            ))
            continue

        # Check: not empty
        content_lines = [
            l for l in text.split("\n")
            if l.strip() and not l.strip().startswith("#")
        ]
        if len(content_lines) == 0:
            findings.append(Finding(
                rule="EMPTY_FILE",
                severity="ERROR",
                message="SDC file is empty or contains only comments",
                file=rel,
            ))
            file_errors += 1
            continue

        # Check: create_clock command exists
        if not CREATE_CLOCK_RE.search(text):
            findings.append(Finding(
                rule="NO_CREATE_CLOCK",
                severity="ERROR",
                message="No 'create_clock' command found",
                file=rel,
            ))
            file_errors += 1
        else:
            # Validate clock period values
            for m in CLOCK_PERIOD_RE.finditer(text):
                period_str = m.group(1)
                try:
                    period = float(period_str)
                    if period < MIN_PERIOD_NS or period > MAX_PERIOD_NS:
                        findings.append(Finding(
                            rule="BAD_CLOCK_PERIOD",
                            severity="ERROR",
                            message=f"Clock period {period}ns is outside reasonable range "
                                    f"({MIN_PERIOD_NS}ns - {MAX_PERIOD_NS}ns)",
                            file=rel,
                        ))
                        file_errors += 1
                    else:
                        freq_mhz = 1000.0 / period
                        findings.append(Finding(
                            rule="CLOCK_PERIOD_OK",
                            severity="INFO",
                            message=f"Clock period {period}ns ({freq_mhz:.1f} MHz)",
                            file=rel,
                        ))
                except ValueError:
                    # Period might be a variable/expression — not necessarily an error
                    findings.append(Finding(
                        rule="CLOCK_PERIOD_EXPR",
                        severity="WARNING",
                        message=f"Clock period is an expression '{period_str}', cannot validate statically",
                        file=rel,
                    ))

            # Check for create_clock without -period
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "create_clock" in stripped and "-period" not in stripped:
                    # create_clock without -period is invalid
                    findings.append(Finding(
                        rule="SYNTAX_ERROR",
                        severity="ERROR",
                        message="'create_clock' without '-period' flag",
                        file=rel,
                    ))
                    file_errors += 1

        # Check: at least 1 timing constraint
        timing_matches = TIMING_RE.findall(text)
        if not timing_matches:
            findings.append(Finding(
                rule="NO_TIMING_CONSTRAINT",
                severity="ERROR",
                message="No timing constraints found (set_input_delay, set_output_delay, "
                        "set_max_delay, set_false_path, set_multicycle_path)",
                file=rel,
            ))
            file_errors += 1
        else:
            unique_commands = set(timing_matches)
            findings.append(Finding(
                rule="TIMING_FOUND",
                severity="INFO",
                message=f"Found {len(timing_matches)} timing constraint(s): {sorted(unique_commands)}",
                file=rel,
            ))

        # Check: bracket matching
        bracket_issues = check_brackets(text)
        for lineno, desc in bracket_issues:
            findings.append(Finding(
                rule="SYNTAX_ERROR",
                severity="ERROR",
                message=f"Line {lineno}: {desc}",
                file=rel,
            ))
            file_errors += 1

        if file_errors == 0:
            valid_files += 1

    observed = None
    if explicit:
        try:
            observed = hashlib.sha256(sdc_files[0].read_bytes()).hexdigest()
        except OSError:
            observed = None
        if observed != sdc_sha256:
            findings.append(Finding(
                rule="SDC_AUTHORITY_CHANGED", severity="ERROR",
                message="explicit SDC changed while syntax was checked",
                file=str(sdc_files[0]),
            ))
    # Preserve the historical default-discovery contract: one valid deck is
    # sufficient even when another discovered deck is invalid. D20's explicit
    # one-deck override is stricter because every ERROR is about that authority.
    passed = valid_files > 0 and (not explicit or not any(
        f.severity == "ERROR" for f in findings))
    return AuditResult(
        program="sdc_syntax_check",
        passed=passed,
        findings=findings,
        summary={
            "files_checked": len(sdc_files),
            "valid_files": valid_files,
            "errors": sum(1 for f in findings if f.severity == "ERROR"),
            "clocks_found": sum(1 for f in findings if f.rule == "CLOCK_PERIOD_OK"),
            "sdc_files_checked": [str(p) for p in sdc_files],
            "sdc_sha256_expected": sdc_sha256 if explicit else None,
            "sdc_sha256_observed": observed if explicit else None,
        },
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Deterministic compliance check for constraint-gen"
    )
    p.add_argument("project_dir", nargs="?", default=".")
    p.add_argument("--json", nargs="?", const="-", default=None,
                   help="Emit JSON. With no value → stdout. With a path → write file.")
    args = p.parse_args()

    result = audit(args.project_dir)

    if args.json is not None:
        # R-0915-152 -- the document states WHO INVOKED this writer, beside the verdict it
        # already composes. Unstated role == producer, so the run's own path is unchanged.
        payload = json.dumps(_ga.stamp(asdict(result)), indent=2,
                             ensure_ascii=False)
        if args.json == "-":
            print(payload)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(_P(args.json), payload)
    else:
        for f in result.findings:
            tag = f"[{f.file}] " if f.file else ""
            print(f"[{f.severity}] {f.rule}: {tag}{f.message}")
        status = "PASS" if result.passed else "FAIL"
        print(f"\n{status} — {result.summary}")

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
