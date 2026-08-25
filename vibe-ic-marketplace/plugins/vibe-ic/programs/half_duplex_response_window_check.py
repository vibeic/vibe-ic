#!/usr/bin/env python3
"""half_duplex_response_window_check.py — LL-4.

Static-analysis gate. For half-duplex command-response ICs, parse
package-level RTL constants and L2 timing spec, compute upper-bound chip
response latency, and verify it fits within the half-duplex master's
expected receive window.

Computation:

  chip_latency_us = FRAME_END_GAP_us
                  + dispatch_overhead_us       (guess: 4 cycles @ clk_mhz)
                  + TSRS_MIN_us
                  + max(TX_BIT0_LOW_us, TX_BIT1_LOW_us)

Constraint (derived from L2 alone, no oracle):

  chip_latency_us <= L2.ibt_us[1] + 3.0 * L2.tSRS_min_us

i.e., the chip must respond within roughly ibt_max + 3 slot-times. The
3× factor is calibrated against empirical <benchmark> data: a v0118 RTL with
67us total latency PASSes on <half-duplex-tester>, a 117us version FAILs. The 3×
factor admits ~82us as the boundary, leaving headroom but flagging
clear over-budget cases like the v0118 80us-FRAME_END_GAP bug.

If a project's master is known to be stricter, add `tSRS_max_us` to L2
and the gate will use that directly when present.

False-alert escape hatches
==========================

  - L2.tSRS_max_us — when present, overrides the plugin-default budget
    formula (highest-precedence override).
  - L2.response_window_factor — float (default 3.0); multiplied with
    L2.tSRS_min_us to form the budget when tSRS_max_us absent.
  - waivers.json entry `half_duplex_response_window_override` skips the
    gate when present with non-empty rationale.

This gate would have HARD-FAILED the v0118-vendor bug (FRAME_END_GAP=80us
+ dispatch + TSRS_MIN=30us > 22us + 1.5*20us = 52us → FAIL).

The gate is **structural** (parses RTL constants), not behavioral —
runs in CI without any HW or testbench.

THE MASTER-SIDE HALF, DISCLOSED AND NEVER REFUSED ON
====================================================
The budget above is the CHIP's: does the part answer before the master stops
listening. The mirror question is the bench's: is the master's response-capture
window long enough for the LONGEST response. A window sized for the median
response silently truncates the longest one and the CRC residual then reports a
bogus "CRC error" for every long opcode — a timing-window bug wearing a CRC
bug's clothes.

`bist_window_calculator.size_window` is that computation and it is IMPORTED
here rather than restated, because this gate has already parsed every input it
takes: the TX-PHY bit-cell constants, L2's inter-byte gap, and the checker
clock. The result lands in `summary["bist_capture_window"]` and in the printed
report.

IT IS A DISCLOSURE, NOT A FINDING. An undersized capture window is a property
of the BENCH HARNESS, not of the RTL this gate judges; failing a design for it
would refuse the design for somebody else's constant. When an input is missing
the entry says which one, because "not sized" and "sized to zero" must not read
alike.

Exit codes: 0 PASS / 1 FAIL (strict) / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import find_rtl_files, read_text
import _path_layout as _pl
import bist_window_calculator as _bist


def _l8_dispatch_cycles(project: Path) -> int | None:
    """Return L8.dispatch_cycles_at_50MHz override if declared, else None.

    Allows designs with non-default dispatch overhead (CDC pipelines,
    pre-fetch stages, wider FSMs) to report the real cycle count so the
    response-window math reflects reality. Without this, the gate
    used a hard-coded 4-cycle default and could silent-pass on real
    over-budget designs whose dispatch is e.g. 8 cycles.
    """
    for cand in (
        list(project.glob("phase1/generated_docs/L8*.json"))
        + list(project.glob("L8*.json"))
        + list(project.glob("input/docs/L8*.json"))
    ):
        try:
            data = json.loads(read_text(cand) or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue

        def _walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == "dispatch_cycles_at_50MHz" and \
                       isinstance(v, (int, float)) and v >= 0:
                        return int(v)
                    r = _walk(v)
                    if r is not None:
                        return r
            elif isinstance(obj, list):
                for item in obj:
                    r = _walk(item)
                    if r is not None:
                        return r
            return None
        n = _walk(data)
        if n is not None:
            return n
    return None


def _waiver_rationale(project: Path, waiver_id: str) -> str:
    for cand in (project / "waivers.json", *project.glob("**/waivers.json")):
        if not cand.exists():
            continue
        try:
            data = json.loads(read_text(cand) or "{}")
        except json.JSONDecodeError:
            continue
        entries = data if isinstance(data, list) else (
            data.get("waivers") or data.get("waived_steps") or []
        )
        if not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            if e.get("id") == waiver_id:
                rat = e.get("rationale") or e.get("reason") or ""
                if isinstance(rat, str) and rat.strip():
                    return rat.strip()
    return ""


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""


_LOCALPARAM_RE = re.compile(
    r"localparam\s+(?:int\s+)?(?:logic\s+(?:\[[^\]]+\]\s+)?)?"
    r"(\w+)\s*=\s*([^;,)]+)[;,)]"
)
_PARAMETER_RE = re.compile(
    r"\bparameter\s+(?:int\s+)?(?:logic\s+(?:\[[^\]]+\]\s+)?)?"
    r"(\w+)\s*=\s*([^;,)]+)[;,)]"
)


def _parse_constants(rtl_files: list[Path]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in rtl_files:
        text = read_text(f)
        for regex in (_LOCALPARAM_RE, _PARAMETER_RE):
            for m in regex.finditer(text):
                name = m.group(1)
                expr = m.group(2).strip()
                # Handle Verilog literals: 8'h74, 5'd10, simple ints
                num_match = re.match(r"(?:\d+\s*'\s*[hHbBdD])?(\w+)", expr)
                if num_match:
                    val_str = num_match.group(1)
                    try:
                        if val_str.startswith("0x") or val_str.startswith("0X"):
                            out[name] = int(val_str, 16)
                        else:
                            # Verilog '?... base
                            base_match = re.match(
                                r"\d+\s*'\s*([hHbBdD])(\w+)", expr
                            )
                            if base_match:
                                base_char = base_match.group(1).lower()
                                base = {"h": 16, "b": 2, "d": 10, "o": 8}[base_char]
                                out[name] = int(base_match.group(2), base)
                            else:
                                out[name] = int(val_str)
                    except (ValueError, KeyError):
                        continue
    return out


def _detect_clk_mhz(constants: dict[str, int], project: Path) -> int | None:
    """Detect the clock rate at which the RTL constants are evaluated.

    Strategy: collect candidate rates from L8 + RTL parameters, then pick
    the one that makes FRAME_END_GAP fall into a plausible window
    [5us, 200us]. This auto-corrects when L8 says 5MHz but RTL was
    refactored to 50MHz (or vice versa).
    """
    candidates: list[int] = []
    for cand in (
        _pl.generated_docs_dir(project) / "L8_RTL_CONSTANTS.json",
        project / "input" / "docs" / "L8_RTL_CONSTANTS.json",
    ):
        if cand.exists():
            try:
                data = json.loads(cand.read_text())
                for k in ("internal_clock_MHz", "fpga_prediv_clock_MHz"):
                    if k in data:
                        candidates.append(int(data[k]))
            except Exception:
                pass
    for k in ("CLK_MHZ", "INTERNAL_CLK_MHZ", "CLK_FREQ_MHZ"):
        if k in constants:
            candidates.append(constants[k])
    if not candidates:
        return None

    fe = constants.get("FRAME_END_GAP") or constants.get("CYC_FRAME_END")
    if fe is None:
        # No way to validate — return first candidate
        return candidates[0]
    # Pick the rate that makes FRAME_END_GAP land in a reasonable us range
    PLAUSIBLE_MIN_US, PLAUSIBLE_MAX_US = 5.0, 200.0
    for rate in sorted(set(candidates), reverse=True):
        us = fe / rate
        if PLAUSIBLE_MIN_US <= us <= PLAUSIBLE_MAX_US:
            return rate
    return candidates[0]


def _ibt_max_and_tsrs(project: Path) -> tuple[
        float | None, float | None, float | None]:
    """Return (ibt_max_us, tsrs_min_us, tsrs_max_us). max may be None."""
    for cand in (
        _pl.generated_docs_dir(project) / "L2_TIMING_WAVEFORM.json",
        project / "input" / "docs" / "L2_TIMING_WAVEFORM.json",
    ):
        if cand.exists():
            try:
                data = json.loads(cand.read_text())
                ibt = data.get("ibt_us")
                ibt_max = (float(ibt[1]) if isinstance(ibt, list)
                           and len(ibt) >= 2 else None)
                tsrs_min = data.get("tSRS_min_us")
                tsrs_max = data.get("tSRS_max_us")
                tsrs_min = (float(tsrs_min)
                            if isinstance(tsrs_min, (int, float))
                            else None)
                tsrs_max = (float(tsrs_max)
                            if isinstance(tsrs_max, (int, float))
                            else None)
                return ibt_max, tsrs_min, tsrs_max
            except Exception:
                pass
    return None, None, None


_L3_GLOBS = (
    "phase1/generated_docs/L3_CMD_PROTOCOL.json",
    "phase1/generated_docs/L3*.json",
    "input/docs/L3*.json",
)
#: Per-command response-length carriers, in the order `frame_end_gap_in_l8_check`
#: and `l3_opcode_response_template_check` already read them. One convention,
#: three readers -- a fourth spelling invented here would be a fourth answer.
_RSP_LEN_KEYS = ("response_bytes", "response_payload", "response_length",
                 "rsp_len", "response_len")
_HEX_BYTE_RE = re.compile(r"\b[0-9A-Fa-f]{2}\b")


def _len_of_response(value) -> int | None:
    """Bytes in one command-table response entry, or None if it says nothing.

    Three shapes are in the corpus and all three mean a length: an int IS the
    count, a list is counted, and a hex-byte string is tokenised. A shape this
    cannot read returns None and is left out of the max rather than counted as
    zero -- a zero would shorten the window this exists to lengthen.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, list):
        return len(value) or None
    if isinstance(value, str):
        n = len(_HEX_BYTE_RE.findall(value))
        return n or None
    return None


