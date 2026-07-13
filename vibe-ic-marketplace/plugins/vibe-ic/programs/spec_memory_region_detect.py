#!/usr/bin/env python3
r"""spec_memory_region_detect.py — PROGRAM-FIRST addressable-memory detector.

GENERAL CORE (benchmark-AGNOSTIC). A very common spec shape hides a whole
datapath behind one sentence: a bus (APB / AHB / Wishbone / generic register
interface) decodes to **both** a handful of enumerated control/status registers
**and** a larger addressable **memory** region (SRAM / RAM / buffer). An author
who reads only the "## Register Descriptions" table implements the CSRs and
silently DROPS the memory read/write datapath — the design then fails the first
functional check that writes an address in the non-register range and reads it
back (the CVDP `apb_dsp_unit` extraction-gap: the prose said
*"paddr … for accessing internal CSR registers **and Memory**"* + *"A 1 KB SRAM
module serves as the memory"* + *"Addresses 0x00 to 0x05 are reserved for
configuration registers"*, but the draft implemented only 0x00-0x05).

This is a DETERMINISTIC detector, not an authoring step: it reads the prompt
prose and returns whether an addressable memory region exists **beyond** the
enumerated registers, with the evidence and the two hints an author needs
(reserved CSR range + memory size). The AI-backup author then MUST emit the full
memory datapath for the non-register range. Reads ONLY the supplied prompt —
never any oracle/harness/golden (§4.05).

The rule fires on evidence, not on a bare mention of the word "memory" (a spec
that merely says a register *"holds the memory address of the first operand"*
does NOT get flagged — that is a pointer, not a memory block). It requires either
one STRONG signal (a dedicated `## Memory/SRAM Interface` section, an
"<size> SRAM/RAM … serves as the memory" sentence, or an explicit
"registers **and** Memory" bus-decode phrase) or two independent MEDIUM signals.

Usage:
    from spec_memory_region_detect import detect_memory_region
    r = detect_memory_region(prompt)          # -> dict (see below)

    python3 spec_memory_region_detect.py --prompt @file.md   # CLI, JSON out
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# ── STRONG signals ────────────────────────────────────────────────────────────
# a dedicated section header, e.g. "## SRAM Interface:" / "## Memory Interface"
_SEC_HDR_RE = re.compile(
    r"^\s{0,3}#{1,6}\s*(?:the\s+)?(?:on-?chip\s+)?(SRAM|RAM|Memory|Data\s+Memory)"
    r"\s+Interface\b",
    re.IGNORECASE | re.MULTILINE,
)
# "<size> SRAM/RAM (module) serves as (the) memory" / "acts as the memory"
_SERVES_RE = re.compile(
    r"\b(SRAM|RAM|memory)\b[^.\n]{0,60}?\b(?:serves|acts?|used|functions?)\b"
    r"[^.\n]{0,20}?\bas\b[^.\n]{0,20}?\bmemory\b",
    re.IGNORECASE,
)
# bus decode reaches BOTH: "registers and Memory", "CSR(s) and Memory",
# "CSR and Memory selection", "control registers and the memory"
_AND_MEM_RE = re.compile(
    r"\b(?:CSRs?|registers?|configuration\s+registers?|control(?:/status)?"
    r"\s+registers?)\b[^.\n]{0,24}?\band\b[^.\n]{0,12}?\b(?:the\s+)?"
    r"(?:data\s+)?(?:SRAM|RAM|Memory)\b",
    re.IGNORECASE,
)

# ── MEDIUM signals ────────────────────────────────────────────────────────────
_SRAM_KW_RE = re.compile(r"\b(SRAM|BRAM|dual-?port\s+RAM|single-?port\s+RAM)\b",
                         re.IGNORECASE)
# "reserved for … registers" (implies the rest of the map is memory)
_RESERVED_RE = re.compile(
    r"\breserved\s+for\b[^.\n]{0,40}?\bregisters?\b", re.IGNORECASE)
# an explicit memory size, e.g. "1 KB", "4 KiB", "2 kilobyte", "1024 bytes"
_SIZE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(Ki?B|Mi?B|kilobytes?|megabytes?|bytes?|words?)\b",
    re.IGNORECASE)
# an address RANGE reserved for registers, e.g. "0x00 to 0x05" — tolerant of the
# markdown emphasis/backticks/spaces real prompts wrap the bounds in
# (e.g. "**0x00** to **0x05**").
_EMPH = r"[\s*`_]*"
_RANGE_RE = re.compile(
    r"(0x[0-9A-Fa-f]+)" + _EMPH + r"(?:to|-|–|—|through|\.\.)" + _EMPH
    + r"(0x[0-9A-Fa-f]+)")


def _clip(text: str, m: "re.Match[str]", pad: int = 40) -> str:
    a, b = max(0, m.start() - pad), min(len(text), m.end() + pad)
    return " ".join(text[a:b].split())


def detect_memory_region(prompt: str) -> Dict[str, Any]:
    """Return whether the spec describes an addressable memory region beyond the
    enumerated registers.

    Returns a dict::

        {
          "has_memory_region": bool,
          "confidence": "strong" | "medium" | "none",
          "evidence": [str, ...],        # prose snippets that fired
          "reserved_csr_hint": str|None, # e.g. "0x00 to 0x05" (registers only)
          "mem_size_hint": str|None,     # e.g. "1 KB"
          "requirement": str|None,       # ready-to-inject author directive
        }
    """
    p = prompt or ""
    evidence: List[str] = []

    strong = 0
    for rx, tag in ((_SEC_HDR_RE, "section-header"),
                    (_SERVES_RE, "serves-as-memory"),
                    (_AND_MEM_RE, "registers-and-memory")):
        m = rx.search(p)
        if m:
            strong += 1
            evidence.append(f"[{tag}] {_clip(p, m)}")

    medium = 0
    m = _SRAM_KW_RE.search(p)
    if m:
        medium += 1
        evidence.append(f"[sram-keyword] {_clip(p, m)}")
    m = _RESERVED_RE.search(p)
    if m:
        medium += 1
        evidence.append(f"[reserved-registers] {_clip(p, m)}")

    has = strong >= 1 or medium >= 2
    conf = "strong" if strong >= 1 else ("medium" if medium >= 2 else "none")

    # hints — reserved CSR range + memory size (best-effort, evidence only)
    reserved = None
    rm = _RESERVED_RE.search(p)
    if rm:
        # look for an address range in the same sentence as "reserved for …"
        seg = p[max(0, rm.start() - 60):rm.end() + 60]
        rr = _RANGE_RE.search(seg) or _RANGE_RE.search(p)
        if rr:
            reserved = f"{rr.group(1)} to {rr.group(2)}"
    size = None
    if has:
        # prefer a size that sits near an SRAM/RAM/memory word
        for sm in _SIZE_RE.finditer(p):
            ctx = p[max(0, sm.start() - 30):sm.end() + 30].lower()
            if any(w in ctx for w in ("sram", "ram", "memory")):
                size = f"{sm.group(1)} {sm.group(2)}"
                break

    requirement = None
    if has:
        bits = [
            "The bus decodes to BOTH the enumerated control/status registers AND "
            "an addressable MEMORY region — implement the FULL memory read/write "
            "datapath for the non-register address range, not only the registers."
        ]
        if reserved:
            bits.append(f"Registers occupy {reserved}; every other in-range "
                        f"address is memory (read-back must return what was written).")
        if size:
            bits.append(f"Memory size: {size}.")
        requirement = " ".join(bits)

    return {
        "has_memory_region": has,
        "confidence": conf,
        "evidence": evidence,
        "reserved_csr_hint": reserved,
        "mem_size_hint": size,
        "requirement": requirement,
    }


def main(argv: List[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="prompt text or @file")
    a = ap.parse_args(argv)
    prompt = a.prompt
    if prompt.startswith("@"):
        prompt = Path(prompt[1:]).read_text()
    print(json.dumps(detect_memory_region(prompt), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
