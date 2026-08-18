#!/usr/bin/env python3
"""
crc_engine_isolation_check.py — M2: Verify that shared CRC engines have
proper init/update isolation between RX validation and TX generation paths.

v0.119.43 (Wave 11): adds **hard-coded CRC literal detection**. When a CRC
module is structurally present (any module whose name contains ``crc`` or
that exposes ``polynomial`` / ``crc_out`` ports), no OTHER module may emit
an 8-bit hex literal (``8'hXX``) into a packet-construction sink such as
``resp_buf[N]``, ``tx_byte``, ``out_reg``, ``rsp_buf[N]``, etc. This catches
the v0.119.42 fresh-agent failure mode where ``crc8`` was instantiated but
``main_fsm`` hard-coded ``resp_buf[3] <= 8'hA8`` (a vendor sample-frame CRC)
instead of consuming ``crc_out`` — every gate PASSed but the chip emitted
a static CRC byte that didn't match the dynamic payload, and host CRC
verification failed silently. Trivial defaults (``8'h00``, ``8'hFF``,
``8'hAA``, ``8'h55``) are intentionally exempt because they are common
idle / reset / bus-default sentinels. Detection is chip-agnostic: no
specific opcode, polynomial, or vendor ID is referenced.

v0.119.51 (Wave 19): adds **CRC-byte-position literal detection**. The
Wave 11 trivial-literal exemption (``8'h00`` / ``8'hFF`` / ``8'hAA`` /
``8'h55``) is correct in init / reset / idle context but WRONG when
the surrounding control state is the CRC-byte position of a response
packet. The v0.119.50 fresh-agent failure mode wrote
``tx_byte <= 8'h00;`` while the FSM was about to enter ``S_TX_CRC`` —
host CRC residue ≠ 0 → packet rejected → byte[6]=0x02 padding. The
new check detects this by walking up the AST/text from a literal-to-
sink assignment to find an enclosing CRC-state context (case arm,
next-state assignment, or LHS variable name). When that context is
present, even the trivial-literal exemption is dropped. Detection is
chip-agnostic: synonym tables only — no chip / opcode / pin hard-coded.

General pattern (IC-agnostic):

    Many serial-protocol ICs share a single CRC engine between the receive
    path (validate incoming packet CRC) and the transmit path (compute
    outgoing response CRC).  Three invariants must hold:

    1. Explicit ``init`` assertion before each domain's first ``update``.
    2. At least 1-cycle separation between ``init`` deassert and first
       ``update`` assert — a same-cycle overlap can feed data through
       an incompletely-seeded CRC state.
    3. No data-path overlap: the mux selecting CRC input data must not
       glitch between RX and TX sources within a single computation.

    Violation of any of these produces CRC values that are correct in
    simulation (where delta ordering is deterministic) but wrong in
    gate-level or FPGA timing (where setup/hold margins differ).

Static heuristic check.  Scans RTL for:
  - Modules containing both ``crc_init`` and ``crc_update`` (or synonyms)
  - Same-cycle assertions of init and update
  - Multiple drivers/mux on CRC data input
  - **(v0.119.43)** Hard-coded 8-bit hex literal feeding a packet-construction
    sink while a CRC module exists in the same project.

Usage:
    python3 crc_engine_isolation_check.py --rtl-dir <dir> [--json <report.json>]
    python3 crc_engine_isolation_check.py <project_dir>      # auto-detects rtl/

Waiver: ``crc_byte_intentionally_constant`` (≥40 chars) in
        ``<project>/waivers.json`` suppresses the literal-CRC finding.

Exit: 0 = PASS, 1 = findings, 2 = IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _waiver_entries as _we  # noqa: E402  (after sys.path bootstrap)


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    line: int = 0
    details: str = ""


INIT_SIGNAL_RE = re.compile(
    r'\b(\w*crc_init\w*|\w*crc_reset\w*|\w*crc_seed\w*|\w*crc_clear\w*)\b',
    re.IGNORECASE,
)

UPDATE_SIGNAL_RE = re.compile(
    r'\b(\w*crc_update\w*|\w*crc_en\w*|\w*crc_valid\w*|\w*crc_calc\w*|\w*crc_push\w*)\b',
    re.IGNORECASE,
)

CRC_DATA_RE = re.compile(
    r'\b(\w*crc_data\w*|\w*crc_din\w*|\w*crc_in\w*|\w*crc_byte\w*)\b',
    re.IGNORECASE,
)

RX_STATE_RE = re.compile(
    r'\b(S_?RX\w*|RX_\w+|RECEIVE\w*|VALIDATE\w*|rx_state|rx_valid|CMD_RX|PARSE)',
    re.IGNORECASE,
)

TX_STATE_RE = re.compile(
    r'\b(S_?TX\w*|TX_\w+|TRANSMIT\w*|RESPOND\w*|SEND\w*|tx_state|tx_resp|RSP_TX|REPLY)',
    re.IGNORECASE,
)

SILENCE_RE = re.compile(r'//\s*crc-isolation-ok', re.IGNORECASE)

# v0.119.43 Wave 11 — packet-construction sink heuristics.
# Match assignments of an 8-bit hex literal to a register/wire that
# looks like a TX/response packet position. Two flavors:
#   resp_buf[3] <= 8'hA8;
#   tx_byte    <= 8'hA8;
#   rsp_buf[i] <= 8'hA8;
#   out_reg    <= 8'hA8;
#   resp[3]     = 8'hA8;
# We capture the sink name + index (if any) + the literal value.
# The capture group order is: (sink, literal).
_PACKET_SINK_HINTS = (
    "resp_buf", "rsp_buf", "resp", "rsp",
    "tx_byte", "tx_data", "tx_buf", "tx_buffer",
    "out_reg", "out_buf", "out_data", "out_buffer",
    "packet", "frame", "pkt", "response",
    "txd", "tx_reg",
)
# Trivial defaults / idle sentinels — never flagged.
_TRIVIAL_LITERALS = {"00", "FF", "AA", "55"}

_PACKET_LITERAL_RE = re.compile(
    r'\b('
    + r'|'.join(re.escape(h) for h in _PACKET_SINK_HINTS)
    + r')\s*(?:\[[^\]]+\])?\s*(?:<=|=)\s*8\s*\'\s*[hH]\s*([0-9A-Fa-f]{1,2})\b'
)

# CRC module presence — chip-agnostic. Module-header pattern, OR a port
# named polynomial / crc_out / crc_in.
_CRC_MODULE_HEADER_RE = re.compile(
    r'\bmodule\s+(\w*crc\w*)\b', re.IGNORECASE
)
_CRC_PORT_HINT_RE = re.compile(
    r'\b(polynomial|crc_out|crc_in|crc_din|crc_dout)\b', re.IGNORECASE
)


def _project_has_crc_module(rtl_dir: Path) -> tuple[bool, List[str]]:
    """v0.119.43: scan all RTL files; return (present, [module_names])."""
    found: List[str] = []
    for p in _find_v_files(rtl_dir):
        try:
            raw = p.read_text(errors="replace")
        except OSError:
            continue
        text = _strip_comments(raw)
        for m in _CRC_MODULE_HEADER_RE.finditer(text):
            found.append(m.group(1))
        # Module without `crc` in its name but with a polynomial /
        # crc_out / crc_in port also counts.
        if _CRC_PORT_HINT_RE.search(text):
            # avoid double-counting when also matched by header re
            for hm in re.finditer(r'\bmodule\s+(\w+)\b', text):
                name = hm.group(1)
                if name not in found and "crc" in name.lower():
                    found.append(name)
    return (len(found) > 0), found


_CRC_OUT_USAGE_RE = re.compile(
    r'\b(crc_out|crc_dout|crc_result|crc_value|crc_q)\b', re.IGNORECASE
)

# v0.119.51 Wave 19 — CRC-byte-position context signals.
# A literal assigned to a packet sink that is being TX'd as the CRC byte
# of the response packet must be the dynamic CRC engine output, never a
# placeholder. Three signals identify "CRC byte position":
#   1. Enclosing FSM state value contains CRC / TX_CRC / RESP_CRC /
#      SEND_CRC (case-insensitive). Detected via:
#         - case arm head:        S_TX_CRC: begin / S_TX_CRC :
#         - next-state assignment: state <= S_TX_CRC;
#         - if-comparison:         if (state == S_TX_CRC) ...
#   2. LHS variable name itself is *crc_byte* / crc_data / crc_pos / *_crc_*
#      (the LHS is structurally the CRC byte register).
#   3. (Reserved) Conditional gated by counter == LAST_BYTE_INDEX while
#      in CRC state — currently subsumed by signal #1 since the case-arm
#      walk already covers it.
_CRC_STATE_NAME_RE = re.compile(
    r'\b(S_?[A-Z0-9_]*'           # optional S_ prefix + uppercase tokens
    r'(?:TX_?CRC|RESP_?CRC|SEND_?CRC|RSP_?CRC|REPLY_?CRC|OUT_?CRC|CRC_?TX|CRC_?OUT|CRC_?BYTE|CRC_?SEND)'
    r'[A-Z0-9_]*)\b',
    re.IGNORECASE,
)
# Bare-name CRC state (e.g. raw enum value in a `case` statement, no
# S_ prefix): TX_CRC / SEND_CRC / RESP_CRC / etc.
_CRC_STATE_BARE_RE = re.compile(
    r'\b(TX_?CRC|RESP_?CRC|SEND_?CRC|RSP_?CRC|REPLY_?CRC|OUT_?CRC|CRC_?TX|CRC_?OUT|CRC_?BYTE|CRC_?SEND)\b',
    re.IGNORECASE,
)
# LHS variable names that themselves indicate CRC-byte register.
_CRC_LHS_VAR_RE = re.compile(
    r'\b(\w*crc_byte\w*|crc_data|crc_pos|crc_out_reg|crc_tx_byte|tx_crc|tx_crc_byte|resp_crc_byte)\b',
    re.IGNORECASE,
)
# Case-arm head:  "S_TX_CRC: begin" or "S_TX_CRC :"
_CASE_ARM_HEAD_RE = re.compile(
    r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:'
)
# Next-state assignment:  state <= S_TX_CRC ;
_NEXT_STATE_RE = re.compile(
    r'\b(?:state|next_state|nstate|n_state|fsm_state|cur_state)\s*'
    r'(?:<=|=)\s*([A-Za-z_][A-Za-z0-9_]*)\s*[;,)]'
)
# state == S_TX_CRC comparison
_STATE_COMPARE_RE = re.compile(
    r'\bstate\s*==\s*([A-Za-z_][A-Za-z0-9_]*)'
)


def _find_crc_state_names_in_module(text: str) -> set:
    """Collect identifiers that look like CRC-byte FSM states declared
    somewhere in this module (typedef enum / parameter / localparam).
    Match anywhere the name appears; we filter against `_CRC_STATE_NAME_RE`
    or `_CRC_STATE_BARE_RE` so partial chip-specific suffixes pass too."""
    names = set()
    for m in _CRC_STATE_NAME_RE.finditer(text):
        names.add(m.group(1))
    for m in _CRC_STATE_BARE_RE.finditer(text):
        names.add(m.group(1))
    return names


def _line_in_crc_state_context(
    lines: List[str],
    target_lineno: int,
    crc_state_names: set,
    window: int = 40,
) -> tuple[bool, str]:
    """Walk up from `target_lineno` (1-indexed) up to `window` lines and
    determine whether the assignment is inside a CRC-byte state context.

    Returns (is_crc_context, matched_state_name).

    Heuristics, evaluated top-down within the window:
      a) Enclosing case arm head whose label matches a CRC-state name.
         Stop walking once we hit a `case` statement opener (we are in
         the right `case` block) OR another `case_arm:` head that ISN'T
         CRC (we are in a non-CRC arm).
      b) A next-state assignment in the SAME always_ff block that targets
         a CRC-state name BEFORE the literal line — i.e. the literal
         takes effect in the SAME cycle as `state <= S_TX_CRC;`. The
         agent intent is: "I'm transitioning to S_TX_CRC and at the
         same time clobbering tx_byte to a placeholder."
      c) `if (state == S_TX_CRC)` enclosing the literal.
    """
    start = max(0, target_lineno - 1 - window)
    end = target_lineno  # exclusive (literal line itself is at target_lineno-1)
    in_case_block = False
    for i in range(end - 1, start - 1, -1):
        ln = lines[i] if 0 <= i < len(lines) else ""

        # (b) next-state assignment to a CRC-state value
        for m in _NEXT_STATE_RE.finditer(ln):
            tgt = m.group(1)
            if tgt in crc_state_names or _CRC_STATE_BARE_RE.fullmatch(tgt) \
               or _CRC_STATE_NAME_RE.fullmatch(tgt):
                return True, tgt

        # (c) state == compare
        for m in _STATE_COMPARE_RE.finditer(ln):
            tgt = m.group(1)
            if tgt in crc_state_names or _CRC_STATE_BARE_RE.fullmatch(tgt) \
               or _CRC_STATE_NAME_RE.fullmatch(tgt):
                return True, tgt

        # (a) case-arm head — but only treat as authoritative if we
        # already saw `case (...)` opener above.
        head = _CASE_ARM_HEAD_RE.match(ln)
        if head and ln.strip().endswith(("begin", ":")):
            label = head.group(1)
            # exclude things like "default:" or signal-bit-select labels
            if label.lower() == "default":
                continue
            if label in crc_state_names or \
               _CRC_STATE_BARE_RE.fullmatch(label) or \
               _CRC_STATE_NAME_RE.fullmatch(label):
                return True, label
            # Hit a non-CRC case arm → literal is in a different arm → stop.
            # (we're walking UP, so the closest arm head that opens the
            # block containing our literal wins.)
            # But only stop if there's a "begin" — otherwise it might be
            # a constant declaration colon syntax.
            if ln.strip().endswith("begin"):
                return False, ""

        if re.search(r'\bcase\s*\(', ln):
            in_case_block = True
        if re.search(r'\balways_ff\b|\balways\b', ln):
            # Crossed an always-block boundary — stop.
            break

    _ = in_case_block  # currently unused; reserved for stricter mode
    return False, ""


def _find_crc_byte_position_literals(
    rtl_dir: Path,
    crc_module_names: List[str],
) -> List[Finding]:
    """v0.119.51 Wave 19 — detect literal assignments to packet sinks
    that occur in a "CRC byte position" context. This drops the
    Wave 11 trivial-literal exemption when the context is structurally
    a CRC-byte FSM state.
    """
    findings: List[Finding] = []
    crc_names_lc = {n.lower() for n in crc_module_names}
    # Match assignment of ANY 8-bit literal (incl. trivial values). We
    # also match `'h00` style without explicit width so single-byte
    # parameter assigns are caught.
    crc_pos_literal_re = re.compile(
        r'\b('
        + r'|'.join(re.escape(h) for h in _PACKET_SINK_HINTS)
        + r')\s*(?:\[[^\]]+\])?\s*(?:<=|=)\s*'
        + r'(?:8\s*\'\s*[hH]|\'\s*[hH])\s*([0-9A-Fa-f]{1,2})\b'
    )

    for p in _find_v_files(rtl_dir):
        try:
            raw = p.read_text(errors="replace")
        except OSError:
            continue
        text = _strip_comments(raw)

        # Skip CRC module's own source.
        own_modules = re.findall(r'\bmodule\s+(\w+)\b', text)
        if any(m.lower() in crc_names_lc for m in own_modules):
            continue

        crc_state_names = _find_crc_state_names_in_module(text)

        lines = text.split('\n')
        for lineno, line in enumerate(lines, 1):
            for match in crc_pos_literal_re.finditer(line):
                sink = match.group(1)
                lit = match.group(2).upper().zfill(2)

                # Signal #2: LHS variable name itself indicates CRC byte.
                lhs_is_crc = bool(_CRC_LHS_VAR_RE.search(line))

                # Signal #1: enclosing CRC-state context.
                in_crc_ctx, state_label = _line_in_crc_state_context(
                    lines, lineno, crc_state_names,
                )

                if not (lhs_is_crc or in_crc_ctx):
                    continue

                hint_state = state_label or "(LHS-name match)"
                findings.append(Finding(
                    "ERROR", "CRC_BYTE_POSITION_LITERAL",
                    f"In CRC byte position of response packet, the value "
                    f"MUST be the CRC module output (crc_out / crc_dout / "
                    f"crc_q / crc_result), not any literal. "
                    f"Sink '{sink}' assigned 8'h{lit} while FSM context "
                    f"is CRC-byte state '{hint_state}'. "
                    f"Hint: replace with `{sink} <= crc_out;` (or "
                    f"equivalent), and ensure crc_en has been pulsed for "
                    f"all packet bytes preceding this state.",
                    file=str(p), line=lineno,
                    details=line.strip()[:200],
                ))
    return findings


def _find_hardcoded_crc_literals(
    rtl_dir: Path,
    crc_module_names: List[str],
) -> List[Finding]:
    """v0.119.43 Wave 11: detect 8'hXX literals dropped into packet sinks
    while a CRC module is structurally present elsewhere in the project
    AND the consumer module never references the CRC output signal.

    The two-part trigger is intentional:
      1) CRC module exists somewhere → dynamic CRC is the design intent.
      2) Consumer module emits a non-trivial 8-bit literal on a packet
         sink AND never reads any ``crc_out`` / ``crc_dout`` / similar
         signal → the CRC engine is wired but not used.

    A consumer that legitimately mixes opcode / header bytes (e.g.
    ``resp_buf[0] <= 8'h75``) with dynamic ``resp_buf[3] <= crc_out`` is
    PASSed because the file references ``crc_out`` somewhere.

    The check skips:
      - The CRC module's own source file (literals there are POLYNOMIAL
        / INIT constants, not packet construction).
      - Trivial sentinels 00 / FF / AA / 55 (idle / reset / bus default).
    """
    findings: List[Finding] = []
    crc_names_lc = {n.lower() for n in crc_module_names}

    for p in _find_v_files(rtl_dir):
        try:
            raw = p.read_text(errors="replace")
        except OSError:
            continue
        text = _strip_comments(raw)

        # Skip the CRC module's own source file.
        own_modules = re.findall(r'\bmodule\s+(\w+)\b', text)
        if any(m.lower() in crc_names_lc for m in own_modules):
            continue

        # If the consumer does reference crc_out / crc_dout / similar,
        # then any literals on packet sinks are legitimate header /
        # opcode / length bytes and we exempt the file. The "wired but
        # not used" pattern requires the absence of the CRC output
        # signal in the consumer.
        if _CRC_OUT_USAGE_RE.search(text):
            continue

        lines = text.split('\n')
        for lineno, line in enumerate(lines, 1):
            for match in _PACKET_LITERAL_RE.finditer(line):
                sink = match.group(1)
                lit = match.group(2).upper().zfill(2)
                if lit in _TRIVIAL_LITERALS:
                    continue
                findings.append(Finding(
                    "ERROR", "HARDCODED_CRC_LITERAL",
                    f"CRC byte position appears hard-coded; suspect "
                    f"CRC module is wired but not used. "
                    f"Sink '{sink}' assigned 8'h{lit} on a packet-"
                    f"construction path while a CRC module "
                    f"({', '.join(crc_module_names) or 'unknown'}) "
                    f"exists elsewhere in the project but this module "
                    f"never reads crc_out. Replace the literal with the "
                    f"dynamic crc_out signal.",
                    file=str(p), line=lineno,
                    details=line.strip()[:200],
                ))
    return findings


def _load_waiver(project_dir: Path | None) -> bool:
    """Return True if waiver `crc_byte_intentionally_constant` (≥40 chars)
    is present in <project>/waivers.json."""
    if project_dir is None:
        return False
    wpath = project_dir / "waivers.json"
    if not wpath.exists():
        return False
    try:
        data = json.loads(wpath.read_text())
    except Exception:
        return False
    # #519 — via the ONE shared reader. This was `waived_steps or waivers`,
    # first-NON-EMPTY-wins: a file carrying entries under BOTH keys silently
    # dropped the `waivers` half. The shared reader returns the union, so no
    # entry is invisible because another key happened to be populated.
    waivers = _we.entries(data)
    if not isinstance(waivers, list):
        return False
    for w in waivers:
        if not isinstance(w, dict):
            continue
        name = (w.get("name") or w.get("waiver") or w.get("id") or "")
        reason = w.get("reason", "") or ""
        if str(name) == "crc_byte_intentionally_constant" and len(reason) >= 40:
            return True
    return False


def _find_v_files(rtl_dir: Path) -> List[Path]:
    return sorted(
        p for p in rtl_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in (".v", ".sv")
    )


def _strip_comments(src: str) -> str:
    out = []
    i = 0
    while i < len(src):
        if src[i:i+2] == '/*':
            end = src.find('*/', i + 2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end+2]))
            i = end + 2
        elif src[i:i+2] == '//':
            end = src.find('\n', i)
            if end == -1:
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


def _detect_rx_tx_spanning(text: str) -> bool:
    return bool(RX_STATE_RE.search(text)) and bool(TX_STATE_RE.search(text))


def _count_signal_assignments(text: str, pattern: 're.Pattern') -> int:
    total = 0
    for m in pattern.finditer(text):
        sig = m.group(1)
        assign_re = re.compile(rf'{re.escape(sig)}\s*<=\s*', re.IGNORECASE)
        total += len(assign_re.findall(text))
    return total


def _find_same_cycle_overlap(text: str, fname: str, escalate: bool = False) -> List[Finding]:
    """Detect lines where init and update are both asserted in the same
    always block branch (same-cycle overlap)."""
    findings = []
    lines = text.split('\n')

    init_sigs = set()
    update_sigs = set()
    for m in INIT_SIGNAL_RE.finditer(text):
        init_sigs.add(m.group(1))
    for m in UPDATE_SIGNAL_RE.finditer(text):
        update_sigs.add(m.group(1))

    if not init_sigs or not update_sigs:
        return findings

    for i_sig in init_sigs:
        for u_sig in update_sigs:
            i_assign = re.compile(
                rf'{re.escape(i_sig)}\s*<=\s*1', re.IGNORECASE
            )
            u_assign = re.compile(
                rf'{re.escape(u_sig)}\s*<=\s*1', re.IGNORECASE
            )
            for lineno, line in enumerate(lines, 1):
                if i_assign.search(line) and u_assign.search(line):
                    findings.append(Finding(
                        "ERROR", "SAME_LINE_OVERLAP",
                        f"CRC init '{i_sig}' and update '{u_sig}' both "
                        f"asserted on the same line — init may not "
                        f"complete before update feeds data.",
                        file=fname, line=lineno,
                    ))

            for lineno, line in enumerate(lines, 1):
                if not i_assign.search(line):
                    continue
                window = lines[lineno:lineno + 3]
                for offset, wline in enumerate(window):
                    if u_assign.search(wline):
                        ctx_start = max(0, lineno - 3)
                        ctx = lines[ctx_start:lineno]
                        in_same_branch = not any(
                            re.search(r'\belse\b|\bend\b', cl) for cl in ctx
                        )
                        if in_same_branch:
                            sev = "ERROR" if escalate else "WARN"
                            findings.append(Finding(
                                sev, "NEAR_CYCLE_OVERLAP",
                                f"CRC init '{i_sig}' at line {lineno} "
                                f"and update '{u_sig}' at line "
                                f"{lineno + offset + 1} are within "
                                f"1-3 lines in the same branch — "
                                f"verify at least 1-cycle separation "
                                f"between init deassert and update assert."
                                + (" [ESCALATED: RX/TX shared engine]" if escalate else ""),
                                file=fname, line=lineno,
                            ))
                        break
    return findings


def _find_shared_data_mux(text: str, fname: str, escalate: bool = False) -> List[Finding]:
    """Detect if CRC data input has multiple assignment sources (shared mux)."""
    findings = []
    data_sigs = set()
    for m in CRC_DATA_RE.finditer(text):
        data_sigs.add(m.group(1))

    for sig in data_sigs:
        assign_re = re.compile(
            rf'{re.escape(sig)}\s*<=\s*', re.IGNORECASE
        )
        assign_locs = []
        for lineno, line in enumerate(text.split('\n'), 1):
            if assign_re.search(line):
                assign_locs.append((lineno, line.strip()))

        if len(assign_locs) >= 3:
            sev = "ERROR" if escalate else "WARN"
            findings.append(Finding(
                sev, "SHARED_CRC_DATA_MUX",
                f"CRC data signal '{sig}' has {len(assign_locs)} "
                f"assignment sites — likely shared between RX and TX "
                f"paths. Verify the mux cannot glitch between domains "
                f"during a single CRC computation."
                + (" [ESCALATED: RX/TX shared engine with ≥3 data + ≥2 init sites]" if escalate else ""),
                file=fname, line=assign_locs[0][0],
                details=json.dumps([
                    {"line": ln, "code": c} for ln, c in assign_locs[:5]
                ]),
            ))
    return findings


def audit(rtl_dir: Path, project_dir: Path | None = None) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding("ERROR", "IO", f"RTL directory not found: {rtl_dir}"))
        return findings, {}

    # v0.119.43 Wave 11 — hard-coded CRC literal detection.
    crc_present, crc_names = _project_has_crc_module(rtl_dir)
    waived_literal = _load_waiver(project_dir)
    if crc_present and not waived_literal:
        lit_findings = _find_hardcoded_crc_literals(rtl_dir, crc_names)
        findings.extend(lit_findings)
        # v0.119.51 Wave 19 — CRC-byte-position literal (drops trivial
        # exemption when the literal is in a CRC-byte FSM state context).
        crc_pos_findings = _find_crc_byte_position_literals(rtl_dir, crc_names)
        findings.extend(crc_pos_findings)

    crc_modules: List[str] = []
    checked = 0

    for p in _find_v_files(rtl_dir):
        try:
            text = _strip_comments(p.read_text(errors="replace"))
        except OSError:
            continue
        fname = str(p)

        has_init = bool(INIT_SIGNAL_RE.search(text))
        has_update = bool(UPDATE_SIGNAL_RE.search(text))

        if not (has_init and has_update):
            continue

        crc_modules.append(fname)
        checked += 1

        silenced = bool(SILENCE_RE.search(p.read_text(errors="replace")))
        if silenced:
            continue

        data_assigns = _count_signal_assignments(text, CRC_DATA_RE)
        init_assigns = _count_signal_assignments(text, INIT_SIGNAL_RE)
        rx_tx = _detect_rx_tx_spanning(text)
        escalate = data_assigns >= 3 and init_assigns >= 2 and rx_tx

        findings.extend(_find_same_cycle_overlap(text, fname, escalate))
        findings.extend(_find_shared_data_mux(text, fname, escalate))

    return findings, {"crc_modules": crc_modules, "checked": checked}


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify shared CRC engine init/update isolation."
    )
    # Two entry points: `--rtl-dir <dir>` for spot-checking a single
    # RTL directory (3rd-party imports, ad-hoc audits) or a positional
    # `<project_dir>` (matches flow_compliance_check structural-gate
    # invocation convention). When a project dir is given we auto-detect
    # the rtl/ subdir AND honor a waiver in <project>/waivers.json.
    ap.add_argument("project_dir", nargs="?",
                    help="Project directory (auto-detects rtl/, src/, hdl/).")
    ap.add_argument("--rtl-dir",
                    help="Explicit RTL directory (overrides project auto-detect).")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    project_dir: Path | None = None
    if args.rtl_dir:
        rtl_dir = Path(args.rtl_dir)
    elif args.project_dir:
        project_dir = Path(args.project_dir)
        if not project_dir.is_dir():
            print(f"ERROR: project_dir not a directory: {project_dir}",
                  file=sys.stderr)
            return 2
        rtl_dir = None
        for cand in ("phase2/stage1/rtl", "rtl", "src", "hdl"):
            d = project_dir / cand
            if d.is_dir() and (any(d.rglob("*.v")) or any(d.rglob("*.sv"))):
                rtl_dir = d
                break
        if rtl_dir is None:
            # Project root may itself contain RTL files
            if any(project_dir.glob("*.v")) or any(project_dir.glob("*.sv")):
                rtl_dir = project_dir
            else:
                # No RTL → input-missing per structural-gate convention.
                return 2
    else:
        ap.error("either project_dir or --rtl-dir must be given")
        return 2

    try:
        findings, summary = audit(rtl_dir, project_dir=project_dir)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    is_pass = not any(f.severity == "ERROR" for f in findings)
    report = {
        "program": "crc_engine_isolation_check",
        "version": "1.3.0",
        "rtl_dir": str(rtl_dir),
        "summary": {"pass": is_pass, "findings_count": len(findings), **summary},
        "findings": [asdict(f) for f in findings],
    }
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(out)
    # v0.119.43: emit a one-line FAIL summary first so callers like
    # flow_compliance_check (which captures only the first stdout line for
    # its `FAIL: <gate> — <line>` aggregate) see an actionable message.
    if not is_pass:
        # Priority: CRC-byte-position (Wave 19) > hard-coded literal
        # (Wave 11) > generic ERROR. CRC-byte-position is the most
        # actionable for fresh-agent debug since it points directly at
        # the placeholder line.
        first_err = next(
            (f for f in findings if f.severity == "ERROR"
             and f.category == "CRC_BYTE_POSITION_LITERAL"),
            None,
        )
        if first_err is None:
            first_err = next(
                (f for f in findings if f.severity == "ERROR"
                 and f.category == "HARDCODED_CRC_LITERAL"),
                None,
            )
        if first_err is None:
            first_err = next(
                (f for f in findings if f.severity == "ERROR"), None
            )
        if first_err is not None:
            loc = (f"{first_err.file}:{first_err.line}"
                   if first_err.file else "(no location)")
            print(f"FAIL: {first_err.category} at {loc} — "
                  f"{first_err.message[:200]}")
    print(out)
    if any(f.category == "IO" for f in findings):
        return 2
    return 0 if is_pass else 1


if __name__ == "__main__":
    sys.exit(main())
