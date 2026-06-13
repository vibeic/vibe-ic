#!/usr/bin/env python3
"""tx_phy_bit_cell_total_consumed_check.py — Wave 15 silent-bug gate
(amended in Wave 18 / v0.119.50 — see "Wave 18 amendment" below).

The CRITICAL silent-bug pattern this gate catches
=================================================
In half-duplex single-wire bit-bang protocols (e.g. accessory ID-bus,
1-Wire-class, automotive single-edge nibble transmission), every
transmitted bit occupies a fixed total cell duration `BIT_CY` (also
known as `BIT_CELL` / `BIT_PERIOD` / `T_BIT` / `T_BIT_TOTAL`). The
TX side drives:

    LOW for `H0_LOW_TICKS` (BIT0) or `H1_LOW_TICKS` (BIT1),
    HIGH (or releases the bus) for the REMAINDER of the cell so that
        LOW + HIGH == BIT_CY,

and the next bit's LOW pulse begins exactly at the cell boundary.

Wave 15 root cause
------------------
The 21st-attempt fresh agent (v0.119.47) wrote main_fsm.sv such that
`S_TX_BIT_GAP` advanced `bit_idx` after only `gap_cnt + 1 >= 16'd10`
(≈200 ns) of HIGH dwell, then re-entered `S_TX_BIT` to drive the next
LOW. Result: consecutive LOW pulses appeared merged from the host's
perspective. The TB's RX decoder used the SAME wrong bit cell timing,
so simulation PASSed; real silicon (<half-duplex-tester>) used the standard bit cell
and saw garbage → byte[6]=0x02.

Wave 18 amendment (v0.119.50)
-----------------------------
The structural invariant (BIT_CY-class parameter must exist + the
bit-advance must reference it) is preserved. What changed:

  * The previous "BIT_CY = 500 ticks (10 µs) recommended default"
    came from a FALSE oracle (v068's own RTL, which itself FAILed
    real-silicon byte[6]=0xF2). Validation against the vendor PASS
    oracle (`vendor_ref/.../TX_PHY.v` lines 248/240/362/372) shows
    the true bit cell is 8.8 µs (BIT0_LOW=6.8 + 2.0 / BIT1_LOW=1.6
    + 7.2). The "500 default" recommendation is REMOVED.
  * BIT_CY value MUST come from L8 timing constants extracted from
    a vendor measurement document (`量測時序.pptx`,
    `*timing*.pptx`, etc.) — never hardcoded by the plugin.
  * NEW sub-check: when L8 has measurement `bit0_low_us` /
    `bit1_low_us` (synonyms below), the RTL parameters
    `T_HW0_TX_TICKS` / `T_HW1_TX_TICKS` (or equivalent) must be
    within ±10% of those measurements.
  * NEW sub-check: when L8 has both bit_low_us values AND an IBT_MIN
    field, BIT_CY must NOT exceed
    `max(bit0_low_us, bit1_low_us) + IBT_MIN_us × 0.85` by more
    than 10% — otherwise the HIGH portion is so long it crosses
    IBT_MIN and triggers a spurious byte boundary on the host.

This gate is **chip-AGNOSTIC**. It works for any half-duplex single-
wire bit-bang protocol where `BIT_CY = LOW_TICKS + HIGH_TICKS`. No
<chip-class> / <benchmark> / <half-duplex-tester> / VENDOR / 0xF2 / specific tick value is
hard-coded.

Detection algorithm
===================
1. Discover candidate "TX bit-emitter" RTL files. Heuristic matches
   either:
     - filename hint: `tx_phy` / `tx_encoder` / `tx_drv` / `tx_serial`
       / `bit_emit` / `bit_drv` / `bit_tx` / `tx_*` / `bit_*` /
       `main_fsm` / `cmd_fsm` / `proto_fsm`
     - body heuristic: contains a `bit_idx`/`bit_cnt`/`bit_n`
       reference AND a TX-state identifier (`S_TX_BIT` / `tx_kind` /
       `tx_start` / `tx_done` / `tx_byte`).
2. Look in the project's RTL (any file, including
   `rtl_constants_pkg.sv`) for a parameter / localparam / `define`
   whose name matches the canonical bit-cell synonyms:
   `BIT_CY` / `BIT_CELL` / `BIT_PERIOD` / `T_BIT` / `T_BIT_TOTAL` /
   `T_BIT_CELL` / `T_BIT_CY` / `BIT_TICKS_TOTAL` /
   `BIT_CELL_TICKS_TX` (case-insensitive, optional `_TX`/`_RX`
   suffix tolerated).
3. **FAIL** when:
     a. No `BIT_CY`-class parameter exists anywhere in the project's
        RTL, OR
     b. A TX bit-emitter file advances `bit_idx` after only the LOW
        phase without an explicit "drive HIGH for (BIT_CY - LOW_TICKS)
        ticks" / "wait until cnt == BIT_CY" branch — i.e. the
        immediate FSM transition that increments bit_idx never
        references the bit-cell parameter and instead uses a small
        magic literal (≤ ~50 ticks, well below any plausible bit
        cell).
4. Specifically catches the `if (gap_cnt + N >= 16'd10) ...
   bit_idx <= bit_idx + 1; state <= S_TX_BIT;` anti-pattern.
5. Specifically passes:
        if (state == TX_BIT_LOW && cnt == LOW_TICKS)
            state <= TX_BIT_HIGH;
        if (state == TX_BIT_HIGH && cnt == BIT_CY) begin
            bit_idx <= bit_idx + 1;
            state   <= TX_BIT_LOW;
        end
   — the bit_idx-advance condition references BIT_CY directly.

Waiver
======
`tx_bit_cell_intentionally_truncated` (≥40 chars rationale).

Exit codes
==========
0  — PASS / SKIP
1  — FAIL
2  — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple
import _path_layout as _pl

WAIVER_KEY = "tx_bit_cell_intentionally_truncated"
WAIVER_MIN_LEN = 40

# Wave 18 — measurement tolerance and synonym tables.
TOLERANCE = 0.10  # ±10%

# L8 measurement field synonyms — chip-AGNOSTIC protocol-engineering
# terms only.
_BIT0_LOW_MEASURED_US_KEYS: tuple[str, ...] = (
    "bit0_low_us",
    "t_h0_low_us",
    "t_bit0_low_measured_us",
    "h0_low_us",
    "tx_bit0_low_us",
    "t_hw0_us",
    "bit0_low.measured_us",
    "timing.bit0_low_us",
    "vendor_measurement.bit0_low_us",
)
_BIT1_LOW_MEASURED_US_KEYS: tuple[str, ...] = (
    "bit1_low_us",
    "t_h1_low_us",
    "t_bit1_low_measured_us",
    "h1_low_us",
    "tx_bit1_low_us",
    "t_hw1_us",
    "bit1_low.measured_us",
    "timing.bit1_low_us",
    "vendor_measurement.bit1_low_us",
)
_IBT_MIN_US_KEYS: tuple[str, ...] = (
    "ibt_min_us",
    "t_ibt_min_us",
    "ibt.min_us",
    "rx_classifier.ibt_min_us",
    "vendor_measurement.ibt_min_us",
)

# Clock-rate keys (used to convert RTL-tick parameter values to µs).
_CLOCK_NS_KEYS: tuple[str, ...] = (
    "clock_period_ns", "clk_period_ns", "tick_ns",
    "rtl_constants.clock_period_ns",
)
_CLOCK_MHZ_KEYS: tuple[str, ...] = (
    "internal_clock_mhz", "clock_mhz", "clk_mhz",
    "rtl_constants.internal_clock_mhz", "rtl_constants.clock_mhz",
)
DEFAULT_CLOCK_NS = 20.0  # 50 MHz fallback.

# RTL parameter name regexes for BIT0_LOW and BIT1_LOW counter values
# (in ticks).
_RTL_BIT0_LOW_RE = re.compile(
    r"\b(?:T_HW0(?:_TX_TICKS|_TICKS)?|H0_LOW_TICKS|BIT0_LOW_TICKS|"
    r"TX_BIT0_LOW(?:_TICKS)?|T_BIT0_LOW(?:_TICKS)?)\b",
    re.IGNORECASE,
)
_RTL_BIT1_LOW_RE = re.compile(
    r"\b(?:T_HW1(?:_TX_TICKS|_TICKS)?|H1_LOW_TICKS|BIT1_LOW_TICKS|"
    r"TX_BIT1_LOW(?:_TICKS)?|T_BIT1_LOW(?:_TICKS)?)\b",
    re.IGNORECASE,
)

# Canonical bit-cell parameter synonyms. Match is case-insensitive and
# anchored on word boundaries — so e.g. `T_BIT_CELL_TX_TICKS`,
# `BIT_CY_PARAM`, `T_BIT_PERIOD_NS` all match the family.
_BIT_CELL_NAME_RE = re.compile(
    r"\b(?:"
    r"BIT_CY"
    r"|BIT_CELL(?:_TICKS|_TICKS_TX|_PERIOD|_TOT)?"
    r"|BIT_PERIOD"
    r"|T_BIT(?:_TOTAL|_CELL|_CY|_PERIOD)?"
    r"|T_BIT_CELL_TX_TICKS"
    r"|BIT_TICKS_TOTAL"
    r")\b",
    re.IGNORECASE,
)

# Filename hints that imply a TX bit-emitter file.
_TX_FILENAME_HINTS = (
    "tx_phy", "tx_encoder", "tx_drv", "tx_serial",
    "bit_emit", "bit_drv", "bit_tx",
    "main_fsm", "cmd_fsm", "proto_fsm",
)

# Regex for parameter / localparam / `define BIT_CELL = ...
_PARAM_DECL_RE = re.compile(
    r"(?:localparam|parameter|`define)\s+(?:int\s+|integer\s+|"
    r"logic\s*\[[^\]]+\]\s+|\[[^\]]+\]\s+)?"
    r"([A-Za-z_]\w*)",
)


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def find_rtl_files(project_dir: Path) -> List[Path]:
    rtl_dir = _pl.rtl_dir(project_dir)
    if not rtl_dir.exists():
        return []
    files: List[Path] = []
    for p in rtl_dir.rglob("*"):
        if p.suffix.lower() in (".v", ".sv", ".svh", ".vh"):
            files.append(p)
    return sorted(files)


def is_tx_bit_emitter(path: Path, src_no_cmt: str) -> bool:
    """Heuristic: does this file emit per-bit TX pulses?"""
    name = path.stem.lower()
    if any(h in name for h in _TX_FILENAME_HINTS):
        # filename match — but require at least bit_idx-style ref to
        # avoid e.g. tx_phy.sv that's a thin pad wrapper.
        if re.search(r"\bbit_(?:idx|cnt|n|index|num)\b", src_no_cmt):
            return True
    # Body fallback: bit-counter + TX-state identifier.
    if re.search(r"\bbit_(?:idx|cnt|n|index|num)\b", src_no_cmt) and \
       re.search(r"\b(?:S_TX_BIT|tx_kind|tx_start|tx_done|tx_byte|"
                 r"S_TX_BYTE|S_TX_PRE_GAP|S_TX_BIT_GAP)\b",
                 src_no_cmt):
        return True
    return False


def has_bit_cell_param(rtl_files: List[Path]) -> Tuple[bool, Optional[str], Optional[Path]]:
    """Look across ALL project RTL for a BIT_CY-class parameter."""
    for path in rtl_files:
        try:
            src = strip_comments(path.read_text(errors="ignore"))
        except Exception:
            continue
        for m in _PARAM_DECL_RE.finditer(src):
            name = m.group(1)
            if _BIT_CELL_NAME_RE.search(name):
                return True, name, path
    return False, None, None


# Match a bit-cell re-entry branch. Two equivalent silent-bug forms:
#   (A) `if (<cond>) ... bit_idx <= bit_idx + N; ... end` — same-state
#       advance,
#   (B) `if (<cond>) ... state <= <S_TX_BIT-like>; ... end` — re-enter
#       the bit-emit state, which is the v0.119.47 main_fsm.sv:326
#       form (bit_idx is advanced in the OUTER S_TX_BIT branch).
# Either qualifies: the cond is the gating condition we inspect.
_BIT_ADVANCE_RE = re.compile(
    r"if\s*\(\s*([^)]+?)\s*\)\s*begin"
    r"(?P<body>(?:[^\{}]|\{[^}]*\})*?"
    r"(?:"
    r"\bbit_(?:idx|cnt|n|index|num)\b\s*<=\s*"
    r"\bbit_(?:idx|cnt|n|index|num)\b\s*\+\s*[\w']+"
    r"|"
    r"\bstate\b\s*<=\s*\b(?:S_TX_BIT|S_TX_BYTE|S_TX_BIT_LOW|"
    r"S_TX_BIT_DRIVE|TX_BIT|TX_BIT_LOW|S_BIT|S_BIT_LOW)\b"
    r")"
    r"(?:[^\{}]|\{[^}]*\})*?)"
    r"end",
    re.DOTALL,
)


def find_bit_advance_violations(
    src_no_cmt: str,
    file_path: Path,
) -> List[dict]:
    """Find each `bit_idx<=bit_idx+1` branch and inspect the gating cond.

    A violation is one whose IMMEDIATE gating condition lacks a
    BIT_CY-class reference AND uses a small magic literal (≤ 50
    ticks). 50 ticks = 1 µs at 50 MHz, an order of magnitude below
    any plausible bit cell (the simplest single-wire protocols use
    ≥10 µs / 500 ticks).
    """
    violations: List[dict] = []
    for m in _BIT_ADVANCE_RE.finditer(src_no_cmt):
        cond = m.group(1)
        # Skip if cond mentions a BIT_CY-class parameter (PASS).
        if _BIT_CELL_NAME_RE.search(cond):
            continue
        # Skip if cond is a byte-boundary check on bit_idx itself
        # (e.g. `bit_idx == 4'd8`). That's the byte-done branch, not
        # a bit-cell timing branch — covered by other gates.
        if re.match(
            r"\s*bit_(?:idx|cnt|n|index|num)\s*[=!]=",
            cond,
            re.IGNORECASE,
        ):
            continue
        # Skip if cond mentions a state that's the start of TX (e.g.
        # `tx_done` after a tx_phy that itself drives the full cell
        # — but only if BIT_CY param exists at the project level;
        # we re-check below).
        # Find numeric literal in cond. If literal is "small" (≤50)
        # and cond doesn't reference BIT_CY-class param, flag it.
        # Numeric forms tolerated: 16'd10, 8'h0A, 8'b1010, 10, 32'd500.
        magic_match = re.search(
            r"(?:\d+\s*'\s*[bdhBDH]\s*)?(\d+)\b",
            cond,
        )
        if not magic_match:
            continue
        try:
            value = int(magic_match.group(1))
        except ValueError:
            continue
        # Resolve potential hex form: `8'h0A` → group(1)="0A" decoded
        # by int(...,16). Be conservative: try both bases.
        full = magic_match.group(0)
        # Strip Verilog literal prefix to get pure number+base.
        base_match = re.search(
            r"\d+\s*'\s*([bdhBDH])\s*([0-9A-Fa-f]+)", full,
        )
        if base_match:
            base_char = base_match.group(1).lower()
            digits = base_match.group(2)
            try:
                if base_char == "h":
                    value = int(digits, 16)
                elif base_char == "b":
                    value = int(digits, 2)
                elif base_char == "d":
                    value = int(digits, 10)
            except ValueError:
                pass
        if value > 50:
            # Large literal (≥51 ticks): could be a real bit cell
            # constant inlined. We do NOT flag — the project might
            # be mis-using a magic literal but at least it's in the
            # right order of magnitude. The companion gate
            # `tx_bit_timing_units_check` covers that case.
            continue
        # Locate file:line of the matched cond start.
        prefix = src_no_cmt[: m.start()]
        line_no = prefix.count("\n") + 1
        violations.append({
            "file": str(file_path),
            "line": line_no,
            "cond": cond.strip(),
            "literal_ticks": value,
        })
    return violations


def _walk_doc(data, path):
    cur = data
    for tok in path:
        tok_l = tok.lower()
        if isinstance(cur, dict):
            match = None
            for k in cur:
                if isinstance(k, str) and k.lower() == tok_l:
                    match = k
                    break
            if match is None:
                return None
            cur = cur[match]
        else:
            return None
    return cur


def _recursive_find(data, path):
    if not path:
        return None
    head = path[0].lower()
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and k.lower() == head:
                if len(path) == 1:
                    return v
                deeper = _walk_doc(v, path[1:])
                if deeper is not None:
                    return deeper
        for v in data.values():
            r = _recursive_find(v, path)
            if r is not None:
                return r
    elif isinstance(data, list):
        for it in data:
            r = _recursive_find(it, path)
            if r is not None:
                return r
    return None


def _coerce_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.match(r"\s*([-+]?\d+(?:\.\d+)?)", v)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def _scan_synonyms(data, keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        path = tuple(p for p in key.split(".") if p)
        v = _walk_doc(data, path)
        if v is None:
            v = _recursive_find(data, path)
        if v is not None:
            return key, v
    return None


def _load_l_docs(project: Path) -> dict:
    out = {}
    for sub in ("phase1/generated_docs", "generated_docs", "input/docs"):
        d = project / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                out[p.name] = json.loads(p.read_text(errors="ignore") or "{}")
            except json.JSONDecodeError:
                continue
    return out


def _resolve_clock_ns(docs: dict) -> float:
    for data in docs.values():
        hit = _scan_synonyms(data, _CLOCK_NS_KEYS)
        if hit:
            n = _coerce_number(hit[1])
            if n is not None and n > 0:
                return n
        hit = _scan_synonyms(data, _CLOCK_MHZ_KEYS)
        if hit:
            n = _coerce_number(hit[1])
            if n is not None and n > 0:
                return 1000.0 / n
    return DEFAULT_CLOCK_NS


def _resolve_measured_us(docs: dict, keys) -> Tuple[Optional[float], Optional[str]]:
    for doc_name, data in docs.items():
        hit = _scan_synonyms(data, keys)
        if hit:
            n = _coerce_number(hit[1])
            if n is not None:
                return n, f"{doc_name}.{hit[0]}"
    return None, None


def _extract_int_literal(rhs: str) -> Optional[int]:
    rhs = rhs.strip().rstrip(";").strip()
    m = re.search(r"(?:\d+\s*)?'\s*([bdhBDH])\s*([0-9A-Fa-f_]+)", rhs)
    if m:
        base = m.group(1).lower()
        digits = m.group(2).replace("_", "")
        try:
            if base == "h":
                return int(digits, 16)
            if base == "b":
                return int(digits, 2)
            if base == "d":
                return int(digits, 10)
        except ValueError:
            return None
    m = re.match(r"\s*(\d+)", rhs)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _resolve_rtl_param_ticks(rtl_files: List[Path],
                             name_re) -> Optional[int]:
    decl_re = re.compile(
        r"(?:localparam|parameter|`define)\s+"
        r"(?:int\s+|integer\s+|"
        r"logic\s*\[[^\]]+\]\s+|\[[^\]]+\]\s+|real\s+)?"
        r"([A-Za-z_]\w*)\s*=\s*([^;\n]+);",
    )
    for f in rtl_files:
        try:
            src = strip_comments(f.read_text(errors="ignore"))
        except Exception:
            continue
        for m in decl_re.finditer(src):
            name = m.group(1)
            rhs = m.group(2)
            if name_re.search(name):
                v = _extract_int_literal(rhs)
                if v is not None and v > 0:
                    return v
    return None


def _resolve_bit_cy_ticks(rtl_files: List[Path]) -> Optional[int]:
    decl_re = re.compile(
        r"(?:localparam|parameter|`define)\s+"
        r"(?:int\s+|integer\s+|"
        r"logic\s*\[[^\]]+\]\s+|\[[^\]]+\]\s+|real\s+)?"
        r"([A-Za-z_]\w*)\s*=\s*([^;\n]+);",
    )
    for f in rtl_files:
        try:
            src = strip_comments(f.read_text(errors="ignore"))
        except Exception:
            continue
        for m in decl_re.finditer(src):
            name = m.group(1)
            rhs = m.group(2)
            if _BIT_CELL_NAME_RE.search(name):
                v = _extract_int_literal(rhs)
                if v is not None and v > 0:
                    return v
    return None


def waived(project_dir: Path) -> Tuple[bool, str]:
    waivers = project_dir / "waivers.json"
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
        if isinstance(rationale, str) and len(rationale.strip()) >= WAIVER_MIN_LEN:
            return True, rationale.strip()
    return False, ""


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: tx_phy_bit_cell_total_consumed_check.py <project_dir>"
        )
        return 2

    project_dir = Path(argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        return 1

    rtl_files = find_rtl_files(project_dir)
    if not rtl_files:
        print("SKIP — no rtl/ directory or no Verilog/SV files")
        return 0

    # Discover TX bit-emitter files.
    tx_files: List[Tuple[Path, str]] = []
    for path in rtl_files:
        try:
            src = strip_comments(path.read_text(errors="ignore"))
        except Exception:
            continue
        if is_tx_bit_emitter(path, src):
            tx_files.append((path, src))

    if not tx_files:
        print("SKIP — no TX bit-emitter RTL detected")
        return 0

    # Project-wide BIT_CY parameter check.
    has_param, param_name, param_path = has_bit_cell_param(rtl_files)

    is_waived, rationale = waived(project_dir)

    # Collect violations.
    violations: List[dict] = []
    for path, src in tx_files:
        try:
            rel = path.relative_to(project_dir)
        except ValueError:
            rel = path
        violations.extend(find_bit_advance_violations(src, rel))

    # Verdict assembly.
    failures: List[str] = []
    if not has_param:
        failures.append(
            "MISSING_BIT_CELL_PARAM — no BIT_CY-class parameter "
            "(BIT_CY / BIT_CELL / BIT_PERIOD / T_BIT / T_BIT_CELL / "
            "T_BIT_CELL_TX_TICKS) declared in any project RTL file. "
            f"TX bit-emitter file(s): "
            f"{', '.join(str(p[0].relative_to(project_dir)) for p in tx_files)}"
        )

    if violations:
        for v in violations:
            failures.append(
                f"TRUNCATED_BIT_CELL — {v['file']}:{v['line']} — "
                f"`bit_idx` advances on `if ({v['cond']})` with magic "
                f"literal {v['literal_ticks']} ticks; the gating "
                f"condition does not reference any BIT_CY-class "
                f"parameter. TX bit cell must be filled to "
                f"`BIT_CY` before advancing — see Layer 8.6 of rig "
                f"spec."
            )

    # ------------------------------------------------------------------
    # Wave 18 amendment: compare RTL parameter values to L8 vendor
    # measurements when present.
    # ------------------------------------------------------------------
    docs = _load_l_docs(project_dir)
    clock_ns = _resolve_clock_ns(docs)
    bit0_us, bit0_src = _resolve_measured_us(
        docs, _BIT0_LOW_MEASURED_US_KEYS)
    bit1_us, bit1_src = _resolve_measured_us(
        docs, _BIT1_LOW_MEASURED_US_KEYS)
    ibt_min_us, _ = _resolve_measured_us(docs, _IBT_MIN_US_KEYS)

    if bit0_us is not None:
        rtl_t0 = _resolve_rtl_param_ticks(rtl_files, _RTL_BIT0_LOW_RE)
        if rtl_t0 is not None:
            rtl_t0_us = rtl_t0 * clock_ns / 1000.0
            if abs(rtl_t0_us - bit0_us) / bit0_us > TOLERANCE:
                failures.append(
                    f"BIT0_LOW_DEVIATES_FROM_MEASUREMENT — RTL "
                    f"BIT0_LOW={rtl_t0} ticks ({rtl_t0_us:.3f} µs) "
                    f"deviates >{TOLERANCE * 100:.0f}% from L8 "
                    f"`{bit0_src}={bit0_us:.3f}` µs. Adjust the "
                    "RTL parameter to match the vendor measurement."
                )

    if bit1_us is not None:
        rtl_t1 = _resolve_rtl_param_ticks(rtl_files, _RTL_BIT1_LOW_RE)
        if rtl_t1 is not None:
            rtl_t1_us = rtl_t1 * clock_ns / 1000.0
            if abs(rtl_t1_us - bit1_us) / bit1_us > TOLERANCE:
                failures.append(
                    f"BIT1_LOW_DEVIATES_FROM_MEASUREMENT — RTL "
                    f"BIT1_LOW={rtl_t1} ticks ({rtl_t1_us:.3f} µs) "
                    f"deviates >{TOLERANCE * 100:.0f}% from L8 "
                    f"`{bit1_src}={bit1_us:.3f}` µs. Adjust the "
                    "RTL parameter to match the vendor measurement."
                )

    # BIT_CY upper-bound check: BIT_CY must NOT exceed
    # max(bit_low_us) + IBT_MIN_us × 0.85 by more than 10% — otherwise
    # the HIGH portion crosses IBT_MIN and triggers a spurious byte
    # boundary on the host RX classifier.
    if bit0_us is not None and bit1_us is not None and ibt_min_us is not None:
        bit_cy_ticks = _resolve_bit_cy_ticks(rtl_files)
        if bit_cy_ticks is not None:
            bit_cy_us = bit_cy_ticks * clock_ns / 1000.0
            ceiling = max(bit0_us, bit1_us) + ibt_min_us * 0.85
            if bit_cy_us > ceiling * (1.0 + TOLERANCE):
                failures.append(
                    f"BIT_CY_EXCEEDS_IBT_CEILING — RTL "
                    f"BIT_CY={bit_cy_ticks} ticks "
                    f"({bit_cy_us:.3f} µs) is more than "
                    f"{TOLERANCE * 100:.0f}% above the safe ceiling "
                    f"max(bit0_low_us, bit1_low_us) + IBT_MIN_us × "
                    f"0.85 = {ceiling:.3f} µs. The HIGH phase will "
                    "cross IBT_MIN and the host will declare a "
                    "spurious byte boundary mid-cell."
                )

    if not failures:
        print(
            f"PASS — TX bit-emitter consumes full bit cell "
            f"(parameter `{param_name}` declared in "
            f"`{param_path.relative_to(project_dir) if param_path else '?'}`, "
            f"no truncated-cell anti-patterns)"
        )
        return 0

    if is_waived:
        print(
            "PASS_WITH_WAIVER — "
            f"{len(failures)} bit-cell truncation issue(s) "
            f"silenced by waivers.{WAIVER_KEY}: {rationale[:80]}…"
        )
        for f in failures:
            print(f"  • {f}")
        return 0

    print(
        f"FAIL — {len(failures)} bit-cell truncation issue(s) detected:"
    )
    for f in failures:
        print(f"  • {f}")
    print()
    print("Why this matters (silent sim-PASS / hardware-FAIL pattern):")
    print("  Each TX bit cell has total duration BIT_CY. The TX side")
    print("  drives LOW for H{0,1}_LOW_TICKS, then drives HIGH for")
    print("  (BIT_CY - LOW_TICKS), then advances to the next bit at")
    print("  the cell boundary. If the RTL inserts a fixed short")
    print("  gap (e.g. 200 ns) and immediately re-drives LOW, the")
    print("  host sees consecutive LOW pulses merged into one long")
    print("  LOW. Sim PASSes when the TB's RX uses the same wrong")
    print("  timing; real silicon decodes per spec and sees garbage.")
    print()
    print(
        "Fix: declare a BIT_CY-class parameter (Wave 18: value MUST\n"
        "be derived from the vendor measurement document, e.g.\n"
        "`量測時序.pptx` — never hardcode a plugin default), e.g.\n"
        "    // computed from L8 measurements\n"
        "    localparam int T_BIT_CELL_TX_TICKS = <derived>;\n"
        "in rtl_constants_pkg.sv. Then gate bit_idx-advance on the\n"
        "remainder, e.g.\n"
        "    if (gap_cnt + 1 >= T_BIT_CELL_TX_TICKS - tx_low_width)\n"
        "        bit_idx <= bit_idx + 1;\n"
    )
    print(
        "Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": '
        '"<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
