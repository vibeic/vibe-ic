#!/usr/bin/env python3
"""break_handler_safety_check.py — Verify that FSM break/reset handlers do NOT
fire during active response-processing states.

THE PROBLEM
-----------
In half-duplex protocols, the device's own TX break appears on the shared bus.
If the MAC FSM has a global break handler (``if (rx_break) state <= IDLE;``
in a ``default:`` clause or outside per-state logic), it fires during TX,
OTP_RD, CMD_PROC, etc. — aborting the response before it's finished.

The v0.108 <chip-class> run had exactly this: mac.v's catch-all break handler reset
state to IDLE during MS_CMD_PROC and MS_TX, truncating every response.

HEURISTIC
---------
1. For each ``.v`` file, find FSM case statements.
2. Identify "active-processing" state names by pattern:
   ``*TX*``, ``*SEND*``, ``*CMD_PROC*``, ``*OTP_RD*``, ``*OTP_WR*``,
   ``*BUILD*``, ``*RESP*``, ``*XMIT*``, ``*WRITE*``.
3. Find break handlers: ``state <= <idle>`` conditioned on a break signal
   (``rx_break``, ``brk``, ``break_detect``).
4. If the break handler is in a ``default:`` clause, or at the top level
   of the ``always`` block (outside the case), it fires in ALL states
   including active ones → FAIL.
5. If it's inside only safe states (IDLE, UNMATED, WAIT_BR) → PASS.

USAGE
-----
    python3 break_handler_safety_check.py <rtl_dir> [--json report.json]

EXIT CODES
----------
    0 — PASS: break handlers were examined and are properly guarded
    1 — FAIL (unsafe break handler)
    2 — VACUOUS: nothing was examined — no RTL at all, or no break signals,
        so this design is not a break-based protocol and the gate does not
        apply to it. #515: this used to be rc 0, which credited the gate in
        the plain PASS tier for designs it had never looked at.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_utils import dir_parts_excluded  # shared RTL-scope contract
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
    program: str = "break_handler_safety_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


BREAK_SIG_RE = re.compile(r"\b(rx_break|brk|break_detect|break_seen|got_break)\b", re.I)
ACTIVE_STATE_RE = re.compile(
    r"\b\w*(?:TX|SEND|CMD_PROC|OTP_RD|OTP_WR|BUILD|RESP|XMIT|WRITE)\w*\b", re.I
)
IDLE_RESET_RE = re.compile(
    r"\b(\w+)\s*<=\s*(\w*(?:IDLE|UNMATED|WAIT_BR|RESET|INIT)\w*)\b", re.I
)


def collect_files(rtl_dir: Path) -> List[Path]:
    """The RTL files this gate examines. A NAMED function, not an inline
    comprehension inside `audit`, so a test can drive THE REAL collector.

    Skip the flow's own build/output trees. This was a bare rglob with no
    exclusion; given a PROJECT directory — how the phase-2 umbrella invokes
    it — it read every emitted netlist in the tree. MEASURED on
    edge_llm_accel x nangate45: 39.14 s / 1.03 GB RSS, and a TIMEOUT under
    the umbrella's per-gate budget that FAILed phase 2 before PnR.

    Exclusion is delegated to the shared `gate_utils.dir_parts_excluded`, not
    to a private `& EXCLUDED_DIRS` — this collector was the FOURTH one, and
    importing only the NAME SET meant it silently missed the suffix rule when
    one was added. Measured on a project with an out-of-cone sidecar: the other
    three collectors saw `design.v`, this one also read the moved-aside
    `orphan.v` and reported a finding against a file the flow does not compile
    (vibe-ic#781 M1). There is exactly one policy function; four call sites.

    The regression test for that defect had re-implemented this comprehension
    inline with the raw name set, so it asserted on a COPY of the collector and
    could never have caught the drift it was written to catch."""
    if not rtl_dir.is_dir():
        return []
    return sorted(
        p for p in list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv"))
        if not dir_parts_excluded(p.relative_to(rtl_dir).parts[:-1]))


def audit(rtl_dir: Path) -> AuditResult:
    result = AuditResult()
    if not rtl_dir.is_dir():
        result.summary = {"skipped": True, "reason": "not_a_directory"}
        return result

    files = collect_files(rtl_dir)
    if not files:
        result.summary = {"skipped": True, "reason": "no_rtl_files"}
        return result
    # WHAT WAS ACTUALLY READ — recorded on every exit path, including the
    # self-skip ones, so "did this gate open a file it should not have?" is
    # answerable from the result instead of only from a stopwatch.
    scanned = sorted(p.name for p in files)

    has_break = False
    for f in files:
        try:
            txt = f.read_text(errors="replace")
        except OSError:
            continue
        if BREAK_SIG_RE.search(txt):
            has_break = True
            break

    if not has_break:
        result.summary = {"skipped": True, "reason": "no_break_signals",
                          "files_scanned": scanned}
        result.findings.append(Finding(
            "SKIP", "INFO", "No break signals detected — not a break-based protocol.",
        ))
        return result

    result.summary = {"skipped": False, "files_checked": [],
                      "files_scanned": scanned}

    for f in files:
        try:
            raw = f.read_text(errors="replace")
        except OSError:
            continue
        text = _strip_comments(raw)

        if not BREAK_SIG_RE.search(text):
            continue

        result.summary["files_checked"].append(str(f.name))
        lines = text.splitlines()

        case_depth = 0
        in_default = False
        current_state_label = ""

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            if re.match(r"\bcase\s*\(", stripped):
                case_depth += 1
                in_default = False
                current_state_label = ""
                continue

            if stripped.startswith("endcase"):
                case_depth -= 1
                in_default = False
                current_state_label = ""
                continue

            if case_depth > 0:
                state_match = re.match(r"(\w+)\s*:", stripped)
                if state_match and not stripped.startswith("default"):
                    current_state_label = state_match.group(1)
                    in_default = False
                elif stripped.startswith("default"):
                    in_default = True
                    current_state_label = "default"

            if BREAK_SIG_RE.search(line) and IDLE_RESET_RE.search(line):
                if case_depth == 0:
                    result.passed = False
                    result.findings.append(Finding(
                        "GLOBAL_BREAK_HANDLER", "ERROR",
                        f"Break handler transitions to idle OUTSIDE case statement "
                        f"— fires in ALL states including active processing. "
                        f"Move into per-state logic or guard with state check.",
                        file=str(f.name), line=i,
                    ))
                elif in_default:
                    result.passed = False
                    result.findings.append(Finding(
                        "DEFAULT_BREAK_HANDLER", "ERROR",
                        f"Break handler in ``default:`` clause fires during "
                        f"active-processing states (TX, CMD_PROC, OTP_RD, etc.). "
                        f"Move to IDLE/UNMATED states only, or exclude active states.",
                        file=str(f.name), line=i,
                    ))
                elif current_state_label and ACTIVE_STATE_RE.match(current_state_label):
                    result.passed = False
                    result.findings.append(Finding(
                        "ACTIVE_STATE_BREAK_HANDLER", "ERROR",
                        f"Break handler in active state ``{current_state_label}`` "
                        f"will abort response processing. Remove or guard with "
                        f"``if (state == IDLE)``.",
                        file=str(f.name), line=i,
                    ))

    if result.passed:
        result.findings.append(Finding(
            "PASS", "INFO", "Break handlers are properly guarded against active states.",
        ))

    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("rtl_dir", help="RTL directory to scan")
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH")
    args = ap.parse_args(argv)

    target = Path(args.rtl_dir)
    if not target.exists():
        print(f"error: not found: {target}", file=sys.stderr)
        return _vx.RC_VACUOUS

    result = audit(target)
    report = {
        "program": result.program,
        "passed": result.passed,
        "findings": [asdict(f) for f in result.findings],
        "summary": result.summary,
    }

    if args.json:
        txt = json.dumps(report, indent=2)
        if args.json == "-":
            print(txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(Path(args.json), txt + "\n")
    else:
        for f in result.findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        errors = [f for f in result.findings if f.severity == "ERROR"]
        verdict = ("FAIL" if errors
                   else "VACUOUS (nothing examined)"
                   if _vx.summary_is_skipped(result.summary) else "PASS")
        print(f"\n{len(errors)} error(s); verdict: {verdict}")

    # #515 — the exit code is routed from the gate's OWN structured
    # conclusion (`summary["skipped"]`), never from the text above. Three of
    # this gate's four outcomes were vacuous: no RTL directory, no RTL files,
    # and no break signals anywhere. All three used to exit 0 and be counted
    # as a real pass; two of them printed nothing at all, so the whole of the
    # gate's output was the line `0 error(s); verdict: PASS`.
    skipped = _vx.summary_is_skipped(result.summary)
    if result.passed and skipped:
        _vx.announce_vacuous(result.program,
                             str(result.summary.get("reason", "unspecified")))
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
