#!/usr/bin/env python3
"""connect_vs_send_test_parity_check.py — Wave 27 (v0.119.59) gate.

Purpose
-------
Catch the "fresh-agent only implements CONNECT path, leaves SEND_TEST
as stub" pattern that shows up as <half-duplex-tester> byte[6]=0x02 deterministic
FAIL while CONNECT reply looks identical to vendor PASS oracle.

Background
----------
v0.119.58 (32nd-attempt fresh-agent) RTL traced: CONNECT-class opcodes
get a full RX→dispatch→OTP-fetch→CRC→TX-bit chain (~100 lines), but
SEND_TEST-class opcodes route to default `state <= S_IDLE` (1-2
lines).  Sim PASSed because TB stimulus exercised CONNECT only;
hardware FAILed because <half-duplex-tester> follows CONNECT with a SEND_TEST query
that the chip cannot answer.

Detection algorithm
-------------------
1. Load L3.  Classify each opcode by NAME synonym match:
     CONNECT class: connect, wake, init, reset, ping, hello,
       open_session, set_state, awake, attach
     SEND_TEST class: send_test, get_id, getid, query, identify,
       get_info, get_state, get_serial, get_eeprom, read_id,
       send_id, ident
2. Locate FSM RTL files (same heuristic as
   send_test_active_drive_check).
3. For each opcode, find its dispatch arm (line that decodes the
   opcode in a `state <= S_*` context, NOT inside function/task
   bodies).  From the dispatch line, count downstream LINES until
   the matching `end` of the arm.  Where the arm transitions to
   another state, follow the chain (BFS, ≤ 8 hops, ≤ 25 unique
   states, only counting lines once).
4. Compute, per class, max(downstream_lines).  Compare:
     send_test_max < CONNECT_PARITY_RATIO * connect_max
   default ratio = 0.5 (50%).  Below that → FAIL with the actual
   numbers and file:line of each end-point.
5. SKIP gracefully when L3 has no opcodes, no CONNECT-class match,
   no SEND_TEST-class match, OR no FSM file.
6. Honors waiver ``send_test_dispatch_intentionally_minimal``
   (≥40 chars).

CHIP-AGNOSTIC.  No specific opcode hex / chip name / pin / vendor
reference.  Class membership is name-synonym-only.

Usage
-----
    python3 connect_vs_send_test_parity_check.py <project_dir>
        [--json <out>] [--ratio 0.5]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER
    1 — FAIL
    2 — IO / parse error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional
import _path_layout as _pl


WAIVER_KEY = "send_test_dispatch_intentionally_minimal"
WAIVER_MIN = 40

DEFAULT_RATIO = 0.5

CONTAINER_KEYS = (
    "opcodes", "commands", "command_table",
    "opcodes_supported", "opcode_set",
)
HEX_FIELD_KEYS = (
    "opcode", "hex", "code", "opcode_hex",
    "op_hex", "value", "cmd_hex",
)
NAME_FIELD_KEYS = ("name", "description", "label", "title", "mnemonic")

CONNECT_TOKENS = (
    "connect", "wake", "init", "reset",
    "ping", "hello", "open_session", "set_state",
    "awake", "attach",
)
SEND_TEST_TOKENS = (
    "send_test", "send test", "sendtest",
    "get_id", "get id", "getid",
    "query", "identify", "ident",
    "get_info", "get info", "getinfo",
    "get_state", "get state", "getstate",
    "get_serial", "get serial", "getserial",
    "get_eeprom", "get eeprom", "geteeprom",
    "read_id", "send_id", "sendid",
    "accessory_serial", "module_serial",
    "interface_device_info",
)

FSM_FILENAME_PATTERNS = (
    re.compile(r"main_fsm",     re.I),
    re.compile(r"mac\b",        re.I),
    re.compile(r"cmd[_]?fsm",   re.I),
    re.compile(r"top[_]?fsm",   re.I),
    re.compile(r"ctrl.*fsm",    re.I),
    re.compile(r"dispatch",     re.I),
    re.compile(r"protocol.*fsm", re.I),
)

_FUNCTION_RE = re.compile(r"\bfunction\b.*?\bendfunction\b", re.DOTALL)
_TASK_RE = re.compile(r"\btask\b.*?\bendtask\b", re.DOTALL)
_STATE_ARM_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*:\s*begin\b")
_STATE_ASSIGN = re.compile(
    r"\bstate\s*<=\s*([A-Za-z_]\w*)\s*[;,)]?")


def waived(project: Path) -> tuple[bool, str]:
    p = project / "waivers.json"
    if not p.exists():
        return False, ""
    try:
        d = json.loads(p.read_text())
        v = d.get(WAIVER_KEY)
        if isinstance(v, str) and len(v.strip()) >= WAIVER_MIN:
            return True, v.strip()
    except Exception:
        pass
    return False, ""


def _norm_hex(raw) -> Optional[str]:
    if isinstance(raw, int):
        if 0 <= raw <= 0xFF:
            return f"{raw:02x}"
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower().replace("0x", "").replace("'h", "").replace("h", "")
    if not s:
        return None
    try:
        v = int(s, 16)
    except ValueError:
        return None
    return f"{v:02x}" if 0 <= v <= 0xFF else None


def _find_l3(project: Path) -> Optional[Path]:
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if d.is_dir():
            for cand in sorted(d.glob("L3*.json")):
                return cand
    return None


def _classify_opcodes(l3: dict) -> tuple[list[tuple[str, str]],
                                         list[tuple[str, str]]]:
    """Return (connect_class, send_test_class) lists of (hex, name)."""
    connect: list[tuple[str, str]] = []
    sendtest: list[tuple[str, str]] = []
    container = None
    for k in CONTAINER_KEYS:
        if k in l3 and l3[k]:
            container = l3[k]
            break
    if container is None:
        return connect, sendtest
    items = (container if isinstance(container, list)
             else list(container.values())
             if isinstance(container, dict) else [])
    seen_c: set[str] = set()
    seen_s: set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            continue
        text_parts = []
        for k in NAME_FIELD_KEYS:
            v = entry.get(k)
            if isinstance(v, str):
                text_parts.append(v.lower())
        text = " ".join(text_parts)
        if not text:
            continue
        h = None
        for k in HEX_FIELD_KEYS:
            if k in entry:
                h = _norm_hex(entry[k])
                if h:
                    break
        if not h:
            continue
        name = next((v for k in NAME_FIELD_KEYS
                     for v in [entry.get(k)]
                     if isinstance(v, str) and v),
                    "?")
        if any(tok in text for tok in CONNECT_TOKENS) and h not in seen_c:
            connect.append((h, name))
            seen_c.add(h)
        if any(tok in text for tok in SEND_TEST_TOKENS) and h not in seen_s:
            sendtest.append((h, name))
            seen_s.add(h)
    return connect, sendtest


def _find_fsm_files(project: Path) -> list[Path]:
    out: list[Path] = []
    rtl_root = _pl.rtl_dir(project)
    cands: list[Path] = []
    if rtl_root.is_dir():
        cands.extend(rtl_root.rglob("*.v"))
        cands.extend(rtl_root.rglob("*.sv"))
    else:
        cands.extend(project.rglob("*.v"))
        cands.extend(project.rglob("*.sv"))
    for f in cands:
        if not f.is_file():
            continue
        parts = set(p.lower() for p in f.parts)
        if {"build", "sim", "synth", "formal", "pnr", "gds",
            "output_files", "incremental_db", "db",
            "tb", "testbench"} & parts:
            continue
        name = f.name.lower()
        if any(p.search(name) for p in FSM_FILENAME_PATTERNS):
            out.append(f)
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if (re.search(r"\bS_RX\w*", text)
                and re.search(r"\bS_TX\w*", text)):
            out.append(f)
    return out


def _strip_funcs(text: str) -> str:
    out = text
    for pat in (_FUNCTION_RE, _TASK_RE):
        out = pat.sub(lambda m: "\n" * m.group(0).count("\n"), out)
    return out


def _hex_literal_pats(byte_hex: str) -> list[re.Pattern]:
    bh, BH = byte_hex.lower(), byte_hex.upper()
    dec = int(byte_hex, 16)
    return [
        re.compile(rf"\b8\s*'\s*[hH]\s*{bh}\b"),
        re.compile(rf"\b8\s*'\s*[hH]\s*{BH}\b"),
        re.compile(rf"\b'[hH]\s*{bh}\b"),
        re.compile(rf"\b'[hH]\s*{BH}\b"),
        re.compile(rf"\b8\s*'\s*[dD]\s*{dec}\b"),
    ]


def _split_arms(text: str) -> dict[str, tuple[int, int, str]]:
    arms: dict[str, tuple[int, int, str]] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _STATE_ARM_RE.match(lines[i])
        if not m:
            i += 1
            continue
        sname = m.group(1)
        depth = 1
        body_lines: list[str] = []
        j = i + 1
        while j < len(lines) and depth > 0:
            ln = lines[j]
            for tok in re.findall(
                    r"\b(begin|case|fork|end|endcase|join)\b", ln):
                if tok in ("begin", "case", "fork"):
                    depth += 1
                elif tok in ("end", "endcase", "join"):
                    depth -= 1
                    if depth == 0:
                        break
            if depth == 0:
                break
            body_lines.append(ln)
            j += 1
        arms[sname] = (i + 1, j + 1, "\n".join(body_lines))
        i = j + 1
    return arms


def _arm_next_states(body: str) -> set[str]:
    return {m.group(1) for m in _STATE_ASSIGN.finditer(body)}


def _line_count_in_chain(start: str,
                         arms: dict[str, tuple[int, int, str]]) -> int:
    visited: set[str] = set()
    queue = [start] if start else []
    total = 0
    while queue and len(visited) <= 25:
        s = queue.pop(0)
        if not s or s in visited:
            continue
        visited.add(s)
        if s not in arms:
            continue
        ln_start, ln_end, body = arms[s]
        total += max(1, ln_end - ln_start)
        for nxt in _arm_next_states(body):
            if nxt not in visited:
                queue.append(nxt)
    return total


def _opcode_chain_lines(byte_hex: str, fsm_files: list[Path],
                        project: Path) -> tuple[int, list[str]]:
    """Return (max_lines, sample_sites) across all FSM files."""
    pats = _hex_literal_pats(byte_hex)
    best = 0
    sites: list[str] = []
    for f in fsm_files:
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        masked = _strip_funcs(raw)
        masked_lines = masked.splitlines()
        raw_lines = raw.splitlines()
        arms = _split_arms(raw)
        for ln_no, line in enumerate(masked_lines, 1):
            if not any(p.search(line) for p in pats):
                continue
            s = line.strip()
            is_arm = bool(re.match(
                r"^\s*\d*\s*'\s*[hHdD]\s*[0-9A-Fa-f]+\s*[,:]", s))
            is_eq = ("==" in s and (
                "cur_op" in s or "rx_byte" in s or "opcode" in s
                or "cmd_op" in s or "op_decode" in s or "op==" in s))
            if not (is_arm or is_eq):
                continue
            # find next state assignment within the arm
            depth = 0
            seen_begin = False
            snippet_lines = []
            for k in range(ln_no - 1, min(len(raw_lines), ln_no + 60)):
                snippet_lines.append(raw_lines[k])
                for tok in re.findall(
                        r"\b(begin|end|case|endcase)\b", raw_lines[k]):
                    if tok in ("begin", "case"):
                        depth += 1
                        seen_begin = True
                    elif tok in ("end", "endcase"):
                        depth -= 1
                if seen_begin and depth <= 0:
                    break
            snippet = "\n".join(snippet_lines)
            inline_lines = len(snippet_lines)
            m = _STATE_ASSIGN.search(snippet)
            if m:
                nxt = m.group(1)
                chain_lines = _line_count_in_chain(nxt, arms)
                total = inline_lines + chain_lines
            else:
                total = inline_lines
            sample = (f"{f.relative_to(project)}:{ln_no} "
                      f"({total} lines)")
            if total > best:
                best = total
                sites = [sample]
            elif total == best:
                sites.append(sample)
    return best, sites[:3]


def check(project: Path, ratio: float = DEFAULT_RATIO) -> dict:
    findings: list[dict] = []
    info: dict = {"ratio_threshold": ratio}

    l3_path = _find_l3(project)
    if l3_path is None:
        return {
            "program": "connect_vs_send_test_parity_check",
            "skip_reason": "no L3*.json found",
            "pass": True, "findings": [], **info,
        }
    info["l3_path"] = str(l3_path.relative_to(project))

    try:
        l3 = json.loads(l3_path.read_text())
    except Exception as e:
        return {
            "program": "connect_vs_send_test_parity_check",
            "pass": False,
            "findings": [{
                "rule": "L3_UNPARSEABLE",
                "severity": "FAIL",
                "message": f"L3 unparseable: {e}",
            }], **info,
        }

    connect_ops, sendtest_ops = _classify_opcodes(l3)
    info["connect_opcodes"] = [f"0x{h} ({n})" for h, n in connect_ops]
    info["send_test_opcodes"] = [f"0x{h} ({n})" for h, n in sendtest_ops]

    if not connect_ops:
        return {
            "program": "connect_vs_send_test_parity_check",
            "skip_reason": (
                "no CONNECT-class opcode found in L3 (synonyms: "
                "connect/wake/init/reset/ping/hello/set_state/...)"),
            "pass": True, "findings": [], **info,
        }
    if not sendtest_ops:
        return {
            "program": "connect_vs_send_test_parity_check",
            "skip_reason": (
                "no SEND_TEST-class opcode found in L3 (synonyms: "
                "send_test/get_id/query/identify/get_info/...)"),
            "pass": True, "findings": [], **info,
        }

    fsm_files = _find_fsm_files(project)
    info["fsm_files"] = [str(f.relative_to(project)) for f in fsm_files]
    if not fsm_files:
        return {
            "program": "connect_vs_send_test_parity_check",
            "skip_reason": "no FSM-like RTL file found",
            "pass": True, "findings": [], **info,
        }

    connect_max = 0
    connect_sites: list[str] = []
    for h, _n in connect_ops:
        v, sites = _opcode_chain_lines(h, fsm_files, project)
        if v > connect_max:
            connect_max, connect_sites = v, sites

    # Exclude opcodes that ALSO match CONNECT class (e.g.
    # "Get ID (Wake)" – the connect-and-identify combo).  We are
    # measuring whether *non-connect* SEND_TEST opcodes have parity.
    connect_hex = {h for h, _ in connect_ops}
    sendtest_only = [(h, n) for h, n in sendtest_ops
                     if h not in connect_hex]
    info["send_test_excluding_connect"] = [
        f"0x{h} ({n})" for h, n in sendtest_only]
    if not sendtest_only:
        return {
            "program": "connect_vs_send_test_parity_check",
            "skip_reason": (
                "every SEND_TEST-class opcode also matches CONNECT "
                "class (combo 'wake-and-identify' opcode); no "
                "non-connect SEND_TEST handler to compare against"),
            "pass": True, "findings": [], **info,
        }

    sendtest_max = 0
    sendtest_sites: list[str] = []
    sendtest_per_op: list[tuple[str, str, int]] = []
    for h, n in sendtest_only:
        v, sites = _opcode_chain_lines(h, fsm_files, project)
        sendtest_per_op.append((h, n, v))
        if v > sendtest_max:
            sendtest_max, sendtest_sites = v, sites

    info["connect_max_lines"] = connect_max
    info["send_test_max_lines"] = sendtest_max
    info["connect_sample_sites"] = connect_sites
    info["send_test_sample_sites"] = sendtest_sites
    info["send_test_per_op"] = [
        {"opcode": f"0x{h}", "name": n, "lines": v}
        for h, n, v in sendtest_per_op]

    if connect_max <= 0:
        return {
            "program": "connect_vs_send_test_parity_check",
            "skip_reason": (
                "CONNECT-class opcode not found in any FSM dispatch — "
                "send_test_active_drive_check covers that case"),
            "pass": True, "findings": [], **info,
        }

    if sendtest_max < ratio * connect_max:
        # Highlight the smallest-volume SEND_TEST opcode in the
        # message — that's the most-likely-stub.
        worst = min(sendtest_per_op, key=lambda t: t[2])
        findings.append({
            "rule": "SEND_TEST_DISPATCH_STUB",
            "severity": "FAIL",
            "message": (
                f"FAIL — SEND_TEST_DISPATCH_STUB\n"
                f"  CONNECT-class downstream code volume = "
                f"{connect_max} lines (sites: {connect_sites}).\n"
                f"  SEND_TEST-class downstream code volume = "
                f"{sendtest_max} lines (sites: {sendtest_sites}).\n"
                f"  Ratio = {sendtest_max / connect_max:.2%} < "
                f"threshold {ratio:.0%}.\n"
                f"  Smallest SEND_TEST opcode: 0x{worst[0]} "
                f"({worst[1]}) → {worst[2]} lines.\n"
                f"  This is the canonical 'fresh-agent fully wires "
                f"CONNECT but stubs SEND_TEST' pattern: sim PASSes "
                f"if TB exercises CONNECT only, hardware FAILs because "
                f"<half-duplex-tester> (or any host) follows CONNECT with a "
                f"SEND_TEST query the chip cannot answer."),
        })

    return {
        "program": "connect_vs_send_test_parity_check",
        "pass": len(findings) == 0,
        "findings": findings,
        **info,
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None)
    ap.add_argument("--ratio", type=float, default=DEFAULT_RATIO,
                    help=f"min SEND_TEST/CONNECT ratio (default "
                         f"{DEFAULT_RATIO})")
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}",
              file=sys.stderr)
        return 2

    result = check(project, ratio=args.ratio)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    if "skip_reason" in result:
        print(f"PASS_SKIP — {result['skip_reason']}")
        return 0

    if result["pass"]:
        print(
            f"PASS — CONNECT vs SEND_TEST dispatch parity OK "
            f"(connect={result.get('connect_max_lines')} lines, "
            f"send_test={result.get('send_test_max_lines')} lines, "
            f"ratio threshold {result.get('ratio_threshold')})")
        return 0

    is_waived, why = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(result['findings'])} finding(s); "
            f"waiver `{WAIVER_KEY}` set: {why[:80]}…")
        for f in result["findings"]:
            print(f"  • {f['rule']} — {f['message'][:160]}")
        return 0

    print(f"FAIL — {len(result['findings'])} parity violation(s)")
    for f in result["findings"]:
        print(f"FAIL: {f['rule']} — {f['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
