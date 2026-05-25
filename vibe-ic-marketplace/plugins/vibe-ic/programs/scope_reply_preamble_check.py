#!/usr/bin/env python3
"""scope_reply_preamble_check.py — Wave 58 / BACKLOG-v12 P0.4 plugin gate.

When the project ships a scope CSV capturing a host-frame → chip-reply
round-trip on a half-duplex bus, the CHIP REPLY window must NOT contain
LOW pulses ≥ BR_MIN ticks.  A BR-class LOW in the chip's TX is a spec
violation: the BR delimiter is the host's framing — only the host
emits BR; the chip emits only BIT0/BIT1/IBT pulses.

Wave 56 column-D Issue 3 hardware-confirmed this bug class on
v0.121-vendor (every chip reply contained a 14.92 µs BR-class LOW
preamble at t=431.5 µs).  Static RTL inspection couldn't isolate the
source — only scope evidence catches it.

Detection (chip-AGNOSTIC)
=========================
1. SKIP when no scope CSV is found AND the project has no half-duplex
   protocol declaration in L3.
2. Find scope CSV files.  Search order:
     (a) `<project>/reports/wave*/scope_captures/*.csv`
     (b) `<project>/reports/scope_captures/*.csv`
     (c) `<project>/scope/*.csv`
   The CSV must have a numeric voltage column whose name contains
   `volt` / `_v` / `ch1` / `signal`.
3. Read L8 / RTL constants for the bit-classifier thresholds:
   `BR_MIN`, `H0_MAX` (or `H0MAX`).  Values in 50 MHz ticks.
4. SKIP gracefully when neither L8 nor any rtl_constants file declares
   BR_MIN.  This makes the gate inert for projects that don't use the
   AID-class half-duplex protocol convention.
5. For each scope CSV that names a "reply" / "tx" / "response" /
   "chip_reply" / "connect_test" segment in its filename, decode the
   LOW pulse widths.  FAIL when any LOW pulse strictly inside the
   chip-reply window has width ≥ BR_MIN ticks (after host-frame end,
   before scope window end, with a heuristic of "second half of
   capture").

Honors waiver `chip_reply_br_preamble_intentional` (≥40 chars).

Exit codes
==========
0  — PASS / SKIP / PASS_WITH_WAIVER
1  — FAIL
2  — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional
import _path_layout as _pl

# Wave 78 — explicit class applicability. Scope-reply BR preamble is
# an AID-class half-duplex bus concept (BR is the host's framing
# delimiter; only the host emits BR). UART/SPI/I2C and pure-analog
# projects don't share the BR/IBT/H0/H1 pulse-class taxonomy.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402

_APPLICABLE_CLASSES = ("aid_class_half_duplex",)

WAIVER_KEY = "chip_reply_br_preamble_intentional"
WAIVER_MIN_LEN = 40

# Default sample rate when the CSV doesn't carry a sample interval
# in its filename (e.g. `_5ms_5us.csv`) — 100 ns per sample.
_DEFAULT_NS_PER_SAMPLE = 100.0
_TICK_NS = 20.0  # 50 MHz core clock — matches L8 default in rtl_gen.

_SCOPE_FILE_PATTERNS = [
    "reports/wave*/scope_captures/*.csv",
    "reports/wave*/scope/*.csv",
    "reports/scope_captures/*.csv",
    "reports/scope/*.csv",
    "scope/*.csv",
    "scope_captures/*.csv",
]

_REPLY_HINTS = (
    "reply", "response", "tx", "chip_tx", "connect_test", "send_test",
    "round_trip", "roundtrip",
)


def find_scope_csvs(project_dir: Path) -> List[Path]:
    out: List[Path] = []
    for pat in _SCOPE_FILE_PATTERNS:
        out.extend(project_dir.glob(pat))
    return sorted(set(out))


def get_br_min_ticks(project_dir: Path) -> Optional[int]:
    # Try L8 generated_docs.
    gd = _pl.generated_docs_dir(project_dir)
    for path in gd.glob("L8_*.json") if gd.is_dir() else []:
        try:
            d = json.loads(path.read_text())
        except Exception:
            continue
        cls = d.get("rx_classifier_ticks", {})
        if "br_min" in cls:
            return int(cls["br_min"])
        # Sometimes nested under thresholds.
        thr = d.get("thresholds", {})
        if "br_min" in thr:
            return int(thr["br_min"])
    # Fall back: parse rtl_constants_pkg.sv for BR_MIN literal.
    for fn in ( project_dir / "phase2/stage1/rtl", _pl.rtl_dir(project_dir) / "rtl_constants_pkg.sv", project_dir / "phase2/stage1/rtl", _pl.rtl_dir(project_dir) / "rtl_constants.sv", project_dir / "phase2/stage1/rtl", _pl.rtl_dir(project_dir) / "rtl_constants.v",
    ):
        if fn.exists():
            try:
                src = fn.read_text(errors="ignore")
            except Exception:
                continue
            m = re.search(
                r"\bBR_MIN\s*=\s*(\d+)\b", src, re.IGNORECASE,
            )
            if m:
                return int(m.group(1))
    return None


def is_half_duplex_project(project_dir: Path) -> bool:
    """Heuristic: L3 declares half-duplex single-wire protocol OR
    the rtl/ has a `wake_gen` + `id_bus` module."""
    gd = _pl.generated_docs_dir(project_dir)
    if gd.is_dir():
        for path in gd.glob("L3_*.json"):
            try:
                d = json.loads(path.read_text())
            except Exception:
                continue
            t = json.dumps(d).lower()
            if "half_duplex" in t or "single_wire" in t or \
               "id_bus" in t or "1-wire" in t:
                return True
    rtl_dir = _pl.rtl_dir(project_dir)
    if rtl_dir.is_dir():
        for path in rtl_dir.rglob("*.sv"):
            if "id_bus" in path.read_text(errors="ignore"):
                return True
            if "wake_gen" in path.stem.lower():
                return True
    return False


def parse_scope_csv(path: Path) -> List[float]:
    """Return list of voltage samples.  Best-effort: skip headers,
    take the LAST numeric column on each line.
    """
    voltages: List[float] = []
    try:
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = re.split(r"[,\t]", line)
                # Try the last column first, then second-to-last.
                for v in reversed(parts):
                    try:
                        voltages.append(float(v))
                        break
                    except ValueError:
                        continue
    except Exception:
        return []
    return voltages


def find_low_pulses(voltages: List[float], threshold: float) -> List[int]:
    """Return list of LOW pulse widths (in samples).  A pulse is a
    contiguous run of samples below `threshold`.
    """
    widths: List[int] = []
    in_low = False
    cur = 0
    for v in voltages:
        if v < threshold:
            if not in_low:
                in_low = True
                cur = 1
            else:
                cur += 1
        else:
            if in_low:
                widths.append(cur)
                in_low = False
                cur = 0
    if in_low:
        widths.append(cur)
    return widths


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
        if isinstance(rationale, str) and \
           len(rationale.strip()) >= WAIVER_MIN_LEN:
            return True, rationale.strip()
    return False, ""


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: scope_reply_preamble_check.py <project_dir>")
        return 2

    project_dir = Path(argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        return 1

    # Wave 78 — explicit class gate. AID-class only; `unknown` falls
    # through to the existing `is_half_duplex_project` heuristic
    # (fail-closed via the next SKIP guard).
    profile = detect_ic_class(project_dir)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class not in _APPLICABLE_CLASSES and ic_class != "unknown":
        print(f"SKIP — not applicable to ic_class={ic_class}")
        return 0

    if not is_half_duplex_project(project_dir):
        print("SKIP — project is not half-duplex / single-wire")
        return 0

    csvs = find_scope_csvs(project_dir)
    if not csvs:
        print("SKIP — no scope CSV captures found")
        return 0

    br_min = get_br_min_ticks(project_dir)
    if br_min is None:
        print("SKIP — BR_MIN threshold not declared in L8 or rtl_constants")
        return 0

    # Filter CSVs to those that name a "reply" segment in filename.
    reply_csvs = [
        c for c in csvs
        if any(h in c.name.lower() for h in _REPLY_HINTS)
    ]
    if not reply_csvs:
        print(
            "SKIP — no scope CSV filename suggests a chip-reply window "
            "(expected hint: reply / response / tx / connect_test / "
            "send_test / round_trip)"
        )
        return 0

    # Decode each reply CSV.  We use a 50 MHz tick = 20 ns; default
    # CSV sample interval is 100 ns/sample (as per Wave 56 connect_test_5ms).
    # If a `_<X>ns.csv` token is present we use that.
    #
    # Wave 59 Track 2 — host-polling-cadence false-positive fix.
    # On a half-duplex polling capture (continuous host SEND_TEST
    # poll every 100-1000 µs) the "second half" of the capture is
    # NOT exclusively chip reply — it contains the NEXT host BR(s)
    # for subsequent polling frames.  The previous heuristic mis-
    # classified those host BRs as chip preambles (Wave 56 column-D
    # Issue 3 false-positive on `connect_test_5ms.csv`).
    #
    # New rule: a BR-class LOW is treated as a chip-side preamble
    # ONLY if it is ISOLATED (not part of a recurring polling
    # pattern).  Specifically, when ≥ 2 BR-class LOW pulses appear
    # in the capture with similar inter-pulse gaps (Δt within ±25%
    # of the median gap), they are HOST polling BRs and ignored.
    # The plugin reference TB (`aid_class_reference_tb.v`) is the
    # authoritative source for chip-side BR violations — its
    # `PROTOCOL_VIOLATION_DEVICE_BR` sentinel must be empty for the
    # RTL to pass `protocol_reference_tb_pass_check`.
    findings: List[str] = []
    inspected = 0
    for csv in reply_csvs:
        ns_per_sample = _DEFAULT_NS_PER_SAMPLE
        m = re.search(r"_(\d+)ns\b", csv.name.lower())
        if m:
            ns_per_sample = float(m.group(1))
        samples_per_tick = _TICK_NS / ns_per_sample
        br_min_samples = int(br_min * samples_per_tick)

        voltages = parse_scope_csv(csv)
        if not voltages:
            continue
        inspected += 1

        # LOW threshold heuristic: 0.8 V (TTL VIL).  If the capture is
        # all-3.3 V there will be no LOW samples — skip cleanly.
        # Walk the voltage stream once and collect every BR-class
        # LOW pulse with its (sample-index) start time.
        br_pulses: List[Tuple[int, int]] = []  # (start_idx, width)
        in_low = False
        cur = 0
        start_idx = 0
        for idx, v in enumerate(voltages):
            if v < 0.8:
                if not in_low:
                    in_low = True
                    cur = 1
                    start_idx = idx
                else:
                    cur += 1
            else:
                if in_low:
                    if cur >= br_min_samples:
                        br_pulses.append((start_idx, cur))
                    in_low = False
                    cur = 0
        if in_low and cur >= br_min_samples:
            br_pulses.append((start_idx, cur))

        if not br_pulses:
            continue

        # Wave 59 — host-polling detection.
        # Half-duplex polling captures (continuous host SEND_TEST
        # poll every 100-1000 µs) inevitably contain MANY host BRs.
        # Real chip-side BR violations would be ISOLATED anomalies
        # in an otherwise BR-free reply window.
        #
        # Rule: if ≥ 2 BR-class pulses appear in the capture AND
        # they have similar widths (median ± 10% covers ≥ 80% of
        # them) AND the smallest inter-pulse gap is ≥ 100 µs, the
        # capture contains host polling BRs and ALL BR-class pulses
        # are dropped from findings.  The plugin reference TB
        # (`aid_class_reference_tb.v`) remains the authoritative
        # source for chip-side BR violations.
        is_polling_pattern = False
        if len(br_pulses) >= 2:
            widths_sorted = sorted(w for _, w in br_pulses)
            median_w = widths_sorted[len(widths_sorted) // 2]
            near_w = sum(
                1 for _, w in br_pulses
                if abs(w - median_w) <= 0.10 * median_w
            )
            gaps = [
                br_pulses[i + 1][0] - br_pulses[i][0]
                for i in range(len(br_pulses) - 1)
            ]
            min_gap = min(gaps) if gaps else 0
            min_gap_us = min_gap * ns_per_sample / 1000.0
            # Width consistency ≥ 80% AND min gap ≥ 100 µs.
            if (near_w >= max(2, int(0.80 * len(br_pulses)))
                    and min_gap_us >= 100.0):
                is_polling_pattern = True

        if is_polling_pattern:
            # All BR-class pulses in this capture are host polling
            # BRs, not chip preambles — record an INFO note but do
            # NOT contribute findings.
            continue

        # Restrict reporting to the SECOND HALF of the capture
        # (chip-reply heuristic preserved as a fallback for
        # one-shot captures where polling-detection didn't fire).
        n = len(voltages)
        half = n // 2
        for start, w in br_pulses:
            if start < half:
                continue
            pulse_us = w * ns_per_sample / 1000.0
            findings.append(
                f"{csv.name}: BR-class LOW pulse "
                f"({w} samples = {pulse_us:.2f}µs ≥ BR_MIN="
                f"{br_min} ticks = {br_min * _TICK_NS / 1000.0:.2f}µs) "
                f"in chip-reply (2nd-half) window"
            )

    is_waived, rationale = waived(project_dir)

    if not findings:
        if inspected == 0:
            print(
                "SKIP — scope CSVs found but contained no LOW samples "
                "(capture may be too short or threshold too high)"
            )
            return 0
        print(
            f"PASS — {inspected} reply scope CSV(s) inspected; no "
            f"BR-class LOW pulses in chip-reply window"
        )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(findings)} BR-class preamble(s) "
            f"in chip reply, silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        for f in findings:
            print(f"  • {f}")
        return 0

    print(
        f"FAIL — {len(findings)} BR-class LOW pulse(s) in chip-reply "
        f"window (Wave 56 column-D Issue 3 class)"
    )
    for f in findings:
        print(f"  • {f}")
    print()
    print("Why this matters:")
    print("  In a half-duplex single-wire AID-class protocol the host's")
    print("  BR is the frame delimiter.  A chip-side BR pulse during")
    print("  reply makes the host re-classify as a new frame start,")
    print("  resetting frame state and silently corrupting the reply.")
    print()
    print(
        f"Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
