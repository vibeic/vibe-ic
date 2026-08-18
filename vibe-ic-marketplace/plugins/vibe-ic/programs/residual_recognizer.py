#!/usr/bin/env python3
"""residual_recognizer.py — routing recognizers for the genuinely-PROSE and VISION
element types (the ones with no clean deterministic extractor). Each detects that
the artifact is PRESENT and routes it: `lead="ai"` (the dual-pass AI pass extracts
the full structured data) or `lead="vision"` (the eda_doc_extract + vision pass).
Where a regex can lift partial deterministic data (requirement bullets, scan-chain
count, assertion count, electrical numbers), it is attached as the baseline.

This closes the catalog: EVERY element type now has a program-side coverage path —
table/parametric types are fully extracted; prose/vision types are recognized and
routed (so nothing is silently uncovered). chip-AGNOSTIC, pure regex.
"""
from __future__ import annotations
import re
from typing import Dict, List


def _prose(text: str) -> List[Dict]:
    out = []
    if re.search(r"functional\s+requirement|the\s+(?:module|design|block|ip)\s+"
                 r"(?:shall|must|should)\b", text, re.I):
        reqs = re.findall(r"(?:shall|must|should)\s+([^.;\n]{5,120})", text, re.I)
        out.append(("functional_requirements", {"lead": "ai", "requirements": reqs[:20]}))
    if re.search(r"protocol\s+state|\b(AXI|APB|AHB|SPI|I2C|I3C|UART|USB|PCIe|JTAG)\d*\b", text, re.I) \
            and re.search(r"\bstate(?:s)?\b|handshake|transaction", text, re.I):
        out.append(("protocol_state_machine", {"lead": "ai"}))
    if re.search(r"reference\s+design|reference\s+implementation|example\s+design|"
                 r"\bIP\s+(?:core|block)\b", text, re.I):
        out.append(("reference_design", {"lead": "ai"}))
    if re.search(r"scan\s+chain|\bBIST\b|\bMBIST\b|\bJTAG\b|boundary\s+scan|\bATPG\b|\bDFT\b", text, re.I):
        d = {"lead": "ai", "jtag": bool(re.search(r"\bJTAG\b", text, re.I))}
        m = re.search(r"(\d+)\s+scan\s+chain", text, re.I)
        if m:
            d["scan_chains"] = int(m.group(1))
        out.append(("dft_scan_spec", d))
    if re.search(r"assert\s+propert|\bSVA\b|\bassertion\b|cover\s+propert", text, re.I):
        out.append(("assertion_property",
                    {"lead": "ai", "assert_count": len(re.findall(r"assert\s+propert", text, re.I))}))
    if re.search(r"\bgain\b|bandwidth|\bPSRR\b|\bCMRR\b|slew\s+rate|\bSNR\b|\bENOB\b|offset\s+voltage",
                 text, re.I) and re.search(r"\b(dB|MHz|GHz|[uµnm]V|kHz)\b", text):
        out.append(("analog_electrical_spec", {"lead": "ai"}))
    if re.search(r"\bOTP\b|\bfuse\b|one[- ]time[- ]programmable|\beFuse\b", text, re.I):
        out.append(("otp_fuse_content", {"lead": "ai"}))
    return out


def _vision(text: str) -> List[Dict]:
    has_figure = re.search(r"!\[[^\]]*\]\([^)]*\)|figure\s+\d+|shown\s+(?:below|above|in\s+fig)|"
                           r"\bdiagram\b|\bschematic\b|illustrated", text, re.I)
    if not has_figure:
        return []
    out = []
    checks = (
        ("state_diagram", r"state\s+diagram|state\s+bubble|bubble\s+diagram"),
        ("timing_diagram", r"timing\s+diagram|waveform\s+(?:diagram|below)"),
        ("block_diagram", r"block\s+diagram|architecture\s+diagram|top[- ]level\s+diagram"),
        ("circuit_schematic", r"\bschematic\b|circuit\s+diagram|gate[- ]level\s+diagram"),
        ("floorplan_spec", r"floorplan|layout\s+(?:diagram|plot)|placement\s+diagram"),
    )
    for etype, pat in checks:
        if re.search(pat, text, re.I):
            out.append((etype, {"lead": "vision"}))
    return out


def recognize_all(text: str) -> List[Dict]:
    return [{"element_type": t, "data": d} for t, d in (_prose(text) + _vision(text))]


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--doc", required=True)
    a = ap.parse_args()
    print(json.dumps(recognize_all(Path(a.doc).read_text(errors="replace")), indent=2))