def _max_response_bytes(project: Path) -> tuple[int | None, str]:
    """Longest response the L3 command table declares, and where it came from."""
    for pat in _L3_GLOBS:
        for cand in sorted(project.glob(pat)):
            if not cand.is_file():
                continue
            try:
                data = json.loads(read_text(cand) or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            cmds = data.get("command_table") or data.get("commands")
            if not isinstance(cmds, list):
                continue
            lengths = [n for c in cmds if isinstance(c, dict)
                       for n in (max((v for v in (
                           _len_of_response(c.get(k)) for k in _RSP_LEN_KEYS)
                           if v is not None), default=None),)
                       if n is not None]
            if lengths:
                return max(lengths), f"{cand.name}.command_table"
    return None, ""


def _bit_cell_us(constants: dict[str, int], clk_mhz: float
                 ) -> tuple[float | None, str]:
    """Longest FULL TX bit cell (LOW + HIGH) in us, or None with the reason.

    The latency budget above needs only the LOW half of the first bit; a
    capture window has to hold whole bit cells, so the HIGH half is required
    here and its absence is reported rather than defaulted.
    """
    def pick(*names: str) -> int | None:
        for n in names:
            v = constants.get(n)
            if isinstance(v, int) and v > 0:
                return v
        return None

    cells: list[int] = []
    missing: list[str] = []
    for bit in ("0", "1"):
        low = pick(f"TX_BIT{bit}_LOW", f"CYC_TX_BIT{bit}_LOW",
                   f"H{bit}_LOW_TICKS", f"BIT{bit}_LOW_TICKS")
        high = pick(f"TX_BIT{bit}_HIGH", f"CYC_TX_BIT{bit}_HIGH",
                    f"H{bit}_HIGH_TICKS", f"BIT{bit}_HIGH_TICKS")
        if low is not None and high is not None:
            cells.append(low + high)
        elif low is not None:
            missing.append(f"TX_BIT{bit}_HIGH")
    if not cells:
        return None, ("no complete TX bit cell in RTL (need both the LOW and "
                      "the HIGH half of at least one bit; missing: "
                      + (", ".join(missing) or "all TX_BIT*_LOW/HIGH") + ")")
    return max(cells) / clk_mhz, ""


def _capture_window(project: Path, constants: dict[str, int], clk_mhz: float,
                    ibt_max_us: float | None) -> dict:
    """Master-side capture-window sizing -- ADVISORY, never a Finding.

    Delegates the arithmetic to `bist_window_calculator.size_window` so the
    bench number this reports and the number that program's CLI prints are the
    same number.
    """
    if ibt_max_us is None:
        return {"sized": False, "reason": "L2 has no ibt_us[1]"}
    bit_us, why = _bit_cell_us(constants, clk_mhz)
    if bit_us is None:
        return {"sized": False, "reason": why}
    max_bytes, src = _max_response_bytes(project)
    if max_bytes is None:
        return {"sized": False,
                "reason": "no per-command response length in the L3 command "
                          "table (looked for: " + ", ".join(_RSP_LEN_KEYS) + ")"}
    w = _bist.size_window(max_bytes, bit_us, float(clk_mhz),
                          ibt_us=float(ibt_max_us))
    w.update({"sized": True, "max_bytes_source": src,
              "computed_by": "bist_window_calculator.size_window"})
    return w


def _is_half_duplex(project: Path) -> bool:
    ibt, tsrs, _ = _ibt_max_and_tsrs(project)
    return ibt is not None and tsrs is not None


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "is_half_duplex": False,
        "clk_mhz": None,
        "frame_end_gap_us": None,
        "tsrs_min_us": None,
        "tx_bit_low_max_us": None,
        "ibt_max_us_l2": None,
        "tsrs_min_us_l2": None,
        "chip_latency_us": None,
        "budget_us": None,
        "bist_capture_window": {"sized": False,
                                "reason": "gate did not reach the sizing step"},
        "skipped_reason": "",
    }
    if not _is_half_duplex(project):
        summary["skipped_reason"] = "non-half-duplex (no L2 ibt_us+tSRS)"
        return findings, summary
    summary["is_half_duplex"] = True

    waiver = _waiver_rationale(project, "half_duplex_response_window_override")
    if waiver:
        summary["skipped_reason"] = (
            f"waiver half_duplex_response_window_override: {waiver[:80]}"
        )
        return findings, summary

    rtl_files = find_rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files found"
        return findings, summary

    constants = _parse_constants(rtl_files)
    clk_mhz = _detect_clk_mhz(constants, project)
    if clk_mhz is None:
        summary["skipped_reason"] = "could not detect clock frequency"
        return findings, summary
    summary["clk_mhz"] = clk_mhz

    def ticks_to_us(ticks: int | None) -> float | None:
        return float(ticks) / clk_mhz if ticks is not None else None

    fe = constants.get("FRAME_END_GAP") or constants.get("CYC_FRAME_END")
    tsrs = constants.get("TSRS_MIN") or constants.get("CYC_TX_RSP_DELAY")
    bit0_low = constants.get("TX_BIT0_LOW") or constants.get("CYC_TX_BIT0_LOW")
    bit1_low = constants.get("TX_BIT1_LOW") or constants.get("CYC_TX_BIT1_LOW")

    if fe is None or tsrs is None:
        # v0.119.1 hardening: if RTL has SOME constants but none of the
        # expected latency names matched, the project likely uses a
        # vendor-specific naming convention. Surface as WARNING with the
        # expected-name list so the engineer either renames the constants
        # or files an L8 alias entry — instead of letting the gate
        # silently skip and leave the over-budget latency uncaught.
        # If RTL has zero constants, silent skip is still correct.
        if constants:
            summary["constants_found_count"] = len(constants)
            summary["latency_constants_missing"] = [
                n for n, v in (("FRAME_END_GAP", fe),
                               ("TSRS_MIN", tsrs)) if v is None
            ]
            findings.append(Finding(
                # Use ERROR severity so --strict upgrades correctly. In
                # no-strict mode this gate still exits 0 (the existing
                # main() returns 0 unless `args.strict and not passed`),
                # so the finding behaves like a WARNING by default and
                # an ERROR under CI strict mode — matching the "fail
                # loudly when CI runs strict" intent.
                severity="ERROR",
                rule="HALF_DUPLEX_LATENCY_CONSTANTS_NOT_FOUND",
                message=(
                    f"Half-duplex protocol-IP design declares L1/L2/L3 "
                    f"timing markers but the response-latency constants "
                    f"`FRAME_END_GAP / CYC_FRAME_END` and/or "
                    f"`TSRS_MIN / CYC_TX_RSP_DELAY` are absent from RTL "
                    f"(found {len(constants)} other localparams / "
                    f"parameters). Either (a) rename the project's "
                    f"latency constants to match one of the recognised "
                    f"names listed above, or (b) add a waiver "
                    f"`half_duplex_response_window_override` documenting "
                    f"the alternative naming. Without recognised "
                    f"constants the gate cannot verify the chip-response "
                    f"latency budget and v0118-class bugs go silent."
                ),
            ))
            return findings, summary
        summary["skipped_reason"] = (
            f"missing constants in RTL: FRAME_END_GAP={fe} TSRS_MIN={tsrs}"
        )
        return findings, summary

    fe_us = ticks_to_us(fe)
    tsrs_us = ticks_to_us(tsrs)
    bit_low_max_us = max(
        x for x in (ticks_to_us(bit0_low), ticks_to_us(bit1_low))
        if x is not None
    ) if (bit0_low or bit1_low) else 0.0
    summary["frame_end_gap_us"] = fe_us
    summary["tsrs_min_us"] = tsrs_us
    summary["tx_bit_low_max_us"] = bit_low_max_us

    ibt_max_l2, tsrs_min_l2, tsrs_max_l2 = _ibt_max_and_tsrs(project)
    summary["ibt_max_us_l2"] = ibt_max_l2
    summary["tsrs_min_us_l2"] = tsrs_min_l2
    summary["tsrs_max_us_l2"] = tsrs_max_l2
    if ibt_max_l2 is None or tsrs_min_l2 is None:
        summary["skipped_reason"] = "L2 missing ibt_us[1] or tSRS_min_us"
        return findings, summary

    # Conservative dispatch overhead: 4 cycles @ clk_mhz unless the
    # project documents otherwise via L8.dispatch_cycles_at_50MHz
    # (v0.119.1). The override is the absolute number of dispatch-FSM
    # cycles (clock-domain-invariant — same FSM transitions whether the
    # chip is clocked at 5 MHz or 50 MHz; only the wall-clock duration
    # changes). Designs with multi-cycle CDC pipelines, wider dispatch
    # FSMs, or pre-fetch stages should declare the real cycle count
    # here so the latency budget reflects reality.
    dispatch_cycles = _l8_dispatch_cycles(project)
    if dispatch_cycles is None:
        dispatch_cycles = 4  # default: conservative lower bound
        summary["dispatch_cycles_source"] = "default"
    else:
        summary["dispatch_cycles_source"] = "L8.dispatch_cycles_at_50MHz"
    dispatch_us = float(dispatch_cycles) / clk_mhz
    summary["dispatch_cycles"] = dispatch_cycles
    summary["dispatch_us"] = dispatch_us

    chip_latency_us = fe_us + dispatch_us + tsrs_us + bit_low_max_us
    # Budget: prefer L2.tSRS_max if present, else fall back to a
    # plugin-default heuristic of ibt_max + 3 * tSRS_min (calibrated to
    # admit working v0118 67us latency, reject 117us bug).
    if tsrs_max_l2 is not None:
        budget_us = tsrs_max_l2
        budget_basis = "L2.tSRS_max_us"
    else:
        # L2 may override the multiplier
        l2_data = {}
        for cand in (_pl.generated_docs_dir(project) / "L2_TIMING_WAVEFORM.json",
                     project / "input" / "docs" / "L2_TIMING_WAVEFORM.json"):
            if cand.exists():
                try:
                    l2_data = json.loads(cand.read_text())
                    break
                except Exception:
                    pass
        factor = l2_data.get("response_window_factor")
        if not isinstance(factor, (int, float)):
            factor = 3.0
        budget_us = ibt_max_l2 + factor * tsrs_min_l2
        budget_basis = (
            f"L2.ibt_max + {factor}*L2.tSRS_min "
            f"(factor from L2.response_window_factor or default 3.0)"
        )
    summary["chip_latency_us"] = chip_latency_us
    summary["budget_us"] = budget_us
    summary["budget_basis"] = budget_basis

    # ADVISORY (never a Finding, never an rc): the BENCH-side window that has
    # to hold the LONGEST response, sized by `bist_window_calculator`.
    summary["bist_capture_window"] = _capture_window(
        project, constants, clk_mhz, ibt_max_l2)

    if chip_latency_us > budget_us:
        findings.append(Finding(
            severity="ERROR",
            rule="HALF_DUPLEX_RESPONSE_WINDOW_EXCEEDED",
            message=(
                f"Chip response latency upper-bound {chip_latency_us:.1f}us "
                f"exceeds half-duplex receive-window budget {budget_us:.1f}us "
                f"derived from L2 (ibt_max={ibt_max_l2}us + 1.5*tSRS_min="
                f"{tsrs_min_l2}us). Latency breakdown: "
                f"FRAME_END_GAP={fe_us:.1f}us + dispatch={dispatch_us:.2f}us "
                f"+ TSRS_MIN={tsrs_us:.1f}us + first_bit_low="
                f"{bit_low_max_us:.1f}us. "
                f"Reduce FRAME_END_GAP and/or TSRS_MIN; or document an L2 "
                f"override if the master genuinely tolerates this latency."
            ),
        ))
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="half_duplex_response_window_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    passed = not any(f.severity == "ERROR" for f in findings) or not args.strict

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "half_duplex_response_window_check",
            "passed": passed,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== half_duplex_response_window_check ({project.name}) ===")
    if summary.get("skipped_reason"):
        print(f"skipped: {summary['skipped_reason']}")
        return 0
    print(f"clk={summary['clk_mhz']}MHz  L2 ibt_max="
          f"{summary['ibt_max_us_l2']}us  L2 tSRS_min={summary['tsrs_min_us_l2']}us")
    print(f"  chip latency = FRAME_END_GAP({summary['frame_end_gap_us']}us) "
          f"+ dispatch + TSRS_MIN({summary['tsrs_min_us']}us) + bit_low("
          f"{summary['tx_bit_low_max_us']}us)")
    print(f"  total = {summary['chip_latency_us']}us  budget = "
          f"{summary['budget_us']}us")
    win = summary.get("bist_capture_window") or {}
    if win.get("sized"):
        print(f"  bench capture window (advisory, via "
              f"bist_window_calculator): {win['window_us']:.1f}us for "
              f"{win['max_bytes']}B  -> WIN_CYCLES={win['win_cycles']} "
              f"SEQ_RX_CYCLES={win['seq_rx_cycles']}")
    else:
        print(f"  bench capture window: NOT SIZED — {win.get('reason', '?')}")
    for f in findings:
        print(f"[{f.severity}] {f.rule}: {f.message}")
    if not findings:
        print("PASS — chip response latency within half-duplex budget")
        return 0
    return 1 if args.strict and not passed else 0


if __name__ == "__main__":
    sys.exit(main())
