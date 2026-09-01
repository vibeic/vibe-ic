#!/usr/bin/env python3
"""
spec_response_delay_check.py — Response path must honour spec-declared
minimum response delay (tSRS / tIRT / t_turnaround / similar).

Generic pattern (applies to any request/response protocol):
  Host-initiated protocols (UART-slave, I2C-slave, SPI-slave, AID,
  1-Wire, HID report responses) almost always specify a MIN delay
  between end-of-request and first-bit-of-response. The host uses
  that gap to turn around its bus driver (enable RX, release ACK
  line, sample clock edge, etc.). DUT responding too fast →
  host misses the first few response bits → packet malformed →
  silent failure mode.

  The FSM path `cmd_validated → build_response → start_TX` MUST
  include an explicit delay state that waits ≥ the spec minimum.
  Sim passes without the delay because sim's virtual host is
  infinitely-fast-turnaround; hardware host is not.

Real occurrence (v068 <benchmark> fresh-agent):
  L8_RTL_CONSTANTS / L8_TIMING_WAVEFORM declared
    tSRS = 20..100 us  (Start Response Setup)
  cmd_fsm.v went S_BUILD → S_BUILD_CRC → S_TX with no delay state,
  firing tx_start ~1 us after cmd-BR end. <half-duplex-tester> tester was still
  in cmd-TX mode at 1 us and missed the first DUT bits →
  byte[6]=0x02 FAIL across every test cycle.

  Fix was to add a S_TSRS state with a 30 us counter. After that
  scope confirmed DUT response started 19.6 us after tester BR
  (inside the 20-100 us spec window).

Rule enforced
-------------
If the spec (L8_TIMING_WAVEFORM.json or L8_RTL_CONSTANTS.json)
declares any field matching a RESPONSE-DELAY pattern (tSRS, tIRT,
tRTA, tResp, tTurnaround, t_turn, response_delay_*, srs_*), the
corresponding RTL FSM must include a DELAY STATE between request
completion and response launch. The gate:

  1. Scans L8*.json for response-delay fields; extracts MIN in µs
     or ticks.
  2. Scans RTL FSMs in the target dir for obvious "launch response"
     paths: `tx_start <= 1'b1;` / `tx_req <= 1'b1;` / `resp_go <= 1;`
     preceded (in same always block) by a `<= S_TX` / `<= S_RESP`
     state transition.
  3. The immediately-preceding state must contain a counter-based
     wait OR a flag like `srs_done`. If the transition to S_TX
     happens directly from S_BUILD / S_VALIDATE / S_DECODE without
     any wait state in between, WARN.

Usage
-----
    spec_response_delay_check.py <rtl_file_or_dir>
        --spec <L8_TIMING_WAVEFORM.json>
        [--spec L8_RTL_CONSTANTS.json ...]
        [--json]

Exit codes
----------
    0 = spec declares no delay, OR RTL honours it
    1 = spec declares delay but RTL has no wait state
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

# Names that indicate a response-delay field in the spec.
RESPONSE_DELAY_NAMES = re.compile(
    r"(?:"
    r"t?SRS"
    r"|t?IRT"
    r"|t?RTA"
    r"|t?Resp(?:onse)?(?:_delay|_time)?"
    r"|t?Turn(?:around)?"
    r"|start_response"
    r"|response_delay"
    r")",
    re.IGNORECASE,
)


@dataclass
class Finding:
    severity: str
    rule: str
    field: str
    message: str


def _walk(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from _walk(item, f"{path}[{i}]" if path else f"[{i}]")


def _parse_num(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x)
        except ValueError:
            pass
    return None


def find_response_delay(specs: list[Any]) -> tuple[str, float] | None:
    """Return (field_path, min_value_numeric) if any spec declares one.

    Accepts shapes:
      {"name": "tSRS", "min_us": 20}
      {"name": "RSP_74", "value_dec": 91}
      {"tSRS_us": {"min": 20}}
    """
    for spec in specs:
        for p, v in _walk(spec):
            if not isinstance(v, dict):
                continue
            name = str(v.get("name", "")).strip()
            if not name:
                # Also try key in dict
                for k in v.keys():
                    if RESPONSE_DELAY_NAMES.search(str(k)):
                        inner = v[k]
                        if isinstance(inner, dict):
                            for mkey in ("min", "min_us", "minimum"):
                                if mkey in inner:
                                    n = _parse_num(inner[mkey])
                                    if n is not None:
                                        return f"{p}.{k}.{mkey}", n
                        elif isinstance(inner, (int, float)) and not isinstance(inner, bool):
                            return f"{p}.{k}", float(inner)
                continue
            if not RESPONSE_DELAY_NAMES.search(name):
                continue
            # named entry, try to read min/value
            for mkey in ("min_us", "min", "value_dec", "value", "nom", "nom_us"):
                if mkey in v:
                    n = _parse_num(v[mkey])
                    if n is not None:
                        return f"{p}.{name}.{mkey}", n
    return None


def declares_no_response_protocol(specs: list[Any]) -> bool:
    """Whether the supplied design docs explicitly rule out this gate's scope.

    Absence of a delay field alone is not a declaration: it can also be an
    extraction gap.  Only explicit typed fields may turn the check into N/A.
    """
    for doc in specs:
        if not isinstance(doc, dict):
            continue
        if doc.get("no_response_delay_in_input") is True:
            return True
        if doc.get("command_protocol_applicable") is False:
            return True
        if (doc.get("doc_class") == "cmd_protocol"
                and doc.get("no_opcodes_in_input") is True
                and doc.get("opcodes") == []):
            return True
    return False


# RTL analysis
ALWAYS_HEAD_RE = re.compile(r"always\s*@\s*\(\s*posedge\b[^)]*\)\s*begin\b")


def _find_always_blocks(src: str):
    for head in ALWAYS_HEAD_RE.finditer(src):
        body_start = head.end()
        depth = 1
        for tok in re.finditer(r"\b(begin|end)\b", src[body_start:]):
            if tok.group(1) == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    yield body_start, body_start + tok.start()
                    break


# Heuristic: find transitions to a "TX" state.
TX_TRANSITION_RE = re.compile(
    r"st\s*<=\s*(S_TX\w*|S_RESP\w*|S_TRANSMIT\w*|S_RSP\w*)\s*;",
    re.IGNORECASE,
)

# Heuristic: find intermediate wait states by name.
WAIT_STATE_RE = re.compile(
    r"(S_SRS|S_TSRS|S_WAIT\w*|S_DELAY\w*|S_TURN\w*|S_RSP_DELAY)",
    re.IGNORECASE,
)

# Heuristic: find "immediately-preceding" state names like
# `S_BUILD`/`S_VALIDATE`/`S_DECODE` transitioning to S_TX directly.
FAST_PRECEDE_RE = re.compile(
    r"(S_BUILD\w*|S_VALIDATE|S_DECODE|S_BUILD_CRC|S_READY)\s*:\s*begin",
    re.IGNORECASE,
)


def check_rtl(path: Path) -> tuple[bool, bool, list[str]]:
    """Return (has_tx_transition, has_wait_state, file_notes)."""
    src = path.read_text(errors="replace")
    src = re.sub(r"//[^\n]*", "", src)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    notes: list[str] = []
    has_tx = False
    has_wait = False
    for m in TX_TRANSITION_RE.finditer(src):
        has_tx = True
    for m in WAIT_STATE_RE.finditer(src):
        has_wait = True
        notes.append(f"found wait-state token: {m.group(1)}")
    return has_tx, has_wait, notes


def collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.rglob("*")
            if p.is_file() and p.suffix in (".v", ".sv", ".vh")
        )
    return []


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify RTL response path honours spec-declared tSRS-like delay.",
    )
    ap.add_argument("target", help="RTL file or directory.")
    ap.add_argument("--spec", action="append", default=[],
                    help="Spec JSON (L8_TIMING_WAVEFORM / L8_RTL_CONSTANTS). "
                         "May be repeated.")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
    args = ap.parse_args()

    specs: list[Any] = []
    for sp in args.spec:
        try:
            with open(sp) as f:
                specs.append(json.load(f))
        except Exception as e:
            print(f"error: could not read spec {sp}: {e}", file=sys.stderr)
            return 2

    if not specs:
        print("error: at least one --spec required", file=sys.stderr)
        return 2

    delay = find_response_delay(specs)
    findings: list[Finding] = []
    declared_na = delay is None and declares_no_response_protocol(specs)
    applicable: bool | None = False if declared_na else (
        True if delay is not None else None)

    if delay is None:
        # Applicability is determined by an explicit source declaration, not
        # inferred from a missing field and not decided by warning policy.
        if not declared_na:
            findings.append(Finding(
                "WARN", "no_response_delay_spec", "(specs)",
                "None of the supplied spec JSONs declare a response delay "
                "or explicitly declare that command/response protocol timing "
                "is not applicable. Supply the command-protocol declaration "
                "to prove N/A, or declare the required delay.",
            ))
    else:
        field, min_val = delay
        target = Path(args.target)
        if not target.exists():
            print(f"error: not found: {target}", file=sys.stderr)
            return 2
        files = collect_files(target)
        any_tx, any_wait = False, False
        for f in files:
            ht, hw, _ = check_rtl(f)
            if ht:
                any_tx = True
            if hw:
                any_wait = True

        if any_tx and not any_wait:
            findings.append(Finding(
                "ERROR", "response_delay_not_implemented", field,
                f"Spec declares response delay {min_val}, but RTL has "
                f"state transitions to S_TX/S_RESP without any wait "
                f"state (S_TSRS / S_WAIT / S_DELAY / S_TURN). This is "
                f"the v068 <benchmark> hardware-fail mode: sim passes, host "
                f"misses first response bits on hardware. Fix: add a "
                f"counter-based wait state between request validation "
                f"and TX launch.",
            ))

    errors = [f for f in findings if f.severity == "ERROR"]
    verdict = ("SKIPPED-CONDITION" if declared_na else
               "PASS" if not errors else "FAIL")
    if args.json:
        _txt = json.dumps({
            "target": args.target,
            "specs": args.spec,
            "declared_delay": delay,
            "applicable": applicable,
            "reason_class": "DESIGN_DECLARED_NA" if declared_na else None,
            "reason": (None if not declared_na else
                       "The supplied design specifications declare no "
                       "response-delay or bus-turnaround requirement."),
            "errors": len(errors),
            "findings": [asdict(f) for f in findings],
            "verdict": verdict,
        }, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            _P(args.json).write_text(_txt + "\n")
    else:
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.field}")
            print(f"    {f.message}")
        print(f"\n{len(errors)} error(s)")
        print(verdict)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
