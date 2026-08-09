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
  2. Scans RTL FSMs in the target dir for the RESPONSE LAUNCH — a
     state assignment whose right-hand side is a response/transmit
     state symbol (`S_TX*`, `S_RESP*`, `S_RSP*`, `S_TRANSMIT*`),
     written with either `<=` (one-process FSM) or `=` (the
     next-state block of a two-process FSM), whatever the state
     register happens to be called.  Hops that ORIGINATE inside the
     TX cluster (`S_TX_LOAD -> S_TX_ARM`) are pipeline steps, not
     launches, and are ignored.
  3. Each launch must be DELAY-GUARDED: it is launched from a state
     whose name says "wait" (S_TSRS / S_WAIT* / S_TURNAROUND /
     S_DELAY* / ...), or its case arm holds a counter / elapsed-flag
     (`turnaround_cnt >= T_TSRS_MIN_TICKS`, `srs_done`), or the
     module declares a delay state at all, or the module references
     the spec's own delay parameter by name.  A launch with none of
     that is the fail mode below and is reported as an ERROR.

Reachability note (this is what this file was repaired for)
-----------------------------------------------------------
Step 2 used to be the single regex

    r"st\\s*<=\\s*(S_TX\\w*|S_RESP\\w*|S_TRANSMIT\\w*|S_RSP\\w*)\\s*;"

which only matches when the state register is literally spelled `st`
(or ends in those two letters right before the `<=`).  Every FSM this
flow produces writes `state <= S_TX_LOAD;`, and two-process FSMs write
`next_state = S_TX;`; neither matches.  So on the target the flow
actually passes — `phase2/stage1/rtl` — `has_tx_transition` was always
False, the one ERROR-emitting branch was dead, and this gate could only
ever print `verdict: PASS` / exit 0.  The predicate is now keyed on the
right-hand side (a state symbol) instead of on the spelling of the
left-hand register.

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
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x)
        except ValueError:
            pass
    return None


#: Unit / bound suffixes stripped when turning a spec field name into the
#: token the RTL would use for the same parameter (`tSRS_us` -> `SRS`).
_UNIT_SUFFIX_RE = re.compile(
    r"_(?:us|ns|ms|s|ticks?|cycles?|clks?|min|max|nom)$", re.IGNORECASE)


def spec_delay_token(field: str) -> str:
    """Core RTL-searchable token for the spec field `find_response_delay` hit.

    ``timing_parameters.tSRS_us.min`` -> ``SRS``.  Returned empty when the
    residue is too short to search for without matching noise.
    """
    parts = [p for p in str(field).split(".") if p]
    if len(parts) < 2:
        return ""
    name = parts[-2]
    prev = None
    while prev != name:
        prev = name
        name = _UNIT_SUFFIX_RE.sub("", name)
    if name[:2].lower() == "t_":
        name = name[2:]
    elif len(name) > 1 and name[0] == "t" and name[1].isupper():
        name = name[1:]
    return name if len(name) >= 3 else ""


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
                        elif isinstance(inner, (int, float)):
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


# ── RTL analysis ────────────────────────────────────────────────────
#
# Everything below is keyed on the RIGHT-hand side of a state assignment.
# The old predicate was keyed on the left-hand register being spelled
# `st`, which no FSM the flow produces satisfies (see the reachability
# note in the module docstring).

IDENT_RE = re.compile(r"[A-Za-z_]\w*")
IDENT_ONLY_RE = re.compile(r"^[A-Za-z_]\w*$")

#: A state symbol that belongs to the response / transmit cluster.
#: Tolerates the `S_` / `ST_` / `STATE_` / bare naming conventions.
TX_STATE_NAME = re.compile(
    r"^(?:S|ST|STATE)?_?(?:TX|RESP|RSP|TRANSMIT)\w*$", re.IGNORECASE)

