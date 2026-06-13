#!/usr/bin/env python3
"""send_test_active_drive_check.py — Wave 27 (v0.119.59) gate.

Purpose
-------
Enforce that the FSM has a clear path from RX-of-SEND-TEST-class-cmd
to actively driving the half-duplex bus open-drain (i.e. asserting an
``*_oe`` family signal to LOW) for at least 8 bit-cells (= 1 byte
minimum response).

Background
----------
The 32nd-attempt fresh-agent benchmark (v0.119.58, <benchmark> vendor) was
hardware-silent on SEND_TEST async response.  Diagnostic
`docs/design/SCOPE_DIAG_v068_vs_v0119.58.md` byte-stream comparison:
vendor PASS DUT actively drives id_bus during the SEND_TEST query
window (E0 frame trailer carries real CRC `01 A9`); v0.119.58 trailer
is `02 02` (host padding because DUT never drove).

The dispatch → TX path being structurally absent (or absent for the
SEND-TEST opcode while the CONNECT opcode is wired) is the most
common silent root-cause.  This gate flags the structural shape.

CHIP-AGNOSTIC.  No chip / vendor / opcode-hex hard-coded.  We
recognise SEND-TEST-class commands by NAME synonyms read from L3.

Detection algorithm
-------------------
1. Find FSM RTL files (heuristic: filename matches one of
   ``main_fsm`` / ``mac`` / ``cmd_fsm`` / ``top_fsm`` / ``ctrl*fsm``,
   OR contains ``S_RX*`` AND ``S_TX*`` state literals).
2. Load L3.  Identify SEND-TEST-class opcodes by name synonym match
   on each command's ``name`` / ``description`` / ``label`` field:
       send_test, get_id, getid, query, identify, get_info, get_state,
       getserial, get_serial, send_id, get_eeprom, read_id, ident
   (case-insensitive substring).  Each matched opcode contributes its
   hex byte (synonym keys: ``opcode``, ``hex``, ``code``, ``op_hex``,
   ``opcode_hex``, ``cmd_hex``, ``value``).
3. For each SEND-TEST-class opcode, locate the dispatch arm in any
   FSM file: a line of the form
       ``8'h74:`` / ``cur_op == 8'h74`` / ``opcode == 8'h74`` / etc.
4. From each dispatch site, trace the resulting state transitions
   (``state <= S_FOO``) within the next 60 lines and follow the
   reachable state chain (BFS on ``state <= S_BAR`` arms), bounded
   to <=20 distinct states.
5. Verify that within the reachable chain at least one state arm
   asserts an OE-family signal to ``1'b1`` (``tx_oe <= 1'b1`` /
   ``id_bus_oe <= 1'b1`` / ``bus_oe <= 1'b1`` / ``drive_low <=
   1'b1``).  At minimum the OE-asserting state must appear once
   per ``bit_idx`` cycle that totals ≥ 8 (hence "≥8 bit cells = 1
   byte").  We approximate by counting OE-asserting states reached
   from dispatch:
       0 OE-state                         → FAIL
       1 OE-state and a reachable counter
         (`bit_idx` / `cnt` / `tick` / `i `)  → PASS (loop assumed)
       1 OE-state but no counter reachable  → WARN (short drive,
                                                 likely 1-2 cells)
6. **FAIL** when:
   - L3 has SEND-TEST-class opcode, FSM exists, but dispatch arm
     missing for that opcode in any FSM file, OR
   - Dispatch arm exists but TX-state chain never asserts an
     OE-family signal.
7. SKIP gracefully when L3 / FSM / SEND-TEST-class opcode absent.
8. Honors waiver ``send_test_silent_intentional`` (≥40 chars).

Usage
-----
    python3 send_test_active_drive_check.py <project_dir>
        [--json <out>]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER / WARN-only
    1 — FAIL
    2 — usage / IO error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional
import _path_layout as _pl


WAIVER_KEY = "send_test_silent_intentional"
WAIVER_MIN = 40

# L3 navigation -------------------------------------------------------
CONTAINER_KEYS = (
    "opcodes", "commands", "command_table",
    "opcodes_supported", "opcode_set",
)
HEX_FIELD_KEYS = (
    "opcode", "hex", "code", "opcode_hex",
    "op_hex", "value", "cmd_hex",
)
NAME_FIELD_KEYS = ("name", "description", "label", "title", "mnemonic")

SEND_TEST_NAME_TOKENS = (
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

# FSM file recognition -----------------------------------------------
FSM_FILENAME_PATTERNS = (
    re.compile(r"main_fsm",     re.I),
    re.compile(r"mac\b",        re.I),
    re.compile(r"cmd[_]?fsm",   re.I),
    re.compile(r"top[_]?fsm",   re.I),
    re.compile(r"ctrl.*fsm",    re.I),
    re.compile(r"dispatch",     re.I),
    re.compile(r"protocol.*fsm", re.I),
)

# OE-family RHS pattern: signal that is assigned 1'b1 in a state arm.
# We allow `<= 1'b1`, `= 1'b1`, `<= 1`, with optional space.
_OE_FAMILY_NAMES = re.compile(
    r"\b(\w*(?:tx_oe|id_bus_oe|bus_oe|"
    r"drive_low|drive_lo|tx_drive|tx_drv|wake_oe|drv_oe|"
    r"oen?))\b",
    re.IGNORECASE,
)
_OE_ASSIGN_HIGH = re.compile(
    r"(\w+)\s*<?=\s*1\s*'\s*[bB]\s*1",
)
_OE_ASSIGN_HIGH_INT = re.compile(
    r"(\w+)\s*<?=\s*(?:1\s*'[hHdD]\s*)?1\s*[;)\s]",
)

_STATE_ASSIGN = re.compile(
    r"\bstate\s*<=\s*([A-Za-z_]\w*)\s*[;,)]?",
)

_STATE_ARM_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*:\s*begin\b",
)

# v1.6.205 (#87 P0) — one-liner state arm `S_FOO: <stmt>;` (no `begin`).
# Used by RTL emitters that fold trivial transitions onto a single line
# (e.g., S_OTP_REQ: state <= S_OTP_W1;). Without recognising these, BFS
# loses entire reachable chains.
_STATE_ARM_ONELINER_RE = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s*:\s*(?!begin\b)([^;]+);"
)


def _strip_comments(text: str) -> str:
    """v1.6.205 (#87 P0) — strip Verilog `// ...` line comments and
    `/* ... */` block comments before tokenising `begin`/`end`/`case`/
    `endcase`.  Without this, a comment containing the literal word
    `case`/`begin`/`end` (e.g., docstring referring to a `case-arm`)
    desynchronises depth tracking and causes the parser to merge or
    drop downstream state arms. chip-AGNOSTIC: applies to every FSM
    regardless of opcode names or chip class."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text

# bit-cell counter heuristics — names commonly used to count bits/bytes
_COUNTER_NAMES = re.compile(
    r"\b(bit_idx|bit_cnt|bitcnt|byte_idx|byte_cnt|"
    r"tick|tcnt|t_cnt|tx_cnt|tx_idx|i\b|j\b|cnt)\b",
    re.I,
)


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
    if 0 <= v <= 0xFF:
        return f"{v:02x}"
    return None


def _find_l3(project: Path) -> Optional[Path]:
    """Find L3 in either generated_docs/ or l_docs/."""
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if d.is_dir():
            for cand in sorted(d.glob("L3*.json")):
                return cand
    return None


def _iter_command_dicts(l3: dict):
    """Yield each command dict in L3 (recurses through containers)."""
    container = None
    for k in CONTAINER_KEYS:
        if k in l3 and l3[k]:
            container = l3[k]
            break
    if container is None:
        return
    if isinstance(container, list):
        items = container
    elif isinstance(container, dict):
        items = list(container.values())
    else:
        return
    for it in items:
        if isinstance(it, dict):
            yield it


def _extract_send_test_opcodes(l3: dict) -> list[tuple[str, str]]:
    """Return [(hex_byte, name)] for SEND_TEST-class commands."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in _iter_command_dicts(l3):
        # Pull name/description fields
        text_parts = []
        for k in NAME_FIELD_KEYS:
            v = entry.get(k)
            if isinstance(v, str):
                text_parts.append(v.lower())
        text = " ".join(text_parts)
        if not text:
            continue
        if not any(tok in text for tok in SEND_TEST_NAME_TOKENS):
            continue
        # Extract hex
        h = None
        for k in HEX_FIELD_KEYS:
            if k in entry:
                h = _norm_hex(entry[k])
                if h:
                    break
        if not h or h in seen:
            continue
        seen.add(h)
        # Pick the first non-empty name for reporting
        name = next((v for k in NAME_FIELD_KEYS
                     for v in [entry.get(k)]
                     if isinstance(v, str) and v),
                    "?")
        out.append((h, name))
    return out


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
        if {"build", "sim", "synth", "formal", "pnr",
            "gds", "output_files", "incremental_db", "db",
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
        # Fallback: file with both S_RX* and S_TX* style states
        if (re.search(r"\bS_RX\w*", text)
                and re.search(r"\bS_TX\w*", text)):
            out.append(f)
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


def _split_state_arms(text: str) -> dict[str, tuple[int, int, str]]:
    """Crude 'case' state-arm splitter. Returns dict
    state_name -> (start_line, end_line, body_text). Tracks `begin`/
    `end` depth from each `S_FOO: begin` head, plus folded one-liner
    arms (`S_FOO: state <= S_BAR;`).

    v1.6.205 (#87 P0): comments are stripped before depth tracking so
    that a comment containing the word `case`/`begin`/`end` doesn't
    desynchronise the parser. One-liner arms are recognised so that
    chains like `S_OTP_REQ -> S_OTP_W1 -> S_OTP_W2 -> S_OTP_GOT` are
    walkable (otherwise BFS from a SEND_TEST dispatch state dies one
    hop in).  chip-AGNOSTIC."""
    arms: dict[str, tuple[int, int, str]] = {}
    text = _strip_comments(text)
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _STATE_ARM_RE.match(lines[i])
        if not m:
            # v1.6.205 — also try one-liner arm
            m2 = _STATE_ARM_ONELINER_RE.match(lines[i])
            if m2 and m2.group(1) not in arms:
                arms[m2.group(1)] = (i + 1, i + 1, m2.group(2))
            i += 1
            continue
        sname = m.group(1)
        depth = 1
        body_lines: list[str] = []
        j = i + 1
        while j < len(lines) and depth > 0:
            ln = lines[j]
            # very crude depth tracking on whole-word begin/end
            # (skip strings is overkill for our heuristic).
            for tok in re.findall(r"\b(begin|case|fork|end|endcase|join)\b",
                                  ln):
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


def _arm_assigns_oe_high(body: str) -> Optional[str]:
    """Return the OE-family signal name asserted to 1'b1 in the arm,
    if any."""
    for ln in body.splitlines():
        # find any token matching OE-family on the LHS of an assign
        m_assign = re.search(
            r"(\w+)\s*<=\s*1\s*'\s*[bB]\s*1\b", ln)
        if not m_assign:
            continue
        lhs = m_assign.group(1)
        if _OE_FAMILY_NAMES.fullmatch(lhs):
            return lhs
        # accept names ending with _oe/_drive_low/etc.
        if re.search(
                r"(_oe|_oen|_drive_low|_drv|_drive_lo)$", lhs, re.I):
            return lhs
    return None


def _arm_next_states(body: str) -> set[str]:
    return {m.group(1) for m in _STATE_ASSIGN.finditer(body)}


def _arm_has_counter(body: str) -> bool:
    return bool(_COUNTER_NAMES.search(body))


_FUNCTION_RE = re.compile(r"\bfunction\b.*?\bendfunction\b",
                          re.DOTALL)
_TASK_RE = re.compile(r"\btask\b.*?\bendtask\b", re.DOTALL)


def _strip_funcs(text: str) -> str:
    """Mask out function/task bodies so opcode literals inside
    cmd_len_of / requires_awake helpers don't masquerade as
    dispatch arms."""
    out = text
    for pat in (_FUNCTION_RE, _TASK_RE):
        out = pat.sub(lambda m: "\n" * m.group(0).count("\n"), out)
    return out


def _find_dispatch_arms_for(byte_hex: str, text: str
                            ) -> list[tuple[int, str]]:
    """Locate dispatch lines for the given opcode byte. Returns list
    of (line_no, dispatched_state). dispatched_state is "" when no
    `state <=` is found in the immediate arm body — that itself is a
    failure mode (opcode known by decoder but no TX path)."""
    # v1.6.205 (#87 P0) — strip comments before _strip_funcs so that
    # comment word `case`/`begin`/`end` doesn't poison depth tracking.
    masked = _strip_funcs(_strip_comments(text))
    pats = _hex_literal_pats(byte_hex)
    lines = masked.splitlines()
    raw_lines = masked.splitlines()
    hits: list[tuple[int, str]] = []
    for ln_no, line in enumerate(lines, 1):
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
        # Look at next 30 raw lines for state <= ...; bound by `end`
        # to avoid leaking out of the arm.
        snippet_lines = []
        depth = 0
        seen_begin = False
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
        m = _STATE_ASSIGN.search(snippet)
        nxt = m.group(1) if m else ""
        hits.append((ln_no, nxt))
    return hits


def _trace_chain(start: str, arms: dict[str, tuple[int, int, str]]
                 ) -> tuple[set[str], list[tuple[str, str]]]:
    """BFS on state graph, return (reachable_states, oe_assert_sites)."""
    visited: set[str] = set()
    sites: list[tuple[str, str]] = []
    queue = [start] if start else []
    while queue:
        s = queue.pop(0)
        if not s or s in visited:
            continue
        visited.add(s)
        if len(visited) > 25:
            break
        if s not in arms:
            continue
        _ln, _le, body = arms[s]
        oe_sig = _arm_assigns_oe_high(body)
        if oe_sig:
            sites.append((s, oe_sig))
        for nxt in _arm_next_states(body):
            if nxt not in visited:
                queue.append(nxt)
    return visited, sites


def check(project: Path) -> dict:
    findings: list[dict] = []
    warnings: list[dict] = []
    info: dict = {}

    l3_path = _find_l3(project)
    if l3_path is None:
        return {
            "program": "send_test_active_drive_check",
            "skip_reason": "no L3*.json found",
            "pass": True, "findings": [], "warnings": [], **info,
        }
    info["l3_path"] = str(l3_path.relative_to(project))

    try:
        l3 = json.loads(l3_path.read_text())
    except Exception as e:
        return {
            "program": "send_test_active_drive_check",
            "pass": False,
            "findings": [{
                "rule": "L3_UNPARSEABLE",
                "severity": "FAIL",
                "message": f"L3 unparseable: {e}",
            }],
            "warnings": [], **info,
        }

    targets = _extract_send_test_opcodes(l3)
    info["send_test_opcodes"] = [
        f"0x{h} ({n})" for h, n in targets]
    if not targets:
        return {
            "program": "send_test_active_drive_check",
            "skip_reason": (
                "no SEND_TEST-class opcode found in L3 by name "
                "synonym match"),
            "pass": True, "findings": [], "warnings": [], **info,
        }

    fsm_files = _find_fsm_files(project)
    info["fsm_files"] = [str(f.relative_to(project)) for f in fsm_files]
    if not fsm_files:
        return {
            "program": "send_test_active_drive_check",
            "skip_reason": (
                "no FSM-like RTL file found"),
            "pass": True, "findings": [], "warnings": [], **info,
        }

    # Per opcode -- look across all FSM files
    for byte_hex, op_name in targets:
        dispatched_states: list[tuple[str, str, int]] = []  # (file, state, line)
        for f in fsm_files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for ln_no, nxt in _find_dispatch_arms_for(byte_hex, text):
                dispatched_states.append(
                    (str(f.relative_to(project)), nxt, ln_no))

        if not dispatched_states:
            findings.append({
                "rule": "SEND_TEST_NO_DISPATCH",
                "severity": "FAIL",
                "message": (
                    f"FAIL — SEND_TEST_NO_ACTIVE_DRIVE\n"
                    f"  L3 declares SEND-TEST-class opcode 0x{byte_hex} "
                    f"({op_name}) but NO FSM file contains a dispatch "
                    f"arm. Searched: "
                    f"{[str(f.relative_to(project)) for f in fsm_files]}.\n"
                    f"  Hint: add `8'h{byte_hex.upper()}: state <= "
                    f"S_TX_BIT_LOW;` (or equivalent) in the RX→DISPATCH "
                    f"case, then drive the OE-family signal in the TX "
                    f"state arm."),
            })
            continue

        # Walk reachable chain. ONLY count dispatch entries with a
        # non-empty starting state — otherwise the dispatch arm doesn't
        # actually transition the FSM (silent fall-through).
        starts = [(fp, st, ln) for fp, st, ln in dispatched_states if st]
        if not starts:
            # All dispatch arms found but none transition state →
            # equivalent to no-active-drive.
            file_lines = "; ".join(
                f"{fp}:{ln}" for fp, _s, ln in dispatched_states)
            findings.append({
                "rule": "SEND_TEST_NO_ACTIVE_DRIVE",
                "severity": "FAIL",
                "message": (
                    f"FAIL — SEND_TEST_NO_ACTIVE_DRIVE\n"
                    f"  FSM file:line — {file_lines}\n"
                    f"  Opcode 0x{byte_hex} ({op_name}) appears in "
                    f"decode context but the arm contains NO `state <= "
                    f"S_TX_*` transition (falls through, default branch, "
                    f"or table-only lookup).\n"
                    f"  Vendor PASS oracle: SEND_TEST → S_TX_BIT "
                    f"(drives id_bus_oe for 8+ bit cells × 8+ bytes).\n"
                    f"  Hint: in S_TX_BIT_LOW state, drive id_bus_oe = 1 "
                    f"AND id_bus_dout = 0. For HIGH portion, "
                    f"id_bus_oe = 0 (let bus float = open-drain HIGH)."),
            })
            continue
        all_oe_sites: list[tuple[str, str, str]] = []  # (file, state, sig)
        for fpath_rel, start_state, line_no in starts:
            fpath = project / fpath_rel
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            arms = _split_state_arms(text)
            visited, sites = _trace_chain(start_state, arms)
            # Also walk arms in other FSM files if the dispatched
            # state isn't defined in this file.
            for fpath2_rel in info["fsm_files"]:
                if fpath2_rel == fpath_rel:
                    continue
                fpath2 = project / fpath2_rel
                try:
                    text2 = fpath2.read_text(encoding="utf-8",
                                             errors="replace")
                except OSError:
                    continue
                arms2 = _split_state_arms(text2)
                v2, s2 = _trace_chain(start_state, arms2)
                visited |= v2
                sites += s2
            for st, sig in sites:
                all_oe_sites.append((fpath_rel, st, sig))

        if not all_oe_sites:
            file_lines = "; ".join(
                f"{fp}:{ln}" for fp, _s, ln in dispatched_states)
            findings.append({
                "rule": "SEND_TEST_NO_ACTIVE_DRIVE",
                "severity": "FAIL",
                "message": (
                    f"FAIL — SEND_TEST_NO_ACTIVE_DRIVE\n"
                    f"  FSM file:line — {file_lines}\n"
                    f"  Found opcode dispatch (0x{byte_hex} {op_name}) "
                    f"but TX path doesn't drive any OE-family signal "
                    f"(*_oe / drive_low / *_drv).\n"
                    f"  Vendor PASS oracle: SEND_TEST → S_TX_BIT "
                    f"(drives id_bus_oe for 8+ bit cells × 8+ bytes).\n"
                    f"  This RTL: id_bus_oe never asserted in dispatch "
                    f"path.\n"
                    f"  Hint: in S_TX_BIT_LOW state, drive id_bus_oe = 1 "
                    f"AND id_bus_dout = 0. For HIGH portion, "
                    f"id_bus_oe = 0 (let bus float = open-drain HIGH)."),
            })
            continue

        # OE asserted — now check counter heuristic for "≥8 bit cells"
        loop_back = False
        # Inspect each OE-arm for counter usage AND for a back-edge
        # transition (state <= same_or_predecessor) that indicates a
        # bit-cell loop.
        for fpath_rel, st, _sig in all_oe_sites:
            fpath = project / fpath_rel
            try:
                text = fpath.read_text(encoding="utf-8",
                                       errors="replace")
            except OSError:
                continue
            arms = _split_state_arms(text)
            if st not in arms:
                continue
            _l, _le, body = arms[st]
            if _arm_has_counter(body):
                loop_back = True
                break
            # Look at the immediate next states; if any of them loop
            # back to the same OE-arm (or to its TX peer), accept.
            for nxt in _arm_next_states(body):
                if nxt == st:
                    loop_back = True
                    break
                if nxt in arms:
                    _l2, _le2, body2 = arms[nxt]
                    nxt_targets = _arm_next_states(body2)
                    if st in nxt_targets:
                        loop_back = True
                        break
            if loop_back:
                break

        if not loop_back:
            warnings.append({
                "rule": "SEND_TEST_SHORT_DRIVE",
                "severity": "WARN",
                "message": (
                    f"OE-family signal asserted in dispatch chain for "
                    f"0x{byte_hex} ({op_name}) but no per-bit counter "
                    f"or self/peer back-edge detected in OE arm "
                    f"(`{all_oe_sites[0][1]}`). Drive may be only 1-2 "
                    f"cells. Verify TX bit loop fills ≥ 64 bit cells "
                    f"(8 bytes × 8 bits)."),
            })

    return {
        "program": "send_test_active_drive_check",
        "pass": len(findings) == 0,
        "findings": findings,
        "warnings": warnings,
        **info,
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None)
    # v1.6.145 (#57) — FPGA-prototype-stage stub waiver. Field-agent
    # grouped send_test_active_drive_check with the 5 analog gates
    # because all 6 block fpga_burn on mixed_signal_otp chips during
    # the v1.6.144 verify. Honoring the same waiver contract keeps
    # the gate strict at tapeout signoff while allowing FPGA
    # prototyping to progress.
    import _fpga_stub_waiver as _stub
    _stub.add_fpga_stub_argparse(ap)
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}",
              file=sys.stderr)
        return 2

    result = check(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    if "skip_reason" in result:
        print(f"PASS_SKIP — {result['skip_reason']}")
        return 0

    if result["pass"]:
        if result.get("warnings"):
            print(
                f"PASS_WITH_WARN — SEND_TEST active drive present "
                f"({len(result.get('send_test_opcodes', []))} "
                f"opcode(s)); {len(result['warnings'])} warning(s)")
            for w in result["warnings"]:
                print(f"WARN: {w['rule']} — {w['message']}")
        else:
            print(
                f"PASS — SEND_TEST active drive present "
                f"({len(result.get('send_test_opcodes', []))} "
                f"opcode(s) traced to OE-asserting TX state)")
        return 0

    is_waived, why = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(result['findings'])} finding(s); "
            f"waiver `{WAIVER_KEY}` set: {why[:80]}…")
        for f in result["findings"]:
            print(f"  • {f['rule']} — {f['message'][:160]}")
        return 0

    # v1.6.145 (#57) — FPGA-prototype-stage waiver path. Demote FAIL
    # to PASS_WITH_WAIVERS when the stage marker is set. The same
    # gate re-fires WITHOUT the waiver at phase3.foundry_handoff for
    # tapeout signoff.
    if _stub.fpga_stub_waiver_active(args):
        try:
            if args.json:
                _existing = json.loads(Path(args.json).read_text())
            else:
                _existing = result
            _existing.setdefault("summary", {})
            _existing["summary"]["fpga_stub_waiver_applied"] = True
            _existing["summary"]["waiver_reason"] = _stub.fpga_stub_reason()
            if args.json:
                Path(args.json).write_text(json.dumps(_existing, indent=2))
        except Exception:
            pass
        print(
            f"PASS_WITH_WAIVERS — {len(result['findings'])} send-test-"
            f"drive finding(s) demoted to WARNING for FPGA prototype "
            f"stage (PHASE23_ANALOG_FPGA_STUB / --allow-fpga-stub)")
        for f in result["findings"]:
            print(f"WARN: {f['rule']} — {f['message']}")
        return 0

    print(f"FAIL — {len(result['findings'])} send-test-drive "
          f"violation(s)")
    for f in result["findings"]:
        print(f"FAIL: {f['rule']} — {f['message']}")
    for w in result.get("warnings", []):
        print(f"WARN: {w['rule']} — {w['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
