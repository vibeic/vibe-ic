#!/usr/bin/env python3
"""crc_compute_done_before_tx_start_check.py — v0.119.44 (Wave 12) plugin gate.

When a CRC module exposes a ``done`` / ``valid`` / ``ready`` strobe and
some FSM transitions to a TX-ish state, the gate insists the transition
actually waits on that strobe. Otherwise the FSM may start serializing
the response while the CRC byte is still 'X' or stale, sending a wrong
trailer byte that the host then rejects (the v0.119.43 <benchmark> RESULT.md
flagged exactly this race as one of three suspected root causes).

CHIP-AGNOSTIC. The gate looks at:
- module names containing ``crc`` OR exposing ports named
  ``crc_out`` / ``crc_done`` / ``crc_valid`` / ``crc_ready``;
- the existence of a ``done``/``valid``/``ready`` output strobe on
  that module;
- FSM transitions in OTHER modules whose next-state name suggests TX:
  ``ST_TX*`` / ``*_SEND_*`` / ``*DRIVE*`` / ``*RESP*`` / ``*XMIT*``.

Detection
---------
1. Identify the CRC module(s) and their done/valid/ready output ports.
2. For each non-CRC RTL file, look at every line of the form
   ``state <= NEXT_STATE`` (or ``case <= NEXT_STATE``) where
   NEXT_STATE matches the TX-state heuristic.
3. Walk back to the surrounding ``if (...)`` / ``case`` arm condition;
   FAIL when the condition does NOT reference any of the CRC done
   strobes (or a synonym such as ``*_done`` / ``*_valid`` / ``*_ready``
   whose root contains ``crc``).
4. WARN if no FSM next-state names match the TX heuristic — possibly
   gate not applicable (silent-skip).
5. SKIP (exit 0) if no CRC module is found.
6. SKIP if CRC module has no done/valid/ready output strobe (silent;
   another gate covers fixed-cycle CRC compute timing).
7. Honors waiver ``crc_done_unnecessary_for_tx_timing`` (>= 40 chars).

Usage
-----
    python3 crc_compute_done_before_tx_start_check.py <project_dir>
        [--rtl-dir <path>] [--json <out>]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER / WARN-only
    1 — FAIL
    2 — input-missing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from gate_utils import find_modules, find_rtl_files, read_text, parse_io_ports
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gate_utils import (  # type: ignore
        find_modules, find_rtl_files, read_text, parse_io_ports,
    )


WAIVER_KEY = "crc_done_unnecessary_for_tx_timing"
WAIVER_MIN = 40

CRC_PORT_HINTS = ("crc_out", "crc_done", "crc_valid", "crc_ready",
                  "crc_dout", "crc_result")
DONE_PORT_HINTS = ("done", "valid", "ready", "ack")
TX_STATE_RE = re.compile(
    r"\b(?:ST_)?[A-Z0-9_]*"
    r"(?:TX|SEND|DRIVE|RESP|XMIT|TRANSMIT|EMIT|RESPOND)"
    r"[A-Z0-9_]*\b"
)


def _strip_comments_keep_lines(text: str) -> str:
    def _block(m):
        s = m.group(0)
        return "".join(c if c == "\n" else " " for c in s)
    text = re.sub(r"/\*.*?\*/", _block, text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), text)
    return text


def _find_crc_modules(project: Path) -> list[dict]:
    """Return list of {name, file, done_signals: list[str]}."""
    out: list[dict] = []
    for f in find_rtl_files(project):
        text = read_text(f)
        for span in find_modules(text):
            name = span.name
            inputs, outputs, _ = parse_io_ports(span.header)
            ports = inputs | outputs
            looks_like_crc = (
                "crc" in name.lower()
                or any(h in p.lower() for h in CRC_PORT_HINTS for p in ports)
            )
            if not looks_like_crc:
                continue
            done_signals: list[str] = []
            for p in outputs:
                lower = p.lower()
                if any(lower.endswith("_" + h) or lower == h
                       for h in DONE_PORT_HINTS):
                    done_signals.append(p)
            out.append({
                "name": name,
                "file": str(f),
                "done_signals": done_signals,
                "all_outputs": sorted(outputs),
            })
    return out


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _find_tx_transitions(body: str, file_path: str,
                         module_name: str) -> list[dict]:
    """Return list of {next_state, line, condition_text} for any
    NBA assignment to a state-like variable whose RHS matches the TX
    heuristic."""
    out: list[dict] = []
    # Heuristic: <var> <= STATE_NAME where var contains 'state'/'st_'
    # OR the RHS is a CAPS_NAME matching the TX regex.
    pat = re.compile(
        r"(\w+)\s*<=\s*([A-Z][A-Z0-9_]+)\s*;",
    )
    for m in pat.finditer(body):
        lhs = m.group(1)
        rhs = m.group(2)
        if "state" not in lhs.lower() and not lhs.lower().startswith("st"):
            continue
        if not TX_STATE_RE.fullmatch(rhs):
            continue
        # Look back up to 400 chars for an `if (...)` / `case (...)` arm.
        ctx_start = max(0, m.start() - 400)
        ctx = body[ctx_start:m.start()]
        # Strip nested ifs — get the innermost open `if (` or `case (` arm.
        # Simple approach: walk backward, depth-balance parens.
        cond_text = _extract_innermost_condition(ctx)
        out.append({
            "lhs": lhs,
            "next_state": rhs,
            "line": _line_of(body, m.start()),
            "condition_text": cond_text,
            "file": file_path,
            "module": module_name,
        })
    return out


def _extract_innermost_condition(ctx: str) -> str:
    """Best-effort: return the text inside the most recent `if(...)` /
    `else if(...)` / case-arm trigger BEFORE the assignment. Empty
    string when no condition found (= unconditional transition)."""
    # Collect candidates: scan from right; any `if` / `else if` whose
    # paren block hasn't been closed back at our position is the
    # enclosing condition.
    matches = list(re.finditer(r"\b(if|else\s+if|case)\s*\(", ctx))
    if not matches:
        # Could be a case-arm: ``LABEL : <stmt>``; treat as no condition.
        return ""
    # Take last `if` / `else if` and try to extract its parenthesised
    # condition. We need to balance parens forward from its open paren.
    last = matches[-1]
    open_idx = last.end() - 1  # position of '('
    depth = 0
    j = open_idx
    while j < len(ctx):
        c = ctx[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return ctx[open_idx + 1:j]
        j += 1
    # Unbalanced — return what we have
    return ctx[open_idx + 1:]


def waived(project_dir: Path) -> tuple[bool, str]:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
        text = d.get(WAIVER_KEY)
        if isinstance(text, str) and len(text.strip()) >= WAIVER_MIN:
            return True, text.strip()
    except Exception:
        pass
    return False, ""


def check(project: Path) -> dict:
    crc_modules = _find_crc_modules(project)
    info: dict = {
        "crc_modules": crc_modules,
    }

    if not crc_modules:
        return {
            "program": "crc_compute_done_before_tx_start_check",
            "skip_reason": "no CRC module found",
            "pass": True,
            "findings": [],
            "warnings": [],
            **info,
        }

    # Collect all done strobes across CRC modules
    done_signal_set: set[str] = set()
    for cm in crc_modules:
        for s in cm["done_signals"]:
            done_signal_set.add(s.lower())
    # Also accept any signal name containing both 'crc' and one of
    # done/valid/ready as a wire-level synonym in caller modules.
    if not done_signal_set:
        return {
            "program": "crc_compute_done_before_tx_start_check",
            "skip_reason": (
                "CRC module(s) found but none expose a done/valid/ready/"
                "ack output port; fixed-cycle CRC timing is not "
                "covered by this gate"
            ),
            "pass": True,
            "findings": [],
            "warnings": [],
            **info,
        }

    # Walk other RTL files, find FSM TX transitions.
    findings: list[dict] = []
    warnings: list[dict] = []
    saw_any_tx_transition = False

    crc_files = {cm["file"] for cm in crc_modules}
    for f in find_rtl_files(project):
        if str(f) in crc_files:
            continue
        text = read_text(f)
        clean = _strip_comments_keep_lines(text)
        for span in find_modules(clean):
            transitions = _find_tx_transitions(
                span.body, str(f), span.name,
            )
            for t in transitions:
                saw_any_tx_transition = True
                cond_lower = t["condition_text"].lower()
                # PASS if condition references any known done strobe or
                # any wire whose name has 'crc' AND a done synonym.
                ref_done = any(
                    ds in cond_lower for ds in done_signal_set
                )
                if not ref_done:
                    # Check `crc_*_done` / `crc_*_valid` synonyms
                    if re.search(
                        r"\bcrc\w*_(?:done|valid|ready|ack)\b",
                        cond_lower,
                    ):
                        ref_done = True
                if ref_done:
                    continue
                findings.append({
                    "rule": "CRC_DONE_NOT_IN_TX_TRANSITION",
                    "severity": "FAIL",
                    "module": t["module"],
                    "file": t["file"],
                    "line": _line_of(text, text.find(
                        f"<= {t['next_state']}")) if (
                        f"<= {t['next_state']}" in text
                    ) else t["line"],
                    "next_state": t["next_state"],
                    "condition": t["condition_text"][:160],
                    "message": (
                        f"FSM transitions to TX state `{t['next_state']}` "
                        f"in module `{t['module']}`; condition "
                        f"`{t['condition_text'].strip()[:80]}` does not "
                        f"reference any CRC done strobe ({sorted(done_signal_set)}). "
                        f"Starting TX before CRC is computed will emit "
                        f"a stale or X CRC byte. Gate the transition "
                        f"on `crc_done` (or equivalent)."
                    ),
                })

    if not saw_any_tx_transition:
        warnings.append({
            "rule": "NO_TX_STATES_DETECTED",
            "severity": "WARN",
            "message": (
                "no FSM next-state name matched the TX heuristic "
                "(*TX*/*SEND*/*DRIVE*/*RESP*/*XMIT*); CRC-done-before-TX "
                "could not be evaluated. Confirm the FSM uses a "
                "recognisable TX state name or document via waiver."
            ),
        })

    return {
        "program": "crc_compute_done_before_tx_start_check",
        "pass": len(findings) == 0,
        "findings": findings,
        "warnings": warnings,
        "tx_transitions_seen": saw_any_tx_transition,
        "done_signals_known": sorted(done_signal_set),
        **info,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--rtl-dir", default=None,
                    help="(reserved; rtl/ is autodiscovered)")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}", file=sys.stderr)
        return 2

    result = check(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    if "skip_reason" in result:
        print(f"PASS_SKIP — {result['skip_reason']}")
        return 0

    if result["pass"]:
        if result["warnings"]:
            print(
                f"PASS_WITH_WARN — no CRC-done-vs-TX violations; "
                f"{len(result['warnings'])} warning(s)"
            )
            for w in result["warnings"]:
                print(f"WARN: {w['rule']} — {w['message']}")
        else:
            print(
                f"PASS — every FSM TX-state transition gates on CRC "
                f"done strobe ({result['done_signals_known']})"
            )
        return 0

    is_waived, why = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(result['findings'])} CRC-done-"
            f"before-TX finding(s); waiver `{WAIVER_KEY}` set: "
            f"{why[:80]}..."
        )
        for f in result["findings"]:
            print(f"  • {f['file']}:{f['line']} → {f['next_state']} "
                  f"({f['rule']})")
        return 0

    print(
        f"FAIL — {len(result['findings'])} TX-state transition(s) "
        f"do not gate on CRC done strobe"
    )
    for f in result["findings"]:
        print(f"FAIL: {f['rule']} at {f['file']}:{f['line']} — {f['message']}")
    for w in result.get("warnings", []):
        print(f"WARN: {w['rule']} — {w['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