#: A state symbol whose name declares it to be a deliberate wait.
DELAY_STATE_NAME = re.compile(
    r"(?:SRS|TURN|DELAY|DLY|WAIT|GUARD|HOLDOFF|GAP|IFS|PAUSE|SETTLE)",
    re.IGNORECASE)

#: Any identifier carrying wait / turnaround / counter semantics — the
#: evidence that a launch is held off rather than fired immediately.
DELAY_EVIDENCE_NAME = re.compile(
    r"^\w*(?:srs|turn|delay|dly|wait|guard|holdoff|gap|ifs|pause|settle"
    r"|cnt|count|counter|timer|tick|elapsed|expire)\w*$", re.IGNORECASE)

#: `<state_reg> <= S_TX;` and `<next_state> = S_TX;` alike.
STATE_ASSIGN_RE = re.compile(
    r"\b([A-Za-z_]\w*)\s*(?:<=|=)\s*([A-Za-z_]\w*)\s*;")

#: A case-arm label: an identifier or a sized/plain literal before `:`.
CASE_LABEL_RE = re.compile(
    r"(?:^|[\s;\)\}])"
    r"((?:[A-Za-z_]\w*)"
    r"|(?:\d+\s*'\s*[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_]+)"
    r"|(?:\d+))"
    r"\s*:(?!:|=)",
    re.MULTILINE)

ENUM_BLOCK_RE = re.compile(r"\benum\b[^{}]*\{([^{}]*)\}", re.DOTALL)
PARAM_STMT_RE = re.compile(r"\b(?:localparam|parameter)\b[^;]*;", re.DOTALL)


@dataclass
class Launch:
    """One transition INTO the response/transmit cluster."""
    from_state: str      # "" when no enclosing case label was found
    to_state: str
    guard: str           # "" == unguarded == the fail mode


def _strip_comments(src: str) -> str:
    src = re.sub(r"//[^\n]*", "", src)
    return re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)


def _state_symbols(src: str, labels: list[tuple[int, str]]) -> set[str]:
    """Identifiers this module uses as state constants."""
    syms = {lab for _p, lab in labels if IDENT_ONLY_RE.match(lab)}
    for blk in ENUM_BLOCK_RE.findall(src):
        syms.update(IDENT_RE.findall(blk))
    for stmt in PARAM_STMT_RE.findall(src):
        syms.update(re.findall(r"([A-Za-z_]\w*)\s*=", stmt))
    return syms


def _is_state_symbol(name: str, syms: set[str]) -> bool:
    return name in syms or bool(
        re.match(r"^(?:S|ST|STATE)_", name, re.IGNORECASE))


def analyse_rtl(src: str, spec_token: str = "") -> list[Launch]:
    """Every response launch in *src*, each marked guarded or not."""
    src = _strip_comments(src)
    labels = [(m.end(), m.group(1)) for m in CASE_LABEL_RE.finditer(src)]
    syms = _state_symbols(src, labels)

    # File-level evidence: a delay state is declared at all, or the RTL
    # names the spec's own delay parameter. Both are generous on purpose
    # — this gate must not redden RTL that does implement the hold-off
    # in a shape this parser cannot walk.
    file_delay_states = sorted({
        lab for _p, lab in labels
        if IDENT_ONLY_RE.match(lab) and DELAY_STATE_NAME.search(lab)})
    names_spec_param = bool(
        spec_token and re.search(re.escape(spec_token), src, re.IGNORECASE))

    launches: list[Launch] = []
    for m in STATE_ASSIGN_RE.finditer(src):
        to_state = m.group(2)
        if not TX_STATE_NAME.match(to_state):
            continue
        if not _is_state_symbol(to_state, syms):
            continue
        arm_start, from_state = 0, ""
        for pos, lab in labels:
            if pos <= m.start():
                arm_start, from_state = pos, lab
            else:
                break
        if (from_state and IDENT_ONLY_RE.match(from_state)
                and TX_STATE_NAME.match(from_state)):
            continue        # intra-TX pipeline hop, not a response launch
        arm = src[arm_start:m.start()]
        if from_state and DELAY_STATE_NAME.search(from_state):
            guard = f"launched from delay state {from_state}"
        elif any(DELAY_EVIDENCE_NAME.match(i) for i in IDENT_RE.findall(arm)):
            guard = "counter / elapsed-flag wait on the launch path"
        elif file_delay_states:
            guard = f"module declares delay state(s) {','.join(file_delay_states)}"
        elif names_spec_param:
            guard = f"module references spec delay parameter '{spec_token}'"
        else:
            guard = ""
        launches.append(Launch(from_state, to_state, guard))
    return launches


