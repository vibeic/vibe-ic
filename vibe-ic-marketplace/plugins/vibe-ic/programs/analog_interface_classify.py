#!/usr/bin/env python3
"""analog_interface_classify.py — structural L9 top-interface classifier
(ORGANIC #144-sibling, filed as #141).

Answers ONE chip-AGNOSTIC structural question: does the top interface expose
any DIGITAL clock / reset / data INPUT, or is it entirely analog?

Motivation
----------
An ADC / data-converter whose actual top interface is 100% analog (analog
inputs, analog supplies/refs, and raw 1-bit modulator-bitstream OUTPUTS, with
the digital decimation/serial-readout scoped OFF-chip) is classified
`data_converter` — which makes the digital `spec-to-rtl` step mandatory — and
then hard-FAILs, because there is no honest synthesizable digital datapath to
author (synthesizable RTL needs a clock, and this pinout provides no digital
clock/reset/data INPUT). Fabricating one violates the no-invention rule.

The discriminator is purely STRUCTURAL and name-independent of any chip: an
all-analog `top_ports` set with NO digital clock/reset/data INPUT port is a
`DIGITAL_DATAPATH_ABSENT` interface. Such a design routes its digital RTL→GDS
steps to N/A / SKIPPED-CONDITION (exactly as the analog A-steps skip on a
digital-only design), instead of WAIVE→spec-to-rtl→FAIL.

A data_converter that DOES expose a digital clk/rst/data interface (real
on-chip decimation) is UNCHANGED — it keeps authoring RTL.

Fail-SAFE bias
--------------
When the direction/type is ambiguous or a non-analog input cannot be
positively recognised as analog, the port is treated as a *digital data
input* — i.e. the interface is judged to HAVE a digital datapath and the RTL
path is kept. Routing to N/A only fires when the interface is UNAMBIGUOUSLY
all-analog. Dropping a real digital datapath is worse than an honest FAIL, so
the default keeps RTL.

Usage:
    python3 analog_interface_classify.py <project> [--json out.json]
    exit 0 → digital_datapath_absent (all-analog interface)
    exit 1 → a digital clk/rst/data input is present (keep RTL)
    exit 2 → indeterminate (no L9 / no top_ports)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── digital clock / reset input name patterns (aligned with the plugin's
#    existing cvdp_complete_extract convention set) ─────────────────────────
# vibe-ic dfa75131a — `ck<N>` AND `phi<N>` ARE CLOCKS. They are the standard
# switched-capacitor spellings, and omitting them made a pin's CLASS depend on
# how its designer spelled it: measured on this file before the fix, only the
# spelling changed between the two rows —
#
#     ck1,  ck2   -> digital_data_input   (has_digital_clock_input=False)
#     clk1, clk2  -> digital_clk_input    (has_digital_clock_input=True)
#
# It was also an INTERNAL inconsistency, not merely an omission: in the SAME
# plugin version `harness_exact_selfverify._CLOCK_NAME_RE` already matches
# `ck`/`ck1`/`ck4`. Two regexes in one plugin disagreed about what a clock is,
# and the analog track got the losing one — an SC modulator whose own L1 calls
# CK4/CK5/CK6 "modulator clocks" had them classified as DATA.
#
# SCOPE, stated so this is not over-read: fixing the regex does NOT by itself
# reroute such a design. `digital_datapath_absent` is
# `not (has_clk or has_rst or has_data)`, so ANY clock still forces the digital
# track. A clocked-but-logic-free SC modulator (clock in, bitstream out, no
# data, no reset) is exactly the case that predicate cannot express. That is a
# separate design decision and is deliberately NOT bundled here.
_CLK_RE = re.compile(
    r"(?i)^(clk|clock|ck|phi|sclk|aclk|hclk|pclk|mclk|refclk|xclk|clkin)"
    r"(\d+)?"
    r"([_\.]?(in|i|sys|core|div|gen|en|ref))?(\d+)?$")
_RST_RE = re.compile(
    r"(?i)(^|_)(rst|reset|arst|areset|srst|nreset|resetn|rstn|por)"
    r"([_\.]?(in|i|n|b|async|sync))?($|_)")
_AMBA_RST_RE = re.compile(r"(?i)^[abph]reset_?n$")

# ── analog port name patterns (supply / reference / analog signal) ──────────
# Voltage supplies & references: v/av/dv prefix, or a named supply/ref token.
_ANALOG_SUPPLY_RE = re.compile(
    r"(?i)^(a?v(dd|ss|cc|ee|pp|nn)|vbg|vref|vcm|vbias|vb|vhi|vlo|vldo|vddio|"
    r"vdda|vssa|vddd|vssd|agnd|dgnd|gnd|avdd|avss|dvdd|dvss|vpwr|vgnd|vnb|vpb)"
    r"[a-z0-9_]*$")
# Analog signal ins/outs, biases, currents, converter references.
_ANALOG_SIGNAL_RE = re.compile(
    r"(?i)^("
    r"v(in|out|ip|im|inp|inn|op|om|refp|refn|cm|p|n)|"    # v-signals
    r"a?in|a?out|ain|aout|"                                # analog in/out
    r"in|out|inp|inn|outp|outn|"                           # bare in/out
    r"i(ref|bias|in|out|b)|iref|ibias|"                   # currents
    r"sig|comp|bg|bandgap|ptat|ctat|bias|ref"             # references/bias
    r")(\d+)?([_\.]?(p|n|m|in|out|ref|bias|pos|neg))?(\d+)?$")
# type / description tokens that assert analog nature.
_ANALOG_WORD_RE = re.compile(r"(?i)\banalog\b|\bcurrent\b|\bvoltage\b")
_DIGITAL_WORD_RE = re.compile(r"(?i)\bdigital\b|\bclock\b|\breset\b|\bserial\b")


def _norm_dir(port: Dict[str, Any]) -> str:
    """Normalise the port direction to input/output/inout/unknown."""
    for key in ("direction", "dir", "mode", "io"):
        v = port.get(key)
        if isinstance(v, str) and v.strip():
            s = v.strip().lower()
            if s in ("input", "in", "i"):
                return "input"
            if s in ("output", "out", "o"):
                return "output"
            if s in ("inout", "bidir", "bidirectional", "io"):
                return "inout"
    return "unknown"


def _port_text(port: Dict[str, Any]) -> str:
    return " ".join(
        str(port.get(k, "")) for k in
        ("type", "signal_type", "kind", "class", "description", "desc", "note"))


def _is_analog_name(name: str, ptext: str) -> bool:
    n = name.strip()
    if _ANALOG_SUPPLY_RE.match(n) or _ANALOG_SIGNAL_RE.match(n):
        return True
    if _ANALOG_WORD_RE.search(ptext) and not _DIGITAL_WORD_RE.search(ptext):
        return True
    return False


def _is_clock_name(name: str) -> bool:
    return bool(_CLK_RE.match(name.strip()))


def _is_reset_name(name: str) -> bool:
    n = name.strip()
    return bool(_RST_RE.search(n) or _AMBA_RST_RE.match(n))


def classify_port(port: Any) -> str:
    """Classify a single top port. Returns one of:
       digital_clk_input | digital_rst_input | digital_data_input |
       analog_input | analog_supply_inout | analog_or_bitstream_output |
       indeterminate

    Only INPUT-capable ports (input / inout / unknown-direction) can be a
    digital clk/rst/data SOURCE; an output can never be a digital input to the
    datapath (a modulator-bitstream OUT / on-chip-generated clock OUT is not a
    digital datapath input)."""
    if isinstance(port, str):
        port = {"name": port}
    if not isinstance(port, dict):
        return "indeterminate"
    name = str(port.get("name") or "").strip()
    if not name:
        return "indeterminate"
    ptext = _port_text(port)
    dirn = _norm_dir(port)

    # A type/description that explicitly says clock/reset/digital + input dir.
    if dirn == "output":
        # outputs are never a digital datapath INPUT — analog out, converter
        # bitstream out, or on-chip-generated clock out all live here.
        return "analog_or_bitstream_output"

    # input / inout / unknown → could be a digital source.
    if _is_clock_name(name):
        return "digital_clk_input"
    if _is_reset_name(name):
        return "digital_rst_input"
    if _is_analog_name(name, ptext):
        return "analog_supply_inout" if dirn == "inout" else "analog_input"
    # Unrecognised input → fail-safe: treat as a DIGITAL data input (keep RTL).
    return "digital_data_input"


def classify_top_ports(ports: List[Any]) -> Dict[str, Any]:
    per_port = []
    has_clk = has_rst = has_data = False
    for p in ports:
        cls = classify_port(p)
        nm = p.get("name") if isinstance(p, dict) else p
        per_port.append({"name": nm, "class": cls})
        if cls == "digital_clk_input":
            has_clk = True
        elif cls == "digital_rst_input":
            has_rst = True
        elif cls == "digital_data_input":
            has_data = True
    return {
        "ports": per_port,
        "n_ports": len(ports),
        "has_digital_clock_input": has_clk,
        "has_digital_reset_input": has_rst,
        "has_digital_data_input": has_data,
        "digital_datapath_absent": not (has_clk or has_rst or has_data),
    }


def read_l9_top_ports(project: Path) -> Optional[List[Any]]:
    """Return the L9 top_ports list, or None when no L9 exists."""
    base = project / "phase1"
    if not base.is_dir():
        return None
    for cand in sorted(base.rglob("L9_INTEGRATION_SPEC.json")):
        try:
            d = json.loads(cand.read_text(errors="replace"))
        except (OSError, ValueError):
            continue
        tp = d.get("top_ports")
        if isinstance(tp, list):
            return tp
    return None


def digital_datapath_absent(project: Path) -> Tuple[bool, str, Dict[str, Any]]:
    """(is_absent, reason, evidence). is_absent True ONLY when the L9 top
    interface exposes NO digital clock/reset/data INPUT (all-analog). When L9
    is missing/empty the answer is fail-SAFE False (cannot assert → keep RTL)."""
    ports = read_l9_top_ports(project)
    if not ports:
        return (False, "no L9 top_ports to classify (cannot assert all-analog)",
                {"digital_datapath_absent": False, "n_ports": 0})
    ev = classify_top_ports(ports)
    if ev["digital_datapath_absent"]:
        return (True,
                "all-analog top interface: no digital clock/reset/data INPUT "
                "port — digital RTL steps are N/A (analog track owns silicon)",
                ev)
    present = [k for k in ("has_digital_clock_input", "has_digital_reset_input",
                           "has_digital_data_input") if ev[k]]
    return (False,
            f"digital datapath present ({', '.join(present)}) — keep spec-to-rtl",
            ev)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project.is_dir():
        print(f"error: not a directory: {args.project}", file=sys.stderr)
        return 2
    absent, reason, ev = digital_datapath_absent(args.project.resolve())
    out = {
        "program": "analog_interface_classify",
        "digital_datapath_absent": absent,
        "reason": reason,
        "evidence": ev,
    }
    blob = json.dumps(out, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(blob + "\n")
    print(blob)
    if ev.get("n_ports", 0) == 0:
        return 2
    return 0 if absent else 1


if __name__ == "__main__":
    sys.exit(main())
