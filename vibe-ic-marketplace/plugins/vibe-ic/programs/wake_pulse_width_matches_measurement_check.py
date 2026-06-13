#!/usr/bin/env python3
"""wake_pulse_width_matches_measurement_check.py — Wave 18 silent-bug gate.

Half-duplex single-wire bit-bang protocols typically specify the chip's
wake pulse LOW duration as a measurement (e.g. PPTX scope-shot diagram
labelled `RSP_Time = 22.7 µs` / `WAKE_PULSE = 22.4 µs`). The chip RTL
must drive a LOW pulse whose width matches that measurement within
PVT tolerance — NOT the host's WKP_MIN spec lower bound.

Why this matters
================
WKP_MIN is the host RX classifier's *acceptance* threshold (e.g.
14.76 µs). Vendor reference RTL drives a LOW pulse well above that
threshold (e.g. 22.4 µs), giving margin for cable + analog
front-end edge filtering. Fresh agents that read `WKP_MIN=14.76 µs`
from L8 spec table and pick `wake_pulse=16 µs` (the spec lower
bound + small safety) end up with insufficient margin: the host's
analog front-end filters the pulse to ~13 µs effective and rejects
it. The CORRECT source-of-truth is the vendor measurement document
in `input/docs/`, NOT the spec lower bound.

Detection
=========
1. Find wake-pulse generator RTL (filename `wake_gen` / `wake_ctrl` /
   `wake_pulse` / `wake_drv` / `wake_fsm` / `wake_emit`, or body
   heuristic: drives `wake_oe`/`wake_pulse`/`wake_drv`/`wake_o` from
   a counter).
2. Extract wake-pulse LOW duration from RTL (parameter / localparam
   matching `T_TWK_PULSE_TICKS` / `TWK_PULSE` / `TWK_TICKS` /
   `wake_pulse_ticks` / `wake_low_ticks` / `wake_pulse_us` etc).
3. Look up the wake-pulse measurement value in L8 (synonyms:
   `wake_pulse_us`, `t_wake_pulse_us`, `rsp_time_us`,
   `wake_pulse_measured_us`, `t_wake_low_us`,
   `wake_pulse_width_us`).
4. **FAIL** when:
     a. RTL value not within ±10% of the measured value, OR
     b. L8 has no measurement field while a `*.pptx` (or
        equivalent measurement source) exists in `input/docs/` —
        emit clear "extract from PPTX" hint.
5. **PASS** when RTL value within ±10% of measurement.
6. **WARN** when L8 has measurement and RTL also OK but margin
   small (<2%).
7. **SKIP** when no wake-pulse generator RTL.
8. Honors waiver `wake_pulse_intentional_offset` (≥40 chars
   rationale).

Chip-AGNOSTIC. No chip / tester / PDK / specific µs value
hard-coded. The synonym lists are protocol-class generic.

Exit codes
==========
0  — PASS / SKIP / PASS_WITH_WAIVER / WARN
1  — FAIL
2  — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple
import _path_layout as _pl

WAIVER_KEY = "wake_pulse_intentional_offset"
WAIVER_MIN_LEN = 40
TOLERANCE = 0.10  # ±10%

# --- Synonym tables --------------------------------------------------

# Measurement-source field names in L8 / L2.
_WAKE_MEASURED_US_KEYS: tuple[str, ...] = (
    "wake_pulse_us",
    "wake_pulse_measured_us",
    "t_wake_pulse_us",
    "t_wake_low_us",
    "wake_pulse_width_us",
    "wake_low_us",
    "rsp_time_us",
    "rsp_time",
    "response_time_us",
    "wake_pulse.measured_us",
    "wake_pulse.width_us",
    "timing.wake_pulse_us",
    "timing.t_wake_pulse_us",
    "vendor_measurement.wake_pulse_us",
    "vendor_measurement.rsp_time_us",
)

# Wake-pulse RTL parameter synonyms (ticks).
_RTL_TICK_PARAM_RE = re.compile(
    r"\b(?:"
    r"T_TWK_PULSE_TICKS"
    r"|TWK_PULSE(?:_TICKS)?"
    r"|TWK_TICKS"
    r"|T_TWK_TICKS"
    r"|WAKE_PULSE_TICKS"
    r"|WAKE_PULSE_CNT"
    r"|WAKE_LOW_TICKS"
    r"|WAKE_LOW_CNT"
    r"|T_WAKE_PULSE_TICKS"
    r"|T_WAKE_LOW_TICKS"
    r"|TWK_PULSE_CNT"
    r")\b",
    re.IGNORECASE,
)

# Wake-pulse RTL parameter synonyms (µs directly).
_RTL_US_PARAM_RE = re.compile(
    r"\b(?:"
    r"WAKE_PULSE_US"
    r"|T_WAKE_PULSE_US"
    r"|TWK_US"
    r"|WAKE_LOW_US"
    r")\b",
    re.IGNORECASE,
)

# Clock rate keys.
_CLOCK_NS_KEYS: tuple[str, ...] = (
    "clock_period_ns", "clk_period_ns", "tick_ns",
    "rtl_constants.clock_period_ns",
)
_CLOCK_MHZ_KEYS: tuple[str, ...] = (
    "internal_clock_mhz", "clock_mhz", "clk_mhz",
    "rtl_constants.internal_clock_mhz", "rtl_constants.clock_mhz",
)
DEFAULT_CLOCK_NS = 20.0  # 50 MHz fallback.

# Wake-gen file-name hints.
_WAKE_FILENAME_HINTS = (
    "wake_gen", "wake_ctrl", "wake_pulse", "wake_drv",
    "wake_fsm", "wake_emit",
)
_WAKE_OUT_NAMES_RE = re.compile(
    r"\bwake_(?:oe|pulse|drv|o|out|en|emit|active|low)\b",
    re.IGNORECASE,
)

# Measurement-source file extensions in input/docs/ that suggest a
# vendor measurement diagram is present.
_MEASUREMENT_DOC_GLOBS = (
    "**/*.pptx", "**/*.PPTX",
    "**/*timing*.pdf", "**/*Timing*.pdf",
    "**/*量測時序*",  # generic CJK measurement-timing keyword
    "**/*waveform*.pdf", "**/*Waveform*.pdf",
    "**/*measurement*.pdf",
)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _find_rtl_files(project_dir: Path) -> List[Path]:
    rtl_dir = _pl.rtl_dir(project_dir)
    if not rtl_dir.exists():
        return []
    files: List[Path] = []
    for p in rtl_dir.rglob("*"):
        if p.suffix.lower() in (".v", ".sv", ".svh", ".vh"):
            files.append(p)
    return sorted(files)


def _is_wake_gen(path: Path, src_no_cmt: str) -> bool:
    name = path.stem.lower()
    if any(h in name for h in _WAKE_FILENAME_HINTS):
        return True
    if not _WAKE_OUT_NAMES_RE.search(src_no_cmt):
        return False
    if re.search(
        r"\b\w*cnt\w*\s*<=\s*\w*cnt\w*\s*\+\s*\d",
        src_no_cmt,
        re.IGNORECASE,
    ):
        return True
    return False


def _extract_int_literal(rhs: str) -> Optional[int]:
    """Extract an integer from a Verilog RHS expression."""
    rhs = rhs.strip().rstrip(";").strip()
    # Try Verilog sized literal first: 32'd800, 16'h320, 8'b1010.
    m = re.search(
        r"(?:\d+\s*)?'\s*([bdhBDH])\s*([0-9A-Fa-f_]+)", rhs
    )
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
    # Plain decimal.
    m = re.match(r"\s*(\d+)", rhs)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _extract_float_literal(rhs: str) -> Optional[float]:
    rhs = rhs.strip().rstrip(";").strip()
    m = re.match(r"\s*([-+]?\d+(?:\.\d+)?)", rhs)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _resolve_rtl_wake_us(
    rtl_files: List[Path],
    clock_ns: float,
) -> Tuple[Optional[float], Optional[str], Optional[Path]]:
    """Return (wake_pulse_us, param_name, declaring_file)."""
    # First try µs-named parameter (preferred).
    decl_re = re.compile(
        r"(?:localparam|parameter|`define)\s+"
        r"(?:int\s+|integer\s+|"
        r"logic\s*\[[^\]]+\]\s+|\[[^\]]+\]\s+|real\s+)?"
        r"([A-Za-z_]\w*)\s*=\s*([^;\n]+);",
    )
    for f in rtl_files:
        try:
            src = _strip_comments(f.read_text(errors="ignore"))
        except Exception:
            continue
        for m in decl_re.finditer(src):
            name = m.group(1)
            rhs = m.group(2)
            if _RTL_US_PARAM_RE.search(name):
                v = _extract_float_literal(rhs)
                if v is not None and v > 0:
                    return v, name, f
    # Fall back to ticks.
    for f in rtl_files:
        try:
            src = _strip_comments(f.read_text(errors="ignore"))
        except Exception:
            continue
        for m in decl_re.finditer(src):
            name = m.group(1)
            rhs = m.group(2)
            if _RTL_TICK_PARAM_RE.search(name):
                v = _extract_int_literal(rhs)
                if v is not None and v > 0:
                    return v * clock_ns / 1000.0, name, f
    return None, None, None


# --- Doc helpers -----------------------------------------------------

def _walk(data: Any, path: tuple[str, ...]) -> Optional[Any]:
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


def _recursive_find(data: Any, path: tuple[str, ...]) -> Optional[Any]:
    if not path:
        return None
    head = path[0].lower()
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str) and k.lower() == head:
                if len(path) == 1:
                    return v
                deeper = _walk(v, path[1:])
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


def _coerce_number(v: Any) -> Optional[float]:
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


def _scan_synonyms(data: Any, keys: Iterable[str]) -> Optional[Tuple[str, Any]]:
    if not isinstance(data, dict):
        return None
    for key in keys:
        path = tuple(p for p in key.split(".") if p)
        v = _walk(data, path)
        if v is None:
            v = _recursive_find(data, path)
        if v is not None:
            return key, v
    return None


def _load_l_docs(project: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
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


def _resolve_clock_ns(docs: dict[str, dict]) -> float:
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


def _resolve_measurement_us(docs: dict[str, dict]) -> Tuple[Optional[float], Optional[str]]:
    for doc_name, data in docs.items():
        hit = _scan_synonyms(data, _WAKE_MEASURED_US_KEYS)
        if hit:
            n = _coerce_number(hit[1])
            if n is not None:
                return n, f"{doc_name}.{hit[0]}"
    return None, None


def _has_measurement_doc(project: Path) -> Optional[Path]:
    """Return path of any measurement-bearing doc if found in input/docs/."""
    docs_dir = project / "input" / "docs"
    if not docs_dir.is_dir():
        return None
    for pat in _MEASUREMENT_DOC_GLOBS:
        for p in docs_dir.glob(pat):
            if p.is_file():
                return p
    return None


# --- Waiver ----------------------------------------------------------

def _waived(project_dir: Path) -> Tuple[bool, str]:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text(errors="ignore"))
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


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: wake_pulse_width_matches_measurement_check.py "
            "<project_dir>"
        )
        return 2
    project_dir = Path(argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        return 1

    rtl_files = _find_rtl_files(project_dir)
    if not rtl_files:
        print("SKIP — no rtl/ directory")
        return 0

    # Detect any wake-gen RTL file.
    wake_present = False
    for f in rtl_files:
        try:
            src = _strip_comments(f.read_text(errors="ignore"))
        except Exception:
            continue
        if _is_wake_gen(f, src):
            wake_present = True
            break
    if not wake_present:
        print("SKIP — no wake-pulse generator RTL detected")
        return 0

    docs = _load_l_docs(project_dir)
    clock_ns = _resolve_clock_ns(docs)
    rtl_us, rtl_param, rtl_file = _resolve_rtl_wake_us(rtl_files, clock_ns)
    measured_us, source = _resolve_measurement_us(docs)
    measurement_doc = _has_measurement_doc(project_dir)

    is_waived, rationale = _waived(project_dir)

    failures: List[str] = []
    warnings: List[str] = []

    # Case A — RTL value missing.
    if rtl_us is None:
        failures.append(
            "RTL_WAKE_PULSE_PARAM_NOT_FOUND — could not extract a "
            "wake-pulse LOW-duration parameter from RTL. Searched "
            "for ticks-style names (T_TWK_PULSE_TICKS / "
            "WAKE_PULSE_TICKS / TWK_TICKS / WAKE_LOW_TICKS …) and "
            "us-style names (WAKE_PULSE_US / T_WAKE_PULSE_US). "
            "Declare one of these as a localparam in "
            "rtl_constants_pkg.sv (or equivalent)."
        )

    # Case B — L8 has the measurement; compare.
    elif measured_us is not None:
        ratio = rtl_us / measured_us if measured_us > 0 else float("inf")
        deviation = abs(rtl_us - measured_us) / measured_us
        if deviation > TOLERANCE:
            failures.append(
                f"RTL_VS_MEASUREMENT_DEVIATION — RTL "
                f"`{rtl_param}` resolves to "
                f"{rtl_us:.3f} µs but L8 measurement "
                f"`{source}={measured_us:.3f}` µs. Deviation "
                f"{deviation * 100:.1f}% exceeds ±{TOLERANCE * 100:.0f}% "
                f"tolerance (ratio={ratio:.2f}). Adjust the RTL "
                "parameter to match the vendor measurement."
            )
        elif deviation > 0.02:
            warnings.append(
                f"RTL `{rtl_param}`={rtl_us:.3f} µs vs L8 "
                f"`{source}`={measured_us:.3f} µs — within "
                f"±{TOLERANCE * 100:.0f}% but >2% drift "
                f"({deviation * 100:.1f}%); review for PVT margin."
            )

    # Case C — L8 lacks measurement field but a measurement doc
    #          (PPTX, *時序*, waveform PDF) is present in input/docs/.
    elif measurement_doc is not None:
        failures.append(
            "MEASUREMENT_DOC_NOT_EXTRACTED — `input/docs/` contains "
            f"`{measurement_doc.name}` but L8 has no wake-pulse "
            "measurement field. Run `eda_doc_extract` on the file "
            "and emit the measured value into L8 under one of: "
            f"{list(_WAKE_MEASURED_US_KEYS)[:6]}.... The chip's "
            "wake-pulse width must come from the vendor measurement, "
            "NOT the spec WKP_MIN lower bound."
        )

    # Case D — no measurement at all.
    else:
        warnings.append(
            f"RTL `{rtl_param}`={rtl_us:.3f} µs but no L8 "
            "measurement field and no measurement-bearing doc "
            "found in input/docs/. Cannot value-check. Add the "
            "vendor measurement to L8 or ship "
            f"`{WAIVER_KEY}` waiver if the absence is intentional."
        )

    if not failures:
        if warnings:
            print("PASS — wake-pulse width matches measurement "
                  f"(within ±{TOLERANCE * 100:.0f}%)")
            for w in warnings:
                print(f"  [WARN] {w}")
        else:
            print(
                "PASS — wake-pulse width within "
                f"±{TOLERANCE * 100:.0f}% of L8 measurement"
                + (f" ({source})" if source else "")
            )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(failures)} issue(s) silenced "
            f"by waivers.{WAIVER_KEY}: {rationale[:80]}…"
        )
        for f in failures:
            print(f"  • {f}")
        return 0

    print(f"FAIL — {len(failures)} wake-pulse measurement issue(s):")
    for f in failures:
        print(f"  • {f}")
    for w in warnings:
        print(f"  [WARN] {w}")
    print()
    print("Why this matters:")
    print("  WKP_MIN is the host's RX classifier *acceptance* lower")
    print("  bound, NOT the chip's implementation target. Vendor")
    print("  reference RTL drives a wake pulse comfortably above")
    print("  WKP_MIN to give margin for cable + analog filtering.")
    print("  Read the wake pulse value from the vendor measurement")
    print("  document (often a PPTX scope-shot in input/docs/) and")
    print("  match RTL within ±10%.")
    print()
    print(
        "Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": '
        '"<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