def check_rtl(path: Path, spec_token: str = "") -> tuple[bool, bool, list[str]]:
    """Return (has_response_launch, every_launch_delayed, file_notes)."""
    launches = analyse_rtl(path.read_text(errors="replace"), spec_token)
    notes = [
        (f"UNGUARDED launch {ln.from_state or '<no case label>'} -> "
         f"{ln.to_state}") if not ln.guard else
        (f"guarded launch {ln.from_state or '<no case label>'} -> "
         f"{ln.to_state} ({ln.guard})")
        for ln in launches
    ]
    return bool(launches), all(ln.guard for ln in launches), notes


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
    launch_notes: list[str] = []
    any_launch = False

    if delay is None:
        findings.append(Finding(
            "WARN", "no_response_delay_spec", "(specs)",
            "None of the supplied spec JSONs declare a response delay "
            "(tSRS / tIRT / tResponse / t_turnaround / response_delay_*). "
            "If this protocol has host-to-DUT bus turnaround, the spec "
            "should declare the minimum delay and RTL should honour it. "
            "Otherwise this gate is a no-op for this IC.",
        ))
    else:
        field, min_val = delay
        spec_token = spec_delay_token(field)
        target = Path(args.target)
        if not target.exists():
            print(f"error: not found: {target}", file=sys.stderr)
            return 2
        files = collect_files(target)
        for f in files:
            has_launch, all_delayed, notes = check_rtl(f, spec_token)
            launch_notes.extend(f"{f}: {n}" for n in notes)
            if not has_launch:
                continue
            any_launch = True
            if all_delayed:
                continue
            unguarded = [n for n in notes if n.startswith("UNGUARDED")]
            findings.append(Finding(
                "ERROR", "response_delay_not_implemented", field,
                f"Spec declares response delay {min_val} at '{field}', but "
                f"{f} launches the response with no hold-off on that path: "
                f"{'; '.join(unguarded)}. The launch must be gated by a "
                f"delay state or an explicit counter/elapsed flag "
                f"(S_TSRS / S_WAIT* / S_TURNAROUND / '*_cnt >= T_*') so the "
                f"first response bit arrives no earlier than the spec "
                f"minimum. Firing immediately is the sim-passes / "
                f"hardware-fails mode: the host bus is still turning around "
                f"and drops the leading response bits.",
            ))

    errors = [f for f in findings if f.severity == "ERROR"]
    if args.json:
        _txt = json.dumps({
            "target": args.target,
            "specs": args.spec,
            "declared_delay": delay,
            "response_launch_seen": any_launch,
            "response_launches": launch_notes,
            "errors": len(errors),
            "findings": [asdict(f) for f in findings],
            "verdict": "PASS" if not errors else "FAIL",
        }, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            from pathlib import Path as _P
            _P(args.json).parent.mkdir(parents=True, exist_ok=True)
            _P(args.json).write_text(_txt + "\n")
    else:
        for n in launch_notes:
            print(f"[INFO] {n}")
        for f in findings:
            print(f"[{f.severity}] {f.rule} @ {f.field}")
            print(f"    {f.message}")
        print(f"\n{len(errors)} error(s)")
        print("PASS" if not errors else "FAIL")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
