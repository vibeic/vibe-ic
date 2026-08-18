#!/usr/bin/env python3
"""parametric_spec_extractor.py — deterministic baseline extractors for the PROSE
PARAMETRIC element types (the design parameters a spec states in words but in a
regular way): arithmetic primitive, memory, counter, shift register, boolean
expression, sequence detector, number format, PDK target, timing constraints, CRC.

These are not tables, so the AI pass LEADS the understanding; this module supplies
the deterministic BASELINE (the key parameters a regex can lift with confidence) so
the program baseline covers them too. §4.05: each returns None unless it can lift the
defining parameters unambiguously. chip-AGNOSTIC, pure regex.
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional

_W = r"(\d+)\s*[- ]?bit"


def _width(text: str) -> Optional[int]:
    m = re.search(_W, text, re.I)
    return int(m.group(1)) if m else None


def extract_arithmetic(text: str) -> Optional[Dict]:
    m = re.search(r"\b(adder|subtractor|subtracter|multiplier|divider|comparator|"
                  r"accumulator|\bALU\b|multiply[- ]accumulate|\bMAC\b)\b", text, re.I)
    if not m:
        return None
    op = m.group(1).lower()
    signed = bool(re.search(r"\bsigned\b", text, re.I)) and not re.search(r"\bunsigned\b", text, re.I)
    d = {"op": op, "width": _width(text), "signed": signed}
    sat = "saturate" if re.search(r"saturat", text, re.I) else (
        "wrap" if re.search(r"\bwrap\b|overflow", text, re.I) else None)
    if sat:
        d["overflow"] = sat
    return d


def extract_memory(text: str) -> Optional[Dict]:
    m = re.search(r"\b(RAM|ROM|FIFO|LIFO|register file|cache|SDRAM|SRAM|DRAM)\b", text, re.I)
    if not m:
        return None
    depth = re.search(r"(?:depth|deep|entries|locations|words)\D{0,12}?(\d+)", text, re.I) \
        or re.search(r"(\d+)\s*[- ]?(?:entry|word|deep|location)", text, re.I)
    dw = re.search(r"(?:width|wide|data\s*width)\D{0,12}?(\d+)", text, re.I)
    return {"kind": m.group(1).upper(),
            "depth": int(depth.group(1)) if depth else None,
            "width": int(dw.group(1)) if dw else _width(text)}


def extract_counter(text: str) -> Optional[Dict]:
    if not re.search(r"\bcounter\b|\bcount(?:s|ing)?\s+(?:up|down|from|to|modulo)", text, re.I):
        return None
    direction = "down" if re.search(r"\bdown[- ]?count|count\s+down|decrement", text, re.I) else (
        "up_down" if re.search(r"up[/-]?down", text, re.I) else "up")
    mod = re.search(r"\bmod(?:ulo)?[- ]?(\d+)|counts?\s+(?:from\s+0\s+)?to\s+(\d+)", text, re.I)
    return {"width": _width(text), "direction": direction,
            "modulo": int(next(g for g in (mod.groups() if mod else []) if g)) if mod else None}


def extract_shift_register(text: str) -> Optional[Dict]:
    if not re.search(r"shift\s*register|\bLFSR\b|barrel\s*shifter|shifts?\s+(?:left|right)|"
                     r"(?:left|right)[\s-]*shift(?:er)?", text, re.I):
        return None
    direction = "right" if re.search(r"shift\w*\s+right|right[\s-]*shift(?:er)?|MSB[- ]?first",
                                     text, re.I) else "left"
    return {"width": _width(text), "direction": direction,
            "lfsr": bool(re.search(r"\bLFSR\b", text, re.I)),
            "load": bool(re.search(r"\bload\b|parallel\s+load", text, re.I))}


def extract_sequence_detector_v2(text: str) -> Optional[Dict]:
    m = (re.search(r"(?:sequence|pattern)\s+[\"']?([01]{2,})[\"']?", text, re.I)
         or re.search(r"detect(?:s|ing)?\s+(?:the\s+)?(?:sequence|pattern)?\s*[\"']?([01]{3,})", text, re.I)
         or re.search(r"when\s+(?:the\s+)?input\s+is\s+[\"']?([01]{3,})", text, re.I)
         or re.search(r"\b([01]{4,})\b[^.]{0,40}?(?:is\s+detected|detected|\bmatch)", text, re.I))
    if not m:
        return None
    return {"pattern": m.group(1),
            "overlap": bool(re.search(r"overlap", text, re.I)),
            "mealy": bool(re.search(r"\bMealy\b", text, re.I)),
            "moore": bool(re.search(r"\bMoore\b", text, re.I))}


def extract_edge_detector(text: str) -> Optional[Dict]:
    if not re.search(r"edge\s+detect|detect\w*\s+(?:the\s+)?edge|changes?\s+from\s+0\s+to\s+1|"
                     r"rising\s+edge|falling\s+edge", text, re.I):
        return None
    edge = ("rising" if re.search(r"0\s+to\s+1|rising|low\s+to\s+high", text, re.I)
            else "falling" if re.search(r"1\s+to\s+0|falling|high\s+to\s+low", text, re.I) else "any")
    return {"detect": "edge", "edge": edge}


def extract_pulse_detector(text: str) -> Optional[Dict]:
    if not re.search(r"pulse\s+detect|detect\w*\s+(?:a\s+)?pulse", text, re.I):
        return None
    return {"detect": "pulse"}


def extract_clock_generator(text: str) -> Optional[Dict]:
    if not re.search(r"clock\s+generator|generates?\s+(?:a\s+)?(?:periodic\s+)?clock|"
                     r"clock\s+divider|frequency\s+divider|divide[- ]by[- ]\d", text, re.I):
        return None
    d = {"kind": "clock_generator"}
    m = re.search(r"divide[- ]by[- ](\d+)|period\D{0,8}(\d+)", text, re.I)
    if m:
        d["divisor"] = int(next(g for g in m.groups() if g))
    return d


def extract_signal_generator(text: str) -> Optional[Dict]:
    m = re.search(r"\b(triangle|sawtooth|square|sine|ramp)\b\s*wave|waveform\s+generat|"
                  r"signal\s+generator", text, re.I)
    if not m:
        return None
    return {"kind": "signal_generator", "wave": (m.group(1).lower() if m.group(1) else None),
            "width": _width(text)}


def extract_timekeeping(text: str) -> Optional[Dict]:
    if not re.search(r"\bcalendar\b|second\w*\D{0,30}minute|\bRTC\b|real[- ]time\s+clock|"
                     r"stopwatch|hh:mm:ss", text, re.I):
        return None
    fields = [f for f in ("second", "minute", "hour", "day", "month", "year")
              if re.search(rf"\b{f}", text, re.I)]
    return {"kind": "timekeeping", "fields": fields}


def extract_boolean_expression(text: str) -> Optional[Dict]:
    # "out = a & b | ~c"  (one or more assignments)
    rows = []
    for m in re.finditer(r"^\s*(?:assign\s+)?(\w+)\s*=\s*([^;\n]*[~&|^][^;\n]*?)\s*;?\s*$",
                         text, re.M):
        expr = m.group(2).strip()
        if re.search(r"[~&|^]", expr) and len(expr) <= 120:
            rows.append({"output": m.group(1), "expr": expr})
    return {"assignments": rows} if rows else None


def extract_sequence_detector(text: str) -> Optional[Dict]:
    m = re.search(r"(?:sequence|pattern)\s+[\"']?([01]{2,})[\"']?", text, re.I) \
        or re.search(r"detect(?:s|ing)?\s+(?:the\s+)?(?:sequence|pattern)?\s*[\"']?([01]{3,})", text, re.I)
    if not m:
        return None
    return {"pattern": m.group(1),
            "overlap": bool(re.search(r"overlap", text, re.I)),
            "mealy": bool(re.search(r"\bMealy\b", text, re.I)),
            "moore": bool(re.search(r"\bMoore\b", text, re.I))}


def extract_number_format(text: str) -> Optional[Dict]:
    if re.search(r"\bQ(\d+)\.(\d+)\b", text):
        m = re.search(r"\bQ(\d+)\.(\d+)\b", text)
        return {"format": "fixed_point", "int_bits": int(m.group(1)), "frac_bits": int(m.group(2))}
    if re.search(r"IEEE[- ]?754|floating[- ]?point|\bfp32\b|\bfp16\b", text, re.I):
        return {"format": "floating_point"}
    if re.search(r"\bBCD\b|binary[- ]coded[- ]decimal", text, re.I):
        return {"format": "bcd"}
    return None


def extract_pdk_target(text: str) -> Optional[Dict]:
    # an explicit "pdk: <value>" label wins regardless of foundry (IHP SG13G2, XFAB, ...)
    m = re.search(r"\bpdk\b\s*[:=]\s*([A-Za-z0-9][\w .-]{1,30})", text, re.I)
    if m:
        return {"pdk": m.group(1).strip().rstrip(".")}
    m = re.search(r"\b(sky130\w*|gf180\w*|gf130\w*|ihp\w*|sg13\w*|asap7|nangate\w*|"
                  r"freepdk\w*|x?fab\w*|tsmc\w*|(\d+)\s*nm)\b", text, re.I)
    return {"pdk": m.group(1)} if m else None


def extract_timing_constraints(text: str) -> Optional[Dict]:
    period = re.search(r"(?:clock\s+)?period\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*(ns|ps)", text, re.I)
    freq = re.search(r"(\d+(?:\.\d+)?)\s*(MHz|GHz|kHz)", text, re.I)
    if not period and not freq:
        return None
    d = {}
    if period:
        d["period"] = f"{period.group(1)}{period.group(2)}"
    if freq:
        d["frequency"] = f"{freq.group(1)}{freq.group(2)}"
    return d


def extract_crc(text: str) -> Optional[Dict]:
    if not re.search(r"\bCRC\b|cyclic\s+redundancy", text, re.I):
        return None
    poly = re.search(r"poly(?:nomial)?\s*[:=]?\s*(0x[0-9a-f]+)", text, re.I)
    init = re.search(r"init(?:ial)?\s*(?:value)?\s*[:=]?\s*(0x[0-9a-f]+)", text, re.I)
    w = re.search(r"CRC[- ]?(\d+)", text, re.I)
    d = {}
    if poly:
        d["poly"] = poly.group(1)
    if init:
        d["init"] = init.group(1)
    if w:
        d["width"] = int(w.group(1))
    return d or None


# element_type -> extractor (the dual-pass baseline calls all of these)
EXTRACTORS = {
    "arithmetic_spec": extract_arithmetic,
    "memory_spec": extract_memory,
    "counter_spec": extract_counter,
    "shift_register_spec": extract_shift_register,
    "boolean_expression": extract_boolean_expression,
    "sequence_detector": extract_sequence_detector_v2,
    "number_format": extract_number_format,
    "pdk_target": extract_pdk_target,
    "timing_constraints": extract_timing_constraints,
    "crc_checksum_spec": extract_crc,
    "edge_detector": extract_edge_detector,
    "pulse_detector": extract_pulse_detector,
    "clock_generator": extract_clock_generator,
    "signal_generator": extract_signal_generator,
    "timekeeping": extract_timekeeping,
}


def extract_all(text: str) -> List[Dict]:
    """[{element_type, data}] for every parametric type whose defining params are
    present. [] for none."""
    out = []
    for etype, fn in EXTRACTORS.items():
        try:
            d = fn(text)
        except Exception:
            d = None
        if d:
            out.append({"element_type": etype, "data": d})
    return out


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--doc", required=True)
    a = ap.parse_args()
    print(json.dumps(extract_all(Path(a.doc).read_text(errors="replace")), indent=2))
