#!/usr/bin/env python3
"""slave_tx_no_device_break_check.py — Wave 25/34 silent-bug gate.

In a half-duplex single-wire request-response protocol (AID class —
<half-duplex-tester> / <chip-class> / similar), the device/slave's response path MUST
NOT prepend its own BR (Break) pulse before transmitting response
bits. The host master already sent a BR at the beginning of the
frame as the framing marker; the device just answers within the
tSRS turnaround. Adding a SECOND device-side BR is a silent bug:
host firmware reads the spurious LOW pulse as another BR/IBT
abnormality, resets its frame state, and discards the device's
reply — host firmware sees the SEND_TEST async frame all-padding
from byte[6] onward (typical verdict byte[6]=0x02).

Wave 34 (v0.119.66) escape — v0.119.65 fresh-agent renamed the
BR-emit state from `S_TX_BR` to `S_TX_HEADER` and used a custom
constant `T_TX_HEADER_TICKS = 690` to drive `id_bus_drive_low <=
1'b1` for 690 ticks (≈13.8 µs), exactly matching real BR width.
Wave 33 substring matching of state name and constant name missed
both. Wave 34 adds a behavior-based detector: any FSM state arm
that asserts an OE-class LHS AND waits on a counter compared to a
constant whose RESOLVED INTEGER VALUE is ≥ project's BR_MIN-class
threshold ticks → FAIL. State name and constant name no longer
matter; the duration of LOW-drive in ticks is the verdict.

Detection
=========
1. Locate FSM RTL file (heuristic: filename or module name contains
   `main_fsm` / `fsm` / `mac` / `protocol_fsm`, AND the file declares
   protocol-style state names matching `S_RX*` / `S_TX*` / `S_TURN*`
   / `S_WAIT_TURN`). Skip when no such file exists.

2. Walk the case-statement / always_ff / always_comb FSM body.

3. Trace the TX entry path: from a turnaround state
   (`S_WAIT_TURN` / `S_TURN` / `S_TURNAROUND_WAIT` / `S_TSRS*` /
   `S_RX_DONE` / `S_VALIDATE`) toward the first state that drives
   the bus LOW (`tx_oe`/`id_tx_oe`/`bus_oe`/`tx_drive_low` <= 1'b1)
   and starts emitting bit cells (`S_TX_BIT*`).

4. **FAIL** when the entry path between the turnaround state and
   the first TX_BIT state includes an intermediate state that:
     a. has a state name matching `*_TX_BR` / `*_BREAK_TX` /
        `*_LEADING_BR` / `*_DEVICE_BREAK` / `*_TX_BREAK` /
        `*_WAKE_TX` / `*_INIT_LOW` (case-insensitive); OR
     b. asserts a bus LOW driver inside its arm (`<oe> <= 1'b1`
        on a name we believe is the bus drive enable); AND
     c. has a counter that runs against a constant matching the
        BR_MIN class — synonyms:
        `T_BR_MIN_TICKS`, `BR_MIN`, `T_BR_TX_TICKS`,
        `T_TWK_BR_TX_TICKS`, `T_BR_RX_MIN_TICKS`, `t_br_min_*`,
        `BREAK_LEN`, `BR_LEN`, `TX_BR_TICKS`.

5. Specifically catches the v0.119.56 pattern: a state named
   `S_TX_BR` that drives `id_tx_oe <= 1'b1` for
   `T_TWK_BR_TX_TICKS` (1200 ticks ≈ 24 µs) immediately before
   the first TX_BIT state.

6. **PASS** when: TX path goes directly from the turnaround state
   (after tSRS countdown) into the bit-transmission state without
   any LOW-pulse plateau ≥ BR_MIN.

7. **PASS_WITH_WAIVER** when waiver `slave_tx_break_intentional`
   exists in `<project>/waivers.json` and the rationale string is
   ≥ 40 chars.

Chip-AGNOSTIC: synonyms only; no <chip-class> / <half-duplex-tester> / specific pin
or constant value hardcoded.

Exit codes
==========
0 — PASS / SKIP / PASS_WITH_WAIVER
1 — FAIL
2 — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl

WAIVER_KEY = "slave_tx_break_intentional"
WAIVER_MIN_LEN = 40

# Wave 36 — inout id_bus regex (kept local to avoid cross-module
# coupling; mirrors ic_class_profile._INOUT_ID_BUS_RE).
_INOUT_ID_BUS_RE_LOCAL = re.compile(
    r"\binout\b[^,;)]*\b(id_bus|id_io|idbus|id_data)\b",
    re.IGNORECASE,
)

# State-name patterns.
_TURN_STATE_RE = re.compile(
    r"\bS_(?:WAIT_TURN|TURN|TURNAROUND[A-Z_]*|TSRS[A-Z_]*|"
    r"RX_DONE|VALIDATE|VALIDATE_CRC)\b",
    re.IGNORECASE,
)
_TX_BIT_STATE_RE = re.compile(
    r"\bS_TX_(?:BIT[A-Z_0-9]*|BYTE[A-Z_0-9]*|DATA[A-Z_0-9]*|"
    r"PAYLOAD[A-Z_0-9]*)\b",
    re.IGNORECASE,
)
# BR-emit state name pattern.
_BR_STATE_RE = re.compile(
    r"\bS_(?:TX_BR|BREAK_TX|LEADING_BR|DEVICE_BREAK|TX_BREAK|"
    r"WAKE_TX|INIT_LOW|TX_LEAD_BR|RESPONSE_BR)\b",
    re.IGNORECASE,
)
# Wave 33 (v0.119.65) — match by token presence rather than the
# brittle whole-word alternation that missed `T_TB_TICKS` (the
# v0.119.64 escape). Any constant whose UPPER-cased name contains
# one of the BR-class keywords below is treated as a BR_MIN-class
# constant. Chip-AGNOSTIC: the keyword list is generic protocol
# nomenclature, no chip / vendor / pin name.
_BR_MIN_CONST_KEYWORDS: tuple[str, ...] = (
    "BR_MIN",
    "BR_TICKS",
    "TB_TICKS",     # T_TB_TICKS (Wave 33 escape constant)
    "T_TB",
    "T_BR",
    "BR_LOW",
    "TBR_MIN",
    "BREAK_MIN",
    "T_BREAK",
    "BREAK_LEN",
    "BR_LEN",
    "TWK_BR",       # legacy T_TWK_BR_TX_TICKS family
    "WAKE_BR_TX",
    "DEVICE_BR",
    "RESPONSE_BR",
    "LP_BR",
)


def _is_br_min_constant(name: str) -> bool:
    """Wave 33: True if `name` is a BR_MIN-class timer constant.

    Chip-AGNOSTIC token-based test: any UPPER-cased name containing
    one of `_BR_MIN_CONST_KEYWORDS` substrings qualifies. Catches
    `T_BR_MIN_TICKS`, `BR_MIN`, `T_BR_TX_TICKS`, `T_TWK_BR_TX_TICKS`,
    `T_TB_TICKS` (v0.119.64 escape), `BREAK_LEN`, `T_BREAK_TX_TICKS`,
    `LP_BR_MIN`, etc.
    """
    if not name:
        return False
    upper = name.upper()
    return any(kw in upper for kw in _BR_MIN_CONST_KEYWORDS)


# Wave 33 — keep _BR_MIN_CONST_RE for legacy callers but redefine
# as a permissive substring matcher equivalent to _is_br_min_constant.
_BR_MIN_CONST_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\b",
)


# tx-OE-style LHS naming heuristic (chip-agnostic).
#
# Wave 33 (v0.119.65): the previous whole-word `\btx_oe\b` style
# pattern missed `tx_oe_low` (the v0.119.64 escape) — `\b` between
# `e` and `_` is NOT a word boundary because both sides are word
# chars. Switch to substring/IGNORECASE matching: any LHS containing
# one of the OE-class tokens below is treated as a bus-LOW driver.
_OE_LHS_TOKENS: tuple[str, ...] = (
    "tx_oe",
    "id_tx_oe",
    "bus_oe",
    "drive_low",
    "drv_low",
    "tx_drive_low",
    "id_oe",
    "pad_oe",
    "bus_low",
    "tx_low",
    "id_low",
    "oe_low",
    "drive_lo",
)


def _is_oe_lhs(name: str) -> bool:
    """Wave 33 chip-AGNOSTIC OE-class LHS detector.

    Any LHS containing an `oe`/`drive_low`/`bus_low`/`tx_low`-class
    token is treated as a bus-LOW driver. Catches `tx_oe_low`
    (v0.119.64 escape), `id_tx_oe`, `bus_drive_low`, etc.
    """
    if not name:
        return False
    lower = name.lower()
    return any(tok in lower for tok in _OE_LHS_TOKENS)


# Permissive regex retained for back-compat with any external caller;
# the actual decision lives in `_is_oe_lhs`.
_OE_LHS_RE = re.compile(
    r"\b([a-z_][a-z0-9_]*)\b",
    re.IGNORECASE,
)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _find_rtl_files(project: Path) -> List[Path]:
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.exists():
        return []
    out: List[Path] = []
    for p in rtl_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".v", ".sv", ".svh"):
            out.append(p)
    return sorted(out)


def _is_fsm_file(path: Path, text: str) -> bool:
    name = path.stem.lower()
    if any(h in name for h in ("main_fsm", "fsm", "mac", "protocol_fsm",
                               "ctrl_fsm")):
        # Confirm it has protocol-style state names.
        if (_TURN_STATE_RE.search(text)
                or _TX_BIT_STATE_RE.search(text)
                or _BR_STATE_RE.search(text)):
            return True
    # A non-fsm-named file that still declares many S_RX*/S_TX* states
    # also qualifies (some agents put the FSM in a file with another
    # name).
    if (len(_TX_BIT_STATE_RE.findall(text)) >= 1
            and _TURN_STATE_RE.search(text)):
        return True
    return False


def _arm_bodies(text: str) -> List[Tuple[str, str, int]]:
    """Return list of (state_name, arm_body, line_no) for each
    case-arm `<state_name>: begin ... end` (or single-line form).
    Whole-state body (between this state header and the next) is the
    arm_body — used for counter / OE detection.
    """
    arms: List[Tuple[str, str, int]] = []
    # Match case-arm head: `S_FOO: begin` (also single-line `S_FOO:`).
    arm_head_re = re.compile(
        r"^[ \t]*(S_[A-Za-z0-9_]+)\s*:\s*(begin\b|[A-Za-z_])",
        re.MULTILINE,
    )
    matches = list(arm_head_re.finditer(text))
    lines = text.splitlines()
    line_starts = [0]
    for ln in lines:
        line_starts.append(line_starts[-1] + len(ln) + 1)

    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        line_no = sum(1 for c in text[:start] if c == "\n") + 1
        arms.append((name, body, line_no))
    return arms


def _find_low_drive_in_arm(body: str) -> bool:
    """True iff the arm asserts a bus-LOW driver: `<oe-like> <= 1'b1`
    or `... = 1'b1` with the LHS matching OE-naming heuristic.

    Wave 33 (v0.119.65): substring/token match (`_is_oe_lhs`) so
    `tx_oe_low`, `id_tx_oe_low`, `bus_drive_low_n`, etc. are caught.
    """
    for m in re.finditer(
        r"\b([a-z_][a-z0-9_]*)\s*<=\s*1'b1\s*;",
        body,
        re.IGNORECASE,
    ):
        lhs = m.group(1)
        if _is_oe_lhs(lhs):
            return True
    # Blocking-assignment variant.
    for m in re.finditer(
        r"\b([a-z_][a-z0-9_]*)\s*=\s*1'b1\s*;",
        body,
        re.IGNORECASE,
    ):
        lhs = m.group(1)
        if _is_oe_lhs(lhs):
            return True
    return False


def _find_counter_wait_constant(body: str) -> Optional[str]:
    """Wave 33 fallback: return the FIRST constant identifier on the
    RHS of any `cnt-style </<=/>=/>/== CONST` comparison in the arm.

    Used by the fallback rule (state name in BR/BREAK/LEADING family
    AND a counter-wait condition) regardless of constant whitelist.
    """
    for m in re.finditer(
        r"(?:<=|>=|<|>|==)\s*(?P<const>[A-Za-z_][A-Za-z0-9_]*)"
        r"\s*(?:\[[^\]]*\])?",
        body,
    ):
        const = m.group("const")
        # Skip obvious non-constants: lowercase identifiers (signals)
        # are unlikely to be timer-class constants. Heuristic: at
        # least one upper-case letter.
        if any(c.isupper() for c in const) and "_" in const:
            return const
    return None


def _find_br_min_counter(body: str) -> Optional[str]:
    """If the arm has `<cnt> < <BR_MIN_const>` (or `>= <BR_MIN_const>` /
    `+1 >= <BR_MIN_const>` etc.), return the constant name. Otherwise
    None.

    Wave 33 (v0.119.65): substring keyword match so `T_TB_TICKS`,
    `T_BR_MIN_TICKS`, `T_TWK_BR_TX_TICKS`, `BREAK_LEN`, `LP_BR_MIN`,
    `T_BREAK_TX_TICKS`, etc. all qualify.
    """
    for m in re.finditer(
        r"(?:<=|>=|<|>|==)\s*(?P<const>[A-Za-z_][A-Za-z0-9_]*)"
        r"\s*(?:\[[^\]]*\])?",
        body,
    ):
        const = m.group("const")
        if _is_br_min_constant(const):
            return const
    return None


def _collect_localparams(text: str) -> dict[str, int]:
    """Wave 34: collect every `localparam [type] NAME = VALUE;` and
    `parameter NAME = VALUE;` into a name → integer-value map.

    Resolves both decimal (e.g. `690`), sized (`16'd690`, `8'h2B`),
    and parameter-of-parameter chains (one-pass — sufficient for
    typical RTL).
    """
    consts: dict[str, int] = {}

    # Two passes so a localparam that references another localparam
    # earlier in the file resolves correctly.
    for _ in range(2):
        for m in re.finditer(
            r"\b(?:localparam|parameter)\b\s*"
            r"(?:\[[^\]]*\]\s*)?"
            r"(?:int\s+|integer\s+|logic\s*(?:\[[^\]]*\])?\s+|"
            r"reg\s*(?:\[[^\]]*\])?\s+|bit\s*(?:\[[^\]]*\])?\s+)?"
            r"(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<rhs>[^;]+?);",
            text,
        ):
            name = m.group("name")
            rhs = m.group("rhs").strip()
            v = _resolve_int_literal_or_const(rhs, consts)
            if v is not None:
                consts[name] = v

    return consts


def _resolve_int_literal_or_const(
    rhs: str, consts: dict[str, int]
) -> Optional[int]:
    """Resolve a Verilog integer literal or a previously-declared
    localparam name. Returns None if it cannot be reduced to int.
    """
    rhs = rhs.strip()
    # Strip a `[15:0]` slice suffix sometimes used in compares.
    rhs = re.sub(r"\s*\[[^\]]*\]\s*$", "", rhs).strip()

    # Sized literal: <width>'<base><digits>
    m = re.match(
        r"^\s*\d*\s*'\s*([sS])?\s*([dDhHbBoO])\s*([0-9a-fA-F_]+)\s*$",
        rhs,
    )
    if m:
        base = m.group(2).lower()
        digits = m.group(3).replace("_", "")
        try:
            if base == "d":
                return int(digits, 10)
            if base == "h":
                return int(digits, 16)
            if base == "b":
                return int(digits, 2)
            if base == "o":
                return int(digits, 8)
        except ValueError:
            return None

    # Plain decimal
    if re.match(r"^-?\d+$", rhs):
        try:
            return int(rhs, 10)
        except ValueError:
            return None

    # Hex literal: 0xNN
    if re.match(r"^0[xX][0-9a-fA-F_]+$", rhs):
        try:
            return int(rhs.replace("_", ""), 16)
        except ValueError:
            return None

    # Identifier — look up in consts
    m = re.match(r"^([A-Za-z_]\w*)$", rhs)
    if m and m.group(1) in consts:
        return consts[m.group(1)]
    return None


def _resolve_compare_constant_value(
    rhs_token: str, consts: dict[str, int]
) -> Optional[int]:
    """Wave 34: given the RHS of a `cnt >= X` style compare, return
    the integer value of X (whether X is a literal or a parameter
    name). Strips trailing `[15:0]`-style slices."""
    return _resolve_int_literal_or_const(rhs_token, consts)


def _resolve_br_min_threshold(consts: dict[str, int]) -> Optional[int]:
    """Wave 34: locate the project's BR_MIN-class threshold value in
    ticks. Returns the smallest BR_MIN-class constant value found
    (the threshold above which a LOW pulse is read as BR by the
    host classifier) or None if no such constant.
    """
    candidates: list[int] = []
    for name, val in consts.items():
        if not _is_br_min_constant(name):
            continue
        # We want the lower edge of the BR window, so prefer names
        # ending in _MIN / _MIN_TICKS / _MIN_NS. If none, accept any
        # BR-class constant.
        candidates.append(val)
    if not candidates:
        return None
    # Use the smallest as the threshold — any LOW ≥ this value is
    # classified BR by host.
    return min(candidates)


def _state_low_drive_duration(
    body: str, consts: dict[str, int]
) -> Optional[int]:
    """Wave 34: if the FSM state arm body asserts a bus-LOW driver
    AND has a counter wait condition against a resolvable integer
    constant N, return N (in ticks). Otherwise None.
    """
    if not _find_low_drive_in_arm(body):
        return None
    # Find counter compare: `<cnt-like> [+ <expr>]? <op> <const>`
    # where <op> is >= / > / == / <= / <.
    # We want the threshold the LOW-drive is held against.
    candidate_durations: list[int] = []
    for m in re.finditer(
        r"\b(?:cnt|counter|tick_cnt|low_cnt|tx_low_cnt|tx_cnt|"
        r"hdr_cnt|tx_header_cnt|br_cnt|break_cnt|preamble_cnt|"
        r"lead_cnt|leading_cnt|drive_cnt|drv_cnt)\b"
        r"(?:\s*\+\s*\d+\s*'?[dh]?\d*)?"  # optional `+ 1` or `+ 16'd1`
        r"\s*(?:>=|>|==|<=|<)\s*(?P<rhs>[A-Za-z_]\w*"
        r"(?:\s*\[[^\]]*\])?|\d+\s*'?\s*[sdhboSDHBO]?\s*[0-9a-fA-F_]+|"
        r"\d+|0[xX][0-9a-fA-F_]+)",
        body,
        re.IGNORECASE,
    ):
        rhs = m.group("rhs").strip()
        v = _resolve_compare_constant_value(rhs, consts)
        if v is not None and v > 0:
            candidate_durations.append(v)

    if not candidate_durations:
        return None
    # Use the largest — that's the duration the state's LOW-drive
    # plateau actually waits for before transitioning out.
    return max(candidate_durations)


def _l8_br_min_ticks(project: Path) -> Optional[int]:
    """Wave 34: read L8.rx_classifier_ticks.br_min from
    generated_docs/L8*.json (chip-agnostic). Returns None when the
    L doc is absent or doesn't carry the field.
    """
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if not d.is_dir():
            continue
        for cand in sorted(d.glob("L8*.json")):
            try:
                j = json.loads(cand.read_text(errors="ignore"))
            except Exception:
                continue
            for path in (
                ("rx_classifier_ticks", "br_min"),
                ("rx_classifier", "br_min"),
                ("br_min",),
                ("br_min_ticks",),
            ):
                cur: object = j
                ok = True
                for k in path:
                    if isinstance(cur, dict) and k in cur:
                        cur = cur[k]
                    else:
                        ok = False
                        break
                if ok:
                    try:
                        v = int(cur)  # type: ignore[arg-type]
                        if v > 0:
                            return v
                    except (TypeError, ValueError):
                        continue
    return None


def _next_state_in_arm(body: str) -> Optional[str]:
    """Return the FIRST `state <= S_FOO;` target found in the arm,
    treating the typical "elapsed-counter then transition" pattern.
    For a BR-emit state, this is usually the first TX_BIT state.
    """
    targets = re.findall(
        r"\bstate\s*<=\s*(S_[A-Za-z0-9_]+)\s*;", body
    )
    for t in targets:
        # Skip same-state self-loops to find the actual successor.
        return t
    return None


def _waived(project: Path) -> Tuple[bool, str]:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
    except Exception:
        return False, ""
    raw = d.get(WAIVER_KEY)
    if isinstance(raw, str) and len(raw.strip()) >= WAIVER_MIN_LEN:
        return True, raw.strip()
    if isinstance(raw, dict):
        rationale = raw.get("rationale") or raw.get("reason") or ""
        if isinstance(rationale, str) and \
           len(rationale.strip()) >= WAIVER_MIN_LEN:
            return True, rationale.strip()
    return False, ""


_NON_AID_PROTOCOL_TOKENS: tuple[str, ...] = (
    "lin", "kwp2000", "kwp_2000", "fast_init", "5_baud_init",
    "k_line", "kline", "iso14230", "iso_14230", "iso9141",
)


def _l2_protocol_blob(project: Path) -> str:
    """Return concatenated lower-case L2 protocol/interface text."""
    for sub in ("phase1/generated_docs", "generated_docs", "l_docs"):
        d = project / sub
        if not d.is_dir():
            continue
        for cand in sorted(d.glob("L2*.json")):
            try:
                j = json.loads(cand.read_text(errors="ignore"))
            except Exception:
                continue
            parts: list[str] = []
            for path in (
                ("protocol_type",),
                ("protocol",),
                ("interface_type",),
                ("frs_doc", "protocol_type"),
                ("frs_doc", "interface"),
                ("physical_layer", "interface"),
            ):
                cur: object = j
                ok = True
                for k in path:
                    if isinstance(cur, dict) and k in cur:
                        cur = cur[k]
                    else:
                        ok = False
                        break
                if ok and isinstance(cur, str) and cur:
                    parts.append(cur.lower())
            if parts:
                return " ".join(parts)
    return ""


def _l8_has_br_min(project: Path) -> bool:
    """Wave 36 — True iff L8.rx_classifier_ticks.br_min is present."""
    return _l8_br_min_ticks(project) is not None


def inspect(project: Path) -> Tuple[List[str], List[str], dict]:
    failures: List[str] = []
    warnings: List[str] = []
    summary: dict = {}

    rtl = _find_rtl_files(project)
    if not rtl:
        summary["skip_reason"] = "no rtl/ directory"
        return failures, warnings, summary

    # Wave 36 (v0.119.68) — protocol-class guard.  This gate is
    # specific to AID-class half-duplex single-wire request-response
    # framing.  LIN / KWP2000 / fast_init / K-line / ISO14230 use
    # different break semantics (master-side break is the framing
    # marker, not the slave-reply break).  Skip when L2 says one of
    # those.  Also skip when neither L8.rx_classifier_ticks.br_min
    # exists nor an inout id_bus is present — the static rule has
    # nothing to anchor against.
    proto_blob = _l2_protocol_blob(project)
    for tok in _NON_AID_PROTOCOL_TOKENS:
        if tok in proto_blob:
            # Wave 42 (v0.119.70) / SF4 — fault-injection hardening.
            # If L2.protocol_type names a non-AID half-duplex protocol
            # but the RTL still exposes an `inout id_bus` (i.e. AID-
            # class single-wire bidirectional pin), the project has a
            # protocol-type / RTL inconsistency.  FAIL instead of
            # silently SKIPping.
            has_inout_id_bus = False
            for f in rtl:
                try:
                    if _INOUT_ID_BUS_RE_LOCAL.search(
                            f.read_text(errors="ignore")):
                        has_inout_id_bus = True
                        break
                except OSError:
                    continue
            if has_inout_id_bus:
                failures.append(
                    f"FAIL — L2.protocol_type='{tok}' (non-AID), but "
                    f"RTL exposes inout id_bus (AID-class hardware). "
                    f"protocol-type / RTL inconsistency: either L2 is "
                    f"wrong or the RTL pin is wrong. Wave 42 / SF4 "
                    f"fault-injection hardening — fail-closed instead "
                    f"of silent SKIP."
                )
                summary["fault_injection_caught"] = (
                    f"L2={tok} but RTL has inout id_bus")
                return failures, warnings, summary
            summary["skip_reason"] = (
                f"L2.protocol_type indicates '{tok}' which is NOT an "
                f"AID-class half-duplex protocol; gate not applicable"
            )
            return failures, warnings, summary

    # Wave 36 — secondary SKIP: if L2 explicitly says SPI / UART /
    # I2C AND there's no inout id_bus AND L8 has no br_min, the gate
    # has nothing to anchor against.  Anchored only on positive
    # SPI/UART/I2C evidence — fail-closed otherwise.
    if any(tok in proto_blob for tok in ("spi", "uart", "i2c", "rs_232",
                                         "rs232", "smbus")):
        has_inout_id_bus = False
        for f in rtl:
            try:
                if _INOUT_ID_BUS_RE_LOCAL.search(
                        f.read_text(errors="ignore")):
                    has_inout_id_bus = True
                    break
            except OSError:
                continue
        if not _l8_has_br_min(project) and not has_inout_id_bus:
            summary["skip_reason"] = (
                f"L2 protocol type matches non-half-duplex synonym "
                f"in `{proto_blob[:60]}...` and no inout id_bus / "
                f"L8.br_min anchor — AID-class gate not applicable"
            )
            return failures, warnings, summary

    fsm_candidates: List[Tuple[Path, str]] = []
    for f in rtl:
        try:
            raw = f.read_text(errors="ignore")
        except OSError:
            continue
        text = _strip_comments(raw)
        if _is_fsm_file(f, text):
            fsm_candidates.append((f, text))

    if not fsm_candidates:
        summary["skip_reason"] = (
            "no FSM RTL file found (heuristic: main_fsm/fsm/mac in "
            "name + S_RX*/S_TX*/S_TURN* states)"
        )
        return failures, warnings, summary

    summary["fsm_files"] = [str(f.relative_to(project))
                            for f, _ in fsm_candidates]

    # Wave 34 — behavior-based detection setup. Collect all
    # localparams across every RTL file (constants may live in a
    # shared `0_rtl_constants_pkg.sv` or similar).
    all_consts: dict[str, int] = {}
    for f in rtl:
        try:
            raw = f.read_text(errors="ignore")
        except OSError:
            continue
        all_consts.update(_collect_localparams(_strip_comments(raw)))
    summary["localparam_count"] = len(all_consts)

    # Wave 34 — choose BR_MIN threshold in ticks. Priority: project's
    # own L8.rx_classifier_ticks.br_min, else the smallest BR_MIN-class
    # localparam in the RTL.
    br_min_ticks = _l8_br_min_ticks(project)
    if br_min_ticks is None:
        br_min_ticks = _resolve_br_min_threshold(all_consts)
    summary["br_min_ticks"] = br_min_ticks

    for f, text in fsm_candidates:
        try:
            rel = f.relative_to(project)
        except ValueError:
            rel = f

        arms = _arm_bodies(text)
        if not arms:
            continue

        # Build state-name → (body, line_no) map.
        arm_by_name = {n: (b, ln) for (n, b, ln) in arms}

        # For every BR-named state that exists in the FSM, decide
        # whether it is a violation.
        for state_name, body, line_no in arms:
            if not _BR_STATE_RE.search(state_name):
                continue

            # Heuristic: BR-named state with LOW drive + BR_MIN counter
            # → silent device-side BR.
            has_low = _find_low_drive_in_arm(body)
            br_const = _find_br_min_counter(body)
            next_state = _next_state_in_arm(body)
            transitions_to_tx_bit = (
                next_state is not None
                and bool(_TX_BIT_STATE_RE.search(next_state))
            )

            if has_low and br_const is not None:
                tail = (
                    f" → next state `{next_state}`"
                    if transitions_to_tx_bit else ""
                )
                failures.append(
                    f"SLAVE_TX_DEVICE_BREAK_PRESENT — {rel}:{line_no}: "
                    f"FSM state `{state_name}` drives the bus LOW "
                    f"and waits for `{br_const}` ticks before bit "
                    f"transmission{tail}. In half-duplex single-wire "
                    f"request-response protocols (AID class), the "
                    f"device/slave reply must NOT prepend its own BR "
                    f"— host already sent BR at frame start; a second "
                    f"LOW pulse ≥ BR_MIN is read by host as a frame "
                    f"abnormality and the device's reply is "
                    f"discarded. Remove the state and let the FSM go "
                    f"directly from the turnaround state into the "
                    f"first TX_BIT state. See rig spec Layer 14."
                )
                continue

            # Wave 33 (v0.119.65) fallback rule — fires on the
            # v0.119.64 escape pattern. Trigger conditions (ALL):
            #   * state name matches BR / BREAK / LEADING family
            #     (already true in this loop)
            #   * arm body contains a LOW-drive assignment (any LHS
            #     matching `_OE_LHS_TOKENS`)
            #   * arm body contains a counter-wait condition (cnt
            #     compared with any constant identifier — even one
            #     not in the BR_MIN keyword list)
            #   * next state is a TX-bit / TX-low / TX-first family
            # No constant whitelist required — state name alone
            # (BR / BREAK / LEADING / DEVICE_BREAK / WAKE_TX) is
            # sufficient evidence the LOW pulse is a device-side BR.
            counter_const = _find_counter_wait_constant(body)
            tx_followup_re = re.compile(
                r"\bS_(?:TX_(?:BIT[A-Z_0-9]*|LOW[A-Z_0-9]*|"
                r"FIRST[A-Z_0-9]*|BYTE[A-Z_0-9]*|DATA[A-Z_0-9]*|"
                r"PAYLOAD[A-Z_0-9]*|BR_END)|TX_LEAD_END)\b",
                re.IGNORECASE,
            )
            transitions_to_tx_followup = bool(
                next_state and tx_followup_re.search(next_state)
            )
            if (has_low and counter_const is not None
                    and transitions_to_tx_followup):
                failures.append(
                    f"SLAVE_TX_DEVICE_BREAK_PRESENT — {rel}:{line_no}: "
                    f"FSM state `{state_name}` (BR-named family) "
                    f"drives the bus LOW and waits on counter "
                    f"constant `{counter_const}` before transitioning "
                    f"to `{next_state}`. Wave 33 fallback rule: any "
                    f"BR/BREAK/LEADING-named state plateau before a "
                    f"TX-bit / TX-low / TX-first / TX-BR-END state is "
                    f"a device-side BR regardless of the constant "
                    f"name. Remove the state. See rig spec Layer 14."
                )

        # Also: detect the structural transition pattern where the
        # turnaround state hands off to a BR-emit state (even if the
        # heuristic above missed it because of unusual constant names).
        # We do this independently so the failure surface is complete.
        for state_name, body, line_no in arms:
            if not _TURN_STATE_RE.search(state_name):
                continue
            target = _next_state_in_arm(body)
            if target and _BR_STATE_RE.search(target):
                # Only flag if not already flagged via the LOW-drive
                # heuristic above.
                already = any(target in fmsg for fmsg in failures)
                if not already:
                    target_body, target_ln = arm_by_name.get(
                        target, ("", 0)
                    )
                    if _find_low_drive_in_arm(target_body):
                        failures.append(
                            f"SLAVE_TX_DEVICE_BREAK_PRESENT — "
                            f"{rel}:{target_ln}: turnaround state "
                            f"`{state_name}` transitions to BR-named "
                            f"state `{target}` that drives the bus "
                            f"LOW. Half-duplex slave reply must NOT "
                            f"prepend BR — see rig spec Layer 14."
                        )

        # ----------------------------------------------------------
        # Wave 34 (v0.119.66) — name-INDEPENDENT behavior-based scan
        # ----------------------------------------------------------
        # The v0.119.65 escape used state name `S_TX_HEADER` and a
        # custom constant `T_TX_HEADER_TICKS = 690`. Wave 33's
        # name-substring matching missed both; the gameable state
        # name was the loophole. Wave 34 ignores names entirely:
        # any FSM state arm in the TX response path (or any state
        # with a counter-driven LOW plateau) whose duration in ticks
        # is ≥ project's BR_MIN threshold is flagged.
        if br_min_ticks is None:
            warnings.append(
                f"WAVE34_NO_BR_MIN_THRESHOLD — {rel}: cannot resolve "
                f"BR_MIN threshold from L8.rx_classifier_ticks.br_min "
                f"or any BR_MIN-class localparam; behavior-based "
                f"detection skipped. Add `br_min` to L8 or define a "
                f"BR_MIN/T_BR_MIN_TICKS-named localparam."
            )
        else:
            for state_name, body, line_no in arms:
                # Skip TX-bit states themselves — those are SUPPOSED
                # to drive LOW for one bit cell (well below BR_MIN).
                if _TX_BIT_STATE_RE.search(state_name):
                    continue
                # Skip RX/turnaround states — they are non-TX path.
                if _TURN_STATE_RE.search(state_name):
                    continue
                # Skip obvious RX-side states (`S_RX*`) — host drives
                # LOW, not us.
                if re.match(r"\bS_RX_", state_name, re.IGNORECASE):
                    continue

                duration = _state_low_drive_duration(body, all_consts)
                if duration is None:
                    continue
                if duration < br_min_ticks:
                    continue

                # Avoid double-reporting if the legacy name-based
                # heuristic already flagged this state.
                already = any(
                    state_name in fmsg and "SLAVE_TX_DEVICE_BREAK_PRESENT"
                    in fmsg for fmsg in failures
                )
                if already:
                    continue

                failures.append(
                    f"SLAVE_TX_DEVICE_BREAK_PRESENT — {rel}:{line_no}: "
                    f"FSM state `{state_name}` drives the bus LOW for "
                    f"{duration} ticks, which is ≥ project BR_MIN "
                    f"threshold {br_min_ticks} ticks. In half-duplex "
                    f"single-wire request-response protocols (AID "
                    f"class), the device/slave reply MUST NOT drive "
                    f"the bus LOW for ≥ BR_MIN at any point — host "
                    f"firmware classifies that LOW pulse as a BR / "
                    f"new-frame marker and discards the in-flight "
                    f"response. Wave 34 (v0.119.66) behavior-based "
                    f"detection: state name does not matter; LOW-drive "
                    f"duration in ticks does. See rig spec Layer 14."
                )

    summary["failures"] = list(failures)
    return failures, warnings, summary


def main(argv: List[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(
            "Usage: slave_tx_no_device_break_check.py "
            "<project_dir> [--json <out>]"
        )
        return 0 if (len(argv) >= 2 and argv[1] in ("-h", "--help")) else 2

    project = Path(argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — project dir not found: {project}")
        return 1

    json_out: Optional[Path] = None
    if "--json" in argv:
        idx = argv.index("--json")
        if idx + 1 < len(argv):
            json_out = Path(argv[idx + 1])

    failures, warnings, summary = inspect(project)
    is_waived, rationale = _waived(project)

    if json_out:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps({
            "program": "slave_tx_no_device_break_check",
            "passed": not failures,
            "warnings": warnings,
            "summary": summary,
            "failures": failures,
            "waived": is_waived,
        }, indent=2))

    if "skip_reason" in summary and not failures and not warnings:
        print(f"SKIP — {summary['skip_reason']}")
        return 0

    if not failures:
        print(
            "PASS — slave/device TX path goes directly from "
            "turnaround state into bit-transmission state without "
            "prepending a device-side BR pulse."
        )
        for w in warnings:
            print(f"WARN — {w}")
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for fmsg in failures:
            print(f"  • {fmsg}")
        return 0

    print(f"FAIL — {len(failures)} slave-TX device-BR issue(s):")
    for fmsg in failures:
        print(f"  • {fmsg}")
    print()
    print("Why this matters:")
    print(
        "  In half-duplex single-wire request-response protocols "
        "(AID\n  class — <half-duplex-tester> / <chip-class> / similar), the host master "
        "sent a BR\n  at the beginning of the frame. The device "
        "ANSWER is NOT\n  preceded by its own BR — host firmware "
        "reads any LOW pulse\n  ≥ BR_MIN after the request as a "
        "frame error / new frame\n  attempt and resets its frame "
        "state. The DUT response that\n  follows is then discarded; "
        "host firmware sees the SEND_TEST\n  async frame all-padding "
        "from byte[6] onward (typical\n  byte[6]=0x02 silent FAIL)."
    )
    print()
    print("Fix recipe:")
    print(
        "  Remove the BR-emit state (`S_TX_BR` / `S_BREAK_TX` / etc.)\n"
        "  from the response path. The FSM should look like:\n"
        "    S_RX_DONE → S_VALIDATE → S_TURNAROUND_WAIT (count to\n"
        "      T_TSRS_MIN_TICKS) → S_TX_BIT (drive first response\n"
        "      bit's LOW pulse immediately).\n"
        "  Vendor reference: vendor MAC.v `TX_*_RDY` jumps from\n"
        "  RX-done directly to TX_CMD on host BR falling edge with\n"
        "  no intermediate BR-emit state."
    )
    print()
    print(
        f"Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
